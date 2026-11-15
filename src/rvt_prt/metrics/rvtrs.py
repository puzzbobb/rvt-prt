"""rvt-rs revisions compared: rvt_prt._native built against any rvt-rs release or commit, each
model file meshed with it, and two builds' meshes compared element by element, before the pin in
native/Cargo.toml moves.

    python -m rvt_prt.metrics.rvtrs build REV [REV ...]        e.g. pinned 0.24.0 main
    python -m rvt_prt.metrics.rvtrs mesh REV [files]           default: Snowdon, test oracles, corpus
    python -m rvt_prt.metrics.rvtrs diff OLD NEW [files] [--out FILE.md]
    python -m rvt_prt.metrics.rvtrs oracles REV                pytest -m oracle with that build, and scores
    python -m rvt_prt.metrics.rvtrs all OLD NEW                all four, OLD and NEW alike

REV is `pinned` (the release native/Cargo.toml pins), a release (`0.23.0` or `v0.23.0`, from
crates.io), or a branch, tag or full commit of rvt-rs's git repository (RVT_PRT_RVTRS_GIT names
another, such as a fork; cargo fetches it). Everything is kept in the folder RVT_PRT_CMP names
(default: `rvtcmp` in the cache folder; not a temporary folder, so that a long comparison survives
a restart), under rvtrs/<v0.23.0 or the commit's first 10 characters>/:
- `Cargo.toml`, `Cargo.lock`, `build.rs`, `src/`: a copy of native/ with its `rvt` dependency set
  to REV (one target folder, rvtrs/target, for every build), `_native.abi3.so` and `build.json`
  (what it was built from);
- `meshes/<folder>__<file>.json`: each element of the file as rvt_prt reads it (`_native.element_meshes`):
  tag, class, family, materials, triangles, box, volume; with the time, peak RSS and failure if any;
- `wt/`: a worktree of rvt_prt (HEAD) with this build's extension, for `oracles`.

Each file is meshed in a fresh interpreter under an address-space cap, killed if the machine's
MemAvailable falls below --floor MB (a small machine can freeze or restart when it runs out). `diff` matches
elements by tag: lost, gained, class changed, box moved (> --tol ft), volume changed (> 1%),
family or materials changed; per file and class, with example tags; and the test oracles'
scores by each build where `oracles` has run for both.
"""
import argparse
import functools
import hashlib
import json
import os
import pathlib
import re
import resource
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict

from ..core import paths
from .labels import label

NATIVE = paths.ROOT / "native"
GIT = os.environ.get("RVT_PRT_RVTRS_GIT") or "https://github.com/DrunkOnJava/rvt-rs.git"
CMP = pathlib.Path(os.environ.get("RVT_PRT_CMP") or paths.CACHE / "rvtcmp") / "rvtrs"
# a folder of test files, one subfolder per year (2019/, 2025/, ...); None: only the oracles are meshed
CORPUS = pathlib.Path(os.environ["RVT_PRT_CORPUS"]) if os.environ.get("RVT_PRT_CORPUS") else None
NATIVE_FILES = ("Cargo.toml", "Cargo.lock", "build.rs", "src")
_DEP = re.compile(r"^rvt\s*=.*$", re.M)
_RELEASE = re.compile(r"v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)")
_COMMIT = re.compile(r"[0-9a-f]{40}")


def _git(*args, cwd=paths.ROOT):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=cwd).stdout.strip()


def pinned():
    """The rvt release native/Cargo.toml pins (\"0.23.0\"), or None when it pins none."""
    m = re.search(r'^rvt\s*=\s*"=?([^"]+)"', (NATIVE / "Cargo.toml").read_text(), re.M)
    return m.group(1) if m else None


def _ls_remote(ref):
    """The commit `ref` (a branch or tag; `upstream/` or `origin/` is dropped) names in GIT."""
    ref = ref.split("/", 1)[1] if ref.startswith(("upstream/", "origin/")) else ref
    lines = [ln.split("\t") for ln in _git("ls-remote", GIT, ref, f"{ref}^{{}}").splitlines()]
    if not lines:
        sys.exit(f"{ref}: not a branch or tag of {GIT} (give a full 40-character commit instead)")
    peeled = [c for c, r in lines if r.endswith("^{}")]  # an annotated tag's commit
    return (peeled or [lines[0][0]])[0]


