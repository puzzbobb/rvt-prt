"""Plan footprints of model elements, for drawing inside plan viewports.

Elements, their categories and boxes come from the headers of their saved graphics
(gelements.py), their systems from their connectors (systems.element_systems). A duct's or
pipe's footprint is its location line (RbsCurveDriver.m_pCrv, curve_drivers) widened to its
width (RbsCurve m_dWidthOrDiameter). Every other element, and one with no line, is its box.

A plan shows what lies in its view range (views.View.view_range); one without a decoded range,
from its level to the next level above (render.band).
"""
import math
from dataclasses import dataclass

from shapely.geometry import LineString, Polygon, box

from ..elements import gelements
from ..model import systems

# the categories drawn as footprints (BuiltInCategory id: the class name Footprint carries); flex
# ducts are drawn from their own curves (flex_footprints)
DRAWN = {-2008000: "Duct", -2008010: "DuctFitting", -2008013: "DuctTerminal", -2001140: "MechanicalEquipment",
         -2008044: "Pipe", -2008049: "PipeFitting", -2001160: "PlumbingFixture",
         -2000080: "Furniture", -2000151: "GenericModel"}


@dataclass
class Footprint:
    element_id: int
    class_name: str
    system: str
    zmin: float
    zmax: float
    shape: Polygon
    axis: LineString | None = None  # a duct's centreline
    path3d: list | None = None  # 3D points along a duct's centreline (model feet)
    box3d: tuple | None = None  # (lo xyz, hi xyz) record box
    width: float = 0.0  # a duct's width or diameter (feet)
    rgb: tuple | None = None  # the line colour of its system type (systems.py), None when unset
    saved: bool = False  # drawn in plans from its saved graphics (the host's model geometry), not as a box


MODULES = ("model2d", "gelements", "systems", "annotations", "pens", "objgraph", "registry", "container")


def footprints(rf, path):
    """[Footprint] of the file's MEP elements and furniture, disk-cached against the decoders' source."""
    from ..core import diskcache
    return diskcache.cached(path, "footprints", MODULES, lambda: _footprints(rf, path))


def _footprints(rf, path):
    from ..elements import annotations
    from ..core import objgraph
    heads = gelements.read(path)
    # types have saved graphics too, in the family's coordinates: instances only
    dec, bodies = objgraph.decoder(path), objgraph.channel_bodies(path, 102)
    boxes = {eid: (DRAWN[h.category], h.lo, h.hi) for eid, h in heads.items()
             if h.category in DRAWN and h.lo and eid in bodies and objgraph.class_name(dec, bodies[eid]) != "FamilySymbol"}
    sizes = annotations.mep_sizes(path, ("RbsDuctCurve", "RbsFlexDuctCurve", "RbsPipeCurve"))
    element_systems = systems.element_systems(path)
    # duct lines: each duct's location curve (RbsCurveDriver.m_pCrv, a GLine)
    best = {eid: (p0, p1, 0.0) for eid, (p0, p1) in curve_drivers(path).items() if eid in boxes}
    out = []
    for eid, (cls, lo, hi) in boxes.items():
        axis, path3d, width = None, None, 0.0
        if eid in best:
            p0, p1, _ = best[eid]
            width = sizes[eid][0] if eid in sizes else min(hi[0] - lo[0], hi[1] - lo[1])
            path3d = [p0, p1]
        if eid in best and math.dist(best[eid][0][:2], best[eid][1][:2]) > 1e-6:
            axis = LineString([p0[:2], p1[:2]])
            shape = axis.buffer(width / 2, cap_style="flat")
        else:
            shape = box(lo[0], lo[1], hi[0], hi[1])
        sid = element_systems.get(eid)
        out.append(Footprint(eid, cls, systems.name_of_system(path, sid) if sid else "", lo[2], hi[2], shape, axis, path3d,
                             (tuple(lo), tuple(hi)), width, systems.colour_of_system(path, sid) if sid else None))
    return out + flex_footprints(rf, path, out)


def flex_footprints(rf, path, others):
    """Flex ducts (RbsFlexDuctCurve): diameter from m_dWidthOrDiameter, vertices from m_ptVertex.
    The path is widened to the diameter; the system is that of the nearest other footprint within 1 ft."""
    from shapely.geometry import Point

    from ..core import objgraph
    out = []
    for eid, g in objgraph.elements(path, ("RbsFlexDuctCurve",)):
        root = g.objects[0]
        diam = root.fields.get("m_dWidthOrDiameter")
        pts = root.fields.get("m_ptVertex")
        if not diam or not pts or len(pts) < 2:
            continue
        line = LineString([q[:2] for q in pts])
        system, rgb = "", None
        for end in (Point(pts[0][:2]), Point(pts[-1][:2])):
            near = min(others, key=lambda f: f.shape.distance(end), default=None)
            if near is not None and near.shape.distance(end) < 1.0 and near.system:
                system, rgb = near.system, near.rgb
                break
        zs = [q[2] for q in pts]
        out.append(Footprint(eid, "FlexDuct", system, min(zs) - diam / 2, max(zs) + diam / 2,
                             line.buffer(diam / 2), line, [tuple(q) for q in pts], None, diam, rgb))
    return out


def in_band(fp, bottom, top):
    return fp.zmin < top and fp.zmax >= bottom


# stroke widths Revit prints most (pt): 1.3 for duct runs and fittings, 0.86 for the rest
WIDTH_PT = {"Duct": 1.3, "DuctFitting": 1.3, "FlexDuct": 1.3}
DEFAULT_WIDTH_PT = 0.86


def colour(fp):
    """The system type's line colour (systems.py); a dark grey where the system sets none."""
    return fp.rgb or (0.15, 0.15, 0.15)


def curve_drivers(path):
    """{element id: (p0, p1)} of MEP curves' location lines: RbsCurveDriver.m_pCrv -> GLine
    (m_endParams, m_origin, m_dirVec), model feet."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, ("Rbs*",)):
        for i, o in enumerate(g.objects):
            if o.name != "RbsCurveDriver":
                continue
            j = g.target(i, o.fields.get("m_pCrv"))
            if j is not None and g.objects[j].name == "GLine":
                f = g.objects[j].fields
                (t0, t1), org, d = f["m_endParams"], f["m_origin"], f["m_dirVec"]
                out[eid] = (tuple(org[k] + t0 * d[k] for k in range(3)), tuple(org[k] + t1 * d[k] for k in range(3)))
            break
    return out

