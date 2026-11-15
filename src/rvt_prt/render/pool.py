"""Printing a set of sheets: to a PDF, or as drawing.Drawing for export, in forked workers."""
import gc
import json
import math
import pathlib


from .. import pdf
from . import state
from .annotate import tag_axes
from .primitives import PT
from .sheet import draw_sheet


_PARALLEL_CTX = None


def _render_worker(args):
    idx, s, tb, fmt = args
    # collections rarer: a sheet's drawing makes many short-lived objects, and each pass over them
    # cost Snowdon's 18 sheets 5% of their time (95 s at the defaults, 90 s so; and with none)
    gc.set_threshold(50_000, 20, 100)
    footprints, notes, tags, axes, curves, project, images, schedules = _PARALLEL_CTX
    if fmt == "drawings":
        d = sheet_drawing(s, footprints, notes, tags, axes, curves, tb, project, images, schedules)
        _keep_selections()
        return idx, d
    doc = pdf.new_document()
    draw_sheet(doc, s, footprints, notes, tags, axes, curves, tb, project, images, schedules)
    _keep_selections()
    if fmt == SHEET_FILE:  # the sheet's own file, finished here, alongside the other sheets
        return idx, _finished(doc, [s])
    # one file of every sheet: each page finished here too (its fonts subset, its streams
    # deflated), on this sheet's core; the parent then only joins the pages (Snowdon's 18:
    # 6.3 s of subsetting and deflating 230 MB in the parent, 1.2 s joining; the file 5% larger,
    # each page with its own subset of a font)
    return idx, pdf.finished_bytes(doc, [])


def _keep_selections():
    """Each model's saved-graphics selections this process worked out, kept for the next print."""
    for item in state.LINK_ITEMS:
        saved = getattr(item[2], "saved", None) if item else None
        if saved is not None:
            saved.write_selections()


def _take_selections():
    """Each model's selections kept so far (_keep_selections of the sheets already drawn), taken
    up by this process for the sheet processes it starts next."""
    for item in state.LINK_ITEMS:
        saved = getattr(item[2], "saved", None) if item else None
        if saved is not None:
            saved.read_selections(gather=False)


SHEET_FILE = "pdf-file"  # a task's format: the sheet's own PDF file, as _save writes it


def _parallel(tasks, workers, seconds=None, memory=None):
    """_render_worker over `tasks`, each sheet in a process of its own forked from this one, at most
    `workers` at a time, each capped (_attempt): a sheet that outgrows its share is tried again
    with fewer at once, down to alone with all the memory there is; failing that, drawn without
    its section and elevation linework (the heavy part: Golden Nugget's views of 2M lines and 15M
    triangles); failing that too, left a blank page saying so. Nothing is drawn in this process,
    whose memory no cap bounds: an 8 GB machine ran out of it redrawing failed sheets here. Results in task order;
    `seconds` ({sheet number: s}) gets each sheet's time drawn in full (its process's start to its result);
    `memory` ({sheet number: bytes}) holds what each sheet's process grew by when last drawn, and gets
    what it grew by now (_attempt)."""
    from ..core import progress
    bar = progress.Bar(len(tasks))
    results, failed = _attempt(tasks, workers, bar=bar, seconds=seconds, memory=memory)
    for light, then in ((True, "drawing it without its section and elevation linework"), (None, "leaving its page blank")):
        for t, why in failed:
            progress.say(f"rvt-prt: sheet {t[1].number} failed in a render worker ({why}); {then}")
        if light is None:
            results.update((t[0], _blank(t)) for t, _why in failed)
            bar.update(bar.done + len(failed), note=f"{len(failed)} sheet(s) left blank")
            break
        if not failed:
            break
        more, failed = _attempt([t for t, _why in failed], 1, light, bar=bar)
        results.update(more)
    bar.close()
    return [(i, results[i]) for i, *_ in tasks]


