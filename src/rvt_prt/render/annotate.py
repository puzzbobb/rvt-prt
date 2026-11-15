"""Annotations in a viewport: datums, grids, text notes, tags, detail curves, filled regions, room
tags, and annotation family instances on the sheet."""
import math

import numpy as np

from .. import pdf
from ..model import pens
from . import state
from .primitives import PT, draw_leader, in_crop, stroke_segments, to_sheet
from .text import ASCENT, LINE_PITCH, NOTE_PITCH, TB_ASCENT, TB_DESCENT, WRAP_WIDTH_FACTOR, annotations_cap, put_text, tb_font, text_len, wrap, wrap_runs

LEVELS = -2000240  # OST_Levels


def draw_datums(page, viewports):
    """Elevation markers and section lines in plans, level lines in sections and elevations
    (datums.py), at annotation pen 1 (test02's print; their categories' pens not decoded)."""
    from ..elements import datums
    from ..geometry import sections
    if state.PEN_PATH is None:
        return
    H = page.rect.height
    P = lambda p: pdf.Point(p[0] * PT, H - p[1] * PT)
    shape = page.new_shape()
    n = 0
    for v in viewports:
        try:
            if sections.is_section(v):
                if LEVELS in state.HIDDEN.get(v.view_id, ()):
                    continue  # Golden Nugget's sections and elevations all hide their 100 levels
                marks = [("line", seg) for seg in datums.section_levels(v, state.PEN_PATH)]
            elif v.view_range:
                marks = datums.plan_marks(v, state.PEN_PATH)
            else:
                continue
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        for kind, data in marks:
            if kind == "circle":
                (c, r) = data
                shape.draw_circle(P(c), r * PT)
            else:
                shape.draw_line(P(data[0]), P(data[1]))
            n += 1
    if n:
        shape.finish(color=(0, 0, 0), width=pens.annotation_width_pt(state.PEN_PATH, 1) or 0.5, closePath=False)
        shape.commit()


def draw_grids(page, viewports, grids):
    """Grids on a sheet's plan viewports (see grids.py). A viewport draws the part of each grid
    within its crop grown by the type's end segment length; the parts that aligned viewports
    (same placement) draw are joined into one line, with the head at its bubble end."""
    from shapely.geometry import LineString, Point, box as sbox
    from ..elements import grids as G
    H = page.rect.height
    runs = {}  # (grid, placement) -> [t0, t1, viewport, unit, a, grid, type]
    for v in viewports:
        if not (grids and v.crop and v.view_basis and v.view_origin and v.view_id in state.PLAN_VIEWS):
            continue
        (bx, by, _bz), o = v.view_basis, v.view_origin
        view = lambda p, bx=bx, by=by, o=o: ((p[0] - o[0]) * bx[0] + (p[1] - o[1]) * bx[1], (p[0] - o[0]) * by[0] + (p[1] - o[1]) * by[1])
        crop = sbox(*v.crop)
        place = (round(v.offset[0], 6), round(v.offset[1], 6), round(v.scale, 9), tuple(round(c, 6) for c in o[:2]), tuple(map(tuple, (bx, by))))
        for g in grids:
            gt = state.GRID_TYPES.get(g.type_id) or G.GridType(0.0, None)
            m = gt.end_length / v.scale  # model feet
            dx, dy = g.end[0] - g.start[0], g.end[1] - g.start[1]
            L = math.hypot(dx, dy)
            if L < 1e-6:
                continue
            u = (dx / L, dy / L)
            a = (g.start[0] - m * u[0], g.start[1] - m * u[1])  # the bubble end
            line = LineString([view(a), view((g.end[0] + m * u[0], g.end[1] + m * u[1]))])
            if not line.intersects(crop):
                continue
            x0, y0, x1, y1 = v.crop
            part = line.intersection(sbox(x0 - m, y0 - m, x1 + m, y1 + m))
            if part.is_empty or part.geom_type != "LineString":
                continue
            ts = sorted(line.project(Point(c)) for c in part.coords)
            key = (g.element_id, place)
            if key in runs:
                runs[key][0] = min(runs[key][0], ts[0])
                runs[key][1] = max(runs[key][1], ts[-1])
            else:
                runs[key] = [ts[0], ts[-1], v, u, a, g, gt]
    n = 0
    for t0, t1, v, u, a, g, gt in runs.values():
        sheet = lambda p: pdf.Point(to_sheet(v, (p[0], p[1], 0))[0] * PT, H - to_sheet(v, (p[0], p[1], 0))[1] * PT)
        at = lambda t: (a[0] + t * u[0], a[1] + t * u[1])
        r = gt.head_half[0] if gt.head_half else 0.0  # paper feet
        centre = sheet(at(t0 - r / v.scale))
        shape = page.new_shape()
        shape.draw_line(sheet(at(t0)), sheet(at(t1)))
        shape.finish(color=(0, 0, 0), width=0.24, dashes=gt.dashes, lineCap=0, closePath=False)
        if gt.head_curves:
            for pts in gt.head_curves:
                shape.draw_polyline([pdf.Point(centre.x + x * PT, centre.y - y * PT) for x, y, *_z in pts])
            shape.finish(color=(0, 0, 0), fill=(1, 1, 1), width=0.24, closePath=False)
        elif r:
            shape.draw_circle(centre, r * PT)
            shape.finish(color=(0, 0, 0), fill=(1, 1, 1), width=0.24)
        shape.commit()
        if gt.size_ft:
            font = (gt.font, False, False)
            size = round(gt.size_ft * PT / annotations_cap() * 2) / 2
            w = text_len(g.name, font, size)
            put_text(page, (centre.x - w / 2, centre.y + (TB_ASCENT - (TB_ASCENT + TB_DESCENT) / 2) * size), g.name, fontsize=size, fontname=font)
        n += 1
    return n


