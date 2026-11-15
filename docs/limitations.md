# Limitations

rvt-prt is not a complete Revit renderer. It draws what has been decoded and measured against
Revit's own prints, and this page lists what is known to be missing or different. If your sheets
depend on something listed here, the print will differ from Revit's there.

The list comes from the development record and is in user terms. It is not exhaustive: Revit has many features that no reference model here uses.
[Accuracy](accuracy.md) shows how to find out what differs on a model of your own.

## Supported files

| Files | Support |
|---|---|
| Revit 2019 to 2027 projects (`.rvt`) | Supported. Every such file of the test corpus prints |
| Revit 2014 to 2018 | Read by the same code, but **no file of these releases is in the test corpus**, so they are unverified |
| Revit 2012 and 2013 | Two corpus files print. System elements (walls, floors) have no geometry there, so only family instances and annotations are drawn |
| Revit 2011 and older | Not supported. The command stops with a message naming the release |
| Families (`.rfa`), templates (`.rte`) | Not printed. They have no sheets |
| Models with no sheets | Nothing to print. rvt-prt prints sheets, not single views |
| Cloud models, models on Revit Server | Only as a local `.rvt` file |

What each corpus file does is in `bench/versions.md`.

Workshared files (central and local copies) have not been tested as such. Elements are drawn
whatever their workset. Worksets hidden in a view are not taken into account.

## Views

| View type | State |
|---|---|
| Floor plans, ceiling plans | Drawn: cut at the view range's cut plane and projected. The best-measured views |
| Sections, elevations | Drawn: cut at the view plane, hidden lines removed. Heavy for whole buildings |
| Schedules on sheets | Drawn: sheet lists, element schedules, revision tables |
| Drafting views | Their detail lines, text, filled regions and images are drawn |
| 3D views | A simplified orthographic drawing of the model's own ducts and equipment only. No shading, no crop, no linked models |
| Legends | Not read as legends. Their legend components are not drawn |
| Detail and callout views | Drawn as the plan or section they are. Detail components owned by one view are drawn in every plan of the model (they should appear only in their own view) |
| Area plans | Drawn as plans. Area boundaries are left out |
| Shaded, realistic, ray-traced display | Not supported. Everything prints as hidden-line linework |

## What is not drawn, or drawn differently

### Annotation

- **Dimensions** are not drawn: linear, radial, angular and spot dimensions.
- **Text with mixed formatting**: bold or italic changing within a line is not drawn as such.
- **Section heads, level heads and elevation marker symbols** are drawn simply. The families
  Revit uses for them are not.
- **Keynotes, revision clouds, matchlines, scope boxes, reference planes**: not measured against
  any reference. Assume they are missing.
- **The Date/Time Stamp** in a title block shows the time of the rvt-prt print, as day/month/year
  whatever the machine's own format. It is drawn in its label's direction (up the sheet's edge
  in Autodesk's title blocks). A stamp longer than its box wraps where Revit prints one line.

### Model elements

- **Walls** are single solids. Compound wall layers at Medium and Fine detail are not drawn. Door
  and window openings are cut a little wider than Revit's. Wall sweeps and reveals in plan differ.
- **Sloped roofs, sloped floors and some angled walls** can come out as their bounding boxes,
  which draws wrong outlines and hides the wrong things in ceiling plans. This is the main
  reason roof plans score lowest.
- **Hidden lines in plans**: a plan hides nothing behind floors or other elements below the cut.
  A chair under a table, or a wall under a slab, is drawn where Revit hides it. Ceiling plans do
  hide what is above the floors and roofs over the cut.
- **Handrails and top rails above the cut plane** are left out. Revit draws some of them.
  Railing balusters are drawn as separate symbols.
- **Solid-fill cut patterns** are left empty. Hatched cut patterns are drawn.
- **Phases**: elements are shown or hidden by the view's phase and phase filter, but the
  filter's graphic overrides are not applied. A demolished element that the filter shows
  overridden (dashed, say) is drawn as it is.
- **View filters and visibility overrides**: categories and filters that *hide* elements are
  applied. Overrides that change an element's colour, weight or pattern in one view are applied
  for MEP systems only.
- **Linked models** are always drawn halftone. A view that sets a link to a different display
  ("By Linked View", custom) is not followed. A link's own annotations and view-specific elements
  are never drawn. Nested links are not followed.
- **Design options, groups, parts, assemblies, point clouds, imported CAD (DWG) and topography**:
  not measured against any reference. Assume they are missing or drawn as plain geometry.
- **Extensible Storage** data is not read.

### Pages

- **A sheet without a title block** prints on a page fitted to its contents. Its margin may not
  match Revit's.
- **Title block labels** print at the size of their text type, as Revit prints it. A label that
  does not read left to right is sized by a rule measured on two title blocks only (both
  Date/Time Stamps). A label whose text type is not found falls back to its box's height, which
  can be a few percent small.
- **Text of mixed style in one line** (a regular heading with an italic colon, a bold name in a
  sentence) is drawn in each run's style. Underline is not drawn.
- **Raster images** placed on sheets are drawn. Images that Revit generates at print time
  (rendered views, shaded views) are not.

## Accuracy

On the reference models, plans and ceiling plans reach 93 to 97% recall and 89 to 96% precision
against Revit's PDF, and family symbols 90% and 84% ([Accuracy](accuracy.md)). A print is good
for reading, checking and comparing. It is **not** a substitute for Revit's print where the
drawing is a contract document: check it against Revit's before you rely on it.

## Platforms

| Platform | State |
|---|---|
| Linux, 64-bit ARM (Debian-based) | Developed and tested here |
| Linux, x86-64 | Expected to work. Untested |
| macOS | Untested. Worker processes are forked, which is not safe with every system library there |
| Windows | Untested. No worker processes: sheets are drawn one at a time, with no memory guard |

There are no prebuilt packages. Installing compiles a Rust extension
([Installing](install.md)).

## Memory and time

A sheet with a section or elevation of a whole building needs 1.5 to 2 GB of its own, and large
sheet sets take minutes ([Performance and memory](performance.md)). A sheet that does not fit in
memory even alone is drawn without its section linework, or left blank, with a message.

## Input you do not trust

rvt-prt bounds what a hostile file can do: how much it may inflate to, the counts it may claim,
which files it can make the print open, and, with `--sheet-timeout` and `--memory-limit`, the
time and memory it may take. Reading the model has no time limit of its own, and the native
extension and the PDF library parse file data with their own safeguards. Print untrusted files
with both limits, in a sandbox or container. See [`SECURITY.md`](../SECURITY.md).

## Licence of a dependency

rvt-prt is Apache-2.0, but it writes PDFs with PyMuPDF, which is AGPL-3.0 unless you hold a
commercial licence from Artifex. That affects anyone who distributes a program built on
rvt-prt or offers one over a network.
