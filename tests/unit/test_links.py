"""Unit tests for link lookup: a linked file not found is left out with a warning."""
from types import SimpleNamespace

from rvt_prt import api
from rvt_prt.geometry import links


def test_missing_link_warns(monkeypatch, tmp_path, capsys):
    (tmp_path / "Found.rvt").write_bytes(b"")
    monkeypatch.setattr(links, "LINK_DIR", None)
    monkeypatch.delenv("RVT_PRT_LINKS", raising=False)
    found = links.Link(1, 10, "Arch", "Found.rvt", folder=tmp_path)
    gone = [links.Link(2, 20, "East", "Gone.rvt", folder=tmp_path), links.Link(3, 20, "West", "Gone.rvt", folder=tmp_path)]
    monkeypatch.setattr(links, "read", lambda rf, path: [found, *gone])
    assert api.RevitModel._links(SimpleNamespace(rf=None, path="model.rvt")) == [found]
    err = capsys.readouterr().err
    assert err.count("warning") == 1  # once per file, not per instance
    assert "Gone.rvt not found (link instances 'East', 'West')" in err
    assert str(tmp_path / "links") in err
