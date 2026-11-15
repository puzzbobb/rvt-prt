"""Annotation elements, from the records' object graphs (channel 102).

TextNote: m_ownerDBViewId; m_orig (the text's anchor, model feet), m_upVec, m_baseVec;
m_lineWidth (paper feet: 0.106 ft for a 1.27 in wide note); m_attrId (its text type); m_flags
(the anchor, see TextNote.anchor); m_oSavedRtfData -> RtfData (the RTF; \\fsN its size in
half-points, which can be stale: the type's size is what prints); m_leaders -> Leader (m_end,
m_elbow, m_anchor).
IndependentTag: m_ownerDBViewId, m_symbolId (the tag type), TagOrientationCell.m_headLocation,
TagReferenceWithLeader (m_referenceIdKey: the tagged element; m_isLeaderEnabled; m_elbowOffset and
m_endOffset from the head). Revit 2022 to 2024 write TaggedElem (m_taggedId) in its place (2022's
leader flag the tag's own m_leader); before 2022 the tag's own fields hold them all (m_absHeadPos,
m_taggedElementId, m_leader, m_elbowOffset, m_endOffset).
"""
import functools
import re
from dataclasses import dataclass


RTF = b"{\\rtf"
CAP_HEIGHT = 0.716  # Arial's cap height per em: Revit's text size is the cap height
MODULES = ("annotations", "objgraph", "registry", "titleblock", "schedules", "savedgraphics")


def _disk(name, fn):
    @functools.cache
    def wrapper(rf, path):
        from ..core import diskcache
        return diskcache.cached(path, name, MODULES, lambda: fn(rf, path))
    wrapper.__doc__ = fn.__doc__
    return wrapper


def TYPE_FONTS(rf, path):
    from . import schedules
    return schedules.text_fonts(rf, path)


@dataclass
class TextNote:
    element_id: int
    owner_view: int
    origin: tuple  # model feet, the text box's top-left
    text: str
    size_pt: float
    width_ft: float | None  # paper feet
    align: str | None = None  # RTF \\qc / \\qr: the lines' alignment inside the box; None follows the anchor
    flags: int = 0x2240  # TextElement.m_flags: box anchor at m_orig (see anchor())
    leaders: list | None = None  # [(end, elbow, anchor)] model points, TextNote.m_leaders
    family: str = "Arial"  # RTF \\fonttbl
    lines: list | None = None  # [(text, bold, italic, indent twips)] per RTF paragraph

    def anchor(self):
        """(horizontal, vertical) anchor of m_orig on the text box, from m_flags as measured on
        Snowdon: 0x40 left, 0x80 centre, 0x100 right; 0x200 top, 0x400 middle, 0x800 bottom."""
        h = "centre" if self.flags & 0x80 else "right" if self.flags & 0x100 else "left"
        v = "middle" if self.flags & 0x400 else "bottom" if self.flags & 0x800 else "top"
        return h, v


def _decode_hex(body, rtf):
    """`body` with its runs of `\\'hh` escapes decoded in the code page of the font they are in
    (titleblock.rtf_codecs); its `\\fN` words are kept."""
    from .titleblock import rtf_codecs, rtf_hex
    fonts, codec = rtf_codecs(rtf)
    font = [None]

    def sub(m):
        if m.group(1) is not None:
            font[0] = int(m.group(1))
            return m.group(0)
        return rtf_hex(m.group(2), fonts.get(font[0], codec))
    return re.sub(r"\\f(\d+)(?![0-9])|((?:\\'[0-9a-fA-F]{2})+)", sub, body)


def rtf_to_text(rtf: str):
    """Plain text and the first \\fs size (points) of a RichEdit RTF block."""
    m = re.search(r"\\fs(\d+)", rtf)
    size = int(m.group(1)) / 2 if m else 9.0
    body = rtf[rtf.find("\\pard"):] if "\\pard" in rtf else rtf
    body = re.sub(r"\\par[d]?\b ?", lambda m_: "\n" if m_.group(0).startswith("\\par") and not m_.group(0).startswith("\\pard") else "", body)
    body = body.replace("\\_", "-").replace("\\~", "\u00a0").replace("\\-", "")
    body = _decode_hex(body, rtf)
    body = re.sub(r"\\u(-?\d+)\??", lambda m_: chr(int(m_.group(1)) % 65536), body)
    from .titleblock import RTF_CHARS
    body = re.sub(r"\\([a-z]+) ?", lambda m_: RTF_CHARS.get(m_.group(1), "\n" if m_.group(1) == "line" else m_.group(0)), body)
    body = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", body)
    body = body.replace("{", "").replace("}", "").replace("\r", "")
    return "\n".join(line.strip() for line in body.strip("\n").split("\n")).strip(), size


