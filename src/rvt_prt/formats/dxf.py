"""DXF drawings, read and written with ezdxf (`pip install ezdxf`), in the form Revit's own DXF
export takes when family instances are kept as blocks: a block per family type in the family's
own coordinates, an INSERT per instance, layers by category.

Revit's export of a sheet (Snowdon M101, 2025): $INSUNITS 4 (mm). Model space holds each view's
model linework, the views side by side (each a block per link, "<link>_rvt-1-<view name>",
inserted at its own offset); paper space ("Layout1") holds the title block, the sheet's text and
a VIEWPORT per view (centre and size on the sheet, view_center and view_height in model space;
the layout's own viewport is id 1). Each family instance is a block "<family> - <type>-<element
id>-<view name>" (or "-V<n>-" for a variant) in the family's coordinates, nested in the view's
link block. Every entity carries XDATA "REVIT": groups `{ 1070 code, 1000 "<element id>_<value>" }`
with code 1 the element id, 5 its type id, 2 its BuiltInCategory, 3 its subcategory.

Reading: a file with paper space viewports is read as its sheet (inches): paper space as drawn,
and model space through each viewport, clipped to it. Otherwise model space as a view (feet). An
entity's group is "E<element id>", from REVIT's XDATA or ours (RVT_PRT). Blocks are kept in feet
in the family's coordinates, and each instance's block is in the drawing's meta under its group
(drawing.compare_blocks matches instances by element id): the element most of a block's own
entities name (on Revit's nested family INSERTs the XDATA names the link instance instead).

Writing: one view's Drawing in model feet ($INSUNITS 2); each entity with a group carries it as
XDATA, with the group's element, family and category.
"""
import math
import pathlib

from .drawing import Block, Drawing, Insert, Prim, compose, transformed

APPID = "RVT_PRT"
TO_FT = {1: 1 / 12, 2: 1.0, 4: 1 / 304.8, 5: 1 / 30.48, 6: 1 / 0.3048}  # $INSUNITS -> feet
FLAT = 0.005  # flattening distance (feet) for curves without an exact form here


def _revit(e):
    """{code: value} of Revit's XDATA: 1 element id, 5 type id, 2 category, 3 subcategory."""
    out, code = {}, None
    for tag in e.get_xdata("REVIT"):
        if tag.code == 1070:
            code = tag.value
        elif tag.code == 1000 and code is not None:
            out[code] = tag.value.split("_", 1)[-1]
    return out


def _group(e):
    try:
        if e.has_xdata(APPID):
            return next((v for code, v in e.get_xdata(APPID) if code == 1000), "")
        if e.has_xdata("REVIT"):
            eid = _revit(e).get(1)
            return f"E{eid}" if eid else ""
    except Exception:
        pass
    return ""


def _meta(e):
    """A group's labels from REVIT's XDATA: element, type, category and subcategory names."""
    from ..core import categories
    try:
        r = _revit(e) if e.has_xdata("REVIT") else {}
    except Exception:
        return {}
    m = {}
    if 1 in r:
        m["element"] = r[1]
    if 5 in r:
        m["type"] = r[5]
    for code, key in ((2, "category"), (3, "subcategory")):
        if code in r:
            try:
                m[key] = categories.name(int(r[code]))
            except ValueError:
                m[key] = r[code]
    return m


def _colour(e):
    from ezdxf import colors
    try:
        if e.dxf.hasattr("true_color"):
            return tuple(c / 255 for c in e.rgb)
        aci = e.dxf.get("color", 256)
        if 0 < aci < 256:
            return tuple(c / 255 for c in colors.aci2rgb(aci))
    except Exception:
        pass
    return None


def _width(e):
    lw = e.dxf.get("lineweight", -1)
    return lw / 100 / 25.4 * 72 if lw and lw > 0 else 0.0


