"""Fonts and text: embedded fonts, text widths, word wrap, notes' line metrics, text blocks hung
from a TextData anchor."""
import math
from fractions import Fraction


from .. import pdf
from .primitives import PT


def font_alias(page, name):
    """Embed the font `name` (a (family, bold, italic) spec, or a base-14 name meaning Arial) in
    the page from its file (fonts.file_for), and return the name to draw with. Unembedded base-14 text is
    left out by some viewers; each font file is written once per document."""
    from ..model import fonts
    a = fonts.alias(name)
    if a not in pdf.page_font_names(page):
        path = fonts.file_for(fonts.spec(name))
        if path:
            pdf.embed_font(page, a, path=path)
        else:
            pdf.embed_font(page, a, buffer=pdf.builtin_font(fonts.builtin(name)).buffer)
    return a


def text_len(text, font, size):
    from ..model import fonts
    return fonts.text_length(text, font, size)


def put_text(page, point, text, fontname="helv", **kw):
    """page.insert_text with an embedded font (one with the text's glyphs: fonts.covering)."""
    from ..model import fonts
    return page.insert_text(point, text, fontname=font_alias(page, fonts.covering(fontname, text)), **kw)


def scale_text(scale):
    """1/96 -> 1/8" = 1'-0"; 1.0 -> 1 : 1."""
    if not scale:
        return ""
    ratio = round(1 / scale)
    if ratio in (1, 2, 3, 4, 6, 12) or (ratio % 12 == 0 and ratio > 12):
        inch = Fraction(12, ratio)
        return f'{inch.numerator}/{inch.denominator}" = 1\'-0"' if inch.denominator != 1 else f'{inch.numerator}" = 1\'-0"'
    return f"1 : {ratio}"


def annotations_cap():
    from ..elements import annotations
    return annotations.CAP_HEIGHT


LINE_PITCH = 1.137  # Revit's line spacing for a note, x the text size (Snowdon prints)


ASCENT = 0.905  # Arial ascent, x the text size


# Revit's printed Trebuchet MS note lines are 0.85% wider than the font's advance widths (median
# of 26 lines on M000); its Arial notes wrap as the plain widths do
WRAP_WIDTH_FACTOR = {"trebuchet ms": 1.0085}


def wrap(text, width_pt, size, font="helv", factor=1.0):
    """Greedy word wrap at `width_pt` (Helvetica, Arial's metrics, by default); explicit breaks kept."""
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}" if line else word
            if line and text_len(trial, font, size) * factor > width_pt:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def wrap_runs(pieces, width_pt, size, factor=1.0):
    """wrap() of a line in runs of their own fonts ([(text, font)]): [[(text, font)]] per line,
    broken between words as wrap breaks them, each run keeping its font."""
    words = []  # [[(text, font)]]: a word may span runs ("Origin" bold, "." regular)
    for text, font in pieces:
        for k, part in enumerate(text.split(" ")):
            if k > 0:
                words.append([])  # a space: the next word begins
            if not words:
                words.append([])
            if part:
                words[-1].append((part, font))
    lines, line = [], []

    def length(ws):
        runs = _joined(ws)
        return sum(text_len(t, f, size) for t, f in runs)

    for word in words:
        trial = line + [word]
        if line and length(trial) * factor > width_pt:
            lines.append(_joined(line))
            line = [word]
        else:
            line = trial
    lines.append(_joined(line))
    return lines


def _joined(words):
    """Words ([[(text, font)]]) as one line's runs, a space between words, runs of one font merged."""
    out = []
    for k, word in enumerate(words):
        if k > 0 and out:  # the space between words, in the font of the run before it
            out[-1] = (out[-1][0] + " ", out[-1][1])
        for t, f in word:
            if out and out[-1][1] == f:
                out[-1] = (out[-1][0] + t, f)
            else:
                out.append((t, f))
    return out


NOTE_PITCH = {"arial": 1.137, "trebuchet ms": 1.265}  # line pitch / size, measured on the print


