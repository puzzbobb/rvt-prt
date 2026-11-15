"""Sections and elevations: the model seen along a horizontal view direction, cut at the view
plane and projected behind it to the far clip, with hidden lines removed across elements.

A view's Viewer frame (viewports.viewer_frames) gives its origin and rows right / up / look.
Geometry is moved into the view's frame with the third axis toward the viewer (z' = -depth), so
a section is a plan turned on its side: the view plane is the cut plane (z' = 0) and the far
clip the bottom (z' = -far), and the plan machinery applies unchanged (meshes cut with
linkgeom._cut, family instances from their saved graphics through the view, whose direction
conditions pick their elevation branches). What a plan rarely needs, a section always does:
lines hidden behind other elements. Every projected line is clipped against the triangles of
every solid nearer the viewer (each triangle a depth test besides its three edges: the plane of a
triangle is linear along a segment, so "behind it" is one more half-line in the segment's
parameter), and against the cut sections at the view plane.

Checked against oracle/test02 (four interior elevations, one section at Coarse / Medium / Fine).
"""
import numpy as np

from . import linkgeom


def frame(v):
    """4x4 from model feet to the view's frame (x right, y up, z toward the viewer), or None."""
    if not (v.view_basis and v.view_origin):
        return None
    right, up, look = (np.asarray(b, dtype=float) for b in v.view_basis)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = right, up, -look
    m[:3, 3] = -m[:3, :3] @ np.asarray(v.view_origin, dtype=float)
    return m


def is_section(v):
    """A view looking horizontally (a section or an elevation) with a Viewer frame."""
    return bool(v.view_basis and v.depth and abs(v.view_basis[2][2]) < 1e-6)


def _apply(m, pts):
    return pts @ m[:3, :3].T + m[:3, 3]


def _clip_depth(segs, lo, hi):
    """The parts (m, 2, 3) of 3D segments (n, 2, 3) with lo <= z <= hi."""
    segs = np.asarray(segs, dtype=float).reshape(-1, 2, 3)
    a, b = segs[:, 0], segs[:, 1]
    za, zb = a[:, 2], b[:, 2]
    dz = zb - za
    slope, up = np.abs(dz) > 1e-12, zb > za
    with np.errstate(divide="ignore", invalid="ignore"):
        tlo, thi = (lo - za) / dz, (hi - za) / dz
    # rising, the part from lo to hi; falling, from hi to lo
    t0 = np.where(slope, np.maximum(0.0, np.where(up, tlo, thi)), 0.0)
    t1 = np.where(slope, np.minimum(1.0, np.where(up, thi, tlo)), 1.0)
    keep = ~((np.maximum(za, zb) < lo) | (np.minimum(za, zb) > hi)) & (t1 - t0 > 1e-9)
    a, d, t0, t1 = a[keep], (b - a)[keep], t0[keep, None], t1[keep, None]
    return np.stack([a + t0 * d, a + t1 * d], axis=1)


