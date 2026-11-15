"""One sheet as one PDF page: everything on it, in Revit's drawing order."""

from .. import pdf
from ..model import pens
from . import state
from .primitives import PT
from .text import put_text, scale_text, text_len
from .linework import draw_links, draw_model, draw_model_3d, draw_section
from .annotate import draw_annotation_instances, draw_curves, draw_datums, draw_grids, draw_notes, draw_regions, draw_room_tags, draw_tags
from .paper import draw_images, draw_titleblock
from .tables import draw_schedule


def draw_sheet(doc, sheet, footprints=None, notes=None, tags=None, axes=None, curves=None, titleblock=None, project=None, images=None, schedules=None,
               fit=True):
    w, h = sheet.size
    page = doc.new_page(width=w * PT, height=h * PT)
    H = page.rect.height
    P = lambda x, y: pdf.Point(x * PT, H - y * PT)
    if titleblock is not None:
        draw_titleblock(page, titleblock, sheet, project or {})
    # viewport crop frames: Revit does not print them; state.SHOW_CROP draws them for checking
    shape = page.new_shape()
    for v in (sheet.viewports if state.SHOW_CROP else []):
        if v.frame:
            x0, y0, x1, y1 = v.frame
            shape.draw_rect(pdf.Rect(P(x0, y1), P(x1, y0)))
    shape.finish(color=(0.6, 0.6, 0.6), width=0.5, dashes="[6 4] 0")
    shape.commit()
    from ..geometry import sections
    for v in sheet.viewports:  # linked models first, under the host's elements
        if sections.is_section(v):
            if not state.NO_SECTION_LINES:
                draw_section(page, v, state.LINK_ITEMS)
        else:
            draw_links(page, v, state.LINK_ITEMS)
    draw_datums(page, sheet.viewports)
    draw_grids(page, sheet.viewports, state.GRIDS)
    if footprints:
        for v in sheet.viewports:
            if sections.is_section(v):
                continue  # drawn from the model's geometry (draw_section)
            if v.camera and not v.view_range and not (v.view_basis and abs(v.view_basis[2][2]) > 0.999):
                draw_model_3d(page, v, footprints)
            else:
                draw_model(page, v, footprints)
    own = [sheet.as_viewport()] if sheet.view_id else []
    for so in schedules or []:
        if so.owner_view == sheet.view_id:
            draw_schedule(page, so)
    for v in sheet.viewports + own:
        draw_regions(page, v, state.REGIONS, curves)
    draw_annotation_instances(page, sheet, state.SHEET_ANNOTATIONS)
    if images:
        for v in sheet.viewports + own:
            draw_images(page, v, images)
    if curves:
        for v in sheet.viewports + own:
            draw_curves(page, v, curves)
    if notes:
        for v in sheet.viewports + own:
            draw_notes(page, v, notes)
    for v in sheet.viewports:
        draw_room_tags(page, v, state.ROOM_TAGS)
    if tags:
        for v in sheet.viewports:
            draw_tags(page, v, tags, axes or {})
    # viewport titles, as Revit prints them (M101): a detail circle of radius 0.125 in whose right
    # edge is m_labelOrigin, the title line from there for m_labelLength, the view name 0.079 in in
    # and 0.034 in above the line, the scale 0.167 in below it, all Arial 12.5 pt
    # A viewport type without a title family draws the extension line alone (oracle/testfamily).
    titled = [v for v in sheet.viewports if v.show_title and v.title_family is not None]
    r = 0.125 / 12
    shape = page.new_shape()
    for v in titled:
        lx, ly = v.label_origin
        shape.draw_circle(P(lx - r, ly), r * PT)
    shape.finish(color=(0, 0, 0), width=0.5, closePath=False)
    shape.commit()
    # the extension line: the viewport type's line weight, annotation pen 1 by default (its
    # parameter is not stored when left so: Snowdon 0.24 pt, test02 0.85 pt)
    shape = page.new_shape()
    for v in sheet.viewports:
        if v.show_title and v.title_line:
            lx, ly = v.label_origin
            shape.draw_line(P(lx, ly), P(lx + v.label_length, ly))
    line_w = (pens.annotation_width_pt(state.PEN_PATH, 1) if state.PEN_PATH else None) or 0.5
    shape.finish(color=(0, 0, 0), width=line_w, closePath=False)
    shape.commit()
    for v in titled:
        lx, ly = v.label_origin
        w = text_len(v.detail, "helv", 12.5)
        put_text(page, (P(lx - r, ly).x - w / 2, P(lx, ly).y + 0.054 * 72), v.detail, fontsize=12.5, fontname="helv")
        put_text(page, P(lx + 0.079 / 12, ly + 0.034 / 12), v.view_name, fontsize=12.5, fontname="helv")
        put_text(page, P(lx + 0.079 / 12, ly - 0.167 / 12), scale_text(v.scale), fontsize=12.5, fontname="helv")
    if titleblock is None and fit:
        fit_to_content(page)  # a printed page; a sheet_drawing keeps sheet coordinates
    elif fit:
        # Revit's page is the sheet and 0.24 pt more across, the sheet centred in it (Snowdon
        # 3024.24 pt for 42 in, its edge lines at x 0.12 pt; test02 1224.24 pt for 17 in); from
        # the paper's left edge, where that is not the sheet origin (Golden Nugget's)
        r, x0 = page.mediabox, sheet.left * PT
        page.set_mediabox(pdf.Rect(r.x0 + x0 - PAGE_EXTRA_PT / 2, r.y0, r.x1 + x0 + PAGE_EXTRA_PT / 2, r.y1))
    return page


PAGE_EXTRA_PT = 0.24


NO_TITLEBLOCK_MARGIN_PT = 18  # not decoded: Revit pads its own sheet extents (oracle/testfamily)


def fit_to_content(page):
    """A sheet without a title block has no paper: Revit's page is the sheet's extents (the
    viewports and what else is on it). Here: the page moved and cut to what was drawn, plus a
    margin."""
    boxes = pdf.drawn_boxes(page)
    if not boxes:
        return
    box = boxes[0]
    for r in boxes[1:]:
        box |= r
    m, H = NO_TITLEBLOCK_MARGIN_PT, page.mediabox.height
    page.set_mediabox(pdf.Rect(box.x0 - m, H - box.y1 - m, box.x1 + m, H - box.y0 + m))


def sheet_numbers(doc):
    """{page index: sheet number} from the bookmarks write() sets."""
    return pdf.toc(doc)
