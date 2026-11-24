# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Sheet parameters: `rvt-prt list --params`, `--csv` and `--json` show each sheet's built-in
  parameters (Appears In Sheet List, Sheet Issue Date, Drawn By, ...) and its project and shared
  ones (text, whole numbers, Yes/No). `--where NAME=VALUE` (also `!=` and `~` for contains, `*`
  and `?` wildcards) chooses the sheets `list` shows and `print` prints. In Python:
  `RevitModel.sheet_parameters` and `RevitModel.select_sheets`.
- Prebuilt wheels for Linux (x86_64, aarch64) and macOS (arm64, x86_64), built and published
  by a release workflow, so installing a release needs no Rust toolchain.

### Changed

- rvt-rs 0.25.0 (`rvt = "=0.25.0"`, from 0.24.0). Snowdon's 7 models mesh to the same elements,
  triangles, boxes and volumes; 17 stair landings of the Architectural link now carry their
  family name (Non-Monolithic Landing). `bench/rvtrs.md` has the comparison.

### Fixed

- CI's check that the extension loads, which was a Python syntax error.

## [0.1.0] - 2026-11-15

First public release.

### What it does

- Prints a Revit model's sheets to vector PDF straight from the `.rvt` file, without Revit:
  - title blocks, viewports, plans, ceiling plans, sections and elevations;
  - schedules, sheet indexes, text, tags, room tags, grids, levels and markers;
  - in the model's line weights, colours and patterns.
- Draws standalone models and models with linked models alike, each view at its own phase,
  elements demolished in an earlier phase included.
- Title blocks and text notes in their text types' sizes, styles and baselines, mixed-style runs
  and RTF dashes, bullets and quotes included. Text in the PDF is searchable and copyable.
- Also writes DWFx, and plan views as DXF. `rvt-prt compare` scores a print against Revit's
  own PDF, DWFx or DXF.
- Reads Revit 2014 to 2027 files. Older files stop with a message naming their release.

- A file that cannot be printed stops the command with one line and exit status 1: a missing
  file, a file that is not a Revit project, a damaged file, an unsupported release.
- `rvt-prt --version`. `rvt-prt cache` lists and clears the caches. `rvt-prt ifc` writes
  rvt-rs's IFC4 export.
- The Python API is `rvt_prt.RevitModel`, with the errors `UnsupportedFile` and `NoSheets`.

- Speed: Snowdon Towers HVAC's 18 sheets print in about 2 minutes into an empty cache and
  20 s again, on a 4-core ARM board with 8 GB. Sheets are drawn in parallel, each page finished
  in its sheet's process; each family type's hidden lines and each plan view's linework are
  kept between prints; a plan view walks only the elements that reach its crop.
- Projects whose linked models do not fit in memory together print: the sheets are drawn in
  groups, each with only the models its views show (`RVT_PRT_MODELS_GB` sets the limit).

- Bounds on what a hostile file can do: a limit on how much a file may inflate to, refused
  counts, linked models by file name alone, private cache folders, `--sheet-timeout` and
  `--memory-limit` (`SECURITY.md`).

- rvt-rs is the `rvt` crate from crates.io, pinned exactly (`rvt = "=0.24.0"`).

### Known limitations

- Accuracy is measured, not complete: see `docs/accuracy.md` for the scores against Revit's
  prints and `docs/limitations.md` for what is not yet drawn as Revit draws it.
- Tested on Linux only. On Windows, sheets print one at a time without the memory guard.
- No prebuilt packages: installing compiles a Rust extension.
- The whole print has no time limit, only each sheet (`SECURITY.md`).