def lines(v, link_items, hidden=frozenset(), detail=None):
    """(cut, projected) segment lists (linkgeom._Owned, (p, q) in view feet x / y) of a section or
    elevation viewport over every geometry source, hidden lines removed."""
    m = frame(v)
    far = v.depth[1] if v.depth[1] is not None else 1e4
    bottom = -far
    # the crop, across the view: what lies wholly beside it neither shows nor hides anything in
    # it (Golden Nugget's VE-1 keeps 17% of its lines). Elements by their mesh's box, grown by
    # _ELEMENT_MARGIN for the saved graphics' lines beyond it; then lines and triangles each
    crop = getattr(v, "crop", None)
    cut_owned, proj3d, owners3d, occluders, cut_areas = linkgeom._Owned(), [], [], [], []

    def clip_lines(segs):  # lines beyond the view plane: packed, a section has millions
        segs = _clip_depth(segs, bottom, 0.0)
        if crop is not None and len(segs):
            segs = segs[~_beside(*segs[:, :, :2].min(axis=1).T, *segs[:, :, :2].max(axis=1).T, crop, _MARGIN)]
        return segs

    def clip_tris(tris):
        tris = np.asarray(tris, dtype=float).reshape(-1, 3, 3)
        if crop is not None and len(tris):
            tris = tris[~_beside(*tris[:, :, :2].min(axis=1).T, *tris[:, :, :2].max(axis=1).T, crop, _MARGIN)]
        return tris

    def drawn(saved, place, tag, k):
        """A family instance's saved graphics here: [("cut", style, segments) / ("lines", segments,
        style) / ("tris", triangles)], or None."""
        res = saved.plan(tag, place, 0.0, bottom, None, None, (1.0, 0.0, 0.0), detail, cut_only_through=True)
        if res is None:
            return None
        M, groups = res
        parts = []
        for world, _local, c, style in groups:
            if style is not None and getattr(saved, "style_categories", {}).get(style) in hidden:
                continue  # a subcategory the view hides
            style = style if k == 0 else None  # styles are looked up in the first source's file (render.draw_section)
            if c:
                parts.append(("cut", style, world[:, :, :2]))
            else:
                segs = clip_lines(world)
                if len(segs):
                    parts.append(("lines", segs, style))
        for tris in _solids(saved, tag, M, detail):
            tris = clip_tris(tris)
            if len(tris):
                parts.append(("tris", tris))
        return parts

    # pass 1, per element: its box across the view, its nearest point, whether it reaches the view
    # plane, and its large triangles, the covers of elements hidden whole behind it (_cull); its
    # lines and triangles are made in pass 2, only if it shows: an elevation of a whole building
    # is mostly what lies behind its facade (Snowdon Towers' South: 20,034 of 21,704 elements, 1 GB
    # of triangles). A family's saved graphics are drawn for their box (their lines reach beyond
    # its mesh) and again in pass 2, not kept: they are most of it (15,038 of the 21,704)
    elements = []  # (owner, category, item, vv, zlo, zhi, saved graphics' (saved, place, k) or None)
    box, kept, covers = [], [], []  # (x0, y0, x1, y1, nearest z); reaches the view plane; (triangles, element)
    for k, (items, _cut_patterns, symbols, _stairs, _grey) in enumerate(link_items):
        saved = getattr(symbols, "saved", None)
        place = m @ symbols.place if saved is not None else None
        for it in items:
            cat = it.category or linkgeom.IFC_CATEGORY.get(it.cls, 0)
            if it.cls in linkgeom.PLAN_SKIP or cat in hidden or it.cls == "ModelCurve":
                continue
            owner = (it.tag, it.family or "", cat)
            vv = _apply(m, it.verts)
            zlo, zhi = vv[:, 2].min(), vv[:, 2].max()
            if zhi < bottom or zlo > 0:
                continue  # beyond the far clip or in front of the view plane
            if crop is not None and _beside(vv[:, 0].min(), vv[:, 1].min(), vv[:, 0].max(), vv[:, 1].max(), crop, _ELEMENT_MARGIN):
                continue
            reaches = zhi > -_COVER_GAP
            parts = drawn(saved, place, it.tag, k) if saved is not None and it.tag in saved.instances else None
            if parts is not None:
                lo, hi, z = np.full(2, np.inf), np.full(2, -np.inf), -np.inf
                for p in parts:
                    if p[0] == "cut":
                        reaches = True
                        continue
                    pts = p[1].reshape(-1, 3)
                    lo, hi = np.minimum(lo, pts[:, :2].min(axis=0)), np.maximum(hi, pts[:, :2].max(axis=0))
                    z = max(z, pts[:, 2].max())
                    if p[0] == "tris":
                        covers.append((_large(p[1]), len(elements)))
                box.append((*lo, *hi, z))
                kept.append(reaches)
                elements.append((owner, cat, it, vv, zlo, zhi, (saved, place, k)))
                continue
            # a mesh: its lines and triangles within its vertices' box, the part of it in the crop
            # (grown by _MARGIN) all that shows or hides anything there
            x0, y0 = vv[:, :2].min(axis=0)
            x1, y1 = vv[:, :2].max(axis=0)
            if crop is not None:
                x0, y0 = max(x0, crop[0] - _MARGIN), max(y0, crop[1] - _MARGIN)
                x1, y1 = min(x1, crop[2] + _MARGIN), min(y1, crop[3] + _MARGIN)
            box.append((x0, y0, x1, y1, zhi))
            if len(it.faces):
                fa = np.asarray(it.faces).reshape(-1, 3)
                covers.append((_large(clip_tris(vv[fa[_facing(vv, fa)]])), len(elements)))
            kept.append(reaches)
            elements.append((owner, cat, it, vv, zlo, zhi, None))
    gone = _cull(np.array(box, dtype=float).reshape(-1, 5), np.array(kept, dtype=bool), covers)
    del covers
    # pass 2: the elements that show, in order
    walls = []  # [(triangles, element id)] of walls: joined walls' shared faces (_visible)
    for e, (owner, cat, it, vv, zlo, zhi, family) in enumerate(elements):
        if gone[e]:
            continue
        linkgeom._Owned.owner = owner
        if family is not None:
            for part in drawn(family[0], family[1], it.tag, family[2]):
                if part[0] == "cut":
                    linkgeom._Owned.style = part[1]
                    cut_owned.extend(part[2])
                    linkgeom._Owned.style = None
                elif part[0] == "lines":
                    proj3d.append(part[1])
                    owners3d.append(((owner, part[2]), len(part[1])))
                else:
                    occluders.append(part[1])
            continue
        if len(it.faces):
            faces = vv[it.faces]
            tris = clip_tris(faces[_facing(vv, np.asarray(it.faces).reshape(-1, 3))])
            if len(tris):
                occluders.append(tris)
            if cat == WALLS:
                walls.append((faces, it.tag))
        if zlo < 0 < zhi:
            segs = linkgeom._cut(vv, it.faces, 0.0)
            cut_owned.extend(segs)
            area = _area(segs)
            if area is not None:
                cut_areas.append(area)
        edges = linkgeom._sharp_edges(vv, it.faces)
        if len(edges):
            segs = clip_lines(edges)
            if len(segs):
                proj3d.append(segs)
                owners3d.append(((owner, None), len(segs)))
    del elements
    proj3d = np.concatenate(proj3d) if proj3d else np.zeros((0, 2, 3))
    owners3d = [o for o, n in owners3d for _ in range(n)]
    proj = linkgeom._Owned()
    for (owner, style), parts in _visible(proj3d, occluders, cut_areas, owners3d, walls=walls):
        linkgeom._Owned.owner, linkgeom._Owned.style = owner, style
        proj.extend(parts)
    linkgeom._Owned.style = None
    return cut_owned, proj


