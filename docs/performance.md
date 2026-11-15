# Performance and memory

All figures on this page are from the development machine: a small ARM64 single-board computer
with 4 cores and 8 GB. A desktop is several times faster. Every print in a clone is recorded in `bench/prints.jsonl`.

## Cold and warm prints

A print has two parts: reading the model, and drawing the sheets.

- A **cold** print is the first print of a model, or the first after the model was saved again or
  an update changed a decoder. It meshes the model and each linked model and builds their caches.
- A **warm** print reads the caches and spends nearly all its time drawing.

| Model | Sheets | Cold | Warm |
|---|---:|---:|---:|
| Snowdon Towers Sample HVAC (6 linked models) | 18 | 130 to 150 s | 17 s |
| `test02` (a room, one sheet) | 1 | 5 s | 1 s |

Heavy models, warm, default jobs (2026-10-17, `bench/versions.md`):

| Model | Sheets | Time |
|---|---:|---:|
| Snowdon Architectural | 55 | 370 s |
| model b35787 | 22 | 518 s |
| model fc817f | 40 | 768 s |
| Autodesk structure sample (basic), 2027 | 8 | 48 s |

Where the time goes on a warm print: the three or four heaviest plans take 11 to 12 s each and
bound the whole print, since sheets are drawn in parallel. In sections and elevations of a whole
building, removing hidden lines is the largest part.

## What makes it fast

- **Disk caches** per model and decoder, keyed on the file's size and modification time and on
  the decoder's source ([Caches](configuration.md#caches)).
- **Hidden lines of family types kept between prints.** Which lines of a family type its own
  solids hide depends on the type and the view direction, not on the sheet. It was over half of
  the time the heaviest plans took to draw. Each sheet's process now keeps what it works out,
  later sheets of the same print reuse it, and so does every later print (2026-11-10: drawing
  Snowdon's 18 sheets 32.4 s to 23.1 s on a reprint, 33.5 s to 30.2 s on a first print, the
  pages identical).
- **Sheets drawn in parallel**, each in a process of its own (`-j`, default the CPU count),
  heaviest first, by how long each took last time.
- **A cold print builds several models' caches at once**, each in a process of its own, largest
  first, as many as the cores allow and their estimated memory fits in what is free
  (`--geometry-jobs`). Meanwhile the printing process reads the model's own sheets and
  annotations.
- **Each page finished where it is drawn.** A sheet's process subsets its page's fonts and
  compresses it, and the printing process only joins the pages. Finishing all 18 of Snowdon's
  in the printing process took 6.3 s on one core; joining them takes 1.2 s. The file is 5%
  larger, because each page carries its own subset of a font.
- **A warm print does no cold print's housekeeping.** Memory is handed back to the system only
  after something was decoded, and the decoders' source is hashed once a print (Snowdon's
  reading: 5.2 s to 3.9 s).
- **Each plan view's linework kept between prints.** What a plan view shows of a model
  depends on the model, its placement and the view's range, detail level, phase and what it
  hides, not on the sheet or the output format. It was over half of a heavy plan sheet's time.
  It is kept on disk (`<model>.views` in the cache folder, 96 MB for Snowdon's 18 sheets) and
  read by later prints, PDF, DWFx and DXF alike, until a model or the code changes (Snowdon,
  reprinted: drawing 25 s to 12 s; the heaviest sheet 12 s to 4 s).
- **A plan walks only what reaches its crop.** Elements whose plan box lies more than 3 ft
  outside a plan's crop are not walked (they would be clipped away; a ceiling plan still hides
  lines behind the whole model's floors). On Snowdon 58% of the elements walked lay outside;
  a first print's drawing went from 37 s to 28 s. On a project of many linked models spread
  over a site, most of each model is outside any one view.
- **Saved graphics read as a few large arrays.** Each model's family graphics are kept as one
  array of points and one of mesh vertices and faces, split into views when read, not as
  hundreds of thousands of small arrays (Snowdon: reading them 2.75 s to 1.1 s on a reprint).
- **Sheet processes start together when memory allows.** Each sheet's process may start at
  once if there is room for it to grow as it did when last drawn (2 GB for a sheet not drawn
  before); otherwise they start a second apart. Sheets of two or three seconds each, a second
  apart, kept four cores to two and a half.
- **The largest model's saved graphics decoded on several cores**, on machines with six cores
  or more: its symbols are shared out among helper processes (half the cores, six at most).
  It is the longest single job of a cold print. By itself, Snowdon Architectural's went from
  33 s to 16 s in four processes. On four cores it is not used: they are all busy with the
  other models, and it made nothing faster.
- **Meshing in Rust.** Element meshes come from rvt-rs, compiled into the extension and run
  in-process on a thread that releases Python's lock.

## Memory

| Situation | What it needs |
|---|---|
| Warm print | About 1 GB, plus each sheet's own. Snowdon HVAC's 18 sheets: 0.6 GB in the main process |
| A sheet with a section or elevation of a whole building | 1.5 to 2 GB of its own |
| Cold print, 8 GB machine | Three or four models' caches built at once. The largest worker (Snowdon's Architectural link) peaks at about 2.3 GB, the printing process at 0.8 GB |
| Cold print, 4 GB machine | Caches built one at a time. About 3 GB free is needed for the largest |

