"""Plan linework of a linked model, from rvt-rs's model of it, for a plan view's range.

- Each system element's mesh (walls, slabs, pipes, ...) comes from rvt-rs in-process
  (rvt_prt._native), in world feet, placed by the link instance's transform, cached per link file
  in out/links/<name>.npz. Family instances are Revit's own box of each (gelements: its saved
  graphics' m_bBox) as 12 triangles, the extent their saved graphics are drawn and culled by.
- Cut: elements crossing the view's cut plane give the segments where their triangles meet the
  plane (Revit's cut lines, drawn heavier).
- Cut regions: each cut element's cut segments polygonised, with its material names (IFC layer
  set or material), for the cut pattern (Concrete walls).
- Projection: elements wholly between the view's bottom and the cut plane give their sharp mesh
  edges (faces meeting at more than 30 degrees), projected to the plan; edges that project to a
  point (vertical ones) are dropped. Hidden lines are not removed.
"""
import gc
import os
import pathlib
import sys
from collections import namedtuple

import numpy as np

from ..elements import gelements
from ..core import container, paths

CACHE = paths.CACHE / "links"
# where element meshes come from, recorded in each .npz: rvt-rs's model meshed in-process
# (rvt_prt._native). A cache from another backend (the retired "ifc": ifcopenshell's
# tessellation of rvt-rs's IFC export) is stale.
BACKEND = "native"
# what the .npz holds, recorded in it: 4, the system elements only (family instances: _family_items),
# those demolished before the project's last phase included (_earlier_phases), model text as its
# letters (_model_text); a cache of an earlier format (3: model text as rvt-rs's box; 2: the last
# phase's only; 1: rvt-rs's family boxes too) is stale
FORMAT = 4
SHARP = np.cos(np.radians(30))
# classes left out of plans: none by default (what a view hides is its visibility settings);
# LINK_SKIP in the environment adds some, for experiments
PLAN_SKIP = set()
# Revit's IFC export class -> BuiltInCategory, the last resort for elements neither rvt-elements
# nor the link's families give a category for (walls, floors and other system families)
IFC_CATEGORY = {
    "IfcWall": -2000011, "IfcCurtainWall": -2000011, "IfcSlab": -2000032, "IfcRoof": -2000035,
    "IfcCovering": -2000038, "IfcColumn": -2000100, "IfcBeam": -2001320, "IfcDoor": -2000023,
    "IfcWindow": -2000014, "IfcStair": -2000120, "IfcStairFlight": -2000120, "IfcRamp": -2000180,
    "IfcRailing": -2000126, "IfcPlate": -2000170, "IfcMember": -2000171, "IfcFurniture": -2000080,
    "IfcSanitaryTerminal": -2001160, "IfcLightFixture": -2001120, "IfcElectricAppliance": -2001040,
    "IfcTransportElement": -2001310, "IfcPipeSegment": -2008044, "IfcPipeFitting": -2008049,
    "IfcDuctSegment": -2008000, "IfcDuctFitting": -2008010, "IfcAirTerminal": -2008013,
    "IfcBuildingElementProxy": -2000151,
}
# BuiltInCategory -> the IFC class rvt-rs's exporter gives a family instance of it (one class per
# category over the 58,000 instances of Snowdon's 7 models, rac_advanced, rst_basic, Golden Nugget,
# サンプル意匠 and test02); a category not listed: IfcBuildingElementProxy
CATEGORY_IFC = {
    -2000011: "IfcWall", -2000014: "IfcWindow", -2000023: "IfcDoor", -2000032: "IfcSlab", -2000035: "IfcRoof",
    -2000080: "IfcFurniture", -2000100: "IfcColumn", -2000120: "IfcStair", -2000126: "IfcRailing",
    -2000170: "IfcPlate", -2000171: "IfcMember", -2001000: "IfcFurniture", -2001043: "IfcElectricAppliance",
    -2001052: "IfcTransportElement", -2001120: "IfcLightFixture", -2001160: "IfcSanitaryTerminal",
    -2001300: "IfcFooting", -2001320: "IfcBeam", -2001330: "IfcColumn", -2008010: "IfcDuctFitting",
    -2008013: "IfcAirTerminal", -2008049: "IfcPipeFitting", -2008083: "IfcElectricAppliance",
}
# a link element: IFC class, mesh (feet), materials "a|b", BuiltInCategory, its IFC placement
# (4x4, feet, before the link transform), family name (IFC ObjectType "Family:Type"), its Revit
# element id and the line colour of its MEP system type (systems.py; None when it has none)
# and its phases (created, demolished index in the model's phase order: phases.source_phases)
Item = namedtuple("Item", "cls verts faces materials category matrix family tag rgb classification phase",
                  defaults=(None, None, None))
SKIP = {"IfcSpace", "IfcOpeningElement", "IfcAnnotation", "IfcGrid", "IfcSite", "IfcBuildingStorey"}


