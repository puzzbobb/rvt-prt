"""Model linework in a viewport: the host's footprints, linked models' and the host's plan lines
(linkgeom), sections and elevations (sections.py), each line in its pen, cut patterns hatched."""
import numpy as np

from .. import pdf
from ..model import pens, phases
from . import state, viewlines
from .primitives import PT, _clip_to_rect, stroke_segments


def band(elevation):
    """A plan without a decoded view range: from its level to the next level above."""
    above = [z for z in state.STOREYS_FT.values() if z > elevation + 0.5]
    return elevation - 0.5, (min(above) if above else elevation + 20)


def draw_model_3d(page, v, footprints):
    """A 3D view as an orthographic projection with the view's camera (DBView m_origin, m_horzDir,
    m_vertDir, m_viewDir), far to near: ducts as strokes as wide as their diameter, other elements
    as their projected box filled white with a coloured outline (a painter's hidden-line), within
    the viewport's frame (unclipped, one box of Golden Nugget's 3D view, far off, whited out its
    sheet's title block)."""
    from shapely.geometry import LineString, MultiPoint
    from shapely.geometry import box as sbox
    from ..geometry import model2d
    if not v.camera:
        return 0
    o, hx, vy, vd = v.camera
    H = page.rect.height
    frame = sbox(v.frame[0] * PT, H - v.frame[3] * PT, v.frame[2] * PT, H - v.frame[1] * PT) if v.frame else None
    dot = lambda p, a: (p[0] - o[0]) * a[0] + (p[1] - o[1]) * a[1] + (p[2] - o[2]) * a[2]
    sheet = lambda p: pdf.Point((v.offset[0] + v.scale * dot(p, hx)) * PT, H - (v.offset[1] + v.scale * dot(p, vy)) * PT)
    items = []
    for fp in footprints:
        if fp.path3d:
            depth = sum(dot(p, vd) for p in fp.path3d) / len(fp.path3d)
            items.append((depth, fp, "path"))
        elif fp.box3d:
            lo, hi = fp.box3d
            centre = tuple((lo[i] + hi[i]) / 2 for i in range(3))
            items.append((dot(centre, vd), fp, "box"))
    items.sort(key=lambda t: t[0])  # the view direction points to the viewer: far first
    for _depth, fp, kind in items:
        rgb = model2d.colour(fp)
        shape = page.new_shape()
        if kind == "path":
            pts = [sheet(p) for p in fp.path3d]
            parts = [pts]
            if frame is not None:
                line = LineString([(p.x, p.y) for p in pts]).intersection(frame)
                parts = [[pdf.Point(x, y) for x, y in g.coords] for g in getattr(line, "geoms", [line])
                         if g.geom_type == "LineString" and not g.is_empty]
                if not parts:
                    continue
            for part in parts:
                shape.draw_polyline(part)
            w = max(fp.width * v.scale * PT, 0.6)
            shape.finish(color=rgb, width=w, closePath=False, lineCap=1)
        else:
            lo, hi = fp.box3d
            corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
            hull = MultiPoint([(p.x, p.y) for p in map(sheet, corners)]).convex_hull
            if frame is not None and hull.geom_type == "Polygon" and not frame.contains(hull):
                hull = hull.intersection(frame)
            if hull.geom_type != "Polygon" or hull.is_empty:
                continue
            shape.draw_polyline([pdf.Point(x, y) for x, y in hull.exterior.coords])
            shape.finish(color=rgb, fill=(1, 1, 1), width=0.4, closePath=True)
        shape.commit()
    return len(items)


