"""Family symbols' saved graphics: what Revit regenerated and last drew for each family type, read
from the file's channel-103 records (objgraph.py) as plan primitives.

Each element's channel-103 record is a graphics tree (Revit's GRep): GElement / GGroup nodes,
GFilter nodes whose `m_oConditions` gate their subtree on the view, curves (GLine, GArc,
GEllipse) and solids (Geometry: B-rep Faces on Plane / CylSurf / SurfRev / RuledSurf surfaces,
bounded by EdgeLoops of Edges whose points are stored as (u, v) on each adjacent face). A family
instance's own record is a GInstance whose InstanceInfo holds the transform Revit placed it with
(`m_Trf`: `m_3x3` rows and `m_or`) and the id of its symbol, the type's flip variant, whose
record holds the type's regenerated graphics (sizes and flips applied, nested families included
as further GInstances). The ids are the ones Revit's DXF export names its family blocks by.

Conditions (decoded against Revit's DXF blocks):
- GConditionDir `m_comp` 0: the view direction (toward the viewer) is `m_dir`; with 10, the view's
  right axis is parallel to `m_dir`: silhouettes cached for one view orientation, which exist
  only for views Revit has drawn (a plan's outline otherwise comes from the faces); m_dir is the
  view's left (oracle/test02). 6 / 7: the
  view direction has a positive / negative component along `m_dir` (looking down / up).
  8: the view direction is parallel to `m_dir`. `m_negateDirCondition` negates.
- GConditionInt `m_param` 3: the view's detail level (1 coarse, 2 medium, 3 fine, the view's
  VIEW_DETAIL_LEVEL); `m_comp` 0 not equal, 3 equal (the family's Coarse / Medium / Fine
  visibility boxes: not coarse = medium and fine, equal 3 = fine only; oracle/testfamily).
- GConditionCut `m_comp` 6 / 7: a solid split at a plan's / a ceiling plan's cut height (cached
  for one height: 4.0 / 7.5 ft above a column's base), the whole solid under both negated. Views
  looking across `m_dir` (sections, elevations) take the whole solid (oracle/test02's column);
  plans keep every branch (Snowdon's family bench drops with the split pieces).

Port notes: surfaces and the edge-loop walk follow rvt-rs `native_saved_mesh.rs` and
`native_parametric_surface.rs` (Apache-2.0).
"""
import dataclasses
import math
import os
import pathlib
import struct
import time
from dataclasses import dataclass

import numpy as np

from ..core import memory, objgraph, registry

BOUND = 0x1000000  # GInfo.m_flags: a bounded curve (families.BOUND)
STEP = math.pi / 32  # angle step along curved edges and surfaces


@dataclass
class Prim:
    conds: tuple  # ((class, comp, negate, dir or None, extra), ...): every condition must hold
    kind: str  # "curve" or "solid"
    points: list  # curve: [(N, 3)]; solid: its edges [(N, 3)]
    category: int = -1  # m_GInfo.m_categoryId: the graphics style (GStyleElem) it is drawn in
    solid: tuple | None = None  # (symbol id, Geometry object index, 4x4 placement) for meshing on demand
    gflags: int = 0  # m_GInfo.m_flags
    silhouette: bool = False  # under a GGroup / GFilter whose m_GInfo.m_flags has 0x20: a cached view outline


def _id(v):
    """An ElementId value's integer."""
    while isinstance(v, dict):
        v = v.get("m_id", v.get("m_id64"))
    return v


def _matrix(trf):
    m = np.eye(4)
    m[:3, :3] = np.array(trf["m_3x3"], dtype=float)
    m[:3, 3] = trf["m_or"]
    return m


class Link:
    """Saved graphics of one (linked) Revit file."""

    def __init__(self, path):
        self.path = str(path)
        self._bodies = None
        self.decoder = objgraph.Decoder(registry.load(self.path))
        self._graphs = {}

    @property
    def bodies(self):
        if self._bodies is None:
            self._bodies = objgraph.channel_bodies(self.path, 103)
        return self._bodies

    def graph(self, eid, keep=True):
        """An element's saved graphics (Graph), or None; kept for the next call unless not `keep`."""
        g = self._graphs.get(eid)
        if g is None and eid in self.bodies and len(self.bodies[eid]) >= 2:
            g = self.decoder.graph(self.bodies[eid])
            if keep:
                self._graphs[eid] = g
        return g

    def instance(self, eid):
        """(symbol id, 4x4 placement in the link's coordinates) of a family instance, or None."""
        # not kept: each instance's is read once (Snowdon Architectural's 7,787 held 0.4 GB), its
        # symbol's many times
        g = self.graph(eid, keep=False)
        if g is None:
            return None
        # the GInstance's own m_instanceInfo: a host-cut family with shared nested families
        # (oracle/test02's window) also holds InstanceInfo objects naming the nested elements
        # (drawn as elements of their own), before its own
        for i, o in enumerate(g.objects):
            if o.name == "GInstance":
                ptr = o.fields.get("m_instanceInfo")
                j = g.target(i, ptr[0] if isinstance(ptr, list) else ptr) if ptr is not None else None
                if j is not None and g.objects[j].name == "InstanceInfo":
                    f = g.objects[j].fields
                    return _id(f["m_symbolId"]), _matrix(f["m_Trf"])
                break
        for o in g.objects:
            if o.name == "InstanceInfo":
                return _id(o.fields["m_symbolId"]), _matrix(o.fields["m_Trf"])
        return None

    # ------------------------------------------------------------------ primitives

    def primitives(self, sym):
        """[Prim] of a symbol's graphics in the symbol's coordinates, nested symbols placed."""
        out = []
        self._walk(sym, np.eye(4), (), out, 0)
        return out

    def _walk(self, sym, m, conds, out, depth, sil=False):
        g = self.graph(sym)
        if g is None or depth > 8:
            return
        objs = g.objects
        seen = set()

        def kids(i, key):
            v = objs[i].fields.get(key)
            if v is None:
                return []
            return [t for p in (v if isinstance(v, list) else [v]) if (t := g.target(i, p)) is not None]

        def visit(i, conds, m, d, sil):
            if d > 64 or i in seen:
                return
            o = objs[i]
            name, f = o.name, o.fields
            if name in ("GGroup", "GFilter") and f.get("m_GInfo", {}).get("m_flags", 0) & GINFO_NOT_PRINTED:
                sil = True
            if name == "GFilter":
                conds = conds + tuple(_condition(objs[j]) for j in kids(i, "m_oConditions"))
            elif name in ("GLine", "GArc", "GEllipse"):
                pts = _curve_points(name, f)
                if pts is not None:
                    out.append(Prim(conds, "curve", [_apply(m, pts)], _id(f["m_GInfo"]["m_categoryId"]), gflags=f["m_GInfo"]["m_flags"],
                                    silhouette=sil))
                return
            elif name == "Geometry":
                seen.add(i)
                edges = _solid_edges(g, i)
                if edges:
                    out.append(Prim(conds, "solid", [_apply(m, e) for e in edges], _id(f["m_GInfo"]["m_categoryId"]), (sym, i, m)))
                return
            elif name == "GInstance":
                info = kids(i, "m_instanceInfo")
                if not info:
                    return
                inf = objs[info[0]].fields
                mm = m @ _matrix(inf["m_Trf"])
                emb = kids(i, "m_oEmbeddedSymbolGRep")
                if emb:
                    visit(emb[0], conds, mm, d + 1, sil)
                else:
                    self._walk(_id(inf["m_symbolId"]), mm, conds, out, depth + 1, sil)
                return
            for k in kids(i, "m_subNodes"):
                visit(k, conds, m, d + 1, sil)
        visit(0, conds, m, 0, sil)

    # ------------------------------------------------------------------ solids

    def solid_mesh(self, prim):
        """(verts (n, 3), faces (k, 3)) of a solid primitive, placed: its faces tessellated
        (planar faces from their trimmed boundaries, curved ones on a parameter grid)."""
        sym, gi, m = prim.solid
        mesh = _solid_mesh(self, sym, gi)
        if mesh is None:
            return None
        v, f = mesh
        return _apply(m, v), f


