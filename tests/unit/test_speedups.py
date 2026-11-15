"""Unit tests for what makes prints faster without changing them: pages joined (pdf.joined_bytes),
no trim where nothing was decoded (memory.forget), symbols decoded in helper processes
(savedgraphics._symbols)."""
import multiprocessing

import numpy as np
import pytest

from rvt_prt import pdf
from rvt_prt.core import memory
from rvt_prt.elements import savedgraphics


def _page(text):
    doc = pdf.new_document()
    doc.new_page(width=200, height=100).insert_text((20, 50), text, fontname="helv")
    return pdf.finished_bytes(doc, [])


def test_finished_pages_are_joined_in_order_with_their_bookmarks():
    joined = pdf.open_document(pdf.joined_bytes([_page("first"), _page("second")], [("A101", 1), ("A102", 2)]))
    assert [p.get_text().strip() for p in joined] == ["first", "second"]
    assert pdf.toc(joined) == {0: "A101", 1: "A102"}


def test_forget_trims_only_after_something_was_decoded(monkeypatch):
    trims = []
    monkeypatch.setattr(memory, "trim", lambda grown=0: trims.append(grown))
    monkeypatch.setattr(memory, "_DECODED", False)
    memory.forget("model.rvt")
    assert trims == []  # a warm print: nothing decoded, nothing to hand back
    memory.decoded()
    memory.forget("model.rvt")
    memory.forget("model.rvt")
    assert trims == [0]  # once, for what was decoded


class _Link:
    """A stand-in for savedgraphics.Link: each symbol one solid, its mesh named by the symbol."""
    bodies = {}

    def primitives(self, sym):
        if sym % 7 == 0:
            raise ValueError("does not decode")
        return [savedgraphics.Prim((), "solid", [], category=1, solid=(sym, 0, None))]

    def solid_mesh(self, prim):
        return np.full((3, 3), prim.solid[0], dtype=float), np.array([[0, 1, 2]])


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="no fork")
def test_symbols_decoded_in_helper_processes_are_those_decoded_here():
    link, syms = _Link(), list(range(1, 41))
    here = savedgraphics._symbols(link, syms, {}, 1)
    there = savedgraphics._symbols(link, syms, {}, 3)
    assert len(here) == len(there) == len(syms)
    for (ps, ms), (qs, ns) in zip(here, there):
        assert [p.solid[:2] for p in ps] == [q.solid[:2] for q in qs]
        assert list(ms) == list(ns)
        assert all(np.array_equal(ms[k][0], ns[k][0]) and ms[k][0].dtype == np.float32 for k in ms)
    assert here[6] == ([], {})  # symbol 7: what does not decode has no primitives


def test_kept_linework_reads_back_as_it_was_worked_out(tmp_path):
    from shapely.geometry import box

    from rvt_prt.geometry import linkgeom
    from rvt_prt.render import viewlines
    linkgeom._Owned.owner, linkgeom._Owned.style = (7, "Door", -2000023), 11
    cuts = linkgeom._Owned()
    cuts.append((np.array([0.0, 1.0]), np.array([2.0, 3.0])))
    linkgeom._Owned.owner, linkgeom._Owned.style = (8, "", -2000011), None
    cuts.extend(np.array([[[4.0, 5.0], [6.0, 7.0]]]))
    res = (cuts, linkgeom._Owned(), [("Concrete", box(0, 0, 1, 1))], {(1.0, 0.0, 0.0): cuts}, linkgeom._Owned())
    linkgeom._Owned.owner = linkgeom._Owned.style = None
    f = tmp_path / "view.pkl"
    viewlines.write(f, res)
    back = viewlines.read(f)
    assert isinstance(back[0], linkgeom._Owned) and np.array_equal(np.asarray(back[0]), np.asarray(cuts))
    assert back[0].owners == [(7, "Door", -2000023), (8, "", -2000011)] and back[0].styles == [11, None]
    assert len(back[1]) == 0 and back[1].owners == []
    assert back[2][0][0] == "Concrete" and back[2][0][1].equals(box(0, 0, 1, 1))
    assert list(back[3]) == [(1.0, 0.0, 0.0)] and len(back[3][(1.0, 0.0, 0.0)]) == 2
    assert viewlines.read(tmp_path / "absent.pkl") is None


def test_a_sheet_is_allowed_what_it_grew_by_last_time_or_a_heavy_sheets_share():
    from types import SimpleNamespace

    from rvt_prt.render import pool
    task = (0, SimpleNamespace(number="A101"), None, "pdf")
    assert pool._needs(task, {}) == pool.ROOMY
    assert pool._needs(task, {"A101": 100e6}) == pytest.approx(350e6)


def test_an_earlier_phase_is_meshed_where_elements_exist_only_before_the_last(monkeypatch):
    from rvt_prt.model import phases
    legends, existing, new = 10, 20, 30
    monkeypatch.setattr(phases, "project", lambda path: ([legends, existing, new], {}, {}))
    monkeypatch.setattr(phases, "elements", lambda path: {
        1: (existing, None),       # in the last phase: no extra export
        2: (existing, new),        # demolished in the last phase: exists in Existing
        3: (legends, legends),     # created and demolished in one phase: exists in none
        4: (new, None),
    })
    assert phases.earlier_phases("model.rvt") == [str(existing)]
    monkeypatch.setattr(phases, "elements", lambda path: {1: (existing, None), 3: (legends, legends)})
    assert phases.earlier_phases("model.rvt") == []
    monkeypatch.setattr(phases, "project", lambda path: ([new], {}, {}))
    assert phases.earlier_phases("model.rvt") == []


def test_a_plan_walks_only_the_elements_reaching_its_crop():
    from types import SimpleNamespace

    from rvt_prt.render import linework
    box = lambda x0, y0, x1, y1: SimpleNamespace(verts=np.array([[x0, y0, 0.0], [x1, y1, 3.0]]))
    items = [box(0, 0, 10, 10), box(100, 100, 110, 110), box(-30, 0, -21, 5), box(-7.5, 0, -6.5, 5)]
    # a view turned 90 degrees: its x along the model's y, its origin at (5, 5); crop 20 x 20
    v = SimpleNamespace(view_basis=((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), view_origin=(5.0, 5.0, 0.0),
                        crop=(-10.0, -10.0, 10.0, 10.0))
    kept = linework.in_crop(items, v)
    # in the crop; far away; 16 ft beyond its edge; 1.5 ft beyond it, within CROP_MARGIN
    assert kept == [items[0], items[3]]
    assert linework.in_crop(items[:1], v) is not None and linework.in_crop([], v) == []
