"""linkgeom.prefetch: the caches written by forkserver workers (--geometry-jobs) are what meshes()
writes one by one. Skipped without the oracle files or the native extension."""
import pathlib

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS = [ROOT / "oracle" / "testfamily" / "TestProject.rvt", ROOT / "oracle" / "test02" / "TestProject2.rvt"]

pytest.importorskip("rvt_prt._native")


def _arrays(npz):
    with np.load(npz, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def test_prefetch_matches_serial(tmp_path, monkeypatch):
    from rvt_prt.geometry import linkgeom, links
    if not all(p.exists() for p in MODELS):
        pytest.skip("oracle/testfamily or oracle/test02 not present")
    sources = [links.Host(p) for p in MODELS]
    monkeypatch.setattr(linkgeom, "CACHE", tmp_path / "serial")
    serial = [linkgeom.meshes(s) for s in sources]
    monkeypatch.setattr(linkgeom, "CACHE", tmp_path / "jobs")
    linkgeom.prefetch(sources, 2)
    for p in MODELS:  # written by the workers, not yet by this process
        a, b = _arrays(tmp_path / "serial" / (p.name + ".npz")), _arrays(tmp_path / "jobs" / (p.name + ".npz"))
        assert a.keys() == b.keys()
        for k in a:
            assert np.array_equal(a[k], b[k]), (p.name, k)
    assert [len(linkgeom.meshes(s)) for s in sources] == [len(m) for m in serial]
