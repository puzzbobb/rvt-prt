"""Title blocks and annotation symbols: a family symbol's own lines, fixed texts and labels.

Read from the symbol's object graph (channel 102):
- lines: its GLine objects (m_endParams, m_origin, m_dirVec), each in the graphics style its
  m_GInfo.m_categoryId names (Title Blocks' Wide / Medium / Narrow Lines);
- fixed texts: TextNoteData (m_orig, m_upVec, m_baseVec, m_height, m_lineWidth, m_attrId,
  m_flags) and the RtfData its m_oRtfData points to;
- labels: TagNoteData, the same fields and m_paramDataFormattingArr [{m_paramId (a
  BuiltInParameter), m_prefix, m_suffix, m_sampleText}].
A sheet's title block is the FamilyInstance holding a FamInstTitleBlock whose m_ownerDBViewId is
the sheet's view (the DBView record with m_sheetNumber); its InstanceInfo names the symbol.
Project parameters are the ProjectInfo element's string parameters.
"""
import functools
import math
import re
from dataclasses import dataclass, field

MODULES = ("titleblock", "images", "pens", "objgraph", "registry")


def _disk(name, fn):
    @functools.cache
    def wrapper(rf, path, *args):
        from ..core import diskcache
        return diskcache.cached(path, name, MODULES, lambda: fn(rf, path, *args))
    wrapper.__doc__ = fn.__doc__
    return wrapper

# Autodesk BuiltInParameter ids measured on Snowdon's labels
SHEET_NUMBER, SHEET_NAME, SHEET_SCALE = -1007401, -1007400, -1007402
SHEET_DRAWN_BY, SHEET_CHECKED_BY = -1007404, -1007405
# the date and time of printing ("Date/Time Stamp"): Revit prints it in the printing machine's
# format, "13/10/2026 14:50:37" on both test exports
PRINT_DATE_TIME = -1007403
PROJECT_NUMBER, PROJECT_NAME, CLIENT_NAME, PROJECT_ISSUE_DATE = -1006316, -1006317, -1006319, -1006321


@dataclass
class TextItem:
    origin: tuple  # sheet feet
    height: float  # feet (text box)
    width: float  # feet
    flags: int
    lines: list = field(default_factory=list)  # [(text, bold, italic)]
    size_pt: float = 12.5
    param: int | None = None  # a label's BuiltInParameter
    family: str = "Arial"  # the RTF's font; labels take their text type's, else their symbol's
    base: tuple = (1.0, 0.0)  # the direction the text runs in (m_baseVec): (0, 1) reads up the sheet
    bold: bool = False  # a label's text type's
    italic: bool = False
    typed: bool = False  # a label whose text type gave its font, size and style (read_symbol)
    nominal_pt: float | None = None  # its text type's size (Font.m_size) in points, where known: lines are spaced by it


@dataclass
class TitleBlock:
    symbol_id: int
    lines: list  # (x0, y0, x1, y1) sheet feet
    texts: list  # TextItem
    labels: list  # TextItem with .param
    images: list = field(default_factory=list)  # Image
    family: str = "Arial"  # the symbol's text font (its first RTF's), used for its labels
    pens: list = field(default_factory=list)  # per line: its graphics style's pen number, None unknown
    sheet: tuple | None = None  # (x0, y0, x1, y1) sheet feet: the family's sheet plane's envelope (read_symbol)

    @property
    def extent(self):
        """(x0, y0, x1, y1) of its lines and its sheet plane, sheet feet; None without either."""
        xs = [x for x0, _y0, x1, _y1 in self.lines for x in (x0, x1)]
        ys = [y for _x0, y0, _x1, y1 in self.lines for y in (y0, y1)]
        if self.sheet:
            xs += self.sheet[0::2]
            ys += self.sheet[1::2]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def rtf_family(rtf, default="Arial"):
    """The first font of an RTF's font table, e.g. `{\\f0\\fnil\\fcharset0 Trebuchet MS;}`."""
    m = re.search(r"\\fonttbl\{\\f\d+[^ ;]* ([^;}]+);", rtf)
    return m.group(1).strip() if m else default


