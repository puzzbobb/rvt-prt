"""Unit tests for linkgeom.prefetch: each stale source's task run in a worker process of its own,
largest first; a source already current is left alone; one whose task fails is not reported done
(what reads its caches builds them instead), and the others are."""
import multiprocessing
import pathlib
from types import SimpleNamespace

import pytest

from rvt_prt.geometry import linkgeom

pytestmark = pytest.mark.skipif(not ({"forkserver", "spawn"} & set(multiprocessing.get_all_start_methods())),
                                reason="needs forkserver or spawn")


def _task(source):
    """A worker's task: a marker beside the source, or a failure for one named "bad"."""
    if source.file_name.startswith("bad"):
        raise ValueError("cannot read it")
    pathlib.Path(str(source.path) + ".built").write_text(source.file_name)


def test_prefetch(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(linkgeom, "CACHE", tmp_path / "links")
    sources = []
    for name, size in (("small.rvt", 10), ("large.rvt", 300), ("bad.rvt", 20), ("current.rvt", 50)):
        (tmp_path / name).write_bytes(b"\0" * size)
        sources.append(SimpleNamespace(path=tmp_path / name, file_name=name))
    told = []
    done = linkgeom.prefetch(sources, 2, _task, current=lambda s: s.file_name == "current.rvt",
                             need=lambda source: (1e6, 2e9), on_done=lambda s: told.append(s.file_name))
    assert sorted(s.file_name for s in done) == ["large.rvt", "small.rvt"]
    assert sorted(told) == ["bad.rvt", "current.rvt", "large.rvt", "small.rvt"]  # each once: built, current, failed
    assert (tmp_path / "large.rvt.built").read_text() == "large.rvt"
    assert not (tmp_path / "current.rvt.built").exists()  # current: not built again
    assert "bad.rvt failed in a worker (ValueError: cannot read it); computing it here instead" in capsys.readouterr().err


def test_prefetch_one_job_does_nothing(tmp_path, monkeypatch):
    """One job: nothing in workers; the caches are built where they are read, as before."""
    monkeypatch.setattr(linkgeom, "CACHE", tmp_path / "links")
    sources = [SimpleNamespace(path=tmp_path / n, file_name=n) for n in ("a.rvt", "b.rvt")]
    for s in sources:
        s.path.write_bytes(b"\0")
    assert linkgeom.prefetch(sources, 1, _task, current=lambda s: False) == []
    assert not list(tmp_path.glob("*.built"))


def _log_start(source):
    """A worker's task: its name appended to a log beside the sources when it starts, then a pause."""
    import time
    with open(source.path.parent / "started.log", "a") as f:
        f.write(source.file_name + "\n")
    time.sleep(1.0)


def test_prefetch_largest_that_fits(tmp_path, monkeypatch):
    """When the largest waiting source does not fit beside those running, a smaller one that does
    starts in its place."""
    monkeypatch.setattr(linkgeom, "CACHE", tmp_path / "links")
    monkeypatch.setattr(linkgeom, "_available", lambda: 6e9)
    monkeypatch.setattr(linkgeom, "reserve", lambda: 1.5e9)
    sources = []
    for name, size in (("large.rvt", 300), ("mid.rvt", 200), ("small.rvt", 100)):
        (tmp_path / name).write_bytes(b"\0" * size)
        sources.append(SimpleNamespace(path=tmp_path / name, file_name=name))
    need = {"large.rvt": 3e9, "mid.rvt": 3e9, "small.rvt": 1e9}  # 4.5 GB to spend: large and small, then mid
    done = linkgeom.prefetch(sources, 3, _log_start, current=lambda s: False,
                             need=lambda s: (need[s.file_name], 2e9))
    assert len(done) == 3
    started = (tmp_path / "started.log").read_text().split()
    assert set(started[:2]) == {"large.rvt", "small.rvt"} and started[2] == "mid.rvt"  # the first two at once