def _solid_mesh(link, sym, gi):
    key = (sym, gi)
    cache = link.__dict__.setdefault("_meshes", {})
    if key in cache:
        return cache[key]
    g = link.graph(sym)
    verts, faces = [], []
    n = 0
    for fi in _faces(g, gi):
        try:
            tri = _face_triangles(g, fi)
        except (ValueError, KeyError, IndexError, ZeroDivisionError):
            tri = None
        if tri is None:
            continue
        v, f = tri
        verts.append(v)
        faces.append(f + n)
        n += len(v)
    cache[key] = (np.vstack(verts), np.vstack(faces)) if verts else None
    return cache[key]


def _apply(m, pts):
    pts = np.asarray(pts, dtype=float)
    return pts @ m[:3, :3].T + m[:3, 3]


def _condition(o):
    f = o.fields
    c = o.name
    d = tuple(f["m_dir"]) if "m_dir" in f else None
    if c == "GConditionInt":
        return ("int", f["m_comp"], False, None, (f["m_param"], f["m_value"]))
    if c == "GConditionCut":
        return ("cut", f["m_comp"], f["m_negateDirCondition"], d, (f["m_rangeLo"], f["m_rangeHi"]))
    if c == "GConditionDir":
        return ("dir", f["m_comp"], f["m_negateDirCondition"], d, None)
    return (c, None, False, d, None)


def _curve_points(name, f):
    if name == "GLine":
        t0, t1 = f["m_endParams"]
        o, d = np.array(f["m_origin"]), np.array(f["m_dirVec"])
        return np.array([o + t0 * d, o + t1 * d])
    a0, a1 = f["m_endParams"]
    if not f["m_GInfo"]["m_flags"] & BOUND:
        a1 = a0 + 2 * math.pi  # an unbound arc or ellipse: a full turn (families.BOUND)
    if not a1 > a0:
        return None
    n = max(2, int(math.ceil((a1 - a0) / STEP)) + 1)
    t = np.linspace(a0, a1, n)[:, None]
    c, x, y = np.array(f["m_center"]), np.array(f["m_xVec"]), np.array(f["m_yVec"])
    if name == "GArc":
        r = f["m_radius"]
        return c + r * (np.cos(t) * x + np.sin(t) * y)
    return c + f["m_xLen"] * np.cos(t) * x + f["m_yLen"] * np.sin(t) * y


# ---------------------------------------------------------------------- B-rep

def _faces(g, gi):
    return [t for p in g.objects[gi].fields.get("m_pFaces", []) if (t := g.target(gi, p)) is not None]


class _Surface:
    """(u, v) -> xyz for a face's surface; `curved` when straight (u, v) segments are not straight."""

    def __init__(self, g, si):
        o = g.objects[si]
        f = o.fields
        self.kind = o.name
        self.curved = o.name != "Plane"
        if o.name == "Plane":
            self.o, self.x, self.y = (np.array(f[k]) for k in ("m_origin", "m_xVec", "m_yVec"))
        elif o.name in ("CylSurf", "ConeSurf"):
            self.c, self.x, self.y, self.z = (np.array(f[k]) for k in ("m_center", "m_xVec", "m_yVec", "m_zVec"))
            self.r = f.get("m_radius")
            self.half = f.get("m_halfAngle")
        elif o.name == "SurfRev":
            self.c, self.x, self.y, self.z = (np.array(f[k]) for k in ("m_center", "m_xVec", "m_yVec", "m_zVec"))
            self.profile = _profile(g, g.target(si, f["m_pProfileCurve"]))
        elif o.name == "RuledSurf":
            self.p1 = _profile(g, g.target(si, f["m_pProfileCurve1"]))
            self.p2 = _profile(g, g.target(si, f["m_pProfileCurve2"]))
        else:
            raise ValueError(f"surface {o.name}")
        if (o.name == "SurfRev" and self.profile is None) or (o.name == "RuledSurf" and (self.p1 is None or self.p2 is None)):
            raise ValueError("profile curve")

    def eval(self, uv):
        uv = np.atleast_2d(uv)
        u, v = uv[:, :1], uv[:, 1:2]
        if self.kind == "Plane":
            return self.o + u * self.x + v * self.y
        if self.kind == "CylSurf":
            return self.c + self.r * (np.cos(u) * self.x + np.sin(u) * self.y) + v * self.z
        if self.kind == "ConeSurf":
            rad = (self.r or 0.0) + v * math.tan(self.half or 0.0)
            return self.c + rad * (np.cos(u) * self.x + np.sin(u) * self.y) + v * self.z
        if self.kind == "SurfRev":
            q = self.profile(v[:, 0])
            cu, su = np.cos(u), np.sin(u)
            lx = q[:, :1] * cu - q[:, 1:2] * su
            ly = q[:, :1] * su + q[:, 1:2] * cu
            return self.c + lx * self.x + ly * self.y + q[:, 2:3] * self.z
        a = self.p1(self.p1.lo + u[:, 0] * (self.p1.hi - self.p1.lo))
        b = self.p2(self.p2.lo + u[:, 0] * (self.p2.hi - self.p2.lo))
        return a * (1 - v) + b * v


def _profile(g, i):
    if i is None:
        return None
    o = g.objects[i]
    f = o.fields
    if o.name == "GLine":
        org, d = np.array(f["m_origin"]), np.array(f["m_dirVec"])
        fn = lambda t: org + np.asarray(t, dtype=float)[:, None] * d
    elif o.name == "GArc":
        c, x, y, r = np.array(f["m_center"]), np.array(f["m_xVec"]), np.array(f["m_yVec"]), f["m_radius"]
        fn = lambda t: c + r * (np.cos(np.asarray(t))[:, None] * x + np.sin(np.asarray(t))[:, None] * y)
    elif o.name == "GEllipse":
        c, x, y = np.array(f["m_center"]), np.array(f["m_xVec"]), np.array(f["m_yVec"])
        fn = lambda t: c + f["m_xLen"] * np.cos(np.asarray(t))[:, None] * x + f["m_yLen"] * np.sin(np.asarray(t))[:, None] * y
    else:
        return None
    fn.lo, fn.hi = f["m_endParams"]
    fn.straight = o.name == "GLine"
    return fn


def _surface(g, fi, cache):
    s = cache.get(fi)
    if s is None:
        s = cache[fi] = _Surface(g, g.target(fi, g.objects[fi].fields["m_pSurf"]))
    return s


