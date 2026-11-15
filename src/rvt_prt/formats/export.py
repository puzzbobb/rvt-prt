"""Our views and sheets in the forms Revit exports, for comparison with Revit's own exports.

- view_drawing: a plan viewport's model linework in model feet (the model's internal
  coordinates), as Revit's DXF export of the view with family instances kept as blocks: each
  family symbol we draw becomes a block in its own coordinates (one per distinct geometry of a
  family), each instance an insert; the other linework (cut and projected meshes, stairs, the
  host's MEP footprints) lines on category layers, each grouped by its element.
- Sheets for DWFx come from render.write(fmt="drawings").
"""
import hashlib

import numpy as np

from ..core import categories
from ..geometry import linkgeom, model2d
from ..model import phases
from .. import render
from .drawing import Block, Drawing, Insert, Prim


def _model_from_view(v):
    """View (x, y) -> model XY for a plan viewport: o + x bx + y by."""
    (bx, by, _bz), o = v.view_basis, v.view_origin
    return lambda x, y: (o[0] + x * bx[0] + y * by[0], o[1] + x * bx[1] + y * by[1])


def _clip(segs, v):
    """(keep, model x (N, 2), model y (N, 2)): segments (model XY) clipped to the view's crop."""
    (bx, by, _bz), o = v.view_basis, v.view_origin
    arr = np.asarray(segs, dtype=np.float64)
    vx = (arr[:, :, 0] - o[0]) * bx[0] + (arr[:, :, 1] - o[1]) * bx[1]
    vy = (arr[:, :, 0] - o[0]) * by[0] + (arr[:, :, 1] - o[1]) * by[1]
    keep, vx, vy = render._clip_to_rect(vx, vy, v.crop)
    return keep, o[0] + vx * bx[0] + vy * by[0], o[1] + vx * bx[1] + vy * by[1]


def _group(owner, meta):
    eid, family, cat = owner if owner else (None, "", 0)
    if eid is None:
        return "", categories.name(cat)
    g = f"E{eid}"
    meta.setdefault(g, {"element": eid, "family": family, "category": categories.name(cat)})
    return g, categories.name(cat)


