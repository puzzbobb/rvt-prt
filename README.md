# rvt-prt

**Print Autodesk Revit sheets to vector PDF, straight from the `.rvt` file, without Revit.**

rvt-prt is a python project that uses rvt-rs (Rust toolchain) to read a Revit project file (2014-2027) and draws its sheets the way Revit prints them: title
blocks, plans, ceiling plans, sections and elevations, schedules and annotations, in the model's
own line weights, colours and line patterns. It works on a standalone model and on a model with
linked models. It is a Python package with a command-line tool.

Sheets can also be written as DWFx, and plan views as DXF, and any of these compared line by
line, element by element, with Revit's own PDF, DWFx and DXF exports. That comparison is how the
project measures itself.

> **Status: in development - PRINTS DO NOT MATCH REVIT OUTPUT**
> Not to be used in production for outputs.
> Prints have been benchmarked against revit models and they are 90%+ accurate but there are lots of little details which are incorrect.

## Install

rvt-prt is installed from a GitHub clone. One part, a native extension built on
[rvt-rs](https://github.com/DrunkOnJava/rvt-rs), which is compiled on your machine, so you need a Rust
toolchain as well as Python 3.10 or newer.

```bash
git clone https://github.com/puzzbobb/rvt-prt.git
cd rvt-prt
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/rvt-prt --version
```

[Installing](docs/install.md) has the tools for each system, fonts, optional extras, updating,
and what to do when the build fails. It is developed and tested on Linux. macOS and Windows are
untested.

## Example Usage

```bash
rvt-prt list model.rvt                    # the sheets and the views on each
rvt-prt print model.rvt -o sheets         # every sheet, each to its own PDF in sheets/
rvt-prt print model.rvt -o sheets.pdf     # every sheet in one PDF
rvt-prt compare revit/A101.dxf out/A101.dwfx   # how close is it to Revit's own export?
```

```python
from rvt_prt import RevitModel

model = RevitModel("model.rvt")
for sheet in model.sheets:
    print(sheet.number, sheet.name)
model.render_to_pdf("sheets.pdf", sheet_numbers=["A101"])
```

## What it draws

- **Complete sheet sets**: title blocks, viewports, view titles and scales, revision tables. A
  sheet without a title block prints on a page fitted to its contents.
- **Plans, ceiling plans, sections and elevations**: plans cut at the view range's cut plane and
  projected below it, ceiling plans looking up, sections and elevations cut at the view plane
  with hidden lines removed. Each view's detail level, crop, phase and hidden categories are read
  from the file.
- **Families from Revit's saved graphics**: the curves and solids Revit saved for each family
  type, placed by each instance's transform and chosen by view direction, detail level and cut.
- **Line weights, colours and patterns from the model**: the line weight table per view scale,
  Object Styles per category and subcategory, and each line style's pen, colour and pattern.
- **Walls, MEP, stairs**: joined walls' outlines merged and cut faces hatched; ductwork, piping
  and equipment in their system colours; stair runs, landings and railings.
- **Annotation**: text notes, tags, room and space tags, grids, levels, elevation markers,
  section lines, detail lines, filled regions, images, and schedules.
- **Linked models**: drawn through the same pipeline and printed halftone.
- **Revit 2014 to 2027 files**, read by one code path, because a Revit file carries its own
  catalog of record layouts. Older files stop with a message naming their release.
- **Any script**: text is read in each font's code page, and text a font has no glyphs for is set
  in a fallback font, so Japanese, Chinese and Korean always print.
- **Heavy models on small machines**: sheets are drawn in parallel, each in its own process
  under a memory cap, and a sheet short of memory is retried with more of it.

What it does not draw yet (dimensions, legends, shaded views, compound wall layers and more) is
in [Limitations](docs/limitations.md).

## How close it is

Measured against Revit's own exports of the same sheets:

| Test | Recall | Precision |
|---|---:|---:|
| Test family sheet, lines against Revit's DXF | 100.0% | 100.0% |
| Test room sheet (plan, ceiling plan, elevations, sections), lines against Revit's DXF | 98.7% | 99.5% |
| Sample project, floor and ceiling plans, ink against Revit's PDF | 94 to 98% | 93 to 97% |
| Sample project, every family instance against Revit's DXF blocks | 90.5% | 83.6% |

Recall is how much of Revit's drawing is also in ours. Precision is how much of ours is also in
Revit's. [Accuracy](docs/accuracy.md) has every score with its date, how each is measured, and
how to measure a model of your own.

## Documentation

| | |
|---|---|
| [Installing](docs/install.md) | Requirements, compiling, updating |
| [Command line](docs/usage.md) | Every command and option |
| [Python API](docs/python-api.md) | `RevitModel` and its errors |
| [Fonts, linked models and caches](docs/configuration.md) | Where rvt-prt looks for things, and the environment variables |
| [Accuracy](docs/accuracy.md) | How prints are scored against Revit's, and the scores |
| [Limitations](docs/limitations.md) | What is not drawn yet; supported files and platforms |
| [Performance and memory](docs/performance.md) | Print times, memory needs, heavy models |
| [Troubleshooting](docs/troubleshooting.md) | Messages and what to do about them |
| [How it works](docs/how-it-works.md) | From the bytes of a `.rvt` to a PDF page; the module map |
| [How the project runs](docs/project.md) | Purpose, decisions, how changes are judged, releases |
| [Contributing](CONTRIBUTING.md) | Setting up, measuring a change, rules for the code |
| [Clean-room policy](CLEANROOM.md) | Where the format knowledge comes from |
| [Security](SECURITY.md) | Reporting a vulnerability |
| [Changelog](CHANGELOG.md) | What each release changed |

## How it was made

rvt-prt is an independent implementation, written for interoperability. Its knowledge of the
format comes from the bytes of Revit files, from what Revit itself prints and exports for those
files, from published open-source work, and from public specifications. It contains no Autodesk
code and needs none to run. [`CLEANROOM.md`](CLEANROOM.md) is the policy.

Element meshes come from [rvt-rs](https://github.com/DrunkOnJava/rvt-rs), a separate open-source
project, used as published: `native/Cargo.toml` pins an exact release of the `rvt` crate from
crates.io, unpatched.

## Licence

rvt-prt is licensed under the **Apache License 2.0**. See [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE).

One dependency needs care. PDF pages are written with **PyMuPDF**, which is AGPL-3.0 unless you
hold a commercial licence from Artifex. rvt-prt's own code stays Apache-2.0, but if you
distribute a program built on rvt-prt, or offer one to users over a network, PyMuPDF's AGPL
terms apply to that combined program.

## Trademarks

Autodesk and Revit are registered trademarks of Autodesk, Inc. This project is not affiliated
with, endorsed by, or sponsored by Autodesk. The names are used only to identify the file format
it reads. Autodesk's sample projects, used for testing, are not redistributed here.