def _densify(uv, surf):
    """uv polyline with points added every STEP of parameter on a curved surface."""
    if not surf.curved or len(uv) < 2:
        return uv
    a, b = uv[:-1], uv[1:]
    d = np.abs(b[:, 0] - a[:, 0])
    if surf.kind == "SurfRev":
        d = np.maximum(d, np.abs(b[:, 1] - a[:, 1]))
    k = np.maximum(1, np.ceil(d / STEP)).astype(np.intp)
    # each segment's np.linspace(0, 1, k + 1)[1:]: j * (1 / k), its last exactly 1
    seg = np.repeat(np.arange(len(k)), k)
    j = np.arange(len(seg)) - np.repeat(np.cumsum(k) - k, k) + 1
    t = np.where(j == k[seg], 1.0, j * (1.0 / k[seg]))[:, None]
    return np.vstack([uv[:1], a[seg] + t * (b[seg] - a[seg])])


def _edge_uv(e, side):
    f = e.fields
    pts = [f["m_firstAndLastEdgePnts"][0]["uv"][side]]
    pts += [p["uv"][side] for p in f["m_interiorEdgePnts"]]
    pts.append(f["m_firstAndLastEdgePnts"][1]["uv"][side])
    return np.array(pts, dtype=float)


def _solid_edges(g, gi):
    """Every Edge of a Geometry's faces as an xyz polyline, evaluated on its curved side if any."""
    cache, done, out = {}, set(), []
    for fi in _faces(g, gi):
        for ei in _loop_edges(g, fi):
            if ei in done:
                continue
            done.add(ei)
            e = g.objects[ei]
            sides = [g.target(ei, p) for p in e.fields["m_pFace"]]
            best = None
            for side, face in enumerate(sides):
                if face is None:
                    continue
                try:
                    s = _surface(g, face, cache)
                except (ValueError, KeyError):
                    continue
                if best is None or (s.curved and not best[1].curved):
                    best = (side, s)
            if best is None:
                continue
            side, s = best
            out.append(s.eval(_densify(_edge_uv(e, side), s)))
    return out


def _loop_edges(g, fi):
    """The Edge object indices around every loop of face fi."""
    objs = g.objects
    f = objs[fi].fields
    li = g.target(fi, f["m_pFirstLoop"])
    out, loops = [], set()
    while li is not None and li not in loops:
        loops.add(li)
        lo = objs[li]
        cur = g.target(li, lo.fields["m_next"])
        seen = set()
        while cur is not None and cur != li and cur not in seen:
            seen.add(cur)
            e = objs[cur]
            if e.name != "Edge":
                break
            out.append(cur)
            sides = [g.target(cur, p) for p in e.fields["m_pFace"]]
            side = sides.index(fi) if fi in sides else 0
            cur = g.target(cur, e.fields["m_next"][side])
        li = g.target(li, lo.fields["m_nextLoop"])
    return out


def _face_rings(g, fi, surf, cache):
    """The face's loops as closed (u, v) rings on its own surface, curved neighbours' edges refined."""
    objs = g.objects
    rings = []
    li = g.target(fi, objs[fi].fields["m_pFirstLoop"])
    loops = set()
    while li is not None and li not in loops:
        loops.add(li)
        lo = objs[li]
        segs, cur, seen = [], g.target(li, lo.fields["m_next"]), set()
        while cur is not None and cur != li and cur not in seen:
            seen.add(cur)
            e = objs[cur]
            sides = [g.target(cur, p) for p in e.fields["m_pFace"]]
            side = sides.index(fi) if fi in sides else 0
            uv = _edge_uv(e, side)
            other = sides[1 - side] if len(sides) == 2 else None
            if surf.kind == "Plane" and other is not None:
                try:
                    os_ = _surface(g, other, cache)
                except (ValueError, KeyError):
                    os_ = None
                if os_ is not None and os_.curved:  # refine on the curved neighbour, back into the plane
                    xyz = os_.eval(_densify(_edge_uv(e, 1 - side), os_))
                    d = xyz - surf.o
                    uv = np.column_stack([d @ surf.x, d @ surf.y]) / np.array([surf.x @ surf.x, surf.y @ surf.y])
            elif surf.curved:
                uv = _densify(uv, surf)
            segs.append(uv)
            cur = g.target(cur, e.fields["m_next"][side])
        ring = _chain(segs)
        if ring is not None:
            rings.append(ring)
        li = g.target(li, lo.fields["m_nextLoop"])
    return rings


def _chain(segs):
    if len(segs) < 1:
        return None
    for rev in (False, True):
        out = list(segs[0][::-1] if rev else segs[0])
        ok = True
        for s in segs[1:]:
            last = out[-1]
            if np.hypot(*(last - s[0])) < 1e-6:
                out.extend(s[1:])
            elif np.hypot(*(last - s[-1])) < 1e-6:
                out.extend(s[::-1][1:])
            else:
                ok = False
                break
        if ok and len(out) >= 3:
            return np.array(out)
    return None


def _face_triangles(g, fi):
    """(verts, triangles) of one face: a planar face's trimmed (u, v) region triangulated
    (constrained Delaunay); a curved face as a (u, v) grid (STEP across curvature) whose cells
    have their centre inside the trim region; mapped to xyz."""
    import shapely
    from shapely.geometry import Polygon
    cache = {}
    surf = _surface(g, fi, cache)
    rings = _face_rings(g, fi, surf, cache)
    if not rings:
        return None
    area = None
    for r in rings:  # holes by even-odd
        p = Polygon(r).buffer(0)
        area = p if area is None else area.symmetric_difference(p)
    if area is None or area.is_empty:
        return None
    if not surf.curved:
        t = shapely.constrained_delaunay_triangles(area)
        tris = [np.asarray(x.exterior.coords)[:3] for x in getattr(t, "geoms", [t]) if not x.is_empty and x.geom_type == "Polygon"]
        if not tris:
            return None
        uv = np.concatenate(tris)
        return surf.eval(uv), np.arange(len(uv), dtype=np.int64).reshape(-1, 3)
    u0, v0, u1, v1 = area.bounds
    nu = max(1, int(math.ceil((u1 - u0) / STEP)))
    # a surface of revolution is curved along v unless its profile is a line (a cone or cylinder:
    # v is then a length in feet, not an angle, and STEP rows of it ran to 32k triangles a solid on
    # the cones of a family rac_basic_sample_project places 8 times: 456k triangles an instance)
    curved_v = surf.kind == "RuledSurf" or (surf.kind == "SurfRev" and not surf.profile.straight)
    rect = abs(area.area - (u1 - u0) * (v1 - v0)) <= 1e-9 * max(1.0, (u1 - u0) * (v1 - v0))
    nv = max(1, int(math.ceil((v1 - v0) / STEP))) if curved_v else (1 if rect else 8)
    U, V = np.meshgrid(np.linspace(u0, u1, nu + 1), np.linspace(v0, v1, nv + 1), indexing="ij")
    pts = np.column_stack([U.ravel(), V.ravel()])
    i = np.arange(nu)[:, None] * (nv + 1) + np.arange(nv)[None, :]
    a_, b_, c_, d_ = i.ravel(), (i + nv + 1).ravel(), (i + nv + 2).ravel(), (i + 1).ravel()
    tri = np.concatenate([np.column_stack([a_, b_, c_]), np.column_stack([a_, c_, d_])])
    cen = pts[tri].mean(axis=1)
    keep = shapely.contains_xy(area, cen[:, 0], cen[:, 1]) if not rect else np.ones(len(tri), bool)
    if not keep.any():
        return None
    return surf.eval(pts), tri[keep]