TB_PITCH = 1.267  # Snowdon title block: 12.5 pt Trebuchet lines 0.22 in apart
# ... x the text type's own size (Font.m_size), where known: the printed size is rounded to the
# half point and the pitch is not (Snowdon's M001, 9 pt type printed 12.5: 15.84 pt apart, 1.760;
# M000, 13.5 pt type printed 19: 23.81 pt apart, 1.764, where 1.267 x 19 put the third line 1.5 pt low)
TB_PITCH_NOMINAL = 1.763


TB_ASCENT, TB_DESCENT = 0.905, 0.212
# a title block line's baseline below the top of its line, x the text size: measured on the
# baselines of Revit's PDFs (Snowdon's M001, 19 lines of 9.5 to 63 pt, and test02's A101), where
# TB_ASCENT put every line 0.08 of its size too high
TB_BASELINE = 0.985


def tb_font(bold, italic, family="Trebuchet MS"):
    return (family, bool(bold), bool(italic))


def draw_text_block(page, origin, width_ft, flags, lines, size, family="Trebuchet MS", base=(1.0, 0.0), nominal=None):
    """Lines hung from a TextData anchor (m_flags: 0x40/0x80/0x100 left/centre/right,
    0x200/0x400/0x800 top/middle/bottom), each aligned like the anchor. A line may carry its runs
    of mixed style (titleblock.rtf_lines), drawn each in its own font where the line is not
    wrapped. `base` is the direction the text runs in on the sheet (y up): the block is laid out
    as if it ran left to right, then turned about its anchor. `nominal`: the text type's size in
    points, which spaces the lines (TB_PITCH_NOMINAL)."""
    H = page.rect.height
    width = width_ft * PT
    h = "centre" if flags & 0x80 else "right" if flags & 0x100 else "left"
    v = "middle" if flags & 0x400 else "bottom" if flags & 0x800 else "top"
    pitch = TB_PITCH_NOMINAL * nominal if nominal else TB_PITCH * size
    wrapped = []
    for text, bold, italic, *rest in lines:
        runs = rest[2] if len(rest) > 2 else None
        if runs and text and width > 0:  # words of mixed style, wrapped across their runs
            for part in wrap_runs([(t, tb_font(b, i, family)) for t, b, i in runs if t], width + 0.5, size):
                wrapped.append(("".join(t for t, _f in part), bold, italic, part))
            continue
        parts = wrap(text, width + 0.5, size, tb_font(bold, italic, family)) if text and width > 0 else [text]
        for part in parts:
            wrapped.append((part, bold, italic, [(t, tb_font(b, i, family)) for t, b, i in runs] if runs and len(parts) == 1 else None))
    lines = wrapped
    height = len(lines) * pitch
    x, y = origin[0] * PT, H - origin[1] * PT
    left = x - {"left": 0, "centre": width / 2, "right": width}[h]
    top = {"top": y, "middle": y - height / 2, "bottom": y - height + (TB_PITCH - 1 - TB_DESCENT) * size}[v]
    base_y = top + TB_BASELINE * size
    ux, uy = base[0], -base[1]  # the text's direction on the page (y down)
    turned = abs(ux - 1.0) > 1e-6 or abs(uy) > 1e-6
    angle = math.degrees(math.atan2(-uy, ux))  # counter-clockwise

    def put(lx, at_y, text, font):
        if not turned:
            put_text(page, (lx, at_y), text, fontsize=size, fontname=font)
            return
        dx, dy = lx - x, at_y - y  # along the text, and down from it, from the anchor
        pt = pdf.Point(x + dx * ux - dy * uy, y + dx * uy + dy * ux)
        quarter = round(angle / 90) * 90
        if abs(angle - quarter) < 1e-6:
            put_text(page, pt, text, fontsize=size, fontname=font, rotate=quarter % 360)
        else:
            put_text(page, pt, text, fontsize=size, fontname=font, morph=(pt, pdf.Matrix(angle)))

    for text, bold, italic, runs in lines:
        font = tb_font(bold, italic, family)
        if text:
            pieces = runs or [(text, font)]
            w = sum(text_len(t, f, size) for t, f in pieces)
            lx = {"left": left, "centre": x - w / 2, "right": x - w}[h]
            for t, f in pieces:
                put(lx, base_y, t, f)
                lx += text_len(t, f, size)
        base_y += pitch
