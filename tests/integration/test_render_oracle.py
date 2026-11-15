"""Integration tests verifying oracle recall and precision regression gates."""
import pathlib

import pytest

from rvt_prt import RevitModel, pdf
from rvt_prt.metrics import metrics

ORACLE_DIR = pathlib.Path("oracle/snowdon_hvac")
MODEL_PATH = pathlib.Path("oracle/Snowdon Towers Sample HVAC.rvt")
OUTPUT_PDF = pathlib.Path("out/test_regression.pdf")


@pytest.mark.skipif(not MODEL_PATH.exists() or not ORACLE_DIR.exists(), reason="Oracle models not present")
def test_render_schedule_oracle_gate():
    """Schedules M001 and M002 at >= 99.0% ink recall and precision, title block included (2026-10-14:
    M001 99.3 / 99.4, M002 99.1 / 99.2; the Date/Time Stamp prints the day's date, so a little headroom)."""
    model = RevitModel(MODEL_PATH)
    model.render_to_pdf(OUTPUT_PDF, sheet_numbers=["M001", "M002"], workers=2)

    doc_our = pdf.open_document(OUTPUT_PDF)
    for sheet_num, page_idx in [("M001", 0), ("M002", 1)]:
        ora_pdf = ORACLE_DIR / f"{sheet_num}.pdf"
        assert ora_pdf.exists()
        doc_ora = pdf.open_document(ora_pdf)
        recall, precision, _revit_px, _our_px = metrics.score(doc_ora[0], doc_our[page_idx], dpi=50, r=2, mode="ink")
        assert recall >= 0.990, f"{sheet_num} ink recall {recall:.1%} fell below 99.0% threshold"
        assert precision >= 0.990, f"{sheet_num} ink precision {precision:.1%} fell below 99.0% threshold"


TEST02 = pathlib.Path("oracle/test02/TestProject2.rvt")


@pytest.mark.skipif(not TEST02.exists(), reason="Oracle models not present")
def test_separate_files(tmp_path):
    """A directory output: each sheet to its own one-page PDF, "<number> - <name>.pdf"."""
    summary = RevitModel(TEST02).render_to_pdf(tmp_path / "sheets", workers=1)
    files = sorted((tmp_path / "sheets").glob("*.pdf"))
    assert [f.name for f in files] == ["A101 - Unnamed.pdf"]
    assert summary["files"] == [str(f) for f in files]
    assert len(pdf.open_document(files[0])) == 1
