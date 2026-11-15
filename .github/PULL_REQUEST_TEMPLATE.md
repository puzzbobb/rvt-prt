**What this changes, and why**

**Measured effect**

Which scores moved, by how much, on which files. Or "output unchanged", and how that was checked.

**Checks run**

- [ ] `ruff check src tests`
- [ ] `mypy`
- [ ] `pytest tests/unit`
- [ ] `pytest -m oracle` (say so if you do not have the oracle files)

**Sources** (only for a format finding: a decoded field, record, class or meaning)

These findings come from [file bytes of ..., Revit's DXF export of ..., rvt-rs ...]. I have not
used Autodesk or ODA source, leaked or NDA material, decompiled Revit code, or a debugger on
Revit.

**Documents updated**

Changelog and `docs/`, as `CONTRIBUTING.md` lists.
