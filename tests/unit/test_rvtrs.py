"""Unit tests for the rvt-rs revision diff (metrics/rvtrs.compare): elements matched by tag, an
element written in pieces merged into one, and each kind of change counted once by its class."""
from rvt_prt.metrics import rvtrs


def _el(tag, cls="IfcWall", lo=(0, 0, 0), hi=(1, 1, 1), volume=1.0, tris=12, family="", materials=""):
    return {"tag": tag, "cls": cls, "family": family, "materials": materials, "tris": tris,
            "lo": list(lo), "hi": list(hi), "volume": volume}


def test_pieces_merge():
    merged = rvtrs._by_tag([_el(1, hi=(1, 1, 1)), _el(1, lo=(2, 0, 0), hi=(3, 1, 1))])
    assert merged[1]["pieces"] == 2
    assert merged[1]["lo"] == [0, 0, 0] and merged[1]["hi"] == [3, 1, 1]
    assert merged[1]["volume"] == 2.0 and merged[1]["tris"] == 24


def test_kinds():
    old = {"elements": [_el(1), _el(2), _el(3), _el(4), _el(5), _el(6, materials="Concrete")]}
    new = {"elements": [_el(1),                              # unchanged
                        _el(3, cls="IfcColumn"),             # class changed (2 lost)
                        _el(4, hi=(1, 1, 2), volume=2.0),    # box moved
                        _el(5, volume=1.5),                  # volume only
                        _el(6, materials="Brick"),
                        _el(7, cls="IfcSlab")]}              # gained
    _a, _b, kinds, ex = rvtrs.compare(old, new, tol=1e-3)
    assert kinds == {("lost", "IfcWall"): 1, ("gained", "IfcSlab"): 1,
                     ("class", "IfcWall -> IfcColumn"): 1, ("box", "IfcWall"): 1,
                     ("volume", "IfcWall"): 1, ("materials", "IfcWall"): 1}
    assert ex["lost", "IfcWall"] == [2] and ex["gained", "IfcSlab"] == [7]


def test_box_within_tolerance():
    old = {"elements": [_el(1)]}
    new = {"elements": [_el(1, hi=(1, 1, 1.0005))]}
    assert not rvtrs.compare(old, new, tol=1e-3)[2]


def test_empty_mesh():
    empty = {"tag": 1, "cls": "IfcWall", "family": "", "materials": "", "tris": 0}
    _a, _b, kinds, _ex = rvtrs.compare({"elements": [_el(1)]}, {"elements": [empty]}, tol=1e-3)
    assert kinds == {("mesh emptied", "IfcWall"): 1}