4 GB works and 8 GB is recommended. With less memory, fewer sheets are drawn at once and the
print takes longer. The pages are the same.

### Many linked models

While the sheets are drawn, the printing process holds the geometry of every model they show,
and each sheet's process shares it. Snowdon's seven models take 0.36 GB; fifty can take more
memory than the machine has. When the models together would take more than half the free memory
(`RVT_PRT_MODELS_GB` sets the limit), the sheets are drawn in groups instead:

1. Where each model lies is read first, and each sheet's plans, sections and elevations are
   checked against it: a sheet shows the models its views' crops reach.
2. Sheets showing the same models are grouped, so that each group's models fit the limit. A
   sheet whose models are all loaded already joins the group whatever the limit, as it costs no
   memory.
3. Each group's models are loaded, its sheets drawn, and the models the next group does not show
   dropped. The pages are joined in sheet order at the end.

A model is loaded again for each group that shows it, so this is slower than holding them all, a
little where most sheets show most models (Snowdon, forced into groups: 19 s against 17) and much
less than loading the models for each sheet. On a simulated campus of 50 models (13.7 GB) and
1,000 sheets showing one to four each, a 3 GB limit gave 18 groups and 137 model loads, against
2,329 loads for one sheet at a time. The pages are the same either way.

How much memory a model takes is noted each time it is loaded (in the cache folder), and the
next print plans with that; before then it is taken as 2.5 times its caches' size on disk.

### The memory guard

A heavy sheet can need more memory than the machine has, and a machine that runs out of memory
can freeze or restart. rvt-prt guards against that on Linux and macOS:

1. Each sheet is drawn in a process of its own, with its address space capped at its share of
   the memory that is free.
2. The machine's free memory is watched while the sheets are drawn. Sheet processes start one a
   second, not all at once.
3. A sheet that runs short is drawn again with fewer sheets at once, then alone.
4. If it still does not fit, it is drawn without the model linework of its sections and
   elevations, and a message says so.
5. Only then is its page left blank, with a message. A sheet is never drawn unguarded.

The same applies to the cache-building workers of a cold print: each is capped, and a model
whose worker fails is built in the printing process instead.

The printing process itself is not capped.

On Windows there are no forked workers. Sheets are drawn one at a time in the calling process,
with no guard.

### What keeps heavy sections affordable

In a section or elevation, every line must be tested against every face that could hide it. For
Snowdon Towers' south elevation that is 3.1 million lines and 13 million triangles before
anything is done about it. rvt-prt leaves out what cannot matter before testing: elements,
lines and triangles outside the view's crop, elements wholly hidden behind nearer faces, and the
back faces of closed solids. That leaves 0.3 million lines and 1.4 million triangles.

## Tuning

| You want | Do this |
|---|---|
| A faster print on a machine with memory to spare | Nothing. The defaults use every core |
| To keep the machine usable while printing | `-j 2`, or fewer |
| A cold print on a 4 GB machine | `--geometry-jobs 1`, and close other programs |
| One heavy sheet that failed | `--sheet X -j 1`, so it has all the memory |
| No progress output | `-q` |

## History

Snowdon HVAC, warm, 18 sheets: 1,277 s and 3.5 GB at first, then 415 s, 78 s, 21 s (before
sections, hidden lines and the model's own families were drawn), 52.6 s with whole-building
sections and per-sheet memory caps (2026-10-18), 32 s (2026-10-24), and 28 s now, 23 s of it drawing
(2026-11-10; 37 s, 32 s of it drawing, measured the same day before the change).

With rvt-rs v0.23.0 (2026-11-14), which meshes round ducts round (Snowdon HVAC: 31,000
triangles to 115,000): 38 s warm, then 30 s with pages finished in their sheets' processes and
no housekeeping on a warm print, then 17 to 18 s with each plan view's linework kept and the
sheets started by what they need, then 16.8 s with saved graphics read as joined arrays. Its
peak in the printing process fell from 1.2 GB to 0.67 GB. A first print takes 6 to 11 s more
since elements demolished before the last phase are meshed too (one more export of Snowdon's
Facades link).

Cold: about 553 s, then 193 s (2026-10-24: each model's caches in a process of its own), then
110 to 116 s (2026-10-25), 132 s with rvt-rs v0.10.0-4, whose meshing is slower, and 130 to
137 s with v0.23.0.

At release 0.1.0 (2026-11-15, rvt-rs 0.24.0): 126 s cold into an empty cache, then 20 s warm.

## Benchmarks

```bash
python -m rvt_prt.metrics.geobench backends --repeat 3     # the mesher, on Snowdon's 7 models
python -m rvt_prt.metrics.geobench scaling --jobs 1,2,3,4  # --geometry-jobs into an empty cache
python -m rvt_prt.metrics.geobench versions --corpus DIR   # one project per year folder
python -m rvt_prt.metrics.geobench summary                 # bench/geometry.md from bench/geometry.jsonl
```

Each measurement runs in a fresh process under an address-space cap (`--cap`, 5.5 GB) and records
stage times, the peak memory of the process and its children, and the machine's peak use, in
`bench/geometry.jsonl`. `bench/geometry.md` has the tables of the latest runs, and
`bench/rvtrs.md` compares rvt-rs revisions element by element.
