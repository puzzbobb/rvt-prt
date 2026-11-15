# How the project runs

This page describes how rvt-prt is run as a project: what it is for, who decides, how work is
chosen and judged, how releases happen, and what the project promises its users.
[`CONTRIBUTING.md`](../CONTRIBUTING.md) is the practical guide to sending a change.

## Purpose

**Print any Revit model's sheets as Revit does, from the file alone.**

Three things follow from that sentence, and they settle most arguments:

1. **Revit's own output is the measure.** A print is right when it matches what Revit prints for
   the same file. Not when it looks plausible, and not when it looks better.
2. **From the file alone.** No Revit, no Autodesk code, no service. A user needs the `.rvt` and
   its linked files, nothing else.
3. **Any model.** Behaviour comes from what a file records. No rule is tuned to one model, and a
   reference model is something to measure against, never something to fit.

What rvt-prt is not: a Revit replacement, an editor, a general converter, or an IFC tool. It
reads and prints. Features that do not serve printing sheets, or checking a print against
Revit's, are out of scope.

## Status

Version 0.1, in development, at [github.com/puzzbobb/rvt-prt](https://github.com/puzzbobb/rvt-prt).
It prints the reference models at the scores in [Accuracy](accuracy.md).

## People and decisions

rvt-prt has **one maintainer**, who owns the repository, reviews and merges every change, and
makes the releases.

- **Small decisions** are made in the pull request that needs them.
- **Decisions that change direction** (the scope, a dependency, the public interface, the
  licence, a policy) are written down before they are acted on: as an issue, and then in the
  document they change. The reasons are recorded with the decision.
- **Disagreements about what is right to draw are settled by Revit's export**, not by opinion.
  If two people disagree about how something should print, the answer is to make a small model
  that shows it and look at what Revit does.
- **Disagreements about anything else** are settled by the maintainer, who says why.

There is no steering group, no voting and no roadmap committee. If the project grows to several
regular contributors, this section will be rewritten to say how maintainers are added and how
they decide together.

## How work is chosen

Work is chosen by measurement.

1. The benches say where the print is furthest from Revit's: which sheets, which categories,
   which families ([Accuracy](accuracy.md)).
2. The largest measurable gap that can be closed generically is worked on next.
3. Someone works on it, measures the effect, and records it.

What was **tried and not kept** is recorded too, with the numbers that decided it. A change
that raises one score by less than it lowers another is usually not kept, and the record says so,
so the idea is not tried blind a second time.

Reports from users feed the same queue. A report that comes with a `rvt-prt compare` output is
acted on soonest, because it already says which elements differ.

What users can expect of an issue: an answer, and an honest one. "This is a known limitation and
nobody is working on it" is a possible answer. There is no promised response time for a project
of this size.

## How a change is judged

A change is merged when all of these hold.

| Test | Meaning |
|---|---|
| The checks pass | Lint, types, unit tests, and the two test oracles at or above their floors |
| Its effect is stated | Which scores moved, by how much, on which files. Or "output unchanged", and how that was checked |
| It is generic | Nothing in it names or is tuned to one model |
| Its sources are clean | Any format finding comes from allowed sources, and says which ([`CLEANROOM.md`](../CLEANROOM.md)) |
| It is recorded | The changelog and the limitations page are updated where they apply |

The two test oracles are small models with Revit's own exports. Each of their scores has a floor
at its current value, and the floor only moves up. They run in seconds, so they are run on every
change.

Scores on the large reference project (Snowdon Towers) are measured before a change that alters
what is printed is merged, and at every release. They are not a gate with a fixed floor, because
a correct change sometimes lowers one of them: drawing something Revit draws, but in a slightly
wrong place, costs precision until the placement is fixed. Such a change is merged when it is a
step toward the right answer, and its cost is written down.

## The records

The project keeps its reasoning in the repository, so that anyone can see why the code is as it
is.

| Record | Holds | Updated |
|---|---|---|
| [`CHANGELOG.md`](../CHANGELOG.md) | What each release changed, for users | With every user-visible change |
| Docstrings | What each decoder reads from the file, and what was observed about how Revit prints it | With every finding |
| `bench/` | Measurements: every print's time and memory, the version matrix, meshing benchmarks, comparisons of rvt-rs revisions | By the tools that measure |
| Commit messages | What the program now does, why, and the measured effect | Every commit |

The user documentation in `docs/` is the edited account.

## The clean room

rvt-prt is an independent implementation, written for interoperability. Its knowledge of the
format comes from the bytes of Revit files, from what Revit itself prints and exports, from
published open-source work, and from public specifications. It does not come from Autodesk's or
the Open Design Alliance's code, from confidential material, or from inspecting Revit's program.

[`CLEANROOM.md`](../CLEANROOM.md) is the policy. It binds every contributor, the maintainer
included, and tools used on their behalf. A finding from a forbidden source is not accepted. If
one is merged by mistake, it is reverted, and the affected code is derived again from allowed
sources by someone else.

## rvt-rs

Element meshes come from [rvt-rs](https://github.com/DrunkOnJava/rvt-rs), a separate open-source
project with its own maintainer and its own clean-room policy. The relationship is deliberately
simple:

- rvt-prt uses rvt-rs **as published**: one release of the `rvt` crate from crates.io, pinned
  exactly in `native/Cargo.toml`, with no patches.
- rvt-rs is **not changed to suit rvt-prt**. A bug or a gap in it is reported upstream. What
  rvt-prt needs differently, it adapts on its own side.
- **Moving the pin is measured** like any change: the reference models are meshed with the old
  and the new revision and compared element by element, and the result is recorded in
  `bench/rvtrs.md`.
- Parts of rvt-rs's reader were ported to Python here. They are credited in `NOTICE`, as its
  licence requires.

The longer-term direction is to read each element's solid from the geometry Revit saves in the
file, in Python, so that the Rust extension becomes optional.

## Releases

### Versions

Versions follow [Semantic Versioning](https://semver.org/). While the version is 0.x, a minor
release (0.2, 0.3) may change the public interface, and the changelog says how.

**What the version number covers**: what `import rvt_prt` exports
([Python API](python-api.md)), and the `rvt-prt` command's subcommands and options
([Command line](usage.md)).

**What it does not cover**:

- everything else in the package, including `rvt_prt.metrics` and the benches;
- **the printed output**. Getting closer to Revit's print is the point of every release, so a
  sheet may print differently from one release to the next. A change that makes output *worse*
  on the reference models is a bug;
- the cache's layout. Caches are rebuilt when they do not match the code;
- the progress text on stderr.

### How a release is made

1. The checks pass at the release commit.
2. **The accuracy record is made at that commit**: a cold and a warm print of the reference
   project, its ink scores, the family bench, and the test oracles. The numbers go into
   [Accuracy](accuracy.md), the package page and the release notes. Published scores are never
   carried over from an earlier commit.
3. The changelog is finished, and the version is set in `pyproject.toml` and
   `native/Cargo.toml`.
4. The commit is tagged `vX.Y.Z`. The packages are built from the tag, checked, published to
   TestPyPI, installed from there on a clean machine, and then published to PyPI. The
   release workflow (`.github/workflows/release.yml`) does all of this when the tag is pushed:
   an abi3 wheel for each of Linux x86_64 and aarch64 and macOS arm64 and x86_64, and the sdist.
5. A PyPI version cannot be replaced. A mistake is fixed forward, in the next patch release.

### What is supported

Only the latest release receives fixes. There are no long-term support branches.

| | Supported |
|---|---|
| Revit files | 2014 to 2027, as [Limitations](limitations.md#supported-files) details |
| Python | 3.10 and newer |
| Platforms | Linux. macOS and Windows are untested |

A new Revit release each year may change record layouts. Supporting it means adding its sample
projects to the corpus and printing them. Until that is done for a release, files from it are
unverified.

## Dependencies and licences

rvt-prt is licensed under the Apache License 2.0. Contributions are accepted under the same
licence, with no contributor agreement.

Dependencies are kept few, and each must have a licence compatible with distributing rvt-prt
under Apache-2.0. One needs care: **PyMuPDF**, which writes the PDF pages, is AGPL-3.0 unless a
commercial licence is held. rvt-prt's own code stays Apache-2.0, but a program that combines
the two is bound by the AGPL when distributed or offered over a network. This is stated wherever
the licence is. All use of PyMuPDF is confined to one module (`pdf.py`), so that it can be
replaced by a permissively licensed library.

A new dependency is a decision that changes direction, and is discussed first.

## Trademarks and affiliation

rvt-prt is not affiliated with, endorsed by or sponsored by Autodesk. "Autodesk" and "Revit"
are Autodesk's trademarks, used here only to name the file format. Autodesk's sample projects,
used for testing, are not redistributed.

## Security

rvt-prt reads files that may come from anyone. Vulnerabilities are reported privately and
fixed in the next release ([`SECURITY.md`](../SECURITY.md)). The code has not yet been hardened
against hostile files, and says so ([Limitations](limitations.md#input-you-do-not-trust)).

## Conduct

Be civil, be specific, and argue from evidence. People who report problems are doing the project
a favour, and are treated that way. Harassment and personal attacks are not accepted, in issues,
pull requests or anywhere else the project works.
