# rvt-prt

**Print Autodesk Revit® sheets to vector PDF, straight from the `.rvt` file, without Revit.**

`rvt-prt` reads a Revit project file and draws its sheets the way Revit prints them: title
blocks, plans, ceiling plans, sections and elevations, schedules, annotations, in Revit's line
weights, colours and line patterns. It works on a standalone model and on a model with linked
models. Sheets can also be written as DWFx, and plan views as DXF, and any of these compared line
by line against Revit's own exports.

> Status: **alpha.** It is measured against Revit's own prints (below) and
> improves against them release by release. It is not a complete Revit renderer: see
> `docs/limitations.md`. It is not affiliated with Autodesk.

Tested on 64-bit ARM Linux; macOS should work the same way; Windows is untested
(no forked render workers there: sheets print one at a time, without their memory guard).

---

## What it draws

- **Sheets**: title blocks (their lines in their line styles' pens), viewports, view titles and
  scales, revision tables, schedules, placed images, text notes, tags, room and space tags.
- **Views**: floor plans cut at the view range's cut plane, ceiling plans looking up, sections and
  elevations cut at the view plane with hidden lines removed. Each view's detail level
  (Coarse / Medium / Fine), crop and visibility settings are read from the file.
- **Families** from the graphics Revit saved for each family type: curves and solids, cut and
  projected, chosen by view direction, detail level and cut, with nested families' visibility.
- **Line weights, colours and patterns** from the model: the Line Weights table per view scale,
  Object Styles per category and subcategory, each family line style's pen, colour and pattern.
- **Walls** (joins cleaned up), **MEP** in system colours, **stairs** and railings, **grids**,
  **elevation markers**, **section lines**, **levels**, filled regions and cut hatching.
- **Linked models**: placed and printed halftone, as Revit prints them by default.

---

## Install

Python 3.10 or later:

```bash
git clone <this repository> rvt-prt && cd rvt-prt
python3 -m venv .venv
.venv/bin/pip install -e .            # pymupdf, numpy, shapely, olefile, fonttools; compiles rvt-rs (Rust >= 1.87)
.venv/bin/pip install -e ".[dxf]"     # optional: DXF export and reading Revit's DXF (ezdxf)
```

Wall, slab and other mesh geometry comes from [rvt-rs](https://github.com/DrunkOnJava/rvt-rs),
the `rvt` crate from crates.io (pinned in `native/Cargo.toml`), compiled into the package as `rvt_prt._native` and run
in-process.

Linked models are found by file name, searched in order: beside the model, in a `links/` folder
beside the model, then in the folder named by `RVT_PRT_LINKS`. A link that is not found is left
out of the print, with a warning naming the file and the folders searched.

---

## Commands

```text
rvt-prt list MODEL                      list sheets and their viewports
rvt-prt print MODEL [options]           print sheets to PDF or DWFx, or plan views to DXF
    -o, --output PATH                     a folder (one file per sheet), or a .pdf / .dwfx file holding every sheet
    -f, --format {pdf,dwfx,dxf}           default: from the output's extension, else pdf
    --sheet NUMBER                        only this sheet (repeatable)
    -j, --jobs N                          parallel render processes (default: CPU count)
    --geometry-jobs N                     models/links whose caches are built at once on a first print
                                          (default 0 = as many as cores and memory allow; 1 = one at a time)
    -q, --quiet                           no progress output
rvt-prt compare REFERENCE OURS [opts]   compare drawings line by line (pdf / dwfx / dxf, files or folders)
    --sheet NAME                          only these sheets or views (repeatable)
    --tol, --step, --top                  match tolerance, sampling step, worst groups listed
    --blocks                              compare family blocks in their own coordinates
    --json                                scores as JSON
rvt-prt cache [--clear [MODEL ...]]     what the cache folder holds per model; clear a model's entries, or all
rvt-prt ifc MODEL -o FILE               rvt-rs's IFC4 export of the model
rvt-prt --version
python -m rvt_prt.metrics.blockbench MODEL ORACLE_DXF_DIR
                                          every family instance on every sheet against Revit's DXF blocks
python -m rvt_prt.metrics.metrics OURS.pdf ORACLE_PDF_DIR [dpi] [radius] [mode]
                                          ink recall / precision against Revit's PDF prints
```

`python -m rvt_prt` is the same as `rvt-prt`.

## Examples

```bash
# What is in the model
rvt-prt list "Snowdon Towers Sample HVAC.rvt"

# Every sheet to its own PDF, "<number> - <name>.pdf", in out/sheets
rvt-prt print "Snowdon Towers Sample HVAC.rvt" -o out/sheets

# Every sheet to one PDF (one page and one bookmark per sheet)
rvt-prt print "Snowdon Towers Sample HVAC.rvt" -o out/sheets.pdf

# Two sheets, four processes
rvt-prt print model.rvt -o out/plans.pdf --sheet M101 --sheet M102 -j 4

# DWFx (lines grouped by the element that drew them), or each plan view as DXF
rvt-prt print model.rvt -o out/M101.dwfx --sheet M101
rvt-prt print model.rvt -f dxf -o out/dxf --sheet M101

# How close is it to Revit? Export the sheet from Revit (DXF, DWFx or PDF) and compare
rvt-prt compare revit_exports/M101.dxf out/M101.dwfx
rvt-prt compare revit_exports/ out/sheets.dwfx --json
```

From Python:

```python
from rvt_prt import RevitModel

model = RevitModel("Snowdon Towers Sample HVAC.rvt")
for sheet in model.sheets:
    print(sheet.number, sheet.name, [v.view_name for v in sheet.viewports])

model.render_to_pdf("out/sheets.pdf", sheet_numbers=["M101", "M102"], workers=4)
model.render_to_dwfx("out/M101.dwfx", sheet_numbers=["M101"])
model.export_dxf("out/dxf", sheet_numbers=["M101"])          # needs the dxf extra
```

---

## How close it is

Measured against Revit 2025's own exports of the same sheets. The dates are when each was last
measured; `docs/accuracy.md` has every score and how it is made.

| Test | What it covers | Recall | Precision | Date |
|---|---|---:|---:|---|
| Test family sheet, lines against Revit's DXF | one family at three detail levels, six rotations | 100.0% | 100.0% | 2026-11-15 |
| Test room sheet, lines against Revit's DXF | walls, door, window, column, furniture, light; plan, ceiling plan, 4 elevations, 3 sections, title block, revision table | 98.7% | 99.5% | 2026-11-15 |
| Snowdon Towers HVAC M101, lines against Revit's DWFx | a full floor plan with five linked models | 95.4% | 93.3% | 2026-11-15 |
| Snowdon Towers HVAC, ink against Revit's PDF | 7 floor plans / 7 ceiling plans | 94–95% / 96–98% | 93–97% / 93–96% | 2026-11-15 |
| Snowdon Towers HVAC, every family instance against Revit's DXF blocks | 9,911 instances matched | 90.5% | 83.6% | 2026-11-15 |

Recall is how much of Revit's drawing is also in ours; precision is how much of ours is also in
Revit's.

A warm print of Snowdon's 18 sheets takes about 28 s on a 4-core ARM64 board with 8 GB (0.6 GB in
the main process); a first print, which builds the caches of the model and its links, about two
minutes.

---

## How it was made: clean room

`rvt-prt` is an independent, interoperability-focused implementation. Its knowledge of the
`.rvt` format comes from:

- **The files themselves.** A Revit file carries its own class and field catalog
  (`Formats/Latest`); records are decoded from that catalog, and their meaning is established by
  observing the bytes of files written by Revit: Autodesk's publicly distributed sample projects,
  and small test models made for the purpose.
- **Revit's own exports as the reference.** Each meaning is confirmed by comparing what we draw
  with what Revit printed and exported (PDF, DXF, DWFx) for the same file. The exports name the
  element behind every line, which is how a field is tied to its effect.
- **Published open-source work**: [rvt-rs](https://github.com/DrunkOnJava/rvt-rs) (Apache-2.0),
  itself a clean-room reader with a written
  [clean-room policy](https://github.com/DrunkOnJava/rvt-rs/blob/main/CLEANROOM.md). Parts of its
  reader are ported to Python here (container decompression, the class registry, the object-graph
  decoder, the saved-graphics surfaces), and it is compiled into the native extension that supplies mesh geometry.
- **Public specifications**: Microsoft Compound File Binary ([MS-CFB]), RFC 1950-1952
  (zlib / DEFLATE / gzip), and buildingSMART IFC.

Revit itself was used only to make those reference exports and dumps from files, with a licensed
copy. `rvt-prt` contains no Autodesk code, links none, and needs none to run. It does **not**
use Autodesk's source code or SDK internals, the Open Design Alliance SDK, leaked or NDA
documentation, or decompiled Revit code. The full policy is in
[`CLEANROOM.md`](CLEANROOM.md).

Reverse engineering a file format for interoperability is generally recognised as lawful (for
example the EU Software Directive 2009/24/EC, Art. 6, and US case law such as *Sega v. Accolade*);
Revit files carry no access-control or rights-management technology. This is not legal advice.

---

## License

`rvt-prt` is licensed under the **Apache License 2.0** (see `LICENSE` and `NOTICE`).

Apache 2.0 suits it: it is permissive (use in commercial and closed tools is allowed), it carries
an explicit patent grant, and it matches rvt-rs, from which parts are ported; rvt-rs's copyright
and NOTICE are retained in `NOTICE`.

**Dependencies to be aware of:**

| Dependency | License | Note |
|---|---|---|
| PyMuPDF | **AGPL-3.0** or a commercial license from Artifex | used to write PDF pages and to read PDFs for comparison |
| numpy, shapely, olefile | BSD | |
| fontTools | MIT | PDF font subsetting |
| ezdxf (optional) | MIT | |
| rvt-rs | Apache-2.0 | compiled into the native extension |

`rvt-prt`' own code stays Apache-2.0, but PyMuPDF is AGPL: if you **distribute** a program built
on `rvt-prt`, or offer it to users **over a network**, PyMuPDF's AGPL terms apply to that
combined program unless you hold Artifex's commercial license.

---

## Trademarks

Autodesk® and Revit® are registered trademarks of Autodesk, Inc. This project is not affiliated
with, endorsed by, or sponsored by Autodesk. The names are used only to identify the file format
it reads. Autodesk's sample projects used for testing are not redistributed here.
