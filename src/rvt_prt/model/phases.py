"""Phases: which elements a view shows, by the phase they were created and demolished in.

Read from the records' object graphs (channel 102):
- AllProjectPhases.m_phaseIds: the project's phases (ProjectPhase, `m_name`), in order.
- PhaseFilterElem.m_phaseStatusPresentation: per element status, indexed none 0, past 1,
  existing 2, demolished 3, new 4, future 5, temporary 6: **0 not displayed, 1 by category,
  2 overridden** (Revit's own filters read so: "Show New" [0,0,0,0,1,0,0], "Show Previous + New"
  [0,0,2,0,1,0,0], "Show All" [0,0,2,2,1,2,0]).
- A view's phase and phase filter: its ElementId parameters PHASE (-1012102) and PHASE_FILTER
  (-1012103), its template's where the template sets them.
- An element's `m_createdPhaseId` and `m_demolishedPhaseId` (-1 for none), fields of every
  element record's root object.
- A link type's `m_phaseMap` [{first: the model's phase, second: the link's phase}] (links.py).

An element's status in a view of phase P: future if created after P; past if demolished before
P; temporary if created and demolished in P; demolished if demolished in P; new if created in P;
else existing. Elements with no created phase (annotations, types) are always shown.
Snowdon's floor plans ("Show Previous + New") leave out the Facades link's walls demolished in
New Construction, which Revit's exports leave out.
"""
import functools

from ..core import diskcache, objgraph

VIEW_PHASE = -1012102
VIEW_PHASE_FILTER = -1012103
MODULES = ("phases", "objgraph", "registry")
NONE, PAST, EXISTING, DEMOLISHED, NEW, FUTURE, TEMPORARY = range(7)


def _project(path):
    """(phase ids in order, {filter id: presentation tuple}, {view id: (phase id, filter id)})."""
    order, filters, raw = [], {}, {}
    for eid, g in objgraph.elements(path, ("AllProjectPhases", "PhaseFilterElem", "DBView*")):
        name = g.objects[0].name
        f = g.objects[0].fields
        if name == "AllProjectPhases":
            order = [p["m_id"]["m_id64"] for p in f.get("m_phaseIds", [])]
        elif name == "PhaseFilterElem":
            filters[eid] = tuple(f.get("m_phaseStatusPresentation", ()))
        else:
            params = {}
            for o in g.objects:
                if o.name == "ParamValueSetElementId":
                    params = {e["m_paramId"]["m_id"]["m_id64"]: objgraph.ref(e.get("m_value"))
                              for e in o.fields.get("m_paramSet", [])}
                    break
            own = frozenset(e["m_id"]["m_id64"] for e in f.get("m_nonPropagatedTemplateParamIds", [])
                            if isinstance(e, dict))
            raw[eid] = (params, objgraph.ref(f.get("m_viewTemplateId")), own)
    views = {}
    for eid, (params, template, _own) in raw.items():
        t = raw.get(template) if template is not None else None
        got = []
        for p in (VIEW_PHASE, VIEW_PHASE_FILTER):
            if t is not None and p not in t[2] and t[0].get(p) is not None:
                got.append(t[0][p])
            else:
                got.append(params.get(p))
        views[eid] = tuple(got)
    return order, filters, views


@functools.cache
def project(path):
    return diskcache.cached(path, "phases_project", MODULES, lambda: _project(path))


def _elements(path):
    """{element id: (created phase id, demolished phase id or None)} of every element with a
    created phase, from its record's root object alone."""
    out = {}
    for eid, body in objgraph.channel_bodies(path, 102).items():
        fields = objgraph.root(path, body) if len(body) >= 2 else None
        if fields is None:
            continue
        created = objgraph.ref(fields.get("m_createdPhaseId"))
        if created is not None:
            out[eid] = (created, objgraph.ref(fields.get("m_demolishedPhaseId")))
    return out


@functools.cache
def elements(path):
    return diskcache.cached(path, "phases_elements", MODULES, lambda: _elements(path))


def view_table(path, view_id):
    """(phase index in the project's order, presentation tuple) for a view, or None when the view
    has no phase or filter (every element shown)."""
    order, filters, views = project(path)
    phase, filt = views.get(view_id, (None, None))
    if phase not in order or filt not in filters:
        return None
    return order.index(phase), filters[filt]


def source_phases(host_path, source_path, phase_map=None):
    """{element id: (created index, demolished index or None)} of a geometry source's elements in
    the model's phase order; a link's phases mapped to the model's through its `phase_map`
    ({link phase id: model phase id})."""
    order = project(host_path)[0]
    index = {p: i for i, p in enumerate(order)}
    to_host = (lambda p: p) if phase_map is None else phase_map.get
    out = {}
    for eid, (c, d) in elements(source_path).items():
        ci = index.get(to_host(c))
        if ci is None:
            continue
        di = index.get(to_host(d)) if d is not None else None
        out[eid] = (ci, di)
    return out


def earlier_phases(path):
    """The phases (ElementIds as text) besides the project's last that an export must also be made
    at so that every element existing in some phase is meshed: rvt-rs's export shows the last phase
    only (#1074, RE-184), leaving out what was demolished before it (Snowdon's Facades link: 104
    walls, windows and roofs of Existing, demolished in New Construction, which its ceiling plans
    draw). An element exists in a phase from its created one up to before its demolished one, as
    rvt-rs counts it; each such element asks for the latest it exists in. One created and
    demolished in one phase exists in none (Snowdon Architectural's six Legends slabs), and asks
    for nothing. [] for a file of one phase, or none."""
    order = project(path)[0]
    if len(order) < 2:
        return []
    index = {p: i for i, p in enumerate(order)}
    need = set()
    for created, demolished in elements(path).values():
        c = index.get(created)
        d = index.get(demolished) if demolished is not None else None
        if c is None or d is None or d <= c:
            continue  # in the last phase, or in none
        need.add(d - 1)
    return [str(order[i]) for i in sorted(need)]


def status(phases, view_phase):
    """An element's status (NONE .. TEMPORARY) in a view of phase index `view_phase`."""
    if phases is None:
        return NONE
    c, d = phases
    if c > view_phase:
        return FUTURE
    if d is not None and d < view_phase:
        return PAST
    if d == view_phase:
        return TEMPORARY if c == view_phase else DEMOLISHED
    return NEW if c == view_phase else EXISTING


def visible(items, table):
    """The linkgeom Items a view with `table` shows (all of them when the view has no table)."""
    if table is None:
        return items
    return [i for i in items if shown(i.phase, table)]


def shown(phases, table):
    """Whether a view with `table` (view_table) shows an element of these phases."""
    if table is None or phases is None:
        return True
    st = status(phases, table[0])
    return st >= len(table[1]) or table[1][st] != 0