def _prims(e, k, out, group="", text_pt=None):
    """Primitives for entity e, coordinates times k, appended to out; text heights times
    `text_pt` points per drawing unit (default: k to feet)."""
    text_pt = k * 12 * 72 if text_pt is None else text_pt
    from ezdxf import path as epath
    t = e.dxftype()
    layer = e.dxf.get("layer", "")
    g = _group(e) or group
    col, w = _colour(e), _width(e)
    if t in ("TEXT", "ATTRIB", "MTEXT"):
        text = e.plain_text() if t == "MTEXT" else e.dxf.get("text", "")
        p = e.dxf.insert
        h = e.dxf.get("char_height" if t == "MTEXT" else "height", 0.0)
        out.append(Prim([[(p.x * k, p.y * k)]], layer, g, None, 0.0, False, col, text, h * text_pt,
                        e.dxf.get("rotation", 0.0)))
        return
    if t in ("INSERT", "DIMENSION", "LEADER", "MLEADER", "MULTILEADER", "ACAD_TABLE"):
        try:
            for v in e.virtual_entities():
                _prims(v, k, out, g, text_pt)
        except Exception:
            pass
        if t == "INSERT":
            for a in e.attribs:
                _prims(a, k, out, g, text_pt)
        return
    if t == "HATCH":
        try:
            paths = [[(v.x * k, v.y * k) for v in p.flattening(FLAT / k)] for p in epath.from_hatch(e)]
        except Exception:
            return
        out.append(Prim([p for p in paths if len(p) > 1], layer, g, None, 0.0, True, col or (0.0, 0.0, 0.0)))
        return
    arc = None
    if t == "ARC":
        c, r = e.dxf.center, e.dxf.radius
        a0, a1 = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
        arc = (c.x * k, c.y * k, r * k, a0, a1 if a1 > a0 else a1 + 2 * math.pi)
    elif t == "CIRCLE":
        c, r = e.dxf.center, e.dxf.radius
        arc = (c.x * k, c.y * k, r * k, 0.0, 2 * math.pi)
    try:
        p = epath.make_path(e)
    except (TypeError, ValueError):
        return
    paths = []
    for sp in p.sub_paths():
        pts = [(v.x * k, v.y * k) for v in sp.flattening(FLAT / k)]
        if len(pts) > 1:
            paths.append(pts)
    if paths:
        closed = t in ("CIRCLE", "SOLID", "TRACE", "3DFACE") or bool(getattr(e, "closed", False))
        out.append(Prim(paths, layer, g, col, w, closed, None, arc=arc))


def read(path):
    """A DXF file as a Drawing: its sheet (inches) when paper space has viewports, else its model
    space (feet); named by the file's name."""
    import ezdxf
    from ezdxf import recover
    path = pathlib.Path(path)
    try:
        doc = ezdxf.readfile(str(path))
    except ezdxf.DXFStructureError:
        doc, _auditor = recover.readfile(str(path))
    k = TO_FT.get(doc.header.get("$INSUNITS", 2), 1.0)
    blocks, meta = {}, {}
    for blk in doc.blocks:
        if blk.name.lower().startswith(("*model_space", "*paper_space")):
            continue
        prims, owners = [], {}
        for e in blk:
            _prims(e, k, prims)
            if e.dxftype() != "INSERT":
                g = _group(e)
                if g:
                    owners.setdefault(g, [0, e])[0] += 1
        blocks[blk.name] = Block(blk.name, prims, blk.name.split(" - ")[0])
        if owners:  # a family instance's block: its own entities carry its element id (the INSERT carries the link's)
            g, (_n, e) = max(owners.items(), key=lambda t: t[1][0])
            meta.setdefault(g, {**_meta(e), "family": blk.name.split(" - ")[0], "block": blk.name})
    viewports = [(lay, v) for lay in doc.layouts if lay.name != "Model" for v in lay.query("VIEWPORT") if v.dxf.get("id", 0) != 1]
    if viewports:
        d = _sheet(doc, path.stem, k * 12, [v for _l, v in viewports], viewports[0][0])
        d.blocks = blocks
        for g, m in meta.items():
            d.meta[g] = {**d.meta.get(g, {}), **m}
        return d
    d = Drawing(path.stem, "ft", blocks=blocks, meta=meta)
    for e in doc.modelspace():
        if e.dxftype() == "INSERT" and e.dxf.name in d.blocks:
            m = e.matrix44()  # rows: the block's x axis, y axis, z axis, origin
            a, b = m.get_row(0)[:2]
            c, dd = m.get_row(1)[:2]
            ox, oy = m.get_row(3)[:2]
            g = _group(e) or e.dxf.name
            d.inserts.append(Insert(e.dxf.name, (a, b, c, dd, ox * k, oy * k), g, e.dxf.get("layer", "")))
            for a in e.attribs:
                _prims(a, k, d.prims, g)
        else:
            _prims(e, k, d.prims)
    return d


def _labels(e, d):
    g = _group(e)
    if g and g not in d.meta:
        m = _meta(e)
        if m:
            d.meta[g] = m


