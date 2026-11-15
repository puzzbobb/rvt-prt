"""Every use of PyMuPDF, the PDF library, goes through this module: no other module imports it.

PyMuPDF is licensed AGPL-3.0 (or commercially, by Artifex). Kept here, it can be replaced by a
permissive library (ReportLab to write, pypdfium2 to read) by reimplementing this module alone,
the names below and the methods rvt_prt calls on what they return:

Writing (render/, formats/drawing.from_page, render/pool):
- Document (new_document, open_document): new_page(width=, height=), insert_pdf(doc), len(),
  indexing and iteration over pages; Page.parent is its document.
- Page: rect, mediabox, set_mediabox(Rect), new_shape(), insert_text(point, text, fontname=,
  fontsize=, color=, morph=(Point, Matrix)).
- Shape: draw_line(p, q), draw_polyline([Point]), draw_rect(Rect), draw_circle(Point, r),
  finish(color=, fill=, width=, closePath=, lineCap=, dashes=, even_odd=), commit().
- Point(x, y) (.x, .y), Rect(x0, y0, x1, y1) (x0..y1, width, height, tl/tr/br/bl, |), Matrix(degrees).
- Font (font_from_file, builtin_font): name, buffer, is_bold, is_italic, has_glyph(ord(c)),
  text_length(text, fontsize=).

Reading (metrics/, formats/drawing.read_pdf, tests): open_document, toc, page_text, page_words,
page_drawings, page_text_dict, rasterise, write_png.

PDF space here is PyMuPDF's: points, y down from the page's top.
"""
import numpy as np
import re

import pymupdf

Point = pymupdf.Point
Rect = pymupdf.Rect
Matrix = pymupdf.Matrix


# --- documents ---------------------------------------------------------------------------------

def new_document():
    """An empty PDF document."""
    return pymupdf.open()


def open_document(source):
    """A PDF document from a path or from its bytes."""
    if isinstance(source, (bytes, bytearray)):
        return pymupdf.open("pdf", source)
    return pymupdf.open(str(source))


def document_bytes(doc):
    """The document as PDF bytes, unfinished (a worker's page, merged later)."""
    return doc.tobytes()


def finished_bytes(doc, bookmarks):
    """The document as its file's bytes: `bookmarks` [(title, page number from 1)] at level 1,
    only the glyphs used of each embedded font (needs fontTools), unused objects dropped."""
    doc.set_toc([[1, title, page] for title, page in bookmarks])
    try:
        doc.subset_fonts()
    except Exception:
        pass
    return doc.tobytes(garbage=1, deflate=True)


def joined_bytes(pages, bookmarks):
    """Finished documents (finished_bytes, as bytes) joined in order into one file's bytes, with
    `bookmarks` [(title, page number from 1)]: nothing is subset or deflated again."""
    doc = new_document()
    for b in pages:
        doc.insert_pdf(open_document(b))
    doc.set_toc([[1, title, page] for title, page in bookmarks])
    return doc.tobytes(garbage=1, deflate=True)


def toc(doc):
    """{page index: title} of the document's bookmarks."""
    return {page - 1: title for _level, title, page in doc.get_toc()}


# --- drawing -----------------------------------------------------------------------------------

def stroke_raw(page, operators):
    """Append raw content-stream operators (str, balanced q / Q) to the page: thousands of
    segments at once, where a Shape costs about 0.15 ms a segment."""
    pymupdf.TOOLS._insert_contents(page, operators.encode(), True)


_WRAPPED = set()
_wrap_contents = pymupdf.Page.wrap_contents


def _wrap_once(self):
    """PyMuPDF re-counts the page's whole content stream on every Shape.commit (14 s of a 72 s
    sheet); everything drawn here is balanced, so once per page is enough."""
    key = (id(self.parent), self.xref)
    if key not in _WRAPPED:
        _WRAPPED.add(key)
        _wrap_contents(self)


pymupdf.Page.wrap_contents = _wrap_once  # type: ignore[method-assign]


def drawn_boxes(page):
    """[Rect] of everything drawn on the page so far."""
    return [Rect(r) for _kind, r in page.get_bboxlog()]


# --- fonts -------------------------------------------------------------------------------------

def font_from_file(path):
    return pymupdf.Font(fontfile=str(path))


def builtin_font(name):
    """One of the library's own fonts: "helv", "hebo", "heit", "hebi" (Helvetica), "cjk"."""
    return pymupdf.Font(name)


