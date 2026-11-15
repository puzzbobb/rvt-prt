"""Geometry benchmarks: the element meshes of model files (linkgeom's .npz cache) by each backend,
each measurement in a fresh process under an address-space cap, appended to bench/geometry.jsonl;
`summary` writes the tables of the latest runs to bench/geometry.md.

    python -m rvt_prt.metrics.geobench backends [--repeat 3] [files]
    python -m rvt_prt.metrics.geobench scaling [--jobs 1,2,3,4] [files]
    python -m rvt_prt.metrics.geobench versions [--corpus DIR]   one project per year folder
    python -m rvt_prt.metrics.geobench summary

Backend: `native` (rvt_prt._native.element_meshes; the ifcopenshell backends it was measured
against, `ifc`, `ifc-saved` and `subprocess`, were retired 2026-10-18 and remain in
bench/geometry.md's earlier tables). `scaling` is
linkgeom.prefetch + meshes() with `--geometry-jobs` N into an empty cache. Files default to
Snowdon's host and its 6 links; the corpus is the folder RVT_PRT_CORPUS
or --corpus names (one subfolder per year).

Each record: git SHAs (rvt_prt, rvt-rs), the run and its batch (start time), file, MB, Revit
version, backend or jobs, status, stage seconds, total, peak RSS of the process and of its
children (RUSAGE_CHILDREN), and the machine's peak use (fall in MemAvailable), elements, triangles.
"""
import argparse
import json
import os
import pathlib
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict

from ..core import paths
from . import rvtrs

LOG = paths.ROOT / "bench" / "geometry.jsonl"
SUMMARY = paths.ROOT / "bench" / "geometry.md"
BACKENDS = ("native",)
STAGES = ("ifc_write", "ifc_parse", "tessellate", "mesh", "npz_write")  # the retired backends' first three


def _git(*args, cwd=paths.ROOT):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=cwd).stdout.strip()
    except Exception:
        return ""


def _snowdon():
    host = paths.ROOT / "oracle" / "Snowdon Towers Sample HVAC.rvt"
    return [host] + sorted((paths.ROOT / "links").glob("Snowdon Towers Sample *.rvt"))


def _peaks():
    mb = lambda who: resource.getrusage(who).ru_maxrss // 1024
    return {"peak_mb": mb(resource.RUSAGE_SELF), "children_peak_mb": mb(resource.RUSAGE_CHILDREN)}


def _counts(items):
    return {"elements": len(items), "triangles": int(sum(len(i.faces) for i in items))}


# --- the measured processes -------------------------------------------------------------------

def one(backend, path):
    """One file's meshes by `backend` (native), timed by stage (this process: the parent caps it)."""
    from ..core import container
    from ..geometry import linkgeom
    stages, t0 = {}, time.perf_counter()

    def stage(name, f, *a):
        t = time.perf_counter()
        r = f(*a)
        stages[name] = round(time.perf_counter() - t, 3)
        return r

    try:
        caps = container.capabilities(path)
    except container.UnsupportedFile:
        caps = {"geometry": False, "revit_version": None}
    rec = {"revit_version": caps["revit_version"]}
    if not caps["geometry"]:
        return {**rec, "status": "fallback", "stages": {}, "total": 0.0, **_peaks()}
    with tempfile.TemporaryDirectory() as tmp:
        items = stage("mesh", linkgeom._native_items, pathlib.Path(path), {})
        stage("npz_write", linkgeom._save, os.path.join(tmp, "model.npz"), items)
    return {**rec, "status": "ok", "stages": stages, "total": round(time.perf_counter() - t0, 3),
            **_counts(items), **_peaks()}