def _sheet(doc, name, kin, viewports, layout):
    """The sheet: paper space entities, and model space through each viewport (paper = centre +
    (model - view centre) x height / view height, turned by the view's twist), clipped to it."""
    from .drawing import clip
    d = Drawing(name, "in")
    for e in layout:
        if e.dxftype() != "VIEWPORT":
            _prims(e, kin, d.prims, text_pt=kin * 72)
            _labels(e, d)
    model = []
    for e in doc.modelspace():
        _prims(e, 1.0, model, text_pt=1.0)
        _labels(e, d)
        if e.dxftype() == "INSERT":  # the labels of the elements a view's block holds
            for v in e.virtual_entities():
                _labels(v, d)
                if v.dxftype() == "INSERT":
                    for w in v.virtual_entities():
                        _labels(w, d)
    # (block name, affine block units -> model space, element group) of the family instances: the
    # host's own, placed in model space (its MEP fittings, terminals; the INSERT names the element),
    # and those in each view's link blocks (whose INSERTs name the link's instance, not the element)
    nested = []
    for e in doc.modelspace():
        if e.dxftype() == "INSERT" and e.dxf.name in doc.blocks:
            outer = _affine(e)
            if "_rvt-" not in e.dxf.name:  # not a link's view block ("<link>_rvt-<n>-<view>")
                nested.append((e.dxf.name, outer, _group(e), None))
                continue
            for f in doc.blocks[e.dxf.name]:
                if f.dxftype() == "INSERT":
                    nested.append((f.dxf.name, compose(outer, _affine(f)), "", e.dxf.name))
    k = kin / 12  # drawing units -> feet: blocks are kept in feet
    centres = {}  # block name -> its extents' centre
    # a link's view block is not cut to its view's crop (Snowdon's M101: L1 - Block 37's holds the
    # Plumbing link's water heaters in L1 - Block 35's crop, where the views' shared model space puts
    # them in that viewport too): its instances count in the viewport that holds most of them
    inside, ports = {}, []
    for i, vp in enumerate(viewports):
        s = vp.dxf.height / vp.dxf.view_height if vp.dxf.view_height else 0.0
        if not s:
            continue
        t = math.radians(vp.dxf.get("view_twist_angle", 0.0))
        (cx, cy), (vx, vy) = tuple(vp.dxf.center)[:2], tuple(vp.dxf.view_center_point)[:2]
        a, b = s * math.cos(t) * kin, s * math.sin(t) * kin
        m = (a, b, -b, a, cx * kin - a * vx + b * vy, cy * kin - b * vx - a * vy)
        w, h = vp.dxf.width * kin / 2, vp.dxf.height * kin / 2
        rect = (cx * kin - w, cy * kin - h, cx * kin + w, cy * kin + h)
        here = []
        for block, n, group, src in nested:
            placed = compose(compose(m, n), (1 / k, 0.0, 0.0, 1 / k, 0.0, 0.0))
            x, y = placed[4], placed[5]
            if not (rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]):
                # a tilted instance's block holds its outline in model coordinates, inserted at the
                # model's (or its link's) origin (Snowdon's grilles on ducts' sides, wall lamps):
                # in the view where its outline is
                cx, cy = (c * k for c in _centre(doc, block, centres))  # blocks are kept in feet
                x, y = placed[0] * cx + placed[2] * cy + placed[4], placed[1] * cx + placed[3] * cy + placed[5]
            if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                here.append((block, placed, group, src))
                if src:
                    inside.setdefault(src, {}).setdefault(i, 0)
                    inside[src][i] += 1
        ports.append((i, vp, m, rect, s, here))
    own = {src: max(c, key=c.get) for src, c in inside.items()}
    seen = set()  # Revit's DXF repeats some instances' INSERTs, identical (Snowdon's M103: 129 of 1,475)
    for i, vp, m, rect, s, here in ports:
        for p in model:
            q = clip(transformed(p, m), rect)
            if q is not None:
                q.size = p.size * s * kin * 72 if p.text else q.size
                d.prims.append(q)
        for block, placed, group, src in here:
            key = (block, tuple(round(v, 6) for v in placed))
            if (src is None or own[src] == i) and key not in seen:
                seen.add(key)
                d.placed.append(Insert(block, placed, group))
    return d


def _centre(doc, name, cache):
    """The centre of a block's extents, in its own units."""
    from ezdxf import bbox
    if name not in cache:
        box = bbox.extents(doc.blocks[name])
        cache[name] = tuple(box.center)[:2] if box.has_data else (0.0, 0.0)
    return cache[name]