def draw_model(page, v, footprints):
    """Footprints in the viewport's band, in view coordinates, clipped to its crop, on the sheet."""
    from shapely.affinity import affine_transform
    from shapely.geometry import box as sbox
    from ..geometry import model2d
    if not (v.crop and v.view_basis and v.view_origin):
        return 0
    (bx, by, _bz), o = v.view_basis, v.view_origin
    if abs(bx[2]) > 1e-6 or abs(by[2]) > 1e-6:
        return 0  # not a plan
    if v.view_range:
        bottom, _col, _cut, depth, top = v.view_range
        lo, hi = min(bottom, depth), top
    else:
        lo, hi = band(state.STOREYS_FT.get(v.view_name, o[2]))
    # model -> view: ((p - o) . bx, (p - o) . by); view -> sheet: offset + scale * view
    a, b, d, e = bx[0], bx[1], by[0], by[1]
    xoff = -(o[0] * bx[0] + o[1] * bx[1])
    yoff = -(o[0] * by[0] + o[1] * by[1])
    crop = sbox(*v.crop)
    H = page.rect.height
    n = 0
    shapes = {}
    for fp in footprints:
        if fp.saved or not model2d.in_band(fp, lo, hi):
            continue
        g = affine_transform(fp.shape, [a, b, d, e, xoff, yoff]).intersection(crop)
        if g.is_empty:
            continue
        n += 1
        g = affine_transform(g, [v.scale * PT, 0, 0, -v.scale * PT, v.offset[0] * PT, H - v.offset[1] * PT])
        shapes.setdefault((model2d.colour(fp), model2d.WIDTH_PT.get(fp.class_name, model2d.DEFAULT_WIDTH_PT)), []).append(g)
    for (rgb, width), geoms in shapes.items():
        shape = page.new_shape()
        for g in geoms:
            for poly in getattr(g, "geoms", [g]):
                if poly.geom_type != "Polygon":
                    continue
                pts = [pdf.Point(x, y) for x, y in poly.exterior.coords]
                if len(pts) > 2:
                    shape.draw_polyline(pts)
        shape.finish(color=rgb, width=width, closePath=True)
        shape.commit()
    return n


LINK_GREY = (0.67, 0.67, 0.67)  # Revit's halftone for linked models (M101)


LINK_CUT_PT, LINK_PROJ_PT = 0.86, 0.24  # cut walls and projection, as printed


LINK_SYSTEM_PT = 1.3  # a linked MEP element in its system colour (as the host's ducts print)


HATCH_PT = 0.24  # cut patterns' lines (width not decoded yet: the thinnest pen as printed)


CROP_MARGIN = 3.0  # feet of the model around a plan's crop whose elements are still walked (in_crop)
_BOXES = {}  # {id(items list): (items list, plan boxes (n, 2, 2))}: each model's, worked out once


def _boxes(items):
    """The plan boxes ((n, 2, 2): min and max x, y, model feet) of a model's items, worked out once
    a list (and so before the sheets' processes fork, where they are first asked for there)."""
    hit = _BOXES.get(id(items))
    if hit is None or hit[0] is not items:
        b = np.zeros((len(items), 2, 2))
        for i, it in enumerate(items):
            if len(it.verts):
                b[i, 0], b[i, 1] = it.verts[:, :2].min(axis=0), it.verts[:, :2].max(axis=0)
        hit = _BOXES[id(items)] = (items, b)
    return hit[1]


def in_crop(items, v):
    """The items whose plan box reaches the view's crop (CROP_MARGIN around it): what lies wholly
    outside it draws nothing there, as its lines are clipped to the crop, and hides nothing inside
    it, as a plan looks straight down. Of the elements Snowdon's plans walked, 58% lay outside
    their crop, and a campus of linked models leaves most of each model outside any one view."""
    if not items or not v.crop:
        return items
    (bx, by, _bz), o = v.view_basis, v.view_origin
    b = _boxes(items)
    xs, ys = b[:, :, 0] - o[0], b[:, :, 1] - o[1]  # (n, 2): min, max
    corners_x = np.stack([xs[:, i] * bx[0] + ys[:, j] * bx[1] for i in (0, 1) for j in (0, 1)], axis=1)
    corners_y = np.stack([xs[:, i] * by[0] + ys[:, j] * by[1] for i in (0, 1) for j in (0, 1)], axis=1)
    x0, y0, x1, y1 = v.crop
    m = CROP_MARGIN
    keep = ((corners_x.max(axis=1) >= min(x0, x1) - m) & (corners_x.min(axis=1) <= max(x0, x1) + m)
            & (corners_y.max(axis=1) >= min(y0, y1) - m) & (corners_y.min(axis=1) <= max(y0, y1) + m))
    if keep.all():
        return items
    return [it for it, k in zip(items, keep) if k]