# RTF \fcharset -> Python codec (Windows' ANSI and DBCS code pages)
_CHARSETS = {0: "cp1252", 128: "cp932", 129: "cp949", 134: "gbk", 136: "cp950", 161: "cp1253", 162: "cp1254",
             163: "cp1258", 177: "cp1255", 178: "cp1256", 186: "cp1257", 204: "cp1251", 222: "cp874", 238: "cp1250"}


# RTF's control words that stand for a character (RTF 1.9, "Special characters"); RichEdit writes
# a dash typed in a note as \endash (Snowdon's "Auto \u2013 Internal Origin to Internal Origin"),
# which read as nothing
RTF_CHARS = {"endash": "\u2013", "emdash": "\u2014", "bullet": "\u2022", "lquote": "\u2018", "rquote": "\u2019",
             "ldblquote": "\u201c", "rdblquote": "\u201d", "enspace": "\u2002", "emspace": "\u2003",
             "qmspace": "\u2005", "zwj": "\u200d", "zwnj": "\u200c", "zwbo": "\u200b", "zwnbo": "\ufeff"}


def rtf_codecs(rtf):
    """({font number: codec} from the font table's \\fcharset, the document's codec from \\ansicpg):
    a Japanese note is `\\ansicpg932` with `{\\f0\\fnil\\fcharset128 Meiryo UI;}`, its text runs of
    two-byte Shift-JIS escapes (`\\'93\\'c1`), one character a pair."""
    import codecs
    m = re.search(r"\\ansicpg(\d+)", rtf)
    default = "cp1252"
    if m:
        try:
            default = codecs.lookup(f"cp{m.group(1)}").name
        except LookupError:
            pass
    fonts = {int(n): _CHARSETS[int(c)] for n, c in re.findall(r"\{\\f(\d+)[^{};]*?\\fcharset(\d+)", rtf) if int(c) in _CHARSETS}
    return fonts, default


def rtf_hex(run, codec):
    """A run of `\\'hh` escapes decoded as one byte string (a two-byte character spans two)."""
    return bytes.fromhex(run.replace("\\'", "")).decode(codec, "replace")


def _runs(text, start, marks):
    """A line's [(text, bold, italic)] runs where its words are not all of one style, else None:
    `start` is the style at its first character, `marks` [(position, (bold, italic))] where the
    style changes after. Spaces do not count: a line whose words are all bold is of one style."""
    pieces, pos, style = [], 0, start
    for at, new in [*marks, (len(text), start)]:
        if at > pos:
            if pieces and pieces[-1][1:] == style:
                pieces[-1] = (pieces[-1][0] + text[pos:at], *style)
            else:
                pieces.append((text[pos:at], *style))
        pos, style = at, new
    return pieces if len({p[1:] for p in pieces if p[0].strip()}) > 1 else None


