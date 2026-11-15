"""Unit tests for a title block's text as Revit prints it: label sizes from their text types,
lines of mixed style, text that reads up the sheet, and hyphens that read back as typed."""
import pytest

from rvt_prt import pdf
from rvt_prt.elements import titleblock
from rvt_prt.render.text import draw_text_block, put_text, tb_font


@pytest.mark.parametrize("nominal_pt, printed", [(6.75, 9.5), (9, 12.5), (13.5, 19), (18, 25), (27, 38), (45, 63)])
def test_a_label_prints_at_its_text_types_size_as_revit_prints_it(nominal_pt, printed):
    assert titleblock.printed_size(nominal_pt / 864) == printed  # Snowdon's and test02's title blocks


def test_a_label_reading_up_the_sheet_prints_larger():
    assert titleblock.printed_size(9 / 864, turned=True) == 13.5  # Snowdon's Date/Time Stamp
    assert titleblock.printed_size(6.75 / 864, turned=True) == 10.0  # test02's


def test_a_line_of_one_style_has_no_runs_and_a_mixed_one_has_each():
    lines, size = titleblock.rtf_lines(r"{\rtf1\pard\fs25\i All italic:\i0\par Planning\i :\i0\par\b  Bold\b0  words \b too\b0\par}")
    assert size == 12.5
    assert lines[0][:3] == ("All italic:", False, True) and lines[0][5] is None
    assert lines[1][0] == "Planning:" and lines[1][5] == [("Planning", False, False), (":", False, True)]
    assert [r[1:] for r in lines[2][5]] == [(True, False), (False, False), (True, False)]
    assert "".join(r[0] for r in lines[2][5]) == lines[2][0]


def _spans(doc):
    return [(s["text"].strip(), s["font"], round(s["size"], 1), tuple(round(d) for d in line["dir"]))
            for b in doc[0].get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"] if s["text"].strip()]


def test_a_block_is_drawn_in_its_runs_fonts_and_along_its_direction():
    doc = pdf.new_document()
    page = doc.new_page(width=400, height=300)
    draw_text_block(page, (100 / 864, 200 / 864), 0, 0x240, [("Planning:", False, False, 0, 0, [("Planning", False, False), (":", False, True)])], 12.5)
    draw_text_block(page, (300 / 864, 50 / 864), 0, 0x240, [("14/11/2026", False, False)], 13.5, base=(0.0, 1.0))
    spans = _spans(doc)
    assert [s[0] for s in spans[:2]] == ["Planning", ":"] and spans[0][1] != spans[1][1]
    assert spans[2][0] == "14/11/2026" and spans[2][2] == 13.5 and spans[2][3] == (0, -1)  # up the page


@pytest.mark.parametrize("family", ["Trebuchet MS", "Arial"])
def test_a_hyphen_reads_back_as_the_hyphen_typed(family):
    doc = pdf.new_document()
    page = doc.new_page(width=300, height=100)
    put_text(page, (20, 50), "7765328-33-M", fontname=tb_font(False, False, family), fontsize=12)
    back = pdf.open_document(pdf.finished_bytes(doc, []))
    assert back[0].get_text().strip() == "7765328-33-M"


def test_rtf_named_characters_and_line_breaks_are_read():
    from rvt_prt.elements import annotations
    rtf = r"{\rtf1\pard\fs19 Set to: \b Auto \f1\lang0\endash\f0\lang1033  Internal\b0  end\par One\line Two \ldblquote q\rdblquote\par}"
    lines, _ = titleblock.rtf_lines(rtf)
    assert [line[0] for line in lines] == ["Set to: Auto – Internal end", "One", "Two “q”"]
    assert lines[0][5][1] == ("Auto – Internal", True, False)
    assert annotations.rtf_to_text(rtf)[0] == "Set to: Auto – Internal end\nOne\nTwo “q”"


def test_runs_wrap_where_the_plain_line_wraps_each_keeping_its_font():
    from rvt_prt.render.text import wrap, wrap_runs
    regular, bold = ("Trebuchet MS", False, False), ("Trebuchet MS", True, False)
    runs = [("Ensure that Positioning is set to: ", regular), ("Auto – Internal Origin to Internal Origin", bold),
            (" and then click Open.", regular)]
    plain = "".join(t for t, _f in runs)
    for width in (120, 200, 300, 600):
        got = wrap_runs(runs, width, 9.5)
        assert ["".join(t for t, _f in line) for line in got] == wrap(plain, width, 9.5, regular)
    first = wrap_runs(runs, 300, 9.5)[0]
    assert first[0] == ("Ensure that Positioning is set to: ", regular) and first[1][1] == bold


def test_title_block_lines_are_spaced_by_their_text_types_size():
    from rvt_prt.render.text import TB_PITCH_NOMINAL
    doc = pdf.new_document()
    page = doc.new_page(width=600, height=400)
    lines = [("First", True, False), ("Second", False, False), ("Third", False, False)]
    draw_text_block(page, (50 / 864, 300 / 864), 0, 0x240, lines, 19.0, nominal=13.5)
    ys = [line["spans"][0]["origin"][1] for b in page.get_text("dict")["blocks"] for line in b.get("lines", [])]
    assert len(ys) == 3
    assert ys[1] - ys[0] == pytest.approx(TB_PITCH_NOMINAL * 13.5, abs=0.01)  # 23.8 pt, as Revit's M000
    assert ys[2] - ys[1] == pytest.approx(TB_PITCH_NOMINAL * 13.5, abs=0.01)