def meshes(link):
    """[Item] for a link, cached. System elements' meshes come from the geometry backend
    (`BACKEND`), their category from the saved graphics of the element the IFC Tag names
    (gelements.py; 0 when unknown); family instances from the link file (_family_items), each
    with its own transform (families.instance_transforms)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    npz = CACHE / (link.file_name + ".npz")
    src = link.path
    out = _load(npz, src)
    if out is not None:
        return _place(_instances(out, src), link)
    if src is None:
        return []
    from ..core import progress
    progress.step(f"  meshing {src.name} (once per file: cached in out/links)")
    try:
        caps = container.capabilities(src)
    except container.UnsupportedFile:  # no release in its BasicFileInfo (2008 files: a build date only)
        caps = {"geometry": False, "revit_version": "of an unknown version"}
    if not caps["geometry"]:
        lo, hi = container.GEOMETRY_RELEASES
        print(f"rvt-prt: {src.name} is Revit {caps['revit_version']}: no IFC geometry for this version "
              f"(rvt-rs reads {lo}-{hi}); its family instances are drawn from their saved graphics",
              file=sys.stderr)
        out = []
    else:
        from ..elements import families
        placed = families.instance_transforms(src)
        out = _model_text(src, [i for i in _native_items(src, gelements.categories(src)) if i.tag not in placed])
    _save(npz, out)
    # read back as a warm print reads it: as meshed, Snowdon Architectural's items held 1.0 GB,
    # read back 0.16 GB
    back = _load(npz, src)
    out = out if back is None else back
    from ..core import memory
    memory.trim()
    memory.decoded()
    return _place(_instances(out, src), link)


def _save(npz, out):
    """Write the [Item] `out` as the cache `npz` (the arrays _load reads, BACKEND and FORMAT)."""
    verts = np.concatenate([i.verts for i in out]) if out else np.zeros((0, 3))
    faces = np.concatenate([i.faces for i in out]) if out else np.zeros((0, 3), np.int32)
    index, vo, fo = [], 0, 0
    for i in out:
        v, fa = i.verts, i.faces
        index.append((vo, vo + len(v), fo, fo + len(fa)))
        vo += len(v)
        fo += len(fa)
    np.savez(npz, classes=np.array([i.cls for i in out]), verts=verts, faces=faces,
             index=np.array(index, dtype=np.int64).reshape(-1, 4), materials=np.array([i.materials for i in out]),
             categories=np.array([i.category for i in out], dtype=np.int64),
             matrices=np.array([i.matrix.reshape(16) for i in out]).reshape(-1, 16), families=np.array([i.family for i in out]),
             tags=np.array([i.tag for i in out], dtype=np.int64), backend=np.array(BACKEND),
             format=np.array(FORMAT))


def fresh(npz, src):
    """Whether the cache `npz` exists and is newer than its file `src` (if any) and _native's
    build (a rebuilt extension, a new rvt-rs, invalidates it too); _load also checks its backend."""
    from .. import _native
    built = pathlib.Path(_native.__file__).stat().st_mtime
    return npz.exists() and (src is None or npz.stat().st_mtime >= max(src.stat().st_mtime, built))


def _load(npz, src):
    """[Item] from the cache `npz` of the file `src`, without the instances _instances adds; None
    when it is missing or stale (older than `src` or than _native's build, from another backend or
    format)."""
    if not fresh(npz, src):
        return None
    with np.load(npz, allow_pickle=False) as z:  # each z[key] re-reads the array: read once
        # caches written before the backend was recorded came from ifcopenshell
        backend = str(z["backend"]) if "backend" in z.files else "ifc"
        if "tags" not in z.files or (backend != BACKEND and src is not None):
            return None
        if "format" not in z.files or int(z["format"]) != FORMAT:
            return None
        classes, index, verts, faces = z["classes"], z["index"], z["verts"], z["faces"]
        mats, cats, mtx, fams, tags = z["materials"], z["categories"], z["matrices"], z["families"], z["tags"]
        out = [Item(str(cls), verts[v0:v1], faces[f0:f1], str(m), int(c), x.reshape(4, 4), str(fn), int(t))
               for cls, (v0, v1, f0, f1), m, c, x, fn, t in zip(classes, index, mats, cats, mtx, fams, tags)]
    return out


# a cold meshes()'s peak address space, bytes: VM_BASE + VM_PER_MB per MB of .rvt (Snowdon's 7
# models, native backend, 4-core ARM64: 0.77 GB for HVAC's 22 MB to 1.49 GB for Architectural's 98 MB)
VM_BASE, VM_PER_MB = 0.8e9, 8.5e6
# a cold print's per-model caches built in one process (api._model_caches, rvt-rs meshing on a
# thread beside), Snowdon's 7 models on the same machine: peak address space up to 2.90 GB (Architectural,
# 98 MB); resident 0.59 GB (HVAC, 22 MB), 0.83 to 1.04 (Electrical, Plumbing, Facades, Site: 40 to
# 54 MB), 2.25 (Architectural) and 1.31 for Structural's 28 MB, out of step with its size. The
# resident line is fitted (through Architectural, Structural 0.3 GB over it: what reserve()
# leaves, and a worker stopped at the floor is tried again), not a bound: a bound through
# Structural put Site at 1.7 GB, twice its peak, and ran two workers where three fit. The
# address space line is a bound, for the cap
CACHES_VM_BASE, CACHES_VM_PER_MB = 1.45e9, 15e6
CACHES_RSS_BASE, CACHES_RSS_PER_MB = 0.45e9, 20e6


# the niceness of every prefetch worker but the largest model's, the longest: Snowdon
# Architectural's took 75 s beside the others at the same priority, 65 s ahead of them (36 s alone)
NICE = 5


def reserve():
    """Bytes of memory left to the rest of the machine (and the parent) when sizing workers: 1.5 GB
    of 8, a fifth of less (4 GB: 0.8 GB, where 1.5 left no sheet any)."""
    return min(1.5e9, 0.2 * _total())


def prefetch(link_list, jobs=None, task=None, current=None, need=None, on_done=None):
    """Compute the caches of the sources in `link_list` that are not `current`, each in its own
    process (forkserver or spawn: a forked worker would share the parent's open files), the
    largest that fits first (the largest of all at the highest priority), so that what reads
    them later finds them built.
    `task(source)`: what a worker computes (default meshes(): out/links/<name>.npz and _instances'
    disk caches); `current(source)`: whether its caches are built (default: its .npz is fresh);
    `need(source)`: its worker's peak (resident, address space) bytes (default meshes()'s address
    space for both, by the file's size).
    `jobs` (default RVT_PRT_GEOMETRY_JOBS, else 0): 1 does nothing (they are computed one by one
    where they are read, in this process); 0 = auto: as many at once as the cores allow and their
    estimated resident needs fit in the available memory less reserve(), one at least. A worker's
    address space is capped at 1.5 times its estimate, and the largest worker is stopped when the
    machine's MemAvailable falls below the render pool's floor, and tried again once by itself
    later; a source that fails (over its cap, stopped again, or any error) is left to be computed
    where it is read, in this process. `on_done(source)` is called as each is done with here: built,
    current already, or failed. [sources done]"""
    import multiprocessing
    import multiprocessing.connection
    if jobs is None:
        jobs = int(os.environ.get("RVT_PRT_GEOMETRY_JOBS", "0"))
    need = need or (lambda l: (VM_BASE + VM_PER_MB * l.path.stat().st_size / 1e6,) * 2)
    current = current or (lambda l: _load(CACHE / (l.file_name + ".npz"), l.path) is not None)
    on_done = on_done or (lambda l: None)
    stale = []
    for l in link_list:
        if l.path is not None and not current(l):
            stale.append(l)
        else:
            on_done(l)
    stale.sort(key=lambda l: l.path.stat().st_size, reverse=True)
    jobs = min(jobs or os.cpu_count() or 1, len(stale))
    if jobs <= 1:
        for l in stale:
            on_done(l)
        return []
    from ..core import progress
    from ..render import pool
    progress.step(f"building the caches of {len(stale)} model(s), up to {jobs} at a time, each in its own process")
    CACHE.mkdir(parents=True, exist_ok=True)
    method = "forkserver" if "forkserver" in multiprocessing.get_all_start_methods() else "spawn"
    ctx = multiprocessing.get_context(method)
    budget = _available() - reserve()
    pending, running, done = list(stale), {}, []
    stopped = set()  # file names of the workers stopped at the floor: tried again once, alone
    while pending or running:
        held = sum(n for _p, _l, n in running.values())
        if pending and len(running) < jobs:
            needs = [need(l) for l in pending]
            # the largest that fits (one at least); a stopped one only by itself
            fits = [i for i, (n, _vm) in enumerate(needs)
                    if not running or (held + n <= budget and pending[i].file_name not in stopped)]
            if fits:
                l, (n, vm) = pending.pop(fits[0]), needs[fits[0]]
                r, w = ctx.Pipe(duplex=False)
                # the largest (the longest, the print's critical path) ahead of the others for the cores
                nice = 0 if l.path == stale[0].path else NICE
                # and with helper processes for its saved graphics, most of its time: half the
                # cores, where there are six or more (the other models' workers have the rest, and
                # done before it leave them idle; by itself Snowdon Architectural's decoding went
                # from 33 s to 16 s in four). Not on four cores, all busy with the models: there
                # the helpers only took from the others (a cold Snowdon print 133 s against 130 s)
                cores = os.cpu_count() or 1
                procs = min(6, cores // 2) if cores >= 6 and l.path == stale[0].path else 1
                proc = ctx.Process(target=_warm, args=(l, CACHE, BACKEND, task, int(1.5 * vm), w, nice, procs))
                proc.start()
                w.close()
                running[r] = (proc, l, n)
                progress.step(f"  {l.file_name}: building (about {n / 1e9:.1f} GB)")
                continue
        killed = None
        if running and _available() < pool.floor(len(running) == 1):
            killed = max(running, key=lambda r: running[r][2])
            running[killed][0].kill()
        for r in multiprocessing.connection.wait(list(running), timeout=0.5):
            proc, l, _n = running.pop(r)
            try:
                why = r.recv()
            except EOFError:
                why = f"stopped (exit code {proc.exitcode})"
            r.close()
            proc.join()
            if why is None:
                done.append(l)
                progress.step(f"  {l.file_name}: built ({len(done)}/{len(stale)})")
                on_done(l)
            elif r is killed and running and l.file_name not in stopped:
                stopped.add(l.file_name)
                pending.insert(0, l)
                progress.step(f"  {l.file_name}: stopped, memory low; trying it again by itself")
            else:
                print(f"rvt-prt: {l.file_name} failed in a worker ({why}); computing it here instead", file=sys.stderr)
                on_done(l)
    return done


def _available():
    """Bytes of memory available (MemAvailable), else 4 GB."""
    try:
        with open("/proc/meminfo") as f:
            return next(int(line.split()[1]) * 1024 for line in f if line.startswith("MemAvailable:"))
    except (OSError, StopIteration):
        return 4e9


def _total():
    """Bytes of memory the machine has (MemTotal), else 8 GB."""
    try:
        with open("/proc/meminfo") as f:
            return next(int(line.split()[1]) * 1024 for line in f if line.startswith("MemTotal:"))
    except (OSError, StopIteration):
        return 8e9


def _cap(limit):
    """A prefetch worker's address space limit (RLIMIT_AS, where there is one)."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass


def _warm(link, cache, backend, task, cap, conn, nice=0, procs=1):
    """A prefetch worker: `task(link)` (else meshes()) for its caches, in the parent's CACHE and
    BACKEND, under the address space `cap` and at `nice` (os.nice); None to `conn` when done, else
    what failed. Nothing large returns through the pipe. `procs`: the processes its saved graphics
    are decoded in (savedgraphics.PROCS)."""
    global CACHE, BACKEND
    CACHE, BACKEND = cache, backend
    from ..elements import savedgraphics
    savedgraphics.PROCS = procs
    _cap(cap)
    if nice:
        try:
            os.nice(nice)
        except (AttributeError, OSError):
            pass
    # no cyclic collection: the worker ends with its task, and with millions of decoded objects
    # alive each full pass is slow (a cold Snowdon Architectural: 98 s with it, 67 s without,
    # its peak 2.30 GB against 2.53 GB)
    gc.disable()
    try:
        (task or meshes)(link)
        out = None
    except BaseException as e:  # MemoryError at the cap, or anything else: the parent computes it
        out = f"{type(e).__name__}: {str(e)[:200]}" if str(e) else type(e).__name__
    conn.send(out)
    conn.close()


_started = {}  # {file: Future of its _native.element_meshes}, begun by start_meshing


def start_meshing(link):
    """Begin rvt-rs's meshing of a link's file on a thread of its own, when its cache is stale and
    rvt-rs reads its release, for meshes() to take up: element_meshes releases the GIL, so it runs
    beside the decoding of the file's other caches (a cold Snowdon Architectural: 22 s of 67 in
    its prefetch worker). Its memory is held only while it runs (1.2 GB at its peak there)."""
    src = link.path
    if src is None or str(src) in _started or _load(CACHE / (link.file_name + ".npz"), src) is not None:
        return
    try:
        if not container.capabilities(src)["geometry"]:
            return
    except container.UnsupportedFile:
        return
    import threading
    from concurrent.futures import Future

    from .. import _native
    # read here, on the calling thread: the file's records are read through one open handle, and
    # read on the meshing thread while this one read them too, they came back garbled (zlib
    # "incorrect data check": a cold Snowdon HVAC worker failed so)
    extra = _earlier_phases(src)
    done = _started[str(src)] = Future()

    def run():
        try:
            done.set_result(_native.element_meshes(str(src), extra))
        except BaseException as e:  # noqa: BLE001 - raised where meshes() takes it up
            done.set_exception(e)
    threading.Thread(target=run, daemon=True).start()


def _earlier_phases(src):
    """phases.earlier_phases of the file: those besides the last that rvt-rs's export is also made
    at, so that elements demolished before the last phase are meshed too ([] where it fails)."""
    from ..model import phases
    try:
        return phases.earlier_phases(src)
    except Exception:  # noqa: BLE001 - the last phase's elements are meshed all the same
        return []


def _native_items(src, category):
    """[Item] from rvt-rs's model in-process (rvt_prt._native.element_meshes: its bodies placed
    in world feet, openings cut), or from the meshing start_meshing began."""
    from .. import _native
    started = _started.pop(str(src), None)
    d = started.result() if started is not None else _native.element_meshes(str(src), _earlier_phases(src))
    verts = np.frombuffer(d["verts"], "<f8").reshape(-1, 3)
    faces = np.frombuffer(d["faces"], "<i4").reshape(-1, 3)
    index = np.frombuffer(d["index"], "<i8").reshape(-1, 4)
    mtx = np.frombuffer(d["matrices"], "<f8").reshape(-1, 4, 4)
    return [Item(cls, verts[v0:v1], faces[f0:f1], mat, category.get(tag, 0), m, fam, tag)
            for cls, tag, fam, mat, m, (v0, v1, f0, f1)
            in zip(d["classes"], d["tags"], d["families"], d["materials"], mtx, index)
            if cls not in SKIP and f1 > f0]


def _model_text(src, items):
    """`items` with each model text (Text3dElem) as its letters. rvt-rs writes model text as a box
    (IfcBuildingElementProxy, 12 triangles): the extent of the panel its saved graphics hold besides
    the letters (a solid in no graphics style), so a plan or section drew a rectangle where Revit
    draws the text. Its saved graphics' solids in a graphics style (Generic Models: the letters;
    Snowdon Architectural's 7, Site's 1) replace it, vertices welded so that only the letters'
    outlines are sharp edges. One rvt-rs left out (its phase) stays out; one whose graphics give no
    letters keeps its box."""
    from ..core import objgraph
    from ..elements import savedgraphics
    from ..model import pens
    tags = set(objgraph._class_index(str(src)).get("Text3dElem", ())) & {i.tag for i in items}
    if not tags:
        return items
    link = savedgraphics.Link(src)
    styles = pens.style_categories(str(src))
    out = []
    for i in items:
        if i.tag in tags:
            letters = [(p.category, m) for p in link.primitives(i.tag)
                       if p.kind == "solid" and p.category in styles and (m := link.solid_mesh(p)) is not None]
            if letters:
                v, f = _welded([m for _, m in letters])
                i = i._replace(cls="IfcBuildingElementProxy", verts=v, faces=f, materials="",
                               category=styles[letters[0][0]][0])
        out.append(i)
    return out


def _welded(meshes, tol=1e-6):
    """One mesh of [(verts, faces)], vertices within `tol` ft shared and collapsed triangles dropped."""
    v = np.vstack([m[0] for m in meshes])
    offs = np.cumsum([0] + [len(m[0]) for m in meshes[:-1]])
    f = np.vstack([m[1] + o for m, o in zip(meshes, offs)])
    key, first, inv = np.unique(np.round(v / tol).astype(np.int64), axis=0, return_index=True, return_inverse=True)
    f = inv.reshape(-1)[f]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 2] != f[:, 0])]
    return v[first], f.astype(np.int32)