def rtf_lines(rtf):
    """[(text, bold, italic, indent twips, first-line indent twips, runs)] per RTF paragraph (`\\par`), with the size
    (half-points) of the first `\\fs`. Only \\b, \\i (and their 0 forms), \\li and \\pard are
    followed. bold and italic are those of the line's first word; `runs` is None, or the line's
    [(text, bold, italic)] where its words differ (Snowdon's title block: a heading in regular with
    an italic colon)."""
    m = re.search(r"\\fs(\d+)", rtf)
    size = int(m.group(1)) / 2 if m else 12.5
    body = rtf[rtf.find("\\pard"):] if "\\pard" in rtf else rtf
    out, cur, bold, italic = [], "", False, False
    began, marks = (False, False), []  # the style at the line's start, and where it changes (_runs)
    indent = first = 0
    line_style = None
    fonts, codec = rtf_codecs(rtf)
    font = None
    uc = 1  # \uc: the characters after a \u for readers without Unicode, skipped (`\u24314?`)
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            m = re.match(r"\\([a-zA-Z]+)(-?\d+)? ?", body[i:])
            if m:
                word, arg = m.group(1), m.group(2)
                if word == "par":
                    out.append((cur, *(line_style or (bold, italic)), indent, first, _runs(cur, began, marks)))
                    cur, line_style = "", None
                    began, marks = (bold, italic), []
                elif word == "pard":
                    indent = first = 0
                elif word == "li" and arg:
                    indent = int(arg)
                elif word == "fi" and arg:
                    first = int(arg)
                elif word == "tab":
                    cur += "\t"  # a list item's number, then its text at the indent
                elif word in RTF_CHARS:
                    cur += RTF_CHARS[word]
                elif word == "line":  # a line break within the paragraph: a new line at its indent
                    out.append((cur, *(line_style or (bold, italic)), indent, first, _runs(cur, began, marks)))
                    cur, line_style = "", None
                    began, marks = (bold, italic), []
                elif word == "b":
                    bold = arg != "0"
                    marks.append((len(cur), (bold, italic)))
                elif word == "i":
                    italic = arg != "0"
                    marks.append((len(cur), (bold, italic)))
                elif word == "uc" and arg:
                    uc = int(arg)
                elif word == "u" and arg:
                    cur += chr(int(arg) % 65536)
                    i += len(m.group(0))
                    for _ in range(uc):  # each a \'hh escape or one character
                        hx = re.match(r"\\'[0-9a-fA-F]{2}", body[i:])
                        if hx:
                            i += len(hx.group(0))
                        elif i < len(body) and body[i] not in "\\{}":
                            i += 1
                    continue
                elif word == "f" and arg:
                    font = int(arg)
                i += len(m.group(0))
                continue
            m = re.match(r"(?:\\'[0-9a-fA-F]{2})+", body[i:])
            if m:
                cur += rtf_hex(m.group(0), fonts.get(font, codec))
                i += len(m.group(0))
                continue
            # control symbols: \_ non-breaking hyphen, \~ non-breaking space, \- optional hyphen
            cur += {"_": "-", "~": "\u00a0", "-": ""}.get(body[i + 1:i + 2], "")
            i += 2
            continue
        if body.startswith("{\\*", i):  # an ignorable destination, e.g. a list definition {\\*\\pn ...}
            depth, j = 0, i
            while j < len(body):
                depth += {"{": 1, "}": -1}.get(body[j], 0)
                j += 1
                if depth == 0:
                    break
            i = j
            continue
        if ch in "{}\r\n\x00":
            i += 1
            continue
        if line_style is None and ch.strip():
            line_style = (bold, italic)
        cur += ch
        i += 1
    if cur.strip():
        out.append((cur, *(line_style or (bold, italic)), indent, first, _runs(cur, began, marks)))
    return out, size


def _symbol_graphs(path):
    """{symbol id: Graph} of the FamilySymbols holding fixed texts or labels."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, ("FamilySymbol",)):
        if any(o.name in ("TextNoteData", "TagNoteData") for o in g.objects):
            out[eid] = g
    return out


def _text_item(o, height=None):
    f = o.fields
    bx, by = (list(f.get("m_baseVec") or (1.0, 0.0)) + [0.0])[:2]
    n = math.hypot(bx, by)
    return TextItem(tuple(f["m_orig"]), f["m_height"], f["m_lineWidth"], f["m_flags"] & 0xFFFF,
                    base=(bx / n, by / n) if n > 1e-9 else (1.0, 0.0))


# A label's printed size, in points, over its text type's size (Font.m_size): Revit's size is not
# the font's, which prints 1.4 times as large, to the half point. Snowdon's and test02's title
# blocks, Trebuchet MS, text type -> Revit's PDF: 6.75 -> 9.5, 9 -> 12.5, 13.5 -> 19, 18 -> 25,
# 27 -> 38, 45 -> 63. A label that does not run left to right prints larger: the two there are,
# both Date/Time Stamps reading up the sheet, 6.75 -> 10 and 9 -> 13.5.
LABEL_EM, LABEL_EM_TURNED = 1.4, 1.5


def printed_size(size_ft, turned=False):
    """The size in points Revit prints a label whose text type's size is `size_ft` at."""
    return round(size_ft * 12 * 72 * (LABEL_EM_TURNED if turned else LABEL_EM) * 2) / 2


