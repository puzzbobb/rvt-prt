"""Line weights: which pen a category draws with, and how wide a pen prints at a view's scale.

Decoded (oracle/test02, Snowdon HVAC), from element records' object graphs (objgraph.py):
- PenWidthTableElem -> PenWidthTable (Revit's Line Weights dialog): `m_modelPenInfo`, rows
  {m_invertedScale, m_pens: 16 widths in feet} per view scale (1:10 .. 1:500 metric, 1:12 ..
  1:384 imperial); `m_draftPenInfo`, the annotation pens (one row, scale -1). A file can hold
  several tables (Snowdon: eight with the same model rows); the lowest id is the document's.
- GStyleElem (a category's graphics style, Object Styles): `m_categoryId`, `m_gstyleType` 1
  projection / 2 cut, -> GStyle `m_penNumber`, `m_color`, `m_linePatternId`.
Revit's prints use these widths exactly: test02 at 1:100, Walls cut pen 2 = 0.37 pt, Furniture
pen 1 = 0.28 pt, the viewport title line annotation pen 1 = 0.85 pt; Snowdon at 1:96 prints
0.36 / 0.58 / 0.86 / 1.3 pt for pens 2 to 5, and its pen 1 (0.216 pt, model and annotation:
projection lines, viewport title lines) at 0.24 pt: a minimum printed width, MIN_PT (1/300 in;
test02's thinnest pen, 0.28 pt, cannot show it).
"""
import functools

PT_PER_FT = 864.0
MIN_PT = 0.24
PROJECTION, CUT = 1, 2


def _records(path, class_name):
    """(element id, object graph) of every record of `class_name`."""
    from ..core import objgraph
    return objgraph.elements(path, (class_name,))


@functools.cache
def style_categories(path):
    """{GStyleElem id: (category id, style type: PROJECTION or CUT)} of every graphics style."""
    from ..core import diskcache
    return diskcache.cached(path, "style_categories", ("pens", "objgraph", "registry"), lambda: _style_categories(path))


def _style_categories(path):
    return {eid: (g.objects[0].fields["m_categoryId"]["m_id"]["m_id64"], g.objects[0].fields["m_gstyleType"])
            for eid, g in _records(path, "GStyleElem")}


@functools.cache
def table(path):
    """(model rows {inverted scale: [16 widths, feet]}, annotation pens [widths, feet]) of the
    document's pen width table, or None."""
    from ..core import diskcache
    return diskcache.cached(path, "pen_table", ("pens", "objgraph", "registry"), lambda: _table(path))


def _table(path):
    for _eid, g in sorted(_records(path, "PenWidthTableElem"), key=lambda r: r[0]):
        t = next((o.fields for o in g.objects if o.name == "PenWidthTable"), None)
        if t is None:
            continue
        model = {row["m_invertedScale"]: list(row["m_pens"]) for row in t["m_modelPenInfo"]}
        draft = t["m_draftPenInfo"]
        if isinstance(draft, list):  # one row, kept as a list or as the row itself
            draft = draft[0] if draft else {}
        draft = list(draft.get("m_pens", []))
        return model, draft
    return None


@functools.cache
def category_pens(path):
    """{category id: {PROJECTION: pen, CUT: pen}} from the categories' graphics styles."""
    from ..core import diskcache
    return diskcache.cached(path, "category_pens", ("pens", "objgraph", "registry"), lambda: _category_pens(path))


def _category_pens(path):
    out = {}
    for _eid, g in _records(path, "GStyleElem"):
        f = g.objects[0].fields
        style = next((o.fields for o in g.objects if o.name == "GStyle"), None)
        if style is None or f["m_ownerId"]["m_id"]["m_id64"] != -1:
            continue
        out.setdefault(f["m_categoryId"]["m_id"]["m_id64"], {})[f["m_gstyleType"]] = style["m_penNumber"]
    return out


@functools.cache
def style_pens(path):
    """{GStyleElem id: pen number} of every graphics style (categories' and subcategories')."""
    from ..core import diskcache
    return diskcache.cached(path, "style_pens", ("pens", "objgraph", "registry"), lambda: _style_pens(path))


def _style_pens(path):
    out = {}
    for eid, g in _records(path, "GStyleElem"):
        style = next((o.fields for o in g.objects if o.name == "GStyle"), None)
        if style is not None:
            out[eid] = style["m_penNumber"]
    return out


@functools.cache
def style_colours(path):
    """{GStyleElem id: (r, g, b) 0..1} of every graphics style: GStyle m_color, 0xBBGGRR
    (oracle/test02: the door panel's 0x7F0000 prints navy, its window frame green)."""
    from ..core import diskcache
    return diskcache.cached(path, "style_colours", ("pens", "objgraph", "registry"), lambda: _style_colours(path))