def _text_notes(rf, path):
    """Every TextNote."""
    from ..core import objgraph
    from . import titleblock as _tb
    fonts = TYPE_FONTS(rf, path)
    out = []
    for eid, g in objgraph.elements(path, ("TextNote",)):
        f = g.objects[0].fields
        j = g.target(0, f.get("m_oSavedRtfData"))
        if j is None or not f.get("m_orig"):
            continue
        rtf = bytes(g.objects[j].fields.get("m_arrRtfStream", [])).decode("cp1252", "replace")
        text, size = rtf_to_text(rtf)
        align = "centre" if "\\qc" in rtf else "right" if "\\qr" in rtf else None  # None: follow the anchor
        # Revit sizes a note by its type (the RTF's \fs can be stale: M101's "Electrical
        # Transformer Pad" says 25 pt, its type 10352 is 3/32" and prints 9.5 pt); the type's size
        # is the cap height: points = size / 0.716, to the half point
        typed = fonts.get(objgraph.ref(f.get("m_attrId")))
        if typed:
            size = round(typed[1] * 864 / CAP_HEIGHT * 2) / 2
        note = TextNote(eid, objgraph.ref(f.get("m_ownerDBViewId")), tuple(f["m_orig"]), text.rstrip("\x00").strip(), size,
                        f.get("m_lineWidth"), align, f.get("m_flags", 0x2240) & 0xFFFF)
        note.family = _tb.rtf_family(rtf)
        note.lines, _ = _tb.rtf_lines(rtf)
        note.leaders = []
        for ptr in f.get("m_leaders", []):
            k = g.target(0, ptr)
            if k is not None:
                lf = g.objects[k].fields
                note.leaders.append((tuple(lf["m_end"]), tuple(lf["m_elbow"]), tuple(lf["m_anchor"])))
        out.append(note)
    return out


text_notes = _disk("text_notes", _text_notes)


ALL_MODEL_MARK = -1001203  # Autodesk BuiltInParameter
RBS_SIZE = -1114240  # a duct's Size ("8\"ø"), the label of Snowdon's duct tag 162121
RBS_DIAMETER = -1114103  # a round duct's diameter ("6\""), the flex-duct tag 313476's label


@dataclass
class Tag:
    element_id: int
    owner_view: int
    head: tuple  # model feet: the label's centre
    tagged: int | None
    text: str | None = None
    angle: float = 0.0  # degrees, counter-clockwise in view coordinates (set when placed)
    leader: tuple | None = None  # (elbow, end) model points, when the leader is enabled
    symbol_id: int | None = None  # IndependentTag.m_symbolId: the tag family type
    values: dict | None = None  # {BuiltInParameter id: text} of the tagged element


def string_params(rf, path, element_ids, param):
    """{element id: value} of a string parameter (ParamValueSetAString) of the given elements
    (Snowdon's Mark: -1001203)."""
    from ..core import objgraph
    bodies = objgraph.channel_bodies(path, 102)
    dec = objgraph.decoder(path)
    out = {}
    for eid in element_ids:
        if eid not in bodies:
            continue
        try:
            g = dec.graph(bodies[eid])
        except Exception:  # a record the decoder cannot read: no value
            continue
        for o in g.objects:
            if o.name == "ParamValueSetAString":
                for e in o.fields.get("m_paramSet", []):
                    if e["m_paramId"]["m_id"]["m_id64"] == param and isinstance(e.get("m_value"), str) and e["m_value"]:
                        out[eid] = e["m_value"]
    return out


