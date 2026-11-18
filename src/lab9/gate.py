"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, brows = pr.get("rows") or [], base.get("rows") or []
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. metric values must be real numbers
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN/inf hides a crashed or empty grader)")

    # 2. row count = items x seeds, no duplicates, same (item, seed) set and manifest as the baseline
    seeds, items = list(pm.get("seeds") or []), pm.get("items")
    if not isinstance(items, int) or len(rows) != items * len(seeds):
        problems.append(f"{len(rows)} rows but manifest says {items} items x {len(seeds)} seeds")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"{len(dups)} duplicated (item, seed) row(s), first {dups[0]}")
    bkeys = {(r.get("item_id"), r.get("seed")) for r in brows}
    if set(keys) != bkeys:
        problems.append(f"(item, seed) set differs from baseline: {len(set(keys) - bkeys)} extra, "
                        f"{len(bkeys - set(keys))} missing (dropped rows or cherry-picked seeds)")
    if sorted(seeds) != sorted(bm.get("seeds") or []) or items != bm.get("items"):
        problems.append(f"manifest seeds/items {sorted(seeds)}/{items} differ from baseline "
                        f"{sorted(bm.get('seeds') or [])}/{bm.get('items')}")

    # 3. graders must not have crashed or gone missing
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for mid in graded:
        missing = [r for r in rows if r.get(mid) is None]
        if missing:
            problems.append(f"{len(missing)} row(s) with no value for graded metric {mid} "
                            f"(first {missing[0].get('item_id')}@{missing[0].get('seed')})")

    # 4. reported metrics must equal what the rows say (no hand-edited numbers)
    if rows and not problems:
        ids = [m for m in graded if all(m in r for r in rows)]
        again = aggregate([{"cost": 0.0, **r} for r in rows], ids, k_values=spec.get("pass_k", []))
        has_cost = all("cost" in r for r in rows)
        for k, got in (pr.get("metrics") or {}).items():
            v = again.get(k)
            if k == "cost_per_success" and not has_cost:
                continue
            if isinstance(v, (int, float)) and (not isinstance(got, (int, float)) or abs(got - v) > 1e-3):
                problems.append(f"metric {k} reported {got} but rows give {v}")

    # 5. slice tags must match the baseline item by item
    btags = {r.get("item_id"): sorted(r.get("slices") or []) for r in brows}
    moved = sorted({r.get("item_id") for r in rows
                    if r.get("item_id") in btags and sorted(r.get("slices") or []) != btags[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags changed vs baseline for {len(moved)} item(s), first {moved[0]}")

    # 6. ratchet: same eval-set version => thresholds may only get stricter
    if base_spec is not None and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        problems += ratchet(spec, base_spec)
    return problems


def _looser(new: dict, old: dict, where: str) -> list[str]:
    out = []
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"{where}: blocking -> non-blocking")
    nt, ot = new.get("threshold", new), old.get("threshold", old)
    for key in ("max", "max_increase"):
        if key in ot and (key not in nt or nt[key] > ot[key]):
            out.append(f"{where}: {key} {ot[key]} -> {nt.get(key)}")
    if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
        out.append(f"{where}: min {ot['min']} -> {nt.get('min')}")
    if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
        out.append(f"{where}: no_significant_drop removed")
    return out


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    out = []
    new = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        if m["id"] not in new:
            out.append(f"ratchet: metric {m['id']} removed")
        else:
            out += [f"ratchet: {p}" for p in _looser(new[m["id"]], m, f"metric {m['id']}")]
    snew = {(x["name"], x["metric"]): x for x in spec.get("slices") or []}
    for x in base_spec.get("slices") or []:
        key = (x["name"], x["metric"])
        if key not in snew:
            out.append(f"ratchet: slice {key[0]}/{key[1]} removed")
        else:
            out += [f"ratchet: {p}" for p in _looser(snew[key], x, f"slice {key[0]}/{key[1]}")]
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, mid = sl["name"], sl["metric"]
        sid = f"slice:{name}/{mid}"
        a, b = per_item(pr, mid, slice_name=name), per_item(base, mid, slice_name=name)
        fail, note = False, ""
        if not a:
            fail, val = True, None
            note = "no items in slice"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                fail = True
            if "max" in sl and val > sl["max"]:
                fail = True
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        fail = True
        if fail and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        label = "ok" if not fail else ("BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