# ---------------------------------------------------------------------- per link, per view

class Saved:
    """A link's saved graphics prepared for drawing, disk-cached: instances {element id:
    (symbol, 4x4)}, primitives {symbol: [Prim]} and solid meshes {(symbol, primitive index):
    (verts, faces)} in the symbols' coordinates."""

    def __init__(self, path, instances, prims, meshes=None):
        self.path, self.instances, self.prims = str(path), instances, prims
        self.meshes = meshes if meshes is not None else {}
        self._compiled_cache, self._selection, self._right, self._heights = {}, {}, {}, {}
        self._points_cache = {}
        # selections kept between prints (read_selections / write_selections): those read from
        # the cache folder, and those this process worked out and has yet to write there
        self._kept, self._new, self._read = {}, {}, set()

    def _compiled(self, sym):
        """Per primitive: (conditions, kind, local segments (k, 2, 3), index), cached."""
        c = self._compiled_cache.get(sym)
        if c is None:
            c = []
            for i, p in enumerate(self.prims[sym]):
                ws = [w for w in p.points if len(w) > 1]
                if len(ws) == 1:  # most: one polyline
                    segs = np.stack([ws[0][:-1], ws[0][1:]], axis=1)
                elif ws:  # each polyline's consecutive points, all of the primitive's at once
                    pts = np.concatenate(ws)
                    start = np.delete(np.arange(len(pts) - 1), np.cumsum([len(w) for w in ws[:-1]], dtype=np.intp) - 1)
                    segs = np.stack([pts[start], pts[start + 1]], axis=1)
                else:
                    segs = np.zeros((0, 2, 3))
                c.append((p.conds, p.kind, segs, i))
            self._compiled_cache[sym] = c
        return c

    def _uses_right(self, sym):
        """Whether a condition of the symbol's reads the view's right axis (_holds: comp 10, a
        cached silhouette's edge normals): else its selection is the same at every rotation in
        the view plane, and cached once for all of them."""
        r = self._right.get(sym)
        if r is None:
            r = self._right[sym] = any(x[0] == "dir" and x[1] == 10 for p in self.prims[sym] for x in p.conds)
        return r

    def _solid_heights(self, sym):
        """(lowest, highest) z of the symbol's solid meshes, or None: where a cut plane can change
        what they hide (_unhidden)."""
        if sym not in self._heights:
            zs = [self.meshes[sym, i][0][:, 2] for i, p in enumerate(self.prims[sym])
                  if p.kind == "solid" and (sym, i) in self.meshes and len(self.meshes[sym, i][1])]
            self._heights[sym] = (float(min(z.min() for z in zs)), float(max(z.max() for z in zs))) if zs else None
        return self._heights[sym]

    def _cut_key(self, sym, vdir, cut):
        """The cut height as the selection's cache key: what _unhidden makes of a cut plane beyond
        every solid of the symbol (all short of it: no cut) or short of them all (none hides) is
        the same at any such height, so one key holds those instances at every elevation."""
        if cut is None:
            return None
        zs = self._solid_heights(sym)
        if zs is None or abs(abs(vdir[2]) - 1) > 1e-6:
            return "any"
        sgn = 1.0 if vdir[2] > 0 else -1.0
        lo, hi = sorted((sgn * zs[0], sgn * zs[1]))  # the solids' h = sgn * z toward the viewer
        if sgn * cut - 1e-6 > hi:
            return "beyond"
        if sgn * cut - 1e-6 <= lo:
            return "short"
        return round(cut, 3)

    def _selected(self, sym, vdir, vright, detail=None, cut=None, uncut=False):
        axes = np.concatenate([vdir, vright]) if self._uses_right(sym) else vdir
        key = (sym, detail, self._cut_key(sym, vdir, cut), uncut) + tuple(np.round(axes, 4).tolist())
        hit = self._selection.get(key)
        if hit is None:
            kept = self._kept.get(key)
            if kept is not None:  # worked out by an earlier print: its segments, or the primitive's own
                comp = self._compiled(sym)
                hit = self._selection[key] = [(comp[i][0], comp[i][1], comp[i][2] if segs is None else segs, i)
                                              for i, segs in kept]
                return hit
            # the cut requirement is a solid's (its cut representation); a door's elevation swing,
            # curves under the same comp 6, is drawn uncut (test02's Elevation 1)
            sel = [c for c in self._compiled(sym) if all(_holds(x, vdir, vright, detail, cut, uncut and c[1] == "solid") for x in c[0])]
            hit = self._selection[key] = self._new[key] = self._unhidden(sym, sel, vdir, cut)
        return hit

    # Selections between prints. Working one out (_unhidden: a symbol's lines against its own
    # solids) was over half of the time Snowdon's heaviest plans took to draw, and every sheet's
    # process did it again for the same family types on every print. Each process now writes the
    # ones it worked out to a file of its own in the cache folder, and the next print reads them
    # all before its sheet processes start (they share them). A selection is kept as, per
    # primitive, its segments where lines were hidden and nothing where they are the primitive's
    # own: a few MB a model.

    def _selections(self):
        """(the folder this file's selections are kept in, what they are valid for)."""
        from ..core import diskcache, paths
        return (paths.CACHE / "cache" / f"{pathlib.Path(self.path).name}.selections",
                diskcache.stamp(self.path, MODULES))

    def read_selections(self, gather=True):
        """Take up the selections kept so far: earlier prints', and during a print those of its
        sheets already drawn, for the sheets yet to start (their processes each read what the
        printing process holds). With `gather`, several files are made one."""
        import pickle
        from ..core import paths
        try:
            folder, stamp = self._selections()
            files = sorted(folder.glob("*.pkl")) if paths.trusted(folder) and paths.trusted(folder.parent) else []
        except OSError:
            return
        stale = False
        for f in files:
            if f.name in self._read:
                continue
            self._read.add(f.name)
            try:
                with f.open("rb") as fh:
                    key, entries = pickle.load(fh)
            except Exception:  # noqa: BLE001 - a file cut short or of another version: not used
                key, entries = None, {}
            if key == stamp:
                self._kept.update(entries)
            else:
                stale = True
        if gather and (len(files) > 1 or stale):
            try:
                _write_whole(folder / "all.pkl", (stamp, self._kept))
                for f in files:
                    if f.name != "all.pkl":
                        f.unlink(missing_ok=True)
                        self._read.discard(f.name)
                self._read.add("all.pkl")
            except OSError:
                pass

    def write_selections(self):
        """Keep the selections this process worked out, for the next print."""
        if not self._new:
            return
        entries = {}
        for key, hit in self._new.items():
            comp = self._compiled(key[0])
            entries[key] = [(i, None if segs is comp[i][2] else segs) for _c, _kind, segs, i in hit]
        try:
            from ..core import paths
            folder, stamp = self._selections()
            paths.private(folder)
            _write_whole(folder / f"{os.getpid()}-{time.time_ns()}.pkl", (stamp, entries))
        except OSError:
            return  # a cache folder that cannot be written costs the next print its time, no more
        self._kept.update(entries)
        self._new.clear()

    def _points(self, sym):
        """Every point of the symbol's primitives, (n, 3): where an instance stands against a cut."""
        pts = self._points_cache.get(sym)
        if pts is None:
            ps = self.prims[sym]
            pts = self._points_cache[sym] = (np.concatenate([np.concatenate(p.points) for p in ps if p.points])
                                             if ps else np.zeros((0, 3)))
        return pts

    def _unhidden(self, sym, sel, vdir, cut=None):
        """The selected primitives with the parts of their segments that a solid of the same
        symbol hides removed (hidden lines, in the symbol's coordinates). Looking along `vdir`
        (toward the viewer, +z or -z here) from the cut plane at height `cut` (symbol z; None: no
        cut), a segment inside the footprint of a solid's part between it and the cut plane is
        behind that part, so lines on a solid's underside are hidden too (oracle/testfamily:
        Test_Furniture's arrows, model lines on the box's base), and a part beyond the cut plane
        (cut away: a door head, a canopy) hides nothing. A solid does not hide its own edges, nor
        lines on its outline."""
        if abs(abs(vdir[2]) - 1) > 1e-6:
            return sel
        sgn = 1.0 if vdir[2] > 0 else -1.0  # h = sgn * z grows toward the viewer
        h_cut = np.inf if cut is None else sgn * cut
        solids = []  # (primitive index, top h, triangles (m, 3, 3) toward the viewer of nothing)
        for _c, kind, _local, i in sel:
            mesh = self.meshes.get((sym, i)) if kind == "solid" else None
            if mesh is None or not len(mesh[1]):
                continue
            t = mesh[0][mesh[1]].astype(np.float64)
            h = sgn * t[:, :, 2]
            t = t[h.min(axis=1) < h_cut - 1e-6]  # the part short of the cut plane
            if len(t):
                top = float(np.minimum(sgn * t[:, :, 2].max(), h_cut))
                solids.append((i, top, t))
        if not solids:
            return sel
        counts = np.array([len(c[2]) for c in sel])
        if not counts.sum():
            return sel
        ids = np.array([i for i, _z, _t in solids])
        tops = np.array([z0 for _i, z0, _t in solids])
        bounds = np.array([[t[:, :, 0].min(), t[:, :, 1].min(), t[:, :, 0].max(), t[:, :, 1].max()] for _i, _z, t in solids])
        # every primitive's segments at once (a symbol has thousands of primitives of a few
        # segments each: taken one by one, the bookkeeping was most of the time)
        segs = np.concatenate([c[2] for c in sel if len(c[2])])  # (s, 2, 3)
        owner = np.repeat(np.array([c[3] for c in sel]), counts)
        ends = np.cumsum(counts)
        ds = segs[:, 1] - segs[:, 0]
        lengths = np.hypot(ds[:, 0], ds[:, 1])
        hidden = np.zeros(len(segs), bool)  # a solid may hide it
        span_seg, span_ab = [], []  # the covered spans (0..1 along its segment) and each one's segment
        step = max(1, 8_000_000 // len(solids))  # segments at a time: step x solids flags
        for s0 in range(0, len(segs), step):
            part = segs[s0:s0 + step]
            lo, hi = part.min(axis=1), part.max(axis=1)  # per segment (n, 3)
            h_seg = np.maximum(sgn * lo[:, 2:3], sgn * hi[:, 2:3])
            # occluders per segment: another solid's part nearer the viewer, whose box meets it
            over = (ids[None, :] != owner[s0:s0 + step, None]) & (tops[None, :] > h_seg + 1e-4)
            over &= (bounds[None, :, 0] < hi[:, 0:1]) & (bounds[None, :, 2] > lo[:, 0:1])
            over &= (bounds[None, :, 1] < hi[:, 1:2]) & (bounds[None, :, 3] > lo[:, 1:2])
            rows = np.flatnonzero(over.any(axis=1))
            if not len(rows):
                continue
            hidden[s0 + rows] = True
            # these segments against the occluding solids' triangles in one query (a query per
            # primitive and solid was most of the rest: thousands of them a sheet)
            spans, at = _covered(part[rows, :, :2], over[rows], [t for _i, _z, t in solids])
            span_seg.append(np.repeat(s0 + rows, at[1:] - at[:-1]))
            span_ab.append(spans)
        if not hidden.any():
            return sel
        whole = ~hidden | (lengths < 1e-9)
        # a segment no triangle covers stays whole (as its start and its start plus its length,
        # as the pieces of a covered one are), if it has a length to draw
        single = np.stack([segs[:, 0] + 0.0 * ds, segs[:, 0] + 1.0 * ds], axis=1)
        single[whole] = segs[whole]
        n_out = (whole | (lengths > 1e-3)).astype(np.intp)  # pieces each segment leaves
        span_seg, span_ab = np.concatenate(span_seg), np.concatenate(span_ab)
        keep = ~whole[span_seg]
        of, t0, t1 = _uncovered_parts(span_seg[keep], span_ab[keep], lengths)
        n_out[span_seg[keep]] = 0
        np.add.at(n_out, of, 1)
        at = np.concatenate([[0], np.cumsum(n_out)])
        drawn = np.empty((at[-1], 2, 3), dtype=segs.dtype)
        left = n_out > 0
        left[of] = False  # the segments kept as they are
        drawn[at[:-1][left]] = single[left]
        if len(of):  # the pieces of a segment follow one another: its first is the first of its run
            where = at[of] + np.arange(len(of)) - np.searchsorted(of, of)
            drawn[where, 0] = segs[of, 0] + t0[:, None] * ds[of]
            drawn[where, 1] = segs[of, 0] + t1[:, None] * ds[of]
        out = []
        for c, o0, o1 in zip(sel, ends - counts, ends):
            if o0 == o1 or not hidden[o0:o1].any():
                out.append(c)
            else:
                out.append((c[0], c[1], drawn[at[o0]:at[o1]].copy(), c[3]))
        return out

    def plan(self, tag, place, cut, bottom, top=None, overhead_top=None, right=(1.0, 0.0, 0.0), detail=None,
             cut_only_through=False):
        """(placement 4x4 in the model, [(world segments (k, 2, 3), local segments (k, 2, 3), is_cut,
        graphics style id)])
        of a family instance in a plan view (top None: looking down from the cut plane to
        `bottom`; a ceiling plan: looking up from the cut plane to `top`), or None when it has no
        saved graphics. `place` maps the link's coordinates to the model's; `right` is the view's
        right axis; with `overhead_top`, solids above the cut up to it draw their edges; `detail`
        the view's detail level (None: every detail branch)."""
        hit = self.instances.get(tag)
        if hit is None or hit[0] not in self.prims:
            return None
        sym, m = hit
        M = place @ m
        R, T = M[:3, :3], M[:3, 3]
        Ri = np.linalg.inv(R)
        vdir = Ri @ np.array([0.0, 0.0, 1.0 if top is None else -1.0])
        vright = Ri @ np.asarray(right, dtype=float)
        vdir /= np.linalg.norm(vdir)
        vright /= np.linalg.norm(vright)
        out = []
        cut_local = None  # the cut plane in symbol z, for an instance standing upright or upside down
        if abs(abs(R[2, 2]) - 1) < 1e-6:
            cut_local = (cut - T[2]) / R[2, 2]
        # cached silhouettes (curves under a group flagged 0x20) are a view's outline Revit
        # regenerates: the selected solids' edges draw it (test02's door: its opening-and-swing
        # box outlined 2.5 ft outside the wall in side elevations). They are drawn only where
        # the rest draws nothing (Snowdon's Refrigerator: its plan outline only in silhouettes).
        # a section or an elevation draws a family's cut representations (solids under
        # GConditionDir comps 6 / 7) only where its view plane passes through the instance (test02's window seen side-on
        # from far off in Elevation 3: Revit draws none of its opening solids); plans keep them,
        # and where the cut passes through the instance draw them wherever they lie (Snowdon's
        # Shelving: its plan representation a solid at its top, above M103's cut)
        pts = self._points(sym)
        zs = pts @ R[2] + T[2] if len(pts) else np.zeros(0)
        through = bool(len(zs) and zs.min() < cut < zs.max())
        uncut = cut_only_through and not through
        sel = self._selected(sym, vdir, vright, detail, cut_local, uncut)
        prims = self.prims[sym]
        for want_sil in (False, True):
            for conds, kind, local, i in (c for c in sel if bool(getattr(prims[c[3]], "silhouette", False)) == want_sil):
                if not len(local):
                    continue
                world = local @ R.T + T
                style = self.prims[sym][i].category  # its graphics style (GStyleElem), for pen and colour
                if kind == "curve":
                    out.append((world, local, False, style))
                    continue
                z = world[:, :, 2]
                zlo, zhi = z.min(), z.max()
                if zlo < cut < zhi:  # cut: its section, and its edges on the viewer's side
                    mesh = self.meshes.get((sym, i))  # in the symbol's coordinates
                    if mesh is not None:
                        from ..geometry.linkgeom import _cut
                        cs = _cut(mesh[0].astype(np.float64) @ R.T + T, mesh[1], cut)
                        if cs:
                            w = np.empty((len(cs), 2, 3))
                            w[:, :, :2] = np.array(cs)
                            w[:, :, 2] = cut
                            out.append((w, (w - T) @ Ri.T, True, style))
                    # looking down, the edges below the cut; a ceiling plan looks up, at those above it
                    seen = z.max(axis=1) <= cut + 1e-6 if top is None else z.min(axis=1) >= cut - 1e-6
                    if seen.any():
                        out.append((world[seen], local[seen], False, style))
                elif through and not cut_only_through and any(c[0] == "dir" and c[1] in (6, 7) for c in conds):
                    out.append((world, local, False, style))  # the cut representation, the instance cut
                elif top is None:
                    if zhi <= cut + 1e-6 and zhi >= bottom - 0.05 or overhead_top is not None and cut <= zlo <= overhead_top:
                        out.append((world, local, False, style))
                elif zlo >= cut - 1e-6 and zlo <= top + 0.05:
                    out.append((world, local, False, style))
            # silhouettes stand in only for a selected representation that drew nothing here (the
            # Refrigerator's plan solid above the cut); where the view's conditions select none
            # (test02's trims, hidden in side views) they are not drawn either
            if out or not any(not getattr(prims[c[3]], "silhouette", False) for c in sel):
                break
        return M, out


def _covered(segs, over, solids, inset=1e-4):
    """The parameter spans (0..1 along each) of the segments `segs` ((s, 2, 2) plan) strictly
    inside a triangle of a solid that may hide them (`over` (s, solids) says which may; `solids`
    their triangles (m, 3, 3)), inset by `inset`: (spans (k, 2) sorted by segment, `at` with
    segment j's spans at spans[at[j]:at[j + 1]]). Only pairs whose boxes meet are clipped (an
    STRtree of the triangles' boxes); edge-on triangles are left out."""
    import shapely
    ts, of = [], []
    for k in np.flatnonzero(over.any(axis=0)):
        t = solids[k][:, :, :2]
        e1, e2 = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
        a2 = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        ok = np.abs(a2) > 1e-10
        t, a2 = t[ok], a2[ok]
        t[a2 < 0] = t[a2 < 0][:, ::-1]  # anticlockwise
        ts.append(t)
        of.append(np.full(len(t), k))
    t, of = np.concatenate(ts), np.concatenate(of)
    edge = np.roll(t, -1, axis=1) - t
    n = np.stack([-edge[:, :, 1], edge[:, :, 0]], axis=2)  # inward edge normals
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    tree = shapely.STRtree(shapely.box(*np.concatenate([t.min(axis=1), t.max(axis=1)], axis=1).T))
    si, ti = tree.query(shapely.linestrings(segs))  # sorted by segment
    pair = over[si, of[ti]]
    si, ti = si[pair], ti[pair]
    p, d = segs[si, 0], segs[si, 1] - segs[si, 0]
    nn = n[ti]
    # per triangle edge: n . (p + s d - a) > inset, i.e. s * nd > inset - n . (p - a)
    nd = (nn * d[:, None, :]).sum(axis=2)
    c = inset - (nn * (p[:, None, :] - t[ti])).sum(axis=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = c / nd
    lo = np.maximum(np.where(nd > 0, r, -np.inf).max(axis=1), 0.0)
    hi = np.minimum(np.where(nd < 0, r, np.inf).min(axis=1), 1.0)
    keep = ~((np.abs(nd) <= 1e-15) & (c >= 0)).any(axis=1) & (hi > lo)  # parallel to an edge, outside it
    spans = np.stack([lo[keep], hi[keep]], axis=1)
    return spans, np.searchsorted(si[keep], np.arange(len(segs) + 1))


def _uncovered_parts(seg, spans, lengths):
    """The parts of each segment outside the union of its covered `spans` ((k, 2), 0..1 along the
    segment `seg` (k) names; `lengths` its length): (segment, start, end) of each part, sorted by
    segment and along it. A gap between spans under 1e-3 long is closed, and a part that short is
    not kept. For every segment at once: one by one, in Python, this was most of the time a
    building's family lines took (Snowdon Architectural: 631,000 covered segments)."""
    n = len(seg)
    if not n:
        return np.zeros(0, np.intp), np.zeros(0), np.zeros(0)
    order = np.lexsort((spans[:, 0], seg))
    seg, a, b = seg[order], spans[order, 0], spans[order, 1]
    first = np.concatenate([[True], seg[1:] != seg[:-1]])
    last = np.concatenate([first[1:], [True]])
    # how far the spans before each one reach (the largest end so far within its segment), from
    # the ends' ranks, so that the value is an end as it stands and not one shifted and back
    by_end = np.argsort(b, kind="stable")
    rank = np.empty(n, np.int64)
    rank[by_end] = np.arange(n)
    group = (np.cumsum(first) - 1) * n
    reach = b[by_end][np.maximum.accumulate(group + rank) - group]
    before = np.empty(n)
    before[1:] = reach[:-1]
    before[first] = 0.0
    length = lengths[seg]
    gap = 1e-3 / length
    between = a > before + gap  # the part from where the spans before it reach to this span
    after = last & (reach < 1.0 - gap)  # the part from the last reach to the segment's end
    at = np.concatenate([np.flatnonzero(between), np.flatnonzero(after)])
    t0 = np.concatenate([before[between], reach[after]])
    t1 = np.concatenate([a[between], np.ones(int(after.sum()))])
    # along the segment: a span's part before the part after the segment's last span
    order = np.lexsort((np.concatenate([np.zeros(int(between.sum())), np.ones(int(after.sum()))]), at))
    at, t0, t1 = at[order], t0[order], t1[order]
    long = (t1 - t0) * length[at] > 1e-3
    return seg[at][long], t0[long], t1[long]


def _uncovered(spans, gap):
    """The parts of 0..1 outside the union of `spans`, gaps narrower than `gap` closed (one
    segment's; _uncovered_parts does every segment's at once)."""
    if not len(spans):
        return [(0.0, 1.0)]
    spans = spans[np.argsort(spans[:, 0])]
    out, at = [], 0.0
    for a, b in spans:
        if a > at + gap:
            out.append((at, a))
        at = max(at, b)
    if at < 1.0 - gap:
        out.append((at, 1.0))
    return out


def _holds(c, vdir, vright, detail=None, cut=None, uncut=False):
    kind, comp, neg, d, extra = c
    if kind == "cut" and comp in (6, 7):
        # a column's solid split at a plan's and a ceiling plan's cut heights (pieces under cut 6
        # / 7, the whole solid under both negated): a cache for one cut height (4.0 / 7.5 ft
        # above the base of test02's column and of Snowdon's 58 ft W columns alike), so in a plan
        # every branch is kept and the solid is cut here; a view looking across m_dir (a section,
        # an elevation) is not cut along it: the whole solid (oracle/test02's column)
        if abs(np.asarray(d) @ vdir) < 1e-3:
            return bool(neg)
        return True
    if kind == "int":
        param, value = extra
        if param != 3 or detail is None or comp not in (0, 3):
            return True  # other parameters: not decoded yet (kept)
        return (detail == value) == (comp == 3)
    if kind != "dir":
        return True  # cut ranges: not decoded yet (every branch kept)
    d = np.asarray(d)
    if comp == 0:  # np.allclose(d, vdir, atol=1e-3), without its overhead on three numbers
        r = all(abs(p - q) <= 1e-3 + 1e-5 * abs(q) for p, q in zip(d.tolist(), vdir.tolist()))
    elif comp == 10:
        # each edge of a cached silhouette outline carries its outward normal in the view plane;
        # read as the view's left, one edge of each outline survives (silhouettes are mostly
        # left out: _selected)
        r = d @ vright < -1 + 1e-3
    elif comp == 6:
        r = d @ vdir > 1e-3 and not uncut
    elif comp == 7:
        r = d @ vdir < -1e-3 and not uncut
    elif comp == 8:
        r = abs(abs(d @ vdir) - 1) < 1e-3
    else:
        return True
    return bool(r) != bool(neg)


# Categories of graphics styles a project never prints: -2000083 is the style a family's
# Reference Lines are saved in (oracle/testfamily: Test_Furniture's two reference lines are its
# only -2000083 curves, and Revit's print and DXF leave them out).
NOT_PRINTED = frozenset({-2000083, -2000064})  # and <Invisible lines> (OST_InvisibleLines, fills.py): test02's door
# draws its opening's edge across the wall face in it, which Revit leaves out


# m_GInfo.m_flags bit of curves Revit does not print: a door's opening outline (oracle/test02,
# 0x1088024 where its printed curves have 0x1088004) and reference lines (0x10882a4)
GINFO_NOT_PRINTED = 0x20


def _style_categories(path):
    """{GStyleElem id: its m_categoryId}: the category of each graphics style a curve's
    m_GInfo.m_categoryId names."""
    from ..model import pens
    return {sid: cat for sid, (cat, _kind) in pens.style_categories(str(path)).items()}


# Processes a file's symbols are decoded in (_symbols): 1 here; a prefetch worker building the
# largest model's caches, the print's critical path, is given more (linkgeom.prefetch)
PROCS = 1
SYMBOLS_TIMEOUT = 900.0  # seconds a helper process may take before its symbols are decoded here


def _symbol(link, sym, styles):
    """(a symbol's printed primitives, {(sym, index): (verts float32, faces int32)} of its solids)."""
    try:
        ps = link.primitives(sym)
    except (ValueError, KeyError, IndexError):
        ps = []
    ps = [p for p in ps if styles.get(p.category) not in NOT_PRINTED
          and not (p.kind == "curve" and p.gflags & GINFO_NOT_PRINTED)]
    meshes = {}
    for i, p in enumerate(ps):
        if p.kind == "solid":
            try:
                mesh = link.solid_mesh(p)
            except (ValueError, KeyError, IndexError):
                mesh = None
            if mesh is not None:
                meshes[(sym, i)] = (mesh[0].astype(np.float32), mesh[1].astype(np.int32))
    return ps, meshes


def _symbols_child(link, syms, styles, conn):
    """A helper process of _symbols: _symbol of each of `syms` to `conn`; it ends with its parent."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG: a worker stopped for memory takes its helpers
    except (OSError, AttributeError):
        pass
    import gc
    gc.disable()  # it ends with its task: no passes over the parent's objects and its own (linkgeom._warm)
    try:
        conn.send([_symbol(link, sym, styles) for sym in syms])
    except BaseException:  # noqa: BLE001 - the parent decodes these symbols itself
        pass
    conn.close()


def _symbols(link, syms, styles, procs):
    """[_symbol] of `syms`, in `procs` processes forked from this one when that is more than one
    and there is a fork: each symbol's graphics are decoded and its solids meshed by themselves,
    and they are most of a model's cold caches (Snowdon Architectural: 1,169 symbols and 7,656
    solids, 31 s of its 47, on one core). The helpers share what is read of the file already (its
    bodies and classes: nothing is read after the fork, when they would share its open file);
    what one fails at, or does not send in SYMBOLS_TIMEOUT, is decoded here."""
    import multiprocessing
    import os
    procs = min(procs, len(syms) // 8)
    if procs <= 1 or not hasattr(os, "fork") or "fork" not in multiprocessing.get_all_start_methods():
        return [_symbol(link, sym, styles) for sym in syms]
    _ = link.bodies  # read before the fork
    ctx = multiprocessing.get_context("fork")
    helpers = []
    for k in range(procs):
        chunk = syms[k::procs]  # the heavy symbols come in runs (a family's types): spread them
        r, w = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=_symbols_child, args=(link, chunk, styles, w))
        proc.start()
        w.close()
        helpers.append((proc, r, chunk))
    done = {}
    for proc, r, chunk in helpers:
        try:
            got = r.recv() if r.poll(SYMBOLS_TIMEOUT) else None
        except (EOFError, OSError):
            got = None
        r.close()
        if got is None or len(got) != len(chunk):
            proc.kill()
            got = [_symbol(link, sym, styles) for sym in chunk]
        proc.join()
        done.update(zip(chunk, got))
    return [done[sym] for sym in syms]


def _compute(path):
    from . import families
    link = Link(path)
    from ..core import objgraph
    from .gelements import RAIL_CLASSES
    rails = [e for c in RAIL_CLASSES for e in objgraph._class_index(path).get(c, ())]  # instances of their own symbols
    tags = [t for t in [*families.instance_transforms(path), *rails] if t in link.bodies]
    instances = {}
    for t in tags:
        try:
            hit = link.instance(t)
        except (ValueError, KeyError, IndexError):
            hit = None
        if hit is not None:
            instances[t] = hit
    syms = list(dict.fromkeys(hit[0] for hit in instances.values()))  # in the order first placed
    styles = _style_categories(path)
    prims, meshes = {}, {}
    for sym, (ps, ms) in zip(syms, _symbols(link, syms, styles, PROCS)):
        prims[sym] = ps
        meshes.update(ms)
    return instances, prims, meshes


# the decoder modules a file's saved graphics (and so the selections kept of them) come from
MODULES = ("savedgraphics", "gelements", "objgraph", "registry", "families", "container", "pens")


def _write_whole(f, value):
    """Pickle `value` as the file `f`, whole or not at all (other processes read the folder)."""
    import pickle
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    tmp.write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    os.replace(tmp, f)


def _pack(value):
    """_compute's (instances, prims, meshes) for the disk cache, its arrays joined: every Prim's
    points (n, 3) in one array with their lengths, every mesh's verts and faces in one each.
    Pickled one by one, Snowdon Architectural's 110,000 point arrays and 7,600 meshes took 0.9 s
    to read back on each print; joined, 0.2 s (_unpack)."""
    instances, prims, meshes = value
    arrays, counts, slim = [], [], {}
    for sym, ps in prims.items():
        out = []
        for p in ps:
            arrays.extend(p.points)
            counts.append(len(p.points))
            q = dataclasses.replace(p, points=[])
            out.append(q)
        slim[sym] = out
    lengths = np.array([len(a) for a in arrays], dtype=np.int64)
    points = np.concatenate(arrays).astype(np.float64) if arrays else np.zeros((0, 3))
    keys = list(meshes)
    verts = [meshes[k][0] for k in keys]
    faces = [meshes[k][1] for k in keys]
    return ("packed", instances, slim, np.array(counts, dtype=np.int64), points, lengths, keys,
            np.concatenate(verts) if verts else np.zeros((0, 3), np.float32),
            np.array([len(v) for v in verts], dtype=np.int64),
            np.concatenate(faces) if faces else np.zeros((0, 3), np.int32),
            np.array([len(f) for f in faces], dtype=np.int64))


def _unpack(value):
    """_pack's value back as (instances, prims, meshes): the arrays are views of the joined ones."""
    if not (isinstance(value, tuple) and value and value[0] == "packed"):
        return value  # a cache from before packing
    _tag, instances, prims, counts, points, lengths, keys, verts, nverts, faces, nfaces = value
    parts = np.split(points, np.cumsum(lengths)[:-1]) if len(lengths) else []
    at = 0
    k = 0
    for ps in prims.values():
        for p in ps:
            n = int(counts[k])
            p.points = parts[at:at + n]
            at += n
            k += 1
    vs = np.split(verts, np.cumsum(nverts)[:-1]) if len(nverts) else []
    fs = np.split(faces, np.cumsum(nfaces)[:-1]) if len(nfaces) else []
    return instances, prims, dict(zip(keys, zip(vs, fs)))


@memory.per_model
def load(path):
    """Saved for a (linked) file, disk-cached against the decoders' source."""
    from ..core import diskcache
    instances, prims, meshes = _unpack(diskcache.cached(path, "saved_graphics", MODULES, lambda: _pack(_compute(path))))
    saved = Saved(path, instances, prims, meshes)
    saved.visibility = diskcache.cached(path, "nested_visibility", ("savedgraphics", "objgraph", "registry", "families", "container"),
                                        lambda: nested_visibility(path))
    # each graphics style's category: a family's lines in a subcategory the view hides (test02's
    # and Snowdon's views hide Light Source, -2001121) are not drawn
    saved.style_categories = _style_categories(path)
    return saved


PLAN_RCP = 0x08  # FamElemVisibility: shown in plan and ceiling plan views (Revit's Plan/RCP box)


def nested_visibility(path):
    """{element id: FamElemVisibility m_flags} of shared nested family instances, which the
    project keeps as elements of their own (their own records' flags are unset, -1): each takes
    the flags of the nested instance of its family and type in its parent family's document
    (oracle/test02: Window-Fixed's trims and muntins, 0xE036, Plan/RCP off; Revit's plan leaves
    them out). The parent names its nested elements in its saved graphics (GComponentRef ->
    InstanceInfo m_symbolId, an element id); the parent's type's family id is its embedded
    document (families.documents)."""
    from . import families
    link = Link(path)
    dec, bodies = link.decoder, objgraph.channel_bodies(path, 102)

    def fields(eid):
        try:
            return dec.graph(bodies[eid]).objects[0].fields
        except (KeyError, ValueError, IndexError):
            return None

    children = {}  # parent element -> nested element ids
    # a record holds a GComponentRef only if its class tag is among its bytes: an object is in a
    # graph as a pointer's target (the pointer stores the target's tag) or as the root (its first
    # two bytes); the others are not decoded (Snowdon Architectural: 50,530 records, 59 s of 121)
    ref = dec.reg.named("GComponentRef")
    if ref is None:
        return {}
    tag = struct.pack("<H", ref.tag)
    for eid, body in link.bodies.items():
        # decoded and dropped, not link.graph's memo: every graph of Snowdon Architectural at once is 2.7 GB
        if len(body) < 2 or tag not in body:
            continue
        g = link.decoder.graph(body)
        for i, o in enumerate(g.objects):
            if o.name == "GComponentRef":
                j = g.target(i, o.fields.get("m_instanceInfo"))
                if j is not None and g.objects[j].name == "InstanceInfo":
                    children.setdefault(eid, []).append(_id(g.objects[j].fields["m_symbolId"]))
    if not children:
        return {}
    recs = families.records(path)
    docs = families.documents(path, standalone=True)
    emb = recs.graph

    def proj(eid):
        try:
            return dec.graph(bodies[eid])
        except (KeyError, ValueError, IndexError):
            return None

    def type_key(sym_graph, graph_of):
        if sym_graph is None:
            return None
        f = sym_graph.objects[0].fields
        fam = graph_of(_id(f.get("m_familyId"))) if f.get("m_familyId") else None
        tname = next((o.fields.get("m_name") for o in sym_graph.objects if o.name == "SymbolInfo"), None)
        return (fam.objects[0].fields.get("m_name") if fam else None, tname)

    out = {}
    for parent, kids in children.items():
        pf = fields(parent)
        if not pf or "m_masterSymbolId" not in pf:
            continue
        sym = fields(_id(pf["m_masterSymbolId"]))
        doc = docs.get(_id(sym["m_familyId"])) if sym and sym.get("m_familyId") else None
        if doc is None:
            continue
        flags = {}
        for member in recs.of(("FamilyInstance",), doc.members):
            g = emb(member)
            if g is None:
                continue
            f = g.objects[0].fields
            key = type_key(emb(_id(f["m_masterSymbolId"])), emb)
            if key and key[0]:
                flags.setdefault(key, f["m_famElemVisibility"]["m_flags"])
        for kid in kids:
            kf = fields(kid)
            if not kf or "m_masterSymbolId" not in kf:
                continue
            key = type_key(proj(_id(kf["m_masterSymbolId"])), proj)
            if key in flags:
                out[kid] = flags[key]
    return out
