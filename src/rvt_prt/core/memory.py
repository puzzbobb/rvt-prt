"""Giving memory back to the machine between the stages of a print."""
import functools
import gc
import pathlib

_PER_FILE = []  # the per_file caches, for forget
_DECODED = False  # whether anything was decoded from a file since the last forget (decoded)


def decoded():
    """Note that this process decoded something from a file (a disk cache built, a model meshed):
    the next forget then trims. A warm print decodes nothing, and its forgets collected all the
    same, each a pass over everything the print holds: 2.2 s of Snowdon's 5 s of reading."""
    global _DECODED
    _DECODED = True


def per_file(fn):
    """functools.cache keyed on a file path first (str or Path alike), whose entries for one file
    `forget` drops: a cold print decodes each link to build its disk caches, and kept every link's
    decoded records after (Snowdon Architectural's: objgraph.decoder 256 MB, families.documents
    184 MB), its parent 2.4 GB at its peak."""
    store = {}

    @functools.wraps(fn)
    def wrapper(path, *args, **kw):
        key = (str(pathlib.Path(path)), args, tuple(sorted(kw.items())))
        if key not in store:
            store[key] = fn(path, *args, **kw)
        return store[key]
    wrapper.store = store
    wrapper.cache_clear = store.clear
    _PER_FILE.append(wrapper)
    return wrapper


_PER_MODEL = []  # the per_model caches, for unload


def per_model(fn):
    """A cache of what a print holds of a model while its sheets are drawn (its saved graphics,
    its graphics headers), keyed on the file path first, as per_file; but kept by forget, which
    a print calls once a model is loaded, and dropped by unload, when the sheet batches no longer
    need the model (render.batches)."""
    store = {}

    @functools.wraps(fn)
    def wrapper(path, *args, **kw):
        key = (str(pathlib.Path(path)), args, tuple(sorted(kw.items())))
        if key not in store:
            store[key] = fn(path, *args, **kw)
        return store[key]
    wrapper.store = store
    wrapper.cache_clear = store.clear
    _PER_MODEL.append(wrapper)
    return wrapper


def unload(path):
    """Drop what the per_model and per_file caches hold of `path`, then trim."""
    p = str(pathlib.Path(path))
    for w in _PER_MODEL:
        for k in [k for k in w.store if k[0] == p]:
            del w.store[k]
    forget(path)
    trim()


def forget(path):
    """Drop what the per_file caches (and families' one-file records) hold of `path`, then trim
    if anything was decoded since the last time (decoded)."""
    global _DECODED
    p = str(pathlib.Path(path))
    for w in _PER_FILE:
        for k in [k for k in w.store if k[0] == p]:
            del w.store[k]
    from ..elements import families
    families.forget_records(p)
    if _DECODED:
        _DECODED = False
        trim()


_TRIMMED_AT = 0  # this process's resident bytes after its last trim


def _resident():
    """This process's resident bytes, else 0 (no /proc: every trim then goes ahead)."""
    import os
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError):
        return 0


def trim(grown=0):
    """Collect, then hand the C heap's free pages back to the system (glibc's malloc_trim, where
    there is one). What a cold stage built and dropped otherwise stays resident: Snowdon
    Architectural's cold meshes and saved graphics left a print's parent at 2.2 GB, 1.3 GB trimmed.
    Where collection is off (gc.disable: linkgeom's prefetch workers), the heap is trimmed alone.
    With `grown`, only once the process has grown by that many bytes since the last trim: a
    collection passes over everything held, and one after each of a model's twenty-odd caches,
    most of them small, was 9 s of Snowdon Architectural's 117 s cold (under the profiler)."""
    global _TRIMMED_AT
    now = _resident()
    if grown and now and now - _TRIMMED_AT < grown:
        return
    if gc.isenabled():
        gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass
    _TRIMMED_AT = _resident()