def _instance_family_names(src):
    """{FamilyInstance id: its family's name} (families.instance_family, Family.m_name)."""
    from ..elements import families
    recs = families.records(src)
    out = {}
    for eid in families.instance_transforms(src):
        fam = families.instance_family(recs, eid)
        name = recs.fields(fam).get("m_name") if fam is not None else None
        if name:
            out[eid] = name
    return out


# categories whose instances do not draw in plans: left out of _family_items
NON_PLAN = {-2000280, -2000150, -2006080, -2000400, -2000410, -2000420, -2000095, -2002000}
# a box's 12 triangles over its corners numbered by bits (x: 1, y: 2, z: 4; 0 the min corner),
# each face's normal outwards
BOX_FACES = np.array([[0, 2, 3], [0, 3, 1], [4, 5, 7], [4, 7, 6], [0, 1, 5], [0, 5, 4],
                      [2, 6, 7], [2, 7, 3], [0, 4, 6], [0, 6, 2], [1, 3, 7], [1, 7, 5]], np.int32)


def _compute_family_items(src):
    """[Item] of the link file's placed family instances, each Revit's own box of it (gelements:
    its saved graphics' m_bBox, the box rvt-rs gives them) as 12 triangles, its IFC class from its
    category (CATEGORY_IFC), its family's name ("" for a system family's: curtain panels and
    mullions, whose types are SysPanelFamSym / SysMullionFamSym) and its transform. Their saved
    graphics are what is drawn: the box bounds and culls them. Left out: instances nested in another
    family (their parent's graphics draw them), members of a group type (not placed), instances
    without a box or with an empty one (min 1e30, max -1e30: curtain panels and mullions that draw
    nothing; rvt-rs leaves them out too), and NON_PLAN categories."""
    from ..elements import families
    from ..core import objgraph
    recs = families.records(src)
    tr = families.instance_transforms(src)
    nested = set().union(*[d.members for d in families.documents(src).values()])
    names = _instance_family_names(src)
    head = gelements.read(str(src))
    out = []
    for eid, m in tr.items():
        h = head.get(eid)
        if eid in nested or h is None or not h.lo or not h.hi or h.category in NON_PLAN:
            continue
        lo, hi = np.array(h.lo), np.array(h.hi)
        if (hi < lo).any():
            continue
        if recs.cls(objgraph.ref(recs.fields(eid).get("m_unplacedOwnerId"))) == "ElementGroupType":
            continue  # a member of a group type, not placed
        corners = np.array([[(hi if k & bit else lo)[axis] for axis, bit in enumerate((1, 2, 4))] for k in range(8)])
        out.append(Item(CATEGORY_IFC.get(h.category, "IfcBuildingElementProxy"), corners, BOX_FACES, "",
                        h.category, m, names.get(eid, ""), eid))
    for eid, (h, m) in gelements.rails(str(src)).items():  # a railing's rails: no family instances, drawn alike
        lo, hi = np.array(h.lo), np.array(h.hi)
        corners = np.array([[(hi if k & bit else lo)[axis] for axis, bit in enumerate((1, 2, 4))] for k in range(8)])
        out.append(Item("IfcBuildingElementProxy", corners, BOX_FACES, "", h.category, m,
                        RAIL_FAMILIES.get(h.category, ""), eid))
    return out