def page_font_names(page):
    """The names of the fonts the page has embedded."""
    return {f[4] for f in page.get_fonts()}


def embed_font(page, name, path=None, buffer=None):
    """Embed a font in the page under `name`, from its file or its bytes (once per document)."""
    if path:
        xref = page.insert_font(fontname=name, fontfile=path)
    else:
        xref = page.insert_font(fontname=name, fontbuffer=buffer)
    try:
        _plain_text_map(page.parent, xref, pymupdf.Font(fontfile=path) if path else pymupdf.Font(fontbuffer=buffer))
    except Exception:  # noqa: BLE001 - the text is drawn the same; only what is read back of it differs
        pass


_BF = re.compile(rb"<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4})>\s*<([0-9A-Fa-f]{4})>")


def _plain_text_map(doc, xref, font):
    """Make the embedded font's glyphs read back as the plain characters that draw them. A glyph
    many characters share is given one of them in the font's ToUnicode map, and not the plain one:
    Trebuchet MS's hyphen read back as U+2010 and Arial's as the soft hyphen U+00AD, so that
    "7765328-33-M" was not found by a search, nor copied as typed. Each printable ASCII character
    is mapped again, after the ranges (the later entry is the one readers take)."""
    kind, ref = doc.xref_get_key(xref, "ToUnicode")
    if kind != "xref":
        return
    cmap_xref = int(ref.split()[0])
    stream = doc.xref_stream(cmap_xref)
    if not stream or b"endcmap" not in stream:
        return
    wanted = {}  # glyph -> the printable ASCII character it draws (the first, where several do)
    for cp in range(0x20, 0x7F):
        gid = font.has_glyph(cp)
        if gid:
            wanted.setdefault(gid, cp)
    reads = {}  # of those glyphs, the character each reads back as now (the last entry naming it)
    for lo, hi, uni in _BF.findall(stream):
        lo, hi, uni = int(lo, 16), int(hi, 16), int(uni, 16)
        for gid in wanted:
            if lo <= gid <= hi:
                reads[gid] = uni + gid - lo
    again = {gid: cp for gid, cp in wanted.items() if reads.get(gid) != cp}
    if not again:
        return
    block = b"%d beginbfchar\n" % len(again) + b"".join(b"<%04x> <%04x>\n" % item for item in sorted(again.items())) + b"endbfchar\n"
    head, tail = stream.rsplit(b"endcmap", 1)
    doc.update_stream(cmap_xref, head + block + b"endcmap" + tail)


# --- images ------------------------------------------------------------------------------------

def image_stream(data):
    """An image's bytes (TIFF, BMP, ...) as PNG when it has alpha, else JPEG (quality 85)."""
    pix = pymupdf.Pixmap(data)
    return pix.tobytes("png") if pix.alpha else pix.tobytes("jpeg", jpg_quality=85)


def insert_image(page, rect, stream=None, xref=None):
    """Place an image in `rect`, stretched to it, from its bytes or an image already in the
    document (its xref); the xref."""
    if xref is not None:
        return page.insert_image(rect, xref=xref, keep_proportion=False)
    return page.insert_image(rect, stream=stream, keep_proportion=False)


# --- reading -----------------------------------------------------------------------------------

def page_text(page):
    """The page's text."""
    return page.get_text()


def page_words(page):
    """[(x0, y0, x1, y1, word, ...)] of the page's words."""
    return page.get_text("words")


def page_text_dict(page):
    """The page's text as blocks / lines / spans (PyMuPDF's "dict" layout)."""
    return page.get_text("dict")


def page_drawings(page):
    """The page's vector paths (PyMuPDF's get_drawings layout: items "l", "c", "re", "qu")."""
    return page.get_drawings()


def rasterise(page, dpi, gray=False):
    """The page as a uint8 array, (height, width, 3) RGB or (height, width) grey, white
    background."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY if gray else pymupdf.csRGB, alpha=False)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width * pix.n]
    return a if gray else a.reshape(pix.height, pix.width, 3)


def write_png(rgb, path):
    """A (height, width, 3) uint8 array to a PNG file."""
    h, w = rgb.shape[:2]
    pymupdf.Pixmap(pymupdf.csRGB, w, h, np.ascontiguousarray(rgb, np.uint8).tobytes(), False).save(str(path))
