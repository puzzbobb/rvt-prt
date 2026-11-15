# Fonts, linked models and caches

rvt-prt needs no configuration file. It reads three things from its surroundings: font files,
linked models, and a cache folder. A few environment variables change where it looks.

## Environment variables

| Variable | Meaning | Default |
|---|---|---|
| `RVT_PRT_FONTS` | Extra folders of font files, searched first. Several folders are separated by `:` (`;` on Windows) | none |
| `RVT_PRT_LINKS` | One folder in which linked models are looked for | none |
| `RVT_PRT_CACHE` | The cache folder | `out/` in a clone, else the user's cache folder (below) |
| `RVT_PRT_SHEET_TIMEOUT` | Seconds a sheet may take to draw before it is stopped (`--sheet-timeout`) | no limit |
| `RVT_PRT_DEBUG` | Set to `1` to see a traceback where the command would print one line | off |
| `RVT_PRT_MODELS_GB` | The memory the models of a print may take together. Over it, the sheets are drawn in groups, each with only the models its sheets show (see [Performance](performance.md#many-linked-models)) | half the free memory, less a reserve |
| `RVT_PRT_GEOMETRY_JOBS` | Models and links whose caches are built at once on a first print. `0` means as many as cores and free memory allow, `1` one at a time | `0` |

Two more, `RVT_PRT_CORPUS` and `RVT_PRT_CMP`, are read only by the benchmark tools in
`rvt_prt.metrics` (a folder of test files, and a working folder for comparing rvt-rs builds).

## Fonts

A `.rvt` names its fonts but holds none. rvt-prt draws text with font files on your machine.

**Where it looks**, in order, the first folder that has a family winning:

1. the folders in `RVT_PRT_FONTS`;
2. in a clone, the clone's own `fonts/` folder;
3. your user font folders, then the system's:
   - Linux: `~/.local/share/fonts`, `~/.fonts`, `/usr/local/share/fonts`, `/usr/share/fonts`;
   - macOS: `~/Library/Fonts`, `/Library/Fonts`, `/System/Library/Fonts`;
   - Windows: your user fonts folder, then `C:\Windows\Fonts`.

It reads `.ttf`, `.otf` and `.ttc` files. The first time, it reads every font file's name and
keeps an index (`fonts.json` in the cache folder), so later prints start quickly.

**What it draws with**, for each font a model names:

1. that font, if a file for it is found;
2. else a free substitute with the same character widths, so text wraps and fits as in Revit:

   | Named font | Substitutes tried |
   |---|---|
   | Arial, Helvetica | Liberation Sans, Arimo |
   | Arial Narrow | Liberation Sans Narrow |
   | Times New Roman | Liberation Serif, Tinos |
   | Courier New | Liberation Mono, Cousine |

3. else Arial or its substitutes;
4. else PyMuPDF's built-in Helvetica, which needs nothing installed.

Text that the chosen font has no glyphs for (Japanese in a note set in Arial, for example) is set
in Noto Sans CJK JP, Source Han Sans JP or Noto Sans JP if one is installed, else in PyMuPDF's
built-in CJK font. Such text therefore always prints.

**Recommended on Linux:**

```bash
sudo apt install fonts-liberation fonts-noto-cjk
```

Most Revit text is Arial. Arial itself comes with Windows, or on Debian from
`ttf-mscorefonts-installer` (the contrib section). Models also commonly use Arial Narrow and
Trebuchet MS. Copy the files into a folder and name it in `RVT_PRT_FONTS` if they are not
installed system-wide.

DWFx output needs a font file for its Latin text, so it needs Arial or Liberation Sans installed.
PDF output does not.

## Linked models

A Revit model can link other models, and its views show them. The host file records each link's
file name and where it is placed, but not the linked model's contents. rvt-prt reads each
linked file and draws it through the same pipeline as the model itself. Links print halftone,
as Revit prints them by default.

**Where a linked file is looked for**, by its file name, in order:

1. the folder the model is in;
2. a `links/` folder beside the model;
3. the folder `RVT_PRT_LINKS` names;
4. in a clone, the clone's own `links/` folder.

A linked model that is not found is left out, and the print goes on. A warning names the file,
its link instances and the folders searched:

```text
rvt-prt: warning: linked model Arch.rvt not found (link instance 'Architecture'); its elements
are left out of the sheets. Looked in: /models, /models/links; or set RVT_PRT_LINKS to its folder
```

The path Revit recorded for the link (often a path on the author's network) is not used. Only
the file name is.

## Caches

Reading a large model takes minutes, so rvt-prt keeps what it decodes. A first print of a model
is "cold" and builds the caches. Later prints are "warm" and read them.

**Where they are:**

| How rvt-prt is installed | Cache folder |
|---|---|
| From a clone (`pip install -e .`) | `out/` in the clone |
| Otherwise, Linux | `$XDG_CACHE_HOME/rvt-prt`, else `~/.cache/rvt-prt` |
| Otherwise, macOS | `~/Library/Caches/rvt-prt` |
| Otherwise, Windows | `%LOCALAPPDATA%\rvt-prt\Cache` |
| `RVT_PRT_CACHE` set | the folder it names |

**What is in it:**

- `cache/`: what each decoder read from each model, one file per model and decoder, and per
  model a `<model>.selections` folder: which lines of each family type its own solids hide,
  worked out as sheets are drawn and kept for the next print (a few MB per model);
- `links/`: each model's element meshes, one `.npz` file per model;
- `fonts.json`: the index of font files.

**When an entry is rebuilt.** Each entry records the model file's size and modification time and
a hash of the source of the decoders that made it. It is reused only while all of those are
unchanged. So a model saved again by Revit is read afresh, and an rvt-prt update that changes a
decoder rebuilds that decoder's entries on the next print. A stale cache is never served.

Entries are named after the model's **file name**, not its full path. Two different models with
the same file name share entries, each print replacing the other's. The prints are still right,
but each one is cold. Rename one of them, or give each its own `RVT_PRT_CACHE`.

**Housekeeping.** `rvt-prt cache` lists what the folder holds per model, and
`rvt-prt cache --clear [MODEL ...]` removes a model's entries, or all of them
([Command line](usage.md#cache)). There is no size limit: entries for models you no longer print
stay until you clear them. Deleting the cache folder is always safe. It only makes the next
print slow again.

**Trust.** The entries in `cache/` are Python pickles, which run code when loaded. They are
trusted only because they are your own. rvt-prt creates its cache folders for you alone, and does
not read a cache folder that someone else owns or that others can write to (it says so, and
rebuilds on every print). Do not point `RVT_PRT_CACHE` at a folder other people
can write to, and do not exchange cache files. See [`SECURITY.md`](../SECURITY.md).