def _affine(e):
    """An INSERT's 2D affine (a, b, c, d, e, f), block units to its space's units."""
    m = e.matrix44()  # rows: the block's x axis, y axis, z axis, origin
    (a, b), (c, dd), (ox, oy) = m.get_row(0)[:2], m.get_row(1)[:2], m.get_row(3)[:2]
    return a, b, c, dd, ox, oy


def _name(s):
    bad = '<>/\\":;?*|=`'
    return "".join("_" if ch in bad or ord(ch) < 32 else ch for ch in s)[:255] or "_"


def _attribs(p, scale):
    from ezdxf import colors
    a = {"layer": _name(p.layer or "0")}
    if p.colour:
        a["true_color"] = colors.rgb2int(tuple(round(c * 255) for c in p.colour))
    if p.width:
        lw = p.width / 72 * 25.4 * 100
        a["lineweight"] = min((v for v in (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)
                               if v >= lw), default=211)
    return a


def _add(space, p, meta, scale=1.0):
    """Entities for primitive p in a block or layout; each carries its group as XDATA."""
    a = _attribs(p, scale)
    made = []
    if p.text:
        x, y = p.paths[0][0]
        made.append(space.add_text(p.text, height=p.size / 72 / 12, rotation=p.angle, dxfattribs=a).set_placement((x, y)))
    elif p.arc and len(p.paths) == 1:
        cx, cy, r, a0, a1 = p.arc
        if a1 - a0 >= 2 * math.pi - 1e-9:
            made.append(space.add_circle((cx, cy), r, dxfattribs=a))
        else:
            made.append(space.add_arc((cx, cy), r, math.degrees(a0), math.degrees(a1), dxfattribs=a))
    else:
        for path in p.paths:
            if len(path) == 2 and not p.closed:
                made.append(space.add_line(path[0], path[1], dxfattribs=a))
            elif len(path) > 1:
                made.append(space.add_lwpolyline(path, close=p.closed, dxfattribs=a))
    if p.group:
        tags = [(1000, p.group)] + [(1000, f"{k}={v}") for k, v in meta.get(p.group, {}).items()]
        for e in made:
            e.set_xdata(APPID, tags)
    return made


def _rotation_scale(m):
    """(rotation degrees, x scale, y scale) of a 2D affine's linear part when it is a rotation, a
    scale or a mirror of the block's x axis; None otherwise (a shear)."""
    a, b, c, d = m[:4]
    sx = math.hypot(a, b)
    if sx < 1e-12 or abs(a * c + b * d) > 1e-6 * sx * sx:
        return None
    det = a * d - b * c
    return math.degrees(math.atan2(b, a)), sx, det / sx


def write(drawing, path):
    """Write a Drawing (feet) as a DXF R2013 file."""
    import ezdxf
    doc = ezdxf.new("R2013", setup=False)
    doc.header["$INSUNITS"] = 2 if drawing.units == "ft" else 1
    doc.header["$MEASUREMENT"] = 0
    doc.appids.add(APPID)
    layers = {p.layer for p in drawing.prims} | {i.layer for i in drawing.inserts}
    layers |= {p.layer for b in drawing.blocks.values() for p in b.prims}
    for layer in sorted(filter(None, layers)):
        if _name(layer) not in doc.layers:
            doc.layers.add(_name(layer))
    for name, blk in drawing.blocks.items():
        b = doc.blocks.new(name=_name(name))
        for p in blk.prims:
            _add(b, p, {})
    msp = doc.modelspace()
    for p in drawing.prims:
        _add(msp, p, drawing.meta)
    for ins in drawing.inserts:
        rs = _rotation_scale(ins.matrix)
        attribs = {"layer": _name(ins.layer or "0")}
        if rs is None:  # not expressible as an INSERT: the block's lines, placed
            for p in drawing.blocks[ins.block].prims:
                _add(msp, transformed(p, ins.matrix, ins.group, ins.layer or p.layer), drawing.meta)
            continue
        rot, sx, sy = rs
        attribs.update(rotation=rot, xscale=sx, yscale=sy)
        e = msp.add_blockref(_name(ins.block), (ins.matrix[4], ins.matrix[5]), dxfattribs=attribs)
        if ins.group:
            e.set_xdata(APPID, [(1000, ins.group)] + [(1000, f"{k}={v}") for k, v in drawing.meta.get(ins.group, {}).items()])
    doc.saveas(str(path))
