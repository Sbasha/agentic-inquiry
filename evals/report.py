"""Pre-registered hypothesis verdicts (RFC-0003) from the latest test-split results.

Reads ``evals/results/test-ledger.jsonl``, takes the most recent test run per
suite, and applies each hypothesis exactly as the RFC states it. A hypothesis
whose results are missing is reported as ``not run``, never as passed.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

from evals.arms import COMPETITORS
from evals.run import LEDGER, REPO_ROOT

MEMORY_BASELINES = ("bm25", "dense", "hybrid")


def latest_runs() -> dict[str, dict[str, Any]]:
    """Most recent ledger entry per suite, with its results file loaded."""
    runs: dict[str, dict[str, Any]] = {}
    if not LEDGER.exists():
        return runs
    for line in LEDGER.read_text().splitlines():
        if line.strip():
            entry = json.loads(line)
            runs[entry["suite"]] = entry
    for entry in runs.values():
        entry["report"] = json.loads((REPO_ROOT / entry["results"]).read_text())
    return runs


def _comparison(
    report: dict[str, Any], metric: str, a: str, b: str
) -> Optional[dict[str, Any]]:
    for comp in report.get("comparisons", []):
        if comp["metric"] == metric and comp["a"] == a and comp["b"] == b:
            return comp
    return None


def _beats(
    report: dict[str, Any], metric: str, others: tuple[str, ...]
) -> dict[str, Any]:
    rows = {}
    for other in others:
        comp = _comparison(report, metric, "inquiry", other)
        rows[other] = (
            None
            if comp is None
            else {
                "diff": comp["mean_diff"],
                "ci": [comp["ci_low"], comp["ci_high"]],
                "pass": comp["ci_low"] > 0 and comp.get("valid", True),
            }
        )
    passed = all(r is not None and r["pass"] for r in rows.values())
    return {"metric": metric, "against": rows, "pass": passed}


def verdicts() -> dict[str, Any]:
    runs = latest_runs()
    out: dict[str, Any] = {}

    swe = runs.get("swebench")
    if swe:
        report = swe["report"]
        primary = _beats(report, "fn_hit@2000", ("bm25", "dense", "hybrid", "graphify"))
        lines = _comparison(report, "line_recall@2000", "inquiry", "hybrid")
        non_inferior = lines is not None and lines["ci_low"] >= -0.02
        out["H1"] = {
            "suite": "swebench",
            "primary": primary,
            "line_recall_vs_hybrid": None
            if lines is None
            else [lines["ci_low"], lines["ci_high"]],
            "pass": primary["pass"] and non_inferior,
        }
    else:
        out["H1"] = {"pass": None, "status": "not run"}

    sci = runs.get("scifact")
    if sci:
        comp = _comparison(sci["report"], "ndcg@10", "inquiry", "bm25")
        out["H2"] = {
            "suite": "scifact",
            "ci": None if comp is None else [comp["ci_low"], comp["ci_high"]],
            "pass": comp is not None and comp["ci_low"] >= -0.01,
        }
    else:
        out["H2"] = {"pass": None, "status": "not run"}

    memory = [runs.get("locomo"), runs.get("longmemeval")]
    if all(memory):
        parts = {
            r["suite"]: _beats(r["report"], "unit_recall@2000", MEMORY_BASELINES)
            for r in memory
            if r
        }
        out["H3"] = {"suites": parts, "pass": all(p["pass"] for p in parts.values())}
    else:
        out["H3"] = {"pass": None, "status": "not run"}

    answers = runs.get("locomo-answers")
    if answers:
        report = answers["report"]
        kappa = report["judge_agreement"]["cohen_kappa"]
        best = report.get("best_baseline") or max(
            (arm for arm in report["summary"] if arm in MEMORY_BASELINES),
            key=lambda arm: report["summary"][arm]["accuracy"],
        )
        comp = _comparison(report, "accuracy", "inquiry", best)
        out["H4"] = {
            "best_baseline": best,
            "kappa": kappa,
            "ci": None if comp is None else [comp["ci_low"], comp["ci_high"]],
            "pass": kappa >= 0.6 and comp is not None and comp["ci_low"] > 0,
        }
    else:
        out["H4"] = {"pass": None, "status": "not run"}

    competitors = (
        tuple(arm for arm in answers["report"]["summary"] if arm in COMPETITORS)
        if answers
        else ()
    )
    if answers and competitors:
        out["H6"] = {
            "suite": "locomo",
            **_beats(answers["report"], "accuracy", competitors),
        }
    else:
        out["H6"] = {"pass": None, "status": "not run"}

    agent = runs.get("agent")
    if agent:
        report = agent["report"]
        fn = {
            other: _comparison(report, "fn_hit", "inquiry", other)
            for other in ("floor", "graphify")
        }
        tokens = _comparison(report, "input_token_ratio_minus_1", "inquiry", "floor")
        out["H5"] = {
            "fn_hit": {
                k: None if v is None else [v["ci_low"], v["ci_high"]]
                for k, v in fn.items()
            },
            "token_ratio_minus_1_vs_floor": None
            if tokens is None
            else [tokens["ci_low"], tokens["ci_high"]],
            "pass": all(v is not None and v["ci_low"] > 0 for v in fn.values())
            and tokens is not None
            and tokens["ci_high"] <= 0.10,
        }
    else:
        out["H5"] = {"pass": None, "status": "not run"}
    return out


def main() -> None:
    result = verdicts()
    json.dump(result, sys.stdout, indent=1)
    print()
    for name, verdict in result.items():
        status = (
            "not run"
            if verdict.get("pass") is None
            else ("PASS" if verdict["pass"] else "FAIL")
        )
        print(f"{name}: {status}", file=sys.stderr)


if __name__ == "__main__":
    main()
