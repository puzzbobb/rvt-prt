"""Unit tests for the drawing exchange formats: XPS path data, DWFx and DXF round trips, clipping
and line-by-line comparison."""
import math

import pytest

from rvt_prt.formats import drawing, dwfx
from rvt_prt.formats.drawing import Block, Drawing, Insert, Prim


def _points(expected, abs):
    """pytest.approx for a list of points (pytest 9 refuses nested structures)."""
    return [pytest.approx(p, abs=abs) for p in expected]


def test_xps_abbreviated_path_data():
    paths, closed = dwfx.parse_data("M 0,0 L 10,0 10,10 Z M 20,0 h 5 v 5")
    assert closed
    assert paths[0] == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 0.0)]
    assert paths[1] == [(20.0, 0.0), (25.0, 0.0), (25.0, 5.0)]


def test_xps_relative_moves_as_revit_writes_them():
    # Revit's DWFx: tick marks as relative moves and horizontal lines
    paths, _ = dwfx.parse_data("M100,200h5m-5,10h5")
    assert paths == [[(100.0, 200.0), (105.0, 200.0)], [(100.0, 210.0), (105.0, 210.0)]]


def test_xps_arc_segment_ends_on_its_point():
    paths, _ = dwfx.parse_data("M 10,0 A 10,10 0 0 1 0,10")
    pts = paths[0]
    assert pts[-1] == (0.0, 10.0)
    assert all(abs(math.hypot(x, y) - 10) < 1e-6 for x, y in pts)


def _sheet():
    d = Drawing("M101", "in", (42.0, 30.0))
    d.prims = [
        Prim([[(1, 1), (5, 1), (5, 4)]], "Walls cut", "E619340", (0.67, 0.67, 0.67), 0.86),
        Prim([[(10, 10), (12, 10)]], "", "", (0, 0, 0), 0.24),
    ]
    d.meta = {"E619340": {"element": 619340, "family": "", "category": "Walls"}}
    return d


def test_dwfx_round_trip_keeps_geometry_groups_and_layers(tmp_path):
    out = tmp_path / "s.dwfx"
    dwfx.write([_sheet()], out)
    [d] = dwfx.read(out)
    assert d.name == "M101"
    assert d.size == pytest.approx((42.0, 30.0))
    wall = next(p for p in d.prims if p.group == "E619340")
    assert wall.layer == "Walls cut"
    assert [tuple(p) for p in wall.paths[0]] == _points([(1, 1), (5, 1), (5, 4)], abs=0.01)
    assert wall.width == pytest.approx(0.86, abs=0.01)
    assert d.meta["E619340"]["category"] == "Walls"


def test_dxf_round_trip_keeps_blocks_inserts_and_groups(tmp_path):
    pytest.importorskip("ezdxf")
    from rvt_prt.formats import dxf
    d = Drawing("L1", "ft")
    d.blocks["Door"] = Block("Door", [Prim([[(0, 0), (3, 0)]], "0", "", None, 0.0, arc=None),
                                      Prim([[(0, 0)]], "0", "", None, 0.0, arc=(0.0, 0.0, 3.0, 0.0, math.pi / 2))], "Door")
    d.blocks["Door"].prims[1].paths = [drawing.arc_points(0, 0, 3, 0, math.pi / 2)]
    # a door turned a quarter and mirrored, at (10, 20)
    d.inserts.append(Insert("Door", (0.0, 1.0, 1.0, 0.0, 10.0, 20.0), "E631497", "Doors"))
    d.prims.append(Prim([[(0, 0), (4, 0)]], "Walls", "E619340", None, 0.0))
    d.meta = {"E631497": {"element": 631497}, "E619340": {"element": 619340}}
    out = tmp_path / "v.dxf"
    dxf.write(d, out)
    r = dxf.read(out)
    assert r.units == "ft" and "Door" in r.blocks
    [ins] = r.inserts
    assert ins.group == "E631497"
    assert ins.matrix == pytest.approx((0.0, 1.0, 1.0, 0.0, 10.0, 20.0), abs=1e-9)
    assert any(p.group == "E619340" for p in r.prims)
    placed = [p for p in r.flat() if p.group == "E631497"]
    line = next(p for p in placed if p.arc is None)
    assert [tuple(p) for p in line.paths[0]] == _points([(10, 20), (10, 23)], abs=1e-9)


