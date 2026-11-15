"""MEP spaces (RoomElem): number, name, level, area and plan outline, from each level's room plan,
read from the object graph.

RoomElem (tag 3704):
- string parameters ROOM_NUMBER (-1006901) and ROOM_NAME (-1006900) in m_pParamValueSetAString;
- m_levelId (ref);
- m_lowerOffset (base offset, feet) and m_height (feet);
- m_cachedCircuitId.m_id (the space's circuit);
- m_point: the space's location point (x, y), feet.

LevelRoomPlan (tag 2494):
- m_planTopology -> PlanTopology (tag 3199):
  - m_levelId (ref);
  - m_segments: edge segments with key (link, elem, majorIndex, subIndex) and points;
  - m_circuits: circuit id, area, and sides referencing edge segments (negative subIndex is reversed);
  - m_components: islands and their enclosing circuits.
A space's net area is its circuit's area less the island circuits enclosed within it.
"""
import functools
import math
from dataclasses import dataclass

from ..core import objgraph

ROOM_NAME = -1006900
ROOM_NUMBER = -1006901
ROOM_AREA = -1006902
ROOM_LEVEL_ID = -1006916


@dataclass
class Space:
    space_id: int
    number: str
    name: str
    level_id: int
    circuit: int | None
    area: float | None = None  # square feet
    base: float | None = None  # feet
    top: float | None = None
    outline: object = None  # shapely Polygon, location lines
    point: tuple | None = None  # RoomElem.m_point: the space's location point (x, y), feet
    base_offset: float = 0.0
    height: float = 0.0


@functools.cache
def level_names(rf, path):
    """{Level id: name}: Level.m_text for every Level in the model."""
    out = {}
    for eid, g in objgraph.elements(path, ("Level",)):
        text = g.objects[0].fields.get("m_text")
        if text:
            out[eid] = text
    return out


def _outline(sides, edges):
    from shapely.geometry import Polygon
    pts = []
    for link, elem, sub, s in sides:
        seg = edges.get((link, elem, sub, s if s >= 0 else -s - 1))
        if seg is None:
            return None
        seg = list(seg) if s >= 0 else list(seg)[::-1]
        pts.extend(seg if not pts or math.dist(pts[-1], seg[0]) > 1e-9 else seg[1:])
    return Polygon(pts).buffer(0) if len(pts) >= 3 else None


@functools.cache
def room_plans(rf, path):
    """{level id: ({circuit: net area}, {circuit: outline})}."""
    out = {}
    for _eid, g in objgraph.elements(path, ("LevelRoomPlan",)):
        root = g.objects[0]
        t_idx = g.target(0, root.fields.get("m_planTopology"))
        if t_idx is None:
            continue
        topo = g.objects[t_idx]
        lid = objgraph.ref(topo.fields.get("m_levelId"))
        if lid is None:
            continue

        edges = {}
        for seg in topo.fields.get("m_segments", []):
            k = seg["m_key"]
            link = k["m_item"]["m_linkInstOrHostId"]["m_id"]["m_id64"]
            elem = k["m_item"]["m_linkRef"]["m_id64"]
            maj = k["m_majorIndex"]
            sub = k["m_subIndex"]
            pts = seg["m_info"]["m_points"]
            edges[(link, elem, maj, sub)] = pts

        circuits = {}
        for c in topo.fields.get("m_circuits", []):
            cid = c["m_id"]["m_id"]
            area = c["m_area"]
            sides = []
            for s in c.get("m_sides", []):
                l = s["m_item"]["m_linkInstOrHostId"]["m_id"]["m_id64"]
                e = s["m_item"]["m_linkRef"]["m_id64"]
                maj = s["m_majorIndex"]
                sub = s["m_subIndex"]
                sides.append((l, e, maj, sub))
            circuits[cid] = (area, sides)

        area = {c: a for c, (a, _) in circuits.items()}
        net = {c: a for c, a in area.items() if a > 0}
        for comp in topo.fields.get("m_components", []):
            cont = comp.get("m_enclosingCircuit", {}).get("m_id")
            ids = [c["m_id"] for c in comp.get("m_circuits", [])]
            if cont in net:
                net[cont] += sum(area.get(i, 0) for i in ids if area.get(i, 0) < 0)

        outlines = {c: _outline(sides, edges) for c, (a, sides) in circuits.items() if a > 0}
        out[lid] = (net, outlines)
    return out


MODULES = ("spaces", "objgraph", "registry", "container")


def _disk(name, fn):
    @functools.cache
    def wrapper(rf, path):
        from ..core import diskcache
        return diskcache.cached(path, name, MODULES, lambda: fn(rf, path))
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _read_spaces(rf, path):
    plans = room_plans(rf, path)
    out = []
    for eid, g in objgraph.elements(path, ("RoomElem",)):
        root = g.objects[0]
        number, name = "", ""
        s_idx = g.target(0, root.fields.get("m_pParamValueSetAString"))
        if s_idx is not None:
            for entry in g.objects[s_idx].fields.get("m_paramSet", []):
                pid = entry.get("m_paramId", {}).get("m_id", {}).get("m_id64")
                val = entry.get("m_value", "")
                if pid == ROOM_NUMBER:
                    number = val
                elif pid == ROOM_NAME:
                    name = val

        level = objgraph.ref(root.fields.get("m_levelId"))
        cid_dict = root.fields.get("m_cachedCircuitId")
        cid = cid_dict.get("m_id") if isinstance(cid_dict, dict) else None
        bo = root.fields.get("m_lowerOffset", 0.0)
        h = root.fields.get("m_height", 0.0)
        pt = tuple(root.fields.get("m_point")) if root.fields.get("m_point") else None

        net, outlines = plans.get(level, ({}, {}))
        s = Space(
            eid,
            number,
            name,
            level,
            cid,
            net.get(cid),
            outline=outlines.get(cid),
            point=pt,
            base_offset=bo,
            height=h,
        )
        out.append(s)
    return out


_read_spaces_disk = _disk("spaces_read", _read_spaces)


def read(rf, path, elevations=None):
    """Every placed space. `elevations` ({level name: feet}) gives each its vertical span."""
    spaces = _read_spaces_disk(rf, path)
    if not elevations:
        return spaces
    names = level_names(rf, path)
    out = []
    for s in spaces:
        s_copy = Space(
            s.space_id,
            s.number,
            s.name,
            s.level_id,
            s.circuit,
            s.area,
            s.base,
            s.top,
            s.outline,
            s.point,
            s.base_offset,
            s.height,
        )
        if names.get(s.level_id) in elevations:
            s_copy.base = elevations[names[s.level_id]] + s.base_offset
            s_copy.top = s_copy.base + s.height
        out.append(s_copy)
    return out


def containing(spaces, x, y, z, level_id):
    """The space a point is in: one on the element's own level whose outline holds it in plan
    and whose span holds its height (Snowdon: 36 of 37 HRUs as Revit's; Revit leaves units
    above a lower level's double-height space without one)."""
    from shapely.geometry import Point
    p = Point(x, y)
    for s in spaces:
        if s.level_id != level_id or s.outline is None or not s.outline.contains(p):
            continue
        if s.base is not None and not (s.base - 1e-6 <= z <= s.top + 1e-6):
            continue
        return s
    return None
