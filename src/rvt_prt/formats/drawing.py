"""Drawings as plain primitives, the one form every format is read into and written from, so our
output and Revit's own exports (PDF, DXF, DWFx) can be compared line for line.

A Drawing is a sheet (units "in": paper inches, y up, origin at the sheet's lower left) or a view
(units "ft": model feet, the model's internal coordinates). A Prim is a set of polylines sharing a
style and an owner: `group` names the element or block that drew it ("" when the format does not
say), `layer` its category or layer. Arcs are sampled; `arc` keeps the exact arc when one is known.
Text is a Prim with `text` set and its baseline origin as its only point.

Blocks hold geometry in their own coordinates (a family type's symbol); an Insert places a block
with a 2D affine (a, b, c, d, e, f): x' = a x + c y + e, y' = b x + d y + f. `flat()` expands the
inserts, each of its primitives taking the insert's group.
"""
import math
import pathlib
from dataclasses import dataclass, field

import numpy as np

from .. import pdf


@dataclass
class Prim:
    paths: list  # [[(x, y), ...]]
    layer: str = ""
    group: str = ""
    colour: tuple | None = None  # stroke rgb 0..1
    width: float = 0.0  # line weight (points)
    closed: bool = False
    fill: tuple | None = None  # fill rgb 0..1
    text: str = ""
    size: float = 0.0  # text height (points)
    angle: float = 0.0  # text direction (degrees, anticlockwise)
    font: str = ""
    arc: tuple | None = None  # (cx, cy, r, a0, a1) radians, anticlockwise from a0 to a1


@dataclass
class Block:
    name: str
    prims: list
    family: str = ""


@dataclass
class Insert:
    block: str
    matrix: tuple  # (a, b, c, d, e, f)
    group: str = ""
    layer: str = ""


@dataclass
class Drawing:
    name: str  # the sheet number, or the view's name
    units: str  # "in" or "ft"
    size: tuple | None = None  # (width, height) of a sheet
    prims: list = field(default_factory=list)
    blocks: dict = field(default_factory=dict)  # {name: Block}
    inserts: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)  # {group: {"element": id, "family": ..., "category": ...}}
    placed: list = field(default_factory=list)  # [Insert]: family instances already drawn in prims, placed on the sheet (not expanded by flat)
    placement: tuple | None = None  # a view's affine from model feet to its sheet's inches
    crop: tuple | None = None  # a view's crop on its sheet (x0, y0, x1, y1), inches: what it shows

    def flat(self):
        """Every primitive in the drawing's coordinates, inserts expanded."""
        out = list(self.prims)
        for ins in self.inserts:
            blk = self.blocks.get(ins.block)
            if blk is None:
                continue
            for p in blk.prims:
                out.append(transformed(p, ins.matrix, ins.group or p.group, ins.layer or p.layer))
        return out


def apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def inverse(m):
    a, b, c, d, e, f = m
    det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return ia, ib, ic, id_, -(ia * e + ic * f), -(ib * e + id_ * f)


def compose(m, n):
    """The affine m after n."""
    a, b, c, d, e, f = m
    return (a * n[0] + c * n[1], b * n[0] + d * n[1], a * n[2] + c * n[3], b * n[2] + d * n[3],
            a * n[4] + c * n[5] + e, b * n[4] + d * n[5] + f)


def transformed(p, m, group=None, layer=None):
    paths = [[apply(m, x, y) for x, y in path] for path in p.paths]
    arc = None
    det = m[0] * m[3] - m[1] * m[2]
    if p.arc and abs(abs(det) - 1) < 1e-6 and abs(m[0] * m[2] + m[1] * m[3]) < 1e-6:
        cx, cy, r, a0, a1 = p.arc
        cx, cy = apply(m, cx, cy)
        turn = math.atan2(m[1], m[0])
        arc = (cx, cy, r, a0 + turn, a1 + turn) if det > 0 else (cx, cy, r, turn - a1, turn - a0)
    return Prim(paths, layer if layer is not None else p.layer, group if group is not None else p.group,
                p.colour, p.width, p.closed, p.fill, p.text, p.size, p.angle, p.font, arc)