def test_clip_cuts_segments_at_the_rectangle():
    p = Prim([[(-1, 1), (3, 1)], [(5, 5), (6, 6)]], "x", "g", (0, 0, 0), 1.0)
    q = drawing.clip(p, (0, 0, 2, 2))
    assert q.paths == [[(0.0, 1.0), (2.0, 1.0)]]
    assert drawing.clip(Prim([[(5, 5), (6, 6)]]), (0, 0, 2, 2)) is None


def test_compare_identical_and_shifted():
    a = _sheet()
    s = drawing.compare(a, a)
    assert s.recall == 1.0 and s.precision == 1.0
    b = _sheet()
    for p in b.prims:
        p.paths = [[(x + 1.0, y) for x, y in path] for path in p.paths]
    s = drawing.compare(a, b)
    assert s.recall < 0.5 and s.precision < 0.5


def test_compare_blocks_matches_instances_by_element():
    ref, ours = Drawing("r", "ft"), Drawing("o", "ft")
    ref.blocks["Door - 36_ x 84_-2162734-L1"] = Block("Door - 36_ x 84_-2162734-L1", [Prim([[(0, 0), (3, 0)]])], "Door")
    ref.blocks["Door - 30_ x 84_-1-L1"] = Block("Door - 30_ x 84_-1-L1", [Prim([[(0, 0), (2.5, 0)]])], "Door")
    ref.meta["E631497"] = {"block": "Door - 36_ x 84_-2162734-L1"}
    ours.blocks["Door"] = Block("Door", [Prim([[(0, 0), (3, 0)]])], "Door")
    ours.inserts.append(Insert("Door", (1, 0, 0, 1, 0, 0), "E631497"))
    [(name, rname, rc, pr, n)] = drawing.compare_blocks(ref, ours)
    assert (name, rname, n) == ("Door", "Door - 36_ x 84_-2162734-L1", 1)
    assert rc == 1.0 and pr == 1.0


def test_pair_by_name_or_contained_name():
    refs = [Drawing("Snowdon - Floor Plan - L1 - Block 35", "ft"), Drawing("M101", "in")]
    ours = [Drawing("M101", "in"), Drawing("L1 - Block 35", "ft")]
    pairs = drawing.pair(refs, ours)
    assert {(r.name, o.name) for r, o in pairs} == {("M101", "M101"), ("Snowdon - Floor Plan - L1 - Block 35", "L1 - Block 35")}


def test_inverse_undoes_an_affine():
    m = (0.0, 0.125, -0.125, 0.0, 3.0, 4.0)  # a quarter turn at 1/8" scale
    i = drawing.compose(drawing.inverse(m), m)
    assert all(abs(a - b) < 1e-12 for a, b in zip(i, (1, 0, 0, 1, 0, 0)))


def _swing():
    # a door-like symbol, not symmetric: leaf along +y at x = 0, swing to +x
    return Block("Door - 36", [Prim([[(0, 0), (0, 3)], [(0, 3), (3, 0)]])], "Door")


def test_compare_instances_pairs_by_placement_and_sees_a_mirror():
    view = Drawing("L1", "ft", blocks={"Door": _swing()})
    view.placement = (0.125, 0.0, 0.0, 0.125, 1.0, 1.0)  # model feet -> sheet inches, 1/8" = 1'
    view.inserts = [Insert("Door", (1, 0, 0, 1, 8, 8), "E1"), Insert("Door", (1, 0, 0, 1, 40, 8), "E2")]
    ref = Drawing("M101", "in", (42.0, 30.0), blocks={"Door - 36_-9-L1": Block("Door - 36_-9-L1", _swing().prims)})
    ref.placed = [Insert("Door - 36_-9-L1", (0.125, 0, 0, 0.125, 2.0, 2.0)),  # E1, as ours
                  Insert("Door - 36_-9-L1", (-0.125, 0, 0, 0.125, 6.0, 2.0)),  # E2, mirrored in x
                  Insert("Door - 36_-9-L1", (0.125, 0, 0, 0.125, 20.0, 20.0))]  # one we do not draw
    ref.meta = {"E9": {"family": "Door", "block": "Door - 36_-9-L1"}}
    rows = {r["group"]: r for r in drawing.compare_instances(ref, view)}
    assert rows["E1"]["ref_hit"] == rows["E1"]["ref_n"] > 0
    assert rows["E2"]["reference"] and rows["E2"]["ref_hit"] < rows["E2"]["ref_n"] / 2
    missed = [r for r in rows.values() if r["ours"] is None]
    assert len(missed) == 1 and missed[0]["family"] == "Door"
