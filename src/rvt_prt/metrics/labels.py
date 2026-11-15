"""How the benches name a model: never by its file name. Autodesk's public samples and the test
oracles by what they are ("Snowdon HVAC", "Autodesk architecture sample (basic)", "test02"),
any other file by a short id from its name ("model 3f9a1c"), the same on every run."""
import hashlib
import pathlib
import re

_SNOWDON = re.compile(r"Snowdon Towers Sample (\w+)\.rvt$")
_AUTODESK = re.compile(r"(rac|rst|rme)_(basic|advanced)_sample_project\.rvt$")
_DISCIPLINE = {"rac": "architecture", "rst": "structure", "rme": "MEP"}
_ORACLES = {"TestProject.rvt": "testfamily", "TestProject2.rvt": "test02"}


def label(path):
    """The bench's name for the model at `path` (a path or a file name)."""
    name = pathlib.PurePath(str(path)).name
    if m := _SNOWDON.match(name):
        return f"Snowdon {m[1]}"
    if m := _AUTODESK.match(name):
        return f"Autodesk {_DISCIPLINE[m[1]]} sample ({m[2]})"
    if name in _ORACLES:
        return _ORACLES[name]
    if not name.lower().endswith((".rvt", ".rfa", ".rte", ".rft")):
        return name  # already a label, or not a file ("3 files", "-")
    return "model " + hashlib.sha1(name.encode()).hexdigest()[:6]