def clip(p, rect):
    """Primitive p clipped to rect (x0, y0, x1, y1), or None when nothing is left: a polyline's
    pieces inside (each segment Liang-Barsky clipped), text when its origin is inside."""
    x0, y0, x1, y1 = rect
    if p.text:
        x, y = p.paths[0][0]
        return p if x0 <= x <= x1 and y0 <= y <= y1 else None
    out = []
    for path in p.paths:
        a = np.asarray(path, dtype=np.float64)
        if len(a) == 1:
            if x0 <= a[0, 0] <= x1 and y0 <= a[0, 1] <= y1:
                out.append(path)
            continue
        lo, hi = a.min(0), a.max(0)
        if lo[0] >= x0 and lo[1] >= y0 and hi[0] <= x1 and hi[1] <= y1:
            out.append(path)
            continue
        if hi[0] < x0 or hi[1] < y0 or lo[0] > x1 or lo[1] > y1:
            continue
        p0, d = a[:-1], a[1:] - a[:-1]
        t0, t1 = np.zeros(len(d)), np.ones(len(d))
        ok = np.ones(len(d), bool)
        with np.errstate(divide="ignore", invalid="ignore"):
            for pd, qd in ((-d[:, 0], p0[:, 0] - x0), (d[:, 0], x1 - p0[:, 0]), (-d[:, 1], p0[:, 1] - y0), (d[:, 1], y1 - p0[:, 1])):
                r = qd / pd
                par = pd == 0
                ok &= ~(par & (qd < 0))
                t0 = np.where(~par & (pd < 0), np.maximum(t0, r), t0)
                t1 = np.where(~par & (pd > 0), np.minimum(t1, r), t1)
        ok &= t0 < t1
        for i in np.nonzero(ok)[0]:
            out.append([tuple(p0[i] + t0[i] * d[i]), tuple(p0[i] + t1[i] * d[i])])
    if not out:
        return None
    whole = len(out) == len(p.paths) and all(o is q for o, q in zip(out, p.paths))
    return Prim(out, p.layer, p.group, p.colour, p.width, p.closed and whole, p.fill if whole else None,
                arc=p.arc if whole else None)


def arc_points(cx, cy, r, a0, a1, step=math.pi / 32):
    n = max(2, int(abs(a1 - a0) / step) + 1)
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


# ---------------------------------------------------------------------------------- PDF pages

def _rgb(c):
    if c is None:
        return None
    if isinstance(c, int):
        return ((c >> 16) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255)
    return tuple(c[:3]) if len(c) >= 3 else (c[0],) * 3


