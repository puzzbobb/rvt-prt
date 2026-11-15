"""Loaded families' own documents, embedded in the project's partitions, and their plan geometry.

Decoded (oracle/test02, Snowdon HVAC 2025):
- A loaded family's document is a keyed group of the file's partitions (objgraph.embedded_bodies):
  its elements (curves, dimensions, labels, views, its own Family) framed as the project's
  records, under a content key.
- The project's Family (and a family a document nests) holds a FamilyDocument whose
  m_contentDocGUID is that key. The document's own Family is its Family with no m_famId and no
  FamilyDocument; the document also holds system families of its own (view heads: "Level Head -
  Upgrade"), whose m_famId is the document's Family.
- The document's own Family lists its members in an ElementIdIndexPairSet (element id, index).
- A CurveElem's geometry: CurveElemDriver.m_pCrv, a GLine (m_endParams, m_origin, m_dirVec), a
  GArc (m_endParams, m_center, m_xVec, m_yVec, m_radius) or a GEllipse (m_xLen, m_yLen); one
  whose m_GInfo.m_flags lacks 0x1000000 is unbound, a full turn.
- Several project families can share one document (Snowdon's Structural link: the bar joist
  sizes T9, 14, 17 ...): the name is the referencing Family's.
"""
import dataclasses
import functools
import math
from dataclasses import dataclass, field

from ..core import memory, objgraph


@dataclass
class FamilyDoc:
    family_id: int  # the document's own Family element
    name: str
    members: set  # the document's elements (its own Family's member list)
    category: int | None = None  # the family's BuiltInCategory (Family.m_categoryId)
    curves: list = field(default_factory=list)  # [Curve]


@dataclass
class FamilyText:
    """A text note or tag note inside a family document (family feet, paper units)."""
    origin: tuple
    up: tuple
    base: tuple
    lines: list  # [(text, bold, italic, indent, first indent)]
    size_pt: float
    family: str
    flags: int  # m_flags: 0x40/0x80/0x100 left/centre/right, 0x200/0x400/0x800 top/middle/bottom
    align: str | None
    boxed: bool = False  # the note type shows a border (TextElementAttributes.m_textBoxVisibility)
    param: int | None = None  # a label's parameter (TagNote m_paramDataFormattingArr m_paramId); None for a text note


@dataclass
class Curve:
    element_id: int
    points: list  # family coordinates (feet), sampled for arcs


PROJECT_CLASSES = ("Family", "FamilySymbol", "FamilyInstance", "TagNoteAttributes", "TextNoteAttributes",
                   "ElementGroupType")


class Records(dict):
    """{element id: record body} of the file's element records (channel 102): its family
    documents' and, of the project's, the families, types, instances, note types, group types
    and views (PROJECT_CLASSES, DBView*), with each record's class and decoded graph; `.docs`
    the documents, {content key: {element id: record body}}."""

    def __init__(self, path):
        super().__init__()
        self.dec = objgraph.decoder(path)
        self.docs = objgraph.embedded_bodies(path)
        for d in self.docs.values():
            self.update(d)
        self.project = {}
        for eid, b in objgraph.channel_bodies(path, 102).items():
            c = objgraph.class_name(self.dec, b)
            if c in PROJECT_CLASSES or (c or "").startswith("DBView"):
                self.project[eid] = b
        self.update(self.project)
        self._graphs = {}
        self._classes = {}

    def cls(self, eid):
        c = self._classes.get(eid, False)
        if c is False:
            b = self.get(eid)
            c = self._classes[eid] = objgraph.class_name(self.dec, b) if b is not None else None
        return c

    def graph(self, eid):
        if eid not in self._graphs:
            try:
                self._graphs[eid] = self.dec.graph(self[eid])
            except Exception:  # absent, or a layout the catalog does not describe as stored
                self._graphs[eid] = None
        return self._graphs[eid]

    def fields(self, eid):
        g = self.graph(eid)
        return g.objects[0].fields if g is not None else {}

    def of(self, classes, ids=None):
        """The ids (of `ids`, or every record) whose class is one of `classes`, ascending."""
        return [i for i in sorted(self if ids is None else ids) if self.cls(i) in classes]


def records(path):
    return _records(str(path))


@functools.lru_cache(maxsize=1)  # one file's at a time: a large link's records run to a few hundred MB
def _records(path):
    _held[0] = path
    return Records(path)


_held = [None]  # the path whose records _records holds


def forget_records(path):
    """Drop the records held, if they are `path`'s (memory.forget)."""
    if _held[0] == str(path):
        _records.cache_clear()
        _held[0] = None


