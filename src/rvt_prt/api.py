"""High-level public Python API for inspecting and printing Revit sheets."""
import pathlib
import sys
import time
from typing import Sequence

from .elements import annotations, families, fills, grids, images, patterns, roomtags, schedules, stairs, titleblock
from .metrics import bench
from .core import container, memory, progress
from .model import filters, layout, levels, phases, views
from .geometry import linkgeom, links, model2d
from . import render


def _model_caches(source, host_path):
    """Build the disk caches _prepare reads of one model (the host, or a link): a prefetch worker's
    task (linkgeom.prefetch), so that a cold print builds several models' at once, each in a
    fresh process. Keep it in step with _prepare's loop over the models."""
    from .elements import savedgraphics
    from .model import pens
    # rvt-rs meshes the file on a thread meanwhile; the lighter caches first, while it holds its memory
    linkgeom.start_meshing(source)
    pens.style_pens(str(source.path)), pens.style_colours(str(source.path)), pens.style_dashes(str(source.path))
    stairs.runs(source.path)
    phases.source_phases(host_path, source.path, getattr(source, "phase_map", None))
    if not isinstance(source, links.Host):
        families.view_owned(source.path)
    patterns.link_cut_patterns(source.path)
    savedgraphics.load(str(source.path))
    linkgeom.decoded(source)
    # what was decoded from the file is held no longer, before rvt-rs's meshes are taken up
    memory.forget(source.path)
    linkgeom.meshes(source)


def _prefetch(sources, jobs, task, ready):
    """linkgeom.prefetch of the models' caches (_model_caches), on a thread beside _prepare: each
    source is put on the queue `ready` once its caches are built (or left to be computed where they
    are read: what fails here is computed by _prepare instead), every one by the time it returns."""
    put = set()

    def done(source):
        if id(source) not in put:
            put.add(id(source))
            ready.put(source)
    try:
        linkgeom.prefetch(sources, jobs, task, _caches_built, _caches_need, on_done=done)
    except Exception as e:  # noqa: BLE001 - the caches are then built where they are read
        progress.say(f"rvt-prt: building the models' caches in workers failed ({type(e).__name__}: {e}); building them here")
    finally:
        for s in sources:
            done(s)


def _caches_stamp(source):
    """Where a model's caches are noted as built (_caches_built), and the key they were built for:
    the file's size and mtime and the package's source (every decoder; the extension's build)."""
    from .core import diskcache, paths
    st = source.path.stat()
    return paths.CACHE / "cache" / f"{source.file_name}.caches", f"{st.st_size} {st.st_mtime_ns} {diskcache.package_hash()}"


def _caches_built(source):
    """Whether a model's caches were built (_model_caches) by this code from this file, and its meshes are fresh."""
    try:
        f, key = _caches_stamp(source)
        return f.read_text() == key and linkgeom.fresh(linkgeom.CACHE / (source.file_name + ".npz"), source.path)
    except OSError:
        return False


def _caches_need(source):
    """A _model_caches worker's peak (resident, address space) bytes for its model."""
    mb = source.path.stat().st_size / 1e6
    return (linkgeom.CACHES_RSS_BASE + linkgeom.CACHES_RSS_PER_MB * mb,
            linkgeom.CACHES_VM_BASE + linkgeom.CACHES_VM_PER_MB * mb)


class NoSheets(LookupError):
    """No sheet of the model matches the request (or it has none)."""


def _open(path):
    """The file as a container.RevitFile, or UnsupportedFile saying in a line what it is instead:
    not a compound file at all, a damaged or cut-off one, or a compound file that is not Revit's."""
    import olefile.olefile
    name = pathlib.Path(path).name
    if not pathlib.Path(path).is_file():
        raise FileNotFoundError(f"no such file: {path}")
    try:
        rf = container.RevitFile(path)
    except olefile.olefile.NotOleFileError:
        raise container.UnsupportedFile(f"{name} is not a Revit file (it is not an OLE compound file)") from None
    except olefile.olefile.OleFileError as e:
        raise container.UnsupportedFile(f"{name} cannot be read: it is damaged or incomplete ({e})") from None
    except OSError:
        raise  # permissions and the like: the system's own message
    except Exception as e:  # noqa: BLE001 - olefile on a mangled header: ValueError, IndexError, struct.error
        raise container.UnsupportedFile(
            f"{name} cannot be read: it is damaged or incomplete ({type(e).__name__}: {e})") from None
    if not rf.ole.exists("BasicFileInfo"):
        raise container.UnsupportedFile(f"{name} is not a Revit file (it has no BasicFileInfo stream)")
    return rf


