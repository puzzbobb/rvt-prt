"""Sheet coordinates and the low-level drawing every part of a sheet uses: model point to sheet,
segment clipping, segments stroked as raw content streams, line patterns, leaders. 1 sheet foot = 864 pt."""
import math

import numpy as np

from .. import pdf


PT = 864.0


def _clip_to_rect(x, y, rect):
    """Liang-Barsky clip of N segments (x, y: (N, 2) end coordinates) to rect (x0, y0, x1, y1):
    (keep mask, clipped x, clipped y); segments left with no length are dropped."""
    x0, y0, x1, y1 = rect
    dx, dy = x[:, 1] - x[:, 0], y[:, 1] - y[:, 0]
    t0, t1 = np.zeros(len(x)), np.ones(len(x))
    ok = np.ones(len(x), bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        for pd, qd in ((-dx, x[:, 0] - x0), (dx, x1 - x[:, 0]), (-dy, y[:, 0] - y0), (dy, y1 - y[:, 0])):
            r = qd / pd
            par = pd == 0
            ok &= ~(par & (qd < 0))
            t0 = np.where(~par & (pd < 0), np.maximum(t0, r), t0)
            t1 = np.where(~par & (pd > 0), np.minimum(t1, r), t1)
    ok &= t0 < t1
    cx = np.stack([x[:, 0] + t0 * dx, x[:, 0] + t1 * dx], 1)
    cy = np.stack([y[:, 0] + t0 * dy, y[:, 0] + t1 * dy], 1)
    return ok, cx, cy


def stroke_segments(page, x, y, colour, width, cap=1, dashes=None):
    """Stroke N line segments given by (N, 2) PDF-space x, y (points, y up) as one content stream
    of raw path operators: a Shape's draw_line costs about 0.15 ms a segment, this a few
    microseconds."""
    if not len(x):
        return
    if isinstance(dashes, tuple):  # a line pattern (pens.line_patterns): explicit dashes, butt ends
        x, y = fitted_dashes(np.asarray(x, float), np.asarray(y, float), dashes)
        dashes, cap = None, 0
        if not len(x):
            return
    body = "\n".join(f"{a:.3f} {c:.3f} m {b:.3f} {d:.3f} l" for (a, b), (c, d) in zip(x.tolist(), y.tolist()))
    dash_cmd = f"[{dashes}] 0 d" if dashes else "[] 0 d"
    head = f"q {width:g} w {cap} J {colour[0]:.4g} {colour[1]:.4g} {colour[2]:.4g} RG {dash_cmd}\n"
    pdf.stroke_raw(page, head + body + "\nS Q\n")


def _joined_runs(x, y, tol=0.01):
    """Consecutive segments that continue one another (the next starts where one ends, in the
    same direction) joined into one: hidden-line removal leaves a line in pieces, and a pattern
    is fitted to the whole line."""
    if len(x) < 2:
        return x, y
    out_x, out_y = [list(x[0])], [list(y[0])]
    for (x0, x1), (y0, y1) in zip(x[1:].tolist(), y[1:].tolist()):
        px, py = out_x[-1], out_y[-1]
        d0 = np.array([px[1] - px[0], py[1] - py[0]])
        d1 = np.array([x1 - x0, y1 - y0])
        n0, n1 = np.hypot(*d0), np.hypot(*d1)
        if (abs(x0 - px[1]) < tol and abs(y0 - py[1]) < tol and n0 > 0 and n1 > 0
                and abs(d0[0] * d1[1] - d0[1] * d1[0]) < tol * max(n0, n1) and d0 @ d1 > 0):
            px[1], py[1] = x1, y1
        else:
            out_x.append([x0, x1]), out_y.append([y0, y1])
    return np.array(out_x), np.array(out_y)


def fitted_dashes(x, y, pattern):
    """(x, y) of the dashes of N segments ((N, 2) points) drawn in a line pattern (dash, gap, ...
    points, starting with a dash), as Revit prints them: at the pattern's own size, started
    halfway through its first dash (test02's elevation door swing, 18 pt lines in a 9 / 9 "Dash":
    4.5 dash, 9 gap, 4.5 dash, so a dash at each end and its chevron at the hinge side). Pieces
    of one line (hidden-line removal) are joined first."""
    x, y = _joined_runs(x, y)
    pat = np.asarray(pattern, float)
    period = pat.sum()
    if period <= 0:
        return x, y
    phase = pat[0] / 2
    edges = np.concatenate([[0.0], np.cumsum(pat)])
    xs, ys = [], []
    for (x0, x1), (y0, y1) in zip(x.tolist(), y.tolist()):
        L = float(np.hypot(x1 - x0, y1 - y0))
        if L < 1e-9:
            continue
        t = -phase
        while t < L:
            for i in range(0, len(pat), 2):  # the dashes of one repeat
                a, b = max(t + edges[i], 0.0), min(t + edges[i + 1], L)
                if b > a:
                    xs.append((x0 + a / L * (x1 - x0), x0 + b / L * (x1 - x0)))
                    ys.append((y0 + a / L * (y1 - y0), y0 + b / L * (y1 - y0)))
            t += period
    return np.array(xs).reshape(-1, 2), np.array(ys).reshape(-1, 2)


def to_sheet(v, p):
    """Model point -> sheet feet through the viewport's view (origin, basis) and placement."""
    (bx, by, _bz), o = v.view_basis, v.view_origin
    d = (p[0] - o[0], p[1] - o[1], p[2] - o[2])
    vx = d[0] * bx[0] + d[1] * bx[1] + d[2] * bx[2]
    vy = d[0] * by[0] + d[1] * by[1] + d[2] * by[2]
    return v.offset[0] + v.scale * vx, v.offset[1] + v.scale * vy


def in_crop(v, p):
    (bx, by, _bz), o = v.view_basis, v.view_origin
    d = (p[0] - o[0], p[1] - o[1], p[2] - o[2])
    vx = d[0] * bx[0] + d[1] * bx[1] + d[2] * bx[2]
    vy = d[0] * by[0] + d[1] * by[1] + d[2] * by[2]
    x0, y0, x1, y1 = v.crop
    return x0 <= vx <= x1 and y0 <= vy <= y1


def arrow(shape, tip, tail, size=5.0):
    """A filled arrowhead at `tip` pointing away from `tail` (points)."""
    dx, dy = tip[0] - tail[0], tip[1] - tail[1]
    n = math.hypot(dx, dy) or 1
    ux, uy = dx / n, dy / n
    a = (tip[0] - size * ux + size * 0.35 * uy, tip[1] - size * uy - size * 0.35 * ux)
    b = (tip[0] - size * ux - size * 0.35 * uy, tip[1] - size * uy + size * 0.35 * ux)
    shape.draw_polyline([pdf.Point(*tip), pdf.Point(*a), pdf.Point(*b), pdf.Point(*tip)])


def draw_leader(page, v, points, arrowhead=True):
    """A leader through model points (first to last), arrow at the last."""
    H = page.rect.height
    pts = [(to_sheet(v, p)[0] * PT, H - to_sheet(v, p)[1] * PT) for p in points]
    shape = page.new_shape()
    shape.draw_polyline([pdf.Point(*p) for p in pts])
    shape.finish(color=(0, 0, 0), width=0.5, closePath=False)
    if arrowhead and len(pts) >= 2:
        arrow(shape, pts[-1], pts[-2])
        shape.finish(color=(0, 0, 0), fill=(0, 0, 0), width=0.5)
    shape.commit()