# a note's first baseline below its top, x its size, by font: Arial's ascent (ASCENT, M101's notes);
# Trebuchet MS's notes sat 0.07 x their size high at it (M000: 1.8 pt at 25 pt, 0.6 at 9.5)
NOTE_ASCENT = {"trebuchet ms": 0.975}
NOTE_SLACK = 0.055  # points of a note's box a line may run over, x its size (draw_notes)


def draw_notes(page, v, notes):
    """Text notes owned by the viewport's view, hung from m_orig, wrapped at their width, in the
    RTF's font with its bold, italic and indented lines."""
    if not (v.view_basis and v.view_origin and v.crop):
        return 0
    H = page.rect.height
    n = 0
    for t in notes:
        if t.owner_view != v.view_id:
            continue
        if not in_crop(v, t.origin) and not any(in_crop(v, pt) for leader in (t.leaders or []) for pt in leader):
            continue
        for end, elbow, anchor in t.leaders or []:
            draw_leader(page, v, [anchor, elbow, end])
        x, y = to_sheet(v, t.origin)
        width = (t.width_ft or 1.0) * PT
        size = t.size_pt
        src = t.lines if t.lines else [(line, False, False, 0, 0) for line in t.text.split("\n")]
        while src and not src[-1][0].strip():
            src = src[:-1]
        lines = []  # (text, font, indent pt, hanging prefix, runs [(text, font)] or None)
        for text, bold, italic, indent, *rest in src:
            first = rest[0] if rest else 0
            runs = rest[1] if len(rest) > 1 else None
            font = (t.family, bold, italic)
            ind = indent / 20.0
            prefix = None
            if "\t" in text:  # a list item: the number hangs at indent + first-line indent
                prefix, text = text.split("\t", 1)
                if runs:  # the number is the first run's, up to the tab
                    head = next(k for k, r in enumerate(runs) if "\t" in r[0])
                    runs = [(r[0].split("\t", 1)[1], *r[1:]) if k == head else r for k, r in enumerate(runs) if k >= head]
            # slack in proportion to the size: Revit fits a box to its text, a little short (a 9.5 pt
            # line of 3.769 in in a 3.768 in box; 25 pt lines 1.0 and 1.3 pt over theirs, on M000)
            slack = NOTE_SLACK * size
            if runs:  # words of mixed style: each run in its own font (titleblock.rtf_lines)
                pieces = [(rt, (t.family, rb, ri)) for rt, rb, ri in runs if rt]
                fits = sum(text_len(rt, f, size) for rt, f in pieces) <= width - ind + slack
                factor = 1.0 if fits else WRAP_WIDTH_FACTOR.get(t.family.lower(), 1.0)
                for k, part in enumerate(wrap_runs(pieces, width - ind + slack, size, factor)):
                    lines.append(("".join(rt for rt, _f in part), font, ind,
                                  (prefix, ind + first / 20.0) if k == 0 and prefix else None, part))
                continue
            fits = text_len(text, font, size) <= width - ind + slack  # a box fitted to its text
            factor = 1.0 if fits else WRAP_WIDTH_FACTOR.get(t.family.lower(), 1.0)
            for k, part in enumerate(wrap(text, width - ind + slack, size, font, factor) if text else [""]):
                lines.append((part, font, ind, (prefix, ind + first / 20.0) if k == 0 and prefix else None, None))
        h_anchor, v_anchor = t.anchor()
        pitch = NOTE_PITCH.get(t.family.lower(), LINE_PITCH) * size
        left = x * PT - {"left": 0, "centre": width / 2, "right": width}[h_anchor]
        height = len(lines) * pitch
        top = H - y * PT - {"top": 0, "middle": height / 2, "bottom": height}[v_anchor]
        baseline = top + NOTE_ASCENT.get(t.family.lower(), ASCENT) * size
        for line, font, ind, hang, part in lines:
            if hang:
                put_text(page, (left + hang[1], baseline), hang[0], fontsize=size, fontname=font)
            if line:
                pieces = part or [(line, font)]
                w = sum(text_len(rt, f, size) for rt, f in pieces)
                lx = left + ind + {"left": 0, "centre": (width - ind - w) / 2, "right": width - ind - w}[t.align or h_anchor]
                for rt, f in pieces:
                    put_text(page, (lx, baseline), rt, fontsize=size, fontname=f)
                    lx += text_len(rt, f, size)
            baseline += pitch
        n += 1
    return n


