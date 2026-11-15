"""Unit tests for stair run and zig-zag cut mark decoding."""
import numpy as np
import pytest


def test_stair_cut_mark_geometry():
    A = np.array([0.0, 0.0])
    B = np.array([4.0, 0.0])  # 4-ft wide tread
    W = B - A
    w_len = np.linalg.norm(W)
    assert w_len == pytest.approx(4.0)

    U = np.array([-W[1], W[0]]) / w_len
    p1 = A + 0.42 * W
    p2 = A + 0.46 * W + 0.35 * U
    p3 = A + 0.54 * W - 0.35 * U
    p4 = A + 0.58 * W

    # Verify continuity
    assert np.allclose(p1[:2], [1.68, 0.0])
    assert p2[1] > 0  # zig goes one side
    assert p3[1] < 0  # zag goes other side
    assert np.allclose(p4[:2], [2.32, 0.0])
