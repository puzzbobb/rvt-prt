"""MEP system graphics: the line colour each system type gives its elements, read from the object graph.

Decoded:
- System types (RbsHvacSystemType, RbsPipingSystemType, RbsElectricalSystemType, RbsSystemType):
  - m_symbolInfo -> SymbolInfo: m_name (system classification / type name: "Supply Air", "Vent");
  - m_oSystemOverrides -> SystemOverrides:
    - m_oOverrideGraphicSettings -> OverrideGraphicSettings:
      - m_oProjPenColor -> GStyleColorOverrider: m_color (0x00BBGGRR integer).
- Systems (RbsHvacSystem, RbsPipingSystem, RbsElectricalSystem, RbsSystem):
  - m_typeId (ref): the system's type id.
An element names its system; with no system, or an unset colour, none.
"""
import functools

from ..core import objgraph

TYPE_CLASSES = ("RbsHvacSystemType", "RbsPipingSystemType", "RbsElectricalSystemType", "RbsSystemType")
SYSTEM_CLASSES = ("RbsHvacSystem", "RbsPipingSystem", "RbsElectricalSystem", "RbsSystem")


def _read(path):
    types = {}
    names = {}
    for eid, g in objgraph.elements(path, TYPE_CLASSES):
        root = g.objects[0]
        sym_ptr = root.fields.get("m_symbolInfo")
        if sym_ptr:
            s_idx = g.target(0, sym_ptr)
            if s_idx is not None:
                names[eid] = g.objects[s_idx].fields.get("m_name", "")

        ov_ptr = root.fields.get("m_oSystemOverrides")
        if not ov_ptr:
            types[eid] = None
            continue
        t_idx = g.target(0, ov_ptr)
        if t_idx is None:
            types[eid] = None
            continue
        sys_ov = g.objects[t_idx]
        ogs_ptr = sys_ov.fields.get("m_oOverrideGraphicSettings")
        if not ogs_ptr:
            types[eid] = None
            continue
        ogs_idx = g.target(t_idx, ogs_ptr)
        if ogs_idx is None:
            types[eid] = None
            continue
        ogs = g.objects[ogs_idx]
        col_ptr = ogs.fields.get("m_oProjPenColor")
        if not col_ptr:
            types[eid] = None
            continue
        col_idx = g.target(ogs_idx, col_ptr)
        if col_idx is None:
            types[eid] = None
            continue
        c_val = g.objects[col_idx].fields.get("m_color")
        if c_val is None or c_val < 0 or c_val == 0xFFFFFF:
            types[eid] = None
        else:
            r = (c_val & 0xFF) / 255.0
            g_c = ((c_val >> 8) & 0xFF) / 255.0
            b = ((c_val >> 16) & 0xFF) / 255.0
            types[eid] = (r, g_c, b)

    systems = {}
    system_names = {}
    for eid, g in objgraph.elements(path, SYSTEM_CLASSES):
        root = g.objects[0]
        tid = objgraph.ref(root.fields.get("m_typeId"))
        if tid is not None:
            systems[eid] = tid
        if root.fields.get("m_strName"):
            system_names[eid] = root.fields["m_strName"]

    return {"types": types, "systems": systems, "names": names, "system_names": system_names}


@functools.cache
def read(path):
    from ..core import diskcache
    return diskcache.cached(path, "systems", ("systems", "objgraph", "registry", "container"), lambda: _read(path))


def colour_of_system(path, system_id):
    d = read(path)
    t = d["systems"].get(system_id)
    return d["types"].get(t) if t is not None else None


def name_of_system(path, system_id):
    """A system's own name (m_strName: "Building Sanitary", "Mechanical Supply Air 3")."""
    return read(path)["system_names"].get(system_id, "")


def classification_of_system(path, system_id):
    """The system classification string of a system's type (its name: "Supply Air", "Vent")."""
    d = read(path)
    t = d["systems"].get(system_id)
    return d["names"].get(t) if t is not None else None


def element_systems(path):
    """{element id: system id}, decoded from MEP connectors and analytical model cells in the object graph."""
    from ..core import diskcache

    def compute():
        out = {}
        bodies = objgraph.channel_bodies(path, 102)
        dec = objgraph.decoder(path)
        for eid, b in sorted(bodies.items()):
            cname = objgraph.class_name(dec, b)
            if cname is None or not (cname.startswith("Rbs") or cname == "FamilyInstance"):
                continue
            try:
                g = dec.graph(b)
            except Exception:
                continue
            sids = set()
            for o in g.objects:
                if o.name == "MEPAnalyticalModelCell":
                    x = objgraph.ref(o.fields.get("m_systemId"))
                    if x is not None:
                        sids.add(x)
                elif o.name in ("SegmentConnectorCalculation", "MEPFamilyConnectorCalculationHvac", "MEPFamilyConnectorCalculationPiping"):
                    x = objgraph.ref(o.fields.get("m_idSystem"))
                    if x is not None:
                        sids.add(x)
            if sids:
                out[eid] = min(sids)
        return out
    return diskcache.cached(path, "element_systems", ("systems", "objgraph", "registry", "container"), compute)

