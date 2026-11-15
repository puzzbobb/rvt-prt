"""Unit tests for coordinate transforms."""

import numpy as np


def test_instance_rotation():
    # 90-degree counter-clockwise rotation matrix about Z
    theta = np.pi / 2
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    rot = np.array([
        [cos_t, -sin_t, 0.0, 10.0],
        [sin_t,  cos_t, 0.0, 20.0],
        [0.0,    0.0,   1.0,  0.0],
        [0.0,    0.0,   0.0,  1.0],
    ])
    pt = np.array([1.0, 0.0, 0.0, 1.0])
    res = rot @ pt
    assert np.allclose(res[:3], [10.0, 21.0, 0.0])