# model curves of categories Revit draws only while editing a sketch or in an area plan, never in
# a floor plan: <Sketch> lines (the sketches of walls' profiles, floors, roofs: most of Snowdon's
# model curves) and area boundaries. (Snowdon Architectural's 1,190 curves at its stairs, in
# -2000954, are kept: left out too, M100 and M105 lost recall Revit draws there)
NOT_IN_PLANS = {-2000045, -2000079}


def _compute_model_curves(src):
    from ..elements import annotations
    from ..core import container, objgraph
    from ..model import pens
    rf = container.open_file(src)
    cvs = annotations.detail_curves(rf, src)
    model_cvs = [c for c in cvs if c.owner_view == 18446744073709551615]
    styles = pens.style_categories(src)
    bodies = objgraph.channel_bodies(src, 103)
    items = []
    for c in model_cvs:
        v = np.array(c.points, dtype=np.float64)
        if len(v) < 2 or np.isnan(v).any():
            continue
        r = objgraph.root(src, bodies[c.element_id]) if c.element_id in bodies else None
        style = objgraph.ref(r.get("m_GInfo", {}).get("m_categoryId")) if r else None  # 2020-2022 roots can be empty
        cat = styles.get(style, (-2000051,))[0]  # its line style's category (Lines when unknown)
        fa = np.zeros((0, 3), np.int32)
        items.append(Item("ModelCurve", v, fa, "", cat, np.eye(4), "ModelCurve", c.element_id))
    return items