_COVER_AREA = 1.0  # ft2 across the view: triangles tried as covers (_cull)
_COVER_GAP = 0.01  # feet: a cover's margin around an element, across the view and in front: over _visible's grow, behind and _flush's tol
_COVER_MAX = 2000  # covers unioned for one element at most (_cull)


def _large(tris):
    """Triangles (k, 3, 3) of _COVER_AREA or more across the view: (corners (j, 3, 2), nearest corner's z (j,))."""
    e1, e2 = tris[:, 1, :2] - tris[:, 0, :2], tris[:, 2, :2] - tris[:, 0, :2]
    big = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) >= 2 * _COVER_AREA
    return tris[big, :, :2], tris[big, :, 2].min(axis=1)


def _cull(box, kept, covers):
    """Per element (n,) bool, hidden whole: its box (x0, y0, x1, y1, nearest z) across the view,
    grown by _COVER_GAP, covered by triangles ((corners, z), element) each nearer at its every
    corner than the element's nearest point by _COVER_GAP; elements reaching the view plane (`kept`)
    kept. Its lines are then hidden, and whatever its triangles would hide lies behind the covers
    too, so leaving it out changes nothing (_visible); a cover left out the same way is itself
    behind nearer ones. Nothing but the hairline gaps a nearly edge-on triangle cuts in lines in
    front of it, its plane steep beyond its edge within grow (rst_basic_sample_project's, 0.07 pt
    at most; Snowdon Towers' pergola beams, whole lines). Snowdon Towers' South elevation: 3.1M
    lines and 13M triangles, 0.3M and 1.4M left, its hidden lines 460 s to 42 s."""
    import shapely
    n = len(box)
    gone = np.zeros(n, bool)
    lo, hi, zmax = box[:, :2], box[:, 2:4], box[:, 4]
    cand = np.flatnonzero(~kept & np.isfinite(zmax) & (hi >= lo).all(axis=1))
    covers = [c for c in covers if len(c[0][1])]
    if not covers or not len(cand):
        return gone
    tris = shapely.polygons(np.concatenate([c[0][0] for c in covers]))
    cz = np.concatenate([c[0][1] for c in covers])
    boxes = shapely.box(*(lo[cand] - _COVER_GAP).T, *(hi[cand] + _COVER_GAP).T)
    # a short result (STRtree, short of memory: _Grid) only leaves more elements in
    bi, ti = shapely.STRtree(tris).query(boxes, predicate="intersects")
    near = np.flatnonzero(cz[ti] > zmax[cand[bi]] + _COVER_GAP)
    near = near[np.argsort(bi[near], kind="stable")]
    bi, ti = bi[near], ti[near]
    whole = shapely.covers(tris[ti], boxes[bi])  # one triangle over it
    gone[cand[bi[whole]]] = True
    left = ~gone[cand[bi]]
    bi, ti = bi[left], ti[left]
    # several over it: taken from it one at a time, the largest first, till nothing is left (a
    # union of them all cost 3.7 ms an element, Snowdon Towers' South 15 s)
    area = shapely.area(tris)
    starts = np.flatnonzero(np.r_[True, bi[1:] != bi[:-1]]) if len(bi) else []
    for a, b in zip(starts, np.r_[starts[1:], len(bi)] if len(bi) else []):
        if not 1 < b - a <= _COVER_MAX:
            continue
        rest = boxes[bi[a]]
        for j in ti[a:b][np.argsort(-area[ti[a:b]], kind="stable")]:
            rest = rest.difference(tris[j])
            if rest.is_empty:
                gone[cand[bi[a]]] = True
                break
    return gone


def _solids(saved, tag, M, detail):
    """Triangles (k, 3, 3) in the view of the solids an instance's saved graphics select here."""
    sym = saved.instances[tag][0]
    R = M[:3, :3]
    Ri = np.linalg.inv(R)
    vdir = Ri @ np.array([0.0, 0.0, 1.0])
    vright = Ri @ np.array([1.0, 0.0, 0.0])
    vdir /= np.linalg.norm(vdir)
    vright /= np.linalg.norm(vright)
    out = []
    for _c, kind, _local, i in saved._selected(sym, vdir, vright, detail, None):
        mesh = saved.meshes.get((sym, i)) if kind == "solid" else None
        if mesh is not None and len(mesh[1]):
            v, fa = _apply(M, mesh[0].astype(float)), np.asarray(mesh[1]).reshape(-1, 3)
            out.append(v[fa[_facing(v, fa)]])
    return out