def _view_key(k, symbols, v, bottom, cut, hidden, top, filters, view_top, right):
    """What a plan view's linework of the model `k` depends on, beside the models' files and the
    code (viewlines.folder): the model and its placement, and the view's range, direction, detail
    level, phase and what it hides."""
    # the model by its file and placement, not its place in the list (`k`): the sheet batches
    # (render.batches) list a different set of models each
    place = getattr(symbols, "place", None)
    return (getattr(getattr(symbols, "saved", None), "path", None), None if place is None else place.tobytes().hex(),
            bottom, cut, sorted(hidden), top, repr(filters), view_top, right, v.detail_level, repr(v.phase),
            _rounded((v.crop, v.view_origin, v.view_basis)), CROP_MARGIN)


def draw_links(page, v, link_items):
    """A linked model's plan linework for a plan viewport: elements cut by the view's cut plane
    (heavier) and those below it down to the view's bottom, in the source's pen colour (links halftone), clipped to the crop.
    `link_items` is [(items, {material name: cut pattern grids})] per link (the link file's own
    Material.m_cutPatternId). A cut element of one material is hatched with that material's cut
    pattern, as a drafting pattern anchored at the model origin on the sheet; elements of several
    layers are not (the IFC meshes carry no layer geometry)."""
    from shapely.affinity import affine_transform
    from shapely.geometry import box as sbox
    from ..geometry import linkgeom
    from ..elements import patterns
    if not (link_items and v.crop and v.view_basis and v.view_origin and v.view_range):
        return 0
    (bx, by, _bz), o = v.view_basis, v.view_origin
    if abs(bx[2]) > 1e-6 or abs(by[2]) > 1e-6:
        return 0
    bottom, _col, cut, depth, _top = v.view_range
    # model XY -> sheet feet, for hatching in paper units
    a, b_, c, d = v.scale * bx[0], v.scale * by[0], v.scale * bx[1], v.scale * by[1]
    ox = v.offset[0] - v.scale * (o[0] * bx[0] + o[1] * bx[1])
    oy = v.offset[1] - v.scale * (o[0] * by[0] + o[1] * by[1])
    to_paper = [a, c, b_, d, ox, oy]
    crop_paper = affine_transform(sbox(*v.crop), [v.scale, 0, 0, v.scale, v.offset[0], v.offset[1]])
    n = 0
    for k, (items, cut_patterns, symbols, stair_edges, grey) in enumerate(link_items):
        # the walk limited to the crop (on the model's own list, whose boxes are worked out once);
        # a ceiling plan's occluders the whole model's (plan_lines' occluder_items)
        all_items = phases.visible(items, v.phase) if v.reflected else None
        items = phases.visible(in_crop(items, v), v.phase)
        top = max(depth, _top) if v.reflected else None  # a ceiling plan looks up to its view depth
        hidden, filters = state.HIDDEN.get(v.view_id, frozenset()), state.HIDDEN_FILTERS.get(v.view_id, ())
        compute = lambda: linkgeom.plan_lines(items, min(bottom, depth), cut, hidden, symbols, top, stair_edges, filters, view_top=_top,  # noqa: E731, B023
                                              record=True, right=tuple(bx), detail=v.detail_level,
                                              occluder_items=all_items)
        res = viewlines.kept(_view_key(k, symbols, v, min(bottom, depth), cut, hidden, top, filters, _top, tuple(bx)), compute)
        cuts, proj, regions, coloured = res[0], res[1], res[2], res[3]
        dashed = res[4] if len(res) > 4 else []
        source = getattr(getattr(symbols, "saved", None), "path", None)
        layers = [(s, w, c, d, "") for s, w, c, d in _by_pen(proj, pens.PROJECTION, v.scale, LINK_PROJ_PT, source, grey)]
        layers += [(s, w, c, d, " cut") for s, w, c, d in _by_pen(cuts, pens.CUT, v.scale, LINK_CUT_PT, source, grey)]
        if dashed:
            layers.append((dashed, LINK_PROJ_PT, grey, "3 2", " hidden"))
        layers += [(segs, LINK_SYSTEM_PT, rgb, None, "") for rgb, segs in coloured.items()]
        for layer_item in layers:
            segs, width, colour, dashes, suffix = layer_item
            if not len(segs):
                continue
            arr = np.asarray(segs, dtype=np.float64)  # (N, 2, 2) model XY
            vx = (arr[:, :, 0] - o[0]) * bx[0] + (arr[:, :, 1] - o[1]) * bx[1]
            vy = (arr[:, :, 0] - o[0]) * by[0] + (arr[:, :, 1] - o[1]) * by[1]
            keep, vx, vy = _clip_to_rect(vx, vy, v.crop)
            n += int(keep.sum())
            if state.RECORD is not None:
                record_segments(segs.owners, keep, (v.offset[0] + v.scale * vx) * 12, (v.offset[1] + v.scale * vy) * 12,
                                suffix, colour, width)
                continue
            stroke_segments(page, (v.offset[0] + v.scale * vx[keep]) * PT, (v.offset[1] + v.scale * vy[keep]) * PT,
                            colour, width, dashes=dashes)
        hx, hy = [], []
        for mats, area in regions:
            grids = cut_patterns.get(mats)
            if not grids:
                for lay in mats.split("|"):
                    lay_s = lay.strip()
                    if lay_s in cut_patterns:
                        grids = cut_patterns[lay_s]
                        break
            if not grids:
                continue
            region = affine_transform(area, to_paper).intersection(crop_paper)
            dashes, dots = patterns.hatch(region, grids, (ox, oy))
            for p, q in dashes:
                hx.append((p[0], q[0]))
                hy.append((p[1], q[1]))
            for p in dots:
                hx.append((p[0], p[0] + 0.1 / PT))
                hy.append((p[1], p[1]))
        if hx and state.RECORD is not None:
            from ..formats.drawing import Prim
            state.RECORD.append(Prim([[(a * 12, c * 12), (b * 12, d * 12)] for (a, b), (c, d) in zip(hx, hy)], "hatch", "", grey, HATCH_PT))
        elif hx:
            stroke_segments(page, np.array(hx) * PT, np.array(hy) * PT, grey, HATCH_PT)
    return n