def from_page(page, name="", flatness=0.25):
    """A PDF page as a sheet Drawing: each drawn path one Prim (its subpaths, Bezier curves
    flattened to `flatness` points), each text span one text Prim. PDF space is points, y down."""
    H = page.rect.height
    pt = lambda p: (p.x / 72, (H - p.y) / 72)
    d = Drawing(name, "in", (page.rect.width / 72, H / 72))
    for g in pdf.page_drawings(page):
        paths, cur = [], None
        for it in g["items"]:
            op = it[0]
            if op == "l":
                a, b = pt(it[1]), pt(it[2])
                if cur is None or cur[-1] != a:
                    cur = [a]
                    paths.append(cur)
                cur.append(b)
            elif op == "c":
                p0, p1, p2, p3 = it[1:5]
                n = max(2, min(32, int((abs(p3.x - p0.x) + abs(p3.y - p0.y)) / flatness / 8) + 2))
                a = pt(p0)
                if cur is None or cur[-1] != a:
                    cur = [a]
                    paths.append(cur)
                for i in range(1, n + 1):
                    t = i / n
                    u = 1 - t
                    x = u ** 3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t ** 3 * p3.x
                    y = u ** 3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t ** 3 * p3.y
                    cur.append((x / 72, (H - y) / 72))
            elif op == "re":
                r = it[1]
                paths.append([pt(r.tl), pt(r.tr), pt(r.br), pt(r.bl), pt(r.tl)])
                cur = None
            elif op == "qu":
                q = it[1]
                paths.append([pt(q.ul), pt(q.ur), pt(q.lr), pt(q.ll), pt(q.ul)])
                cur = None
        if not paths:
            continue
        stroke = _rgb(g.get("color")) if g.get("type") in ("s", "fs") else None
        fill = _rgb(g.get("fill")) if g.get("type") in ("f", "fs") else None
        d.prims.append(Prim(paths, g.get("layer") or "", "", stroke, g.get("width") or 0.0,
                            bool(g.get("closePath")), fill))
    for block in pdf.page_text_dict(page)["blocks"]:
        for line in block.get("lines", ()):
            angle = math.degrees(math.atan2(-line["dir"][1], line["dir"][0]))
            for s in line["spans"]:
                if s["text"].strip():
                    x, y = s["origin"]
                    d.prims.append(Prim([[(x / 72, (H - y) / 72)]], "text", "", None, 0.0, False, _rgb(s["color"]),
                                        s["text"], s["size"], angle, s["font"]))
    return d


def read_pdf(path):
    """[Drawing] per page, named by the page's bookmark (render.write sets one per sheet), else by
    the file's name when it has one page."""
    doc = pdf.open_document(path)
    toc = pdf.toc(doc)
    stem = pathlib.Path(path).stem
    return [from_page(page, toc.get(i, stem if len(doc) == 1 else f"{stem}-{i + 1}")) for i, page in enumerate(doc)]


def read(path):
    """[Drawing] from a .pdf, .dxf or .dwfx file, or every such file in a directory."""
    path = pathlib.Path(path)
    if path.is_dir():
        return [d for f in sorted(path.iterdir()) if f.suffix.lower() in READERS for d in read(f)]
    suffix = path.suffix.lower()
    if suffix not in READERS:
        raise ValueError(f"cannot read {path.suffix} drawings (have {', '.join(READERS)})")
    return READERS[suffix](path)


def _read_dxf(path):
    from . import dxf
    return [dxf.read(path)]


def _read_dwfx(path):
    from . import dwfx
    return dwfx.read(path)


READERS = {".pdf": read_pdf, ".dxf": _read_dxf, ".dwfx": _read_dwfx}


# ---------------------------------------------------------------------------------- comparison

def samples(prims, step):
    """(points (N, 2), owner index (N,)) along every stroked polyline, at most `step` apart; text
    and fill-only areas (PDF fills, DXF hatches) left out."""
    pts, own = [], []
    for i, p in enumerate(prims):
        if p.text or (p.fill is not None and p.colour is None):
            continue
        for path in p.paths:
            a = np.asarray(path, dtype=np.float64)
            if len(a) == 1:
                pts.append(a)
                own.append(np.full(1, i))
                continue
            for p0, p1 in zip(a[:-1], a[1:]):
                n = max(1, int(math.ceil(math.hypot(*(p1 - p0)) / step)))
                t = np.linspace(0, 1, n + 1)[:, None]
                pts.append(p0 + t * (p1 - p0))
                own.append(np.full(n + 1, i))
    if not pts:
        return np.zeros((0, 2)), np.zeros(0, int)
    return np.vstack(pts), np.concatenate(own)


def _cells(pts, tol):
    c = np.floor(pts / tol).astype(np.int64)
    return (c[:, 0] << 32) + c[:, 1]


def near(a, b, tol):
    """For each point of a: is a point of b within about `tol` (same or neighbouring tol cell)?"""
    if not len(a) or not len(b):
        return np.zeros(len(a), bool)
    have = np.unique(_cells(b, tol))
    c = np.floor(a / tol).astype(np.int64)
    hit = np.zeros(len(a), bool)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            hit |= np.isin(((c[:, 0] + dx) << 32) + (c[:, 1] + dy), have)
    return hit