def _disk(name, fn, modules=("linkgeom", "families", "container", "gelements", "pens", "objgraph", "registry")):
    import functools
    @functools.cache
    def wrapper(src):
        from ..core import diskcache
        return diskcache.cached(src, name, modules, lambda: fn(src))
    wrapper.__doc__ = fn.__doc__
    return wrapper


family_items = _disk("family_items", _compute_family_items)
model_curves = _disk("model_curves", _compute_model_curves, ("linkgeom", "annotations", "container", "pens", "objgraph", "registry"))


def decoded(link):
    """Build the disk caches meshes() decodes from the link's file (beside rvt-rs's meshes): the
    family instances, categories, systems and model curves _instances adds."""
    from ..elements import families
    from ..model import systems
    src = link.path
    if src is None:
        return
    gelements.categories(src)
    families.instance_transforms(src), families.categories_by_name(src), systems.element_systems(src)
    family_items(src), model_curves(src)


def _instances(items, src):
    """The family instances (_family_items) added to the system elements `items`, and their
    transforms and, where gelements gave none, categories from the link file's own families
    (families.py); systems' colours and classifications."""
    from ..elements import families
    tr = families.instance_transforms(src)
    cats = families.categories_by_name(src)
    from ..model import systems
    sys_of = systems.element_systems(src)
    existing_tags = {i.tag for i in items if i.tag}
    if src is not None:
        items = list(items) + [it for it in family_items(src) if it.tag not in existing_tags]
    out = []
    for i in items:
        if i.tag in sys_of:
            i = i._replace(rgb=systems.colour_of_system(src, sys_of[i.tag]),
                           classification=systems.classification_of_system(src, sys_of[i.tag]))
        if i.tag in tr:
            i = i._replace(matrix=tr[i.tag])
        if not i.category and i.family in cats:
            i = i._replace(category=cats[i.family])
        out.append(i)
    if src is not None:
        for it in model_curves(src):
            if it.tag not in existing_tags:
                out.append(it)
    return out


def _place(items, link):
    ax = np.array(link.axes, dtype=np.float64)  # rows: X, Y, Z axes
    org = np.array(link.origin, dtype=np.float64)
    if np.allclose(ax, np.eye(3)) and not org.any():
        return items
    t = np.eye(4)
    t[:3, :3], t[:3, 3] = ax.T, org
    return [i._replace(verts=i.verts @ ax + org, matrix=t @ i.matrix) for i in items]


def _cut(v, fa, z):
    """Segments where the triangles cross the plane z: [(p, q)] xy, vectorised."""
    if not len(fa):
        return []
    tri = v[fa]  # (m, 3, 3)
    d = tri[:, :, 2] - z
    s = np.sign(d)
    keep = (s.min(axis=1) < 0) & (s.max(axis=1) > 0)
    if not keep.any():
        return []
    tri, d = tri[keep], d[keep]
    pts = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        di, dj = d[:, i], d[:, j]
        cross = ((di < 0) != (dj < 0)) & (di != dj)
        u = np.where(cross, di / np.where(cross, di - dj, 1.0), 0.0)
        p = tri[:, i, :2] + u[:, None] * (tri[:, j, :2] - tri[:, i, :2])
        pts.append((cross, p))
    # each crossing triangle has exactly two crossing edges; pair them in edge order
    c = np.stack([x[0] for x in pts], axis=1)
    rows = np.nonzero(c.sum(axis=1) == 2)[0]
    P = np.stack([x[1] for x in pts], axis=1)[rows]
    idx = np.argsort(~c[rows], axis=1, kind="stable")[:, :2]
    r = np.arange(len(rows))
    return list(zip(P[r, idx[:, 0]], P[r, idx[:, 1]]))


def _sharp_edges(v, fa):
    """Edges between faces meeting at more than 30 degrees, and boundary edges: (m, 2, 3), each
    edge once, in the order the faces first list it. Sorted keys, not a dict of edges: an
    imported mesh of 2.5M vertices (Golden Nugget's) has millions of them."""
    fa = np.asarray(fa).reshape(-1, 3)
    if not len(fa):
        return np.zeros((0, 2, 3))
    tri = v[fa]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    del tri
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 1e-12
    n[ok] /= ln[ok, None]
    a, b = fa.reshape(-1), fa[:, [1, 2, 0]].reshape(-1)  # each face's edges ab, bc, ca in turn
    key = np.minimum(a, b).astype(np.int64) * len(v) + np.maximum(a, b)
    del a, b
    order = np.argsort(key, kind="stable")  # each edge's uses together, in the faces' order
    ks = key[order]
    start = np.ones(len(ks), bool)
    start[1:] = ks[1:] != ks[:-1]
    first = np.flatnonzero(start)
    count = np.diff(np.append(first, len(ks)))
    f0 = order[first] // 3
    f1 = order[np.minimum(first + 1, len(ks) - 1)] // 3
    smooth = (count == 2) & ((n[f0] * n[f1]).sum(axis=1) > SHARP)
    keep = first[~smooth]
    keep = keep[np.argsort(order[keep])]  # in the order of first use
    lo, hi = ks[keep] // len(v), ks[keep] % len(v)
    return np.stack([v[lo], v[hi]], axis=1)