def draw_annotation_instances(page, sheet, items):
    """Annotation family instances owned by the sheet's own view (generic annotations such as a
    "NOT FOR CONSTRUCTION" stamp), from their family documents (families.sheet_annotations): the
    family's curves and text notes through the instance transform (family and sheet units are
    both paper feet). A text hangs from its origin by its anchor flags (0x40/0x80/0x100 left,
    centre, right; 0x200/0x400/0x800 top, middle, bottom), turned by its base vector."""
    H = page.rect.height
    n = 0
    for owner, m, curves, texts, category in items:
        if owner != sheet.view_id or category == -2000280:  # title blocks are drawn by draw_titleblock
            continue
        for pts in curves:
            w = np.c_[np.array(pts), np.ones(len(pts))] @ m.T
            x, y = w[:, 0] * PT, w[:, 1] * PT
            stroke_segments(page, np.stack([x[:-1], x[1:]], 1), np.stack([y[:-1], y[1:]], 1), (0, 0, 0), 0.24)
        for t in texts:
            o = m @ np.r_[t.origin, 1]
            ang = math.degrees(math.atan2(t.base[1], t.base[0]))
            h_anchor = "centre" if t.flags & 0x80 else "right" if t.flags & 0x100 else "left"
            v_anchor = "middle" if t.flags & 0x400 else "bottom" if t.flags & 0x800 else "top"
            size = t.size_pt
            pitch = NOTE_PITCH.get(t.family.lower(), LINE_PITCH) * size
            src = [ln for ln in t.lines]
            while src and not src[-1][0].strip():
                src = src[:-1]
            height = len(src) * pitch
            top = {"top": 0, "middle": -height / 2, "bottom": -height}[v_anchor]
            c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            turn = lambda lx, ly: pdf.Point(o[0] * PT + lx * c + ly * s_, H - o[1] * PT - lx * s_ + ly * c)
            if t.boxed and src:
                # a boxed note: white-filled border, the width of its widest line, 1.257 x size a line
                widest = max(text_len(text, (t.family, bold, italic), size) for text, bold, italic, *_r in src)
                left = {"left": 0, "centre": -widest / 2, "right": -widest}[t.align or h_anchor]
                bh = len(src) * 1.257 * size
                btop = {"top": 0, "middle": -bh / 2, "bottom": -bh}[v_anchor]
                shape = page.new_shape()
                shape.draw_polyline([turn(left, btop), turn(left + widest, btop), turn(left + widest, btop + bh), turn(left, btop + bh)])
                shape.finish(color=(0, 0, 0), fill=(1, 1, 1), width=0.24, closePath=True)
                shape.commit()
            for k, (text, bold, italic, *_r) in enumerate(src):
                font = (t.family, bold, italic)
                w = text_len(text, font, size)
                lx = {"left": 0, "centre": -w / 2, "right": -w}[t.align or h_anchor]
                ly = top + ASCENT * size + k * pitch  # local, y down
                px = o[0] * PT + lx * c + ly * s_
                py = H - o[1] * PT - lx * s_ + ly * c
                pt = pdf.Point(px, py)
                put_text(page, pt, text, fontsize=size, fontname=font, morph=(pt, pdf.Matrix(ang)))
            n += 1
    return n