def _attempt(tasks, workers, light=False, bar=None, seconds=None, memory=None):
    """({task index: result}, [(task, why it failed)]): each task's sheet drawn in a forked process,
    at most `workers` at a time, each capped (RLIMIT_AS) at this process's address space plus its
    share of MemAvailable less linkgeom.reserve() (an 8 GB machine restarted on two 3 GB section sheets). A sheet
    short of memory halves the processes at once, and is tried again first, with the larger share
    (Golden Nugget's seven section sheets each failed at a quarter, then waited to go alone); it
    fails for good only alone. A fresh process per sheet, not a pool: a pooled worker kept one
    sheet's heap into the next under the same cap, and one that died broke the pool for every
    sheet left. `light`: sections drawn without their model linework. `bar` (progress.Bar) shows
    the sheets drawn; `seconds` ({sheet number: s}) gets the time of each drawn. `memory` ({sheet
    number: bytes}): what each sheet's process grew by when last drawn, by which the next starts
    without waiting (_needs); it gets what each grows by now."""
    import multiprocessing
    import multiprocessing.connection
    import time
    from ..core import progress
    from ..geometry import linkgeom
    ctx = multiprocessing.get_context("fork")
    vm = _vm_size()
    budget = max(linkgeom._available() - linkgeom.reserve(), 0.5e9 * workers)
    pending, running, results, failed, stopped, late = list(tasks), {}, {}, [], set(), set()
    expect = dict(memory or {})  # as last drawn: `memory` itself is written to as sheets finish
    started = 0.0
    while pending or running:
        # a cap bounds each process's own growth, not the pages it copies from this one (Python's
        # refcounts write to them: ~200 MB each on rst_basic_sample_project), so the machine is
        # watched too: below floor() the largest sheet's process is stopped
        avail = linkgeom._available()
        if running and avail < floor(len(running) == 1):
            r = max(running, key=lambda r: _rss(running[r][0].pid))
            running[r][0].kill()
            stopped.add(r)
        if SHEET_TIMEOUT:
            for r, (proc, _t, _share, t0) in running.items():
                if r not in stopped and r not in late and time.monotonic() - t0 > SHEET_TIMEOUT:
                    proc.kill()
                    late.add(r)
        # one more at a time, once the last has had RAMP s to grow: started together on one reading
        # of MemAvailable, four took a 4 GB machine from 1.8 GB free to under 0.7 in 18 s
        # ... unless there is room for every sheet running and one more to grow as they did when
        # last drawn (_needs; ROOMY each where that is not known): sheets of a second or two each,
        # a second apart, kept four cores to two and a half, and would a laptop's eight to three
        roomy = bool(pending) and avail - floor() > sum(_needs(v[1], expect) for v in running.values()) + _needs(pending[0], expect)
        began = False
        if pending and len(running) < workers and (not running or roomy or (avail > 2 * floor() and time.monotonic() - started > RAMP)):
            began = True
            t = pending.pop(0)
            _take_selections()  # what the sheets drawn so far worked out, for this one
            r, w = ctx.Pipe(duplex=False)
            proc = ctx.Process(target=_sheet_process, args=(t, w, vm + int(budget / workers) if vm else None, light))
            proc.start()
            w.close()
            running[r] = (proc, t, workers, time.monotonic())
            started = time.monotonic()
        if bar is not None:
            bar.update(bar.done, [v[1][1].number for v in running.values()], free=avail)
        # no wait after starting one where another may start at once
        for r in multiprocessing.connection.wait(list(running), timeout=0 if began and pending and len(running) < workers else 0.25):
            proc, t, share, t0 = running.pop(r)
            try:
                ok, value, grown = r.recv()  # before join: a large result fills the pipe
            except EOFError:
                ok, value, grown = False, None, 0
            r.close()
            proc.join()
            if ok:
                results[t[0]] = value
                if seconds is not None:
                    seconds[t[1].number] = round(time.monotonic() - t0, 2)
                if memory is not None and grown and not light:
                    memory[t[1].number] = int(grown)
                if bar is not None:
                    bar.update(bar.done + 1, [v[1][1].number for v in running.values()], f"sheet {t[1].number} drawn", avail)
                continue
            why = ("stopped: memory low" if r in stopped else f"stopped: over {SHEET_TIMEOUT:g} s" if r in late
                   else value or f"exit code {proc.exitcode}")
            if share > 1 and r not in late and _short_of_memory(why, proc.exitcode):
                workers = min(workers, share // 2)
                progress.say(f"rvt-prt: sheet {t[1].number} failed in a render worker ({why}); trying it again "
                             f"{'on its own' if workers == 1 else f'{workers} at a time'}")
                pending.insert(0, t)
            else:
                failed.append((t, why))
    return results, failed


RAMP = 1.0  # seconds between starting one sheet's process and the next (_attempt)
# bytes of memory free per sheet process, above floor(), with which the next starts without the
# ramp: what a sheet with a section of a whole building takes of its own (1.5 to 2 GB)
ROOMY = 2e9


def _needs(task, expect):
    """Bytes a sheet's process is allowed for when starting it without the ramp: half as much
    again as it grew by when last drawn, and 0.2 GB (it was drawn from kept linework then, perhaps,
    and is worked out now); ROOMY for a sheet not drawn before."""
    was = expect.get(task[1].number)
    return 1.5 * was + 0.2e9 if isinstance(was, (int, float)) and was > 0 else ROOMY
# Seconds a sheet's process may take before it is stopped (None: no limit). A sheet stopped is
# drawn again without its sections' model linework, and failing that left blank with a note, as
# one short of memory is. For files that are not trusted: a file can be made to take for ever.
SHEET_TIMEOUT = None


def _order(tasks, took):
    """`tasks` heaviest first (Longest Processing Time first), to balance the workers: by the
    seconds each sheet took when last drawn (`took`); a sheet never drawn first of all, by its
    viewports' scales (Snowdon by scales: M001 and M000, 1-2 s, went first, M101's 14 s last)."""
    return sorted(tasks, key=lambda t: (took.get(t[1].number, math.inf),
                                        sum(v.scale for v in t[1].viewports) if t[1].viewports else 0.01),
                  reverse=True)


def _seconds_file(path, what="seconds"):
    from ..core import paths
    return paths.CACHE / "cache" / f"{pathlib.Path(path).name}.sheet_{what}.json"


def sheet_seconds(path, what="seconds"):
    """{sheet number: seconds} each sheet of the model `path` last took to draw, or {}; with
    `what` "memory", the bytes its process grew by."""
    try:
        d = json.loads(_seconds_file(path, what).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _keep_seconds(path, seconds, what="seconds"):
    """Record the sheets' draw times (sheet_seconds), for the next print's order; with `what`
    "memory", what their processes grew by, for how soon the next print starts each."""
    if not path or not seconds:
        return
    try:
        f = _seconds_file(path, what)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({**sheet_seconds(path, what), **seconds}, indent=0, sort_keys=True))
    except OSError:
        pass


def _short_of_memory(why, exitcode):
    """Whether a sheet's process failed for want of memory: MemoryError (or numpy's allocation
    errors) at its cap, stopped by the watch, or killed by a signal (GEOS segfaults at the cap)."""
    return (exitcode or 0) < 0 or any(w in why for w in ("MemoryError", "allocate", "memory low"))


def _blank(task):
    """A sheet's page, blank but for a line saying it was too large to draw (_parallel's last resort)."""
    _idx, s, _tb, fmt = task
    doc = pdf.new_document()
    w, h = s.size
    page = doc.new_page(width=w * PT, height=h * PT)
    page.insert_text((36, 36), f"Sheet {s.number}: too large to draw in the memory available", fontsize=12, fontname="helv")
    if fmt == "drawings":
        from ..formats import drawing
        return drawing.from_page(page, s.number)
    return _finished(doc, [s]) if fmt == SHEET_FILE else pdf.document_bytes(doc)


def floor(alone=False):
    """Bytes of MemAvailable below which the largest sheet's process is stopped (_attempt): 1.25 GB
    of 8 (two 3 GB section sheets had restarted an 8 GB machine), 15% of less, 0.35 GB at least; a sheet
    drawing alone, 60% of that. On a 4 GB machine a fixed 1.25 GB was more than the model left
    free: every sheet was stopped, even alone, and left blank."""
    from ..geometry import linkgeom
    f = min(1.25e9, max(0.35e9, 0.15 * linkgeom._total()))
    return f * 0.6 if alone else f


def _rss(pid):
    """A process's resident bytes, else 0 (pages of the kernel's size: 16 KB on some ARM64 kernels)."""
    import os
    try:
        with open(f"/proc/{pid}/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError):
        return 0


def _sheet_process(task, conn, limit, light=False):
    """One sheet in a forked process: (True, result) or (False, the error's name) to `conn`.
    `light`: sections without their model linework (state.NO_SECTION_LINES)."""
    from ..geometry import linkgeom
    if limit:
        linkgeom._cap(limit)
    state.NO_SECTION_LINES = light
    import os
    began = _rss(os.getpid())
    try:
        value = _render_worker(task)[1]
        out = (True, value, max(_peak_rss() - began, 0) if began else 0)
    except BaseException as e:  # MemoryError at the cap, or anything else: the parent tries again lighter
        out = (False, f"{type(e).__name__}: {str(e)[:200]}" if str(e) else type(e).__name__, 0)
    conn.send(out)
    conn.close()


def _peak_rss():
    """This process's peak resident bytes (0 where it is not known)."""
    try:
        import resource
        import sys
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak if sys.platform == "darwin" else peak * 1024  # bytes on macOS, KB elsewhere
    except (ImportError, OSError, ValueError):
        return 0


def _vm_size():
    """This process's address space in bytes (VmSize), else 0."""
    try:
        with open("/proc/self/status") as f:
            return next(int(line.split()[1]) * 1024 for line in f if line.startswith("VmSize:"))
    except (OSError, StopIteration):
        return 0


def sheet_drawing(s, footprints, notes, tags, axes, curves, tb, project, images, schedules):
    """A sheet as a drawing.Drawing (inches): what draw_sheet draws, with the linked models'
    linework grouped by the element that drew it (state.RECORD) and the rest as the page draws it."""
    from ..formats import drawing
    state.RECORD = []
    state.RECORD_META.clear()
    try:
        page = draw_sheet(pdf.new_document(), s, footprints, notes, tags, axes, curves, tb, project, images, schedules, fit=False)
        d = drawing.from_page(page, s.number)
        d.prims = state.RECORD + d.prims
        if s.left:  # the paper's lower left the origin, as a sheet Drawing's is (Golden Nugget's sheets)
            d.prims = [drawing.transformed(p, (1.0, 0.0, 0.0, 1.0, -s.left * 12, 0.0)) for p in d.prims]
        d.meta = dict(state.RECORD_META)
    finally:
        state.RECORD = None
    return d


def write(sheets, out, footprints=None, notes=None, tags=None, curves=None, titleblock=None, project=None, images=None, tag_symbols=None, schedules=None, link_items=None, grids=None, plan_views=None, regions=None, invisible=None, room_tags=None, hidden=None, grid_types=None, sheet_annotations=None, hidden_filters=None, tag_style=None, workers=None, fmt="pdf", pen_path=None,
          separate=False, pages=False):
    """Draw the sheets to the PDF `out`, or with `separate` each to its own PDF in the directory
    `out` (sheet_file) and return their paths; with fmt "drawings", return them as
    [drawing.Drawing] (one per sheet, see sheet_drawing) instead; with `pages`, return each
    sheet's finished page (bytes) for pdf.joined_bytes, `out` unused (render.batches)."""
    global _PARALLEL_CTX
    state.ROOM_TAG_STYLE = tag_style
    state.PEN_PATH = pen_path
    state.HIDDEN.clear()
    state.HIDDEN.update(hidden or {})
    state.HIDDEN_FILTERS.clear()
    state.HIDDEN_FILTERS.update(hidden_filters or {})
    state.SHEET_ANNOTATIONS[:] = sheet_annotations or []
    state.GRID_TYPES.clear()
    state.GRID_TYPES.update(grid_types or {})
    state.ROOM_TAGS[:] = room_tags or []
    state.REGIONS[:] = regions or []
    state.INVISIBLE.clear()
    state.INVISIBLE.update(invisible or ())
    state.LINK_ITEMS[:] = link_items or []
    from .linework import _boxes
    for item in state.LINK_ITEMS:  # each model's plan boxes (linework.in_crop), once, before the sheets fork
        if item:
            _boxes(item[0])
    state.GRIDS[:] = grids or []
    state.PLAN_VIEWS.clear()
    state.PLAN_VIEWS.update(plan_views or ())
    axes = tag_axes(footprints)
    state.TAG_SYMBOLS.clear()
    state.TAG_SYMBOLS.update(tag_symbols or {})

    if workers is None:
        import os
        workers = min(os.cpu_count() or 1, len(sheets))

    import multiprocessing
    use_fork = hasattr(multiprocessing, "get_context") and "fork" in multiprocessing.get_all_start_methods()

    if use_fork:  # one sheet or one worker too: a sheet drawn here has no cap nor watch (_parallel)
        _PARALLEL_CTX = (footprints, notes, tags, axes, curves, project, images, schedules)
        task_fmt = SHEET_FILE if separate and fmt == "pdf" else fmt
        tasks = _order([(i, s, titleblock.get(s.number) if isinstance(titleblock, dict) else titleblock, task_fmt)
                        for i, s in enumerate(sheets)], sheet_seconds(pen_path))
        from ..core import progress
        progress.step(f"drawing {len(tasks)} sheet(s), up to {workers} at a time")
        gc.collect()
        gc.freeze()  # the workers' collections leave the parent's objects alone: their pages stay shared, not copied per worker
        seconds, memory = {}, sheet_seconds(pen_path, "memory") if pen_path else {}
        try:
            results = _parallel(tasks, workers, seconds, memory)
        finally:
            gc.unfreeze()
        _keep_seconds(pen_path, seconds)
        _keep_seconds(pen_path, memory, "memory")
        results = [b for _i, b in sorted(results, key=lambda t: t[0])]
        if fmt == "drawings":
            return results
        if task_fmt == SHEET_FILE:  # each file finished in its worker
            return _write_files(sheets, out, results)
        if pages:
            return results
        from ..core import progress
        progress.step(f"writing {out}")
        pathlib.Path(out).write_bytes(pdf.joined_bytes(results, [(s.number, i + 1) for i, s in enumerate(sheets)]))
        return
    elif fmt == "drawings":
        return [sheet_drawing(s, footprints, notes, tags, axes, curves,
                              titleblock.get(s.number) if isinstance(titleblock, dict) else titleblock, project, images, schedules)
                for s in sheets]
    else:
        docs = []
        for s in sheets:
            tb = titleblock.get(s.number) if isinstance(titleblock, dict) else titleblock
            docs.append(pdf.new_document())
            draw_sheet(docs[-1], s, footprints, notes, tags, axes, curves, tb, project, images, schedules)
        _keep_selections()

    from ..core import progress
    if separate:
        return _write_files(sheets, out, [_finished(d, [s]) for s, d in zip(sheets, docs)])
    if pages:
        return [pdf.finished_bytes(d, []) for d in docs]
    doc = pdf.new_document()
    for d in docs:
        doc.insert_pdf(d)
    progress.step(f"writing {out}")
    _save(doc, sheets, out)


def sheet_file(sheet, ext):
    """A sheet's own file name, as Revit names separate files: "<number> - <name>.<ext>", characters
    a file name cannot hold replaced by "_"."""
    name = f"{sheet.number} - {sheet.name}" if sheet.name else sheet.number
    return "".join(c if c.isalnum() or c in " -_.()" else "_" for c in name).strip(" .") + "." + ext


def _write_files(sheets, out, files):
    """Each sheet's finished PDF (`files`, bytes) to its own file in the directory `out`; their paths."""
    from ..core import progress
    progress.step(f"writing {len(sheets)} file(s) to {out}")
    paths = [pathlib.Path(out) / sheet_file(s, "pdf") for s in sheets]
    for f, data in zip(paths, files):
        f.write_bytes(data)
    return paths


def _finished(doc, sheets):
    """The PDF `doc` of `sheets` as its file's bytes: a bookmark per sheet, only the glyphs used embedded."""
    return pdf.finished_bytes(doc, [(s.number, i + 1) for i, s in enumerate(sheets)])


def _save(doc, sheets, out):
    """Save the PDF `doc` of `sheets` as `out` (_finished)."""
    pathlib.Path(out).write_bytes(_finished(doc, sheets))
