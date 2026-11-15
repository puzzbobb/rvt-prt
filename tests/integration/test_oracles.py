"""The test oracles as the regression gate: each standalone model printed and scored against Revit's
own exports of its sheet (oracle/<name>/A101.dxf, A101.pdf). Floors are the scores at the time
they were set, rounded down to 0.1 points: raise them when a change improves a score, never lower
them to pass. Skipped without the oracle files or the native extension (rvt_prt._native)."""
import importlib.util
import pathlib

import pytest

from rvt_prt import RevitModel, pdf
from rvt_prt.formats import drawing
from rvt_prt.metrics import metrics

ROOT = pathlib.Path(__file__).resolve().parents[2]

# (folder, model, DXF line recall, precision, text recall or None, PDF ink recall, precision or None)
ORACLES = [
    ("testfamily", "TestProject.rvt", 0.999, 0.999, None, None),
    # testfamily's PDF is not gated: its page is the sheet's extents, whose margin is not decoded
    # (plan 2.6, page extents), so the two prints do not overlay
    ("test02", "TestProject2.rvt", 0.986, 0.994, 0.90, (0.992, 0.929)),
]


pytestmark = [pytest.mark.oracle,
              pytest.mark.skipif(importlib.util.find_spec("rvt_prt._native") is None,
                                 reason="native extension not built (pip install -e .)")]


@pytest.fixture(scope="module", params=ORACLES, ids=[o[0] for o in ORACLES])
def printed(request, tmp_path_factory):
    name, model, *gates = request.param
    folder = ROOT / "oracle" / name
    if not (folder / model).exists() or not (folder / "A101.dxf").exists():
        pytest.skip(f"oracle/{name} not present")
    out = tmp_path_factory.mktemp(name)
    RevitModel(folder / model).render_to_dwfx(out / "sheets.dwfx")
    RevitModel(folder / model).render_to_pdf(out / "sheets.pdf")
    return folder, out, gates


def test_lines_against_revit_dxf(printed):
    folder, out, (recall, precision, text, _ink) = printed
    pairs = drawing.pair(drawing.read(folder / "A101.dxf"), drawing.read(out / "sheets.dwfx"))
    assert len(pairs) == 1, f"expected one sheet pair, got {[(r.name, o.name) for r, o in pairs]}"
    s = drawing.compare(*pairs[0])
    assert s.recall >= recall, f"line recall {s.recall:.2%} below {recall:.1%}"
    assert s.precision >= precision, f"line precision {s.precision:.2%} below {precision:.1%}"
    if text is not None:
        assert s.text_recall >= text, f"text recall {s.text_recall:.1%} below {text:.0%}"


def test_pdf_against_revit_pdf(printed):
    folder, out, (*_lines, ink) = printed
    if ink is None:
        pytest.skip("PDF not gated for this oracle")
    revit, ours = pdf.open_document(folder / "A101.pdf")[0], pdf.open_document(out / "sheets.pdf")[0]
    assert abs(revit.rect.width - ours.rect.width) < 0.01 and abs(revit.rect.height - ours.rect.height) < 0.01, \
        f"page {ours.rect} differs from Revit's {revit.rect}"
    recall, precision, _r, _o = metrics.score(revit, ours, dpi=50, r=2, mode="ink")
    assert recall >= ink[0], f"ink recall {recall:.2%} below {ink[0]:.1%}"
    assert precision >= ink[1], f"ink precision {precision:.2%} below {ink[1]:.1%}"
