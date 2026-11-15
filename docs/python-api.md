# Python API

The public API is what `import rvt_prt` exports:

| Name | What it is |
|---|---|
| `RevitModel` | A Revit project opened for listing and printing its sheets |
| `UnsupportedFile` | Raised for a file that is not a Revit project, is damaged or made to mislead a reader, or is from a release rvt-prt does not read. A `ValueError` |
| `NoSheets` | Raised when a print finds no sheet to draw. A `LookupError` |
| `__version__` | The installed version, as a string |

Everything else in the package (`rvt_prt.core`, `model`, `elements`, `geometry`, `render`,
`formats`, `metrics`) is internal. It can be imported, and [How it works](how-it-works.md)
describes it, but it carries no promise of stability between releases.

rvt-prt is at version 0.1. The public API may still change before 1.0.

## A first example

```python
from rvt_prt import RevitModel

model = RevitModel("Snowdon Towers Sample HVAC.rvt")

for sheet in model.sheets:
    print(sheet.number, sheet.name, [v.view_name for v in sheet.viewports])

summary = model.render_to_pdf("out/sheets.pdf", sheet_numbers=["M101", "M102"], workers=4)
print(summary["files"], summary["elapsed_s"])
```

## RevitModel

### `RevitModel(path)`

Opens the project at `path` (a `str` or `pathlib.Path`). Opening reads only the file's directory.
The sheets are read when first asked for.

Raises `FileNotFoundError` when there is no such file, and `UnsupportedFile` when the file is not
a Revit project or cannot be read as one.

### `model.sheets`

The model's sheets, as a list of `Sheet` objects sorted by sheet number. Read once and kept.

Raises `UnsupportedFile` for a file from a Revit release whose sheets cannot be read. The message
names the release, or the build date when the file records no release.

### `model.get_sheet(sheet_number)`

The sheet with that number (for example `"M101"`), or `None`.

### `model.render_to_pdf(output_path, sheet_numbers=None, workers=None, benchmark=False, geometry_jobs=None)`

Prints sheets to vector PDF.

| Argument | Meaning |
|---|---|
| `output_path` | A path ending in `.pdf`: every sheet in that one file, a page and a bookmark each. Any other path is a folder: each sheet goes to its own file in it, `<number> - <name>.pdf` |
| `sheet_numbers` | The sheets to print, by number. `None` prints all |
| `workers` | Sheets drawn at once, each in its own process. `None` uses the CPU count |
| `benchmark` | `True` also prints the stage times to stdout |
| `geometry_jobs` | Models and links whose caches are built at once on a first print. `None` reads `RVT_PRT_GEOMETRY_JOBS`, else `0`: as many as cores and free memory allow. `1` builds them one by one in this process |
| `sheet_timeout` | Seconds a sheet may take to draw before it is stopped. `None` reads `RVT_PRT_SHEET_TIMEOUT`, else no limit |

Returns a [summary](#the-summary). Raises `NoSheets` when no sheet matches.

### `model.render_to_dwfx(output_path, sheet_numbers=None, workers=None, benchmark=False, geometry_jobs=None)`

Prints sheets to DWFx: the PDF's content, with the linework grouped by the element that drew it.
A path ending in `.dwfx` holds every sheet in one package. Any other path is a folder with one
package per sheet. Returns a summary.

### `model.export_dxf(output_dir, sheet_numbers=None, benchmark=False, geometry_jobs=None)`

Writes each plan view placed on the sheets as `<view name>.dxf` in `output_dir`, in model feet,
with family instances as blocks. Needs the `dxf` extra (ezdxf). Returns a summary.

### `model.view_drawings(sheet_numbers=None)`

The same plan views as `export_dxf` writes, kept in memory: a dict from sheet number to a list of
drawings. The drawing objects are internal (`rvt_prt.formats.drawing.Drawing`) and may change.

### The summary

The three output methods return a dict:

| Key | Value |
|---|---|
| `sheets_count` | How many sheets were printed |
| `output` | The output path, as given |
| `files` | The files written, as a list of paths |
| `elapsed_s` | Seconds the print took |
| `peak_rss_mb` | The printing process's peak memory in MB (PDF only, else `None`) |
| `stages` | Seconds per stage, as a dict |

## Sheet

| Attribute | Meaning |
|---|---|
| `number` | The sheet number, for example `"M101"` |
| `name` | The sheet name |
| `size` | The paper's `(width, height)` in **feet**. Multiply by 12 for inches |
| `viewports` | The views placed on the sheet, as a list of viewport objects |
| `fields` | The sheet's title block fields (drawn by, checked by, date and so on), as a dict |
| `scheduled` | Whether the sheet appears in the sheet list |

Each viewport has `detail` (its detail number), `view_name`, `scale` (100 for 1 : 100) and
`view_id`. Its other attributes describe how the view is placed and are internal.

## Errors

```python
from rvt_prt import NoSheets, RevitModel, UnsupportedFile

try:
    RevitModel(path).render_to_pdf("out", sheet_numbers=["A101"])
except FileNotFoundError:
    ...                       # no such file
except UnsupportedFile as e:
    print(e)                  # "old.rvt is from Revit 2011: rvt-prt reads the sheets of Revit 2014-2027 files only"
except NoSheets as e:
    print(e)                  # "no sheets to print in model.rvt numbered A101"
```

A linked model that is not found is not an error. The print goes on without it, and a warning on
stderr names the file and the folders searched.

## Things to know

- **Progress output.** The API is silent by default. The command line turns progress on. To see
  it from your own code, call `rvt_prt.core.progress.enable(True)` before printing (internal,
  and may change).
- **Processes.** On Linux and macOS a print forks worker processes: one per sheet being drawn,
  and on a first print one per model whose caches are built. Call the output methods from the
  main thread of a process that can fork. On Windows sheets are drawn one at a time in the
  calling process.
- **Caches.** A print writes caches under the cache folder (`RVT_PRT_CACHE`, see
  [Fonts, linked models and caches](configuration.md#caches)). The folder is read when
  `rvt_prt` is imported, so set the variable before the import.
- **One model per process is the tested case.** Printing several different models from one
  long-lived process works through the same code, but module-level state is shared between
  prints. For a batch, one process per model is the safe choice.
- **Licence.** PDF pages are written with PyMuPDF, which is AGPL-3.0 (or commercial). That
  matters if you distribute a program built on rvt-prt or offer it over a network. See the
  README's licence section.