def beyond_any(zlo, zhi, cut, bottom, top, view_top, is_overhead):
    """Whether an element's height range reaches a plan's view range (looking down: below the cut
    plane to its bottom, or overhead elements up to the view top; a ceiling plan: above the cut)."""
    if top is None:
        return zhi >= bottom - 0.05 and (zlo <= cut + 1e-6 or (view_top is not None and is_overhead and zlo <= view_top + 0.05))
    return zhi >= cut - 1e-6 and zlo <= top + 0.05


class _Owned(list):
    """A segment list noting, per segment, the owner `_Owned.owner` named when it was added:
    `.owners[i]` is (element id, family name, BuiltInCategory) of the element that drew segment i,
    `.styles[i]` the graphics style (GStyleElem id) it is drawn in where known (`_Owned.style`)."""
    owner = None
    style = None

    def __init__(self, *a):
        super().__init__(*a)
        self.owners = [_Owned.owner] * len(self)
        self.styles = [_Owned.style] * len(self)

    def append(self, x):
        super().append(x)
        self.owners.append(_Owned.owner)
        self.styles.append(_Owned.style)

    def extend(self, xs):
        xs = list(xs)
        super().extend(xs)
        self.owners += [_Owned.owner] * len(xs)
        self.styles += [_Owned.style] * len(xs)

    def __iadd__(self, xs):  # type: ignore[misc]
        self.extend(xs)
        return self


def _joined(walls, tol=1e-3):
    """Walls' cut sections with their joins cleaned, as Revit draws joined walls in plan: the
    sections merged and each wall's segments kept only where they lie on the merged outline (a
    wall's end inside the wall it meets is dropped). [(owner, segments)]; a wall whose section
    does not close is kept as cut."""
    import shapely
    from shapely.ops import polygonize, unary_union
    if len(walls) < 2:
        return walls
    areas = []
    for _owner, segs in walls:
        a = unary_union(list(polygonize([tuple(map(tuple, np.round(s, 6))) for s in segs])))
        areas.append(a if not a.is_empty else None)
    have = [i for i, a in enumerate(areas) if a is not None]
    if not have:
        return walls
    tree = shapely.STRtree([areas[i] for i in have])
    out = []
    for (owner, segs), area in zip(walls, areas):
        if area is None:
            out.append((owner, segs))
            continue
        # the merged outline near this wall: it and the walls it meets
        near = [areas[have[j]] for j in tree.query(area.buffer(tol))]
        edge = shapely.union_all(near).boundary.buffer(tol)
        lines = shapely.linestrings(np.asarray(segs, dtype=float))
        kept = []
        for g in shapely.intersection(lines, edge):
            for part in getattr(g, "geoms", [g]):
                if part.geom_type == "LineString" and part.length > tol * 3:  # not where it crosses the outline
                    c = np.asarray(part.coords)
                    kept.append((c[0], c[-1]))
        out.append((owner, kept))
    return out


# what hides what lies above it in a ceiling plan: floors and roofs. Not ceilings: Snowdon's HVAC
# ceiling plans draw the bar joists above the rooms' ceilings (M201-M205). Within one model only:
# across links, rvt-rs's box for a sloped roof (Facades 1247924, 28.4-45.4 ft) hid M203's west
# bay of Structural joists, which Revit draws (recall -1.7)
CEILING_PLAN_OCCLUDERS = {-2000032, -2000035}

# MEP categories a plan draws up to its view range's top, not only below the cut, as the host's
# ducts are drawn (model2d footprints): ducts, duct fittings, air terminals, mechanical equipment.
# Revit's DXF of Snowdon's floor plans (M100-M106), of those the view shows above the cut: the
# host's duct fittings 873 of 874, air terminals 422 / 422, equipment 33 / 33; the Plumbing link's
# duct fittings 122 / 134, air terminals 24 / 24; but its pipe fittings 0 of 65 (not in the set)
MEP_ABOVE_CUT = {-2008000, -2008010, -2008013, -2001140}

# a railing's top rails and handrails (gelements.rails). Not drawn in ceiling plans: Revit's DXF of
# Snowdon's M202 and M203 holds none (M202: 25 in its range), M201 14 blocks of its 30, and drawn
# there they cost precision (M201 -0.4, M202 -0.3 ink); to review with another test oracle
RAILS = {-2000946, -2000947}
RAIL_FAMILIES = {-2000946: "Top Rail Type", -2000947: "Handrail Type"}  # their system families, as Revit names them


def ceiling_plan_occluders(items, cut, top, hidden=frozenset(), filters=()):
    """[triangles (k, 3, 3)] of the floors and roofs of `items` wholly above a ceiling plan's cut
    and starting below its `top`, those the view shows: what hides lines behind it."""
    out = []
    for it in items:
        cat = it.category or IFC_CATEGORY.get(it.cls, 0)
        if cat not in CEILING_PLAN_OCCLUDERS or it.cls in PLAN_SKIP or cat in hidden or not len(it.faces):
            continue
        if filters and any(f.matches(cat, it.classification) for f in filters):
            continue
        z = it.verts[:, 2]
        if z.min() >= cut - 1e-6 and z.min() < top - 1e-6:
            out.append(it.verts[np.asarray(it.faces).reshape(-1, 3)])
    return out


