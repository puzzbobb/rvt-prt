"""Command-line interface for rvt-prt: list sheets, print them (PDF, DWFx, or DXF views),
compare drawings (ours against Revit's PDF, DWFx or DXF exports), and show or clear the caches."""
import argparse
import json
import sys
from typing import Sequence


def _compare(args):
    import pathlib

    from .formats import drawing
    for given in (args.reference, args.ours):
        if not pathlib.Path(given).exists():
            raise FileNotFoundError(f"no such file or directory: {given}")
    refs, ours = drawing.read(args.reference), drawing.read(args.ours)
    if args.blocks:  # family symbols: every block of each side, instances matched by element id
        rows = drawing.compare_blocks(drawing.merged(refs), drawing.merged(ours), args.step, args.tol)
        if args.json:
            print(json.dumps([dict(zip(("ours", "reference", "recall", "precision", "instances"), r)) for r in rows], indent=1))
        else:
            print("family blocks, in their own coordinates (recall, precision, instances matched by element id):")
            for name, rname, rc, pr, n in sorted(rows, key=lambda r: r[2] + r[3]):
                print(f"  {rc:6.1%} {pr:6.1%} {n:4}  {name} -> {rname or '(none found)'}")
        return 0
    pairs = drawing.pair(refs, ours)
    if args.sheet:
        pairs = [(r, o) for r, o in pairs if r.name in args.sheet or o.name in args.sheet]
    if not pairs:
        print(f"no drawings to compare: reference has {[d.name for d in refs]}, ours {[d.name for d in ours]}")
        return 1
    out = []
    for r, o in pairs:
        if r.units != o.units:
            print(f"{r.name}: reference is in {r.units}, ours in {o.units}: not comparable (a sheet against a view)")
            continue
        s = drawing.compare(r, o, args.step, args.tol, args.top)
        if args.json:
            out.append({**s.__dict__, "reference": r.name, "ours": o.name})
        else:
            print(drawing.report(s, r.units))
    if args.json:
        print(json.dumps(out, indent=1, default=str))
    return 0


