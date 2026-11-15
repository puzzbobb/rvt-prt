"""Schedules on sheets: element schedules as tables, revision schedules and sheet lists."""

from .. import pdf
from ..model import pens
from . import state
from .primitives import PT
from .text import put_text, text_len


# Schedule styles measured on Revit's print (TableCellStyle is not decoded): sizes in pt, rows in
# inches. Revision table: header 19 pt centred in a 0.384 in row, body 12.5 pt in 0.256 in rows,
# 0.037 in from the column's left. Sheet Index: title 19 pt bold, header 12.5 pt bold, body
# 12.5 pt in 0.2395 in rows.
ROW_PER_PT = 1.455  # a schedule row's height per point of its text's printed size (Trebuchet MS)
# ... by font, where it differs: Arial rows are lower (Snowdon's Sheet Index, 12.5 pt in 17.25 pt
# rows; M002's tables, 17.28 pt), Trebuchet MS's 1.455 (test02 9.5 pt in 13.84; Snowdon's
# revision header 19 pt in 27.6)
ROW_PER_PT_BY_FAMILY = {"arial": 1.38}


def row_per_pt(font):
    """ROW_PER_PT for a (family, bold, italic) font."""
    family = font[0] if isinstance(font, tuple) else str(font)
    return ROW_PER_PT_BY_FAMILY.get(family.lower(), ROW_PER_PT)


BORDER_STYLE = -2000042  # the line style schedule cells' borders name (TableCellStyle m_border*LineStyle)


SCHEDULE_STYLES = {
    "revision": dict(title=None, head=(19.0, ("Trebuchet MS", False, False), 0.3838),
                     body=(12.5, ("Trebuchet MS", False, False), 0.2559)),
    "list": dict(title=(19.0, ("Trebuchet MS", True, False), 0.37), head=(12.5, ("Trebuchet MS", True, False), 0.27),
                 body=(12.5, ("Arial", False, False), 0.2395)),
}


# element schedules (M002, measured): title row 0.42 in, header and body rows 0.24 in, all Arial
# 12.5 pt, text 0.04 in from the column's left; header and data cells carry their own 0.24 pt
# borders, blank and footer rows none
TABLE_STYLE = dict(title=(12.5, ("Arial", False, False), 0.42), row=(12.5, ("Arial", False, False), 0.24))


ALIGN = {0: "left", 1: "centre", 2: "right"}


def cell_font(style, fallback):
    """(size pt, font spec) of a decoded CellStyle, else the measured fallback."""
    if style is None:
        return fallback
    return style.size_pt, (style.font, style.bold, False)


def draw_table(page, so):
    sc = so.schedule
    _s, _f, title_h = TABLE_STYLE["title"]
    _s, _f, row_h = TABLE_STYLE["row"]
    title_font = cell_font(sc.title_style, TABLE_STYLE["title"][:2])
    ncol = len(sc.columns)
    head = [(cell_font(c, TABLE_STYLE["row"][:2]), ALIGN.get(c.halign, "centre")) for c in sc.header_styles] or [(TABLE_STYLE["row"][:2], "centre")] * ncol
    bodyst = [(cell_font(c, TABLE_STYLE["row"][:2]), ALIGN.get(c.halign, "left")) for c in sc.body_styles] or [(TABLE_STYLE["row"][:2], "left")] * ncol
    H = page.rect.height
    x0, y = so.origin[0] * PT, H - so.origin[1] * PT
    xs = [x0]
    for _n, w in so.schedule.columns:
        xs.append(xs[-1] + w * PT)
    shape = page.new_shape()

    def text(cx, cw, top, h, t, sf, align):
        if t:
            size, font = sf
            w = text_len(t, font, size)
            tx = {"centre": cx + (cw - w) / 2, "left": cx + 0.04 * 72, "right": cx + cw - 0.04 * 72 - w}[align]
            put_text(page, (tx, top + h / 2 + 0.35 * size), t, fontname=font, fontsize=size)

    def cells(top, h):
        for a, b in zip(xs, xs[1:]):
            shape.draw_rect(pdf.Rect(a, top, b, top + h))

    if so.schedule.name:
        shape.draw_rect(pdf.Rect(xs[0], y, xs[-1], y + title_h * 72))
        text(xs[0], xs[-1] - xs[0], y, title_h * 72, so.schedule.name, title_font, ALIGN.get(sc.title_style.halign if sc.title_style else 1, "centre"))
        y += title_h * 72
    h = row_h * 72
    cells(y, h)
    for (name, _w), a, b, (sf, al) in zip(so.schedule.columns, xs, xs[1:], head):
        text(a, b - a, y, h, name, sf, al)
    y += h
    for kind, row in so.table:
        if kind == "row":
            cells(y, h)
        for i, (t, a, b) in enumerate(zip(row, xs, xs[1:])):
            # footers and totals start in the first column and run on, as Revit prints them
            sf, al = bodyst[i] if i < len(bodyst) else bodyst[-1]
            text(a, b - a, y, h, t, sf, "left" if kind != "row" else al)
        y += h
    shape.finish(color=(0, 0, 0), width=0.24)
    shape.commit()