_SECTION_LINES = {}  # {draw_section key: sections.lines result}: the last few sections drawn


def _rounded(x, places=6):
    """Nested tuples of floats rounded (a key: copies of a view differ in the last digits)."""
    if isinstance(x, (tuple, list)):
        return tuple(_rounded(y, places) for y in x)
    return round(x, places) if isinstance(x, float) else x


def draw_section(page, v, link_items):
    """A section or elevation viewport's model linework (sections.py): cut at the view plane in
    cut pens, projected beyond it with hidden lines removed, each line in its category's pen,
    clipped to the crop."""
    from ..geometry import sections
    if not (link_items and sections.is_section(v)) or not v.scale:
        return 0  # no scale: a perspective 3D view looking level (Golden Nugget's "3D Fassade_Genehmigung"), not a section
    hidden = state.HIDDEN.get(v.view_id, frozenset())
    # views of one frame, depth, crop and phase (Golden Nugget's V1 / V2 / V3 - Schnitt, design
    # option variants on one sheet) draw the same lines: worked out once
    key = (id(link_items), _rounded((v.view_origin, v.view_basis, v.depth, v.crop)), hidden, v.detail_level, repr(v.phase))
    hit = _SECTION_LINES.get(key)
    if hit is None:
        items = [(phases.visible(it[0], v.phase),) + tuple(it[1:]) for it in link_items]
        hit = sections.lines(v, items, hidden, v.detail_level)
        if len(_SECTION_LINES) >= 4:  # a sheet's few: its viewports interleave them (V3, V1, V2)
            del _SECTION_LINES[next(iter(_SECTION_LINES))]
        _SECTION_LINES[key] = hit
    cuts, proj = hit
    grey = link_items[0][4]
    source = getattr(getattr(link_items[0][2], "saved", None), "path", None)  # the host's (sections draw the first source)
    layers = [(s, w, c, d, "") for s, w, c, d in _by_pen(proj, pens.PROJECTION, v.scale, LINK_PROJ_PT, source, grey)]
    layers += [(s, w, c, d, " cut") for s, w, c, d in _by_pen(cuts, pens.CUT, v.scale, LINK_CUT_PT, source, grey)]
    n = 0
    for segs, width, colour, dashes, suffix in layers:
        if not len(segs):
            continue
        arr = np.asarray(segs, dtype=np.float64)  # (N, 2, 2) view feet
        keep, vx, vy = _clip_to_rect(arr[:, :, 0], arr[:, :, 1], v.crop)
        n += int(keep.sum())
        if state.RECORD is not None:
            record_segments(segs.owners, keep, (v.offset[0] + v.scale * vx) * 12, (v.offset[1] + v.scale * vy) * 12,
                            suffix, colour, width)
            continue
        stroke_segments(page, (v.offset[0] + v.scale * vx[keep]) * PT, (v.offset[1] + v.scale * vy[keep]) * PT, colour, width,
                        dashes=dashes)
    return n


