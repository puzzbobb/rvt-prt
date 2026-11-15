"""Disk cache for what is decoded from a (linked) Revit file: out/cache/<file>.<name>.pkl.

An entry is reused only when the file's mtime and size and the source of the modules that decode
it are unchanged, so editing a decoder never serves stale results.
"""
import functools
import hashlib
import os
import pathlib
import pickle

from . import paths

DIR = paths.CACHE / "cache"
TRIM_GROWN = 64e6  # bytes a process grows by building caches before it is trimmed (memory.trim)
SRC = pathlib.Path(__file__).resolve().parents[1]  # the package: decoders are named by module, in any subpackage


@functools.cache
def _sources():
    """{module name: [its files in the package]}: the package walked once, not once per module
    of each decoder (1.1 s of a warm Snowdon print)."""
    found = {}
    for f in sorted(SRC.rglob("*.py")):
        found.setdefault(f.stem, []).append(f)
    return found


@functools.cache
def _code_hash(modules):
    h = hashlib.sha1()
    for m in modules:
        found = _sources().get(m, [])
        if len(found) != 1:
            raise LookupError(f"decoder module {m!r}: {len(found)} files named {m}.py in the package")
        h.update(found[0].read_bytes())
    return h.hexdigest()[:12]


@functools.cache
def package_hash():
    """A hash of the whole package's source and the extension's build: what a model's caches as
    a set were built by (api._caches_stamp). Worked out once a process, not once a model."""
    h = hashlib.sha1()
    for files in _sources().values():
        for f in files:
            h.update(f.read_bytes())
    for f in sorted(SRC.glob("_native*")):
        h.update(str(f.stat().st_mtime_ns).encode())
    return h.hexdigest()[:16]


@functools.cache
def _trusted():
    """paths.trusted of the cache folder, said once when it is not."""
    ok = paths.trusted(DIR)
    if not ok:
        import sys
        print(f"rvt-prt: warning: the cache folder {DIR} is not yours alone to write to (its owner or "
              "its permissions): what it holds is not read, and every print rebuilds it", file=sys.stderr)
    return ok


def stamp(path, modules):
    """What an entry built from the file `path` by the decoder `modules` is valid for: the file's
    mtime and size, and those modules' source."""
    st = pathlib.Path(path).stat()
    return (st.st_mtime_ns, st.st_size, _code_hash(tuple(modules)))


def cached(path, name, modules, compute):
    """compute() once per (file version, decoder source); `modules` are the decoder modules."""
    path = pathlib.Path(path)
    key = stamp(path, modules)
    f = DIR / f"{path.name}.{name}.pkl"
    if f.exists() and _trusted():
        try:
            with f.open("rb") as fh:
                k, value = pickle.load(fh)
            if k == key:
                return value
        except Exception:
            pass
    from . import progress
    progress.step(f"  building the {name} cache of {path.name} (once per file or decoder change)")
    data = pickle.dumps((key, compute()), protocol=pickle.HIGHEST_PROTOCOL)
    paths.private(DIR)
    # whole or not at all: another process (a prefetch worker, the print beside it) may build and
    # read the same entry at once
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, f)
    from . import memory
    memory.trim(grown=TRIM_GROWN)
    memory.decoded()  # what compute() decoded may still be held (memory.per_file) for forget
    # what a warm print would read, not what was built: a built value can hold on to what it was
    # built from (Snowdon Architectural's saved graphics: 0.95 GB resident built, 0.13 GB read
    # back; a cold print's parent 2.4 GB at its peak, more than a 4 GB machine had free)
    return pickle.loads(data)[1]
