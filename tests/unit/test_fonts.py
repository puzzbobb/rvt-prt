"""Unit tests for font choice: a fallback font for glyphs the named font lacks."""
import pytest

from rvt_prt.model import fonts


def test_ascii_keeps_its_font():
    assert fonts.covering("helv", "Level 1") == ("Arial", False, False)
    assert fonts.covering(("Trebuchet MS", True, False), "M101") == ("Trebuchet MS", True, False)


@pytest.mark.skipif(("noto sans cjk jp", False, False) not in fonts.registry(), reason="no Noto Sans CJK JP in fonts/")
def test_japanese_falls_back_to_noto():
    # a note of 2019/サンプル構造.rvt names Meiryo UI, which fonts/ does not hold
    assert fonts.covering(("Meiryo UI", False, False), "・スラブ  S") == ("Noto Sans CJK JP", False, False)
    assert fonts.text_length("スラブ", ("Meiryo UI", False, False), 10) == pytest.approx(30.0)


@pytest.fixture
def no_font_files(monkeypatch, tmp_path):
    """A fresh machine: no font files anywhere, the cache folder empty."""
    from rvt_prt.core import paths
    monkeypatch.setattr(paths, "CACHE", tmp_path)
    monkeypatch.setattr(fonts, "font_dirs", lambda: [])
    for f in (fonts.registry, fonts.file_for, fonts.font_object, fonts._builtin_file):
        f.cache_clear()
    yield
    for f in (fonts.registry, fonts.file_for, fonts.font_object, fonts._builtin_file):
        f.cache_clear()


def test_without_font_files(no_font_files):
    # Arial and its free substitutes missing: PyMuPDF's built-in Helvetica, Arial's metrics
    assert fonts.file_for(("Arial", False, False)) is None
    assert fonts.font_object(("Arial", True, False)).name == "Helvetica-Bold"
    # Japanese: PyMuPDF's built-in CJK font, written out as a file for DWFx
    assert fonts.covering(("Meiryo UI", False, False), "建築図") == (fonts.BUILTIN_CJK, False, False)
    assert fonts.file_for((fonts.BUILTIN_CJK, False, False)).endswith("cjk.ttf")
    assert fonts.text_length("スラブ", ("Meiryo UI", False, False), 10) > 0


def test_user_cache_folder(monkeypatch, tmp_path):
    from rvt_prt.core import paths
    if paths.sys.platform in ("win32", "darwin"):
        pytest.skip("XDG on Linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert paths._user_cache() == tmp_path / "rvt-prt"