@functools.cache
def resolve(rev):
    """REV as (its build folder's name, the Cargo dependency line, what build.json records)."""
    if rev == "pinned":
        rev = pinned() or sys.exit("native/Cargo.toml pins no rvt release")
    m = _RELEASE.fullmatch(rev)
    if m:
        v = m.group(1)
        return f"v{v}", f'rvt = "={v}"', {"rvt_rs": f"v{v}", "describe": f"v{v}", "source": "crates.io"}
    full = rev if _COMMIT.fullmatch(rev) else _ls_remote(rev)
    return full[:10], f'rvt = {{ git = "{GIT}", rev = "{full}" }}', {
        "rvt_rs": full, "describe": full[:10] if rev == full else f"{rev} ({full[:10]})", "source": GIT}


def folder(rev):
    return CMP / resolve(rev)[0]


def _native_stamp():
    """A hash of native/ apart from its rvt dependency: a build is redone when it changes."""
    h = hashlib.sha256()
    files = [NATIVE / "build.rs", *sorted((NATIVE / "src").rglob("*.rs"))]
    for f in files:
        h.update(str(f.relative_to(NATIVE)).encode() + b"\0" + f.read_bytes())
    h.update(_DEP.sub("rvt", (NATIVE / "Cargo.toml").read_text()).encode())
    return h.hexdigest()[:16]


# --- build ------------------------------------------------------------------------------------

def build(rev):
    """_native built against `rev`: its folder (built once; a rebuild when native/ has changed)."""
    name, dep, source = resolve(rev)
    d = CMP / name
    so, info = d / "_native.abi3.so", d / "build.json"
    stamp = _native_stamp()
    if so.exists() and info.exists() and json.loads(info.read_text()).get("native") == stamp:
        print(f"{rev}: built ({d})", flush=True)
        return d
    d.mkdir(parents=True, exist_ok=True)
    for f in NATIVE_FILES:
        src = NATIVE / f
        if src.is_dir():
            shutil.copytree(src, d / f, dirs_exist_ok=True)
        else:
            shutil.copy2(src, d / f)
    manifest = d / "Cargo.toml"
    manifest.write_text(_DEP.sub(dep, manifest.read_text(), count=1))
    env = {**os.environ, "CARGO_TARGET_DIR": str(CMP / "target"), "PYO3_PYTHON": sys.executable}
    print(f"{rev}: building {name} ({dep}) ...", flush=True)
    t0 = time.perf_counter()
    p = subprocess.run(["cargo", "build", "--release", "--message-format=json-render-diagnostics",
                        "--manifest-path", str(manifest)],
                       check=False, env=env, stdout=subprocess.PIPE, text=True)
    lib = None
    for line in p.stdout.splitlines():  # the cdylib this manifest built (the target folder is shared)
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("reason") == "compiler-artifact" and "cdylib" in m["target"]["crate_types"] \
                and m["manifest_path"] == str(manifest):
            lib = next(f for f in m["filenames"] if f.endswith((".so", ".dylib", ".pyd")))
    if p.returncode or lib is None:
        sys.exit(f"{rev}: build failed (cargo exit {p.returncode})")
    shutil.copy2(lib, so)
    info.write_text(json.dumps({
        **source, "rev": rev, "native": stamp,
        "rvt_prt": _git("rev-parse", "--short", "HEAD"),
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.perf_counter() - t0, 1)}, indent=1))
    print(f"{rev}: built in {time.perf_counter() - t0:.0f} s ({d})", flush=True)
    return d


# --- mesh -------------------------------------------------------------------------------------

def default_files():
    """Snowdon's host and links, the test oracles' models, and one project per year folder of the
    corpus (rac_basic_sample_project.rvt, else the smallest)."""
    files = [paths.ROOT / "oracle" / "Snowdon Towers Sample HVAC.rvt",
             *sorted((paths.ROOT / "links").glob("Snowdon Towers Sample *.rvt")),
             *sorted((paths.ROOT / "oracle").glob("test*/*.rvt"))]
    if CORPUS is not None and CORPUS.is_dir():
        for sub in sorted(d for d in CORPUS.iterdir() if d.is_dir() and d.name.isdigit()):
            rvts = sorted(sub.glob("*.rvt"), key=lambda p: p.stat().st_size)
            pref = [p for p in rvts if p.name == "rac_basic_sample_project.rvt"]
            if pref or rvts:
                files.append((pref or rvts)[0])
    return [f for f in files if f.exists()]


