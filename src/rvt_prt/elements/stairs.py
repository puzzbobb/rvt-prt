"""Straight stair runs (StairsRun), landings (StairsLanding) and railings (BaseRailing) as plan lines,
decoded from the object graph.

Decoded:
- StairsRun: tread and riser edges from GLine records with abs(dir.z) <= 1e-6 and length >= 0.5 ft.
- StairsLanding: boundary edges from GLine records with abs(dir.z) <= 1e-4 and length >= 0.2 ft.
- BaseRailing / StairsRailing / Railing: resolves m_sketchId -> VarSketch curves (GLine and GArc).
"""
import functools
import math
from dataclasses import dataclass

import numpy as np

from ..core import objgraph


@dataclass
class Run:
    element_id: int
    edges: list  # [(z, (x0, y0), (x1, y1))] tread / riser edges, ascending z


@dataclass
class Landing:
    element_id: int
    edges: list  # [(z, (x0, y0), (x1, y1))] boundary edges


def _runs(path):
    runs_out = []
    for eid, g in objgraph.elements(path, ["StairsRun"]):
        glines = [o for o in g.objects if o.name == "GLine"]
        seen, edges = set(), []
        for gl in glines:
            f = gl.fields
            t0, t1 = f["m_endParams"]
            o, d = f["m_origin"], f["m_dirVec"]
            if abs(d[2]) > 1e-6 or t1 - t0 < 0.5:
                continue
            p0 = (o[0] + t0 * d[0], o[1] + t0 * d[1], o[2] + t0 * d[2])
            p1 = (o[0] + t1 * d[0], o[1] + t1 * d[1], o[2] + t1 * d[2])
            key = tuple(round(x, 3) for x in (*p0, *p1))
            if key not in seen:
                seen.add(key)
                edges.append((p0[2], p0, p1))
        if len(edges) >= 2:
            runs_out.append(Run(eid, sorted(edges)))

    landings_out = []
    for eid, g in objgraph.elements(path, ["StairsLanding"]):
        glines = [o for o in g.objects if o.name == "GLine"]
        seen, edges = set(), []
        for gl in glines:
            f = gl.fields
            t0, t1 = f["m_endParams"]
            o, d = f["m_origin"], f["m_dirVec"]
            if abs(d[2]) > 1e-4 or t1 - t0 < 0.2:
                continue
            p0 = (o[0] + t0 * d[0], o[1] + t0 * d[1], o[2] + t0 * d[2])
            p1 = (o[0] + t1 * d[0], o[1] + t1 * d[1], o[2] + t1 * d[2])
            key = tuple(round(x, 3) for x in (*p0, *p1))
            if key not in seen:
                seen.add(key)
                edges.append((p0[2], p0, p1))
        if edges:
            landings_out.append(Landing(eid, edges))

    sk_owners = {}
    for eid, g in objgraph.elements(path, ["BaseRailing", "StairsRailing", "Railing"]):
        sk_ref = objgraph.ref(g.objects[0].fields.get("m_sketchId"))
        if sk_ref:
            sk_owners[sk_ref] = eid

    railing_landings = []
    for eid, g in objgraph.elements(path, ["VarSketch"]):
        if eid not in sk_owners:
            continue
        owner_id = sk_owners[eid]
        edges = []
        for o in g.objects:
            if o.name == "GArc":
                f = o.fields
                a0, a1 = f["m_endParams"]
                xx, xy, xz = f["m_xVec"]
                yx, yy, yz = f["m_yVec"]
                r = f["m_radius"]
                cx, cy, cz = f["m_center"]
                n = max(8, int(abs(a1 - a0) / (math.pi / 32)))
                prev = None
                for i in range(n + 1):
                    a = a0 + (a1 - a0) * i / n
                    ca, sa = math.cos(a), math.sin(a)
                    curr = (cx + r * (ca * xx + sa * yx), cy + r * (ca * xy + sa * yy), cz + r * (ca * xz + sa * yz))
                    if prev is not None:
                        edges.append((curr[2], prev, curr))
                    prev = curr
            elif o.name == "GLine":
                f = o.fields
                t0, t1 = f["m_endParams"]
                ox, oy, oz = f["m_origin"]
                dx, dy, dz = f["m_dirVec"]
                p0 = (ox + t0 * dx, oy + t0 * dy, oz + t0 * dz)
                p1 = (ox + t1 * dx, oy + t1 * dy, oz + t1 * dz)
                edges.append((p0[2], p0, p1))
        if edges:
            railing_landings.append(Landing(owner_id, edges))

    return runs_out + landings_out + railing_landings


runs = functools.cache(lambda path: __import__("rvt_prt.core.diskcache", fromlist=["cached"]).cached(
    path, "stair_runs", ("stairs", "objgraph", "registry", "container"), lambda: _runs(path)))


def plan_edges(rs, axes=None, origin=None):
    """(placed_runs, placed_landings) in the host's coordinates."""
    ax = np.eye(3) if axes is None else np.array(axes, dtype=np.float64)
    org = np.zeros(3) if origin is None else np.array(origin, dtype=np.float64)
    placed_runs, placed_landings = [], []
    for r in rs:
        if isinstance(r, Landing):
            edges = [(float((np.array(a) @ ax + org)[2]), tuple((np.array(a) @ ax + org)[:2]), tuple((np.array(b) @ ax + org)[:2]))
                     for _z, a, b in r.edges]
            placed_landings.append(Landing(r.element_id, edges))
        elif isinstance(r, Run):
            edges = [(float((np.array(a) @ ax + org)[2]), tuple((np.array(a) @ ax + org)[:2]), tuple((np.array(b) @ ax + org)[:2]))
                     for _z, a, b in r.edges]
            placed_runs.append(Run(r.element_id, edges))
        elif isinstance(r, tuple) and len(r) == 3:
            # backward compatibility if raw edge tuple
            _z, a, b = r
            A = np.array(a) @ ax + org
            B = np.array(b) @ ax + org
            placed_runs.append((float(A[2]), tuple(A[:2]), tuple(B[:2])))
    if placed_landings:
        return placed_runs, placed_landings
    if placed_runs and isinstance(placed_runs[0], Run):
        return placed_runs, []
    return placed_runs