def _by_pen(segs, kind, scale, fallback, source=None, colour=None):
    """[(segments, width pt, colour, dashes)]: `segs` (an _Owned list) split by pen, colour and
    line pattern (dash lengths in points, None solid). A segment
    drawn in a family's graphics style (`.styles`, a GStyleElem of `source`, the file its saved
    graphics come from) takes that style's pen (projection lines) and colour; otherwise its
    element's category's pen from the model's Object Styles, cut or projection, at the view's
    scale (links By Host View take the host's), `fallback` where none. `colour` is the source's
    pen colour: a halftone link keeps its grey."""
    from ..geometry import linkgeom
    if not len(segs) or state.PEN_PATH is None:
        return [(segs, fallback, colour, None)]
    by_style = source is not None and colour == (0.0, 0.0, 0.0)
    style_pens = pens.style_pens(source) if by_style else {}
    style_rgb = pens.style_colours(source) if by_style else {}
    cat_rgb = pens.category_colours(state.PEN_PATH) if by_style else {}
    style_dash = pens.style_dashes(source) if source is not None else {}
    cat_dash = pens.category_dashes(state.PEN_PATH)
    groups, look = {}, {}
    styles = getattr(segs, "styles", None) or [None] * len(segs)
    for s, owner, style in zip(segs, segs.owners, styles):
        cat = owner[2] if owner else 0
        key = (cat, style)
        hit = look.get(key)
        if hit is None:
            w = None
            if style is not None and kind == pens.PROJECTION and style in style_pens:
                w = pens.model_width_pt(state.PEN_PATH, style_pens[style], scale)
            w = w or pens.category_width_pt(state.PEN_PATH, cat, kind, scale) or fallback
            rgb = style_rgb.get(style) if style is not None else None
            if rgb is None and by_style:  # its category's line colour (Object Styles)
                rgb = cat_rgb.get(cat, {}).get(kind)
            dash = style_dash.get(style) if style is not None else None
            if dash is None and (style is None or style not in style_dash):
                dash = cat_dash.get(cat, {}).get(kind)
            hit = look[key] = (w, rgb or colour, dash)
        gkey = ((owner[0] if owner and owner[0] is not None else -1),) + hit
        g = groups.get(gkey)
        if g is None:
            g = groups[gkey] = linkgeom._Owned()
        linkgeom._Owned.owner, linkgeom._Owned.style = owner, style
        g.append(s)
    linkgeom._Owned.style = None
    # element by element, in id order, as Revit's PDF draws them (test02: the window's frame lines,
    # then its trim's over them)
    return [(g, w, c, d) for (_e, w, c, d), g in sorted(groups.items(), key=lambda kv: kv[0][0])]


def record_segments(owners, keep, x, y, suffix, colour, width):
    """The kept segments ((N, 2) sheet-inch x, y) as one Prim per owning element, on its category's
    layer (+ suffix: " cut", " hidden"), grouped as "E<element id>"."""
    from ..core import categories
    from ..formats.drawing import Prim
    by = {}
    for i in np.nonzero(keep)[0].tolist():
        by.setdefault(owners[i], []).append(i)
    for owner, idx in by.items():
        eid, family, cat = owner if owner else (None, "", 0)
        group = f"E{eid}" if eid is not None else ""
        if group and group not in state.RECORD_META:
            state.RECORD_META[group] = {"element": eid, "family": family, "category": categories.name(cat)}
        state.RECORD.append(Prim([[(x[i, 0], y[i, 0]), (x[i, 1], y[i, 1])] for i in idx], categories.name(cat) + suffix, group,
                           colour, width))
