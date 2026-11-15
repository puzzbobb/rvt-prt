"""Placed viewports and their views' frames, from the records' object graphs (channel 102).

Viewport: m_detailNumber, m_labelLength, m_labelOrigin, m_offset, m_scale, m_attrId (the
viewport type), m_dbDrawingId (the sheet's drawing), m_dbViewId, m_ownerDBViewId (the sheet's
view). A sheet point is m_offset + m_scale x (view coordinates), checked by placing duct
terminals of Snowdon HVAC on its M101 print.

A view's frame is its Viewer's (DBView.m_viewerId -> Viewer, Section or InteriorElevArrow):
m_boundedSpace {m_orig, m_basis rows right / up / the looking direction, m_boundOffset [[max,
min] per axis], m_boundActive}; m_viewerFlags bit 0 the crop region active (Snowdon's RCPs L2..R2
have it off: Revit prints the whole model); m_bReflected a ceiling plan (it looks up).
"""
from dataclasses import dataclass


@dataclass
class Viewport:
    element_id: int
    detail: str
    label_length: float
    label_origin: tuple
    offset: tuple
    scale: float
    drawing_id: int  # the sheet's m_dbDrawingId
    view_id: int
    crop: tuple | None = None  # (xmin, ymin, xmax, ymax) in view coordinates
    owner_view: int | None = None  # Element.m_ownerDBViewId: the sheet's own view
    attr_id: int | None = None  # m_attrId: the viewport type
    show_title: bool = True  # the type's ViewportAttributes.m_showLabel
    title_family: int | None = -1  # the type's view title family (m_familyTagId); -1 unread, None: none
    title_line: bool = True  # the type's m_showExtensionLine
    depth: tuple | None = None  # (near, far) along the looking direction: sections, elevations (viewer_frames)
    view_origin: tuple | None = None
    view_basis: tuple | None = None
    reflected: bool = False  # Viewer.m_bReflected: a ceiling plan




def placed_viewports(rf, path):
    """Viewport records with a detail number (placed on a sheet)."""
    from ..core import objgraph
    out = []
    for eid, g in objgraph.elements(path, ("Viewport",)):
        f = g.objects[0].fields
        detail = f.get("m_detailNumber") or ""
        if not detail.strip():
            continue
        out.append(Viewport(eid, detail, f["m_labelLength"], tuple(f["m_labelOrigin"]), tuple(f["m_offset"]), f["m_scale"],
                            objgraph.ref(f["m_dbDrawingId"]), objgraph.ref(f["m_dbViewId"]),
                            owner_view=objgraph.ref(f.get("m_ownerDBViewId")), attr_id=objgraph.ref(f.get("m_attrId"))))
    return out


NO_CROP = (-1e4, -1e4, 1e4, 1e4)  # view feet: the crop region off


def viewer_frames(path, view_ids):
    """{view id: (origin, (right, up, look), crop, (near, far), reflected)} from each view's
    Viewer. crop is (xmin, ymin, xmax, ymax) in view feet (NO_CROP where inactive); along the
    looking direction, near (0: the view plane, where a section cuts) and far (None where
    inactive)."""
    from ..core import objgraph
    bodies = objgraph.channel_bodies(path, 102)
    out = {}
    for vid in view_ids:
        view = objgraph.root(path, bodies[vid]) if vid in bodies else None
        viewer = objgraph.ref((view or {}).get("m_viewerId"))
        f = objgraph.root(path, bodies[viewer]) if viewer in bodies else None
        bs = (f or {}).get("m_boundedSpace")
        if not bs:
            continue
        (xh, xl), (yh, yl), (zh, zl) = bs["m_boundOffset"]
        (xa_h, xa_l), (ya_h, ya_l), (za_h, za_l) = bs["m_boundActive"]
        crop = (xl if xa_l else NO_CROP[0], yl if ya_l else NO_CROP[1], xh if xa_h else NO_CROP[2], yh if ya_h else NO_CROP[3])
        if "m_viewerFlags" in f and not f["m_viewerFlags"] & 1:
            crop = NO_CROP
        depth = (zl if za_l else 0.0, zh if za_h else None)
        out[vid] = (tuple(bs["m_orig"]), tuple(tuple(r) for r in bs["m_basis"]), crop, depth, bool(f.get("m_bReflected")))
    return out


def title_types(path, type_ids):
    """{viewport type id: (m_showLabel, title family, m_showExtensionLine)} from each
    ViewportAttributes record's object graph: m_showLabel 0 hides the title (Snowdon's "No
    Title"), 1 and 2 show it; m_familyTagId is the view title family, None when the type has
    none (then the title is its extension line alone: oracle/testfamily)."""
    from ..core import objgraph, registry
    dec = objgraph.Decoder(registry.load(str(path)))
    out = {}
    bodies = objgraph.channel_bodies(path, 102)
    for t in type_ids:
        body = bodies.get(t)
        if not body:
            continue
        try:
            f = dec.graph(body).objects[0].fields
        except (ValueError, KeyError, IndexError):
            continue
        fam = f["m_familyTagId"]["m_id"]["m_id64"]
        out[t] = (f["m_showLabel"], fam if fam >= 0 else None, bool(f["m_showExtensionLine"]))
    return out


def read(rf, path):
    vps = placed_viewports(rf, path)
    types = title_types(path, {v.attr_id for v in vps})
    for v in vps:
        show, v.title_family, v.title_line = types.get(v.attr_id, (1, -1, True))
        v.show_title = show != 0
    frames = viewer_frames(path, {v.view_id for v in vps})
    for v in vps:
        if v.view_id in frames:
            v.view_origin, v.view_basis, v.crop, v.depth, v.reflected = frames[v.view_id]
    return vps