def element_id(v):
    """An ElementId field's id, negative (built-in) ids included; None when absent."""
    x = v.get("m_id", {}).get("m_id64") if isinstance(v, dict) else None
    return x


def _doc_key(g):
    """The content key of the document a Family's FamilyDocument names, or None."""
    fd = next((o for o in g.objects if o.name == "FamilyDocument"), None)
    return fd.fields["m_contentDocGUID"]["m_guid"] if fd is not None else None


def _own_family(recs, bodies):
    """A document's own Family: no m_famId and no FamilyDocument."""
    for eid in recs.of(("Family",), bodies):
        g = recs.graph(eid)
        if g is not None and objgraph.ref(g.objects[0].fields.get("m_famId")) is None and _doc_key(g) is None:
            return eid
    return None


@memory.per_file
def documents(path, standalone=False):
    """{Family id: FamilyDoc} of every Family whose FamilyDocument names a loaded document (the
    project's families and the families documents nest); with `standalone`, also each document's
    own Family id (an annotation family placed by itself, such as a text stamp)."""
    out, own = _documents(str(path))
    return {**out, **own} if standalone else out


@memory.per_file
def _documents(path):
    """documents' ({Family id: FamilyDoc}, {each document's own Family id: FamilyDoc}), each
    document's curves built once for both (Snowdon Architectural: 500 documents, 8 s twice)."""
    recs = records(path)
    docs = {}
    for key, bodies in recs.docs.items():
        own = _own_family(recs, bodies)
        if own is None:
            continue
        g = recs.graph(own)
        members = {objgraph.ref(e["m_elementId"]) for o in g.objects if o.name == "ElementIdIndexPairSet"
                   for e in o.fields.get("m_data", [])} - {None}
        docs[key] = FamilyDoc(own, "", members & recs.keys(), element_id(g.objects[0].fields.get("m_categoryId")))
    for d in docs.values():
        _build(recs, d)
    recs._graphs.clear()  # decoded on demand again: kept, every file's graphs outgrow the memory a print has
    out, first = {}, {}
    for eid in recs.of(("Family",)):
        g = recs.graph(eid)
        key = _doc_key(g) if g is not None else None
        if key not in docs:
            continue
        name = g.objects[0].fields.get("m_name") or ""
        out[eid] = dataclasses.replace(docs[key], name=name)
        if key not in first or (eid in recs.project and first[key][0] not in recs.project):
            first[key] = (eid, name)  # the document's name: its first project family's, else its first nesting family's
    return out, {d.family_id: dataclasses.replace(d, name=first.get(k, (0, ""))[1]) for k, d in docs.items()}


def _build(recs, d):
    """A document's curves."""
    import numpy as np
    cvs = [cv for i in recs.of(("CurveElem",), d.members) if (cv := curve(i, recs.graph(i)))]
    if len(cvs) >= 4:
        all_pts = np.vstack([np.array(c.points) for c in cvs])
        p_min = np.percentile(all_pts[:, :2], 2, axis=0)
        p_max = np.percentile(all_pts[:, :2], 98, axis=0)
        kept = []
        for c in cvs:
            pts = np.array(c.points)
            if len(pts) == 2:
                c_min, c_max = pts[:, :2].min(0), pts[:, :2].max(0)
                if max(p_min[0] - c_min[0], c_max[0] - p_max[0], p_min[1] - c_min[1], c_max[1] - p_max[1]) > 1.5:
                    continue
            kept.append(c)
        cvs = kept
    d.curves = cvs


BOUND = 0x1000000  # GInfo.m_flags: a bounded curve; an arc without it is a full turn (its m_endParams equal, or 2 pi apart)


def curve(eid, g):
    """A CurveElem's line, arc or ellipse (CurveElemDriver.m_pCrv; GEllipse: m_xLen, m_yLen for
    the radius), arcs sampled every pi/32 (at least 8 segments), or None."""
    if g is None:
        return None
    drv = next((i for i, o in enumerate(g.objects) if o.name == "CurveElemDriver"), None)
    j = g.target(drv, g.objects[drv].fields.get("m_pCrv")) if drv is not None else None
    if j is None:
        return None
    o = g.objects[j]
    f = o.fields
    if o.name == "GLine":
        t0, t1 = f["m_endParams"]
        p, d = f["m_origin"], f["m_dirVec"]
        return Curve(eid, [tuple(p[k] + t0 * d[k] for k in range(3)), tuple(p[k] + t1 * d[k] for k in range(3))])
    if o.name in ("GArc", "GEllipse"):
        a0, a1 = f["m_endParams"]
        if not f["m_GInfo"]["m_flags"] & BOUND:
            a1 = a0 + 2 * math.pi  # unbound: a full circle or ellipse
        if not a1 > a0:
            return None
        cen, xa, ya = f["m_center"], f["m_xVec"], f["m_yVec"]
        rx, ry = (f["m_radius"], f["m_radius"]) if o.name == "GArc" else (f["m_xLen"], f["m_yLen"])
        n = max(8, int((a1 - a0) / (math.pi / 32)))
        pts = []
        for i in range(n + 1):
            a = a0 + (a1 - a0) * i / n
            ca, sa = rx * math.cos(a), ry * math.sin(a)
            pts.append(tuple(cen[k] + ca * xa[k] + sa * ya[k] for k in range(3)))
        return Curve(eid, pts)
    return None


