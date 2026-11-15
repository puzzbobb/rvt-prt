# rvt-prt documentation

rvt-prt prints the sheets of an Autodesk Revit project to vector PDF, straight from the `.rvt`
file, without Revit. These pages are for people who use it and for people who work on it.

## Using rvt-prt

| Page | What it covers |
|---|---|
| [Installing](install.md) | What you need, compiling the extension, checking it works, updating, saving disk space |
| [Command line](usage.md) | `rvt-prt list`, `print`, `compare`, `cache` and `ifc`, with every option and the output each writes |
| [Python API](python-api.md) | `RevitModel`: opening a model, listing sheets, printing from your own code, errors |
| [Fonts, linked models and caches](configuration.md) | Where rvt-prt looks for fonts and linked models, where it keeps caches, and the environment variables |
| [Troubleshooting](troubleshooting.md) | Messages you may see and what to do about each |

## What to expect

| Page | What it covers |
|---|---|
| [Accuracy](accuracy.md) | How a print is scored against Revit's own, the current scores, and how to measure your own model |
| [Limitations](limitations.md) | What Revit draws that rvt-prt does not yet, by view type; supported Revit releases and platforms |
| [Performance and memory](performance.md) | Print times, cold and warm prints, memory needs, how heavy models are handled |

## How it works

| Page | What it covers |
|---|---|
| [How it works](how-it-works.md) | The path from the bytes of a `.rvt` to a PDF page, and which module does each step |
| [Clean-room policy](../CLEANROOM.md) | Where the project's knowledge of the format comes from, and what sources are not allowed |

## Project

| Page | What it covers |
|---|---|
| [Contributing](../CONTRIBUTING.md) | Setting up, measuring a change, rules for the code |
| [Security](../SECURITY.md) | Reporting a vulnerability; what the disk cache trusts |
| [Changelog](../CHANGELOG.md) | What each release changed |
| [How the project runs](project.md) | Purpose, decisions, how changes are judged, releases |
