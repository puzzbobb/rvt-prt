"""Grids (datum planes) and how plan views draw them, from the records' object graphs.

Grid: m_text (its name, "1", "B.1"), m_attrId (its GridAttributes) and its Plane: m_origin,
m_xVec, m_yVec and m_Envelope's corners ([u min, v min], [u max, v max]). One axis is vertical,
the other runs along the grid. The bubble end is the end furthest against t = z x (x x y) (as
Revit prints Snowdon's 15 grids; GridAttributes.m_bubbleAtEnd1 / End2 name ends of the grid's
own curve, which on the angled grid 9 runs against the plane's axis: open).

Drawn from the grid's type (GridAttributes, see GridType): the line runs the type's
m_endSegmentsLength (paper) past the extents, clipped to each plan viewport's crop grown by that
length; the head symbol (m_familyTagId) at the bubble end, sized by the extent of its saved
graphics, with the name in its label's text type; the centre segment in the projection style of
m_categoryForCenterSegment (pen and line pattern). The head is drawn from its family's own
curves (families.py), a circle sized by the symbol's extents when the family has none.
"""
import functools
from dataclasses import dataclass



@dataclass
class Grid:
    element_id: int
    name: str
    start: tuple  # (x, y) model feet, the bubble end, stored extent
    end: tuple
    type_id: int | None = None  # Grid.m_attrId: its GridAttributes


@dataclass
class GridType:
    """GridAttributes: m_endSegmentsLength (paper feet: how far the line runs past the grid's
    extents, Snowdon's "M Grid" 1/12), m_familyTagId (the head symbol), and the head symbol's
    extents (its bubble's half size, paper feet) and label text type (font, size feet); its line
    pattern (dashes) and pen number decoded from m_categoryForCenterSegment -> GStyleElem."""
    end_length: float
    head_id: int | None
    head_half: tuple | None = None  # (half width, half height)
    font: str = "Arial"
    size_ft: float | None = None
    head_curves: list | None = None  # the head family's curves (paper feet about the symbol origin)
    dashes: str | None = None  # PDF dash array (e.g. "[36 9 9 9] 0"), None when solid
    pen: int = 1  # line weight pen number


def _ends(plane):
    """(bubble end, other end) (x, y) model feet of a grid's Plane fields."""
    o, u, w = plane["m_origin"], plane["m_xVec"], plane["m_yVec"]
    (u0, v0), (u1, v1) = plane["m_Envelope"]["m_corners"]
    if abs(u[2]) > 0.999 and abs(w[2]) < 1e-6:
        along, lo, hi = w, v0, v1
    elif abs(w[2]) > 0.999 and abs(u[2]) < 1e-6:
        along, lo, hi = u, u0, u1
    else:
        return None
    n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    t = (-n[1], n[0])  # z x n, in plan
    p0 = (o[0] + lo * along[0], o[1] + lo * along[1])
    p1 = (o[0] + hi * along[0], o[1] + hi * along[1])
    if p0[0] * t[0] + p0[1] * t[1] > p1[0] * t[0] + p1[1] * t[1]:
        p0, p1 = p1, p0
    return p0, p1


MODULES = ("grids", "objgraph", "registry", "pens", "savedgraphics", "views", "families", "schedules")


def _disk(name, fn):
    @functools.cache
    def wrapper(rf, path):
        from ..core import diskcache
        return diskcache.cached(path, name, MODULES, lambda: fn(rf, path))
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _read(rf, path):
    from ..core import objgraph
    out = []
    for eid, g in objgraph.elements(path, ("Grid",)):
        f = g.objects[0].fields
        plane = next((o.fields for o in g.objects if o.name == "Plane"), None)
        ends = _ends(plane) if plane else None
        if f.get("m_text") and ends:
            out.append(Grid(eid, f["m_text"], *ends, objgraph.ref(f.get("m_attrId"))))
    return out


read = _disk("grids_read", _read)


def _grid_types(rf, path):
    """{GridAttributes id: GridType}."""
    from . import families, schedules
    from ..core import objgraph
    from ..model import pens
    fonts = schedules.text_fonts(rf, path)
    projection = {cat: sid for sid, (cat, kind) in pens.style_categories(str(path)).items() if kind == pens.PROJECTION}
    dashes, style_pens = pens.style_dashes(str(path)), pens.style_pens(str(path))
    symbols = {eid: g for eid, g in objgraph.elements(path, ("FamilySymbol",))}
    out = {}
    for eid, g in objgraph.elements(path, ("GridAttributes",)):
        f = g.objects[0].fields
        head = objgraph.ref(f.get("m_familyTagId"))
        t = GridType(f.get("m_endSegmentsLength") or 0.0, head)
        style = projection.get(objgraph.ref(f.get("m_categoryForCenterSegment")))
        if style is None or style not in dashes:
            style = projection.get(objgraph.ref(f.get("m_leaderCategoryId")), style)
        if style is not None:
            if style in dashes:
                t.dashes = "[" + " ".join(f"{v:g}" for v in dashes[style]) + "] 0"
            if style_pens.get(style):
                t.pen = style_pens[style]
        if head in symbols:
            t.head_half = _extents(path, head)
            label = next((o.fields for o in symbols[head].objects if o.name == "TagNoteData"), None)
            typed = fonts.get(objgraph.ref(label.get("m_attrId"))) if label else None
            if typed:
                t.font, t.size_ft = typed
            fam = objgraph.ref(symbols[head].objects[0].fields.get("m_familyId"))
            docs = families.documents(path)
            if fam in docs:
                t.head_curves = [cv.points for cv in docs[fam].curves]
        out[eid] = t
    return out


grid_types = _disk("grid_types", _grid_types)


def _extents(path, symbol_id):
    """(half width, half height) paper feet of a family symbol's saved graphics' curves."""
    from . import savedgraphics
    try:
        prims = savedgraphics.Link(path).primitives(symbol_id)
    except (ValueError, KeyError, IndexError):
        return None
    xs = [q[0] for pr in prims if pr.kind == "curve" for c in pr.points for q in c]
    ys = [q[1] for pr in prims if pr.kind == "curve" for c in pr.points for q in c]
    return ((max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2) if xs else None


def _plan_view_ids(rf, path):
    from ..core import objgraph
    return frozenset(eid for eid, _g in objgraph.elements(path, ("DBViewPlan",)))


plan_view_ids = _disk("plan_view_ids", _plan_view_ids)
