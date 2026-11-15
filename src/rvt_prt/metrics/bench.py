"""Print timing: per-stage wall times of `cli.py print`, appended to bench/prints.jsonl.

Each record: when, git commit (and whether the tree had uncommitted changes), model, sheets,
whether the link mesh caches were warm, stage seconds, total seconds and peak memory. Runs are
compared with the previous run of the same model, sheet set and cache state.

python -m rvt_prt.bench [N]   the last N runs, each against the run before it
"""
import contextlib
import json
import subprocess
import sys
import time
from ..core import paths

LOG = paths.BENCH / "prints.jsonl" if paths.BENCH else None  # a checkout's only


def _git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                              cwd=paths.ROOT).stdout.strip()
    except Exception:
        return ""


def _peak_mb(who):
    """Peak resident MB of this process ("self") or its largest child ("children"); None where
    there is no `resource` module (Windows)."""
    try:
        import resource
    except ImportError:
        return None
    return resource.getrusage(resource.RUSAGE_SELF if who == "self" else resource.RUSAGE_CHILDREN).ru_maxrss // 1024


class Timer:
    def __init__(self, model, sheets, warm):
        from .labels import label
        self.model, self.sheets, self.warm = label(model), sorted(sheets), warm
        self.stages = {}
        self.start = time.perf_counter()

    @contextlib.contextmanager
    def stage(self, name, say=True):
        if say:
            from ..core import progress
            progress.step(f"reading {name}")
        t = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0.0) + time.perf_counter() - t

    def record(self):
        rec = {
            "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "commit": _git("rev-parse", "--short", "HEAD") if LOG else "",
            "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")) if LOG else False,
            "model": self.model,
            "sheets": self.sheets,
            "warm": self.warm,
            "stages": {k: round(v, 2) for k, v in self.stages.items()},
            "total": round(time.perf_counter() - self.start, 2),
            "peak_mb": _peak_mb("self"),
            "children_peak_mb": _peak_mb("children"),  # the largest worker's (render, geometry prefetch)
        }
        if LOG is None:  # installed: no record kept
            return rec, None
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        prev = previous(rec)
        return rec, prev


def runs():
    if LOG is None or not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def _key(r):
    return r["model"], tuple(r["sheets"]), r["warm"]


def previous(rec, history=None):
    """The last earlier run comparable with `rec` (same model, sheets and cache state)."""
    history = runs() if history is None else history
    earlier = [r for r in history if _key(r) == _key(rec) and r["when"] < rec["when"]]
    return earlier[-1] if earlier else None


def describe(rec, prev):
    head = (f"{rec['when']} {rec['commit']}{'+' if rec['dirty'] else ''} {rec['model']} "
            f"{len(rec['sheets'])} sheet(s) {'warm' if rec['warm'] else 'cold'}: "
            f"{rec['total']:.1f} s, {rec['peak_mb']} MB")
    if not prev:
        return head + "  (no earlier comparable run)"
    d = rec["total"] - prev["total"]
    pct = 100 * d / prev["total"] if prev["total"] else 0
    lines = [head + f"  {'+' if d >= 0 else ''}{d:.1f} s ({pct:+.0f}%) vs {prev['commit']}{'+' if prev['dirty'] else ''}"]
    for k in sorted(set(rec["stages"]) | set(prev["stages"]), key=lambda k: -rec["stages"].get(k, 0)):
        a, b = rec["stages"].get(k, 0.0), prev["stages"].get(k, 0.0)
        if max(a, b) >= 0.5:
            lines.append(f"    {k:18} {a:7.1f} s  {'+' if a - b >= 0 else ''}{a - b:.1f}")
    return "\n".join(lines)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    hist = runs()
    for r in hist[-n:]:
        print(describe(r, previous(r, hist)))
