"""Saved graphics' hidden lines: a symbol's lines behind its own solid, the uncovered parts of
many segments at once against one at a time, and selections kept between prints."""
import numpy as np
import pytest

from rvt_prt.core import paths
from rvt_prt.elements import savedgraphics as sg


class _Prim:
    def __init__(self, kind, points):
        self.kind, self.points, self.conds, self.category = kind, points, (), None


def _symbol():
    """A 2 x 2 x 1 box (primitive 0, its top outline as its lines) over a line at z 0 from x -1 to
    3 through its middle, and a line beside it."""
    top = np.array([[0, 0, 1], [2, 0, 1], [2, 2, 1], [0, 2, 1], [0, 0, 1]], float)
    under = np.array([[-1, 1, 0], [3, 1, 0]], float)
    beside = np.array([[-1, 5, 0], [3, 5, 0]], float)
    verts = np.array([[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0], [0, 0, 1], [2, 0, 1], [2, 2, 1], [0, 2, 1]], np.float32)
    faces = np.array([[4, 5, 6], [4, 6, 7], [0, 2, 1], [0, 3, 2]], np.int32)
    prims = {1: [_Prim("solid", [top]), _Prim("curve", [under]), _Prim("curve", [beside])]}
    return prims, {(1, 0): (verts, faces)}


def _saved(tmp_path, monkeypatch):
    model = tmp_path / "model.rvt"
    if not model.exists():  # written once: a file written again is a changed file
        model.write_bytes(b"x")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    prims, meshes = _symbol()
    return sg.Saved(model, {}, prims, meshes)


DOWN = (np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0]))


def test_a_solid_hides_the_line_under_it(tmp_path, monkeypatch):
    saved = _saved(tmp_path, monkeypatch)
    sel = saved._selected(1, *DOWN)
    box, under, beside = (c[2] for c in sel)
    assert len(box) == 4  # its own edges stay
    assert np.allclose(sorted(under[:, :, 0].ravel()), [-1, 0, 2, 3], atol=1e-3)  # the part under it is gone
    assert beside is saved._compiled(1)[2][2]  # untouched: the primitive's own segments


def test_uncovered_parts_as_one_by_one():
    rng = np.random.default_rng(7)
    seg = np.sort(rng.integers(0, 40, 300))
    a = rng.random(300)
    spans = np.stack([a, np.minimum(a + rng.random(300) * 0.3, 1.0)], axis=1)
    spans = spans[spans[:, 1] > spans[:, 0]]
    seg = seg[:len(spans)]
    lengths = rng.random(40) * 5 + 0.01
    of, t0, t1 = sg._uncovered_parts(seg, spans, lengths)
    want = [(j, s0, s1) for j in range(40) if (seg == j).any()
            for s0, s1 in sg._uncovered(spans[seg == j], 1e-3 / lengths[j]) if (s1 - s0) * lengths[j] > 1e-3]
    assert list(zip(of.tolist(), t0.tolist(), t1.tolist())) == want


def test_selections_are_kept_for_the_next_print(tmp_path, monkeypatch):
    first = _saved(tmp_path, monkeypatch)
    worked_out = first._selected(1, *DOWN)
    first.write_selections()
    again = _saved(tmp_path, monkeypatch)
    again.read_selections()
    monkeypatch.setattr(again, "_unhidden", lambda *a, **k: pytest.fail("worked out again"))
    kept = again._selected(1, *DOWN)
    assert [c[3] for c in kept] == [c[3] for c in worked_out]
    assert all(np.array_equal(x[2], y[2]) for x, y in zip(kept, worked_out))
    assert kept[2][2] is again._compiled(1)[2][2]


def test_selections_of_a_changed_file_are_not_used(tmp_path, monkeypatch):
    first = _saved(tmp_path, monkeypatch)
    first._selected(1, *DOWN)
    first.write_selections()
    (tmp_path / "model.rvt").write_bytes(b"changed")
    again = _saved(tmp_path, monkeypatch)
    again.read_selections()
    assert not again._kept
