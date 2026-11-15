"""Sheets drawn in batches, each with only the models its sheets show, when the models of a print
do not all fit in memory together.

The process that prints holds every model's geometry (meshes, saved graphics) while the sheets
are drawn, each sheet in a process forked from it. Snowdon's seven models hold 0.36 GB; a project
of fifty linked models can hold several times the memory a machine has. Where they do not fit in
`budget()`, the sheets are grouped (`plan`) so that each group's models fit, by the models each
sheet's views reach (`sheet_models`): each group's models are loaded, its sheets drawn, and the
models the next group does not show dropped (memory.unload). Where they fit, nothing changes: one
group, every model loaded once.

A model is read again for each group that shows it, so the groups are formed to keep the models
in common together; a model every sheet shows (the host) is loaded once.
"""
import json
import os
import pathlib

import numpy as np

# a loaded model's resident memory, by its caches' size on disk where it has not been measured
# (Snowdon's seven: 1.8 to 2.4 times; the host's own less): a little over, as the budget is a bound
CACHE_TO_MEMORY = 2.5
# the share of the memory available to a print that its models may take; the rest is the sheets'
# processes' (each copies the pages of the models it touches as it draws: ~0.2 GB each on Snowdon)
MODEL_SHARE = 0.5
REACH_MARGIN = 3.0  # feet around a viewport's crop within which a model counts as shown (linework.in_crop's)


def resident():
    """This process's resident bytes (0 where it is not known)."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError):
        return 0


def _memory_file(host_path):
    from ..core import paths
    return paths.CACHE / "cache" / f"{pathlib.Path(host_path).name}.model_memory.json"


def _measured(host_path):
    try:
        d = json.loads(_memory_file(host_path).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def note_model_memory(host_path, source, grown):
    """Note what loading `source` took (bytes), for the next print's model_need."""
    if not host_path or source.path is None or grown <= 0:
        return
    try:
        from ..core import paths
        d = _measured(host_path)
        d[source.file_name] = [source.path.stat().st_size, int(grown)]
        f = _memory_file(host_path)
        paths.private(f.parent)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d, indent=0, sort_keys=True))
        os.replace(tmp, f)
    except (OSError, TypeError, ValueError):
        pass


def model_need(host_path, source):
    """Bytes a model takes loaded: as measured when last loaded (the file unchanged in size), else
    CACHE_TO_MEMORY times its caches' size on disk, else that of the file itself (cold: its caches
    run to about its size)."""
    from ..core import paths
    if source.path is None:
        return 0
    size = source.path.stat().st_size
    was = _measured(host_path).get(source.file_name)
    if isinstance(was, list) and len(was) == 2 and was[0] == size and was[1] > 0:
        return int(was[1])
    on_disk = sum(f.stat().st_size for d in ("cache", "links") for f in (paths.CACHE / d).glob(source.file_name + ".*")
                  if f.is_file())
    return int(CACHE_TO_MEMORY * (on_disk or size))


def budget():
    """Bytes the models of a print may take together: MODEL_SHARE of what is available less the
    reserve kept for the rest of the machine; RVT_PRT_MODELS_GB sets it."""
    from ..geometry import linkgeom
    if os.environ.get("RVT_PRT_MODELS_GB"):
        return float(os.environ["RVT_PRT_MODELS_GB"]) * 1e9
    return max(MODEL_SHARE * (linkgeom._available() - linkgeom.reserve()), 0.25e9)


# --- which models a sheet shows ---------------------------------------------------------------

def extent(items):
    """(lo, hi) xyz box of a model's items (linkgeom.Item: world feet), or None when it has none."""
    boxes = [(i.verts.min(axis=0), i.verts.max(axis=0)) for i in items if len(i.verts)]
    if not boxes:
        return None
    return np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)


def reaches(v, box, margin=REACH_MARGIN):
    """Whether the viewport `v` can draw anything of a model whose extent is `box`: a plan
    (render.linework.draw_links) or a section or elevation (draw_section) whose crop, `margin`
    around it, meets the box seen in the view's coordinates. Other views (3D, drafting,
    schedules) draw none of the linked models' geometry."""
    from ..geometry import sections
    if box is None or not (v.view_basis and v.view_origin and v.crop):
        return False
    (bx, by, _bz), o = v.view_basis, v.view_origin
    plan = abs(bx[2]) < 1e-6 and abs(by[2]) < 1e-6 and v.view_range
    if not plan and not sections.is_section(v):
        return False
    lo, hi = box
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) - np.asarray(o)
    vx, vy = corners @ np.asarray(bx, dtype=float), corners @ np.asarray(by, dtype=float)
    x0, y0, x1, y1 = v.crop
    return bool(vx.max() >= min(x0, x1) - margin and vx.min() <= max(x0, x1) + margin
                and vy.max() >= min(y0, y1) - margin and vy.min() <= max(y0, y1) + margin)


def sheet_models(sheets, boxes):
    """{sheet number: frozenset of the indexes of `boxes` ({index: extent}) its viewports reach}."""
    return {s.number: frozenset(k for k, box in boxes.items() if any(reaches(v, box) for v in s.viewports))
            for s in sheets}


# --- groups -------------------------------------------------------------------------------------

def plan(sheets, shows, need, limit, always=frozenset()):
    """[(sheets, model indexes)] in drawing order: groups of `sheets` whose models (`shows`
    {sheet number: indexes}, plus `always`) fit in `limit` bytes together (`need` {index:
    bytes}). Sheets of the same models are taken together, those of the most-shown models first,
    and each group runs on while the next sheet's models still fit, or are all loaded already (it
    costs no memory: Snowdon's plans each show the same six models, and a group a sheet left one
    core of four drawing); a sheet whose models alone do not fit starts a group of its own (it
    must be drawn: its process is capped as every sheet's)."""
    if not sheets:
        return []
    count = {}
    for s in sheets:
        for k in shows[s.number]:
            count[k] = count.get(k, 0) + 1
    # sheets of the same models together, the models shown most first: one model's sheets follow on
    key = lambda s: tuple(sorted((-count[k], k) for k in shows[s.number]))
    order = sorted(sheets, key=key)
    size = lambda ks: sum(need.get(k, 0) for k in ks | always)
    groups, cur, models = [], [], set()
    for s in order:
        want = models | shows[s.number]
        if cur and size(want) > limit and not shows[s.number] <= models:
            groups.append((cur, frozenset(models | always)))
            cur, models = [], set()
            want = set(shows[s.number])
        cur.append(s)
        models = set(want)
    groups.append((cur, frozenset(models | always)))
    return groups