TAG_SIZE_PT = 9.5


ARIAL_LINE = 1.144  # a tag label's box height / its text size (0.151 in for 9.5 pt)


def draw_family_texts(page, head, angle, symbol, values):
    """A tag family's fixed texts and labels, at their offsets (paper feet) from the head,
    turned by `angle` (0 or 90 degrees counter-clockwise). Anchors by m_flags; labels are filled
    from `values` ({BuiltInParameter: text}); a label with no value is left out."""
    H = page.rect.height
    hx, hy = head[0] * PT, H - head[1] * PT
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    to_page = lambda x, y: (hx + x * ca - y * sa, hy - (x * sa + y * ca))
    items = [(t, t.lines, t.size_pt) for t in symbol.texts]
    for l in symbol.labels:
        value = values.get(l.param)
        if value:
            items.append((l, [(value, False, False)], l.height * 12 * 72 / ARIAL_LINE))
    family = getattr(symbol, "family", "Arial")
    n = 0
    for t, lines, size in items:
        lines = [x for x in lines if x[0]]
        if not lines:
            continue
        flags = t.flags
        h = "centre" if flags & 0x80 else "right" if flags & 0x100 else "left"
        vv = "middle" if flags & 0x400 else "bottom" if flags & 0x800 else "top"
        ox, oy = t.origin[0] * PT, t.origin[1] * PT  # local, y up
        pitch = LINE_PITCH * size
        height = len(lines) * pitch
        top = {"top": oy, "middle": oy + height / 2, "bottom": oy + height}[vv]
        base = top - ASCENT * size
        for text, bold, italic, *_ in lines:
            font = tb_font(bold, italic, getattr(t, "family", family))
            w = text_len(text, font, size)
            lx = {"left": ox, "centre": ox - w / 2, "right": ox - w}[h]
            put_text(page, to_page(lx, base), text, fontname=font, fontsize=size, rotate=angle)
            base -= pitch
        n += 1
    return n


def draw_tags(page, v, tags, axes):
    """Tag labels centred on their head; a duct's label turns with the duct (orientation 2,
    'align with element'), kept readable: horizontal or reading bottom-to-top."""
    if not (v.view_basis and v.view_origin and v.crop):
        return 0
    H = page.rect.height
    (bx, by, _bz) = v.view_basis
    n = 0
    for t in tags:
        if t.owner_view != v.view_id or not t.text or not in_crop(v, t.head):
            continue
        if t.leader:
            draw_leader(page, v, [t.head, t.leader[0], t.leader[1]])
        x, y = to_sheet(v, t.head)
        vertical = False
        if t.tagged in axes:
            (x0, y0), (x1, y1) = axes[t.tagged].coords[:2] if hasattr(axes[t.tagged], "coords") else axes[t.tagged]
            dx = (x1 - x0) * bx[0] + (y1 - y0) * bx[1]
            dy = (x1 - x0) * by[0] + (y1 - y0) * by[1]
            vertical = abs(dy) > abs(dx)
        symbol = (state.TAG_SYMBOLS or {}).get(t.symbol_id)
        if symbol is not None and (symbol.texts or symbol.labels):
            if draw_family_texts(page, (x, y), 90 if vertical else 0, symbol, t.values or {}):
                n += 1
                continue
        w = text_len(t.text, "helv", TAG_SIZE_PT)
        cx, cy = x * PT, H - y * PT
        mid = 0.35 * TAG_SIZE_PT  # half the cap height: baseline below the centre
        if vertical:
            put_text(page, (cx + mid, cy + w / 2), t.text, fontsize=TAG_SIZE_PT, fontname="helv", rotate=90)
        else:
            put_text(page, (cx - w / 2, cy + mid), t.text, fontsize=TAG_SIZE_PT, fontname="helv")
        n += 1
    return n


def draw_curves(page, v, curves):
    """Detail lines of the viewport's view, clipped to its crop (whole curves kept or dropped)."""
    if not (v.view_basis and v.view_origin and v.crop):
        return 0
    H = page.rect.height
    shape = page.new_shape()
    n = 0
    for c in curves:
        if c.owner_view != v.view_id or c.element_id in state.INVISIBLE or not any(in_crop(v, p) for p in c.points):
            continue
        pts = [pdf.Point(to_sheet(v, p)[0] * PT, H - to_sheet(v, p)[1] * PT) for p in c.points]
        shape.draw_polyline(pts)
        n += 1
    shape.finish(color=(0, 0, 0), width=0.5, closePath=False)
    shape.commit()
    return n