DEFAULTS = {"in": (0.01, 0.03), "ft": (0.02, 0.05)}  # (sample step, tolerance) per unit


@dataclass
class Score:
    name: str
    recall: float  # share of the reference's linework with ours within tolerance
    precision: float  # share of ours with the reference's within tolerance
    ref_len: float
    our_len: float
    text_recall: float | None = None
    by_layer: list = field(default_factory=list)  # [(layer, side, share, length)]
    by_group: list = field(default_factory=list)  # [(group, side, share, length, label)]


def compare(ref, ours, step=None, tol=None, top=15):
    """Score `ours` against `ref` (same units and coordinates): linework recall and precision, by
    layer and by group (element or block) on each side, the worst groups first; text recall is the
    share of reference words that ours draws within 1 inch (sheets) or 1 foot (views) of the
    reference text holding them (a Revit MTEXT is a paragraph where a PDF has a span per line)."""
    step0, tol0 = DEFAULTS.get(ref.units, DEFAULTS["in"])
    step, tol = step or step0, tol or tol0
    rp, op = ref.flat(), ours.flat()
    ra, ro = samples(rp, step)
    oa, oo = samples(op, step)
    rhit, ohit = near(ra, oa, tol), near(oa, ra, tol)
    s = Score(ref.name, rhit.mean() if len(rhit) else 1.0, ohit.mean() if len(ohit) else 1.0,
              len(ra) * step, len(oa) * step)

    def tally(prims, owner, hit, key, side, out, label=lambda k: ""):
        if not len(owner):
            return
        keys = np.array([key(prims[i]) for i in range(len(prims))], dtype=object)[owner]
        for k in set(keys.tolist()):
            m = keys == k
            out.append((k, side, float(hit[m].mean()), float(m.sum() * step), label(k)))

    layers = []
    tally(rp, ro, rhit, lambda p: p.layer, "ref", layers)
    tally(op, oo, ohit, lambda p: p.layer, "ours", layers)
    s.by_layer = sorted([t[:4] for t in layers], key=lambda t: (t[1], -t[3]))
    groups = []
    label = lambda meta: (lambda g: " ".join(str(v) for v in meta.get(g, {}).values()))
    tally(rp, ro, rhit, lambda p: p.group, "ref", groups, label(ref.meta))
    tally(op, oo, ohit, lambda p: p.group, "ours", groups, label(ours.meta))
    worst = lambda side: sorted((g for g in groups if g[1] == side and g[0] and g[3] >= 10 * step), key=lambda g: (g[2], -g[3]))[:top]
    s.by_group = worst("ref") + worst("ours")
    rt = [(w, p.paths[0][0]) for p in rp if p.text for w in p.text.split()]
    ot = {}
    for p in op:
        for w in p.text.split() if p.text else ():
            ot.setdefault(w, []).append(p.paths[0][0])
    if rt:
        found = sum(any(math.hypot(x - u, y - v) <= 1.0 for u, v in ot.get(w, ())) for w, (x, y) in rt)
        s.text_recall = found / len(rt)
    return s


