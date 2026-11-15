"""The cache folder's listing and what clearing it would remove (core/cachedir.py)."""
from rvt_prt.core import cachedir


def _folder(tmp_path):
    (tmp_path / "cache" / "oracle").mkdir(parents=True)
    (tmp_path / "cache" / "oracle" / "M101.dxf.1.2.v7.pkl").write_bytes(b"x" * 10)
    (tmp_path / "cache" / "A Model.rvt.gelements.pkl").write_bytes(b"x" * 3)
    (tmp_path / "cache" / "A Model.rvt.saved_graphics.pkl.123.tmp").write_bytes(b"x")
    (tmp_path / "cache" / "B.RVT.views_read.pkl").write_bytes(b"x" * 2)
    (tmp_path / "links").mkdir()
    (tmp_path / "links" / "A Model.rvt.npz").write_bytes(b"x" * 5)
    (tmp_path / "fonts.json").write_text("{}")
    (tmp_path / "sheets").mkdir()  # printed sheets: never the cache's
    (tmp_path / "sheets" / "M101.pdf").write_bytes(b"%PDF")
    return tmp_path


def test_model_of():
    assert cachedir.model_of("Snowdon Towers Sample HVAC.rvt.gelements.pkl") == "Snowdon Towers Sample HVAC.rvt"
    assert cachedir.model_of("x.RVT.npz") == "x.RVT"
    assert cachedir.model_of("fonts.json") is None


def test_entries_group_by_model(tmp_path):
    groups = {p.name: g for p, g, _n in cachedir.entries(_folder(tmp_path))}
    assert groups == {"oracle": "(bench)", "A Model.rvt.gelements.pkl": "A Model.rvt",
                      "A Model.rvt.saved_graphics.pkl.123.tmp": "(unfinished)", "B.RVT.views_read.pkl": "B.RVT",
                      "A Model.rvt.npz": "A Model.rvt", "fonts.json": "(fonts)"}
    assert "M101.pdf" not in {p.name for p, _g, _n in cachedir.entries(tmp_path)}


def test_targets(tmp_path):
    root = _folder(tmp_path)
    names = lambda ps: sorted(p.name for p in ps)
    assert names(cachedir.targets(["/some/where/A Model.rvt"], root)) == ["A Model.rvt.gelements.pkl", "A Model.rvt.npz"]
    assert names(cachedir.targets(["b.rvt"], root)) == ["B.RVT.views_read.pkl"]
    assert names(cachedir.targets(["(bench)"], root)) == ["oracle"]
    every = cachedir.targets(None, root)
    assert len(every) == 6 and all("sheets" not in p.parts for p in every)