def mep_sizes(path, classes=("RbsDuctCurve", "RbsFlexDuctCurve")):
    """{element id: (width or diameter, height, round)} of ducts and flex ducts, or the given
    RbsCurve classes (m_dWidthOrDiameter, m_dHeight; round where the type's profile is round:
    width = height)."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, classes):
        f = g.objects[0].fields
        w, h = f.get("m_dWidthOrDiameter"), f.get("m_dHeight")
        if w:
            out[eid] = (w, h, g.objects[0].name == "RbsFlexDuctCurve" or not h or abs(w - h) < 1e-9)
    return out


def _tags(rf, path):
    """IndependentTags: owner view, head, tagged element, leader, tag type. Text: a duct's size,
    an element's Mark."""
    from ..core import objgraph
    out = []
    for eid, g in objgraph.elements(path, ("IndependentTag",)):
        f = g.objects[0].fields
        orient = next((o.fields for o in g.objects if o.name == "TagOrientationCell"), None)
        ref = next((o.fields for o in g.objects if o.name in ("TagReferenceWithLeader", "TaggedElem")), None)
        if orient is not None and ref is not None:
            head = tuple(orient["m_headLocation"])
            # TagReferenceWithLeader from Revit 2025; TaggedElem (m_taggedId) in 2022 to 2024
            item = ref["m_referenceIdKey"]["m_hostOrLinkElemId"] if "m_referenceIdKey" in ref else ref["m_taggedId"]
            on = ref["m_isLeaderEnabled"] if "m_isLeaderEnabled" in ref else f.get("m_leader")  # the tag's own in 2022
            leader = on and (ref["m_elbowOffset"]["m_xyz"], ref["m_endOffset"]["m_xyz"])
        elif "m_absHeadPos" in f:  # before: the tag's own fields
            head = tuple(f["m_absHeadPos"])
            item = f["m_taggedElementId"]
            leader = f.get("m_leader") and (f["m_elbowOffset"], f["m_endOffset"])
        else:
            continue
        tagged = objgraph.ref(item["m_linkInstOrHostId"])
        tag = Tag(eid, objgraph.ref(f.get("m_ownerDBViewId")), head, tagged, symbol_id=objgraph.ref(f.get("m_symbolId")))
        if leader:
            el, en = leader
            # plan offsets only: the third component is not a height (181.0 on tag 1490313)
            tag.leader = ((head[0] + el[0], head[1] + el[1], head[2]), (head[0] + en[0], head[1] + en[1], head[2]))
        out.append(tag)
    sizes = mep_sizes(path)
    marks = string_params(rf, path, {t.tagged for t in out if t.tagged is not None and t.tagged not in sizes}, ALL_MODEL_MARK)
    inch = lambda v: f"{round(v * 12, 2):g}\""
    for t in out:
        t.values = {}
        if t.tagged in sizes:
            w, h, rnd = sizes[t.tagged]
            t.text = f"{inch(w)}ø" if rnd else f"{inch(w)}x{inch(h)}"
            t.values = {RBS_SIZE: t.text, RBS_DIAMETER: inch(w)}
        elif t.tagged in marks:
            t.text = marks[t.tagged]
            t.values = {ALL_MODEL_MARK: t.text}
    return out


tags = _disk("tags", _tags)


@dataclass
class DetailCurve:
    element_id: int
    owner_view: int
    points: list  # model points along the curve (2 for a line, sampled for an arc)


def _detail_curves(rf, path):
    """CurveElem records (detail and model lines): m_ownerDBViewId and the curve its
    m_pCurveDriver holds (a GLine, GArc or GEllipse in the record's graph)."""
    from ..core import objgraph
    from . import savedgraphics
    out = []
    for eid, g in objgraph.elements(path, ("CurveElem",)):
        curve = next((o for o in g.objects if o.name in ("GLine", "GArc", "GEllipse")), None)
        if curve is None:
            continue
        pts = savedgraphics._curve_points(curve.name, curve.fields)
        if pts is None:
            continue
        owner = objgraph.ref(g.objects[0].fields.get("m_ownerDBViewId"))
        out.append(DetailCurve(eid, owner if owner is not None else 2**64 - 1, [tuple(float(x) for x in q) for q in pts]))
    return out


detail_curves = _disk("detail_curves", _detail_curves)