def instance_family(recs, iid):
    """The Family a FamilyInstance places: InstanceInfo.m_symbolId (or m_masterSymbolId), the
    FamilySymbol's m_familyId."""
    g = recs.graph(iid)
    if g is None:
        return None
    info = next((o for o in g.objects if o.name == "InstanceInfo"), None)
    sym = objgraph.ref(info.fields.get("m_symbolId")) if info is not None else None
    if recs.cls(sym) != "FamilySymbol":
        sym = objgraph.ref(g.objects[0].fields.get("m_masterSymbolId"))
    return objgraph.ref(recs.fields(sym).get("m_familyId")) if sym is not None else None


def composed(path, family_id, depth=0, standalone=False):
    """A family's curves with its nested families': each FamilyInstance in its document draws
    its symbol's family through the instance's transform (a door: its own lines and its "Door
    Swing-Single" arc). A nested 2D family (every curve at z = 0 in its own coordinates) placed
    with its plane not horizontal is left out: view-specific families show only in views
    parallel to their plane (Snowdon's windows: the "Filled Arrow" opening marks, stood on the
    wall plane for the elevations)."""
    import numpy as np
    docs = documents(path, standalone)
    d = docs.get(family_id)
    if d is None or depth > 4:
        return []
    out = [c.points for c in d.curves]
    recs = records(path)
    tr = instance_transforms(path)
    for i in recs.of(("FamilyInstance",), d.members):
        fam = instance_family(recs, i)
        if i not in tr or fam not in docs or fam == family_id:
            continue
        m = tr[i]
        nested = composed(path, fam, depth + 1, standalone)
        if nested and abs(m[2, 2]) < 1 - 1e-6 and all(abs(z) < 1e-6 for pts in nested for _x, _y, z in pts):
            continue  # a 2D family (all its curves in its own XY plane) stood on a plane that is not a plan: it does not show in plans
        for pts in nested:
            w = np.c_[np.array(pts), np.ones(len(pts))] @ m.T
            out.append([tuple(p[:3]) for p in w])
    return out


class Symbols:
    """A geometry source's family graphics: its saved graphics and its placement."""

    def __init__(self):
        self.saved = None  # savedgraphics.Saved: the link's saved graphics, drawn in preference
        self.place = None  # the link's 4x4 placement in the model


def _instance_transforms(path):
    """{FamilyInstance id: 4x4 transform from the family's coordinates} of the file's model
    instances, the project's and those nested in its loaded families' documents
    (objgraph.embedded_bodies): InstanceInfo.m_Trf (m_3x3 rows, m_or origin). An instance a view
    owns (view_owned: detail items; annotation symbols, whose m_Trf carries the view's scale) is
    included: a nested one in a family's view is drawn with its family (a door's swing symbol).

    The 3x3's rows are the rotation's rows, not the family axes: read as columns, every instance
    turned by +-90 or +-120 degrees came out turned the other way against the blocks Revit's DXF
    export places for the same elements (Snowdon: chairs, beams, double-hung windows).

    Handedness comes from the symbol, not the instance's flip flags: InstanceInfo.m_symbolId
    names a flip variant of the type (FamilySymbol with m_masterId the type; Revit's DXF names its
    blocks by these ids), and a variant with m_mirrored is the family mirrored in its y axis.
    Checked on Snowdon's linked models against Revit's DXF: of the instances whose symbol is
    mirrored, about 116 in 127 fit only so. FamilyInstance's m_flippedX / m_flippedY are already
    folded into which variant the instance uses and are not applied again."""
    import numpy as np
    from ..core import objgraph
    bodies = dict(objgraph.channel_bodies(path, 102))  # its own: channel_bodies' is shared
    for doc in objgraph.embedded_bodies(path, 102).values():
        bodies.update(doc)
    mirrored = {eid: bool(g.objects[0].fields.get("m_mirrored"))
                for eid, g in objgraph.elements(path, ("FamilySymbol",), bodies)}
    out = {}
    for eid, g in objgraph.elements(path, ("FamilyInstance",), bodies):
        info = next((o for o in g.objects if o.name == "InstanceInfo" and "m_Trf" in o.fields), None)
        if info is None:
            continue
        t = info.fields["m_Trf"]
        m = np.eye(4)
        m[:3, :3], m[:3, 3] = t["m_3x3"], t["m_or"]
        if mirrored.get(objgraph.ref(info.fields.get("m_symbolId"))):
            m = m @ np.diag([1.0, -1.0, 1.0, 1.0])
        out[eid] = m
    return out