def _style_colours(path):
    out = {}
    for eid, g in _records(path, "GStyleElem"):
        style = next((o.fields for o in g.objects if o.name == "GStyle"), None)
        c = style.get("m_color") if style else None
        if isinstance(c, int) and 0 <= c <= 0xFFFFFF:
            out[eid] = ((c & 0xFF) / 255, ((c >> 8) & 0xFF) / 255, ((c >> 16) & 0xFF) / 255)
    return out


@functools.cache
def category_colours(path):
    """{category id: {PROJECTION: (r, g, b), CUT: (r, g, b)}}: Object Styles line colours (test02:
    Doors blue, Windows navy; a door's lines in no subcategory print blue)."""
    from ..core import diskcache
    return diskcache.cached(path, "category_colours", ("pens", "objgraph", "registry"), lambda: _category_colours(path))


def _category_colours(path):
    colours = style_colours(path)
    out = {}
    for eid, g in _records(path, "GStyleElem"):
        f = g.objects[0].fields
        if f["m_ownerId"]["m_id"]["m_id64"] == -1 and eid in colours:
            out.setdefault(f["m_categoryId"]["m_id"]["m_id64"], {})[f["m_gstyleType"]] = colours[eid]
    return out


@functools.cache
def line_patterns(path):
    """{LinePatternElem id: (dash, gap, ...) points on paper}: LinePattern m_segs [{m_data
    (paper feet), m_type 0 dash / 1 space / 2 dot}] (test02's "Dash": 1/8" dash, 1/8" space; a
    dot prints as a 0.1 pt dash), starting with a dash."""
    from ..core import diskcache
    return diskcache.cached(path, "line_patterns", ("pens", "objgraph", "registry"), lambda: _line_patterns(path))


def _line_patterns(path):
    out = {}
    for eid, g in _records(path, "LinePatternElem"):
        lp = next((o.fields for o in g.objects if o.name == "LinePattern"), None)
        segs = lp.get("m_segs") if lp else None
        if not segs:
            continue
        vals = [(max(s["m_data"] * PT_PER_FT, 0.1), s["m_type"] != 1) for s in segs]
        if not vals[0][1]:
            vals = vals[1:] + vals[:1]
        out[eid] = tuple(round(v, 3) for v, _d in vals)
    return out


@functools.cache
def style_dashes(path):
    """{GStyleElem id: dash lengths (points)} of the graphics styles drawn in a line pattern."""
    from ..core import diskcache
    return diskcache.cached(path, "style_dashes", ("pens", "objgraph", "registry"), lambda: _style_dashes(path))


def _style_dashes(path):
    pats = line_patterns(path)
    out = {}
    for eid, g in _records(path, "GStyleElem"):
        style = next((o.fields for o in g.objects if o.name == "GStyle"), None)
        pid = style["m_linePatternId"]["m_id"]["m_id64"] if style else -1
        if pid in pats:
            out[eid] = pats[pid]
    return out


@functools.cache
def category_dashes(path):
    """{category id: {PROJECTION / CUT: dash lengths (points)}}: Object Styles line patterns."""
    dashes = style_dashes(path)
    out = {}
    for eid, g in _records(path, "GStyleElem"):
        f = g.objects[0].fields
        if f["m_ownerId"]["m_id"]["m_id64"] == -1 and eid in dashes:
            out.setdefault(f["m_categoryId"]["m_id"]["m_id64"], {})[f["m_gstyleType"]] = dashes[eid]
    return out


def model_width_pt(path, pen, scale):
    """Points a model pen prints at for a view of `scale` (sheet / model, e.g. 0.01): the row of
    the nearest listed scale (scales between rows not checked against Revit), or None."""
    t = table(path)
    if not t or not t[0] or not scale or not 1 <= pen <= 16:
        return None
    inv = 1.0 / scale
    row = min(t[0], key=lambda s: abs(s - inv) / s)
    return max(t[0][row][pen - 1] * PT_PER_FT, MIN_PT)


def annotation_width_pt(path, pen):
    t = table(path)
    if not t or not t[1] or not 1 <= pen <= len(t[1]):
        return None
    return max(t[1][pen - 1] * PT_PER_FT, MIN_PT)


def category_width_pt(path, category, kind, scale):
    """Points a category's cut (kind CUT) or projection (PROJECTION) lines print at, from the
    document's Object Styles and pen table; None when the category has no style there."""
    pen = category_pens(path).get(category, {}).get(kind)
    return None if pen is None else model_width_pt(path, pen, scale)