def text_types(path):
    """{text type id: (font name, size ft, bold, italic)} of the label and text types: the font and
    size from the type's FontElem, a label type's (TagNoteAttributes) bold and italic from its
    m_lineAndTextAttr (a text's come from its RTF)."""
    from ..core import objgraph
    fonts = {}
    for _eid, g in objgraph.elements(path, ("FontElem",)):
        font = next((o.fields for o in g.objects if o.name == "Font"), None)
        owner = objgraph.ref(g.objects[0].fields.get("m_ownerId"))
        if owner and font and font.get("m_size"):
            fonts[owner] = (font.get("m_name"), font["m_size"])
    out = {eid: (*font, False, False) for eid, font in fonts.items()}  # a text's type (TextNoteAttributes) too
    for eid, g in objgraph.elements(path, ("TagNoteAttributes",)):
        if eid in fonts:
            attr = g.objects[0].fields.get("m_lineAndTextAttr") or {}
            out[eid] = (*fonts[eid], bool(attr.get("m_bBold")), bool(attr.get("m_bItalic")))
    return out


def read_symbol(sid, g, styles=None, types=None):
    """A TitleBlock of a symbol's object graph; `styles` ({graphics style id: pen}) gives each
    line its pen, `types` (text_types) each label its font, size and style."""
    from ..core import objgraph
    lines, pens_ = [], []
    texts, labels = [], []
    sheet = None
    for i, o in enumerate(g.objects):
        f = o.fields
        if o.name == "Plane" and abs(f["m_xVec"][2]) < 1e-9 and abs(f["m_yVec"][2]) < 1e-9:
            # the plane of the sheet: its envelope is the paper, whose frame a parametric title block
            # draws from its parameters, not as lines (Golden Nugget's German ones, A4 to A0, their
            # origin the paper's lower right); where lines draw the frame, the same (Snowdon, rst_basic)
            (u0, v0), (u1, v1) = f["m_Envelope"]["m_corners"]
            (ox, oy, _oz), xv, yv = f["m_origin"], f["m_xVec"], f["m_yVec"]
            xs = [ox + u * xv[0] + v * yv[0] for u in (u0, u1) for v in (v0, v1)]
            ys = [oy + u * xv[1] + v * yv[1] for u in (u0, u1) for v in (v0, v1)]
            sheet = (min(xs), min(ys), max(xs), max(ys))
        elif o.name == "GLine":
            if f["m_GInfo"]["m_flags"] & 0x20:
                continue  # not printed (a revision table's cached grid; savedgraphics.GINFO_NOT_PRINTED)
            (t0, t1), (ox, oy, _oz), (dx, dy, _dz) = f["m_endParams"], f["m_origin"], f["m_dirVec"]
            lines.append((ox + t0 * dx, oy + t0 * dy, ox + t1 * dx, oy + t1 * dy))
            style = objgraph.ref(f["m_GInfo"]["m_categoryId"])
            pens_.append((styles or {}).get(style))
        elif o.name == "TextNoteData":
            item = _text_item(o)
            j = g.target(i, f.get("m_oRtfData"))
            if j is not None:
                rtf = bytes(g.objects[j].fields.get("m_arrRtfStream", [])).decode("cp1252", "replace")
                item.lines, item.size_pt = rtf_lines(rtf)
                item.family = rtf_family(rtf)
            kind = (types or {}).get(objgraph.ref(f.get("m_attrId")))
            if kind is not None:
                item.nominal_pt = kind[1] * 864
            texts.append(item)
        elif o.name == "TagNoteData":
            item = _text_item(o)
            item.param = next((d["m_paramId"]["m_id"]["m_id64"] for d in f.get("m_paramDataFormattingArr", [])
                               if isinstance(d, dict) and "m_paramId" in d), None)
            # label size, where its text type is not known (`types`): box height / 1.257, which
            # is near for some sizes only (Snowdon's sheet number 58 pt for 63). Tag families'
            # Arial labels are re-sized by the renderer (/ 1.144)
            item.size_pt = item.height * 12 * 72 / 1.257
            kind = (types or {}).get(objgraph.ref(f.get("m_attrId")))
            if kind is not None:  # the label's text type: its size as Revit prints it
                item.typed = True
                item.family, item.bold, item.italic = kind[0] or "", kind[2], kind[3]
                item.size_pt = printed_size(kind[1], turned=abs(item.base[0] - 1.0) > 1e-6)
                item.nominal_pt = kind[1] * 864
            labels.append(item)
    family = texts[0].family if texts else "Arial"
    for lb in labels:
        lb.family = lb.family if lb.typed and lb.family else family
    return TitleBlock(sid, lines, texts, labels, family=family, pens=pens_, sheet=sheet)


