"""Levels and storeys read directly from the model: each Level record's m_text (its name) and
its datum Plane's m_origin, whose z is the level's elevation (feet).
"""
import functools


@functools.cache
def read(rf, path):
    """{level name: elevation feet} for every Level in the model."""
    from ..core import objgraph
    out = {}
    for _eid, g in objgraph.elements(path, ("Level",)):
        name = g.objects[0].fields.get("m_text")
        plane = next((o.fields for o in g.objects if o.name == "Plane"), None)
        if name and plane and name not in out:
            out[name] = plane["m_origin"][2]
    return out
