"""The sheet's paper: its title block (lines, texts, labels, images) and placed images."""

from .. import pdf
from ..model import pens
from . import state
from .primitives import PT, to_sheet
from .text import draw_text_block, scale_text


def label_value(param, sheet, project):
    from ..elements import titleblock as T
    f = sheet.fields
    scales = {round(1 / v.scale) for v in sheet.viewports if v.scale}
    return {
        T.SHEET_NUMBER: sheet.number, T.SHEET_NAME: sheet.name,
        T.SHEET_DRAWN_BY: f.get("drawn_by"), T.SHEET_CHECKED_BY: f.get("checked_by"),
        T.PRINT_DATE_TIME: state.PRINT_TIME.strftime("%d/%m/%Y %H:%M:%S"),
        T.SHEET_SCALE: (scale_text(1 / scales.pop()) if len(scales) == 1 else "As indicated") if scales else "",
    }.get(param, project.get(param, ""))


def draw_titleblock(page, tb, sheet, project):
    H = page.rect.height
    for im in tb.images:
        (cx, cy), (w, h) = im.centre, im.size
        place_image(page, pdf.Rect((cx - w / 2) * PT, H - (cy + h / 2) * PT, (cx + w / 2) * PT, H - (cy - h / 2) * PT), im.png)
    # each line at its graphics style's annotation pen (pens.py); 0.7 pt where not known
    by_width = {}
    for (x0, y0, x1, y1), pen in zip(tb.lines, getattr(tb, "pens", None) or [None] * len(tb.lines)):
        w = (pens.annotation_width_pt(state.PEN_PATH, pen) if state.PEN_PATH and pen else None) or 0.7
        by_width.setdefault(w, []).append((x0, y0, x1, y1))
    for w, lines in by_width.items():
        shape = page.new_shape()
        for x0, y0, x1, y1 in lines:
            shape.draw_line(pdf.Point(x0 * PT, H - y0 * PT), pdf.Point(x1 * PT, H - y1 * PT))
        shape.finish(color=(0, 0, 0), width=w, closePath=False)
        shape.commit()
    for t in tb.texts:
        draw_text_block(page, t.origin, t.width, t.flags, t.lines, t.size_pt, t.family, base=t.base, nominal=t.nominal_pt)
    for l in tb.labels:
        value = label_value(l.param, sheet, project)
        if value:
            draw_text_block(page, l.origin, l.width, l.flags, [(value, l.bold, l.italic)], l.size_pt, l.family, base=l.base, nominal=l.nominal_pt)


_IMAGE_CACHE = {}  # id(bytes) -> (compact bytes); xrefs per document in _XREFS


_XREFS = {}


def compact_image(data):
    """A compact stream for embedding: TIFF and BMP are decoded and stored as JPEG (photos, no
    alpha) or PNG; JPEG and PNG pass through."""
    key = id(data)
    if key not in _IMAGE_CACHE:
        if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
            _IMAGE_CACHE[key] = data
        else:
            _IMAGE_CACHE[key] = pdf.image_stream(data)
    return _IMAGE_CACHE[key]


def place_image(page, rect, data):
    """Embed an image once per document; later pages reuse its xref."""
    doc = page.parent
    if not hasattr(doc, "_xrefs"):
        doc._xrefs = {}
    data_id = id(data)
    if data_id in doc._xrefs:
        pdf.insert_image(page, rect, xref=doc._xrefs[data_id])
    else:
        doc._xrefs[data_id] = pdf.insert_image(page, rect, stream=compact_image(data))


def draw_images(page, v, images):
    """Images owned by the viewport's view (or, for the sheet's own 'viewport', the sheet)."""
    if not (v.view_basis and v.view_origin and v.crop):
        return 0
    H = page.rect.height
    n = 0
    for im in images:
        if im.owner_view != v.view_id:
            continue
        x, y = to_sheet(v, im.centre)
        w, h = im.size[0] * v.scale, im.size[1] * v.scale
        try:
            place_image(page, pdf.Rect((x - w / 2) * PT, H - (y + h / 2) * PT, (x + w / 2) * PT, H - (y - h / 2) * PT), im.data)
            n += 1
        except Exception:
            pass
    return n
