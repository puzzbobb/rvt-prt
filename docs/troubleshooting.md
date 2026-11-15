# Troubleshooting

Problems while installing are in [Installing](install.md#if-the-install-fails). This page covers
what you may see when printing.

## Messages that stop the command

Each of these is one line on stderr, with exit status 1.

| Message | What it means |
|---|---|
| `no such file: X` | The path does not name a file |
| `X is not a Revit file (it is not an OLE compound file)` | The file is something else: a PDF, a text file, a `.zip` |
| `X is not a Revit file (it has no BasicFileInfo stream)` | A compound file, but not Revit's: an old Office document, for example |
| `X cannot be read: it is damaged or incomplete (...)` | The file is cut short or corrupt. A download or copy that did not finish is the usual cause |
| `X cannot be read: its class catalog (Formats/Latest) is damaged or not as Revit writes it (...)`, or `its element records (Partitions)` | The container opens, but what is inside does not read as a Revit file's. The file is corrupt, or was not written by Revit |
| `it inflates to more than N MB, 40 times its size or more: not a file Revit wrote` | A decompression bomb, or a file damaged into looking like one. Refused |
| `could not print X: ...Error: ... (the file may be damaged; set RVT_PRT_DEBUG=1 for the traceback)` | Something in the file led to an error no other message covers. If the file is a sound Revit file, this is a bug: please report it with the traceback |
| `X is from Revit 2011: rvt-prt reads the sheets of Revit 2014-2027 files only` | The file is from an older release. Open and save it in a newer Revit, if you can. When the file records no release, the message gives its build date instead |
| `no sheets to print in X` | The model has no sheets, or none with the numbers given to `--sheet`. `rvt-prt list X` shows what it has |

## Messages while a print goes on

**`warning: linked model X not found ...`**
The model links X, and X was not found beside the model, in `links/` beside it, or in
`RVT_PRT_LINKS`. Its elements are left out of every sheet. If the sheets look half empty, this
is usually why: in many projects most of the building is in linked models. Put the linked files
beside the model, or name their folder in `RVT_PRT_LINKS`
([Linked models](configuration.md#linked-models)).

**`building the ... cache of X (once per file or decoder change)`** and **`meshing X`**
A first print of a model, or the first after an update or after the model was saved again. This
takes minutes for a large model with links, and happens once.

**`sheet X failed in a render worker (MemoryError ...); trying it again 2 at a time`**
The sheet outgrew its share of memory. It is drawn again with fewer sheets at once, so with more
memory. The print goes on, and the sheet is complete in the output.

**`drawing it without its section and elevation linework`** or **`leaving its page blank`**
The sheet did not fit in memory even drawn alone. Free some memory (close other programs) and
print that sheet on its own: `rvt-prt print model.rvt --sheet X -j 1`. See
[Performance and memory](performance.md#memory).

**`X is Revit 2013: no IFC geometry for this version (rvt-rs reads 2014-2027); its family instances are drawn from their saved graphics`**
The file is older than the releases rvt-rs reads geometry from. Walls, floors and other system
elements are missing, and family instances are drawn from their saved graphics only.

## The print looks wrong

**Text is slightly wider, narrower or differently shaped than in Revit's PDF.**
The font the model names is not installed, and a substitute is drawn. Install Arial or
Liberation Sans ([Fonts](configuration.md#fonts)).

**Squares or missing characters in Japanese, Chinese or Korean text.**
This should not happen: such text falls back to a CJK font that is always available. Please
report it, with the text if you can share it.

**Elements are missing, or are drawn that Revit hides.**
rvt-prt is not a complete Revit renderer. [Limitations](limitations.md) lists what it does not
draw yet. To see exactly what differs, export the same sheet from Revit as DXF or DWFx and run
`rvt-prt compare` ([Accuracy](accuracy.md#measuring-your-own-model)). An accuracy report with
that comparison is the most useful kind of bug report.

**A sheet's page is the wrong size.**
A sheet without a title block prints on a page fitted to its contents, which may not be the
paper size Revit would use.

## The print is slow

- **The first print of a model is slow by design.** Later ones reuse its caches. Check with
  `rvt-prt cache` that the model has entries.
- **Every print is cold.** Something changes between prints: the model file's modification time
  (a sync tool that rewrites it), or two models with the same file name sharing cache entries
  ([Caches](configuration.md#caches)).
- **Sheets are drawn one or two at a time.** That is the memory guard, on a machine short of free
  memory. The bar shows how many are being drawn and the memory free.
- **The extension was built in debug mode.** A hand build without `--release` is 10 to 50 times
  slower. Reinstall with `pip install -e .`.

## Seeing what a print is doing

`rvt-prt print` reports each stage on stderr as it starts, with the seconds since it began and
the memory the process holds:

```text
[ 35.1 s  0.4 GB] model 2/7: ...
```

It also reports each cache it builds, then shows a bar while the sheets are drawn. Piped to a
file, the bar becomes a line per sheet. `-q` turns all of it off.

## Reporting a problem

Say which rvt-prt version (`rvt-prt --version`), which Revit release saved the file, your
operating system, and the full message. For a print that differs from Revit's, a screenshot of
both, or the `rvt-prt compare` report, is what helps most.

Do not attach a model unless you are sure you may share it. Client files are usually
confidential, and a description is often enough.
