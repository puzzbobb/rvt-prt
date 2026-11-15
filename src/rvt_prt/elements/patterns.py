"""Fill patterns (FillPatternElem) and hatching with them, from the records' object graphs.

FillPatternElem.m_pFillPattern -> FillPattern: m_name and m_gridsArr -> FillGrid: m_angle (rad),
m_origin (u, v), m_deltas (shift, offset) and m_segs (dash, gap, dash, ... feet; a 0 dash is a
dot). Revit's Concrete (Snowdon 21874) is AutoCAD's AR-CONC / 300: grid 1 is 50°, origin 0,0,
shift 0.01377 (4.1298 / 300), offset -0.01966, dashes 0.0025 / 0.0275.
A material's cut pattern: MaterialElem.m_pMaterial -> Material m_name, m_cutPatternId.

A grid's lines pass through origin + k (shift·d + offset·n) for every integer k, d the direction
and n its left normal; along each line the dash list repeats from that point.
"""
import functools
import math
from dataclasses import dataclass


@dataclass
class Grid:
    angle: float
    origin: tuple
    shift: float
    offset: float
    segments: tuple


@functools.cache
def by_id(rf, path):
    """{FillPatternElem id: (name, [Grid])}."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, ("FillPatternElem",)):
        fp = next((o.fields for o in g.objects if o.name == "FillPattern"), None)
        grids = [Grid(o.fields["m_angle"], tuple(o.fields["m_origin"]), o.fields["m_deltas"][0], o.fields["m_deltas"][1],
                      tuple(o.fields.get("m_segs", ()))) for o in g.objects if o.name == "FillGrid"]
        if fp and grids:
            out[eid] = (fp.get("m_name", ""), grids)
    return out


@functools.cache
def read(rf, path):
    """{pattern name: [Grid]}."""
    return {name: grids for name, grids in by_id(rf, path).values()}


@functools.cache
def material_cut_patterns(rf, path):
    """{material name: cut FillPatternElem id} (Snowdon's "Concrete, Cast-in-Place gray": 21874,
    Concrete)."""
    from ..core import objgraph
    known = by_id(rf, path)
    out = {}
    for _eid, g in objgraph.elements(path, ("MaterialElem",)):
        m = next((o.fields for o in g.objects if o.name == "Material"), None)
        pid = objgraph.ref(m.get("m_cutPatternId")) if m else None
        if pid in known:
            out.setdefault(m.get("m_name", ""), pid)
    return out


def hatch(poly, grids, anchor=(0.0, 0.0), scale=1.0):
    """(dashes [(p, q)], dots [p]) of `grids` clipped to the shapely polygon `poly`, all in the
    polygon's units; the pattern's origin at `anchor`, its lengths times `scale`."""
    from shapely.geometry import LineString
    dashes, dots = [], []
    if poly.is_empty:
        return dashes, dots
    x0, y0, x1, y1 = poly.bounds
    corners = [(x0, y0), (x0, y1), (x1, y0), (x1, y1)]
    for g in grids:
        d = (math.cos(g.angle), math.sin(g.angle))
        n = (-d[1], d[0])
        off, sh = g.offset * scale, g.shift * scale
        if abs(off) < 1e-12:
            continue
        o = (anchor[0] + g.origin[0] * scale, anchor[1] + g.origin[1] * scale)
        ks = [((c[0] - o[0]) * n[0] + (c[1] - o[1]) * n[1]) / off for c in corners]
        period = sum(g.segments) * scale
        for k in range(math.floor(min(ks)), math.ceil(max(ks)) + 1):
            base = (o[0] + k * (sh * d[0] + off * n[0]), o[1] + k * (sh * d[1] + off * n[1]))
            ts = [(c[0] - base[0]) * d[0] + (c[1] - base[1]) * d[1] for c in corners]
            t0, t1 = min(ts), max(ts)
            line = LineString([(base[0] + t0 * d[0], base[1] + t0 * d[1]), (base[0] + t1 * d[0], base[1] + t1 * d[1])])
            inside = line.intersection(poly)
            if inside.is_empty:
                continue
            parts = getattr(inside, "geoms", [inside])
            for part in parts:
                if part.geom_type != "LineString":
                    continue
                (ax, ay), (bx, by) = part.coords[0], part.coords[-1]
                ta = (ax - base[0]) * d[0] + (ay - base[1]) * d[1]
                tb = (bx - base[0]) * d[0] + (by - base[1]) * d[1]
                ta, tb = min(ta, tb), max(ta, tb)
                if not g.segments or period <= 0:
                    dashes.append(((base[0] + ta * d[0], base[1] + ta * d[1]), (base[0] + tb * d[0], base[1] + tb * d[1])))
                    continue
                t = math.floor(ta / period) * period
                while t < tb:
                    s = t
                    for i, seg in enumerate(g.segments):
                        seg *= scale
                        if i % 2 == 0:
                            a, e = max(s, ta), min(s + seg, tb)
                            if seg == 0 and ta <= s <= tb:
                                dots.append((base[0] + s * d[0], base[1] + s * d[1]))
                            elif e > a:
                                dashes.append(((base[0] + a * d[0], base[1] + a * d[1]), (base[0] + e * d[0], base[1] + e * d[1])))
                        s += seg
                    t += period
    return dashes, dots


def _link_cut_patterns(path):
    """{material name: [Grid]} of a (linked) file: each material's cut pattern."""
    from ..core import container
    rf = container.open_file(path)
    table = by_id(rf, str(path))
    return {name: table[pid][1] for name, pid in material_cut_patterns(rf, str(path)).items() if pid in table}


@functools.cache
def link_cut_patterns(path):
    from ..core import diskcache
    return diskcache.cached(path, "cut_patterns", ("patterns", "objgraph", "registry"), lambda: _link_cut_patterns(path))