def _view_owned(path):
    """{FamilyInstance id: owner view id} of the project's instances a view owns
    (m_ownerDBViewId): they show only in that view, never through a link."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, ("FamilyInstance",)):
        v = objgraph.ref(g.objects[0].fields.get("m_ownerDBViewId"))
        if v is not None:
            out[eid] = v
    return out


def _categories_by_name(path):
    """{family name: BuiltInCategory}: Family.m_name and m_categoryId (RPC Shrub: Planting
    -2001360), the first family of a name in id order."""
    from ..core import objgraph
    out = {}
    for _eid, g in objgraph.elements(path, ("Family",)):
        f = g.objects[0].fields
        cat = (f.get("m_categoryId") or {}).get("m_id", {}).get("m_id64")
        if f.get("m_name") and cat is not None and cat < -1:
            out.setdefault(f["m_name"], cat)
    return out


MODULES = ("families", "container", "schema", "titleblock", "objgraph", "registry")


def _disk(name, fn):
    @functools.cache
    def wrapper(path):
        from ..core import diskcache
        return diskcache.cached(path, name, MODULES, lambda: fn(path))
    wrapper.__doc__ = fn.__doc__
    return wrapper


instance_transforms = _disk("instance_transforms", _instance_transforms)
categories_by_name = _disk("categories_by_name", _categories_by_name)
view_owned = _disk("view_owned", _view_owned)
sheet_annotations = _disk("sheet_annotations", lambda path: _sheet_annotations(path))




def family_texts(path, family_id, standalone=True):
    """The TextNote / TagNote elements of a family document: m_orig, m_upVec, m_baseVec, the
    RTF (RtfData), m_flags, and the note type's (m_attrId) m_textBoxVisibility."""
    from . import titleblock
    d = documents(path, standalone=standalone).get(family_id)
    if d is None:
        return []
    recs = records(path)
    out = []
    for i in recs.of(("TagNote", "TextNote"), d.members):
        g = recs.graph(i)
        if g is None:
            continue
        f = g.objects[0].fields
        rtf = next((bytes(o.fields["m_arrRtfStream"]) for o in g.objects if o.name == "RtfData"), b"")
        if b"{\\rtf" not in rtf:
            continue
        rtf = rtf[rtf.index(b"{\\rtf"):].decode("cp1252", "replace")
        lines, size = titleblock.rtf_lines(rtf)
        boxed = bool(recs.fields(objgraph.ref(f.get("m_attrId"))).get("m_textBoxVisibility"))
        align = "centre" if "\\qc" in rtf else "right" if "\\qr" in rtf else None
        param = next((d["m_paramId"]["m_id"]["m_id64"] for d in f.get("m_paramDataFormattingArr", [])
                      if isinstance(d, dict) and "m_paramId" in d), None)
        out.append(FamilyText(tuple(f["m_orig"]), tuple(f["m_upVec"]), tuple(f["m_baseVec"]), lines, size,
                              titleblock.rtf_family(rtf), f["m_flags"] & 0xFFFF, align, boxed, param))
    return out


def _sheet_annotations(path):
    """Annotation family instances (generic annotations, tags, symbols) in the file's views:
    [(owner view id, 4x4 transform, [curve point lists], [FamilyText], BuiltInCategory)], each
    drawing its symbol's family document (instance_family)."""
    path = str(path)
    docs = documents(path, standalone=True)
    recs = records(path)
    views = ("DBViewDrafting", "DBViewPlan", "DBViewSheet", "DBView3d", "DBViewSection")
    out = []
    for iid, m in instance_transforms(path).items():
        owner = objgraph.ref(recs.fields(iid).get("m_ownerDBViewId"))
        fam = instance_family(recs, iid)
        if recs.cls(owner) not in views or fam not in docs:
            continue
        texts = family_texts(path, fam)
        curves = composed(path, fam, standalone=True)
        if texts or curves:
            out.append((owner, m, curves, texts, element_id(recs.fields(fam).get("m_categoryId"))))
    return out