def compare_blocks(ref, ours, step=None, tol=None):
    """Family symbols in their own coordinates (feet), instance by instance: each of our inserts
    against the block Revit placed for the same element (its group, "E<element id>", in the
    reference's meta), else the reference blocks whose name contains its family's name (letters
    and digits only, any case), the best kept. One row per our block:
    (our block, reference block or None, recall, precision, instances matched by element)."""
    step0, tol0 = DEFAULTS["ft"]
    step, tol = step or step0, tol or tol0
    key = lambda s: "".join(c for c in s.lower() if c.isalnum())
    cache = {}

    def pts(blocks, name):
        if (id(blocks), name) not in cache:
            cache[(id(blocks), name)] = samples(blocks[name].prims, step)[0]
        return cache[(id(blocks), name)]

    def score(oname, rname):
        oa, ra = pts(ours.blocks, oname), pts(ref.blocks, rname)
        if not len(oa) or not len(ra):
            return 0.0, 0.0
        return float(near(ra, oa, tol).mean()), float(near(oa, ra, tol).mean())

    by_element = {}
    for ins in ours.inserts:
        rname = ref.meta.get(ins.group, {}).get("block")
        if rname in ref.blocks:
            by_element.setdefault(ins.block, set()).add(rname)
    out = []
    for name, blk in sorted(ours.blocks.items()):
        if not blk.prims:
            continue
        cands = by_element.get(name)
        matched = len(cands or ())
        if not cands:
            fam = key(blk.family or name)
            cands = {r for r in ref.blocks if fam and fam in key(r)}
        best = (min(cands) if matched else None, 0.0, 0.0)
        for rname in cands:
            rc, pr = score(name, rname)
            if rc + pr > best[1] + best[2]:
                best = (rname, rc, pr)
        out.append((name,) + best + (matched,))
    return out


_NOT_IN_BLOCK_NAMES = str.maketrans({c: "_" for c in '<>/\\":;?*|,=`&()'})


def block_name(name):
    """A family's name as Revit's DXF writes it in block names: the characters a block name may
    not hold, "&" and parentheses, as "_" ("Vanity Cabinet-Double Door & 4 Drawer" -> "... _ 4
    Drawer", 24" -> 24_, "Rectangular Column (Off Center)" -> "... _Off Center_")."""
    return name.translate(_NOT_IN_BLOCK_NAMES)


