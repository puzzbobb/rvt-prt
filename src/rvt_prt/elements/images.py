"""Raster images placed on sheets and in views, from the records' object graphs.

- ImageSymbol: m_dpi, m_widthInFeet, m_heightInFeet, m_idImageHolder -> ImageHolder, whose
  ARasterImage.m_compressedImage is the original file (TIFF, JPEG or PNG; a PDF page is stored
  as a PNG).
- ImageInstance (channel 102): m_ownerDBViewId (a sheet or a view), m_pImageInfo ->
  ImageInfoScaled: m_Trf (m_or the image's centre in the owner's coordinates, feet), m_symbolId,
  m_dWidthScale, m_dHeightScale; or ImageInfo, the same with its own size, m_dWidth and m_dHeight
  (feet; the only kind before Revit 2020, whose ImageSymbol has no size). On M000 the Perennial logo's centre is (3.89, 18.86) in, as
  Revit prints it.
- An image in a family symbol (a title block's logo) is a GImage of the symbol's saved graphics
  (channel 103), its m_imageInfo the same ImageInfoScaled.
"""
import functools
from dataclasses import dataclass

SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*", b"BM", b"GIF8")


@dataclass
class PlacedImage:
    instance_id: int
    owner_view: int
    data: bytes
    centre: tuple  # owner coordinates, feet
    size: tuple  # width, height, feet


@functools.cache
def symbols(rf, path):
    """{ImageSymbol id: (width ft, height ft, file bytes)}."""
    from ..core import objgraph
    files = {}
    for eid, g in objgraph.elements(path, ("ImageHolder",)):
        raster = next((o.fields for o in g.objects if o.name == "ARasterImage"), None)
        if raster and raster.get("m_compressedImage"):
            files[eid] = bytes(raster["m_compressedImage"])
    out = {}
    for eid, g in objgraph.elements(path, ("ImageSymbol",)):
        f = g.objects[0].fields
        data = files.get(objgraph.ref(f.get("m_idImageHolder")))
        if data and data.startswith(SIGNATURES):
            out[eid] = (f.get("m_widthInFeet"), f.get("m_heightInFeet"), data)  # no size before 2020
    return out


def placement(info, syms):
    """(centre XYZ, (width, height) feet, symbol id, data) of an ImageInfoScaled's fields (the
    symbol's size scaled), or an ImageInfo's (its own m_dWidth, m_dHeight), or None."""
    from ..core import objgraph
    sid = objgraph.ref(info.get("m_symbolId"))
    if sid not in syms:
        return None
    w, h, data = syms[sid]
    if "m_dWidth" in info:
        size = (info["m_dWidth"], info["m_dHeight"])
    elif w is not None and "m_dWidthScale" in info:
        size = (w * info["m_dWidthScale"], h * info["m_dHeightScale"])
    else:
        return None
    return tuple(info["m_Trf"]["m_or"]), size, sid, data


MODULES = ("images", "objgraph", "registry", "container")


def placed(rf, path):
    """[PlacedImage] of the file's ImageInstances, disk-cached against the decoders' source."""
    from ..core import diskcache
    return diskcache.cached(path, "placed_images", MODULES, lambda: _placed(rf, path))


def _placed(rf, path):
    from ..core import objgraph
    syms = symbols(rf, path)
    out = []
    for eid, g in objgraph.elements(path, ("ImageInstance",)):
        info = next((o.fields for o in g.objects if o.name in ("ImageInfoScaled", "ImageInfo")), None)
        got = placement(info, syms) if info else None
        if got:
            centre, size, _sid, data = got
            out.append(PlacedImage(eid, objgraph.ref(g.objects[0].fields.get("m_ownerDBViewId")), data, centre, size))
    return out
