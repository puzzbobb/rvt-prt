"""Unit tests for the render pool's fallbacks: a sheet short of memory in its worker is tried
again with fewer at once, down to alone, then without its sections' model linework, then left
blank, never drawn in the parent."""
import multiprocessing
import os
from types import SimpleNamespace

import pytest

from rvt_prt import pdf
from rvt_prt.render import pool, state

pytestmark = pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="needs fork")


def _fake_worker(task):
    idx, s, _tb, _fmt = task
    assert os.getpid() != PARENT, "a sheet drawn in the parent"
    if s.number == "heavy" and not state.NO_SECTION_LINES:
        raise MemoryError("too big")
    if s.number == "hopeless":
        raise MemoryError("too big")
    return idx, f"{s.number}{' light' if state.NO_SECTION_LINES else ''}"


PARENT = os.getpid()


def test_fallbacks(monkeypatch, capsys):
    monkeypatch.setattr(pool, "_render_worker", _fake_worker)
    sheets = [SimpleNamespace(number=n, size=(1.0, 0.5)) for n in ("plain", "heavy", "hopeless")]
    out = dict(pool._parallel([(i, s, None, "pdf") for i, s in enumerate(sheets)], 2))
    assert out[0] == "plain"
    assert out[1] == "heavy light"
    page = pdf.open_document(out[2])[0]
    assert "too large to draw" in page.get_text()
    assert page.rect.width == pytest.approx(864)  # 1 ft
    err = capsys.readouterr().err
    assert "sheet heavy failed in a render worker (MemoryError: too big); trying it again on its own" in err
    assert "sheet heavy failed in a render worker (MemoryError: too big); drawing it without its section" in err
    assert "sheet hopeless failed in a render worker (MemoryError: too big); leaving its page blank" in err


def test_sheet_file():
    """A sheet's own file: "<number> - <name>.<ext>", characters a file name cannot hold replaced."""
    sheet = SimpleNamespace
    assert pool.sheet_file(sheet(number="M101", name="Level 1 Plan"), "pdf") == "M101 - Level 1 Plan.pdf"
    assert pool.sheet_file(sheet(number="A-1/2", name='Roof: "North"'), "dwfx") == "A-1_2 - Roof_ _North_.dwfx"
    assert pool.sheet_file(sheet(number="S001", name=""), "pdf") == "S001.pdf"
    assert pool.sheet_file(sheet(number="1", name="平面図"), "pdf") == "1 - 平面図.pdf"


def test_order_by_last_times(monkeypatch, tmp_path):
    """Sheets drawn heaviest first by their last draw times (kept per model); one never drawn goes
    first, by its viewports' scales."""
    from rvt_prt.core import paths
    monkeypatch.setattr(paths, "CACHE", tmp_path)
    vp = lambda scale: SimpleNamespace(scale=scale)
    sheets = {"light": [vp(200)], "slow": [vp(48)], "new": [vp(96)], "newer": [vp(24), vp(24), vp(96)], "cover": []}
    tasks = [(i, SimpleNamespace(number=n, viewports=v), None, "pdf") for i, (n, v) in enumerate(sheets.items())]
    assert pool.sheet_seconds(tmp_path / "Model.rvt") == {}
    pool._keep_seconds(tmp_path / "Model.rvt", {"light": 1.5, "slow": 14.0})
    pool._keep_seconds(tmp_path / "Model.rvt", {"cover": 0.4})  # merged with the times kept
    took = pool.sheet_seconds(tmp_path / "Model.rvt")
    assert took == {"light": 1.5, "slow": 14.0, "cover": 0.4}
    assert [t[1].number for t in pool._order(tasks, took)] == ["newer", "new", "slow", "light", "cover"]
