"""Where rvt_prt keeps what is not part of the package.

Run from a checkout (`pip install -e .` in a clone: `pyproject.toml` and `src/` beside the
package), the development layout beside `src/`: `out/` (caches), `fonts/`, `links/`, `bench/`
(print records). Installed as a package, its caches go to the user's cache folder
(`~/.cache/rvt-prt`, `~/Library/Caches/rvt-prt`, `%LOCALAPPDATA%\\rvt-prt\\Cache`), and
nothing is written beside the package. `RVT_PRT_CACHE` names the cache folder either way.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
DEV = (ROOT / "pyproject.toml").is_file() and (ROOT / "src" / "rvt_prt").is_dir()


def _user_cache():
    if sys.platform == "win32":
        base = pathlib.Path(os.environ.get("LOCALAPPDATA") or pathlib.Path.home() / "AppData" / "Local")
        return base / "rvt-prt" / "Cache"
    if sys.platform == "darwin":
        return pathlib.Path.home() / "Library" / "Caches" / "rvt-prt"
    return pathlib.Path(os.environ.get("XDG_CACHE_HOME") or pathlib.Path.home() / ".cache") / "rvt-prt"


# caches: disk caches in CACHE / "cache", meshes in CACHE / "links", the font index
CACHE = pathlib.Path(os.environ["RVT_PRT_CACHE"]) if os.environ.get("RVT_PRT_CACHE") else (
    ROOT / "out" if DEV else _user_cache())
BENCH = ROOT / "bench" if DEV else None  # print records (metrics/bench.py), a checkout's only
FONTS = ROOT / "fonts" if DEV else None  # a checkout's own font files, searched first
LINKS = ROOT / "links" if DEV else None  # a checkout's linked models, searched last


def private(folder):
    """Make `folder` (and its parents) if it is not there, for this user alone (mode 0700): what
    is kept in it is unpickled when read back, and a pickle runs code."""
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def trusted(folder):
    """Whether what `folder` holds may be unpickled: it is this user's and others cannot write
    to it. A cache someone else could have put a file in is not read (it is rebuilt each time)."""
    if not hasattr(os, "getuid"):
        return True  # no such ownership to ask about (Windows)
    try:
        st = folder.stat()
    except OSError:
        return True  # not there yet: private() makes it
    return st.st_uid == os.getuid() and not st.st_mode & 0o002
