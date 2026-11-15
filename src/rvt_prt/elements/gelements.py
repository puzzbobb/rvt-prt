"""Each element's category and box, from the header of its saved graphics.

Decoded (oracle/test02, oracle/testfamily, Snowdon HVAC and its five links), channel 103 of the
element records (objgraph.py) holds each element's regenerated graphics; its root object is a
GElement:
- `m_elementId`: the element's own id (2024 and later; the root of a 2023 or older file has no such
  field: its record's id is the element's, as it always is where the field exists);
- `m_GInfo.m_categoryId`: the GStyleElem of the element's category (its projection style), whose
  `m_categoryId` is the BuiltInCategory (pens.style_categories);
- `m_bBox`: (min xyz, max xyz) in the model's coordinates, feet.

Checked against rvt-rs's `rvt-elements` m_builtinCategory, which it reads from a fixed-offset
partition record prologue: the same category on every element both give (13,000+ over the eight
files), except the Facades link's 103 wall sweeps, which rvt-rs files under Wall Sweeps
(-2000181) and whose graphics are in Walls (-2000011): a wall sweep type draws in a subcategory of
Walls (CorniceAttr.m_wallSubCategoryId), and the graphics style is what a view's visibility and
pens act on. The headers also give categories rvt-rs gives none for: every element of
Snowdon's Architectural and Structural links (rvt-rs: 1 and 0).

`m_bBox` is the box rvt-rs gives each family instance (it reads the same box from the element's
record): equal within 1e-13 ft on all 1,543 to 5,210 instances of Snowdon HVAC, Architectural,
Structural and Plumbing, rst_basic and rac_advanced (2027), and within 1e-3 ft on all 5,185 of
rme_basic (2019).
"""
from typing import NamedTuple

from ..core import memory


class Header(NamedTuple):
    category: int  # BuiltInCategory id (negative)
    lo: tuple  # box min xyz, model feet
    hi: tuple  # box max xyz


def _read(path):
    from ..core import objgraph
    from ..model import pens
    styles = pens.style_categories(path)
    out = {}
    for eid, body in objgraph.channel_bodies(path, 103).items():
        r = objgraph.root(path, body)
        if not r or "m_GInfo" not in r or r.get("m_elementId", eid) != eid:
            continue
        style = r["m_GInfo"]["m_categoryId"]["m_id"]["m_id64"]
        if style not in styles:
            continue
        lo, hi = r.get("m_bBox") or (None, None)
        out[eid] = Header(styles[style][0], tuple(lo) if lo else None, tuple(hi) if hi else None)
    return out


@memory.per_model
def read(path):
    """{element id: Header} of every element with saved graphics, disk-cached."""
    from ..core import diskcache
    return diskcache.cached(path, "gelements", ("gelements", "pens", "objgraph", "registry", "container"),
                            lambda: _read(str(path)))


def categories(path):
    """{element id: BuiltInCategory id}."""
    return {eid: h.category for eid, h in read(str(path)).items()}


# the continuous rails of a railing (its top rail, its handrails): elements of their own whose
# saved graphics are an instance of their own symbol, the GElement carrying no category (its
# m_categoryId is -1) where the symbol's names Top Rails or Handrails (Snowdon Architectural:
# 92 TopRail, 121 HandRail; Revit's DXF draws each as a block)
RAIL_CLASSES = ("TopRail", "HandRail")


def _read_rails(path):
    from ..core import objgraph
    from ..model import pens
    from . import savedgraphics
    styles = pens.style_categories(path)
    bodies = objgraph.channel_bodies(path, 103)
    link = savedgraphics.Link(path)
    out = {}
    for eid in sorted(e for c in RAIL_CLASSES for e in objgraph._class_index(path).get(c, ())):
        if eid not in bodies:
            continue
        r = objgraph.root(path, bodies[eid])
        hit = link.instance(eid)
        if not r or hit is None or hit[0] not in bodies:
            continue
        s = objgraph.root(path, bodies[hit[0]])
        style = s and s.get("m_GInfo", {}).get("m_categoryId", {}).get("m_id", {}).get("m_id64")
        lo, hi = r.get("m_bBox") or (None, None)
        if style in styles and lo and hi:
            out[eid] = (Header(styles[style][0], tuple(lo), tuple(hi)), hit[1])
    return out


@memory.per_model
def rails(path):
    """{element id: (Header, 4x4 transform)} of the file's continuous rails, the category their
    symbol's graphics are in, disk-cached."""
    from ..core import diskcache
    return diskcache.cached(path, "rails", ("gelements", "savedgraphics", "pens", "objgraph", "registry", "container"),
                            lambda: _read_rails(str(path)))
