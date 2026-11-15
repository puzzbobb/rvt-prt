"""A file that cannot be printed stops the command with one line on stderr and exit status 1,
never a traceback: a missing file, one that is not a compound file, a compound file cut short,
and a compound file that is not Revit's."""
import olefile
import pytest

import rvt_prt
from rvt_prt import cli


def _not_ole(tmp_path):
    f = tmp_path / "text.rvt"
    f.write_text("not a Revit file")
    return f


def _cut_short(tmp_path):
    f = tmp_path / "cut.rvt"
    f.write_bytes(olefile.MAGIC + bytes(700))  # the compound file signature, then nothing usable
    return f


@pytest.mark.parametrize("command", [["list"], ["print", "-q"]])
@pytest.mark.parametrize("make, says", [
    (lambda tmp: tmp / "missing.rvt", "no such file"),
    (_not_ole, "is not a Revit file"),
    (_cut_short, "text.rvt|cut.rvt"),
])
def test_bad_model_is_one_line(tmp_path, capsys, command, make, says):
    model = make(tmp_path)
    status = cli.main([*command, str(model), *(["-o", str(tmp_path / "out")] if command[0] == "print" else [])])
    err = capsys.readouterr().err.strip()
    assert status == 1
    assert err.startswith("rvt-prt: ") and len(err.splitlines()) == 1
    assert any(part in err for part in says.split("|"))


def test_compare_missing_file(tmp_path, capsys):
    assert cli.main(["compare", str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")]) == 1
    assert "no such file" in capsys.readouterr().err


def test_api_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        rvt_prt.RevitModel(tmp_path / "missing.rvt")
    with pytest.raises(rvt_prt.UnsupportedFile):
        rvt_prt.RevitModel(_not_ole(tmp_path))


def test_version(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"rvt-prt {rvt_prt.__version__}"