def compare_instances(ref, ours, step=None, tol=None, at=0.05):
    """Family instances, one by one, in our family's own coordinates (feet). ref: Revit's sheet,
    its family instances in `placed`; ours: a sheet's view Drawings (a Drawing or a list), each
    with its `placement` on the sheet. Each of our instances is paired with the instance Revit
    placed for the same element where Revit's insert names it (the host's own), else with the
    nearest instance Revit placed of the same family (its block named "<family> - ...") whose
    origin is within `at` sheet inches of ours (of several there, a railing's rails all placed at
    their link's origin, the one whose outline's centre is nearest), else whose outline's centre is (a tilted
    instance: Revit's block holds its outline about the model's or its link's origin; ours, about
    its own; a system family's of ours, unnamed, pairs with any family's there), and Revit's
    block is brought into our block's frame through the two placements, so a wrong flip or turn
    scores as a miss. Then the family's blocks left unpaired whose centre is inside our outline's
    box and whose samples lie on ours join its pair (Revit draws a rail, a wall-hung water heater,
    as several blocks). Returns a dict per instance: family,
    group (our element), ours and reference (block names) and the sample counts behind recall
    and precision: ref_n samples of Revit's, ref_hit of them near ours; our_n of ours, our_hit
    near Revit's; of ours, only the samples inside the view's crop (Revit's DXF keeps only those:
    Snowdon's Union Station, the context building, cut to M101's crop). Revit's instances we did not pair have ours None, or "(lines)" when the element
    its block names is one we draw as plain lines (only linked models' family instances:
    family_block); ours Revit has none for, reference None."""
    step0, tol0 = DEFAULTS["ft"]
    step, tol = step or step0, tol or tol0
    ours = [ours] if isinstance(ours, Drawing) else list(ours)
    block_meta = {m["block"]: (g, m) for g, m in ref.meta.items() if "block" in m}
    rcache = {}

    def ref_pts(name):
        if name not in rcache:
            rcache[name] = samples(ref.blocks[name].prims, step)[0] if name in ref.blocks else np.zeros((0, 2))
        return rcache[name]

    mine = {}  # (view, group) -> [family, [block names], [point arrays], sheet placement]
    for vi, d in enumerate(ours):
        if d.placement is None:
            continue
        dcache = {}
        for ins in d.inserts:
            blk = d.blocks.get(ins.block)
            if blk is None or not blk.prims or not ins.group:
                continue
            if ins.block not in dcache:
                dcache[ins.block] = samples(blk.prims, step)[0]
            pm = compose(d.placement, ins.matrix)
            item = mine.setdefault((vi, ins.group), [blk.family or ins.block, [], [], pm, bool(blk.family)])
            if ins.block not in item[1]:
                pts = dcache[ins.block]
                if d.crop is not None and len(pts):
                    x = pm[0] * pts[:, 0] + pm[2] * pts[:, 1] + pm[4]
                    y = pm[1] * pts[:, 0] + pm[3] * pts[:, 1] + pm[5]
                    x0, y0, x1, y1 = d.crop
                    pts = pts[(x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)]
                item[1].append(ins.block)
                item[2].append(pts)
    placed = [(i.block, i.matrix) for i in ref.placed if i.block in ref.blocks]
    groups = [i.group for i in ref.placed if i.block in ref.blocks]
    by_group = {g: j for j, g in enumerate(groups) if g}
    origins = np.array([(m[4], m[5]) for _b, m in placed]).reshape(-1, 2)

    def centre(pts, m):  # the centre of a block's samples' box, on the sheet
        if not len(pts):
            return (np.nan, np.nan)
        c = (pts.min(0) + pts.max(0)) / 2
        return (m[0] * c[0] + m[2] * c[1] + m[4], m[1] * c[0] + m[3] * c[1] + m[5])

    centres = np.array([centre(ref_pts(n), m) for n, m in placed]).reshape(-1, 2)
    used = np.zeros(len(placed), bool)
    rows, pieces = [], []

    def theirs(k, pm):  # Revit's block k in the frame of our block placed at pm
        t = compose(inverse(pm), placed[k][1])
        ra = ref_pts(placed[k][0])
        return np.column_stack([t[0] * ra[:, 0] + t[2] * ra[:, 1] + t[4], t[1] * ra[:, 0] + t[3] * ra[:, 1] + t[5]])

    for (_vi, g), (fam, names, arrs, pm, named) in sorted(mine.items(), key=lambda kv: kv[0]):
        oa = np.vstack(arrs)
        if not len(oa):
            continue  # wholly outside the view's crop
        row = dict(family=fam, group=g, ours=" + ".join(names), reference=None, ref_n=0, ref_hit=0, our_n=len(oa), our_hit=0)
        if len(placed):
            same = np.array([n.startswith(block_name(fam) + " - ") for n, _m in placed])
            j = by_group.get(g)
            if j is None or used[j]:
                dist = np.hypot(origins[:, 0] - pm[4], origins[:, 1] - pm[5])
                ok = (dist <= at) & ~used & same
                cx, cy = centre(oa, pm)
                if ok.sum() > 1:  # several at the origin (a railing's rails, all about their link's): the nearest outline
                    dist = np.where(ok, np.hypot(centres[:, 0] - cx, centres[:, 1] - cy), np.inf)
                elif not ok.any():
                    dist = np.hypot(centres[:, 0] - cx, centres[:, 1] - cy)
                    ok = (dist <= at) & ~used & (same if named else True)
                j = int(np.argmin(np.where(ok, dist, np.inf))) if ok.any() else None

            if j is not None:
                used[j] = True
                ra = theirs(j, pm)
                row.update(reference=placed[j][0], ref_n=len(ra), ref_hit=int(near(ra, oa, tol).sum()),
                           our_hit=int(near(oa, ra, tol).sum()))
                pieces.append((row, oa, pm, ra, same))
        rows.append(row)
    # Revit draws some instances as several blocks (a rail; a wall-hung water heater's pieces, each
    # about its link's origin): those left unpaired of the family whose centre is inside our
    # outline's box and whose samples lie on ours are its pieces
    for row, oa, pm, ra, same in pieces:
        parts = [row["reference"]]
        sx = pm[0] * oa[:, 0] + pm[2] * oa[:, 1] + pm[4]
        sy = pm[1] * oa[:, 0] + pm[3] * oa[:, 1] + pm[5]
        ks = np.nonzero(~used & same & (centres[:, 0] >= sx.min() - at) & (centres[:, 0] <= sx.max() + at)
                        & (centres[:, 1] >= sy.min() - at) & (centres[:, 1] <= sy.max() + at))[0]
        for k in ks:
            rk = theirs(k, pm)
            if len(rk) and near(rk, oa, tol).mean() >= 0.5:
                used[k] = True
                parts.append(placed[k][0])
                ra = np.vstack([ra, rk])
        if len(parts) > 1:
            row.update(reference=" + ".join(parts), ref_n=len(ra), ref_hit=int(near(ra, oa, tol).sum()),
                       our_hit=int(near(oa, ra, tol).sum()))
    drawn = {p.group for d in ours for p in d.prims if p.group}
    for j in np.nonzero(~used)[0]:
        rname = placed[j][0]
        g, m = block_meta.get(rname, ("", {"block": rname}))
        if groups[j]:  # the insert names its element (a shared block's meta is another's)
            g, m = groups[j], {**ref.meta.get(groups[j], {}), "block": rname}
        n = len(ref_pts(rname))
        if n and family_block(m):
            rows.append(dict(family=m.get("family") or rname.split(" - ")[0], group=g,
                             ours="(lines)" if g and g in drawn else None, reference=rname,
                             ref_n=n, ref_hit=0, our_n=0, our_hit=0))
    return rows


