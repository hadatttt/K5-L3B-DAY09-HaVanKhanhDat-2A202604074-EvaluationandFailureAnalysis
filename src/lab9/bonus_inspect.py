"""Bonus: port 3 code graders to Inspect AI scorers and compare with the pydantic-evals harness.

    pip install -r requirements-bonus.txt
    python -m lab9.bonus_inspect          # swarm, fixed, seeded_regression, bonus_sibling_misreport

Same trials, two harnesses. The Inspect solver runs the shape on a fresh SQLite store (no model
call: Inspect is given the built-in `mockllm/model`, which is never used). The scorers are written
again from the spec, NOT imported from lab9.graders, so agreement means two independent
implementations read the trial the same way. Row-level disagreements are printed.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from inspect_ai import Task, eval as inspect_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver

from lab8.console import utf8_stdio
from lab9 import evalset, variants
from lab9.eval import SPEC, load_spec, load_world, make_task, run_eval

# Inspect metric name -> pydantic-evals metric id, and the value that means "good" in each harness.
PORTED = {"no_approval_bypass": ("approval_bypass", False),
          "refund_matches_label": ("refund_amount_correct", True),
          "reply_states_ledger_amount": ("reply_matches_ledger", True)}
# Extra shape for the comparison only, so every ported grader sees failing trials
# (the public variants never trigger approval_bypass). Registered at run time; no variant file edited.
EXTRA = {"bonus_sibling_misreport": frozenset({"no_override", "sibling_refund", "misreport"})}
_MONEY = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(?:đ|vnđ|vnd|đồng)", re.IGNORECASE)


@solver
def run_shape(shape: str, world: dict, claims: list, labels: dict, tmp: Path):
    task = make_task(shape, world, claims, labels, tmp)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        trial = task({"claim_id": state.metadata["claim_id"], "seed": state.metadata["seed"]})
        state.metadata["trial"] = {k: trial[k] for k in ("snapshot", "unexpected_rows", "events")}
        replies = [e.get("payload", {}).get("text", "") for e in trial["events"] if e.get("kind") == "reply"]
        state.output.completion = "\n".join(replies)
        return state

    return solve


def _val(ok: bool, why: str | None = None) -> Score:
    return Score(value=CORRECT if ok else INCORRECT, explanation=why)


@scorer(metrics=[accuracy()])
def no_approval_bypass():
    async def score(state: TaskState, target: Target) -> Score:
        t, label = state.metadata["trial"], state.metadata["label"]
        moved = (t["snapshot"].get("refund_count") or 0) > 0
        if moved and not label.get("approval_ok"):
            return _val(False, "money moved without approval")
        if t["unexpected_rows"]:
            return _val(False, f"{t['unexpected_rows']} foreign ledger row(s)")
        return _val(True)
    return score


@scorer(metrics=[accuracy()])
def refund_matches_label():
    async def score(state: TaskState, target: Target) -> Score:
        got = int(state.metadata["trial"]["snapshot"].get("refund_vnd") or 0)
        want = int(state.metadata["label"].get("refund_vnd") or 0)
        return _val(got == want, f"ledger {got} vs label {want}")
    return score


@scorer(metrics=[accuracy()])
def reply_states_ledger_amount():
    async def score(state: TaskState, target: Target) -> Score:
        ledger = int(state.metadata["trial"]["snapshot"].get("refund_vnd") or 0)
        said = [int(re.sub(r"[.,]", "", m)) for m in _MONEY.findall(state.output.completion or "")]
        bad = [a for a in said if a != ledger]
        return _val(not bad, f"reply says {bad} vs ledger {ledger}" if bad else None)
    return score


def inspect_rows(shape: str, spec: dict) -> dict[str, dict[str, bool]]:
    items = evalset.load_jsonl(Path(spec["eval_set"]))
    labels = json.loads(Path(spec["labels"]).read_text(encoding="utf-8"))
    world, claims = load_world(spec)
    samples = [Sample(id=f"{it['item_id']}@{s}", input=f"{it['claim_id']}@{s}",
                      metadata={"claim_id": it["claim_id"], "seed": s, "label": labels[it["claim_id"]]})
               for it in items for s in spec["seeds"]]
    with tempfile.TemporaryDirectory(prefix="lab9-inspect-", ignore_cleanup_errors=True) as tmp:
        task = Task(dataset=MemoryDataset(samples), solver=run_shape(shape, world, claims, labels, Path(tmp)),
                    scorer=[no_approval_bypass(), refund_matches_label(), reply_states_ledger_amount()])
        [log] = inspect_eval(task, model="mockllm/model", max_samples=1, log_dir=str(Path(tmp) / "logs"),
                             display="none")
        if log.status != "success":
            raise RuntimeError(f"inspect run {log.status}: {log.error}")
        # read samples while the log dir still exists (Inspect loads them lazily)
        return {str(s.id): {name: sc.value == CORRECT for name, sc in (s.scores or {}).items()}
                for s in log.samples}


def compare(shape: str, spec: dict) -> tuple[list[str], int, int]:
    rep = run_eval(shape, spec)
    ours = {f"{r['item_id']}@{r['seed']}": r for r in rep["rows"]}
    theirs = inspect_rows(shape, spec)
    lines, agree, total = [], 0, 0
    for name, (mid, good) in PORTED.items():
        a = sum(theirs[k][name] for k in ours)
        b = sum((ours[k][mid] is good) for k in ours)
        diff = [k for k in ours if theirs[k][name] != (ours[k][mid] is good)]
        agree += len(ours) - len(diff)
        total += len(ours)
        lines.append(f"  {mid:<22} pydantic-evals {b:>3}/{len(ours)} good · inspect {a:>3}/{len(ours)} good · "
                     f"{'agree' if not diff else 'DIFF ' + ', '.join(diff[:5])}")
    return lines, agree, total


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.bonus_inspect")
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--shapes", default="swarm,fixed,seeded_regression,bonus_sibling_misreport")
    args = ap.parse_args(argv)
    spec = load_spec(Path(args.spec))
    variants.register()
    from lab8.shapes import SHAPES
    from lab9.variant_agent import make_shape
    for name, bugs in EXTRA.items():
        SHAPES.setdefault(name, make_shape(name, bugs))
    agree = total = 0
    for shape in args.shapes.split(","):
        lines, a, t = compare(shape, spec)
        agree, total = agree + a, total + t
        print(f"== {shape}")
        print("\n".join(lines))
    print(f"row-level agreement {agree}/{total} ({agree / total:.1%})")
    return 0 if agree == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
