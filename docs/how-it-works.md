# How it works

This page follows a print from the bytes of a `.rvt` file to a PDF page, and says which module
does each step. Read it before changing the code. The decoders' own docstrings describe the records
they read.

## The idea

A Revit project file contains more than the model. It also contains what Revit computed from the
model the last time it regenerated and saved:

- the **class and field catalog** of every record type in the file, so the file describes its own
  layout;
- each element's **record**: its parameters, placement and relations;
- each element's **saved graphics**: the curves and solids Revit last generated for it.

rvt-prt reads those three things and reproduces what Revit's print does with them: choose what
each view shows, cut and project it, remove hidden lines, apply the model's pens, and lay the
views out on the sheet. It does not regenerate anything, and it does not need Revit.

## The path of a print

```text
 model.rvt
    │
    ▼
 1. Container        core/container.py     the compound file's streams, inflated
    │
    ▼
 2. Schema           core/schema.py        the file's own catalog of classes and fields
    │                core/registry.py
    ▼
 3. Records          core/objgraph.py      each element record decoded into an object graph
    │
    ├────────────────────────────┬──────────────────────────────┐
    ▼                            ▼                              ▼
 4. Sheets and views          5. Elements                    6. Geometry
    model/                       elements/                      geometry/  +  rvt_prt._native
    sheets, viewports,           text, tags, title blocks,      meshes of walls, floors, pipes;
    view ranges, pens,           schedules, grids, families'    family graphics placed; plan
    phases, filters              saved graphics                 cuts; sections with hidden lines
    │                            │                              │
    └────────────────────────────┴──────────────────────────────┘
                                 │
                                 ▼
 7. Drawing                   render/              one page per sheet, in worker processes
                                 │
                                 ▼
 8. Output                    pdf.py, formats/     PDF, DWFx, DXF
```

### 1. The container

A `.rvt` is a Microsoft Compound File (the format of old Office documents), holding named
streams. `Formats/Latest` is the catalog, `Global/*` are document-level tables, and
`Partitions/NN` hold the element records. Most streams are stored in pages of 65,249 bytes whose
last 353 bytes are a checksum, and inside those pages the data is a series of gzip members.
`core/container.py` strips the page checksums and inflates the members. It also reads the Revit
release and build from the `BasicFileInfo` stream.

### 2. The schema

`Formats/Latest` lists every class Revit serialises in this file: its name, its base class, and
each field's name and type. `core/schema.py` and `core/registry.py` decode it. Because the
catalog comes from the file, the same code reads Revit 2014 and Revit 2027 files: a field that
moved or changed width between releases is found where that file's catalog says it is.

### 3. Records as object graphs

A partition stream is a sequence of segments, each on a numbered channel. Channel 102 carries
element records, and channel 103 carries each element's saved graphics. A record's body is an
object graph: a root object of some class, its fields laid out as the schema says (base class
first), and the objects its pointer fields refer to following in first-seen order.

`core/objgraph.py` decodes a body into objects and the edges between them. Every decoder above
this layer works on those graphs, by class and field name:

```python
for element_id, graph in objgraph.elements(path, ("Level",)):
    root = graph.objects[0]
    name = root.fields["m_text"]
```

No module above `core/` scans bytes or uses fixed offsets. That rule is what lets one decoder
read many releases.

Families loaded into a project are embedded as documents of their own inside the partitions.
`objgraph.embedded_bodies` reads them with the same framing.

### 4. Sheets, views and settings

`model/` reads what describes the drawing set and not any one element:

- `views.py` and `viewports.py`: every view (its scale, view range, crop, direction, template,
  hidden categories, detail level) and where each is placed on which sheet;
- `layout.py`: a sheet's page, its paper size from its title block, and its placed views;
- `pens.py`: the line weight table per view scale, Object Styles per category and subcategory,
  and each line style's pen, colour and pattern;
- `phases.py`, `filters.py`: which elements a view shows, by phase and by view filter;
- `levels.py`, `spaces.py`, `systems.py`: levels, rooms and spaces, MEP systems and their colours;
- `fonts.py`: the fonts the text names, and the files to draw them with.

### 5. Elements

`elements/` has a decoder per kind of element: text notes and tags (`annotations.py`), title
blocks (`titleblock.py`), schedules (`schedules.py`), grids, filled regions, fill patterns, room
tags, elevation markers and section lines (`datums.py`), stairs and railings, and images.