def family_block(m):
    """Is a reference block (its meta) a linked model's family instance? Revit's DXF names a
    link's view block "<link>_rvt-<n>-<view>", and the elements of a linked model carry no
    category in their XDATA, while the host's own (MEP fittings, tags, title blocks) do."""
    return "_rvt-" not in m.get("block", "") and not m.get("category")


def merged(drawings):
    """One drawing holding every drawing's blocks, inserts and meta (block names kept)."""
    d = Drawing("all", drawings[0].units if drawings else "ft")
    for x in drawings:
        d.blocks.update(x.blocks)
        d.inserts += x.inserts
        for g, m in x.meta.items():
            d.meta.setdefault(g, m)
    return d


def pair(refs, ours):
    """[(ref, ours)] matched by name (sheet number or view name); else a name containing the
    other's (Revit names exported files "<project> - <view type> - <view name>"); else a sheet
    number drawn as a word on the other drawing; two single drawings pair anyway."""
    key = lambda s: "".join(c for c in s.lower() if c.isalnum())
    words = lambda d: {p.text.strip() for p in d.prims if p.text}
    out, left = [], list(ours)
    for r in refs:
        o = (next((o for o in left if o.name == r.name), None)
             or next((o for o in left if key(o.name) and key(o.name) in key(r.name)), None)
             or next((o for o in left if o.name in words(r) or r.name in words(o)), None))
        if o is not None:
            out.append((r, o))
            left.remove(o)
    if not out and len(refs) == 1 and len(ours) == 1:
        out = [(refs[0], ours[0])]
    return out


def report(s, unit):
    lines = [f"{s.name}: recall {s.recall:6.1%}  precision {s.precision:6.1%}  "
             f"(reference {s.ref_len:,.0f} {unit} of line, ours {s.our_len:,.0f})"
             + (f"  text {s.text_recall:6.1%}" if s.text_recall is not None else "")]
    if s.by_layer:
        lines.append("  by layer (share matched, length):")
        for layer, side, share, ln in s.by_layer:
            lines.append(f"    {side:4} {share:6.1%} {ln:10,.1f}  {layer or '(none)'}")
    if s.by_group:
        lines.append("  worst groups (ref: missed by ours; ours: not in ref):")
        for g, side, share, ln, lab in s.by_group:
            lines.append(f"    {side:4} {share:6.1%} {ln:10,.1f}  {g}  {lab}")
    return "\n".join(lines)