def view_drawing(v, link_items, footprints=(), hidden=frozenset(), hidden_filters=()):
    """A plan viewport's linework as a Drawing in model feet, or None for a view that is not a
    cropped plan with a view range."""
    if not (v.crop and v.view_basis and v.view_origin and v.view_range):
        return None
    (bx, by, _bz) = v.view_basis
    if abs(bx[2]) > 1e-6 or abs(by[2]) > 1e-6:
        return None
    bottom, _col, cut, depth, top_clip = v.view_range
    d = Drawing(v.view_name or str(v.view_id), "ft")
    sx, sy = v.scale * 12, v.scale * 12  # sheet inches = 12 (offset + scale (model - o) . basis)
    ox = 12 * v.offset[0] - sx * (v.view_origin[0] * bx[0] + v.view_origin[1] * bx[1])
    oy = 12 * v.offset[1] - sy * (v.view_origin[0] * by[0] + v.view_origin[1] * by[1])
    d.placement = (sx * bx[0], sy * by[0], sx * bx[1], sy * by[1], ox, oy)
    cx0, cy0, cx1, cy1 = v.crop
    d.crop = (12 * (v.offset[0] + v.scale * cx0), 12 * (v.offset[1] + v.scale * cy0),
              12 * (v.offset[0] + v.scale * cx1), 12 * (v.offset[1] + v.scale * cy1))
    geometry_blocks = {}  # (family, geometry digest) -> block name
    to_model = _model_from_view(v)
    x0, y0, x1, y1 = v.crop
    crop_model = np.array([to_model(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
    lo, hi = crop_model.min(0), crop_model.max(0)
    for items, _cut_patterns, symbols, stair_edges, grey in link_items:
        items = phases.visible(items, v.phase)
        top = max(depth, top_clip) if v.reflected else None
        inserts = []
        res = linkgeom.plan_lines(items, min(bottom, depth), cut, hidden, symbols, top, stair_edges, hidden_filters,
                                  view_top=top_clip, record=True, inserts=inserts, right=tuple(bx), detail=v.detail_level)
        cuts, proj, _regions, coloured = res[0], res[1], res[2], res[3]
        dashed = res[4] if len(res) > 4 else []
        layers = [(proj, "", grey, render.LINK_PROJ_PT), (cuts, " cut", grey, render.LINK_CUT_PT),
                  (dashed, " hidden", grey, render.LINK_PROJ_PT)]
        layers += [(segs, "", rgb, render.LINK_SYSTEM_PT) for rgb, segs in coloured.items()]
        for segs, suffix, colour, width in layers:
            if not len(segs):
                continue
            keep, mx, my = _clip(segs, v)
            by_owner = {}
            for i in np.nonzero(keep)[0].tolist():
                by_owner.setdefault(segs.owners[i], []).append(i)
            for owner, idx in by_owner.items():
                g, layer = _group(owner, d.meta)
                d.prims.append(Prim([[(mx[i, 0], my[i, 0]), (mx[i, 1], my[i, 1])] for i in idx], layer + suffix, g, colour, width))
        for owner, m, curves, kind in inserts:
            world = [(c @ m.T)[:, :2] for c in curves]
            pts = np.vstack(world)
            if (pts.max(0) < lo).any() or (pts.min(0) > hi).any():
                continue  # outside the crop
            g, layer = _group(owner, d.meta)
            layer += " cut" if kind == "cut" else ""
            family = owner[1] if owner else ""
            place = (m[0, 0], m[1, 0], m[0, 1], m[1, 1], m[0, 3], m[1, 3])
            local = [np.round(c[:, :2], 6) for c in curves]
            if abs(m[2, 2]) < 1 - 1e-6:  # a tilted instance (a grille on a duct's side): its plan
                # projection is no affine image of its symbol's x and y, so its block is the
                # projected curves about its origin, placed by translation (Revit's DXF, too, places
                # a block for each)
                place = (1.0, 0.0, 0.0, 1.0, m[0, 3], m[1, 3])
                local = [np.round(w - m[:2, 3], 6) for w in world]
            digest = hashlib.sha1(b"".join(c.tobytes() for c in local)).hexdigest()[:10]
            name = geometry_blocks.get((family, digest))
            if name is None:
                n = sum(1 for f, _ in geometry_blocks if f == family)
                name = f"{family or 'Family'}" + (f" #{n + 1}" if n else "")
                geometry_blocks[(family, digest)] = name
                d.blocks[name] = Block(name, [Prim([c.tolist() for c in local], "0", "", None, 0.0)], family)
            d.inserts.append(Insert(name, place, g, layer))
    _footprints(d, v, footprints)
    return d


def _footprints(d, v, footprints):
    """The host's MEP elements in the view's band, outlines on their class's layer."""
    from shapely.geometry import Polygon
    bottom, _col, _cut, depth, top = v.view_range
    lo, hi = min(bottom, depth), top
    to_model = _model_from_view(v)
    x0, y0, x1, y1 = v.crop
    crop = Polygon([to_model(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
    for fp in footprints or ():
        if fp.saved or not model2d.in_band(fp, lo, hi):
            continue
        g = fp.shape.intersection(crop)
        if g.is_empty:
            continue
        rings = [list(p.exterior.coords) for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon"]
        if rings:
            group = f"E{fp.element_id}"
            d.meta.setdefault(group, {"element": fp.element_id, "family": fp.system, "category": fp.class_name})
            d.prims.append(Prim(rings, fp.class_name, group, model2d.colour(fp),
                                model2d.WIDTH_PT.get(fp.class_name, model2d.DEFAULT_WIDTH_PT), True))
