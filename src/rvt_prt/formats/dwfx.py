"""DWFx drawings: DWF's XPS form, a zip (Open Packaging) of XML fixed pages.

Reading (any XPS or DWFx package): the pages in document order, each a sheet Drawing in inches
(XPS units are 1/96 in, y down). A Path's geometry (the abbreviated `Data` syntax, or a
PathGeometry with PathFigure segments) goes through every enclosing RenderTransform; arcs and
Beziers are sampled. A Glyphs element is a text primitive. Canvas clips are not applied.

Revit's DWFx (Snowdon M101, Revit 2025, element properties exported): one FixedPage per sheet
under dwf/documents/<id>/sections/com.autodesk.dwf.ePlot_<id>/, in large integer units under a
scaling RenderTransform; every Canvas and Path is Named "N<guid>_<n>". The section's W2X part
(root `W2X`) gives, in drawing order, a `RenditionSync refName=<Name>` per named element with
the attributes that change there: `Object_Node Number=<node>` (and on the node's first use its
Name), `Layer`, `Line_Weight`. Attributes hold until changed. The object definition part
(`PageObjectDefinition`) lists `Instance nodes=<node> object=<object id>` with the element's
properties; object ids read "<name> [<element id>]" or "<name> [<element id>][<link instance
id>]" for an element of a linked model. A primitive's group is then "E<element id>" (as our
exports and Revit's DXF name it), its layer the object's name (Basic Wall, Door-Passage-Single-
Flush). In other packages a primitive's group is the Name of the nearest named element.

Writing: a sheet Drawing as an XPS package: one FixedPage per sheet, each run of primitives of
one group and layer a Canvas named "C<n>", text as Glyphs in the sheet's own font files (fonts/),
and `Metadata/rvt_prt.xml` with the pages' sheet numbers, each canvas's group and layer (XPS
has no layers) and each group's element, family and category. It is not a full DWF (no DWF
manifest or section descriptors), so Autodesk's viewers may not open it; XPS viewers and
`read` do.
"""
import math
import pathlib
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

from .drawing import Drawing, Prim, apply, compose

XPS = 96.0  # XPS units per inch
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _matrix(s):
    v = [float(x) for x in re.split(r"[\s,]+", s.strip()) if x]
    return tuple(v) if len(v) == 6 else IDENTITY


def _brush(s):
    """'#AARRGGBB' / '#RRGGBB' / 'sc#a,r,g,b' -> rgb 0..1, or None (transparent, resources)."""
    if not s:
        return None
    s = s.strip()
    if s.startswith("sc#"):
        v = [float(x) for x in s[3:].split(",")]
        return tuple(v[-3:]) if (len(v) == 3 or v[0] > 0) else None
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 8:
            if int(h[:2], 16) == 0:
                return None
            h = h[2:]
        if len(h) == 6:
            return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return None