def _ceiling_plan_visible(looked_at, occluders, cut):
    """Add each ceiling-plan line of `looked_at` [(list, owner, style, 3D segments)] to its list,
    in its owner and style, where no occluding triangle wholly above the cut lies between it and
    the cut plane: sections' hidden-line test looking up, depth the height above the cut."""
    from . import sections
    if not looked_at:
        return
    occ = [t for t in occluders if len(t)]
    occ = [t[t[:, :, 2].min(axis=1) >= cut - 1e-6] for t in occ]
    occ = [t for t in occ if len(t)]
    if not occ:
        for into, owner, style, segs in looked_at:
            _Owned.owner, _Owned.style = owner, style
            s = np.asarray(segs)[:, :, :2]
            d = s[:, 1] - s[:, 0]
            into.extend(s[np.hypot(d[:, 0], d[:, 1]) > 1e-4])
        _Owned.style = None
        return
    segs = [np.asarray(s, dtype=float).reshape(-1, 2, 3) for _, _, _, s in looked_at]
    owners = [j for j, s in enumerate(segs) for _ in range(len(s))]
    segs = np.concatenate(segs)
    segs[:, :, 2] = cut - segs[:, :, 2]
    tris = []
    for t in occ:
        t = np.array(t, dtype=float)
        t[:, :, 2] = cut - t[:, :, 2]
        tris.append(t)
    for j, parts in sections._visible(segs, tris, [], owners):
        into, owner, style, _ = looked_at[j]
        _Owned.owner, _Owned.style = owner, style
        into.extend(parts)
    _Owned.style = None