def draw_regions(page, v, regions, curves):
    """Filled regions of the viewport's view: the boundary curves polygonised, filled solid in the
    type's colour (white when masking), no stroke (see fills.py)."""
    from shapely.ops import polygonize, unary_union
    if not (regions and v.view_basis and v.view_origin):
        return 0
    H = page.rect.height
    by_id = {c.element_id: c for c in curves or []}
    n = 0
    for r in regions:
        if r.owner_view != v.view_id:
            continue
        segs = [tuple(tuple(round(x, 6) for x in to_sheet(v, p)) for p in by_id[i].points) for i in r.curve_ids if i in by_id]
        area = unary_union(list(polygonize(segs)))
        polys = getattr(area, "geoms", [area])
        shape = page.new_shape()
        for poly in polys:
            if poly.is_empty:
                continue
            shape.draw_polyline([pdf.Point(x * PT, H - y * PT) for x, y in poly.exterior.coords])
            n += 1
        shape.finish(color=None, fill=r.colour, width=0)
        shape.commit()
    return n


def draw_room_tags(page, v, tags, style=None):
    """Room tags of the viewport's view in its crop (see roomtags.py), all sizes paper points."""
    if not (tags and v.view_basis and v.view_origin and v.crop):
        return 0
    from ..elements import roomtags
    st = style or state.ROOM_TAG_STYLE or roomtags.TagStyle()
    H = page.rect.height
    S = lambda p: pdf.Point(to_sheet(v, p)[0] * PT, H - to_sheet(v, p)[1] * PT)
    bold, plain = (st.font_name, True, False), (st.font_name, False, False)
    n = 0
    for t in tags:
        if t.owner_view != v.view_id or not t.number or not in_crop(v, t.head or t.point):
            continue
        end = S(t.point)
        cx = end.x
        if t.head:
            head, elbow = S(t.head), S(t.elbow)
            shape = page.new_shape()
            shape.draw_polyline([head, elbow, end])
            shape.finish(color=(0, 0, 0), width=0.24, closePath=False)
            d = end - elbow if abs(end - elbow) > 1e-6 else end - head
            L = math.hypot(d.x, d.y)
            if L > 1e-6:
                shape.draw_line(end - d * (9 / L), end)
                shape.finish(color=(0, 0, 0), width=2.52, lineCap=0, closePath=False)
            shape.commit()
            cx = head.x
            if elbow.y > head.y + 0.5:  # elbow below on the page: the tag above the head
                base = head
            elif elbow.y < head.y - 0.5:
                base = pdf.Point(head.x, head.y + 37.1)
            else:
                w = max(2 * st.box_half_w, text_len(t.name, bold, st.font_size)) / 2
                cx = head.x + w if elbow.x < head.x else head.x - w
                base = pdf.Point(cx, head.y + 18.7)
            base = pdf.Point(cx, base.y)
        else:
            base = pdf.Point(end.x, end.y + st.box_y_offset)
        shape = page.new_shape()
        shape.draw_rect(pdf.Rect(base.x - st.box_half_w, base.y - st.box_h, base.x + st.box_half_w, base.y))
        shape.finish(color=(0, 0, 0), width=0.24)
        shape.commit()
        for text, font, dy in ((t.number, plain, st.num_dy), (t.name, bold, st.name_dy)):
            w = text_len(text, font, st.font_size)
            put_text(page, (base.x - w / 2, base.y - dy), text, fontsize=st.font_size, fontname=font)
        n += 1
    return n


def tag_axes(footprints):
    """Each duct's plan run for its tag's direction: its centreline, else its box's longer side."""
    axes = {}
    for f in footprints or []:
        if f.class_name == "FlexDuct":
            continue  # Revit prints flex-duct tags horizontal (Snowdon restrooms)
        if f.axis is not None:
            axes[f.element_id] = f.axis
        elif f.class_name == "Duct":
            x0, y0, x1, y1 = f.shape.bounds
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            axes[f.element_id] = ((x0, cy), (x1, cy)) if x1 - x0 >= y1 - y0 else ((cx, y0), (cx, y1))
    return axes
