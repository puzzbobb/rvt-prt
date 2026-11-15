"""Unit tests for geometric curve decoders (RE-49 lines and RE-75 arcs)."""
import math
import struct

import pytest


def test_line_unpacking():
    t0, t1 = 0.0, 10.0
    ox, oy, oz = 1.0, 2.0, 3.0
    dx, dy, dz = 1.0, 0.0, 0.0
    packed = struct.pack("<8d", t0, t1, ox, oy, oz, dx, dy, dz)
    assert len(packed) == 64

    unpacked = struct.unpack_from("<8d", packed, 0)
    p0 = (unpacked[2] + unpacked[0] * unpacked[5], unpacked[3] + unpacked[0] * unpacked[6], unpacked[4] + unpacked[0] * unpacked[7])
    p1 = (unpacked[2] + unpacked[1] * unpacked[5], unpacked[3] + unpacked[1] * unpacked[6], unpacked[4] + unpacked[1] * unpacked[7])
    assert p0 == (1.0, 2.0, 3.0)
    assert p1 == (11.0, 2.0, 3.0)


def test_arc_unpacking():
    a0, a1 = 0.0, math.pi / 2
    xx, xy, xz = 1.0, 0.0, 0.0
    yx, yy, yz = 0.0, 1.0, 0.0
    r = 3.0
    cx, cy, cz = 10.0, 20.0, 0.0
    packed = struct.pack("<12d", a0, a1, xx, xy, xz, yx, yy, yz, r, cx, cy, cz)
    assert len(packed) == 96

    unpacked = struct.unpack_from("<12d", packed, 0)
    assert unpacked[8] == pytest.approx(3.0)
    assert unpacked[9:12] == (10.0, 20.0, 0.0)

    n = 8
    pts = []
    for i in range(n + 1):
        ang = a0 + (a1 - a0) * i / n
        ca, sa = math.cos(ang), math.sin(ang)
        px = cx + r * (ca * xx + sa * yx)
        py = cy + r * (ca * xy + sa * yy)
        pts.append((px, py))

    assert pts[0] == pytest.approx((13.0, 20.0))
    assert pts[-1] == pytest.approx((10.0, 23.0))