def plan_lines(items, bottom, cut, hidden=frozenset(), symbols=None, top=None, stair_edges=(), filters=(), view_top=None,
               record=False, inserts=None, right=(1.0, 0.0, 0.0), detail=None, occluder_items=None):
    """(cut segments, projected segments, cut regions [(materials, polygon)], {rgb: segments} of the
    elements a system colours) in model XY feet for
    a view range, leaving out the categories the view hides. With `top` set (a ceiling plan, looking
    up) the projected elements are those between the cut plane and `top` instead. An element whose family has curves
    in `symbols` ({family name: [points]}, families.py) draws them, through its placement, in
    place of its mesh (rvt-ifc's family meshes are boxes).

    For export: with `record`, the segment lists are _Owned (each segment's element in .owners);
    with an `inserts` list, family curves are not added as segments but appended to it as
    (owner, 4x4 placement, [family-coordinate (N, 4) curves], "cut" or "proj"), one per instance.
    `detail` is the view's detail level (saved graphics' detail conditions; None keeps every branch).
    A ceiling plan's lines behind the floors and roofs of `items` (or `occluder_items`) above its
    cut are hidden."""
    from shapely.ops import polygonize, unary_union
    import os
    skip = PLAN_SKIP | set(filter(None, os.environ.get("LINK_SKIP", "").split(",")))  # env: experiments
    saved = getattr(symbols, "saved", None)
    segs_list = _Owned if record else list
    cuts, proj, regions = segs_list(), segs_list(), []
    walls = []  # [(owner, cut segments)]: walls' sections, joined before drawing
    coloured = {}  # rgb -> segments: elements whose MEP system type sets a colour
    # a ceiling plan: [(list, owner, style, 3D segments)] seen above the cut, added once the
    # floors' and roofs' triangles above it (occluders) have hidden what lies behind them
    looked_at = []
    for it in items:
        _cls, v, fa, mats, cat = it.cls, it.verts, it.faces, it.materials, it.category
        if record:
            _Owned.owner = (it.tag, it.family or "", cat or IFC_CATEGORY.get(_cls, 0))
        if _cls in skip or (cat or IFC_CATEGORY.get(_cls, 0)) in hidden:
            continue
        if filters and any(f.matches(cat or IFC_CATEGORY.get(_cls, 0), it.classification) for f in filters):
            continue  # a view filter with visibility off (filters.py)
        zlo, zhi = v[:, 2].min(), v[:, 2].max()
        eff_bottom = bottom - 5.0 if _cls == "ModelCurve" else bottom
        if top is None and zhi < eff_bottom - 0.05 or top is not None and (zhi < cut - 1e-6 or zlo >= top - 1e-6):
            continue
        if top is not None and cat in RAILS:
            continue
        if top is None and _cls in ("IfcWall", "IfcWallStandardCase") and zhi <= bottom + 1e-3:
            continue  # a wall wholly below the view range, its top on the bottom plane (Snowdon's foundation walls up to L1 - Block 35's -5.92 ft)
        if _cls == "ModelCurve":
            if cat in NOT_IN_PLANS:
                continue
            ok = (zlo <= cut + 0.05 and zhi >= eff_bottom - 0.05) if top is None else (zlo <= top + 0.05 and zhi >= cut - 0.05)
            if ok:
                into = coloured.setdefault(it.rgb, segs_list()) if it.rgb else proj
                for i in range(len(v) - 1):
                    into.append((v[i, :2], v[i + 1, :2]))
            continue
        # above the cut up to the view's top: windows, casework (-2001000) and generic models, as
        # Revit's view range shows them, lights, columns, and the MEP categories
        is_overhead = (cat or 0) in (-2001120, -2000014, -2001000, -2000040, -2000151, -2000100) or (cat or 0) in MEP_ABOVE_CUT or _cls in ("IfcLightFixture", "IfcWindow", "IfcColumn")
        vis = getattr(saved, "visibility", {}).get(it.tag) if saved is not None else None
        if vis is not None and vis != -1 and not vis & 0x08:
            continue  # a nested family its parent hides in plans (savedgraphics.nested_visibility)
        if saved is not None and it.tag in saved.instances and beyond_any(zlo, zhi, cut, bottom, top, view_top, is_overhead):
            res_s = saved.plan(it.tag, symbols.place, cut, bottom, top, (view_top + 0.05) if (view_top is not None and is_overhead and top is None) else None, right, detail)
            if res_s is not None:  # the type's regenerated graphics, as Revit saved them (savedgraphics.py)
                M, groups = res_s
                style_cats = getattr(saved, "style_categories", {})
                groups = [g for g in groups if g[3] is None or style_cats.get(g[3]) not in hidden]  # a subcategory the view hides
                if inserts is not None:
                    owner = (it.tag, it.family or "", cat or IFC_CATEGORY.get(_cls, 0))
                    for want_cut in (False, True):
                        loc = [g[1] for g in groups if g[2] == want_cut]
                        if loc:
                            loc = np.concatenate(loc)
                            homo = np.concatenate([loc, np.ones(loc.shape[:2] + (1,))], axis=2)
                            inserts.append((owner, M, list(homo), "cut" if want_cut else "proj"))
                else:
                    for world, _local, c, style in groups:
                        into = coloured.setdefault(it.rgb, segs_list()) if it.rgb else cuts if c else proj
                        if top is not None and not c:
                            looked_at.append((into, _Owned.owner, style, world))
                            continue
                        _Owned.style = style
                        into.extend(world[:, :, :2])
                    _Owned.style = None
                continue
        if stair_edges and ((cat or 0) in (-2000400, -2000404, -2000126, -2000127, -2000128) or _cls in ("IfcStair", "IfcStairFlight", "IfcRailing")):
            continue
        if zlo < cut < zhi:
            segs = _cut(v, fa, cut)
            if _cls in ("IfcWall", "IfcWallStandardCase") and segs:
                walls.append((_Owned.owner, segs))  # joined below (_joined)
            else:
                cuts += segs
            mats_eff = mats or ("Concrete, Cast-in-Place gray" if it.cls in ("IfcWall", "IfcSlab") and it.category not in (-2000120, -2000400, -2000404) else "")
            if mats_eff and segs:
                area = unary_union(list(polygonize([tuple(map(tuple, np.round(s, 6))) for s in segs])))
                if not area.is_empty:
                    regions.append((mats_eff, area))
        elif (zhi <= cut + 1e-6) if top is None else (zlo >= cut - 1e-6):
            into = coloured.setdefault(it.rgb, segs_list()) if it.rgb else proj
            if top is not None:
                looked_at.append((into, _Owned.owner, None, _sharp_edges(v, fa)))
                continue
            for p, q in _sharp_edges(v, fa):
                if np.hypot(p[0] - q[0], p[1] - q[1]) > 1e-4:
                    into.append((p[:2], q[:2]))
    for owner, segs in _joined(walls):
        _Owned.owner = owner
        cuts += segs
    if looked_at:
        # occluders from `occluder_items` where given: the whole model's, so that lines are split at
        # the same edges whatever the walk was limited to (render.linework.in_crop)
        _ceiling_plan_visible(looked_at, ceiling_plan_occluders(items if occluder_items is None else occluder_items,
                                                                cut, top, hidden, filters), cut)
    dashed = segs_list()
    if top is None and stair_edges:
        if isinstance(stair_edges, tuple) and len(stair_edges) == 2:
            stair_runs, stair_landings = stair_edges
            # Find runs directly intersecting [bottom - 0.05, cut + 0.05]
            vis_runs = set()
            for r in stair_runs:
                zs = [z for z, a, b in r.edges]
                z_min, z_max = min(zs), max(zs)
                if z_max >= bottom - 0.05 and z_min <= cut + 0.05:
                    vis_runs.add(r.element_id)

            # Also include lower companion runs meeting a visible run at a landing
            for r1 in stair_runs:
                if r1.element_id in vis_runs:
                    z1_min = min(z for z, a, b in r1.edges)
                    c1 = (np.mean([a[0] for z, a, b in r1.edges]), np.mean([a[1] for z, a, b in r1.edges]))
                    for r2 in stair_runs:
                        z2_max = max(z for z, a, b in r2.edges)
                        c2 = (np.mean([a[0] for z, a, b in r2.edges]), np.mean([a[1] for z, a, b in r2.edges]))
                        if abs(z1_min - z2_max) < 0.2 and np.hypot(c1[0] - c2[0], c1[1] - c2[1]) < 15.0:
                            vis_runs.add(r2.element_id)

            for r in stair_runs:
                if r.element_id not in vis_runs:
                    continue
                _Owned.owner = (r.element_id, "", -2000120)
                zs = [z for z, a, b in r.edges]
                z_min, z_max = min(zs), max(zs)
                # Filter tread front edges (perpendicular to run, length in 2.0 to 6.0 ft)
                treads = [e for e in r.edges if 2.0 <= np.linalg.norm(np.array(e[1][:2]) - np.array(e[2][:2])) <= 6.0 and e[0] <= cut + 0.05]
                unique_treads = []
                seen_mids = set()
                for e in treads:
                    mid = (round((e[1][0] + e[2][0]) / 2, 2), round((e[1][1] + e[2][1]) / 2, 2))
                    if mid not in seen_mids:
                        seen_mids.add(mid)
                        unique_treads.append(e)

                for z, a, b in unique_treads:
                    proj.append((a[:2], b[:2]))


                if z_min <= cut <= z_max and unique_treads:
                    cut_tread = min(unique_treads, key=lambda e: abs(e[0] - cut))
                    A, B = np.array(cut_tread[1][:2]), np.array(cut_tread[2][:2])
                    W = B - A
                    w_len = np.linalg.norm(W)
                    if w_len > 0.5:
                        U = np.array([-W[1], W[0]]) / w_len
                        p0 = A - 0.1 * W
                        p1 = A + 0.42 * W
                        p2 = A + 0.46 * W + 0.35 * U
                        p3 = A + 0.54 * W - 0.35 * U
                        p4 = A + 0.58 * W
                        p5 = B + 0.1 * W
                        proj += [(tuple(p0), tuple(p1)), (tuple(p1), tuple(p2)), (tuple(p2), tuple(p3)), (tuple(p3), tuple(p4)), (tuple(p4), tuple(p5))]

            # Landings that connect to visible runs
            vis_z_landings = set()
            for r in stair_runs:
                if r.element_id in vis_runs:
                    zs = [z for z, a, b in r.edges]
                    vis_z_landings.add(round(min(zs), 1))
                    vis_z_landings.add(round(max(zs), 1))

            seen_land_edges = set()
            for l in stair_landings:
                _Owned.owner = (l.element_id, "", -2000120)
                for z, a, b in l.edges:
                    if bottom - 0.5 <= z <= cut + 0.05:
                        seg = (tuple(round(x, 2) for x in a[:2]), tuple(round(x, 2) for x in b[:2]))
                        k = tuple(sorted(seg))
                        if k not in seen_land_edges:
                            seen_land_edges.add(k)
                            proj.append((a[:2], b[:2]))
        else:
            proj += [(a[:2], b[:2]) for z, a, b in stair_edges if bottom - 0.01 <= z <= cut + 0.01]
    return cuts, proj, regions, coloured, dashed
