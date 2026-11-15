"""Fonts: the family each text names in the file (RTF \\fonttbl, text types), drawn with real
font files (a .rvt names fonts but embeds none).

A font is named by a spec (family, bold, italic). The base-14 names used earlier map to Arial:
helv, hebo, heit, hebi. Font files are found in `RVT_PRT_FONTS` (folders, os.pathsep apart), a
checkout's own `fonts/`, then the user's and the system's font folders. Without a file for the
family: its free metric-compatible substitute (Arial -> Liberation Sans / Arimo, Arial Narrow ->
Liberation Sans Narrow), then Arial's; without any, PyMuPDF's built-in Helvetica (Arial's
metrics). Text the font has no glyphs for (Japanese notes in Arial) is set in a CJK font: Noto
Sans CJK where installed, else PyMuPDF's built-in Droid Sans Fallback.
"""
import functools
import json
import os
import pathlib
import sys

from .. import pdf
from ..core import paths

BASE14 = {"helv": ("Arial", False, False), "hebo": ("Arial", True, False),
          "heit": ("Arial", False, True), "hebi": ("Arial", True, True)}
BUILTIN = {(False, False): "helv", (True, False): "hebo", (False, True): "heit", (True, True): "hebi"}
# free fonts drawn in place of a family that is not installed, metrics alike
SUBSTITUTES = {"arial": ("Liberation Sans", "Arimo"), "arial narrow": ("Liberation Sans Narrow",),
               "helvetica": ("Liberation Sans", "Arimo"), "times new roman": ("Liberation Serif", "Tinos"),
               "courier new": ("Liberation Mono", "Cousine")}
# fonts with the glyphs a project's own may lack, tried in order; then BUILTIN_CJK
FALLBACKS = ("Noto Sans CJK JP", "Source Han Sans JP", "Noto Sans JP")
BUILTIN_CJK = "Droid Sans Fallback"  # the PDF library's own (pdf.builtin_font("cjk")), in every wheel
SUFFIXES = (".ttf", ".otf", ".ttc")


def font_dirs():
    """The folders searched for font files, in order."""
    out = [pathlib.Path(p) for p in os.environ.get("RVT_PRT_FONTS", "").split(os.pathsep) if p]
    if paths.FONTS is not None:
        out.append(paths.FONTS)
    home = pathlib.Path.home()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        out += [pathlib.Path(local) / "Microsoft" / "Windows" / "Fonts"] if local else []
        out.append(pathlib.Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
    elif sys.platform == "darwin":
        out += [home / "Library" / "Fonts", pathlib.Path("/Library/Fonts"), pathlib.Path("/System/Library/Fonts")]
    else:
        data = os.environ.get("XDG_DATA_HOME") or home / ".local" / "share"
        out += [pathlib.Path(data) / "fonts", home / ".fonts", pathlib.Path("/usr/local/share/fonts"),
                pathlib.Path("/usr/share/fonts")]
    return [d for d in out if d.is_dir()]


def _family_of(font):
    name = font.name
    for suffix in (" Bold Italic", " Bold", " Italic", " Regular"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


@functools.cache
def registry():
    """{(family lower-case, bold, italic): font file}, the first folder's file winning. Each
    file's names are read once and kept in an index in the cache folder (a system's fonts are
    hundreds of files)."""
    index_path = paths.CACHE / "fonts.json"
    try:
        index = json.loads(index_path.read_text())
    except (OSError, ValueError):
        index = {}
    fresh, changed, out = {}, False, {}
    for d in font_dirs():
        for f in sorted(p for p in d.rglob("*") if p.suffix.lower() in SUFFIXES):
            try:
                st = f.stat()
            except OSError:
                continue
            key, stamp = str(f), [st.st_mtime_ns, st.st_size]
            entry = index.get(key)
            if entry is None or entry[0] != stamp:
                try:
                    font = pdf.font_from_file(key)
                    entry = [stamp, _family_of(font), bool(font.is_bold), bool(font.is_italic)]
                except Exception:
                    entry = [stamp, None, False, False]
                changed = True
            fresh[key] = entry
            if entry[1]:
                out.setdefault((entry[1].lower(), entry[2], entry[3]), key)
    if changed or len(fresh) != len(index):
        try:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(json.dumps(fresh))
        except OSError:
            pass
    return out


def spec(font):
    """A (family, bold, italic) spec from a spec or a base-14 name."""
    if isinstance(font, str):
        return BASE14.get(font, (font, False, False))
    return font


@functools.cache
def file_for(font):
    """The font file to draw `font` with: its family's, its substitute's, Arial's (or Arial's
    substitute's); a built-in font's written to the cache folder when it is TrueType (DWFx wants
    a file); None for the built-in Helvetica."""
    family, bold, italic = spec(font)
    if family == BUILTIN_CJK:
        return _builtin_file("cjk")
    reg = registry()
    for fam in (family, *SUBSTITUTES.get(family.lower(), ()), "Arial", *SUBSTITUTES["arial"]):
        for key in ((fam.lower(), bold, italic), (fam.lower(), bold, False), (fam.lower(), False, False)):
            if key in reg:
                return reg[key]
    return None


@functools.cache
def _builtin_file(name):
    """A PyMuPDF built-in font written out as a file, if TrueType or OpenType, else None."""
    buf = pdf.builtin_font(name).buffer
    if not buf or buf[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return None
    f = paths.CACHE / "fonts" / f"{name}.ttf"
    try:
        if not f.exists() or f.stat().st_size != len(buf):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(buf)
    except OSError:
        return None
    return str(f)


def builtin(font):
    """The PyMuPDF built-in font name to draw `font` with when it has no file."""
    family, bold, italic = spec(font)
    return "cjk" if family == BUILTIN_CJK else BUILTIN[(bold, italic)]


@functools.cache
def font_object(font):
    path = file_for(font)
    if path:
        return pdf.font_from_file(path)
    return pdf.builtin_font(builtin(font))


def covering(font, text):
    """`font`'s spec, or, when it lacks a glyph of `text`, the first FALLBACKS font that has them
    all, else BUILTIN_CJK: Japanese notes name Meiryo UI or MS Gothic, which are seldom installed,
    and the Arial used in their place has no kana or kanji (2019 and 2025 サンプル構造's notes
    printed blank)."""
    s = spec(font)
    if text.isascii():
        return s
    f = font_object(s)
    if all(c.isspace() or f.has_glyph(ord(c)) for c in text):
        return s
    for family in FALLBACKS + (BUILTIN_CJK,):
        if family == BUILTIN_CJK or (family.lower(), False, False) in registry():
            fb = font_object((family, False, False))
            if all(c.isspace() or fb.has_glyph(ord(c)) for c in text):
                return (family, s[1], s[2])
    return s


def text_length(text, font, size):
    return font_object(covering(font, text)).text_length(text, fontsize=size)


def alias(font):
    family, bold, italic = spec(font)
    return "F" + "".join(c for c in family if c.isalnum())[:20] + ("B" if bold else "") + ("I" if italic else "")
