"""Unit tests for sheet parameters by name and the --where filters that select sheets by them."""
import pytest

from rvt_prt.model import sheetparams
from rvt_prt.model.layout import Sheet

DEFS = {101: ("Sheet Group", "ParamDefString"), 102: ("Sheet Sort", "ParamDefString"),
        103: ("For Tender", "ParamDefYesNo"), 104: ("Drawn By", "ParamDefString")}


def _sheet(number, name, scheduled=True, custom=None, **fields):
    return Sheet(number, name, {"number": number, **fields}, (3.5, 2.5), scheduled=scheduled, custom=custom or {})


def test_built_in_parameters_first_then_project_ones_by_name():
    s = _sheet("A101", "First Floor Plan", drawn_by="APF", issue_date="08/28/22",
               custom={102: "070", 101: "Architectural", 103: 1, 999: "no definition"})
    p = sheetparams.of(s, DEFS)
    assert list(p)[:4] == ["Sheet Number", "Sheet Name", "Appears In Sheet List", "Sheet Issue Date"]
    assert p["Sheet Number"] == "A101" and p["Appears In Sheet List"] == "Yes"
    assert p["Drawn By"] == "APF" and p["Checked By"] == ""
    assert list(p)[-3:] == ["For Tender", "Sheet Group", "Sheet Sort"]
    assert p["For Tender"] == "Yes" and p["Sheet Sort"] == "070"
    assert "no definition" not in p.values()


def test_a_project_parameter_does_not_take_a_built_in_name():
    p = sheetparams.of(_sheet("A1", "x", drawn_by="APF", custom={104: "someone else"}), DEFS)
    assert p["Drawn By"] == "APF"


@pytest.mark.parametrize("text, parsed", [
    ("Sheet Group=Architectural", ("Sheet Group", "=", "Architectural")),
    (" Sheet Group != General ", ("Sheet Group", "!=", "General")),
    ("Sheet Name~plan", ("Sheet Name", "~", "plan")),
    ("Drawn By=", ("Drawn By", "=", "")),
    ("Note=a=b", ("Note", "=", "a=b")),
])
def test_filters_parse(text, parsed):
    assert sheetparams.parse(text) == parsed


@pytest.mark.parametrize("text", ["Sheet Group", "=Architectural", ""])
def test_a_filter_without_a_name_and_operator_is_refused(text):
    with pytest.raises(ValueError, match="NAME=VALUE"):
        sheetparams.parse(text)


PARAMS = {"Sheet Number": "A101", "Sheet Name": "First Floor Plan", "Appears In Sheet List": "Yes",
          "Sheet Group": "Architectural", "Drawn By": ""}


@pytest.mark.parametrize("text, hit", [
    ("Sheet Group=Architectural", True),
    ("sheet group=ARCHITECTURAL", True),  # names and values in any case
    ("Sheet Group=Arch*", True),
    ("Sheet Group=Arch", False),  # = is the whole value
    ("Sheet Number=A10?", True),
    ("Sheet Group!=General", True),
    ("Sheet Group!=Arch*", False),
    ("Sheet Name~floor", True),
    ("Sheet Name~ceiling", False),
    ("Appears In Sheet List=yes", True),
    ("Appears In Sheet List=true", True),
    ("Appears In Sheet List=0", False),
    ("Drawn By=", True),  # no value is ""
    ("Sheet Sort=", True),  # a parameter the sheet does not have is ""
    ("Drawn By!=", False),
])
def test_filters_match(text, hit):
    assert sheetparams.matches(PARAMS, sheetparams.parse(text)) is hit


def _sheets():
    sheets = [_sheet("A101", "First Floor Plan", custom={101: "Architectural"}),
              _sheet("G101", "Life Safety Plan", custom={101: "General"}),
              _sheet("SD101", "First Floor Plan", scheduled=False)]
    return sheets, {s.number: sheetparams.of(s, DEFS) for s in sheets}


def test_every_filter_must_hold():
    sheets, params = _sheets()
    pick = sheetparams.select(sheets, params, ["Sheet Name~plan", "Appears In Sheet List=Yes"])
    assert [s.number for s in pick] == ["A101", "G101"]
    pick = sheetparams.select(sheets, params, ["Sheet Name~plan", "Sheet Group!=General", "Appears In Sheet List=Yes"])
    assert [s.number for s in pick] == ["A101"]
    assert sheetparams.select(sheets, params, []) == sheets


def test_a_misspelt_name_is_an_error_naming_the_parameters_there_are():
    sheets, params = _sheets()
    with pytest.raises(LookupError, match="'Sheet Grup'.*Sheet Group"):
        sheetparams.select(sheets, params, ["Sheet Grup=Architectural"])


def test_a_known_parameter_no_sheet_has_a_value_for_is_not_an_error():
    sheets, params = _sheets()
    pick = sheetparams.select(sheets, params, ["For Tender=Yes"], known=["For Tender"])
    assert pick == []
