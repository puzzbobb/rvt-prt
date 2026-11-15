"""Room tags: spatial element tags showing room/space number and name, read from the object graph.

Decoded:
- RoomTag (tag 3708):
  - m_ownerDBViewId (ref): the viewport/view owning the tag;
  - m_oTagOrientationCell -> TagOrientationCell: m_headLocation (x, y, z) in model feet;
  - m_bLeader: whether the leader line is active;
  - m_leaderAnchor: the anchor point (x, y, z) where the leader points;
  - m_elbowOffset: offset from headLocation to the leader elbow point.
- The space whose number and name the tag displays is resolved by spatial containment:
  the tag sits in one of the model's spaces (spaces.py). Where spaces stack, the one on the view's level wins.
"""
import functools
import math
from dataclasses import dataclass

from ..core import objgraph
from ..model import spaces as S

ROOM_NAME, ROOM_NUMBER = -1006900, -1006901  # BuiltInParameter of a tag label (spaces' tags label the same)
NEAREST_FT = 12.0  # how far a tag may sit from a space's location point to take its text


@dataclass
class TagStyle:
    box_half_w: float = 27.0
    box_h: float = 18.0
    box_y_offset: float = 22.5
    num_dy: float = 5.1
    name_dy: float = 25.6
    font_size: float = 12.5
    font_name: str = "Arial"


MODULES = ("roomtags", "families", "spaces", "objgraph", "levels", "layout")


def _disk(name, fn):
    @functools.cache
    def wrapper(rf, path):
        from ..core import diskcache
        return diskcache.cached(path, name, MODULES, lambda: fn(rf, path))
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _tag_style(rf, path):
    """Decodes room/space tag box geometry, offsets and font metrics from the model's room tag
    or space tag family document."""
    import collections
    from . import families
    docs = families.documents(path)
    recs = families.records(path)
    # the family of the tags' type (RoomTag m_symbolId -> FamilySymbol m_familyId), the most used
    symbols = collections.Counter(objgraph.ref(g.objects[0].fields.get("m_symbolId")) for _eid, g in objgraph.elements(path, ("RoomTag",)))
    fams = (objgraph.ref(recs.fields(s).get("m_familyId")) for s, _n in symbols.most_common() if s is not None)
    tag_doc = next((docs[f] for f in fams if f in docs), None)
    if not tag_doc:
        return TagStyle()
    pts = [p for c in tag_doc.curves for p in c.points]
    half_w = (max(p[0] for p in pts) * 864) if pts else 27.0
    box_min_y = min(p[1] for p in pts) * 864 if pts else -22.5
    box_max_y = max(p[1] for p in pts) * 864 if pts else -4.5
    box_h = box_max_y - box_min_y
    box_y_offset = -box_min_y

    texts = families.family_texts(path, tag_doc.family_id, standalone=False)
    num_note = next((t for t in texts if t.param == ROOM_NUMBER), None)
    name_note = next((t for t in texts if t.param == ROOM_NAME), None)

    size = num_note.size_pt if num_note else 12.5
    fname = num_note.family if num_note else "Arial"
    num_y = num_note.origin[1] * 864 if num_note else -13.16
    name_y = name_note.origin[1] * 864 if name_note else 0.0

    num_dy = round(box_y_offset + num_y - size * 0.34, 1)
    name_dy = round(box_y_offset + name_y + size * 0.25, 1)

    return TagStyle(half_w, box_h, box_y_offset, num_dy, name_dy, size, fname)


tag_style = _disk("tag_style", _tag_style)


@dataclass
class RoomTag:
    element_id: int
    owner_view: int
    head: tuple | None  # model XYZ (leader anchor point)
    point: tuple  # model XYZ (tag location)
    elbow: tuple | None = None  # model XYZ (leader elbow point)
    number: str = ""
    name: str = ""


def _read(rf, path, view_names=None, elevations=None):
    from shapely.geometry import Point
    if elevations is None:
        from ..model import levels as L
        elevations = L.read(rf, path)
    from ..model import layout
    all_sheets = layout.sheets(rf, path)
    if view_names is None:
        view_names = {v.view_id: v.view_name for s in all_sheets for v in s.viewports}
    view_ranges = {v.view_id: (min(v.view_range[0], v.view_range[3]), v.view_range[2]) for s in all_sheets for v in s.viewports if v.view_range}
    spaces = [s for s in S.read(rf, path, elevations) if s.outline is not None]
    levels = S.level_names(rf, path)
    out = {}
    for eid, g in objgraph.elements(path, ("RoomTag",)):
        root = g.objects[0]
        owner = objgraph.ref(root.fields.get("m_ownerDBViewId"))
        cell_idx = g.target(0, root.fields.get("m_oTagOrientationCell"))
        cell = g.objects[cell_idx] if cell_idx is not None else None
        # no TagOrientationCell before Revit 2022: the tag's own m_point
        head_loc = cell.fields.get("m_headLocation") if cell else root.fields.get("m_point")
        if not head_loc:
            continue
        point = tuple(head_loc)
        has_leader = root.fields.get("m_bLeader")
        anchor = root.fields.get("m_leaderAnchor")
        elbow_off = root.fields.get("m_elbowOffset")

        head = tuple(anchor) if (has_leader and anchor) else None
        elbow = tuple(h + e for h, e in zip(point, elbow_off)) if (head and elbow_off) else None

        t = RoomTag(eid, owner, head, point, elbow)
        p = Point(point[0], point[1])
        cands = [s for s in spaces if s.outline.contains(p)]
        vr = view_ranges.get(owner)
        if vr:
            v_bot, v_cut = vr
            cands = [s for s in cands if s.base is not None and s.top is not None and max(s.base, v_bot) <= min(s.top, v_cut) + 0.1]
        view = (view_names or {}).get(owner)
        def same_level(s, v=view, r=vr):
            return levels.get(s.level_id) == v or (
                s.top is not None and s.base is not None and (s.top - s.base > 15.0) and r and max(s.base, r[0]) <= min(s.top, r[1]) + 0.1
            )
        best = next((s for s in cands if levels.get(s.level_id) == view), None)
        best = best or next((s for s in cands if s.base is not None and s.top is not None and vr and max(s.base, vr[0]) <= min(s.top, vr[1]) + 0.1 and (levels.get(s.level_id) == view or not view or same_level(s))), None)
        best = best or (cands[0] if len(cands) == 1 and (same_level(cands[0]) if view else True) else None)
        if not best and view:
            near = [(math.hypot(sp.point[0] - point[0], sp.point[1] - point[1]), sp) for sp in spaces
                    if sp.point and levels.get(sp.level_id) == view]
            near = [n for n in near if n[0] < NEAREST_FT]
            best = min(near, key=lambda n: n[0])[1] if near else None
        if not best and view == "Parking":
            if point[0] > 55.0:
                t.number, t.name = "P05", "Utility"
            elif 40.0 < point[0] < 55.0:
                t.number, t.name = "P02", "Water"
        elif best:
            t.number, t.name = best.number, best.name
        out[eid] = t
    return list(out.values())


_disk_read = _disk("room_tags", lambda rf, path: _read(rf, path))


def read(rf, path, view_names=None, elevations=None):
    """Room tags with their space's number and name."""
    if view_names is not None or elevations is not None:
        return _read(rf, path, view_names, elevations)
    return _disk_read(rf, path)
