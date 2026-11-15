# Contributing

Thank you for helping. rvt-prt prints Revit sheets from the `.rvt` file, and every change is
judged by one question: **does the print come closer to Revit's own?**

This guide covers how to contribute. [How the project runs](docs/project.md) covers how
decisions are made, how releases happen and what the project promises.

| Section | For |
|---|---|
| [Ways to help](#ways-to-help) | Everyone |
| [Reporting a problem](#reporting-a-problem) | Users |
| [Setting up](#setting-up) | Anyone changing code or documents |
| [The checks](#the-checks) | What must pass before a change is merged |
| [Measuring a change](#measuring-a-change) | Changes that alter what is printed |
| [Rules for the code](#rules-for-the-code) | |
| [Adding a decoder](#adding-a-decoder-a-walk-through) | Reading something new from the file |
| [Where format knowledge comes from](#where-format-knowledge-comes-from) | Required reading before any format finding |
| [Documents](#documents) | Which file to update |
| [Commits and pull requests](#commits-and-pull-requests) | |
| [Test files](#test-files) | What may and may not be shared |
| [rvt-rs](#rvt-rs) | Changes that belong upstream |

## Ways to help

You do not need to write code.

- **Report what differs from Revit.** Print a sheet, export the same sheet from Revit, run
  `rvt-prt compare`, and send the report. This is the most valuable contribution, because it
  says exactly which elements are wrong.
- **Try it on a file from a release or discipline the corpus lacks.** No Revit 2014 to 2018
  project is in the test corpus. Structural, electrical and landscape models are thin.
- **Make a small test model.** A model with one feature (one dimension, one legend, one compound
  wall) and Revit's own PDF, DXF and DWFx of its sheet isolates that feature far better than a
  large project. See [Test files](#test-files) for what makes one usable.
- **Try a platform.** macOS and Windows are untested.
- **Improve the documentation.**
- **Fix something** from [Limitations](docs/limitations.md).

For anything larger than a small fix, open an issue first and say what you plan. It avoids two
people doing the same work, and some approaches have already been tried and set aside, with the
scores that decided it.

## Reporting a problem

**A print that differs from Revit's** is an ordinary issue. Include:

- `rvt-prt --version`, your operating system, and the Revit release that saved the file;
- what differs: a screenshot of both prints side by side, or better, the output of
  `rvt-prt compare REVIT_EXPORT OUR_PRINT` ([how](docs/accuracy.md#measuring-your-own-model));
- the model only if you are sure you may share it. Never attach a client's model. A small model
  you made yourself that shows the same problem is ideal.

**A crash or a traceback**: the full output, and the command you ran.

**A security problem** (a file that makes rvt-prt hang, exhaust memory, write outside its
output, or run code): report it privately. See [`SECURITY.md`](SECURITY.md).

## Setting up

You need Python 3.10 or newer, git, and Rust 1.87 or newer ([rustup](https://rustup.rs)) with a C
toolchain. The first install compiles rvt-rs: about 5 minutes on a small ARM board (4 cores, 8 GB), less on a
desktop. [Installing](docs/install.md) has the details for each system.

```bash
git clone https://github.com/puzzbobb/rvt-prt.git
cd rvt-prt
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/unit      # needs no model files: seconds
```

What you have after that:

| Path | What it is |
|---|---|
| `src/rvt_prt/` | The package. [How it works](docs/how-it-works.md) maps it |
| `native/src/` | The Rust extension that calls rvt-rs |
| `native/Cargo.toml` | The extension's dependencies, rvt-rs among them: the `rvt` crate, pinned to one release (`rvt = "=0.24.0"`) |
| `tests/unit/` | Tests on synthetic data |
| `tests/integration/` | Tests on real models, skipped when the files are absent |
| `docs/` | Documentation |
| `bench/` | Benchmark records |
| `out/` | Created by prints: caches and printed sheets. Not in git |
| `oracle/`, `links/`, `fonts/` | Reference models, linked models and font files. Not in git, and yours to supply |

After changing anything under `native/`, rebuild the extension: `.venv/bin/pip install -e .`,
or `maturin develop --release`. Always build in release mode. A debug build is 10 to 50 times
slower.

### Reference models

The unit tests need nothing. The integration tests and the benches need models:

- **The two test oracles**, `testfamily` and `test02`: small models with Revit's exports of one
  sheet each. They are the regression gate (`pytest -m oracle`). They are not in the
  repository: the gate runs on the maintainer's machine, and its result is stated in the pull request by whoever can run it.
- **Autodesk's Snowdon Towers sample project** and Revit's exports of its HVAC sheets. Autodesk
  distributes the sample with Revit. It is not redistributed here.

Put them under `oracle/` as [Accuracy](docs/accuracy.md#the-test-oracles) describes.

## The checks

Run these before sending a change. All must pass.

```bash
.venv/bin/ruff check src tests     # lint
.venv/bin/mypy                     # types
.venv/bin/pytest tests/unit        # unit tests
.venv/bin/pytest -m oracle         # the two test oracles, if you have them
```

`pytest` alone also runs the Snowdon integration tests when the Snowdon files are present. Those
print a whole sheet set and take minutes.

The lint rule set is deliberately small (pyflakes, the pycodestyle errors, bugbear): it finds
mistakes and does not police style. The settings are in `pyproject.toml`.

A new behaviour needs a test. If it can be shown on synthetic data, add a unit test. If it needs
a real file, add it to the integration tests with a skip when the file is absent.

## Measuring a change

Accuracy is measured against Revit's own exports of the same file, never by eye alone.
[Accuracy](docs/accuracy.md) explains the measures. In short:

| Check | Command | When |
|---|---|---|
| Test oracles | `pytest -m oracle` | After any change to a decoder or the renderer. Seconds |
| One sheet, by element | `rvt-prt compare REVIT_EXPORT OUR_PRINT` | While working on something |
| Whole set, ink | `python -m rvt_prt.metrics.metrics out/sheets.pdf oracle/snowdon_hvac 50 2 ink` | Before sending a change that alters what is printed |
| Family symbols | `python -m rvt_prt.metrics.blockbench MODEL REVIT_DXF_DIR` | The same |

**A change that alters what is printed states its effect**: which scores moved, by how much, on
which files. A change that raises one score and lowers another says so. "Scores unchanged" is a
valid and common effect, and is stated too.

The oracle gates have floors at their current scores. A change that lowers one must either be
fixed or argue, with evidence from Revit's export, that the floor was wrong.

**Record what did not work.** If you try an approach and the scores say no, write down what you
tried and the numbers, in the pull request. The next person will have
the same idea.

### Things to know when measuring

- **Editing a decoder makes the next print cold.** Disk caches are keyed on the source of the
  decoders that built them. A change to `core/objgraph.py`, `core/schema.py`,
  `core/registry.py` or `core/container.py` invalidates every cache of every model.
- **Heavy prints need memory.** A cold print of a large model with links can take several GB.
  On a small machine, close other programs first, and prefer the two test oracles while
  iterating.
- **Compare like with like.** A cold and a warm print draw the same pages. If they do not, that
  is a bug.
- **Every print in a clone is logged** to `bench/prints.local.jsonl`, which git ignores. To
  add the record of the change you are sending to the committed log, `bench/prints.jsonl`,
  print with `RVT_PRT_BENCH_RECORD=1`.

## Rules for the code

1. **No rules for one model.** Nothing may name a family, material, view, sheet or heading of a
   particular model, or use a constant tuned to one. Behaviour comes from what the file records.
   Snowdon Towers is a reference to measure against, never a thing to fit. If a number has to be
   chosen from a benchmark, say so in a comment and name it in the pull request, so it can be
   reviewed against the next reference model.
2. **Records from the object graph.** Read a record through `core/objgraph.py` and the file's
   own class catalog, by class and field name. Do not scan bytes or use fixed offsets above
   `core/`. Offsets differ between Revit releases, and names mostly do not.
3. **Fail in one line.** A file that cannot be printed raises `UnsupportedFile` with a message
   a user can act on. Something a view needs that cannot be read is left out with a warning.
   Neither is a traceback.
4. **One PDF module.** Only `pdf.py` imports PyMuPDF. Everything else calls `pdf.py`.
5. **Nothing heavy in a render worker.** Whatever a sheet needs from the model is decoded in the
   main process before the workers fork (`api.RevitModel._prepare`).
6. **Match the surrounding code**: its naming, its comment density, its idiom. Comments say why,
   and name the evidence ("Revit's DXF of M101 holds ..."), not what the next line does.
7. **Public API changes are deliberate.** What `import rvt_prt` exports and the command line's
   options are the public surface ([Python API](docs/python-api.md)). Changing either needs a
   line in the changelog.

## Adding a decoder: a walk-through

Suppose a view needs something the code does not read yet.

1. **Find the record.** Decide which class holds it. A file's own catalog lists its classes and
   fields (`core/registry.py`), and `objgraph.elements(path, ("ClassName",))`
   gives every record of a class as an object graph you can print and read.
2. **Find the meaning.** Make or find a model where the thing varies, export the sheet from
   Revit as DXF, and see which field changes with what Revit drew. Revit's DXF names the element
   behind every line, which ties a field to its effect.
3. **Write the reader** in the module for that kind of element, in the house idiom:

   ```python
   MODULES = ("levels", "objgraph", "registry", "schema", "container")  # what the result depends on

   def read(rf, path):
       """{level name: elevation in feet} for every Level in the model."""
       return diskcache.cached(path, "levels", MODULES, lambda: _read(path))

   def _read(path):
       out = {}
       for _eid, g in objgraph.elements(path, ("Level",)):
           name = g.objects[0].fields.get("m_text")
           plane = next((o.fields for o in g.objects if o.name == "Plane"), None)
           if name and plane:
               out[name] = plane["m_origin"][2]
       return out
   ```

   Name every module the result depends on in the cache call, so that editing any of them
   rebuilds it. Use `.get` for fields: older releases may lack one.
4. **Read it in the main process**, in `api.RevitModel._prepare`, under a timed stage, and pass
   it to the renderer. If a first print's cache workers should build it too, add it to
   `api._model_caches`.
5. **Draw it** in the matching `render/` module, in the pen and colour the model gives.
6. **Measure**, as above, and add a test.
7. **Write it down**: the finding in the decoder's docstring, with the files it was observed in; and the user-visible result in
   `CHANGELOG.md`. If it closes a limitation, update `docs/limitations.md`.

## Where format knowledge comes from

Read [`CLEANROOM.md`](CLEANROOM.md) before adding or changing a format finding: a decoded field,
record or class, or its meaning.

**Allowed**: the bytes of Revit files; what Revit itself prints, exports and reports for a file;
published open-source work under a compatible licence, cited; public specifications; Autodesk's
public documentation of what features do.

**Not allowed**: Autodesk or Open Design Alliance source or SDK internals; leaked or NDA
material; decompiled or disassembled Revit code; a debugger, hook or memory reader on a running
Revit; code copied from GPL, LGPL or AGPL projects.

A pull request with a format finding states its sources in its description:

> These findings come from [file bytes of ..., Revit's DXF export of ..., rvt-rs ...]. I have not
> used Autodesk or ODA source, leaked or NDA material, decompiled Revit code, or a debugger on
> Revit.

If you have had access to a forbidden source (you have worked with the ODA's BIM SDK under its
licence, say), do not contribute format findings in the area you saw. Rendering, tests, tooling
and documentation are still open to you.

Routine changes need no declaration.

## Documents

| If you change | Update |
|---|---|
| What a command or the API does | `docs/usage.md` or `docs/python-api.md`, and `CHANGELOG.md` |
| What is drawn | `CHANGELOG.md`; `docs/limitations.md` if a limitation closes or opens |
| A score | `docs/accuracy.md` at a release. Between releases the record is the commit message and `bench/` |
| A format finding, or how Revit prints something | The docstring of the decoder or drawing function it concerns |
| A module's job, or a new module | `docs/how-it-works.md` |
| An install step, a dependency | `docs/install.md`, `pyproject.toml`, `NOTICE` |

Documentation is written plainly: short sentences, the reader's terms, exact numbers with their
date, and no claim that was not measured.

## Commits and pull requests

**Commit subject**: one sentence saying what the program now does, in the present tense, with
the area first when it helps.

```text
Sections and elevations leave out levels when the view hides the Levels category
DXF reader keeps one of Revit's identical repeated INSERTs
Plan: rails above the cut tried, not kept
```

**Commit body**: why, on what evidence, and the measured effect.

```text
Golden Nugget's ARCH-LPH 4-01 drew up to 100 level lines per view, sheets wide,
in views that all hide Levels. Snowdon ink and the test oracles unchanged.
```

One change per commit. A commit that changes what is printed and a commit that tidies are
separate commits.

**A pull request** says:

- what it changes and why;
- the measured effect, or "output unchanged" and how that was checked;
- which checks were run, and which could not be (no oracle files, say);
- the source declaration, if it holds a format finding.

Whatever tools you use to write a change, you are responsible for what
you send: that you understand it, that it was measured, and that its format knowledge comes only
from allowed sources.

## Test files

- **Never commit a Revit model or export you do not have the right to share.** Autodesk's sample
  projects are used locally and are not redistributed.
- **A test model for the repository** must be your own work from an empty template, and must not
  contain Autodesk's content: its title block families, its sample families, its logo. Draw your
  own title block. Include Revit's PDF, DXF and DWFx of each sheet, and say which Revit release
  made them.
- **Keep it small**: one feature per model, one sheet, a few elements.
- **In an issue**, describe the problem or share a screenshot. Never attach a client's model.

## rvt-rs

[rvt-rs](https://github.com/DrunkOnJava/rvt-rs) is a separate project with its own maintainer.
rvt-prt uses it as published.

- A bug or a missing feature in rvt-rs is reported and fixed **in rvt-rs**. This repository
  carries no patches to it.
- What rvt-prt needs differently is adapted on this side: in `native/src/`, or in the Python
  decoders.
- `native/Cargo.toml` pins one rvt-rs release from crates.io, exactly (`rvt = "=0.24.0"`):
  rvt-rs is 0.x, and a minor release may change the API the extension uses. Moving the pin is a
  change like any other, and is measured: `python -m rvt_prt.metrics.rvtrs all pinned 0.25.0`
  meshes the reference models with both releases and compares them element by element
  (`bench/rvtrs.md`). An unreleased rvt-rs commit can be measured the same way (`... all pinned
  main`), but the pin moves only to a release.
  With the pin, refresh `native/NOTICE-rvt-rs` from the new release's `NOTICE`.

## Licence

Contributions are accepted under the Apache License 2.0, the project's licence: what you send is
licensed as the project is (inbound = outbound). You keep your copyright. There is no
contributor licence agreement.
