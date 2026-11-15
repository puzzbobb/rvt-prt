"""Views and sheets, from each view's record (a DBView* object graph, channel 102).

DBView: m_viewName, m_viewDescription, m_dbDrawingId, m_scale (1 / drawing scale),
m_sheetViewportElemId (a list, m_sheetViewportElemIds, before Revit 2023), m_origin / m_horzDir /
m_vertDir / m_viewDir, m_viewTemplateId, m_isTemplate. A sheet's view (catalogued as
DBViewDrafting) adds m_sheetNumber, m_date, m_drawnBy, m_checkedBy, m_designedBy, m_approvedBy,
m_issueDate. DBViewPlan adds its view range: m_bottomClipElev, m_columnSymbolElev, m_cutPlaneElev,
m_levelBelowElev, m_topClipElev (an unlimited plane is stored as 1e9). Visibility/Graphics' hidden
categories are IckyExcludedCategoriesSetPtrWrapper.m_categoryIds.
"""
import functools
from dataclasses import dataclass, field

SHEET_FIELDS = ("number", "date", "drawn_by", "checked_by", "designed_by", "approved_by", "issue_date")
_SHEET_KEYS = ("m_sheetNumber", "m_date", "m_drawnBy", "m_checkedBy", "m_designedBy", "m_approvedBy", "m_issueDate")
_RANGE_KEYS = ("m_bottomClipElev", "m_columnSymbolElev", "m_cutPlaneElev", "m_levelBelowElev", "m_topClipElev")
UNLIMITED = 1e5  # feet


@dataclass
class View:
    element_id: int  # the view's own id
    name: str
    description: str
    sheet: dict = field(default_factory=dict)  # SHEET_FIELDS of a sheet's view, else empty
    drawing_id: int | None = None  # m_dbDrawingId
    scale: float | None = None  # m_scale, 1 / drawing scale
    sheet_viewport_ids: tuple = ()  # m_sheetViewportElemId (m_sheetViewportElemIds before Revit 2023)
    view_range: tuple | None = None  # DBViewPlan: (bottom, column symbol, cut, view depth, top) elevations, feet
    camera: tuple | None = None  # (m_origin, m_horzDir, m_vertDir, m_viewDir)
    template_id: int | None = None  # m_viewTemplateId
    is_template: bool = False
    hidden_categories: frozenset = frozenset()  # Visibility/Graphics: BuiltInCategory ids hidden
    revisions: tuple = ()  # a sheet's m_explicitlyPresentRevisionIds
    scheduled: bool = True  # a sheet's m_bScheduled ("Appears In Sheet List")


def _view(eid, g):
    from ..core import objgraph
    f = g.objects[0].fields
    sheet = {}
    if f.get("m_sheetNumber"):
        sheet = {k: f.get(m, "") for k, m in zip(SHEET_FIELDS, _SHEET_KEYS)}
    vr = None
    if all(isinstance(f.get(k), float) for k in _RANGE_KEYS):
        vals = tuple(f[k] for k in _RANGE_KEYS)
        vr = tuple(min(v, UNLIMITED) if v > 0 else max(v, -UNLIMITED) for v in vals)
    cam = None
    if all(isinstance(f.get(k), list) for k in ("m_origin", "m_horzDir", "m_vertDir", "m_viewDir")):
        cam = tuple(tuple(f[k]) for k in ("m_origin", "m_horzDir", "m_vertDir", "m_viewDir"))
    hidden = frozenset()
    for o in g.objects:
        if o.name == "IckyExcludedCategoriesSetPtrWrapper":
            hidden = frozenset(e["m_id"]["m_id64"] for e in o.fields.get("m_categoryIds", []))
            break
    return View(eid, f.get("m_viewName", ""), f.get("m_viewDescription", ""), sheet,
                objgraph.ref(f.get("m_dbDrawingId")), f.get("m_scale"), tuple(r for r in map(objgraph.ref, [f.get("m_sheetViewportElemId")] + f.get("m_sheetViewportElemIds", [])) if r),
                vr, cam, objgraph.ref(f.get("m_viewTemplateId")), bool(f.get("m_isTemplate")), hidden,
                tuple(objgraph.ref(r) for r in f.get("m_explicitlyPresentRevisionIds", []) if objgraph.ref(r)),
                f.get("m_bScheduled", True) is not False)


def _read(rf, path):
    from ..core import objgraph
    return [_view(eid, g) for eid, g in objgraph.elements(path, ("DBView*",))
            if g.objects[0].name not in ("DBViewType",)]


MODULES = ("views", "objgraph", "registry")


def _disk(name, fn):
    @functools.cache
    def wrapper(rf, path):
        from ..core import diskcache
        return diskcache.cached(path, name, MODULES, lambda: fn(rf, path))
    wrapper.__doc__ = fn.__doc__
    return wrapper


read = _disk("views_read", _read)


def _all_hidden_categories(rf, path):
    return {v.element_id: v.hidden_categories for v in read(rf, path) if v.hidden_categories}


all_hidden_categories = functools.cache(_all_hidden_categories)


def hidden_categories(rf, path, view_id):
    """BuiltInCategory ids a view hides (Visibility/Graphics, IckyExcludedCategoriesSetPtrWrapper
    .m_categoryIds). The view's own list is what prints (Snowdon's parking ceiling plan hides
    Parking, Site and Lighting Fixtures in its own 94, which its template's 255 do not); a view
    with none takes its template's."""
    if view_id is None:
        return frozenset()
    return all_hidden_categories(rf, path).get(view_id, frozenset())


VIEW_DETAIL_LEVEL = -1011002  # BuiltInParameter: 1 coarse, 2 medium, 3 fine


def _int_params(rf, path):
    """{view id: ({parameter id: value}, template id, parameter ids its template does not set)}
    of every view, from its record's object graph (channel 102): DBView.m_pParamValueSetInt
    -> ParamValueSetInt.m_paramSet [{m_paramId, m_value}], m_viewTemplateId and
    m_nonPropagatedTemplateParamIds."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, ("DBView*",)):
        f = g.objects[0].fields
        params = {}
        for o in g.objects:
            if o.name == "ParamValueSetInt":
                params = {e["m_paramId"]["m_id"]["m_id64"]: e["m_value"] for e in o.fields.get("m_paramSet", [])}
                break
        template = (f.get("m_viewTemplateId") or {}).get("m_id", {}).get("m_id64")
        own = frozenset(e["m_id"]["m_id64"] for e in f.get("m_nonPropagatedTemplateParamIds", []) if isinstance(e, dict))
        out[eid] = (params, template if template is not None and template >= 0 else None, own)
    return out


@functools.cache
def int_params(rf, path):
    from ..core import diskcache
    return diskcache.cached(path, "view_int_params", MODULES + ("objgraph", "registry"), lambda: _int_params(rf, path))


def detail_level(rf, path, view_id):
    """A view's detail level (1 coarse, 2 medium, 3 fine), its template's where the template sets
    it, else None when not stored."""
    views = int_params(rf, path)
    hit = views.get(view_id)
    if hit is None:
        return None
    params, template, own = hit
    t = views.get(template) if template is not None else None
    if t is not None and VIEW_DETAIL_LEVEL not in t[2] and VIEW_DETAIL_LEVEL in t[0]:
        return t[0][VIEW_DETAIL_LEVEL]
    return params.get(VIEW_DETAIL_LEVEL)
