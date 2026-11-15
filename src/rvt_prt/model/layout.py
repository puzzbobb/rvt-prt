"""A sheet's page: paper size, title-block fields and viewports, in sheet feet (origin bottom-left)."""
from dataclasses import dataclass, field

from . import views, viewports



@dataclass
class Placed:
    detail: str
    view_name: str
    scale: float
    frame: tuple | None  # x0, y0, x1, y1 on the sheet (feet)
    label_origin: tuple
    label_length: float
    offset: tuple = (0.0, 0.0)
    crop: tuple | None = None  # view coordinates
    view_origin: tuple | None = None
    view_basis: tuple | None = None
    view_id: int | None = None
    view_range: tuple | None = None  # (bottom, column, cut, depth, top) feet
    camera: tuple | None = None  # (origin, horz, vert, viewDir) of a 3D view
    show_title: bool = True
    template_id: int | None = None  # the view's template (m_viewTemplateId)
    reflected: bool = False  # a ceiling plan (looks up)
    detail_level: int | None = None  # VIEW_DETAIL_LEVEL (1 coarse, 2 medium, 3 fine): views.detail_level
    phase: tuple | None = None  # (phase index, phase filter's presentations): phases.view_table
    title_family: int | None = -1  # the viewport type's view title family; None: the type has none
    title_line: bool = True  # the viewport type's extension line
    depth: tuple | None = None  # (near, far) feet along the looking direction (sections, elevations)


@dataclass
class Sheet:
    number: str
    name: str
    fields: dict
    size: tuple  # width, height (feet)
    viewports: list = field(default_factory=list)
    view_id: int | None = None  # the sheet's own view (owner of its viewports, schedules and notes)
    drawing_id: int | None = None  # its view's m_dbDrawingId (its viewports' m_dbDrawingId)
    scheduled: bool = True  # "Appears In Sheet List"
    left: float = 0.0  # the paper's left edge, sheet feet: below 0 for a title block drawn left of its origin (_paper)

    def as_viewport(self):
        """The sheet as a 1:1 'viewport' of itself, so sheet-owned notes, lines and images go
        through the same placement as a view's."""
        w, h = self.size
        return Placed("", "", 1.0, None, (0, 0), 0, (0.0, 0.0), (self.left, 0.0, self.left + w, h), (0.0, 0.0, 0.0),
                      ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), self.view_id)


def _paper(title_block):
    """A sheet's paper (left edge, (width, height)) in feet: its title block's extent from the
    sheet origin, or from its left edge for one lying left of the origin (Golden Nugget's, whose
    origin is the paper's lower right). Without one, a working page that the printed page is then
    fitted to (render.fit_to_content: Revit's page for such a sheet is its content and a margin)."""
    ext = title_block.extent if title_block is not None else None
    if ext is None:
        return 0.0, (3.5, 2.5)
    x0, _y0, x1, y1 = ext
    left = x0 if x1 <= 1e-6 else 0.0
    return left, (x1 - left, y1)


def sheets(rf, path):
    all_views = views.read(rf, path)
    by_viewport = {vid: v for v in all_views if not v.sheet for vid in v.sheet_viewport_ids}
    vps = viewports.read(rf, path)
    out = {}
    for sv in all_views:
        if not sv.sheet or sv.sheet["number"] in out:
            continue
        placed = []
        for vp in vps:
            if vp.drawing_id != sv.drawing_id:
                continue
            frame = None
            if vp.crop:
                x0, y0, x1, y1 = vp.crop
                ox, oy = vp.offset[0], vp.offset[1]
                frame = (ox + x0 * vp.scale, oy + y0 * vp.scale, ox + x1 * vp.scale, oy + y1 * vp.scale)
            view = by_viewport.get(vp.element_id)
            placed.append(Placed(vp.detail, view.name if view else f"view {vp.view_id}", vp.scale, frame,
                                 vp.label_origin[:2], vp.label_length, vp.offset[:2], vp.crop,
                                 vp.view_origin, vp.view_basis, vp.view_id, view.view_range if view else None,
                                 view.camera if view else None, vp.show_title, view.template_id if view else None, vp.reflected,
                                 title_family=vp.title_family, title_line=vp.title_line, depth=vp.depth))
        out[sv.sheet["number"]] = Sheet(sv.sheet["number"], sv.name, sv.sheet, None, sorted(placed, key=lambda p: p.detail),
                                         sv.element_id, sv.drawing_id, sv.scheduled)
    sheets_ = [out[k] for k in sorted(out)]
    from ..elements import titleblock
    tbs = titleblock.for_sheets(rf, path, sheets_)
    for s in sheets_:
        s.left, s.size = _paper(tbs.get(s.number))
    return sheets_