def scale(jobs, files):
    """meshes() of `files` into an empty cache, prefetched `jobs` at a time."""
    from ..geometry import linkgeom, links
    with tempfile.TemporaryDirectory() as tmp:
        linkgeom.CACHE = pathlib.Path(tmp)
        sources = [links.Host(pathlib.Path(f)) for f in files]
        t0 = time.perf_counter()
        linkgeom.prefetch(sources, jobs)
        t1 = time.perf_counter()
        try:  # reap the forkserver (it reaps the workers), so RUSAGE_CHILDREN counts them
            from multiprocessing import forkserver
            forkserver._forkserver._stop()
        except Exception:
            pass
        items = [i for s in sources for i in linkgeom.meshes(s)]
        t2 = time.perf_counter()
    return {"status": "ok", "stages": {"prefetch": round(t1 - t0, 3), "meshes": round(t2 - t1, 3)},
            "total": round(t2 - t0, 3), **_counts(items), **_peaks()}


def _child_main(argv):
    kind, *rest = argv
    if kind == "_one":
        out = one(rest[0], rest[1])
    else:
        out = scale(int(rest[0]), rest[1:])
    print("\n" + json.dumps(out))


def _measure(kind, args, cap, timeout):
    """Run `kind args` in a fresh interpreter under RLIMIT_AS = `cap` bytes; its JSON result (or a
    failure) and the machine's peak use while it ran."""
    def limit():
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))

    avail0 = _available()
    low = [avail0]
    done = threading.Event()

    def sample():
        while not done.wait(0.2):
            low[0] = min(low[0], _available())

    threading.Thread(target=sample, daemon=True).start()
    t0 = time.perf_counter()
    try:
        p = subprocess.run([sys.executable, "-m", "rvt_prt.metrics.geobench", kind, *map(str, args)],
                           capture_output=True, text=True, preexec_fn=limit, timeout=timeout)
        lines = p.stdout.strip().splitlines()
        if p.returncode == 0 and lines:
            out = json.loads(lines[-1])
            # prefetch's workers that failed (their files then meshed in the parent)
            out["worker_failures"] = p.stderr.count("failed in a worker")
            out["notes"] = [l[:200] for l in p.stderr.splitlines() if l.startswith("rvt_prt:")][:10]
        else:
            err = (p.stderr.strip().splitlines() or [""])[-1][:300]
            out = {"status": f"failed ({p.returncode}): {err}"}
    except subprocess.TimeoutExpired:
        out = {"status": f"failed: timeout {timeout} s"}
    done.set()
    out["wall"] = round(time.perf_counter() - t0, 3)
    out["machine_peak_mb"] = int((avail0 - low[0]) // 2**20)
    return out


def _available():
    with open("/proc/meminfo") as f:
        return next(int(line.split()[1]) * 1024 for line in f if line.startswith("MemAvailable:"))


# --- runs -------------------------------------------------------------------------------------

def _record(base, rec):
    rec = {**base, **rec}
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    st = rec["status"]
    what = rec.get("backend") or f"jobs {rec.get('jobs')}"
    print(f"{rec['file']} {what}: {st}"
          + (f", {rec['total']:.1f} s, {rec.get('peak_mb')} MB" if st == "ok" else ""), flush=True)
    return rec


def _base(run):
    return {"when": time.strftime("%Y-%m-%dT%H:%M:%S"), "commit": _git("rev-parse", "--short", "HEAD"),
            "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "rvt_rs": rvtrs.pinned(), "run": run}


def _file(p):
    p = pathlib.Path(p)
    from .labels import label
    return {"file": label(p), "mb": round(p.stat().st_size / 1e6, 1)}


def backends(files, which, repeat, cap, timeout):
    base = _base("backends")
    base["batch"] = base["when"]
    for r in range(repeat):
        for p in files:
            for b in which:
                _record({**base, "when": time.strftime("%Y-%m-%dT%H:%M:%S")},
                        {**_file(p), "backend": b, "repeat": r, "cap_gb": cap / 1e9,
                         **_measure("_one", [b, p], cap, timeout)})


def scaling(files, jobs, cap, timeout):
    base = _base("scaling")
    base["batch"] = base["when"]
    for j in jobs:
        _record({**base, "when": time.strftime("%Y-%m-%dT%H:%M:%S")},
                {"file": f"{len(files)} files", "mb": round(sum(pathlib.Path(f).stat().st_size for f in files) / 1e6, 1),
                 "jobs": j, "cap_gb": cap / 1e9, **_measure("_scale", [j, *files], cap, timeout)})


def _year_project(folder):
    """The project to try for a year folder: rac_basic_sample_project.rvt, else the smallest .rvt."""
    rvts = sorted(folder.glob("*.rvt"), key=lambda p: p.stat().st_size)
    pref = [p for p in rvts if p.name == "rac_basic_sample_project.rvt"]
    return (pref or rvts or [None])[0]


def versions(corpus, cap, timeout):
    base = _base("versions")
    base["batch"] = base["when"]
    for folder in sorted(d for d in corpus.iterdir() if d.is_dir() and d.name.isdigit()):
        p = _year_project(folder)
        rec = {"year": int(folder.name), "backend": "native"}
        if p is None:
            _record(base, {**rec, "file": "-", "mb": 0, "status": "no project"})
        else:
            _record({**base, "when": time.strftime("%Y-%m-%dT%H:%M:%S")},
                    {**rec, **_file(p), **_measure("_one", ["native", p], cap, timeout)})


# --- summary ----------------------------------------------------------------------------------

def runs():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def _latest(recs, run):
    """The latest batch of `run` (of `backends`: each backend's latest batch)."""
    recs = [r for r in recs if r["run"] == run]
    key = (lambda r: r["backend"]) if run == "backends" else (lambda r: None)
    batch = {}
    for r in recs:
        batch[key(r)] = max(batch.get(key(r), ""), r["batch"])
    return [r for r in recs if r["batch"] == batch[key(r)]]


def _med(rs, f):
    vals = [f(r) for r in rs if r["status"] == "ok"]
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def _fmt(v, nd=1):
    return "–" if v is None else f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def summary():
    hist = runs()
    out = ["# Geometry benchmarks", "",
           "Generated by `python -m rvt_prt.metrics.geobench summary` from `bench/geometry.jsonl`"
           " (the latest batch of each run; medians over repeats). Seconds; MB of peak RSS"
           " (the process and its children) and of the machine's peak use (fall in MemAvailable).", ""]
    b = _latest(hist, "backends")
    if b:
        r0 = b[0]
        out += [f"## Backends ({min(r['batch'] for r in b)}, rvt-prt {r0['commit']}{'+' if r0['dirty'] else ''},"
                f" rvt-rs {r0['rvt_rs']}, cap {r0['cap_gb']:.1f} GB)", "",
                "| File | MB | Backend | Runs | Elements | Triangles | " + " | ".join(STAGES)
                + " | Total | Peak MB | Children MB | Machine MB |",
                "|" + "---|" * (10 + len(STAGES))]
        groups = defaultdict(list)
        for r in b:
            groups[r["file"], r["backend"]].append(r)
        totals = defaultdict(lambda: [0.0, 0])
        for (f, be), rs in groups.items():
            ok = [r for r in rs if r["status"] == "ok"]
            row = [f, _fmt(rs[0]["mb"]), be, f"{len(ok)}/{len(rs)}", _fmt(_med(rs, lambda r: r["elements"])),
                   _fmt(_med(rs, lambda r: r["triangles"]))]
            row += [_fmt(_med(rs, lambda r, s=s: r["stages"].get(s))) for s in STAGES]
            tot = _med(rs, lambda r: r["total"])
            row += [_fmt(tot), _fmt(_med(rs, lambda r: r["peak_mb"])),
                    _fmt(_med(rs, lambda r: r["children_peak_mb"])), _fmt(_med(rs, lambda r: r["machine_peak_mb"]))]
            if len(ok) < len(rs):
                row[2] += f" ({next(r['status'] for r in rs if r['status'] != 'ok')[:60]})"
            out.append("| " + " | ".join(row) + " |")
            if tot is not None:
                totals[be][0] += tot
                totals[be][1] += 1
        out += ["", "Sum of medians per backend: "
                + ", ".join(f"{be} {t:.1f} s ({n} files)" for be, (t, n) in totals.items()), ""]
    s = _latest(hist, "scaling")
    if s:
        r0 = s[0]
        out += [f"## Scaling: `--geometry-jobs` ({r0['batch']}, {r0['file']}, {r0['mb']} MB,"
                f" rvt-prt {r0['commit']}{'+' if r0['dirty'] else ''})", "",
                "| Jobs | Status | Worker failures | Prefetch | meshes() | Total | Parent MB | Children MB | Machine MB |",
                "|---|---|---|---|---|---|---|---|---|"]
        for r in s:
            ok = r["status"] == "ok"
            g = lambda k: _fmt(r[k]) if ok else "–"
            out.append(f"| {r['jobs']} | {r['status'][:60]} | {r.get('worker_failures', '–')} | {_fmt(r['stages']['prefetch']) if ok else '–'} | "
                       f"{_fmt(r['stages']['meshes']) if ok else '–'} | {g('total')} | {g('peak_mb')} | "
                       f"{g('children_peak_mb')} | {_fmt(r['machine_peak_mb'])} |")
        out.append("")
    v = _latest(hist, "versions")
    if v:
        r0 = v[0]
        out += [f"## Versions: native backend, one project per year ({r0['batch']}, rvt-rs {r0['rvt_rs']})", "",
                "| Year | File | MB | Revit | Status | Elements | Triangles | Seconds | Peak MB |",
                "|---|---|---|---|---|---|---|---|---|"]
        for r in v:
            ok = r["status"] == "ok"
            out.append(f"| {r['year']} | {r['file']} | {_fmt(r['mb'])} | {r.get('revit_version') or '–'} | "
                       f"{r['status'][:80]} | {r.get('elements', '–') if ok else '–'} | "
                       f"{r.get('triangles', '–') if ok else '–'} | {_fmt(r['total']) if ok else '–'} | "
                       f"{r.get('peak_mb', '–') if ok else '–'} |")
        out.append("")
    SUMMARY.parent.mkdir(exist_ok=True)
    SUMMARY.write_text("\n".join(out))
    print(f"wrote {SUMMARY}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("_one", "_scale"):
        return _child_main(argv)
    ap = argparse.ArgumentParser(prog="python -m rvt_prt.metrics.geobench")
    ap.add_argument("run", choices=("backends", "scaling", "versions", "summary"))
    ap.add_argument("files", nargs="*")
    ap.add_argument("--backend", default="native")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--jobs", default="1,2,3,4")
    ap.add_argument("--corpus", default=os.environ.get("RVT_PRT_CORPUS"))
    ap.add_argument("--cap", type=float, default=5.5, help="address-space cap per measured process, GB")
    ap.add_argument("--timeout", type=float, default=1800)
    a = ap.parse_args(argv)
    files = [str(pathlib.Path(f).resolve()) for f in a.files] or [str(f) for f in _snowdon()]
    cap = int(a.cap * 1e9)
    if a.run == "backends":
        bad = set(a.backend.split(",")) - set(BACKENDS)
        if bad:
            ap.error(f"unknown backend(s) {sorted(bad)}: expected {', '.join(BACKENDS)}")
        backends(files, a.backend.split(","), a.repeat, cap, a.timeout)
    elif a.run == "scaling":
        scaling(files, [int(j) for j in a.jobs.split(",")], cap, a.timeout)
    elif a.run == "versions":
        if not a.corpus:
            ap.error("versions needs a corpus folder: --corpus DIR or RVT_PRT_CORPUS")
        versions(pathlib.Path(a.corpus), cap, a.timeout)
    summary()


if __name__ == "__main__":
    main()