def _style_width(style):
    """The printed width (pt) of a line style's (a category's) annotation pen, or None."""
    if not state.PEN_PATH or style is None:
        return None
    pen = pens.category_pens(state.PEN_PATH).get(style, {}).get(pens.PROJECTION)
    return pens.annotation_width_pt(state.PEN_PATH, pen) if pen else None


def draw_schedule(page, so):
    if so.table is not None:
        return draw_table(page, so)
    heads = [c[0] for c in so.schedule.columns]
    kind = "revision" if heads[:3] == ["No.", "Description", "Date"] else "list"
    st = SCHEDULE_STYLES[kind]
    H = page.rect.height
    x0, top = so.origin[0] * 12 * 72, H - so.origin[1] * 12 * 72
    widths = [w * 12 * 72 for _, w in so.schedule.columns]
    x1 = x0 + sum(widths)
    y = top
    shape = page.new_shape()

    def text_in(cell_x, cell_w, row_top, row_h, text, size, font, align):
        w = text_len(text, font, size)
        tx = {"centre": cell_x + (cell_w - w) / 2, "left": cell_x + 0.037 * 72, "right": cell_x + cell_w - 0.037 * 72 - w}[align]
        put_text(page, (tx, row_top + row_h / 2 + 0.35 * size), text, fontname=font, fontsize=size)

    sc = so.schedule
    ncol = len(widths)
    # fonts, sizes, bold and alignment from the file (Schedule.*_style); heights as measured
    head = [(*cell_font(c, st["head"][:2]), ALIGN.get(c.halign, "centre")) for c in sc.header_styles] or [(*st["head"][:2], "centre")] * ncol
    body = [(*cell_font(c, st["body"][:2]), ALIGN.get(c.halign, "left")) for c in sc.body_styles] or [(*st["body"][:2], "left")] * ncol
    if st["title"] and so.schedule.name and not so.schedule.name.startswith("<"):
        size, font = cell_font(sc.title_style, st["title"][:2])
        h = st["title"][2]
        if sc.title_height:  # at least its stored height (feet), else the measured one
            h = max(sc.title_height * 12, ROW_PER_PT * size / 72)
        text_in(x0, x1 - x0, y, h * 72, so.schedule.name, size, font, ALIGN.get(sc.title_style.halign, "centre") if sc.title_style else "centre")
        y += h * 72
    # a row is 1.455 times its text's printed size (test02: 9.5 pt text, 13.84 pt rows; Snowdon's
    # revision header 19 pt, 0.384 in); the measured heights where no style is decoded
    row_in = lambda styles, fallback: max(s[0] * row_per_pt(s[1]) for s in styles) / 72 if (sc.header_styles if styles is head else sc.body_styles) else fallback
    h = row_in(head, st["head"][2])
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    for (name, _), cx, cw, (size, font, al) in zip(so.schedule.columns, xs, widths, head):
        text_in(cx, cw, y, h * 72, name, size, font, al)
    head_top = y
    y += h * 72
    shape.draw_line(pdf.Point(x0, y), pdf.Point(x1, y))
    h = row_in(body, st["body"][2])
    bottom = top + so.schedule.fixed_height * 12 * 72 if so.schedule.fixed_height else None
    rows = list(so.rows)
    while bottom is not None and y + (len(rows) + 1) * h * 72 <= bottom + 0.01:
        rows.append([""] * len(widths))  # a fixed-height table shows empty rows to its height
    for row in rows:
        for text, cx, cw, (size, font, al) in zip(row, xs, widths, body):
            if text:
                text_in(cx, cw, y, h * 72, text, size, font, al)
        y += h * 72
        shape.draw_line(pdf.Point(x0, y), pdf.Point(x1, y))
    end = y  # the last row's line (test02: Revit's grid stops there, short of the fixed height)
    for cx in xs:
        shape.draw_line(pdf.Point(cx, head_top), pdf.Point(cx, end))
    # the cells' border line style (-2000042) gives the grid's annotation pen (test02 pen 2,
    # 1.42 pt, frame included; Snowdon pen 1); the measured widths where it is not known
    inner = _style_width(sc.grid_style or BORDER_STYLE)
    shape.finish(color=(0, 0, 0), width=inner or 0.24, closePath=False)
    shape.draw_rect(pdf.Rect(x0, top, x1, end))
    # the outline in its own line style where the schedule names one (Snowdon's Sheet Index: Wide
    # Lines, pen 5, 1.3 pt), else the grid's
    shape.finish(color=(0, 0, 0), width=(_style_width(sc.outline_style) if sc.outline_style else None) or inner or 0.58)
    shape.commit()