def _facing(v, fa):
    """Faces (k, 3) of a mesh (vertices v in the view) that may hide anything (k,) bool: all, but
    of a closed mesh wound alike (each edge in two faces, once either way) those facing the viewer.
    What lies behind a face of a solid facing away lies behind one of it facing the viewer too:
    half a duct's triangles (Golden Nugget's TGA-RLT-LPH 2: 1.5M of 3M)."""
    keep = np.ones(len(fa), bool)
    if len(fa) < 4:
        return keep
    a, b = fa.reshape(-1).astype(np.int64), fa[:, [1, 2, 0]].reshape(-1).astype(np.int64)
    ab = np.sort(a * len(v) + b)
    if (ab[1:] == ab[:-1]).any() or not np.array_equal(ab, np.sort(b * len(v) + a)):
        return keep  # open, or not wound alike: which side is out unknown
    t = v[fa]
    volume = np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum()
    if abs(volume) < 1e-12:
        return keep
    e1, e2 = t[:, 1, :2] - t[:, 0, :2], t[:, 2, :2] - t[:, 0, :2]
    return (e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) * np.sign(volume) > 0


def _area(segs):
    from shapely.ops import polygonize, unary_union
    a = unary_union(list(polygonize([tuple(map(tuple, np.round(np.asarray(s)[:, :2], 6))) for s in segs])))
    return None if a.is_empty else a


def _triangles(occluders):
    """All occluding triangles (m, 3, 3) not edge-on, counter-clockwise across the view, or None.
    The arrays are taken out of `occluders` as they are copied, the copy made once: a section of
    a whole building has 15M triangles (Golden Nugget's VE-1), 1 GB of them."""
    chunks = [np.asarray(o, dtype=float).reshape(-1, 3, 3) for o in occluders if len(o)]
    occluders.clear()
    turn = []  # per chunk: 0 edge-on, 1 counter-clockwise, -1 clockwise
    for c in chunks:
        e1, e2 = c[:, 1] - c[:, 0], c[:, 2] - c[:, 0]
        a2 = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        turn.append(np.where(np.abs(a2) > 1e-9, np.where(a2 < 0, -1, 1), 0).astype(np.int8))
    total = sum(int(np.count_nonzero(w)) for w in turn)
    if not total:
        return None
    t, i = np.empty((total, 3, 3)), 0
    for k, w in enumerate(turn):
        c, chunks[k] = chunks[k][w != 0], None
        back = w[w != 0] < 0
        c[back] = c[back][:, ::-1]
        t[i:i + len(c)] = c
        i += len(c)
    return t


def _boxes(t, grow, chunk=200_000):
    """Boxes covering triangles (k, 3, 3) across the view, grown by `grow`: (lo (b, 2), hi (b, 2),
    triangle (b,)). One each, but a long thin triangle lying across its box (tessellation's
    slivers: 27% of rst_basic_sample_project's section triangles, in 79% of the pairs their boxes
    gave, of which 8% met at all) as slabs along its length, up to 16, each boxing its part."""
    v = t[:, :, :2]
    lo, hi = v.min(axis=1), v.max(axis=1)
    size = hi - lo
    e1, e2 = v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]
    area = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2
    fill = area / np.maximum(size[:, 0] * size[:, 1], 1e-30)
    k = np.clip(np.floor(0.25 / np.maximum(fill, 1e-9)), 1, 16).astype(np.int64)
    k[size.max(axis=1) < 0.05] = 1  # small already
    one = np.flatnonzero(k == 1)
    out = [(lo[one] - grow, hi[one] + grow, one)]
    split = np.flatnonzero(k > 1)
    for c0 in range(0, len(split), chunk):
        idx = split[c0:c0 + chunk]
        kk = k[idx]
        rows = np.repeat(idx, kk)
        j = np.arange(len(rows)) - np.repeat(np.cumsum(kk) - kk, kk)
        kr = k[rows]
        along = size[rows, 1] > size[rows, 0]  # slabs across the longer side
        V = v[rows]
        X = np.where(along[:, None], V[:, :, 1], V[:, :, 0])
        Y = np.where(along[:, None], V[:, :, 0], V[:, :, 1])
        x0, x1 = X.min(axis=1), X.max(axis=1)
        a = x0 + (x1 - x0) * j / kr
        b = np.where(j == kr - 1, x1, x0 + (x1 - x0) * (j + 1) / kr)
        # the part's extent across: its corners within the slab, its edges at the slab's sides
        ys = [np.where((X >= a[:, None]) & (X <= b[:, None]), Y, np.nan)]
        X1, Y1 = np.roll(X, -1, axis=1), np.roll(Y, -1, axis=1)
        for side in (a, b):
            with np.errstate(divide="ignore", invalid="ignore"):
                f = (side[:, None] - X) / (X1 - X)
            ys.append(np.where((X1 != X) & (f >= 0) & (f <= 1), Y + f * (Y1 - Y), np.nan))
        ys = np.concatenate(ys, axis=1)
        y0, y1 = np.nanmin(ys, axis=1), np.nanmax(ys, axis=1)
        blo = np.where(along[:, None], np.stack([y0, a], axis=1), np.stack([a, y0], axis=1))
        bhi = np.where(along[:, None], np.stack([y1, b], axis=1), np.stack([b, y1], axis=1))
        out.append((blo - grow, bhi + grow, rows))
    return tuple(np.concatenate(z) for z in zip(*out))