def _filter(text):
    from .model import sheetparams
    try:
        sheetparams.parse(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None
    return text


def _where(parser):
    parser.add_argument("--where", action="append", type=_filter, metavar="FILTER", default=[],
                        help="only sheets whose parameter matches (repeatable; all must hold): NAME=VALUE "
                             "(* and ? wildcards), NAME!=VALUE or NAME~TEXT (contains), e.g. "
                             "--where \"Appears In Sheet List=Yes\" --where \"Sheet Group=Arch*\"")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rvt-prt",
        description="Fast, standalone vector sheet renderer for Autodesk Revit (.rvt) models",
    )
    from . import __version__
    ap.add_argument("--version", action="version", version=f"rvt-prt {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="list sheets and their viewports, or their parameters")
    ls.add_argument("model", help="path to the input .rvt Revit model file")
    _where(ls)
    ls.add_argument("--params", action="store_true", help="each sheet's parameters under it, those with a value")
    lf = ls.add_mutually_exclusive_group()
    lf.add_argument("--csv", action="store_true", help="every sheet's parameters as CSV, a column per parameter")
    lf.add_argument("--json", action="store_true", help="every sheet, its viewports and its parameters as JSON")
    pr = sub.add_parser("print", help="print sheets to PDF or DWFx, or their plan views to DXF")
    pr.add_argument("model", help="path to the input .rvt Revit model file")
    pr.add_argument("-o", "--output", default=None,
                    help="output directory, each sheet to its own file '<number> - <name>.<format>' "
                         "(default out/sheets; dxf: each view, default out/dxf), or a .pdf / .dwfx file "
                         "holding every sheet")
    pr.add_argument("-f", "--format", choices=["pdf", "dwfx", "dxf"], default=None,
                    help="output format (default: from the output's extension, else pdf)")
    pr.add_argument("--sheet", action="append", dest="sheets", help="sheet number to print (repeatable, e.g. --sheet M101)")
    _where(pr)
    pr.add_argument("-j", "--jobs", type=int, default=None, help="parallel render worker processes (default cpu_count)")
    pr.add_argument("-q", "--quiet", action="store_true", help="no progress: only warnings and the summary")
    pr.add_argument("--geometry-jobs", type=int, default=None,
                    help="models and links whose caches are built at once, each in its own process, when they are cold "
                         "(default RVT_PRT_GEOMETRY_JOBS, else 0: as many as cores and memory allow; 1 = one at a time in this process)")
    pr.add_argument("--sheet-timeout", type=float, default=None, metavar="SECONDS",
                    help="stop a sheet that takes longer to draw (it is drawn again without its sections' model "
                         "linework, else left blank with a note); default RVT_PRT_SHEET_TIMEOUT, else no limit")
    pr.add_argument("--memory-limit", type=float, default=None, metavar="GB",
                    help="the most address space this process and each of its workers may take; past it the print "
                         "stops with a message (for files that are not trusted; Linux and macOS)")
    ic = sub.add_parser("ifc", help="export a model to IFC4 with rvt-rs (as its rvt-ifc tool does)")
    ic.add_argument("model", help="path to the input .rvt Revit model file")
    ic.add_argument("-o", "--output", required=True, help="the .ifc file to write")
    ic.add_argument("--saved-meshes", action="store_true",
                    help="family instances as their saved meshes instead of boxes (large models need over 4 GB)")
    cp = sub.add_parser("compare", help="compare drawings line by line: a reference (Revit's export) against ours")
    cp.add_argument("reference", help="Revit's drawing: a .pdf, .dwfx or .dxf file, or a directory of them")
    cp.add_argument("ours", help="our drawing: a .pdf, .dwfx or .dxf file, or a directory of them")
    cp.add_argument("--sheet", action="append", help="only these sheet numbers or view names (repeatable)")
    cp.add_argument("--tol", type=float, default=None, help="match tolerance (in for sheets, ft for views; default 0.03 / 0.05)")
    cp.add_argument("--step", type=float, default=None, help="sampling step along lines (default 0.01 in / 0.02 ft)")
    cp.add_argument("--top", type=int, default=15, help="worst groups listed per side (default 15)")
    cp.add_argument("--blocks", action="store_true", help="compare family blocks in their own coordinates instead (DXF: Revit's sheet export against our view export)")
    cp.add_argument("--json", action="store_true", help="print the scores as JSON")
    ca = sub.add_parser("cache", help="show what the cache folder holds per model, or clear it")
    ca.add_argument("--clear", nargs="*", metavar="MODEL", default=None,
                    help="remove the entries of these model files (a path or a file name) or groups the listing names "
                         "('(bench)', '(unfinished)', '(fonts)'), or with none named every entry; printed sheets are never touched")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if getattr(args, "memory_limit", None):
        return _limited(args)
    return _guarded(args)


def _limited(args):
    """The print in a child process under `--memory-limit` (RLIMIT_AS), its outcome said here. In
    a child because what runs out of memory in the native extension (rvt-rs) aborts the process,
    where Python could not report it: here a child that dies so is one line, like any other."""
    import os
    try:
        import resource
    except ImportError:
        print("rvt-prt: warning: --memory-limit not applied (no address-space limits on this system)", file=sys.stderr)
        return _guarded(args)
    limit = int(args.memory_limit * 2**30)
    try:  # loaded before the limit applies: mapping it is not what a limit is for
        from . import _native  # type: ignore[attr-defined]  # noqa: F401
    except ImportError:
        pass
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            code = _guarded(args)
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(code)
    _pid, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    sig = os.WTERMSIG(status)
    if sig in (6, 9, 11):  # SIGABRT (the native extension out of memory), SIGKILL, SIGSEGV (a library at the cap)
        print(f"rvt-prt: out of memory within --memory-limit {args.memory_limit:g} GB (the print was stopped)", file=sys.stderr)
    else:
        print(f"rvt-prt: the print was stopped by signal {sig}", file=sys.stderr)
    return 1


def _guarded(args):
    """The command, any failure one line on stderr and exit status 1."""
    from .api import NoSheets
    from .core.container import UnsupportedFile
    try:
        return _run(args)
    except (UnsupportedFile, NoSheets, OSError) as e:
        # a file that is missing, not Revit's, damaged, or cannot be written: one line, no traceback
        print(f"rvt-prt: {e}", file=sys.stderr)
        return 1
    except MemoryError:
        limit = getattr(args, "memory_limit", None)
        print(f"rvt-prt: out of memory{f' within --memory-limit {limit:g} GB' if limit else ''}", file=sys.stderr)
        return 1
    except ImportError as e:  # a library that cannot be mapped into what the limit leaves
        limit = getattr(args, "memory_limit", None)
        if not limit:
            raise
        print(f"rvt-prt: out of memory within --memory-limit {limit:g} GB (loading {e.name or 'a library'})", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - what a file's contents led to, short of the above
        import os
        if os.environ.get("RVT_PRT_DEBUG"):
            raise
        print(f"rvt-prt: could not {args.command} {getattr(args, 'model', '') or 'it'}: {type(e).__name__}: {str(e)[:200]} "
              "(the file may be damaged; set RVT_PRT_DEBUG=1 for the traceback)", file=sys.stderr)
        return 1


def _run(args):
    if args.command == "compare":
        return _compare(args)
    if args.command == "cache":
        from .core import cachedir
        if args.clear is None:
            print(cachedir.report())
            return 0
        done = cachedir.clear(args.clear)
        print(f"removed {len(done)} entries, {sum(n for _p, n in done) / 2**20:.1f} MB")
        return 0
    if args.command == "ifc":
        import pathlib

        from . import _native  # type: ignore[attr-defined]  # the compiled extension
        if not pathlib.Path(args.model).is_file():
            raise FileNotFoundError(f"no such file: {args.model}")
        diagnostics = json.loads(_native.export_ifc(args.model, args.output, args.saved_meshes))
        exported = diagnostics["exported"]
        print(f"wrote {args.output}: {exported['building_elements']} building elements, "
              f"{exported['building_elements_with_geometry']} with geometry")
        return 0
    return _model_command(args)


def _model_command(args):
    from .api import RevitModel
    from .core import progress
    from .render import scale_text
    if args.command == "print":
        progress.enable(not args.quiet)
        progress.step(f"opening {args.model}")
    model = RevitModel(args.model)
    try:
        chosen = model.select_sheets(args.where)
    except LookupError as e:  # a parameter name no sheet has
        print(f"rvt-prt: {e}", file=sys.stderr)
        return 1
    if args.where and model.sheets and not chosen:
        print(f"rvt-prt: no sheet of {args.model} matches " + " and ".join(f'"{w}"' for w in args.where),
              file=sys.stderr)
        return 1

    if args.command == "list":
        if not model.sheets:
            print(f"rvt-prt: {args.model} has no sheets", file=sys.stderr)
        params = model.sheet_parameters if args.params or args.csv or args.json else {}
        if args.csv:
            import csv
            columns = list(dict.fromkeys(n for s in chosen for n in params[s.number]))
            w = csv.writer(sys.stdout, lineterminator="\n")
            w.writerow(columns)
            for s in chosen:
                w.writerow([params[s.number].get(c, "") for c in columns])
            return 0
        if args.json:
            print(json.dumps([{"number": s.number, "name": s.name,
                               "size_in": [round(s.size[0] * 12, 2), round(s.size[1] * 12, 2)],
                               "viewports": [{"detail": v.detail, "view": v.view_name, "scale": scale_text(v.scale)}
                                             for v in s.viewports],
                               "parameters": params[s.number]} for s in chosen], indent=2, ensure_ascii=False))
            return 0
        for s in chosen:
            vps_str = "; ".join(f"{v.detail} {v.view_name} ({scale_text(v.scale)})" for v in s.viewports)
            print(f"{s.number:6} {s.name:32} {s.size[0] * 12:.1f} x {s.size[1] * 12:.1f} in  viewports: {vps_str}")
            for name, value in params.get(s.number, {}).items():
                if value and name not in ("Sheet Number", "Sheet Name"):
                    print(f"       {name}: {value}")
        return 0

    if args.where:  # the sheets the filters chose, of those --sheet names
        named = args.sheets
        args.sheets = [s.number for s in chosen if not named or s.number in named]
        if not args.sheets:  # never an empty list passed on: that would print every sheet
            print(f"rvt-prt: no sheet of {args.model} numbered {', '.join(named or [])} matches "
                  + " and ".join(f'"{w}"' for w in args.where), file=sys.stderr)
            return 1

    fmt = args.format or (args.output.rsplit(".", 1)[-1].lower() if args.output and args.output.lower().endswith((".pdf", ".dwfx")) else "pdf")
    output = args.output or {"pdf": "out/sheets", "dwfx": "out/sheets", "dxf": "out/dxf"}[fmt]
    if fmt == "pdf":
        summary = model.render_to_pdf(output_path=output, sheet_numbers=args.sheets, workers=args.jobs, benchmark=True,
                                     geometry_jobs=args.geometry_jobs, sheet_timeout=args.sheet_timeout)
    elif fmt == "dwfx":
        summary = model.render_to_dwfx(output, args.sheets, args.jobs, geometry_jobs=args.geometry_jobs,
                                       sheet_timeout=args.sheet_timeout)
    else:
        summary = model.export_dxf(output, args.sheets, geometry_jobs=args.geometry_jobs)
    print(f"wrote {summary['sheets_count']} sheets to {summary['output']}"
          + (f" ({len(summary['files'])} files)" if len(summary["files"]) > 1 or fmt == "dxf" else "")
          + f" in {summary['elapsed_s']:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
