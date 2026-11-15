# Accuracy

rvt-prt has one measure of success: how close its print of a sheet is to Revit's own print of
the same sheet. Nothing is judged by eye alone. This page explains how that is measured, what the
scores are, and how to measure a model of your own.

The scores below are from the development machine on the dates given. They are refreshed at each
release. Accuracy is **measured, not complete**: [Limitations](limitations.md) lists what is not
drawn as Revit draws it.

## Two numbers

Every comparison gives two numbers.

- **Recall**: of what Revit drew, how much did rvt-prt also draw? Low recall means things are
  missing.
- **Precision**: of what rvt-prt drew, how much did Revit also draw? Low precision means extra
  things are drawn: lines Revit hides, or lines in the wrong place.

A change can raise one and lower the other, so both are always reported.

## Three ways of measuring

| Measure | Compares | Tool | Good for |
|---|---|---|---|
| **Lines** | Line by line, in sheet inches, each line labelled with the element that drew it | `rvt-prt compare` | Finding exactly which element differs |
| **Ink** | The two PDFs rasterised, pixel against pixel | `rvt_prt.metrics.metrics` | A whole-page score that includes text, fills and line weights |
| **Family blocks** | Every family instance against the block Revit placed for it, each in the family's own coordinates | `rvt_prt.metrics.blockbench` | How well family symbols are drawn, family by family |

**Lines.** Revit labels its exports by element. In its DXF, entities carry the element's id, type,
category and subcategory. In its DWFx, each path resolves to an object such as
`Basic Wall [619340]`. rvt-prt writes the same labels in its own DWFx and DXF. So a comparison
can say not only "94% of the lines match" but "element 619340 is missing a line". Points are
sampled along every line (every 0.01 in), and a point matches when the other drawing has a line
within the tolerance (0.03 in).

**Ink.** Both PDFs are drawn at 50 dpi, and a pixel matches when the other page has ink within
2 pixels. The whole page counts, title block included.

**Family blocks.** Instances are paired by where they sit on the sheet, and each pair is scored
in the family's own frame, so a symbol drawn turned or mirrored counts as a miss.

## The reference models

| Reference | What it is | Why |
|---|---|---|
| `testfamily` | One sheet: one family at Coarse, Medium and Fine, turned six ways | Isolates family graphics and placement |
| `test02` | One sheet: a room with walls, a door, a window, a column, furniture and a light, in a plan, a ceiling plan, four elevations and three sections, with a title block and a revision table | Isolates each view type on a model small enough to read by hand |
| Snowdon Towers Sample HVAC | Autodesk's sample project: 18 sheets, an MEP model with five linked models | A real sheet set, with links |
| A corpus of 68 files, Revit 2008 to 2027 | Autodesk's sample projects of each year and openly licensed test models | That every supported release prints at all (`bench/versions.md`) |

Each of the first three has Revit's own PDF, DXF and DWFx of its sheets. Autodesk's sample
projects and their exports are not redistributed with rvt-prt.

## Current scores

### Test models, lines against Revit's DXF

| Model | Recall | Precision | Text |
|---|---:|---:|---:|
| `testfamily`, sheet A101 | 100.0% | 100.0% | |
| `test02`, sheet A101 | 98.7% | 99.5% | 90.0% |

`test02`'s ink against Revit's PDF: 99.2% recall, 92.9% precision. These are checked on every
change (`pytest -m oracle`), each against a floor at its current value.

### Snowdon Towers HVAC, ink against Revit's PDF

Recall / precision in percent, 50 dpi, 2026-11-15 (release 0.1.0).

| Sheet | Recall | Precision | | Sheet | Recall | Precision |
|---|---:|---:|---|---|---:|---:|
| M100 parking plan | 94.2 | 96.6 | | M200 ceiling plan | 96.2 | 96.2 |
| M101 floor plan | 95.2 | 95.0 | | M201 ceiling plan | 97.5 | 95.5 |
| M102 floor plan | 94.4 | 95.8 | | M202 ceiling plan | 96.5 | 93.5 |
| M103 floor plan | 95.4 | 96.6 | | M203 ceiling plan | 97.0 | 94.7 |
| M104 floor plan | 94.7 | 96.2 | | M204 ceiling plan | 96.7 | 93.4 |
| M105 floor plan | 94.2 | 93.2 | | M205 ceiling plan | 97.3 | 93.9 |
| M106 roof plan | 94.5 | 92.7 | | M206 ceiling plan | 95.6 | 95.5 |

The cover sheet M000 scores 89.3 / 99.6, and the schedule sheets M001 and M002 score
99.5 / 99.4 and 99.3 / 99.2.