_TOKEN = re.compile(r"[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _arc(p0, rx, ry, phi, large, sweep, p1, n=16):
    """Points of an elliptical arc segment (the SVG / XPS endpoint form), p0 excluded."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    cp, sp = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cx1, cy1 = co * rx * y1 / ry, -co * ry * x1 / rx
    cx = cp * cx1 - sp * cy1 + (p0[0] + p1[0]) / 2
    cy = sp * cx1 + cp * cy1 + (p0[1] + p1[1]) / 2
    ang = lambda ux, uy: math.atan2(uy, ux)
    t0 = ang((x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((-x1 - cx1) / rx, (-y1 - cy1) / ry) - t0
    if sweep and dt < 0:
        dt += 2 * math.pi
    elif not sweep and dt > 0:
        dt -= 2 * math.pi
    n = max(2, int(abs(dt) / (math.pi / 32)))
    out = []
    for i in range(1, n + 1):
        t = t0 + dt * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cp * x - sp * y + cx, sp * x + cp * y + cy))
    out[-1] = p1
    return out


def _bezier(p0, p1, p2, p3, n=12):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def parse_data(s):
    """XPS abbreviated geometry -> ([[points]], closed?) in the path's own coordinates."""
    toks = _TOKEN.findall(s)
    paths, cur, closed = [], None, False
    pos, start, cmd, i = (0.0, 0.0), (0.0, 0.0), None, 0
    last_ctrl = None
    num = lambda j: float(toks[j])

    def begin(p):
        nonlocal cur
        cur = [p]
        paths.append(cur)

    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(cur[0])
                    closed = True
                pos, cur = start, None
                continue
            if cmd == "F":
                i += 1
                continue
        rel = cmd.islower()
        c = cmd.upper()
        off = pos if rel else (0.0, 0.0)
        if c == "M":
            pos = start = (off[0] + num(i), off[1] + num(i + 1))
            i += 2
            begin(pos)
            cmd = "l" if rel else "L"
            continue
        if cur is None:
            begin(pos)
        if c == "L":
            pos = (off[0] + num(i), off[1] + num(i + 1))
            i += 2
            cur.append(pos)
        elif c == "H":
            pos = ((pos[0] if rel else 0.0) + num(i), pos[1])
            i += 1
            cur.append(pos)
        elif c == "V":
            pos = (pos[0], (pos[1] if rel else 0.0) + num(i))
            i += 1
            cur.append(pos)
        elif c == "C":
            p1 = (off[0] + num(i), off[1] + num(i + 1))
            p2 = (off[0] + num(i + 2), off[1] + num(i + 3))
            p3 = (off[0] + num(i + 4), off[1] + num(i + 5))
            i += 6
            cur.extend(_bezier(pos, p1, p2, p3))
            pos, last_ctrl = p3, p2
            continue
        elif c == "S":
            p1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl else pos
            p2 = (off[0] + num(i), off[1] + num(i + 1))
            p3 = (off[0] + num(i + 2), off[1] + num(i + 3))
            i += 4
            cur.extend(_bezier(pos, p1, p2, p3))
            pos, last_ctrl = p3, p2
            continue
        elif c == "Q":
            q = (off[0] + num(i), off[1] + num(i + 1))
            p3 = (off[0] + num(i + 2), off[1] + num(i + 3))
            i += 4
            p1 = (pos[0] + 2 / 3 * (q[0] - pos[0]), pos[1] + 2 / 3 * (q[1] - pos[1]))
            p2 = (p3[0] + 2 / 3 * (q[0] - p3[0]), p3[1] + 2 / 3 * (q[1] - p3[1]))
            cur.extend(_bezier(pos, p1, p2, p3))
            pos = p3
        elif c == "A":
            rx, ry, phi, large, sweep = num(i), num(i + 1), num(i + 2), int(num(i + 3)), int(num(i + 4))
            p1 = (off[0] + num(i + 5), off[1] + num(i + 6))
            i += 7
            cur.extend(_arc(pos, rx, ry, phi, large, sweep, p1))
            pos = p1
        else:
            i += 1
        last_ctrl = None
    return [p for p in paths if len(p) > 1], closed


def _figures(geom):
    """A PathGeometry element's figures -> ([[points]], closed?)."""
    paths, closed = [], False
    if geom.get("Figures"):
        p, c = parse_data(geom.get("Figures"))
        paths += p
        closed |= c
    for fig in geom:
        if _local(fig.tag) != "PathFigure":
            continue
        pos = tuple(float(x) for x in fig.get("StartPoint", "0,0").split(","))
        pts = [pos]
        for seg in fig:
            kind = _local(seg.tag)
            nums = [float(x) for x in re.split(r"[\s,]+", seg.get("Points", seg.get("Point", "")).strip()) if x]
            ps = list(zip(nums[0::2], nums[1::2]))
            if kind == "PolyLineSegment":
                pts += ps
            elif kind == "PolyBezierSegment":
                for j in range(0, len(ps) - 2, 3):
                    pts += _bezier(pts[-1], ps[j], ps[j + 1], ps[j + 2])
            elif kind == "PolyQuadraticBezierSegment":
                for j in range(0, len(ps) - 1, 2):
                    q, p3 = ps[j], ps[j + 1]
                    p0 = pts[-1]
                    pts += _bezier(p0, (p0[0] + 2 / 3 * (q[0] - p0[0]), p0[1] + 2 / 3 * (q[1] - p0[1])),
                                   (p3[0] + 2 / 3 * (q[0] - p3[0]), p3[1] + 2 / 3 * (q[1] - p3[1])), p3)
            elif kind == "ArcSegment" and ps:
                rx, ry = (float(x) for x in seg.get("Size", "0,0").split(","))
                pts += _arc(pts[-1], rx, ry, float(seg.get("RotationAngle", 0)), seg.get("IsLargeArc") == "true",
                            seg.get("SweepDirection") == "Clockwise", ps[0])
        if fig.get("IsClosed") == "true":
            pts.append(pts[0])
            closed = True
        if len(pts) > 1:
            paths.append(pts)
    m = _matrix(geom.get("Transform")) if geom.get("Transform") else None
    if m:
        paths = [[apply(m, x, y) for x, y in p] for p in paths]
    return paths, closed


def _own_transform(el):
    if el.get("RenderTransform") and not el.get("RenderTransform").startswith("{"):
        return _matrix(el.get("RenderTransform"))
    for child in el:
        if _local(child.tag).endswith(".RenderTransform"):
            mt = next(iter(child), None)
            if mt is not None and mt.get("Matrix"):
                return _matrix(mt.get("Matrix"))
    return IDENTITY


def _page(root, name, sync, objects):
    """A FixedPage element as a Drawing in inches, y up. `sync` maps element Names to W2X object
    nodes, `objects` nodes (or our group names) to {"object", property: value}."""
    W, H = float(root.get("Width", 0)), float(root.get("Height", 0))
    d = Drawing(name, "in", (W / XPS, H / XPS))
    to_sheet = (1 / XPS, 0.0, 0.0, -1 / XPS, 0.0, H / XPS)

    def owner(el, group):
        n = el.get("Name")
        if not n:
            return group
        node = sync.get(n)
        return f"#{node}" if node is not None else n

    def walk(el, m, group):
        kind = _local(el.tag)
        m = compose(m, _own_transform(el))
        group = owner(el, group)
        if kind == "Path":
            data = el.get("Data")
            if data and not data.startswith("{"):
                paths, closed = parse_data(data)
            else:
                paths, closed = [], False
                for child in el:
                    if _local(child.tag) == "Path.Data":
                        for g in child:
                            if _local(g.tag) == "PathGeometry":
                                p, c = _figures(g)
                                paths += p
                                closed |= c
            if paths:
                mm = compose(to_sheet, m)
                scale = math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or 1.0
                d.prims.append(Prim([[apply(mm, x, y) for x, y in p] for p in paths], "", group,
                                    _brush(el.get("Stroke")), float(el.get("StrokeThickness", 0)) * scale * 72 / XPS,
                                    closed, _brush(el.get("Fill"))))
        elif kind == "Glyphs":
            text = el.get("UnicodeString", "").removeprefix("{}")
            if text.strip():
                ox, oy = float(el.get("OriginX", 0)), float(el.get("OriginY", 0))
                mm = compose(to_sheet, m)
                scale = math.hypot(m[0], m[1]) or 1.0
                size = float(el.get("FontRenderingEmSize", 0)) * scale * 72 / XPS
                angle = math.degrees(math.atan2(-m[1], m[0]))
                font = pathlib.PurePosixPath(el.get("FontUri", "")).stem
                d.prims.append(Prim([[apply(mm, ox, oy)]], "text", group, None, 0.0, False, _brush(el.get("Fill")),
                                    text, size, angle, font))
        for child in el:
            if not _local(child.tag).startswith(kind + "."):
                walk(child, m, group)

    walk(root, IDENTITY, "")
    groups = {}
    for p in d.prims:
        if not p.group.startswith("#"):
            continue
        if p.group not in groups:
            obj = objects.get(p.group[1:], {})
            ids = re.findall(r"\[(-?\d+)\]", obj.get("object", ""))
            g = f"E{ids[0]}" if ids else p.group
            groups[p.group] = (g, obj.get("object", "").split(" [")[0])
            if obj and g not in d.meta:
                d.meta[g] = {"element": ids[0] if ids else "", **obj}
        p.group, layer = groups[p.group]
        p.layer = layer if p.layer in ("", "text") and layer else p.layer
    return d


def _resolve(base, target):
    return posixpath.normpath(target.lstrip("/")) if target.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


def _page_parts(z):
    """Fixed page part names in document order: .rels -> sequence -> documents -> pages."""
    names = set(z.namelist())
    pages = []
    seq = None
    if "_rels/.rels" in names:
        for r in ET.fromstring(z.read("_rels/.rels")):
            if r.get("Type", "").endswith("/fixedrepresentation"):
                seq = _resolve("", r.get("Target", ""))
    seqs = [seq] if seq in names else [n for n in names if n.lower().endswith(".fdseq")]
    for s in seqs:
        for ref in ET.fromstring(z.read(s)):
            doc = _resolve(s, ref.get("Source", ""))
            if doc in names:
                for pc in ET.fromstring(z.read(doc)):
                    if _local(pc.tag) == "PageContent":
                        pages.append(_resolve(doc, pc.get("Source", "")))
    return [p for p in pages if p in names] or sorted(n for n in names if n.lower().endswith(".fpage"))


KEEP = ("Category", "Family", "Type", "Family and Type")  # element properties kept as labels


def _dwf_parts(z):
    """(sync, objects): {element Name: object node number} from W2X parts, attributes carried
    forward in drawing order; {node number: {"object": object id, property: value}} from object
    definition parts (their Instance elements)."""
    sync, objects = {}, {}
    for n in z.namelist():
        if not n.lower().endswith(".xml") or "metadata/rvt_prt.xml" in n.lower():
            continue
        head = z.open(n).read(200)
        if b"<W2X" in head:
            node = None
            for rs in ET.fromstring(z.read(n)).iter():
                if _local(rs.tag) != "RenditionSync":
                    continue
                for a in rs:
                    if _local(a.tag) == "Object_Node":
                        node = a.get("Number", node)
                if node is not None:
                    sync[rs.get("refName")] = node
        elif b"ObjectDefinition" in head:
            for el in ET.fromstring(z.read(n)).iter():
                if _local(el.tag) == "Instance" and el.get("object"):
                    props = {p.get("name"): p.get("value") for p in el.iter()
                             if _local(p.tag) == "Property" and p.get("name") in KEEP}
                    for node in (el.get("nodes") or "").split():
                        objects[node] = {"object": el.get("object"), **props}
    return sync, objects


def read(path):
    """[Drawing] per fixed page; named by our metadata's sheet numbers, else `<file>-<page>`."""
    path = pathlib.Path(path)
    with zipfile.ZipFile(path) as z:
        names, groups, canvases = {}, {}, {}
        meta = next((n for n in z.namelist() if n.lower().endswith("metadata/rvt_prt.xml")), None)
        if meta:
            root = ET.fromstring(z.read(meta))
            names = {int(p.get("n")): p.get("name") for p in root.iter("Page")}
            groups = {g.get("name"): {k: v for k, v in g.attrib.items() if k != "name"} for g in root.iter("Group")}
            canvases = {c.get("name"): (c.get("group", ""), c.get("layer", "")) for c in root.iter("Canvas")}
        sync, objects = _dwf_parts(z)
        parts = _page_parts(z)
        out = []
        for i, part in enumerate(parts):
            name = names.get(i + 1) or (path.stem if len(parts) == 1 else f"{path.stem}-{i + 1}")
            d = _page(ET.fromstring(z.read(part)), name, sync, objects)
            for p in d.prims:
                if p.group in canvases:
                    p.group, layer = canvases[p.group]
                    p.layer = layer or p.layer
            d.meta = {g: m for g, m in groups.items()} if canvases else d.meta
            out.append(d)
        return out


# ---------------------------------------------------------------------------------- writing

def _hex(rgb, alpha=255):
    return "#%02X%02X%02X%02X" % ((alpha,) + tuple(max(0, min(255, round(c * 255))) for c in rgb))


def _font_file(font):
    """Our font file for a PDF span's font name (ArialMT, ABCDEF+Arial-BoldMT, TrebuchetMS-Italic)."""
    from ..model import fonts
    low = font.lower().split("+")[-1]
    squeezed = low.replace(" ", "").replace("-", "")
    family = ("Trebuchet MS" if "trebuc" in low else "Arial Narrow" if "narrow" in low
              else "Noto Sans CJK JP" if "notosanscjk" in squeezed
              else fonts.BUILTIN_CJK if "droidsansfallback" in squeezed else "Arial")  # fonts.FALLBACKS
    return fonts.file_for((family, "bold" in low, "italic" in low or "oblique" in low))


def _path_data(p, H):
    out = []
    for path in p.paths:
        pts = [(x * XPS, (H - y) * XPS) for x, y in path]
        out.append("M %.2f,%.2f L " % pts[0] + " ".join("%.2f,%.2f" % q for q in pts[1:]) + (" Z" if p.closed else ""))
    return " ".join(out)


def write(drawings, path):
    """Write sheet Drawings (inches) as an XPS / DWFx package."""
    path = pathlib.Path(path)
    font_parts = {}  # font file -> part name
    pages, canvases = [], []
    for d in drawings:
        W, H = d.size
        body, used = [], set()
        group = None
        for p in d.prims:
            if (p.group, p.layer) != group:
                if group:
                    body.append("</Canvas>")
                group = (p.group, p.layer)
                canvases.append(group)
                body.append(f'<Canvas Name="C{len(canvases)}">')
            if p.text:
                f = _font_file(p.font or "")
                if not f:
                    continue
                part = font_parts.setdefault(f, f"Resources/Fonts/{len(font_parts) + 1}_{pathlib.Path(f).name}")
                used.add(part)
                x, y = p.paths[0][0]
                a = math.radians(p.angle)
                text = ("{}" + p.text) if p.text.startswith("{") else p.text
                body.append(f'<Glyphs OriginX="0" OriginY="0" FontRenderingEmSize="{p.size * XPS / 72:.3f}" '
                            f'FontUri="/{part}" UnicodeString={quoteattr(text)} Fill="{_hex(p.fill or (0, 0, 0))}" '
                            f'RenderTransform="{math.cos(a):.6f},{-math.sin(a):.6f},{math.sin(a):.6f},{math.cos(a):.6f},'
                            f'{x * XPS:.2f},{(H - y) * XPS:.2f}"/>')
                continue
            attrs = [f'Data="{_path_data(p, H)}"']
            if p.colour:
                attrs.append(f'Stroke="{_hex(p.colour)}" StrokeThickness="{max(p.width, 0.1) * XPS / 72:.3f}" '
                             'StrokeLineJoin="Round" StrokeStartLineCap="Round" StrokeEndLineCap="Round"')
            if p.fill and p.closed:
                attrs.append(f'Fill="{_hex(p.fill)}"')
            if len(attrs) > 1:
                body.append("<Path " + " ".join(attrs) + "/>")
        if group:
            body.append("</Canvas>")
        page = (f'<FixedPage xmlns="http://schemas.microsoft.com/xps/2005/06" Width="{W * XPS:.2f}" '
                f'Height="{H * XPS:.2f}" xml:lang="en-US">' + "".join(body) + "</FixedPage>")
        pages.append((page, used))
    rel = "http://schemas.microsoft.com/xps/2005/06/required-resource"
    meta = ['<RvtPrt>'] + [f'<Page n="{i + 1}" name={quoteattr(d.name)}/>' for i, d in enumerate(drawings)]
    meta += [f'<Canvas name="C{i + 1}" group={quoteattr(g)} layer={quoteattr(lay)}/>' for i, (g, lay) in enumerate(canvases)]
    seen = set()
    for d in drawings:
        for g, m in d.meta.items():
            if g not in seen:
                seen.add(g)
                meta.append(f'<Group name={quoteattr(g)} ' + " ".join(f"{k}={quoteattr(str(v))}" for k, v in m.items()) + "/>")
    meta.append("</RvtPrt>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="fdseq" ContentType="application/vnd.ms-package.xps-fixeddocumentsequence+xml"/>'
                   '<Default Extension="fdoc" ContentType="application/vnd.ms-package.xps-fixeddocument+xml"/>'
                   '<Default Extension="fpage" ContentType="application/vnd.ms-package.xps-fixedpage+xml"/>'
                   '<Default Extension="ttf" ContentType="application/vnd.ms-opentype"/>'
                   '<Default Extension="TTF" ContentType="application/vnd.ms-opentype"/>'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="R0" Type="http://schemas.microsoft.com/xps/2005/06/fixedrepresentation" '
                   'Target="/FixedDocumentSequence.fdseq"/></Relationships>')
        z.writestr("FixedDocumentSequence.fdseq",
                   '<FixedDocumentSequence xmlns="http://schemas.microsoft.com/xps/2005/06">'
                   '<DocumentReference Source="/Documents/1/FixedDocument.fdoc"/></FixedDocumentSequence>')
        z.writestr("Documents/1/FixedDocument.fdoc",
                   '<FixedDocument xmlns="http://schemas.microsoft.com/xps/2005/06">'
                   + "".join(f'<PageContent Source="/Documents/1/Pages/{i + 1}.fpage"/>' for i in range(len(pages)))
                   + "</FixedDocument>")
        for i, (page, used) in enumerate(pages):
            z.writestr(f"Documents/1/Pages/{i + 1}.fpage", page)
            if used:
                z.writestr(f"Documents/1/Pages/_rels/{i + 1}.fpage.rels",
                           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           + "".join(f'<Relationship Id="F{j}" Type="{rel}" Target="/{u}"/>' for j, u in enumerate(sorted(used)))
                           + "</Relationships>")
        for f, part in font_parts.items():
            z.write(f, part)
        z.writestr("Documents/1/Metadata/rvt_prt.xml", "".join(meta))
