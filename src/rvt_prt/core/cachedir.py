"""What the cache folder (paths.CACHE) holds and clearing it: `rvt-prt cache [--clear [MODEL ...]]`.

Only what rvt_prt builds there is touched: `cache/` (the decoders' entries, diskcache.py, named
"<file>.<name>.pkl", each model's own folders "<file>.<name>"; the bench's oracle drawings in
`cache/oracle/`), `links/` (each model's meshes, "<file>.npz") and the font index `fonts.json`.
In a checkout the folder is `out/`, which holds the printed sheets too: those are never listed
or removed. An entry is rewritten in place when its file or decoder changes, so what accumulates
is every model ever printed, `.tmp` files a killed build left, and the bench's oracle drawings
read by earlier readers.
"""
import pathlib
import shutil

from . import paths

SUBDIRS = ("cache", "links")
FONT_INDEX = "fonts.json"
BENCH = "oracle"  # cache/oracle: the family bench's Revit drawings (metrics/blockbench.py)


def _size(p):
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return p.stat().st_size


def model_of(name):
    """The model file an entry belongs to ("Snowdon Towers Sample HVAC.rvt" for
    "Snowdon Towers Sample HVAC.rvt.gelements.pkl" or "....rvt.npz"), or None."""
    low = name.lower()
    for ext in (".rvt.", ".rfa.", ".rte."):
        i = low.find(ext)
        if i >= 0:
            return name[:i + len(ext) - 1]
    return None


def entries(root=None):
    """[(path, model file name or a group: "(bench)", "(fonts)", "(unfinished)"), size in bytes)]
    of everything rvt_prt keeps in the cache folder `root` (default paths.CACHE)."""
    root = pathlib.Path(root or paths.CACHE)
    out = []
    for sub in SUBDIRS:
        d = root / sub
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if sub == "cache" and p.name == BENCH and p.is_dir():
                group = "(bench)"
            elif p.name.endswith(".tmp"):
                group = "(unfinished)"
            else:
                group = model_of(p.name) or "(other)"
            out.append((p, group, _size(p)))
    f = root / FONT_INDEX
    if f.is_file():
        out.append((f, "(fonts)", f.stat().st_size))
    return out


def targets(models=None, root=None):
    """The entries `clear` removes: those of the model files named in `models` (a path or a file
    name, case aside), or, with none named, every entry."""
    found = entries(root)
    if not models:
        return [p for p, _g, _n in found]
    want = {pathlib.Path(m).name.lower() for m in models}
    return [p for p, g, _n in found if g.lower() in want]


def clear(models=None, root=None):
    """Remove `targets(models, root)`; [(path, bytes)] removed."""
    done = []
    for p in targets(models, root):
        n = _size(p)
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        done.append((p, n))
    return done


def report(root=None):
    """The cache folder, its size per model and group, largest first."""
    root = pathlib.Path(root or paths.CACHE)
    by = {}
    for _p, g, n in entries(root):
        c = by.setdefault(g, [0, 0])
        c[0] += 1
        c[1] += n
    lines = [f"cache folder: {root}"]
    if not by:
        return "\n".join(lines + ["  (empty)"])
    for g, (k, n) in sorted(by.items(), key=lambda kv: -kv[1][1]):
        lines.append(f"  {n / 2**20:9.1f} MB  {k:4} entries  {g}")
    lines.append(f"  {sum(n for _k, n in by.values()) / 2**20:9.1f} MB  total")
    return "\n".join(lines)