class RevitModel:
    """High-level Revit model representation for inspection and vector PDF sheet rendering."""

    def __init__(self, path: str | pathlib.Path):
        """Open the Revit project at `path`. Raises FileNotFoundError when there is no such file,
        and UnsupportedFile (a ValueError) when it is not a Revit file or cannot be read as one."""
        self.path = str(path)
        self.rf = _open(self.path)
        self._sheets: list[layout.Sheet] | None = None

    @property
    def sheets(self) -> list[layout.Sheet]:
        """Discovered printable sheets in the model."""
        if self._sheets is None:
            try:
                self._sheets = layout.sheets(self.rf, self.path)
            except container.DamagedFile:
                raise
            except container.UnsupportedFile:
                self._sheets = []
            release = container.revit_release(self.path)
            if not self._sheets and (release is None or release < container.SHEET_RELEASES[0]):
                lo, hi = container.SHEET_RELEASES
                build = None if release else container.revit_build(self.path)
                saved_by = f"Revit {release}" if release else "an older Revit release" + (f" (build {build})" if build else "")
                raise container.UnsupportedFile(
                    f"{pathlib.Path(self.path).name} is from {saved_by}: "
                    f"rvt-prt reads the sheets of Revit {lo}-{hi} files only")
        return self._sheets

    def get_sheet(self, sheet_number: str) -> layout.Sheet | None:
        """Find a sheet by its sheet number (e.g. 'M101')."""
        for s in self.sheets:
            if s.number == sheet_number:
                return s
        return None

    def render_to_pdf(
        self,
        output_path: str | pathlib.Path,
        sheet_numbers: Sequence[str] | None = None,
        workers: int | None = None,
        benchmark: bool = False,
        geometry_jobs: int | None = None,
        sheet_timeout: float | None = None,
    ) -> dict:
        """Render model sheets to a high-quality vector PDF.

        Args:
            output_path: Target PDF file path, or a directory (a path without the .pdf extension):
                each sheet then goes to its own file in it, "<number> - <name>.pdf".
            sheet_numbers: Optional subset of sheet numbers to render (e.g. ['M101', 'M102']).
            workers: Number of concurrent parallel worker processes (defaults to CPU count).
            benchmark: If True, record and return stage timing benchmarks.
            geometry_jobs: Models and links whose caches are built at once when cold, each in its
                own process (linkgeom.prefetch): default RVT_PRT_GEOMETRY_JOBS, else 0, as many
                as the cores and the available memory allow; 1 = one by one, in this process.
            sheet_timeout: Seconds a sheet may take to draw before it is stopped (drawn again
                without its sections' model linework, else left blank with a note). Default
                RVT_PRT_SHEET_TIMEOUT, else no limit. For files that are not trusted.

        Returns:
            Dict containing render metadata and stage timings.
        """
        return self._output("pdf", output_path, sheet_numbers, workers, benchmark, geometry_jobs, sheet_timeout)

    def render_to_dwfx(self, output_path, sheet_numbers=None, workers=None, benchmark=False, geometry_jobs=None,
                       sheet_timeout=None) -> dict:
        """Render sheets to a DWFx (XPS) package: the PDF's content, with the linked models'
        linework grouped by the element that drew it (see dwfx.py). A directory `output_path` (no
        .dwfx extension): one package per sheet in it, "<number> - <name>.dwfx"."""
        return self._output("dwfx", output_path, sheet_numbers, workers, benchmark, geometry_jobs, sheet_timeout)

    def export_dxf(self, output_dir, sheet_numbers=None, benchmark=False, geometry_jobs=None) -> dict:
        """Write each plan view placed on the sheets as `<view name>.dxf` in model feet, family
        instances as blocks (see export.py), for comparison with Revit's DXF export of the view."""
        return self._output("dxf", output_dir, sheet_numbers, None, benchmark, geometry_jobs)

    def view_drawings(self, sheet_numbers=None) -> dict:
        """{sheet number: [Drawing]}: each sheet's plan views as export_dxf writes them (model
        feet, family instances as blocks), kept in memory."""
        target_sheets = [s for s in self.sheets if not sheet_numbers or s.number in sheet_numbers]
        link_list = self._links()
        timer = bench.Timer(self.path, [s.number for s in target_sheets], False)
        return self._view_drawings(target_sheets, self._prepare(target_sheets, link_list, timer))

    def _links(self):
        """The model's links whose files are found; a warning for each file that is not (its
        elements are then left out of every view)."""
        found, missing = [], {}
        for l in links.read(self.rf, self.path):
            if l.path:
                found.append(l)
            else:
                missing.setdefault(l.file_name, (l, []))[1].append(l.name)
        for file_name, (l, names) in missing.items():
            print(f"rvt-prt: warning: linked model {file_name} not found (link instance{'s' if len(names) > 1 else ''} "
                  f"{', '.join(repr(n) for n in names)}); its elements are left out of the sheets. "
                  f"Looked in: {', '.join(str(f) for f in l.folders)}; or set RVT_PRT_LINKS to its folder",
                  file=sys.stderr)
        return found

    def _batched(self, fmt, output_path, separate, target_sheets, sources, args, need, limit, workers, timer):
        """The sheets drawn in groups (render.batches.plan), each with the models its sheets show
        loaded and the others dropped (memory.unload); the files written, as _output writes them
        drawn together. The host's own geometry (args' link items) stays loaded throughout."""
        from .render import batches
        from .render.pool import sheet_file
        host = args["link_items"][0]
        boxes = {}
        with timer.stage("link meshes", say=False):
            for k, l in enumerate(sources[1:], 1):
                boxes[k] = batches.extent(linkgeom.meshes(l))  # where it lies, its geometry dropped again
                memory.unload(l.path)
        shows = batches.sheet_models(target_sheets, boxes)
        groups = batches.plan(target_sheets, shows, need, limit - need.get(0, 0))
        loaded, pages, drawings, seen, written = {}, {}, {}, set(), []
        for g, (sheets, models) in enumerate(groups):
            for k in [k for k in loaded if k not in models]:
                del loaded[k]
                memory.unload(sources[k].path)
            for k in sorted(models):
                if k not in loaded:
                    progress.step(f"group {g + 1}/{len(groups)}: loading {sources[k].path.name}")
                    loaded[k] = self._load_model(sources[k], args["footprints"], timer)
            progress.step(f"group {g + 1}/{len(groups)}: {len(sheets)} sheet(s), {len(models)} linked model(s)")
            a = dict(args, link_items=[host] + [loaded[k] for k in sorted(loaded)])
            if fmt == "pdf" and separate:
                written += render.write(sheets, str(output_path), workers=workers, separate=True, **a)
            elif fmt == "pdf":
                pages.update(zip((s.number for s in sheets), render.write(sheets, None, workers=workers, pages=True, **a)))
            elif fmt == "dwfx":
                drawings.update(zip((s.number for s in sheets), render.write(sheets, None, workers=workers, fmt="drawings", **a)))
            else:
                from .formats import dxf
                for views in self._view_drawings(sheets, a).values():
                    for d in views:
                        if d.name not in seen:
                            seen.add(d.name)
                            f = output_path / ("".join(c if c.isalnum() or c in " -_." else "_" for c in d.name) + ".dxf")
                            dxf.write(d, f)
                            written.append(f)
        for k in list(loaded):
            memory.unload(sources[k].path)
        if fmt == "pdf" and not separate:
            from . import pdf
            progress.step(f"writing {output_path}")
            pathlib.Path(output_path).write_bytes(pdf.joined_bytes(
                [pages[s.number] for s in target_sheets], [(s.number, i + 1) for i, s in enumerate(target_sheets)]))
            written.append(output_path)
        elif fmt == "dwfx":
            from .formats import dwfx
            if separate:
                for s in target_sheets:
                    written.append(output_path / sheet_file(s, "dwfx"))
                    dwfx.write([drawings[s.number]], written[-1])
            else:
                dwfx.write([drawings[s.number] for s in target_sheets], output_path)
                written.append(output_path)
        return written

    @staticmethod
    def _view_drawings(target_sheets, args):
        from .formats import export
        out, done = {}, {}
        for s in target_sheets:
            for v in s.viewports:
                if v.view_id not in done:
                    done[v.view_id] = export.view_drawing(v, args["link_items"], args["footprints"],
                                                          args["hidden"].get(v.view_id, frozenset()),
                                                          args["hidden_filters"].get(v.view_id, ()))
                if done[v.view_id] is not None:
                    out.setdefault(s.number, []).append(done[v.view_id])
        return out

    def _load_model(self, l, footprints, timer):
        """One model's (the host's, or a link's) entry of render's link items: its meshes, cut
        patterns, saved graphics (families.Symbols), stair edges and pen colour, from its caches;
        what decoding it left is dropped (memory.forget), and the memory it holds is noted for the
        next print's sheet batches (render.batches)."""
        from .render import batches
        before = batches.resident()
        with timer.stage("link meshes", say=False):
            meshes = linkgeom.meshes(l)
        with timer.stage("link patterns", say=False):
            cut = patterns.link_cut_patterns(l.path)
        with timer.stage("saved graphics", say=False):
            fam = families.Symbols()
            from .elements import savedgraphics
            import numpy as np
            fam.saved = savedgraphics.load(str(l.path))
            fam.saved.read_selections()  # what earlier prints worked out, shared by the sheet processes
            from .model import pens  # built here, before the render workers fork (their disk caches)
            pens.style_pens(str(l.path)), pens.style_colours(str(l.path)), pens.style_dashes(str(l.path))
            fam.place = np.eye(4)
            fam.place[:3, :3], fam.place[:3, 3] = np.array(l.axes, dtype=float).T, np.array(l.origin, dtype=float)
        with timer.stage("link stairs", say=False):
            edges = stairs.plan_edges(stairs.runs(l.path), l.axes, l.origin)
        with timer.stage("phases", say=False):
            of = phases.source_phases(self.path, l.path, getattr(l, "phase_map", None))
            meshes = [i._replace(phase=of[i.tag]) if i.tag in of else i for i in meshes]
        if not isinstance(l, links.Host):
            # a link's view-specific elements (detail items, annotation symbols) never show
            owned = families.view_owned(l.path)
            meshes = [i for i in meshes if i.tag not in owned]
        if isinstance(l, links.Host):
            # the host's own elements: a family instance with saved graphics draws from them
            # here, in place of its footprint box; the rest stay with the footprints (model2d)
            drawn = {fp.element_id for fp in footprints}
            meshes = [i for i in meshes if i.tag in fam.saved.instances or i.tag not in drawn]
            for fp in footprints:
                fp.saved = fp.element_id in fam.saved.instances
        entry = (meshes, cut, fam, edges, render.LINK_GREY if l.halftone else (0.0, 0.0, 0.0))
        if not isinstance(l, links.Host):
            # what decoding the link left (a cold print builds its caches from it; a warm
            # one never holds it): Snowdon's, kept, took a cold print's parent to 2.4 GB
            memory.forget(l.path)
        batches.note_model_memory(self.path, l, batches.resident() - before)
        return entry

    def _prepare(self, target_sheets, link_list, timer, ready=None, load_links=True):
        """Everything render.write draws, decoded (each stage timed): the model's own first, then
        each model's and link's in the order the queue `ready` gives them (prefetch's, as their
        caches are built; None: in order). With `load_links` False, the links' caches are waited
        for but not loaded: the sheet batches load each for the sheets that show it (render.batches)."""
        with timer.stage("levels"):
            render.STOREYS_FT.update(levels.read(self.rf, self.path))

        with timer.stage("title blocks"):
            tbs = titleblock.for_sheets(self.rf, self.path, target_sheets)
            project = titleblock.project_params(
                self.rf, self.path,
                {lbl.param for tb in tbs.values() if tb for lbl in tb.labels}
            )

        with timer.stage("annotations"):
            tag_list = annotations.tags(self.rf, self.path)
            notes = annotations.text_notes(self.rf, self.path)
            curves = annotations.detail_curves(self.rf, self.path)
            tag_symbols = titleblock.symbols_by_id(self.rf, self.path, {t.symbol_id for t in tag_list})

        with timer.stage("MEP footprints"):
            footprints = model2d.footprints(self.rf, self.path)

        with timer.stage("images"):
            placed_images = images.placed(self.rf, self.path)

        with timer.stage("schedules"):
            # every sheet of the model: a sheet list lists them all, whichever are printed
            scheds = schedules.on_sheets(self.rf, self.path, self.sheets, render.STOREYS_FT)

        with timer.stage("pens"):
            from .model import pens
            pens.table(self.path), pens.category_pens(self.path), pens.category_colours(self.path), pens.category_dashes(self.path)
            # read here, not first in a forked render worker: workers share the model's open file
            # (a first read there garbled another's: zlib "invalid distance too far back")
            from .elements import datums
            datums.read(self.path)

        with timer.stage("grids"):
            grid_list = grids.read(self.rf, self.path)
            plan_ids = grids.plan_view_ids(self.rf, self.path)
            grid_types = grids.grid_types(self.rf, self.path)

        with timer.stage("filled regions"):
            regions = fills.read(self.rf, self.path)
            invisible = fills.invisible_curves(self.rf, self.path)

        with timer.stage("room tags"):
            room_tags = roomtags.read(self.rf, self.path)
            tag_style = roomtags.tag_style(self.rf, self.path)

        with timer.stage("visibility"):
            hidden = {
                v.view_id: views.hidden_categories(self.rf, self.path, v.view_id)
                or views.hidden_categories(self.rf, self.path, v.template_id)
                for s in target_sheets for v in s.viewports
            }

        with timer.stage("detail levels"):
            for s in target_sheets:
                for v in s.viewports:
                    v.detail_level = views.detail_level(self.rf, self.path, v.view_id)
                    v.phase = phases.view_table(self.path, v.view_id)

        with timer.stage("view filters"):
            hidden_filters = {
                v.view_id: filters.hidden_in_view(self.rf, self.path, v.view_id)
                or filters.hidden_in_view(self.rf, self.path, v.template_id)
                for s in target_sheets for v in s.viewports
            }

        with timer.stage("annotation families"):
            sheet_annotations = families.sheet_annotations(self.path)

        # the models' caches: built by prefetch's workers while this process read the above
        sources = [links.Host(pathlib.Path(self.path))] + link_list
        if ready is None:
            import queue
            ready = queue.Queue()
            for l in sources:
                ready.put(l)
        link_items = [None] * len(sources)  # in the sources' order, whichever is read first
        for n in range(len(sources)):
            with timer.stage("link meshes", say=False):
                l = ready.get()
            k = next(i for i, s in enumerate(sources) if s is l or (s.path == l.path and link_items[i] is None))
            if not load_links and k > 0:
                link_items[k] = False  # built, not loaded: the sheet batches load it (render.batches)
                continue
            progress.step(f"model {n + 1}/{len(sources)}: {l.path.name}: meshes, patterns, saved graphics, stairs, phases")
            link_items[k] = self._load_model(l, footprints, timer)
        link_items = [item for item in link_items if item is not False]

        return dict(
            footprints=footprints, notes=notes, tags=tag_list, curves=curves, titleblock=tbs, project=project,
            images=placed_images, tag_symbols=tag_symbols, schedules=scheds, link_items=link_items, grids=grid_list,
            plan_views=plan_ids, regions=regions, invisible=invisible, room_tags=room_tags, hidden=hidden,
            grid_types=grid_types, sheet_annotations=sheet_annotations, hidden_filters=hidden_filters, tag_style=tag_style,
            pen_path=self.path,
        )

    def _output(self, fmt, output_path, sheet_numbers, workers, benchmark, geometry_jobs=None, sheet_timeout=None):
        import os

        from .render import pool
        if sheet_timeout is None and os.environ.get("RVT_PRT_SHEET_TIMEOUT"):
            sheet_timeout = float(os.environ["RVT_PRT_SHEET_TIMEOUT"])
        pool.SHEET_TIMEOUT = sheet_timeout or None
        output_path = pathlib.Path(output_path)
        # a file per sheet unless the output names one file (dxf: a file per view, always)
        separate = fmt != "dxf" and output_path.suffix.lower() != "." + fmt
        (output_path if fmt == "dxf" or separate else output_path.parent).mkdir(parents=True, exist_ok=True)

        t0 = time.perf_counter()
        progress.step("reading the sheets and their viewports")
        target_sheets = [
            s for s in self.sheets
            if not sheet_numbers or s.number in sheet_numbers
        ]
        if not target_sheets:
            raise NoSheets(f"no sheets to print in {pathlib.Path(self.path).name}"
                              + (f" numbered {', '.join(sheet_numbers)}" if sheet_numbers else ""))
        layout_sec = time.perf_counter() - t0

        link_list = self._links()
        progress.step(f"{len(target_sheets)} sheet(s) to print; "
                      + (f"{len(link_list)} linked model(s): {', '.join(l.path.name for l in link_list)}" if link_list else "no linked models"))
        warm = all(linkgeom.fresh(linkgeom.CACHE / (l.file_name + ".npz"), l.path) for l in link_list)
        timer = bench.Timer(self.path, [s.number for s in target_sheets], warm)
        timer.start = t0
        timer.stages["layout"] = layout_sec
        sources = [links.Host(pathlib.Path(self.path))] + link_list
        import functools
        import queue
        import threading
        # the models' caches built in worker processes while this one reads the model's own
        # (_prepare reads each model's as its worker finishes)
        ready = queue.Queue()
        worker = threading.Thread(target=_prefetch, daemon=True, args=(
            sources, geometry_jobs, functools.partial(_model_caches, host_path=self.path), ready))
        worker.start()
        # the models together in memory, or the sheets in groups by the models they show
        from .render import batches
        need = {k: batches.model_need(self.path, s) for k, s in enumerate(sources)}
        limit = batches.budget()
        batched = len(sources) > 1 and sum(need.values()) > limit
        if batched:
            progress.step(f"the {len(sources)} models take about {sum(need.values()) / 1e9:.1f} GB together, more than "
                          f"{limit / 1e9:.1f} GB: the sheets are drawn in groups, each with the models it shows")
        args = self._prepare(target_sheets, link_list, timer, ready, load_links=not batched)
        worker.join()
        for s in sources:  # all built now, here or in prefetch's workers
            if s.path is not None:
                f, key = _caches_stamp(s)
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(key)

        written = []
        with timer.stage("render", say=False):
            if batched:
                written += self._batched(fmt, output_path, separate, target_sheets, sources, args, need, limit, workers, timer)
            elif fmt == "pdf" and separate:
                written += render.write(target_sheets, str(output_path), workers=workers, separate=True, **args)
            elif fmt == "pdf":
                render.write(target_sheets, str(output_path), workers=workers, **args)
                written.append(output_path)
            elif fmt == "dwfx":
                from .formats import dwfx
                from .render.pool import sheet_file
                drawings = render.write(target_sheets, None, workers=workers, fmt="drawings", **args)
                if separate:
                    for s, d in zip(target_sheets, drawings):
                        written.append(output_path / sheet_file(s, "dwfx"))
                        dwfx.write([d], written[-1])
                else:
                    dwfx.write(drawings, output_path)
                    written.append(output_path)
            else:
                from .formats import dxf
                seen = set()
                for drawings in self._view_drawings(target_sheets, args).values():
                    for d in drawings:
                        if d.name in seen:
                            continue
                        seen.add(d.name)
                        f = output_path / ("".join(c if c.isalnum() or c in " -_." else "_" for c in d.name) + ".dxf")
                        dxf.write(d, f)
                        written.append(f)

        if fmt == "pdf":  # bench/prints*.jsonl track print times
            rec, prev = timer.record()
        else:
            rec, prev = {"total": round(time.perf_counter() - t0, 2), "peak_mb": None, "stages": dict(timer.stages)}, None
        summary = {
            "sheets_count": len(target_sheets),
            "output": str(output_path),
            "files": [str(f) for f in written],
            "elapsed_s": rec["total"],
            "peak_rss_mb": rec["peak_mb"],
            "stages": rec["stages"],
        }
        if benchmark and fmt == "pdf":
            print(bench.describe(rec, prev))
        return summary
