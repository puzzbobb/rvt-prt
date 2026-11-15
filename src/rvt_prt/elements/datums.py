"""View references and datums drawn in views: elevation markers and section lines in plans,
level lines in sections and elevations. They have no saved graphics (their channel-103 records
are dummies); Revit draws them from their records and their types.

Decoded (oracle/test02, against Revit's DXF and PDF), from element records' object graphs:
- InteriorElev (an elevation marker): `m_pos` (model feet), `m_symbolId` the view type
  (DBViewType `m_elevatnAttrId` -> InteriorElevAttributes: `m_width` the marker's diameter on
  paper (feet), `m_shape` 1 circle, `m_elevationSymbolId` its family, -1 for Revit's own),
  `m_arrowIds`. Each InteriorElevArrow is the elevation's Viewer: its `m_boundedSpace` basis's
  third row is the direction the elevation looks. Revit draws, without a family, the circle
  (radius m_width / 2, centred on m_pos) and per arrow a line from the circle outward along the
  looking direction, m_width / 2 long, all at paper size.
- Section (a section's Viewer): `m_frontCut` [[x, y, z] x 2], the section line drawn in plans;
  its type's SectionAttributes `m_sectionHeadFamilyTagId` / `m_sectionTailFamilyTagId` -1: no
  heads (not drawn here yet when a type has them).
- Level: its datum plane's `Plane.m_Envelope` corners (plane coordinates along m_xVec / m_yVec
  from m_origin, at the level's height): in a section or elevation the level line spans the
  envelope seen along the view's right axis (test02's elevations: 0..30 ft, -15..15 ft as Revit;
  its section's line ends 5.5 ft short at one end, a per-view extent not found). The level type's
  `m_familyTagId` -1: no head.
All print at annotation pen 1 in test02 (0.85 pt); their categories' pens are not decoded.

Which plans show a marker or section: those whose cut plane lies within its Viewer's vertical
extent (m_boundedSpace: origin z and the up axis's bounds), at a scale no coarser than its
`m_coarserScale` (Revit's "Hide at scales coarser than": 0.01 is 1:100).
"""
import functools

import numpy as np

from ..model.pens import _records


@functools.cache
def read(path):
    """(markers [(position, radius ft on paper, [(looking direction, extent)])], section lines
    [((p0, p1), extent)], levels [(height, [4 envelope corners xy])]); an extent is (z low,
    z high, coarsest scale shown)."""
    from ..core import diskcache
    return diskcache.cached(path, "datums", ("datums", "pens", "objgraph", "registry"), lambda: _read(path))


def _id(f, key):
    return f[key]["m_id"]["m_id64"]


def _extent(f):
    """(z low, z high, coarsest scale shown) of a Viewer record's fields."""
    bs = f["m_boundedSpace"]
    z0 = bs["m_orig"][2]
    up = np.asarray(bs["m_basis"][1], float)
    (hi, lo) = bs["m_boundOffset"][1]
    zs = [z0 + up[2] * hi, z0 + up[2] * lo]
    return min(zs), max(zs), f.get("m_coarserScale", 0.0)


def _read(path):
    recs = {}
    for name in ("InteriorElev", "InteriorElevArrow", "Section", "Level", "DBViewType", "InteriorElevAttributes"):
        recs[name] = {eid: g.objects for eid, g in _records(path, name)}
    looks = {eid: (objs[0].fields["m_boundedSpace"]["m_basis"][2], _extent(objs[0].fields))
             for eid, objs in recs["InteriorElevArrow"].items()}
    markers = []
    for _eid, objs in recs["InteriorElev"].items():
        f = objs[0].fields
        width = 0.5 / 12  # Revit's default marker
        vt = recs["DBViewType"].get(_id(f, "m_symbolId"))
        if vt:
            attr = recs["InteriorElevAttributes"].get(_id(vt[0].fields, "m_elevatnAttrId"))
            if attr:
                width = attr[0].fields["m_width"]
        dirs = [looks[a["m_id"]["m_id64"]] for a in f.get("m_arrowIds", []) if a["m_id"]["m_id64"] in looks]
        markers.append((tuple(f["m_pos"]), width / 2, dirs))
    sections = [(tuple(map(tuple, objs[0].fields["m_frontCut"])), _extent(objs[0].fields)) for objs in recs["Section"].values()
                if objs[0].fields.get("m_frontCut")]
    levels = []
    for _eid, objs in recs["Level"].items():
        plane = next((o.fields for o in objs if o.name == "Plane"), None)
        if plane is None:
            continue
        o, xv, yv = (np.asarray(plane[k], float) for k in ("m_origin", "m_xVec", "m_yVec"))
        (u0, v0), (u1, v1) = plane["m_Envelope"]["m_corners"]
        corners = [tuple((o + u * xv + v * yv)[:2]) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]
        levels.append((float(o[2]), corners))
    return markers, sections, levels


def plan_marks(v, path):
    """[(kind, data)] in sheet feet for a plan viewport: ("circle", (centre, radius)) and ("line",
    (p, q)) of elevation markers and section lines inside its crop."""
    if not (v.view_basis and v.view_origin):
        return []
    markers, sections, _levels = read(path)
    (bx, by, _bz), o = v.view_basis, v.view_origin
    x0, y0, x1, y1 = v.crop or (-1e4, -1e4, 1e4, 1e4)

    def view(p):
        return ((p[0] - o[0]) * bx[0] + (p[1] - o[1]) * bx[1], (p[0] - o[0]) * by[0] + (p[1] - o[1]) * by[1])

    def sheet(u, w):
        return (v.offset[0] + v.scale * u, v.offset[1] + v.scale * w)

    cut = v.view_range[2] if v.view_range else None

    def shown(extent):
        lo, hi, coarsest = extent
        return (cut is None or lo - 1e-6 <= cut <= hi + 1e-6) and v.scale >= coarsest - 1e-12

    out = []
    for pos, r, dirs in markers:
        u, w = view(pos)
        dirs = [d for d, extent in dirs if shown(extent)]
        if not dirs or not (x0 <= u <= x1 and y0 <= w <= y1):
            continue
        c = sheet(u, w)
        out.append(("circle", (c, r)))
        for d in dirs:
            du, dw = d[0] * bx[0] + d[1] * bx[1], d[0] * by[0] + d[1] * by[1]
            n = np.hypot(du, dw)
            if n < 1e-9:
                continue
            du, dw = du / n, dw / n
            out.append(("line", ((c[0] + r * du, c[1] + r * dw), (c[0] + 2 * r * du, c[1] + 2 * r * dw))))
    for (p0, p1), extent in sections:
        if not shown(extent):
            continue
        (ua, wa), (ub, wb) = view(p0), view(p1)
        out.append(("line", (sheet(ua, wa), sheet(ub, wb))))
    return out


def section_levels(v, path):
    """[(p, q)] sheet feet: the level lines of a section or elevation viewport."""
    _m, _s, levels = read(path)
    right, up, _look = (np.asarray(b, float) for b in v.view_basis)
    o = np.asarray(v.view_origin, float)
    out = []
    for z, corners in levels:
        w = (np.array([0.0, 0.0, z]) - o) @ up
        if v.crop and not (v.crop[1] <= w <= v.crop[3]):
            continue
        us = [(np.array([x, y, z]) - o) @ right for x, y in corners]
        a, b = min(us), max(us)
        if b - a < 1e-6:
            continue
        out.append(((v.offset[0] + v.scale * a, v.offset[1] + v.scale * w), (v.offset[0] + v.scale * b, v.offset[1] + v.scale * w)))
    return out