Text, all 18 sheets, words placed within 0.1 in of Revit's: 3,066 of our 3,136 (97.8%); Revit
prints 3,237.

### Snowdon Towers HVAC, lines

Sheet M101, 0.03 in tolerance, 2026-11-15:

| Reference | Recall | Precision | Text |
|---|---:|---:|---:|
| Revit's DWFx | 95.4% | 93.3% | 95.3% |
| Revit's DXF | 98.3% | 93.2% | 95.3% |

Revit's own DXF and DWFx of M101 agree with each other at 99.9% recall and 98.8% precision, which
checks both readers.

### Snowdon Towers HVAC, family blocks

All sheets, 2026-11-15: **90.5% recall, 83.6% precision**. 9,911 instances matched, 333 missed,
54 drawn as loose lines, 2,917 extra.

How it got there:

| Step | Recall | Precision |
|---|---:|---:|
| Family documents' curves | 37.2% | 57.3% |
| Instance placement fixes | 39.0% | 61.5% |
| Extrusions built from sketches | 48.2% | 64.2% |
| Revit's saved graphics per family type | 66.2% | 78.0% |
| Phases; the Facades link drawn | 72.8% | 83.1% |
| MEP above the cut, rails, casework, cut representations; the bench pairing split and repeated instances | 90.5% | 83.6% |

## Measuring your own model

You need Revit once, to make the reference.

1. In Revit, export the sheet: **File > Export > CAD Formats > DXF** (or DWFx), or print it to
   PDF. DXF and DWFx are the more useful, because they name the element behind each line.
2. Print the same sheet with rvt-prt, to DWFx:

   ```bash
   rvt-prt print model.rvt -o out/A101.dwfx --sheet A101
   ```

3. Compare:

   ```bash
   rvt-prt compare revit_exports/A101.dxf out/A101.dwfx
   ```

The report ([Command line](usage.md#compare)) gives the overall recall and precision, then the
same by layer, then the worst elements on each side. A line starting `ref` is something Revit
drew that rvt-prt missed. A line starting `ours` is something rvt-prt drew that Revit did
not. Each names the element id, which you can look up in Revit (**Manage > Select by ID**).

How Revit's DXF is read: a sheet's DXF holds each view in model space, in millimetres, placed on
the sheet by paper-space viewports, and the reader maps each view through its viewport. DWF (the
binary format, not DWFx) is not read.

## Measuring tools

```bash
# Ink: our PDF against a folder of Revit's PDFs, one per sheet
python -m rvt_prt.metrics.metrics out/sheets.pdf oracle/snowdon_hvac 50 2 ink

# Family blocks: every family instance on every sheet against Revit's DXF blocks
python -m rvt_prt.metrics.blockbench "oracle/Snowdon Towers Sample HVAC.rvt" oracle/snowdon_hvac_dxf
python -m rvt_prt.metrics.blockbench --show 3     # the last runs, each against the one before

# Text: our words against Revit's, placed within a tolerance
python -m rvt_prt.metrics.textscore out/sheets.pdf oracle/snowdon_hvac [tolerance_in]

# Overlays: our sheet over Revit's print, one PNG per sheet
python -m rvt_prt.metrics.compare out/sheets.pdf oracle/snowdon_hvac out/overlays [dpi]
```

The family bench reports, per sheet and per family, recall, precision, and instances matched,
missed, drawn as plain lines, or extra. Each run is appended to `bench/families.jsonl`, with the
table in `bench/families.md`, and the run reports what improved or regressed against the one
before.

`rvt-prt compare ... --blocks` is a quick look at the same thing for one sheet. Revit shares
one block among all instances of a type, so pairing by element id pairs just one instance per
block. The bench pairs by position instead.

## The test oracles

The two small models are the regression gate. In a clone that has them:

```bash
7z x -ooracle/testfamily oracle/TestFamily.7z
7z x -ooracle/test02 oracle/02.7z
pytest -m oracle
```

`pytest -m oracle` prints each model and fails if a score falls below its floor
(`tests/integration/test_oracles.py`). It takes seconds, and needs the native extension built.
The tests are skipped when the oracle files are absent.

## What the scores do not say

- They are for these models. A model that uses features the references do not (dimensions,
  legends, shaded views) will score lower, and nothing here measures by how much.
- Ink at 50 dpi with a 2 pixel tolerance forgives small offsets and line-weight differences.
- A high score on a sheet does not mean every element on it is right. Read the per-element lines
  of `rvt-prt compare` for that.
