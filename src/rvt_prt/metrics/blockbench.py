"""Family symbol scores across sheets: every family instance we draw against the block Revit
exported for the same element (drawing.compare_instances), per sheet and per family, appended to
bench/families.jsonl with the latest table in bench/families.md.

Each record: when, git commit (and whether the tree had uncommitted changes), model, the oracle
directory, per sheet and per family the sample counts (ref_n, ref_hit, our_n, our_hit) and the
instances matched, missed (Revit drew a block, we drew nothing) and extra (we drew a symbol for an
element Revit has no block for on that sheet). Recall is ref_hit / ref_n, precision our_hit /
our_n over the matched instances, so a family's score weighs its instances by their linework.

python -m rvt_prt.blockbench MODEL ORACLE_DXF_DIR [--sheet M101 ...]   run and record
python -m rvt_prt.blockbench --show [N]                               the last run against the one before
"""
import argparse
import json
import pathlib
import pickle
import sys
import time

from .bench import _git
from .labels import label
from ..core import paths

LOG = paths.ROOT / "bench" / "families.jsonl"
TABLE = LOG.with_suffix(".md")
CACHE = paths.ROOT / "out" / "cache" / "oracle"
KEYS = ("ref_n", "ref_hit", "our_n", "our_hit")
READER = 8  # bump when the readers change what they keep


def read_oracle(path):
    """A Revit export read as a Drawing, pickled beside our caches (keyed by size and mtime)."""
    from ..formats import drawing
    path = pathlib.Path(path)
    st = path.stat()
    f = CACHE / f"{path.name}.{st.st_size}.{int(st.st_mtime)}.v{READER}.pkl"
    if f.exists():
        try:
            return pickle.loads(f.read_bytes())
        except (ImportError, AttributeError, pickle.UnpicklingError, EOFError):
            pass  # written by an older rvt-prt (another module layout): read the export again
    d = drawing.read(path)
    d = d[0] if isinstance(d, list) else d
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_bytes(pickle.dumps(d, protocol=pickle.HIGHEST_PROTOCOL))
    return d


def _tally(rows):
    t = dict.fromkeys(KEYS, 0)
    t.update(matched=0, missed=0, lines=0, extra=0)
    for r in rows:
        if r["ours"] == "(lines)":  # drawn, but as plain lines: not a family symbol of ours
            t["lines"] += 1
        elif r["ours"] and r["reference"]:
            t["matched"] += 1
            for k in KEYS:
                t[k] += r[k]
        elif r["reference"]:
            t["missed"] += 1
            t["ref_n"] += r["ref_n"]
        else:
            t["extra"] += 1
    return t


def recall(t):
    return t["ref_hit"] / t["ref_n"] if t["ref_n"] else None


def precision(t):
    return t["our_hit"] / t["our_n"] if t["our_n"] and t["matched"] else None


def run(model_path, oracle_dir, sheets=None):
    from ..formats import drawing
    from ..api import RevitModel
    oracle = {p.stem: p for p in sorted(pathlib.Path(oracle_dir).glob("*.dxf"))}
    if sheets:
        oracle = {k: v for k, v in oracle.items() if k in sheets}
    t0 = time.perf_counter()
    ours = RevitModel(model_path).view_drawings(list(oracle))
    known = sorted({b.family for ds in ours.values() for d in ds for b in d.blocks.values() if b.family}, key=len)
    per_sheet, per_family = {}, {}
    for sheet, path in oracle.items():
        rows = drawing.compare_instances(read_oracle(path), ours.get(sheet, []))
        if not rows:
            continue
        for r in rows:  # Revit's block names "<family> - <type>-<id>-<view>": the longest family of ours it starts with
            if r["ours"] is None or r["ours"] == "(lines)":
                r["family"] = next((f for f in reversed(known) if r["reference"].startswith(drawing.block_name(f) + " - ")), r["family"])
        per_sheet[sheet] = _tally(rows)
        by_fam = {}
        for r in rows:
            by_fam.setdefault(r["family"], []).append(r)
        for fam, rs in by_fam.items():
            t = _tally(rs)
            acc = per_family.setdefault(fam, {k: 0 for k in t} | {"sheets": []})
            for k in t:
                acc[k] += t[k]
            acc["sheets"].append(sheet)
    rec = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "model": label(model_path),
        "oracle": str(oracle_dir),
        "seconds": round(time.perf_counter() - t0, 1),
        "total": _sum(per_sheet.values()),
        "sheets": per_sheet,
        "families": per_family,
    }
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    TABLE.write_text(table(rec))
    return rec


