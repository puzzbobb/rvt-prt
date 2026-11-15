"""A plan view's linework of one model (linkgeom.plan_lines), kept on disk between prints.

What plan_lines returns depends on the model's file, where it is placed, and the view's range,
direction, detail level, phase and what it hides: not on the sheet, nor on the output format. It
is over half of the time a heavy plan sheet takes to draw, so it is kept, in
<cache>/cache/<host file>.views/<generation>/<key>.pkl:

- the generation names the code and every model's file (size and mtime): when any of them
  changes, the folder is a new one and the old ones are removed;
- the key names the model, its placement and the view's parameters.

Segment lists are kept as one array each with their owners and styles (linkgeom._Owned).
"""
import hashlib
import os
import pathlib
import pickle
import shutil

import numpy as np

from . import state

_FOLDER = {}  # {generation: its folder, or None when it cannot be used}: once a process


def _stamp(path):
    try:
        st = pathlib.Path(path).stat()
        return (str(path), st.st_size, st.st_mtime_ns)
    except OSError:
        return (str(path), 0, 0)


def _sources():
    """The files of the models being drawn (state.LINK_ITEMS), the host's first."""
    out = [state.PEN_PATH]
    for item in state.LINK_ITEMS:
        saved = getattr(item[2], "saved", None) if item else None
        if saved is not None:
            out.append(saved.path)
    return [p for p in out if p]


def folder():
    """This print's folder of kept linework (made, earlier generations removed), or None where
    nothing may be kept: no host model, or a cache folder that is not this user's alone."""
    from ..core import diskcache, paths
    if state.PEN_PATH is None:
        return None
    key = repr((diskcache.package_hash(), [_stamp(p) for p in _sources()], os.environ.get("LINK_SKIP", "")))
    gen = hashlib.sha1(key.encode()).hexdigest()[:12]
    if gen not in _FOLDER:
        try:
            root = diskcache.DIR / f"{pathlib.Path(state.PEN_PATH).name}.views"
            paths.private(root)
            ok = diskcache._trusted() and paths.trusted(root)
            if ok:
                for old in root.iterdir():
                    if old.name != gen:
                        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
                paths.private(root / gen)
            _FOLDER[gen] = root / gen if ok else None
        except OSError:
            _FOLDER[gen] = None
    return _FOLDER[gen]


def _pack(segs):
    from ..geometry import linkgeom
    if isinstance(segs, linkgeom._Owned):
        return ("owned", np.asarray(segs, dtype=np.float64) if len(segs) else None, segs.owners, segs.styles)
    return ("plain", segs)


def _unpack(packed):
    from ..geometry import linkgeom
    if packed[0] != "owned":
        return packed[1]
    _kind, arr, owners, styles = packed
    out = linkgeom._Owned()
    if arr is not None:
        list.extend(out, arr)
    out.owners, out.styles = owners, styles
    return out


def pack(res):
    cuts, proj, regions, coloured, dashed = res
    return (_pack(cuts), _pack(proj), regions, {rgb: _pack(s) for rgb, s in coloured.items()}, _pack(dashed))


def unpack(packed):
    cuts, proj, regions, coloured, dashed = packed
    return (_unpack(cuts), _unpack(proj), regions, {rgb: _unpack(s) for rgb, s in coloured.items()}, _unpack(dashed))


def file_for(key):
    """Where the linework named by `key` (any repr-able value) is kept, or None (folder)."""
    d = folder()
    return None if d is None else d / (hashlib.sha1(repr(key).encode()).hexdigest()[:24] + ".pkl")


def read(f):
    """The linework kept in `f`, or None."""
    try:
        with f.open("rb") as fh:
            return unpack(pickle.load(fh))
    except Exception:  # noqa: BLE001 - absent, cut off, or of another layout: worked out again
        return None


def write(f, res):
    """Keep `res` (plan_lines' five) as `f`, whole or not at all; a full disk is no error."""
    try:
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
        tmp.write_bytes(pickle.dumps(pack(res), protocol=pickle.HIGHEST_PROTOCOL))
        os.replace(tmp, f)
    except OSError:
        pass


def kept(key, compute):
    """compute() (plan_lines' five), read from disk where this `key` was worked out before."""
    f = file_for(key)
    if f is None:
        return compute()
    res = read(f) if f.exists() else None
    if res is None:
        res = compute()
        write(f, res)
    return res
