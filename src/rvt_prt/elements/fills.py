"""Filled regions and the line styles of curves (Snowdon HVAC: the M001 page shadows, M000's box
and its shadow), from the records' object graphs (channel 102).

- FilledRegion: m_ownerDBViewId, m_sketchId (its VarSketch), m_attrId (its type,
  FilledRegionAttributes; -1 on a masking region), m_bMasking.
- Boundary: the CurveElems whose SketchMembership.m_groupId is the sketch.
- Colour: the type's m_lineAndTextAttr.m_categoryId (a subcategory) -> its projection graphics
  style's GStyle.m_color ("Solid Gray" 192, 192, 192, as Revit prints it). A masking region
  fills white. Fill patterns are taken as solid (all Snowdon's).
- A curve's line style is its curve's m_GInfo.m_categoryId (a GStyleElem); -2000064 is
  OST_InvisibleLines, which Revit does not print (the shadows' boundaries).
"""
import functools
from dataclasses import dataclass

INVISIBLE = -2000064


@dataclass
class Region:
    element_id: int
    owner_view: int
    colour: tuple
    curve_ids: list


@functools.cache
def curve_info(rf, path):
    """{CurveElem id: (style id, sketch id)}."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, ("CurveElem",)):
        curve = next((o for o in g.objects if o.name in ("GLine", "GArc", "GEllipse")), None)
        sketch = next((o for o in g.objects if o.name == "SketchMembership"), None)
        style = objgraph.ref(curve.fields["m_GInfo"]["m_categoryId"]) if curve else None
        out[eid] = (style, objgraph.ref(sketch.fields.get("m_groupId")) if sketch else None)
    return out


def invisible_curves(rf, path):
    from ..model import pens
    cats = pens.style_categories(str(path))
    return {c for c, (s, _k) in curve_info(rf, path).items() if s is not None and cats.get(s, (None,))[0] == INVISIBLE}


def read(rf, path):
    from ..core import objgraph
    from ..model import pens
    info = curve_info(rf, path)
    colours = pens.style_colours(str(path))
    projection = {cat: sid for sid, (cat, kind) in pens.style_categories(str(path)).items() if kind == pens.PROJECTION}
    types = {eid: g.objects[0].fields for eid, g in objgraph.elements(path, ("FilledRegionAttributes",))}
    out = []
    for eid, g in objgraph.elements(path, ("FilledRegion",)):
        f = g.objects[0].fields
        sketch, type_id = objgraph.ref(f.get("m_sketchId")), objgraph.ref(f.get("m_attrId"))
        colour = (1.0, 1.0, 1.0)
        if type_id is not None and not f.get("m_bMasking"):
            cat = objgraph.ref((types.get(type_id, {}).get("m_lineAndTextAttr") or {}).get("m_categoryId"))
            colour = colours.get(projection.get(cat), (0.0, 0.0, 0.0))
        out.append(Region(eid, objgraph.ref(f.get("m_ownerDBViewId")), colour, [c for c, (_s, k) in info.items() if k == sketch]))
    return out