The most important is `savedgraphics.py`. Each family type's channel-103 record is a tree of
graphics: groups, curves (lines, arcs, ellipses) and solids (boundary representations: faces on
planes, cylinders and other surfaces, bounded by loops of edges). Nodes in the tree carry
**conditions** that gate their subtree on the view: the view direction, the detail level
(Coarse, Medium, Fine), and whether the view's cut passes through. Evaluating the tree against a
view gives exactly the graphics Revit would draw for that family type in that view. Each
instance's own record holds the transform Revit placed it with.

### 6. Geometry

Two sources of model geometry are combined.

**System elements** (walls, floors, roofs, ducts, pipes) come from
[rvt-rs](https://github.com/DrunkOnJava/rvt-rs), a Rust library that reads the same file and
builds each element's solid. It is compiled into the native extension `rvt_prt._native`
(`native/src/`), which meshes a model in-process and hands the triangles to Python.
`geometry/linkgeom.py` caches them per model.

**Family instances** (doors, furniture, fixtures, fittings) come from their saved graphics
(step 5), placed by each instance's transform.

The open model and each of its linked models is a geometry source of the same kind
(`geometry/links.py`: `Host` and `Link`). A link is the same pipeline run on another file, placed
by the link's transform and drawn halftone.

From these, per view:

- **Plans** (`linkgeom.py`): elements crossing the cut plane give the segments where they meet
  it, drawn in the heavier cut pen, and their cut faces are hatched with the material's cut
  pattern. Elements below the cut are projected. Joined walls' cut outlines are merged. Ceiling
  plans look up, and hide what lies above the floors and roofs over the cut.
- **Sections and elevations** (`sections.py`): the geometry is taken into the view's frame, cut
  at the view plane, and projected to the far clip, with hidden lines removed across all
  elements.
- **MEP in the host model** (`model2d.py`): ducts, pipes, terminals and equipment as footprints,
  in their system's colour.

### 7. Drawing a sheet

`render/` draws one page per sheet. `sheet.py` places each view on the page at its scale and
clips it to its crop. `linework.py` draws model lines in their pens and hatching. `annotate.py`
draws datums, grids, notes, tags, regions and room tags. `paper.py` draws the title block and
images, `tables.py` the schedules, and `text.py` sets text in the fonts found.

`pool.py` runs the sheets in parallel, each in a forked process under a memory cap
([Performance and memory](performance.md#the-memory-guard)). Everything a worker needs is decoded
in the main process first (`api.RevitModel._prepare`), so workers only draw.

### 8. Output

Every call into the PDF library goes through one module, `pdf.py`, the only one that imports
PyMuPDF. A sheet can also be recorded as a plain **drawing** (`formats/drawing.py`): lines, arcs
and text in sheet inches, each labelled with the element that drew it. `formats/dwfx.py` and
`formats/dxf.py` write drawings out, and read Revit's own exports into the same form, which is
what makes `rvt-prt compare` possible.

## Caching

Decoding a large model's records takes minutes, so each decoder's result is kept on disk
(`core/diskcache.py`), keyed on the model file's size and modification time and on a hash of the
decoder's own source files. Editing a decoder therefore invalidates exactly its entries, and a
stale result is never served. Note the consequence when developing: a change to `core/objgraph.py`
or `core/schema.py`, which every decoder names, makes the next print of every model cold.

A second cache works at a finer grain. For each family type and view direction,
`savedgraphics.Saved` keeps which of the type's lines its own solids hide (a *selection*). Sheet
processes write the selections they work out to the cache folder, and the printing process reads
them before it starts each sheet, so a later sheet, and a later print, does not work them out
again.

## Module map

`src/rvt_prt/` in subpackages:

| Subpackage | Holds |
|---|---|
| `core` | The file, its schema and object graphs, the disk cache |
| `model` | Sheets, views, viewports, levels, spaces, systems, filters, phases, pens, fonts |
| `elements` | Element decoders |
| `geometry` | The geometry sources (the open model and its links) and the linework drawn from them |
| `render` | The drawing engine |
| `formats` | Drawings, DWFx, DXF |
| `metrics` | Scores against Revit's prints, and the benchmarks |

| Path | Description |
|---|---|
| `cli.py` | The `rvt-prt` command: `list`, `print`, `compare`, `cache`, `ifc` |
| `api.py` | `RevitModel`, the public API: sheets, `render_to_pdf`, `render_to_dwfx`, `export_dxf` |
| `pdf.py` | Every call into PyMuPDF. The only module that imports it |
| `core/container.py` | Compound file reader, page stripping and gzip members; the Revit release and build from BasicFileInfo |
| `core/schema.py` | Class, field and tag catalog decoded from `Formats/Latest` |
| `core/registry.py` | `Formats/Latest` class registry with full field descriptors (ported from rvt-rs) |
| `core/objgraph.py` | Partition segments, channel record framing and schema-driven object graphs (ported from rvt-rs) |
| `core/diskcache.py` | Disk cache keyed on the file and on decoder source hashes |
| `core/cachedir.py` | What the cache folder holds, and clearing it (`rvt-prt cache`) |
| `core/memory.py` | Memory given back between a print's stages |
| `core/progress.py` | What a print is doing, on stderr: stages with time and memory, caches built, the sheets bar |
| `core/categories.py` | Autodesk's public BuiltInCategory ids for documentation elements |
| `core/paths.py` | Where caches go: a clone's `out/` (and its `fonts/`, `links/`, `bench/`), else the user's cache folder |
| `model/views.py` | Views, sheets, view ranges, templates, hidden categories, detail level |
| `model/viewports.py` | Viewport placement, crop boxes, view basis and origins; sections' and elevations' frames; viewport types' title settings |
| `model/layout.py` | Sheet assembly: paper sizes, placed viewports, title block labels |
| `model/sheetparams.py` | A sheet's parameters by name, and the `--where` filters that select sheets by them |
| `model/pens.py` | Line weights, Object Styles, line styles' pens, colours and patterns |
| `model/phases.py` | Which elements a view shows, by the phase they were created and demolished in |
| `model/filters.py` | View filters and their visibility rules |
| `model/systems.py` | MEP system classification and override colours |
| `model/levels.py` | Levels and their elevations |
| `model/spaces.py` | Rooms and MEP spaces, room boundaries |
| `model/fonts.py` | The fonts each text names, the files found for them, substitutes and fallbacks |
| `elements/annotations.py` | Text notes (RTF formatting, text types), tags, detail curves |
| `elements/titleblock.py` | Title block symbols, labels, and project parameters |
| `elements/schedules.py` | Schedules on sheets: cells, headers, grid lines |
| `elements/grids.py` | Grid lines, grid types, and head families |
| `elements/fills.py` | Filled regions, masking boundaries, invisible lines |
| `elements/patterns.py` | Fill patterns, line patterns, cut hatching |
| `elements/roomtags.py` | Room tags and space tags |
| `elements/datums.py` | Elevation markers and section lines in plans, level lines in sections and elevations |
| `elements/savedgraphics.py` | Family types' saved graphics: curves and solids under view, detail-level and cut conditions |
| `elements/families.py` | Embedded family documents, types, instances and their transforms |
| `elements/stairs.py` | Stair runs, treads, risers, landings, cut marks |
| `elements/gelements.py` | Each element's category and box, from the header of its saved graphics |
| `elements/images.py` | Raster images placed on sheets and in views |
| `geometry/links.py` | Geometry sources: the open model (`Host`) and its linked models (`Link`) |
| `geometry/linkgeom.py` | Meshes per model, plan cut and projection linework, wall joins, model curves |
| `geometry/sections.py` | Sections and elevations: cut at the view plane, hidden lines removed |
| `geometry/model2d.py` | The host model's MEP footprints |
| `render/` | `primitives`, `text`, `linework`, `annotate`, `paper`, `tables`, `sheet` (one page), `pool` (parallel sheet workers), `state` (what a print shares across its sheets) |
| `formats/drawing.py` | Drawings as labelled primitives; PDF reader; line-by-line and family-block comparison |
| `formats/dwfx.py` | DWFx reader and writer |
| `formats/dxf.py` | DXF reader and writer (ezdxf) |
| `formats/export.py` | A plan view's linework in model feet, family instances as blocks, for DXF |
| `metrics/` | `metrics` (ink), `blockbench` (family blocks), `textscore`, `compare` (overlays), `bench` (print-time records), `geobench` and `rvtrs` (meshing benchmarks, comparing rvt-rs revisions) |
| `native/src/` | The Rust extension: `lib.rs` (the Python module), `mesh.rs` (meshing), `ifc_names.rs` |

## Outside the package

| Path | Holds |
|---|---|
| `docs/` | This documentation |
| `bench/` | Benchmark records: print times, the version matrix, meshing and rvt-rs comparisons |
| `tests/unit/` | Tests that need no model file |
| `tests/integration/` | Tests against the test oracles and Snowdon, skipped when the files are absent |

Not in git, and present only on a development machine: `oracle/` (reference models and Revit's
exports of them), `links/` (linked models), `fonts/`, and `out/` (caches and printed sheets).