def _sum(ts):
    out = {}
    for t in ts:
        for k, v in t.items():
            if isinstance(v, int):
                out[k] = out.get(k, 0) + v
    return out


def _pct(x):
    return "    -" if x is None else f"{x:6.1%}"


def table(rec):
    """The run as a Markdown table: totals, per sheet, then per family worst first."""
    t = rec["total"]
    lines = ["# Family symbols against Revit's DXF blocks", "",
             f"{rec['when']} {rec['commit']}{'+' if rec['dirty'] else ''} {rec['model']} vs `{rec['oracle']}`", "",
             (f"All sheets: recall {_pct(recall(t))}, precision {_pct(precision(t))}; "
              f"{t['matched']} instances matched, {t['missed']} missed, {t.get('lines', 0)} drawn as lines, "
              f"{t['extra']} extra"), "",
             "| sheet | recall | precision | matched | missed | as lines | extra |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s, x in rec["sheets"].items():
        lines.append(f"| {s} | {_pct(recall(x))} | {_pct(precision(x))} | {x['matched']} | {x['missed']} | "
                     f"{x.get('lines', 0)} | {x['extra']} |")
    lines += ["", "Families, most missed linework first (the length of Revit's linework we do not draw):", "",
              "| family | recall | precision | matched | missed | as lines | extra | sheets |",
              "|---|---:|---:|---:|---:|---:|---:|---|"]
    for fam, x in sorted(rec["families"].items(), key=lambda kv: -(kv[1]["ref_n"] - kv[1]["ref_hit"])):
        lines.append(f"| {fam} | {_pct(recall(x))} | {_pct(precision(x))} | {x['matched']} | {x['missed']} | "
                     f"{x.get('lines', 0)} | {x['extra']} | {len(x['sheets'])} |")
    return "\n".join(lines) + "\n"


def runs():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]


def describe(rec, prev, top=25):
    t = rec["total"]
    head = (f"{rec['when']} {rec['commit']}{'+' if rec['dirty'] else ''}: recall {_pct(recall(t))}, "
            f"precision {_pct(precision(t))}, {t['matched']} matched, {t['missed']} missed, {t['extra']} extra")
    lines = [head]
    if prev:
        p = prev["total"]
        lines[0] += f"  (was {_pct(recall(p))} / {_pct(precision(p))} at {prev['commit']}{'+' if prev['dirty'] else ''})"
        pairs = [(s, rec["sheets"][s], prev["sheets"].get(s)) for s in rec["sheets"]]
        pairs += [(f, rec["families"][f], prev["families"].get(f)) for f in rec["families"]]
        for name, a, b in pairs:
            if not b:
                continue
            dr = (recall(a) or 0) - (recall(b) or 0)
            dp = (precision(a) or 0) - (precision(b) or 0)
            if min(dr, dp) < -0.005:
                lines.append(f"  REGRESSED {name}: recall {_pct(recall(b))} -> {_pct(recall(a))}, "
                             f"precision {_pct(precision(b))} -> {_pct(precision(a))}")
            elif max(dr, dp) > 0.005:
                lines.append(f"  improved  {name}: recall {_pct(recall(b))} -> {_pct(recall(a))}, "
                             f"precision {_pct(precision(b))} -> {_pct(precision(a))}")
    lines.append("  worst families (missed linework):")
    for fam, x in sorted(rec["families"].items(), key=lambda kv: -(kv[1]["ref_n"] - kv[1]["ref_hit"]))[:top]:
        lines.append(f"    {_pct(recall(x))} {_pct(precision(x))}  {x['matched']:3} matched {x['missed']:3} missed  {fam}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m rvt_prt.blockbench", description=__doc__.split("\n\n")[0])
    ap.add_argument("model", nargs="?")
    ap.add_argument("oracle", nargs="?", help="directory of Revit's sheet DXF exports")
    ap.add_argument("--sheet", action="append", dest="sheets")
    ap.add_argument("--show", type=int, nargs="?", const=1, help="describe the last N runs without running")
    args = ap.parse_args(argv)
    hist = runs()
    if args.show or not args.model:
        for i in range(max(0, len(hist) - (args.show or 1)), len(hist)):
            print(describe(hist[i], _previous(hist[i], hist[:i])))
        return 0
    rec = run(args.model, args.oracle, args.sheets)
    print(describe(rec, _previous(rec, hist)))
    print(f"table: {TABLE}")
    return 0


def _previous(rec, history):
    same = [r for r in history if r["model"] == rec["model"] and set(r["sheets"]) == set(rec["sheets"])]
    return same[-1] if same else None


if __name__ == "__main__":
    sys.exit(main())