def project_params(rf, path, extra=()):
    """{BuiltInParameter id: value} of the project's string parameters (ProjectInfo)."""
    from ..core import objgraph
    out = {}
    for _eid, g in objgraph.elements(path, ("ProjectInfo",)):
        for o in g.objects:
            if o.name == "ParamValueSetAString":
                for e in o.fields.get("m_paramSet", []):
                    if isinstance(e.get("m_value"), str) and e["m_value"]:
                        out.setdefault(e["m_paramId"]["m_id"]["m_id64"], e["m_value"])
    return out


def sheet_views(path):
    """{sheet number: the sheet's view id}: the DBView records with m_sheetNumber."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, ("DBView*",)):
        number = g.objects[0].fields.get("m_sheetNumber")
        if number:
            out.setdefault(number, eid)
    return out


def _title_blocks(rf, path):
    """{symbol id: TitleBlock} of the symbols placed as title blocks."""
    from ..model import pens
    graphs = _symbol_graphs(path)
    styles = pens.style_pens(str(path))
    out = {}
    for sid, _view, _trf in _instances(rf, path).values():
        if sid in graphs and sid not in out:
            tb = read_symbol(sid, graphs[sid], styles, text_types(path))
            tb.images = images(rf, path, sid)
            out[sid] = tb
    return out


title_blocks = _disk("title_blocks", _title_blocks)


def _instances(rf, path):
    """{title block instance id: (symbol id, owner view id, InstanceInfo.m_Trf)}: FamilyInstances
    holding a FamInstTitleBlock."""
    from ..core import objgraph
    out = {}
    for eid, g in objgraph.elements(path, ("FamilyInstance",)):
        names = {o.name: o.fields for o in g.objects}
        if "FamInstTitleBlock" in names and "InstanceInfo" in names:
            info = names["InstanceInfo"]
            out[eid] = (objgraph.ref(info["m_symbolId"]), objgraph.ref(g.objects[0].fields.get("m_ownerDBViewId")),
                        info["m_Trf"])
    return out


instances = _disk("tb_instances", _instances)


def for_sheets(rf, path, sheets):
    """{sheet number: TitleBlock or None}: the title block placed on each sheet's view."""
    tbs = title_blocks(rf, path)
    views = sheet_views(path)
    on_view = {view: sid for sid, view, _trf in instances(rf, path).values()}
    return {s.number: tbs.get(on_view.get(views.get(s.number))) for s in sheets}


@dataclass
class Image:
    symbol_id: int
    png: bytes
    centre: tuple  # sheet feet
    size: tuple  # width, height feet


def images(rf, path, tb_symbol):
    """Raster images of a title block symbol: the GImage nodes of its saved graphics (channel
    103), each an ImageInfoScaled (images.py)."""
    from . import images as im
    from ..core import objgraph
    body = objgraph.channel_bodies(path, 103).get(tb_symbol)
    if not body:
        return []
    try:
        g = objgraph.decoder(path).graph(body)
    except Exception:  # a symbol whose saved graphics do not decode: no images
        return []
    syms = im.symbols(rf, path)
    out = []
    for i, o in enumerate(g.objects):
        if o.name != "GImage":
            continue
        j = g.target(i, o.fields.get("m_imageInfo"))
        got = im.placement(g.objects[j].fields, syms) if j is not None else None
        if got:
            centre, size, sid, data = got
            out.append(Image(sid, data, centre[:2], size))
    return out


def symbols_by_id(rf, path, ids):
    """Annotation family symbols (texts, labels, lines) for the given symbol ids, e.g. tag types."""
    from ..model import pens
    graphs = _symbol_graphs(path)
    styles = pens.style_pens(str(path))
    return {sid: read_symbol(sid, graphs[sid], styles) for sid in ids if sid in graphs}