def _summary(so, path):
    """Each element of `path` meshed by the extension `so` (in this process: the parent caps it)."""
    import importlib.util

    import numpy as np
    spec = importlib.util.spec_from_file_location("rvt_prt._native", so)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    t0 = time.perf_counter()
    from ..model import phases
    try:  # as rvt_prt meshes it (linkgeom._earlier_phases): with the earlier phases' elements,
        extra = phases.earlier_phases(path)  # none where rvt_prt cannot read them (Revit 2008-2011)
    except Exception:  # noqa: BLE001
        extra = []
    try:
        d = native.element_meshes(str(path), extra)
    except TypeError:  # a build from before element_meshes took them
        d = native.element_meshes(str(path))
    secs = time.perf_counter() - t0
    verts = np.frombuffer(d["verts"], "<f8").reshape(-1, 3)
    faces = np.frombuffer(d["faces"], "<i4").reshape(-1, 3)
    index = np.frombuffer(d["index"], "<i8").reshape(-1, 4)
    rows = []
    for cls, tag, fam, mat, (v0, v1, f0, f1) in zip(d["classes"], d["tags"], d["families"], d["materials"], index):
        v, f = verts[v0:v1], faces[f0:f1]
        row = {"tag": int(tag), "cls": cls, "family": fam, "materials": mat, "tris": int(f1 - f0)}
        if len(f) and len(v):
            t = v[f]
            row["lo"] = [round(float(x), 4) for x in v.min(0)]
            row["hi"] = [round(float(x), 4) for x in v.max(0)]
            row["volume"] = round(float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6), 4)
        rows.append(row)
    return {"status": "ok", "seconds": round(secs, 2), "stats": dict(d["stats"]), "elements": rows,
            "peak_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024}


def _available_mb():
    with open("/proc/meminfo") as f:
        return next(int(line.split()[1]) // 1024 for line in f if line.startswith("MemAvailable:"))


def _guarded(cmd, cap, floor, timeout, **kw):
    """Run `cmd` in its own session under RLIMIT_AS `cap` (None: uncapped); SIGKILL its group when
    MemAvailable falls below `floor` MB or at `timeout` s. (returncode, stdout, stderr, why killed
    or None)."""
    def limit():
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         preexec_fn=limit if cap else None, start_new_session=True, **kw)  # noqa: PLW1509 (the watch starts after)
    why, t0 = [None], time.time()
    done = threading.Event()

    def watch():
        while not done.wait(0.2):
            a = _available_mb()
            if a < floor or time.time() - t0 > timeout:
                why[0] = f"MemAvailable {a} MB < {floor}" if a < floor else f"timeout {timeout} s"
                os.killpg(p.pid, signal.SIGKILL)
                return

    threading.Thread(target=watch, daemon=True).start()
    out, err = p.communicate()
    done.set()
    return p.returncode, out, err, why[0]


def _key(f):
    """A file's record name: its folder's and its own (each corpus year has a rac_basic_sample_project.rvt)."""
    f = pathlib.Path(f)
    return f"{f.parent.name}__{f.name}.json"


def mesh(rev, files, cap, floor, timeout, force=False):
    d = folder(rev)
    so = d / "_native.abi3.so"
    if not so.exists():
        sys.exit(f"{rev}: not built (rvtrs build {rev})")
    (d / "meshes").mkdir(exist_ok=True)
    for f in files:
        f = pathlib.Path(f)
        out = d / "meshes" / _key(f)
        if out.exists() and not force:
            continue
        t0 = time.perf_counter()
        rc, stdout, err, why = _guarded([sys.executable, "-m", "rvt_prt.metrics.rvtrs", "_summary", str(so), str(f)],
                                        cap, floor, timeout)
        if why:
            rec = {"status": f"killed: {why}"}
        elif rc:
            rec = {"status": f"failed ({rc}): " + ((err.strip().splitlines() or [""])[-1])[:300]}
        else:
            rec = json.loads(stdout.strip().splitlines()[-1])
        rec.update(file=str(f), mb=round(f.stat().st_size / 1e6, 1), wall=round(time.perf_counter() - t0, 1))
        out.write_text(json.dumps(rec))
        n = len(rec.get("elements", []))
        print(f"{d.name} {f.name}: {rec['status']}" + (f", {n} elements, {rec['seconds']} s, {rec['peak_mb']} MB"
                                                         if rec["status"] == "ok" else ""), flush=True)


# --- diff -------------------------------------------------------------------------------------

def _by_tag(rows):
    """{tag: merged element}: an element written in pieces is one, its box the union, its volume
    and triangles summed."""
    out = {}
    for r in rows:
        e = out.get(r["tag"])
        if e is None:
            out[r["tag"]] = {**r, "pieces": 1}
            continue
        e["pieces"] += 1
        e["tris"] += r["tris"]
        if "lo" in r:
            e["lo"] = [min(a, b) for a, b in zip(e.get("lo", r["lo"]), r["lo"])]
            e["hi"] = [max(a, b) for a, b in zip(e.get("hi", r["hi"]), r["hi"])]
            e["volume"] = e.get("volume", 0) + r["volume"]
    return out


def compare(a, b, tol):
    """Element-by-element differences of two meshes() records of one file: Counter of (kind, class)
    and example tags of each."""
    A, B = _by_tag(a["elements"]), _by_tag(b["elements"])
    kinds, ex = Counter(), defaultdict(list)

    def note(kind, cls, tag):
        kinds[kind, cls] += 1
        if len(ex[kind, cls]) < 5:
            ex[kind, cls].append(tag)

    for t in A.keys() | B.keys():
        x, y = A.get(t), B.get(t)
        if y is None:
            note("lost", x["cls"], t)
            continue
        if x is None:
            note("gained", y["cls"], t)
            continue
        if x["cls"] != y["cls"]:
            note("class", f"{x['cls']} -> {y['cls']}", t)
        if ("lo" in x) != ("lo" in y):
            note("mesh emptied" if "lo" in x else "mesh filled", y["cls"], t)
        elif "lo" in x:
            moved = max(max(abs(p - q) for p, q in zip(x["lo"], y["lo"])),
                        max(abs(p - q) for p, q in zip(x["hi"], y["hi"])))
            if moved > tol:
                note("box", y["cls"], t)
            elif abs(x["volume"] - y["volume"]) > 0.01 * max(abs(x["volume"]), abs(y["volume"]), 1e-6):
                note("volume", y["cls"], t)
            elif x["tris"] != y["tris"]:
                note("triangles", y["cls"], t)
        if x["pieces"] != y["pieces"]:
            note("pieces", y["cls"], t)
        if x["family"] != y["family"]:
            note("family", y["cls"], t)
        if x["materials"] != y["materials"]:
            note("materials", y["cls"], t)
    return A, B, kinds, ex


def _info(d):
    p = d / "build.json"
    return json.loads(p.read_text()) if p.exists() else {"rvt_rs": d.name}


def diff(old, new, files, tol, out=None):
    da, db = folder(old), folder(new)
    ia, ib = _info(da), _info(db)
    names = [_key(f) for f in files] if files else sorted(
        p.name for p in (da / "meshes").glob("*.json") if (db / "meshes" / p.name).exists())
    lines = [f"# rvt-rs {ia.get('describe', da.name)} -> {ib.get('describe', db.name)}", "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `python -m rvt_prt.metrics.rvtrs diff`.",
             f"Old: `{ia.get('describe', da.name)}` {ia.get('source', ia.get('subject', ''))}  ",
             f"New: `{ib.get('describe', db.name)}` {ib.get('source', ib.get('subject', ''))}  ",
             f"Elements matched by tag; box moved more than {tol} ft, volume by more than 1%.", "",
             "| File | Old | New | Elements | Triangles | Lost | Gained | Class | Box | Volume | Other | s | MB |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    details = []
    for name in names:
        pa, pb = da / "meshes" / name, db / "meshes" / name
        year, _, file = name[:-5].partition("__")
        name = (f"{year} " if year.isdigit() else "") + label(file)
        if not (pa.exists() and pb.exists()):
            lines.append(f"| {name} | {'meshed' if pa.exists() else 'not meshed'} | "
                         f"{'meshed' if pb.exists() else 'not meshed'} |" + " |" * 11)
            continue
        a, b = json.loads(pa.read_text()), json.loads(pb.read_text())
        if a["status"] != "ok" or b["status"] != "ok":
            lines.append(f"| {name} | {a['status'][:60]} | {b['status'][:60]} |" + " |" * 11)
            continue
        A, B, kinds, ex = compare(a, b, tol)
        by = Counter()
        for (kind, _), n in kinds.items():
            by[kind] += n
        other = sum(n for k, n in by.items() if k not in ("lost", "gained", "class", "box", "volume"))
        tri = lambda r: sum(e["tris"] for e in r["elements"])
        lines.append(f"| {name} | ok | ok | {len(A)} → {len(B)} | {tri(a)} → {tri(b)} | {by['lost']} | "
                     f"{by['gained']} | {by['class']} | {by['box']} | {by['volume']} | {other} | "
                     f"{a['seconds']} → {b['seconds']} | {a['peak_mb']} → {b['peak_mb']} |")
        if kinds:
            details += ["", f"## {name}", "", "| Change | Class | Elements | Example tags |", "|---|---|---|---|"]
            for (kind, cls), n in sorted(kinds.items(), key=lambda kv: (kv[0][0], -kv[1])):
                details.append(f"| {kind} | {cls} | {n} | {', '.join(map(str, ex[kind, cls]))} |")
    text = "\n".join(lines + _oracle_table(da, db) + details) + "\n"
    out = pathlib.Path(out) if out else CMP / f"diff-{da.name}-{db.name}.md"
    out.write_text(text)
    print(text)
    print(f"written to {out}")


# --- oracles ----------------------------------------------------------------------------------

# run in a build's worktree (its rvt_prt, its _native): each test oracle printed and scored as
# tests/integration/test_oracles.py scores it, as JSON {oracle: {score: value}}
SCORES = '''
import importlib.util, json, pathlib, sys, tempfile
from rvt_prt import RevitModel, pdf
from rvt_prt.formats import drawing
from rvt_prt.metrics import metrics
spec = importlib.util.spec_from_file_location("oracles", "tests/integration/test_oracles.py")
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
out = {}
for name, model, _r, _p, _t, ink in t.ORACLES:
    folder = pathlib.Path("oracle") / name
    if not (folder / model).exists():
        continue
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        RevitModel(folder / model).render_to_dwfx(tmp / "sheets.dwfx")
        s = drawing.compare(*drawing.pair(drawing.read(folder / "A101.dxf"), drawing.read(tmp / "sheets.dwfx"))[0])
        o = {"line recall": s.recall, "line precision": s.precision, "text recall": s.text_recall}
        if ink is not None:
            RevitModel(folder / model).render_to_pdf(tmp / "sheets.pdf")
            r, q, _a, _b = metrics.score(pdf.open_document(folder / "A101.pdf")[0], pdf.open_document(tmp / "sheets.pdf")[0],
                                         dpi=50, r=2, mode="ink")
            o.update({"ink recall": r, "ink precision": q})
    out[name] = {k: round(float(v), 5) for k, v in o.items() if v is not None}
print("\\n" + json.dumps(out))
'''


def oracles(rev, floor, timeout):
    """`pytest -m oracle` in a worktree of rvt_prt (HEAD) with `rev`'s build of _native, and the
    test oracles' scores with it (oracles.json, for diff). Its out/ (caches) is its own."""
    d = folder(rev)
    so = d / "_native.abi3.so"
    if not so.exists():
        sys.exit(f"{rev}: not built (rvtrs build {rev})")
    wt = d / "wt"
    head = _git("rev-parse", "HEAD", cwd=paths.ROOT)
    if not (wt / ".git").exists():
        _git("worktree", "add", "--detach", "--force", str(wt), head, cwd=paths.ROOT)
    else:
        _git("checkout", "--detach", "--quiet", head, cwd=wt)
    shutil.copy2(so, wt / "src" / "rvt_prt" / "_native.abi3.so")
    for name in ("links", "fonts", "oracle"):
        if not (wt / name).exists() or (wt / name).is_dir() and not any((wt / name).iterdir()):
            if (wt / name).exists():
                shutil.rmtree(wt / name)
            (wt / name).symlink_to(paths.ROOT / name)
    env = {**os.environ, "PYTHONPATH": str(wt / "src")}
    env.pop("RVT_PRT_CACHE", None)
    # uncapped: the print's render pool caps its own workers by what is free
    rc, out, err, why = _guarded([sys.executable, "-m", "pytest", "-m", "oracle", "-q", "-rA", "--no-header",
                                  "-p", "no:cacheprovider", "tests/integration/test_oracles.py"],
                                 None, floor, timeout, cwd=wt, env=env)
    report = (out + err).strip().splitlines()
    tail = [line for line in report if line.startswith(("PASSED", "FAILED", "SKIPPED", "ERROR", "E   "))
            or " passed" in line or " failed" in line]
    (d / "oracles.txt").write_text("\n".join(report) + "\n")
    print(f"{d.name} oracles: " + ("killed: " + why if why else f"exit {rc}"))
    print("\n".join(tail))
    rc, out, err, why = _guarded([sys.executable, "-c", SCORES], None, floor, timeout, cwd=wt, env=env)
    if rc or why:
        print(f"{d.name} scores: " + ("killed: " + why if why else
                                      f"failed ({rc}): " + ((err.strip().splitlines() or [""])[-1])[:300]))
        return
    scores = json.loads(out.strip().splitlines()[-1])
    (d / "oracles.json").write_text(json.dumps(scores, indent=1))
    for name, o in scores.items():
        print(f"{d.name} {name}: " + ", ".join(f"{k} {v:.2%}" for k, v in o.items()))


def _oracle_table(da, db):
    """diff's table of the test oracles' scores by each build (oracles.json), or []."""
    pa, pb = da / "oracles.json", db / "oracles.json"
    if not (pa.exists() and pb.exists()):
        return []
    a, b = json.loads(pa.read_text()), json.loads(pb.read_text())
    rows = ["", "## Test oracles", "", "| Oracle | Score | Old | New | Δ points |", "|---|---|---|---|---|"]
    for name in dict.fromkeys([*a, *b]):  # in test_oracles' order
        for k in dict.fromkeys([*a.get(name, {}), *b.get(name, {})]):
            x, y = a.get(name, {}).get(k), b.get(name, {}).get(k)
            fmt = lambda v: "–" if v is None else f"{v:.2%}"
            delta = "" if x is None or y is None else f"{(y - x) * 100:+.2f}"
            rows.append(f"| {name} | {k} | {fmt(x)} | {fmt(y)} | {delta} |")
    return rows


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_summary"]:
        print("\n" + json.dumps(_summary(argv[1], argv[2])))
        return
    ap = argparse.ArgumentParser(prog="python -m rvt_prt.metrics.rvtrs",
                                 description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("build", "mesh", "diff", "oracles", "all"))
    ap.add_argument("args", nargs="*", help="revisions, then files")
    ap.add_argument("--force", action="store_true", help="mesh files again")
    ap.add_argument("--tol", type=float, default=1e-3, help="box tolerance, feet")
    ap.add_argument("--cap-gb", type=float, default=5.0, help="address space of each meshing process")
    ap.add_argument("--floor", type=int, default=1500, help="MemAvailable MB below which a run is killed")
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--out", help="diff's markdown (default: RVT_PRT_CMP/rvtrs/diff-OLD-NEW.md)")
    a = ap.parse_args(argv)
    cap = int(a.cap_gb * 2**30)
    revs, files = (a.args[:1], a.args[1:]) if a.cmd in ("mesh", "oracles") else (a.args[:2], a.args[2:])
    if a.cmd == "build":
        revs, files = a.args, []
    if not revs:
        ap.error("a revision is needed")
    if a.cmd in ("build", "all"):
        for r in revs:
            build(r)
    if a.cmd in ("mesh", "all"):
        for r in revs:
            mesh(r, files or default_files(), cap, a.floor, a.timeout, a.force)
    if a.cmd in ("oracles", "all"):  # before diff, which reports their scores
        for r in revs:
            oracles(r, a.floor, a.timeout)
    if a.cmd in ("diff", "all"):
        if len(revs) != 2:
            ap.error("diff takes OLD NEW")
        diff(*revs, files, a.tol, a.out)


if __name__ == "__main__":
    main()
