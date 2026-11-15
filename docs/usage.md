# Command line

The `rvt-prt` command has five subcommands. `python -m rvt_prt` is the same command.

| Command | What it does |
|---|---|
| [`rvt-prt list MODEL`](#list) | Lists the sheets and the views placed on each |
| [`rvt-prt print MODEL`](#print) | Prints sheets to PDF or DWFx, or their plan views to DXF |
| [`rvt-prt compare REFERENCE OURS`](#compare) | Scores one drawing against another, line by line |
| [`rvt-prt cache`](#cache) | Shows what the cache folder holds, or clears it |
| [`rvt-prt ifc MODEL -o FILE`](#ifc) | Writes rvt-rs's IFC4 export of the model |

`rvt-prt --version` prints the version, and `rvt-prt COMMAND --help` lists a command's
options.

A command that cannot go on stops with one line on stderr and exit status 1. This covers a
missing file, a file that is not a Revit project, a damaged file, a file from a Revit release
that is not supported, and a request for sheets the model does not have. Any other failure is
also one line, and `RVT_PRT_DEBUG=1` shows its traceback.

For a file you do not trust, give `--memory-limit` and `--sheet-timeout`
([`SECURITY.md`](../SECURITY.md)).

## list

```bash
rvt-prt list model.rvt
```

One line per sheet: its number, name, paper size in inches, and its viewports. Each viewport is
shown as its detail number, the view's name and the view's scale.

```text
A101   TEST                             42.0 x 30.0 in  viewports: 1 Level 1 - Fine (1 : 100); 2 Level 1 - Medium (1 : 100); 3 Level 1 - Coarse (1 : 100)
```

A model with no sheets prints nothing on stdout and says so on stderr.

| Option | Meaning |
|---|---|
| `--where FILTER` | Only the sheets whose parameters match. Repeat it for several, which must all hold. See [Choosing sheets by their parameters](#choosing-sheets-by-their-parameters) |
| `--params` | Each sheet's parameters that have a value, a line each under the sheet |
| `--csv` | Every sheet's parameters as CSV on stdout: a row per sheet, a column per parameter |
| `--json` | Every sheet as JSON: its number, name, paper size in inches, viewports and parameters |

```bash
rvt-prt list model.rvt --params
rvt-prt list model.rvt --csv > sheets.csv
rvt-prt list model.rvt --json --where "Appears In Sheet List=Yes"
```

```text
A101   First Floor Plan                 42.0 x 30.0 in  viewports: 1 L1 (1/8" = 1'-0")
       Appears In Sheet List: Yes
       Sheet Issue Date: 08/28/22
       Drawn By: APF
       Sheet Group: Architectural
```

### Choosing sheets by their parameters

`list` and `print` take `--where`, once or several times, to choose sheets by their parameters.

| Filter | A sheet matches when |
|---|---|
| `NAME=VALUE` | the parameter is VALUE. `*` stands for any text and `?` for one character: `"Sheet Number=A1*"` |
| `NAME!=VALUE` | the parameter is anything else |
| `NAME~TEXT` | the parameter contains TEXT: `"Sheet Name~plan"` |

- **Names** are the parameters' names as Revit shows them. The built-in ones are `Sheet Number`,
  `Sheet Name`, `Appears In Sheet List`, `Sheet Issue Date`, `Drawn By`, `Checked By`,
  `Designed By` and `Approved By`. After them come the model's project and shared parameters
  that hold text, whole numbers or Yes/No (`Sheet Group`, say). `list --params` shows a model's.
  Parameters that are numbers with units, such as lengths, are not read yet.
- **Names and values** are compared in any case. A Yes/No parameter is `Yes` or `No`, and
  `true`, `false`, `1` and `0` mean the same. A parameter a sheet has no value for is empty, so
  `"Drawn By="` chooses the sheets without one.
- **A name no sheet parameter has** stops the command with a line listing the names there are,
  and exit status 1. So does a filter that no sheet matches.
- Put a filter with spaces in quotes.

```bash
rvt-prt print model.rvt -o issue.pdf --where "Appears In Sheet List=Yes" --where "Sheet Group=Architectural"
rvt-prt print model.rvt -o plans --where "Sheet Name~plan" --where "Sheet Number!=SD*"
```

With `--sheet` as well, a sheet is printed when it is one of those numbered and matches the filters.

## print

```bash
rvt-prt print model.rvt                       # every sheet, each to its own PDF in out/sheets
rvt-prt print model.rvt -o sheets             # the same, in sheets/
rvt-prt print model.rvt -o sheets.pdf         # every sheet in one PDF
rvt-prt print model.rvt -o plans.pdf --sheet M101 --sheet M102 -j 4
```

| Option | Meaning |
|---|---|
| `-o`, `--output PATH` | A folder, or a `.pdf` or `.dwfx` file. Default: `out/sheets` (`out/dxf` for DXF) |
| `-f`, `--format {pdf,dwfx,dxf}` | The output format. Default: from the output's extension, else `pdf` |
| `--sheet NUMBER` | Print only this sheet. Repeat it for several |
| `--where FILTER` | Print only the sheets whose parameters match: `"Appears In Sheet List=Yes"`. Repeatable. See [Choosing sheets by their parameters](#choosing-sheets-by-their-parameters) |
| `-j`, `--jobs N` | Sheets drawn at once, each in a process of its own. Default: the number of CPU cores |
| `--geometry-jobs N` | Models and links whose caches are built at once on a first print. Default: `RVT_PRT_GEOMETRY_JOBS`, else `0`, which means as many as the cores and free memory allow. `1` builds them one after another in the printing process |
| `--sheet-timeout SECONDS` | Stop a sheet that takes longer than this to draw. It is drawn again without its sections' model linework, and failing that left blank with a note. Default: `RVT_PRT_SHEET_TIMEOUT`, else no limit |
| `--memory-limit GB` | The most address space the print and each of its workers may take. The print runs in a process of its own, and past the limit it stops with one line (`out of memory within --memory-limit ...`, exit status 1). Linux and macOS |
| `-q`, `--quiet` | No progress lines or bar. Warnings and the summary still print |

### Where the output goes

- **A folder** (any path that does not end in `.pdf` or `.dwfx`): each sheet goes to its own
  file in it, named `<number> - <name>.pdf`. The folder is created if needed.
- **A `.pdf` file**: every sheet in one PDF, one page and one bookmark per sheet.
- **A `.dwfx` file**: every sheet in one DWFx package.
- **DXF** always writes a folder, one `<view name>.dxf` per plan view placed on the sheets.

Existing files with the same names are overwritten. Nothing else in the folder is touched.

### Formats

| Format | What is written |
|---|---|
| PDF | Vector pages at the sheet's paper size, with the model's line weights, colours and patterns, and fonts embedded as subsets |
| DWFx | The same content as an XPS-based DWFx package, with the linework grouped by the element that drew it |
| DXF | Each plan view in model feet, with family instances as blocks. Needs the `dxf` extra (`pip install -e ".[dxf]"`) |

DWFx and DXF exist mainly so that a print can be compared with Revit's own exports, element by
element (see [compare](#compare)).

### What you see while it prints

`print` reports each stage on stderr as it starts, with the seconds since it began and the memory
the process holds:

```text
[   2.1 s  0.1 GB] model 1/1: TestProject2.rvt: meshes, patterns, saved graphics, stairs, phases
[   2.1 s  0.1 GB]   meshing TestProject2.rvt (once per file: cached in out/links)
[   3.5 s  0.1 GB]   building the saved_graphics cache of TestProject2.rvt (once per file or decoder change)
[   4.2 s  0.1 GB] drawing 1 sheet(s), up to 1 at a time
[   5.4 s] sheet A101 drawn (1/1)
wrote 1 sheets to out/test02.dwfx in 5.5 s
```

While the sheets are drawn it shows a bar: sheets done, those being drawn, and memory free.
Piped to a file, the bar is a line per sheet. The last line, on stdout, is the summary. A PDF
print also reports its stage times against the previous print of the same model.

### Linked models

A model's linked models are drawn too, halftone, as Revit prints them by default. They are found
by file name: beside the model, in a `links/` folder beside it, then in the folders
`RVT_PRT_LINKS` names. A link that is not found is left out of the print, with a warning that
names the file and the folders searched. See
[Fonts, linked models and caches](configuration.md#linked-models).

## compare

```bash
rvt-prt compare revit_exports/M101.dxf out/M101.dwfx
rvt-prt compare revit_exports/ out/sheets.dwfx --json
rvt-prt compare revit_exports/M101.dxf out/dxf --blocks
```

`compare` reads a reference drawing (normally Revit's own export) and one of ours, and reports
how much of each lies on the other. Either side may be a PDF, DWFx or DXF file, or a folder of
them. Drawings are paired by sheet number or view name.

| Option | Meaning |
|---|---|
| `--sheet NAME` | Only these sheet numbers or view names. Repeatable |
| `--tol X` | How close a point must be to count as matched. Default 0.03 in for sheets, 0.05 ft for views |
| `--step X` | The spacing of sample points along lines. Default 0.01 in, 0.02 ft |
| `--top N` | How many of the worst elements to list per side. Default 15 |
| `--blocks` | Compare family blocks in their own coordinates instead (Revit's DXF sheet export against our DXF view export) |
| `--json` | Print the scores as JSON |

The report gives **recall** (the share of the reference's line length that ours also draws) and
**precision** (the share of ours that the reference also draws), overall, by layer, and for the
worst elements on each side:

```text
A101: recall  98.7%  precision  99.5%  (reference 596 in of line, ours 471)  text  90.0%
  by layer (share matched, length):
    ours  99.4%      331.3  (none)
    ours 100.0%       45.3  Walls cut
    ours  98.0%       20.6  Furniture
    ref  100.0%      165.9  Z-040-M_ELEVATION
    ref   80.6%       40.2  Z-020-M_TITLE_BLOCK
  worst groups (ref: missed by ours; ours: not in ref):
    ref   96.5%      222.8  E9274  9274 9267 TitleBlocks B 11 x 17 Horizontal ...
    ours  95.8%        8.6  E5083  5083 Test_Furniture Furniture
```

Each group is an element: `E9274` is element id 9274. [Accuracy](accuracy.md) explains how to
export a sheet from Revit and read these numbers.

A sheet (in inches) cannot be compared with a view (in feet). `compare` says so and skips the
pair.

## cache

```bash
rvt-prt cache                          # what the cache folder holds, per model
rvt-prt cache --clear model.rvt        # remove one model's entries
rvt-prt cache --clear                  # remove every entry
```

```text
cache folder: /home/you/.cache/rvt-prt
       94.2 MB    21 entries  Snowdon Towers Sample Architectural.rvt
       15.2 MB    47 entries  Snowdon Towers Sample HVAC.rvt
        0.9 MB    42 entries  TestProject2.rvt
        0.0 MB     1 entries  (fonts)
      110.3 MB  total
```

`--clear` takes model paths or file names, or one of the groups the listing names: `(bench)`,
`(unfinished)` and `(fonts)`. Printed sheets are never touched. Clearing a cache only makes the
next print of that model slow again.

## ifc

```bash
rvt-prt ifc model.rvt -o model.ifc
rvt-prt ifc model.rvt -o model.ifc --saved-meshes
```

Writes the IFC4 export that rvt-rs makes of the model, as rvt-rs's own `rvt-ifc` tool does, and
reports how many building elements it holds. `--saved-meshes` writes family instances as their
saved meshes instead of boxes. Large models then need over 4 GB of memory.

This command is a convenience. The IFC is rvt-rs's work, and rvt-prt does not read it back.

## Measuring tools

Three more tools score whole sheet sets. They are development tools, run as modules, and their
options may change:

```bash
python -m rvt_prt.metrics.metrics OURS.pdf REVIT_PDF_DIR [dpi] [radius] [mode]
python -m rvt_prt.metrics.blockbench MODEL REVIT_DXF_DIR
python -m rvt_prt.metrics.geobench summary
```

[Accuracy](accuracy.md#measuring-tools) describes each.