class _Grid:
    """Boxes (lo (b, 2), hi (b, 2)) indexed by the cells of a uniform grid they cover, for the
    pairs of boxes meeting a query's (pairs): numpy throughout, so that short of memory it raises.
    shapely's STRtree, there, returned some of the pairs and no error (rst_basic_sample_project's
    S206 at 1.4 GB above its parent: 521,845 of 884,837, its West section's lines left showing)."""
    LIMIT = 4096  # cells: a box or query box covering more is tried against all the others
    CHUNK = 1_000_000  # candidates from the cells tested at a time (pairs)
    SCALE = 2.0  # cell side / the boxes' median size, at most
    ENTRIES = 4_000_000  # (cell, box) entries the cells are made finer up to: few boxes, finer cells

    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi
        size = np.maximum(hi - lo, 0.0).max(axis=1)
        self.origin = lo.min(axis=0)
        extent = max(float((hi.max(axis=0) - self.origin).max()), 1e-9)
        self.cell = max(float(np.median(size)) * self.SCALE, extent / 65536, 1e-9)
        # halved while the entries stay few and the boxes in cells: fewer candidates a query
        # (Snowdon Towers' South, its 2,683 largest triangles in 13 x 13 cells of 30 ft: 10.6 s of pairs)
        span = np.maximum(hi - lo, 0.0)
        while self.cell / 2 >= max(extent / 65536, 1e-9):
            count = (np.floor(span / (self.cell / 2)) + 2).prod(axis=1)
            if count.sum() > self.ENTRIES or (count > self.LIMIT).mean() > 0.001:
                break
            self.cell /= 2
        self.n = int(extent / self.cell) + 2  # cells across, either way: keys ix * n + iy
        c0, c1 = self._cells(lo), self._cells(hi)
        count = (c1 - c0 + 1).prod(axis=1)
        self.big = np.flatnonzero(count > self.LIMIT)
        keys, boxes = self._expand(c0, c1, count, np.flatnonzero(count <= self.LIMIT))
        order = np.argsort(keys, kind="stable")
        self.keys, self.boxes = keys[order], boxes[order]

    def _cells(self, p):
        return np.clip(np.floor((p - self.origin) / self.cell), 0, self.n - 1).astype(np.int64)

    def _expand(self, c0, c1, count, which):
        """(cell keys, box) of every cell each box `which` covers."""
        span = c1[which] - c0[which] + 1
        k = count[which]
        rows = np.repeat(which, k)
        j = np.arange(len(rows)) - np.repeat(np.cumsum(k) - k, k)
        ny = np.repeat(span[:, 1], k)
        ix = c0[rows, 0] + j // ny
        iy = c0[rows, 1] + j % ny
        return ix * self.n + iy, rows.astype(np.int32)

    def pairs(self, qlo, qhi):
        """(query, box) index arrays of each query box (lo, hi (q, 2)) and box whose envelopes meet."""
        c0, c1 = self._cells(qlo), self._cells(qhi)
        count = (c1 - c0 + 1).prod(axis=1)
        small = np.flatnonzero(count <= self.LIMIT)
        keys, qi = self._expand(c0, c1, count, small)
        a = np.searchsorted(self.keys, keys, "left")
        hits = np.searchsorted(self.keys, keys, "right") - a
        ends = np.cumsum(hits)
        out_q, out_b = [], []
        # the cells' candidates CHUNK at a time (a block of 1024 of S206's lines met 20M)
        cuts = np.searchsorted(ends, np.arange(self.CHUNK, int(ends[-1]) if len(ends) else 0, self.CHUNK), "right")
        for e0, e1 in zip(np.concatenate([[0], cuts]), np.concatenate([cuts, [len(keys)]])):
            h = hits[e0:e1]
            if not h.sum():
                continue
            qs = np.repeat(qi[e0:e1], h)
            cell = np.repeat(keys[e0:e1], h)
            bi = self.boxes[np.repeat(a[e0:e1], h) + np.arange(int(h.sum())) - np.repeat(np.cumsum(h) - h, h)]
            m = self._meet(qlo[qs], qhi[qs], bi)
            qs, bi, cell = qs[m], bi[m], cell[m]
            # a pair in each cell both cover: kept in the one holding their meeting box's lower left
            corner = self._cells(np.maximum(qlo[qs], self.lo[bi]))
            keep = corner[:, 0] * self.n + corner[:, 1] == cell
            out_q.append(qs[keep])
            out_b.append(bi[keep].astype(np.int64))
        del keys, a, hits
        # boxes too big for cells, and query boxes too big: every pair tried
        rest = [(np.arange(len(qlo)), self.big)]
        wide = np.flatnonzero(count > self.LIMIT)
        if len(wide):
            rest.append((wide, np.setdiff1d(np.arange(len(self.lo)), self.big)))
        for q, bx in rest:
            step = max(1, 4_000_000 // max(len(q), 1))
            for k0 in range(0, len(bx), step):
                b_ = bx[k0:k0 + step]
                m = ((qlo[q, None, 0] <= self.hi[None, b_, 0]) & (qhi[q, None, 0] >= self.lo[None, b_, 0])
                     & (qlo[q, None, 1] <= self.hi[None, b_, 1]) & (qhi[q, None, 1] >= self.lo[None, b_, 1]))
                qq, bb = np.nonzero(m)
                out_q.append(q[qq])
                out_b.append(b_[bb])
        if not out_q:
            return np.zeros(0, np.int64), np.zeros(0, np.int64)
        return np.concatenate(out_q), np.concatenate(out_b)

    def _meet(self, qlo, qhi, bi):
        lo, hi = self.lo[bi], self.hi[bi]
        return (qlo[:, 0] <= hi[:, 0]) & (qhi[:, 0] >= lo[:, 0]) & (qlo[:, 1] <= hi[:, 1]) & (qhi[:, 1] >= lo[:, 1])


def _edges_planes(t):
    """Triangles' (k, 3, 3) inward edge normals (k, 3, 2) across the view and planes (k, 3), z = a x + b y + c."""
    edge = np.roll(t[:, :, :2], -1, axis=1) - t[:, :, :2]
    n = np.stack([-edge[:, :, 1], edge[:, :, 0]], axis=2)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    # plane through the corners: z = a x + b y + c
    nrm = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    a = -nrm[:, 0] / nrm[:, 2]
    b = -nrm[:, 1] / nrm[:, 2]
    c = t[:, 0, 2] - a * t[:, 0, 0] - b * t[:, 0, 1]
    return n, np.stack([a, b, c], axis=1)


WALLS = -2000011
_MARGIN = 0.01  # feet beyond the crop kept of lines and triangles: over _visible's grow and the drawn crop's clip
_ELEMENT_MARGIN = 1.0  # feet beyond the crop kept of elements, by their mesh's box (lines.crop)


def _beside(x0, y0, x1, y1, crop, margin):
    """Whether boxes (x0, y0, x1, y1), scalars or arrays, lie wholly outside the crop grown by margin."""
    return (x1 < crop[0] - margin) | (x0 > crop[2] + margin) | (y1 < crop[1] - margin) | (y0 > crop[3] + margin)

_SEG_BLOCK = 1024  # segments queried at a time (_visible): pairs cluster, 8192 of rst_basic_sample_project's gave 1.6 GB of them
_PAIR_BLOCK = 250_000  # (segment, triangle) pairs tested at a time: ~100 MB of temporaries
_STRIP = 1_000_000  # triangles indexed at a time (_behind): 15M boxes in one STRtree took 2 GB
_BANDS = (np.inf, 10.0, 0.1, 0.01, 1e-3, 1e-4)  # ft2 across the view: triangles by area, the largest tried first (_visible)


def _flush(seg, tris, grow=2e-3, tol=1e-3):
    """(k, 2) parameter spans of a 3D segment lying in the plane of triangles (within `tol` of
    it, toward the viewer or away) and within them, their outline grown by `grow`: butt-joined
    walls' faces meet flush, their shared edge on both outlines (test02's corners)."""
    t = _triangles([tris])
    if t is None:
        return np.zeros((0, 2))
    n, plane = _edges_planes(t)
    p, d = seg[0], seg[1] - seg[0]
    nd = (n * d[:2]).sum(axis=2)
    c = -grow - (n * (p[:2] - t[:, :, :2])).sum(axis=2)
    pa, pb, pc = plane[:, 0], plane[:, 1], plane[:, 2]
    dd = pa * d[0] + pb * d[1] - d[2]
    off = pa * p[0] + pb * p[1] + pc - p[2]
    # |plane - z| < tol along the segment: two more half-lines in s
    nd = np.concatenate([nd, dd[:, None], -dd[:, None]], axis=1)
    c = np.concatenate([c, (-tol - off)[:, None], (-tol + off)[:, None]], axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = c / nd
    lo = np.maximum(np.where(nd > 0, r, -np.inf).max(axis=1), 0.0)
    hi = np.minimum(np.where(nd < 0, r, np.inf).min(axis=1), 1.0)
    keep = ~((np.abs(nd) <= 1e-15) & (c >= 0)).any(axis=1) & (hi > lo)
    return np.stack([lo[keep], hi[keep]], axis=1)


def _union(si, lo, hi):
    """Spans (segment, lo, hi), 0 <= lo < hi <= 1, merged into each segment's union, by segment.
    Offsetting each segment's by 4 x its index keeps segments apart in one sort and running max."""
    if not len(si):
        return si, lo, hi
    off = si.astype(float) * 4.0
    order = np.lexsort((lo, si))
    si, a, b = si[order], lo[order] + off[order], hi[order] + off[order]
    reach = np.maximum.accumulate(b)
    start = np.ones(len(a), bool)
    start[1:] = a[1:] > reach[:-1]
    first = np.flatnonzero(start)
    last = np.append(first[1:], len(a)) - 1
    return si[first], a[first] - off[order][first], reach[last] - off[order][first]


def _behind(segs, sidx, t, tidx, grow, behind):
    """[(segment, lo, hi)] merged spans of segments segs[sidx] (n, 2, 3) behind triangles t[tidx]
    (_visible). In strips across the view, a few triangles' boxes indexed at a time (by their left
    edges' quantiles), each (segment, triangle) pair whose boxes meet tried in the one strip where
    their meeting box's left edge lies; boxes grown like the outlines, or a line just outside a box
    is never tested against it."""
    hidden = []
    txlo = t[tidx, :, 0].min(axis=1) - grow
    txhi = t[tidx, :, 0].max(axis=1) + grow
    sxlo, sxhi = segs[sidx, :, 0].min(axis=1), segs[sidx, :, 0].max(axis=1)
    cuts = np.quantile(txlo, np.linspace(0, 1, -(-len(tidx) // _STRIP) + 1)[1:-1]) if len(tidx) > _STRIP else []
    edges = np.concatenate([[-np.inf], cuts, [np.inf]])
    for x0, x1 in zip(edges[:-1], edges[1:]):
        tsel = np.flatnonzero((txhi >= x0) & (txlo < x1))
        ssel = np.flatnonzero((sxhi >= x0) & (sxlo < x1))
        if not len(tsel) or not len(ssel):
            continue
        ts, tl = t[tidx[tsel]], txlo[tsel]
        n, plane = _edges_planes(ts)
        blo, bhi, box_tri = _boxes(ts, grow)
        grid = _Grid(blo, bhi)
        del blo, bhi
        # (segment, triangle) pairs a block at a time: each pair costs ~400 bytes of temporaries,
        # and a section of a whole building has millions (rac_advanced_sample_project's: 9.3M, 3 GB at once)
        for b0 in range(0, len(ssel), _SEG_BLOCK):
            block = ssel[b0:b0 + _SEG_BLOCK]
            sb = segs[sidx[block], :, :2]
            qi, bi = grid.pairs(sb.min(axis=1), sb.max(axis=1))
            del sb
            sl, ti_all = block[qi], box_tri[bi]  # a pair once per slab it meets: its spans merge alike
            ref = np.maximum(sxlo[sl], tl[ti_all])
            mine = (ref >= x0) & (ref < x1)
            si_all, ti_all = sidx[sl[mine]], ti_all[mine]
            hits = []
            for k in range(0, len(si_all), _PAIR_BLOCK):
                si, ti = si_all[k:k + _PAIR_BLOCK], ti_all[k:k + _PAIR_BLOCK]
                p, d = segs[si, 0], segs[si, 1] - segs[si, 0]
                # behind the triangle: (a x + b y + c) - z > inset along the segment, linear in s,
                # dd s > dc; tried first, at its ends, a pair nowhere behind left out (the most)
                pa, pb, pc = plane[ti, 0], plane[ti, 1], plane[ti, 2]
                dd = pa * d[:, 0] + pb * d[:, 1] - d[:, 2]
                dc = behind - (pa * p[:, 0] + pb * p[:, 1] + pc - p[:, 2])
                some = dc < np.maximum(dd, 0.0) + 1e-12
                si, ti, p, d, dd, dc = si[some], ti[some], p[some], d[some], dd[some], dc[some]
                tt = ts[ti][:, :, :2]
                nn = n[ti]
                nd = (nn * d[:, None, :2]).sum(axis=2)
                c = -grow - (nn * (p[:, None, :2] - tt)).sum(axis=2)
                del nn, tt
                nd = np.concatenate([nd, dd[:, None]], axis=1)
                c = np.concatenate([c, dc[:, None]], axis=1)
                with np.errstate(divide="ignore", invalid="ignore"):
                    r = c / nd
                lo = np.maximum(np.where(nd > 0, r, -np.inf).max(axis=1), 0.0)
                hi = np.minimum(np.where(nd < 0, r, np.inf).min(axis=1), 1.0)
                keep = ~((np.abs(nd) <= 1e-15) & (c >= 0)).any(axis=1) & (hi > lo)
                hits.append((si[keep], lo[keep], hi[keep]))
            if hits:
                # merged per block: rst_basic_sample_project's sections keep tens of millions of pairs
                hidden.append(_union(*(np.concatenate(a) for a in zip(*hits))))
    return hidden


def _visible(segs, occluders, cut_areas, owners, inset=1e-4, gap=1e-3, behind=1e-3, grow=2e-3, walls=()):
    """[(owner, [(p, q) 2D])]: each 3D segment's parts not behind an occluding triangle nor behind
    a cut section at z = 0. Behind a triangle is more than `behind` further from the viewer and
    within its outline grown by `grow`: a line lying on a nearer face's outline is hidden (that
    outline is drawn): test02's window glass, set in its frame's rebate, whose edges Revit leaves
    out where they meet the frame's inner edges."""
    import shapely
    if not len(segs):
        return []
    t = _triangles(occluders)
    segs = np.asarray(segs, dtype=float)  # (n, 2, 3)
    spans = {}  # {segment: [(lo, hi)]} hidden by joined walls and cut sections
    hidden = []  # (segment, lo, hi) arrays, each segment's spans behind triangles merged
    alive = np.arange(len(segs))  # the segments not hidden whole: the rest draw nothing, whatever else hides them
    if t is not None:
        # the largest triangles first (walls, floors: rst_basic_sample_project's 262 of 10 ft2 or
        # more hid 90% of a section's lines, from 2.8M of its 268M pairs), then smaller ones
        # against the lines still showing: a line hidden whole is hidden whatever else lies there.
        # Down to the finest: a detailed family's 2.4 mm2 triangles (Golden Nugget's ceiling
        # baffles, 3M of them) in one band below 0.1 ft2 met 207k lines in 85M pairs, 138 s; in
        # four, 29M, 55 s
        e1, e2 = t[:, 1, :2] - t[:, 0, :2], t[:, 2, :2] - t[:, 0, :2]
        area = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2
        del e1, e2
        for lo_area, hi_area in zip(_BANDS[1:] + (0.0,), _BANDS):
            tidx = np.flatnonzero((area >= lo_area) & (area < hi_area))
            if not len(tidx) or not len(alive):
                continue
            hidden += _behind(segs, alive, t, tidx, grow, behind)
            if hidden:  # merged, in segment order: a line's spans from several bands and strips
                hidden = [_union(*(np.concatenate(a) for a in zip(*hidden)))]
                hs, hlo, hhi = hidden[0]
                alive = np.setdiff1d(alive, hs[(hlo <= 0.0) & (hhi >= 1.0)], assume_unique=True)
        del t, area
    # joined walls: a wall's edge lying in another wall's face (an end against the face it meets)
    # is not drawn, as Revit cleans up wall joins (test02's elevation corners)
    if len(walls) > 1:
        for j in alive:
            (owner, _style), seg = owners[j], segs[j]
            if not owner or owner[2] != WALLS:
                continue
            lo_s, hi_s = seg.min(axis=0), seg.max(axis=0)
            for tris, tag in walls:
                if tag == owner[0]:
                    continue
                bmin, bmax = tris.reshape(-1, 3).min(axis=0), tris.reshape(-1, 3).max(axis=0)
                if (bmin[:2] > hi_s[:2] + 1e-3).any() or (bmax[:2] < lo_s[:2] - 1e-3).any():
                    continue
                spans.setdefault(j, []).extend(map(tuple, _flush(seg, tris)))
    if cut_areas:
        region = shapely.union_all(cut_areas).buffer(-inset)
        if not region.is_empty:
            for j, g in zip(alive, shapely.intersection(shapely.linestrings(segs[alive, :, :2]), region)):
                if g.is_empty:
                    continue
                d = segs[j, 1, :2] - segs[j, 0, :2]
                L2 = float(d @ d)
                if L2 < 1e-18:
                    continue
                for part in getattr(g, "geoms", [g]):
                    if part.geom_type != "LineString":
                        continue
                    (x0, y0), (x1, y1) = part.coords[0], part.coords[-1]
                    s0 = ((x0 - segs[j, 0, 0]) * d[0] + (y0 - segs[j, 0, 1]) * d[1]) / L2
                    s1 = ((x1 - segs[j, 0, 0]) * d[0] + (y1 - segs[j, 0, 1]) * d[1]) / L2
                    spans.setdefault(j, []).append((min(s0, s1), max(s0, s1)))
    from ..elements.savedgraphics import _uncovered
    first = last = None  # hidden[first[j]:last[j]]: segment j's spans (hidden is in segment order)
    if hidden:
        hs, hlo, hhi = hidden[0]
        first = np.searchsorted(hs, np.arange(len(segs)), "left")
        last = np.searchsorted(hs, np.arange(len(segs)), "right")
    out = []
    for j in alive:
        seg, owner = segs[j], owners[j]
        sp = spans.get(j, [])
        if first is not None and last[j] > first[j]:
            a, b = first[j], last[j]
            sp = np.concatenate([np.stack([hlo[a:b], hhi[a:b]], axis=1), np.asarray(sp, dtype=float).reshape(-1, 2)])
        d = seg[1] - seg[0]
        L = float(np.hypot(d[0], d[1]))
        if L < 1e-6:
            continue
        parts = [(seg[0, :2] + s0 * d[:2], seg[0, :2] + s1 * d[:2])
                 for s0, s1 in _uncovered(np.asarray(sp).reshape(-1, 2), gap / L) if (s1 - s0) * L > gap]
        if parts:
            out.append((owner, parts))
    return out
