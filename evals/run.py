"""Level A runner: index each corpus per arm, search, score, compare, write results."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.arms import COMPETITORS, REPO_ROOT, make_arm
from evals.data import LOADERS, SEED, Case, Suite
from evals.metrics import (
    Hit,
    acc_at,
    dedupe,
    mrr_at,
    ndcg_at,
    paired,
    recall_at,
    render,
)

BUDGETS = (1000, 2000, 4000, 8000)
PRIMARY_BUDGET = 2000
RESULTS = REPO_ROOT / "evals" / "results"
LEDGER = RESULTS / "test-ledger.jsonl"
RFC = REPO_ROOT / "docs" / "rfc" / "0003-eval-harness-and-competitor-parity.md"
MAX_FAILURE_SHARE = 0.05
# Arms whose index build runs in a subprocess and can be built concurrently.
PREFETCH = {"graphify", "inquiry", "graphify-text", "mem0", "openkb", "cognee"}

# Metrics compared between arms, per suite family (RFC-0003 primary first).
COMPARED = {
    "code": [
        "fn_hit@2000",
        "line_recall@2000",
        "file_recall@2000",
        "file_ndcg@10",
        "file_acc@5",
    ],
    "memory": [
        "unit_recall@2000",
        "unit_recall@10",
        "unit_all@10",
        "session_recall@10",
    ],
    "scifact": ["ndcg@10", "recall@100"],
}


def family(suite: Suite) -> str:
    if suite.code:
        return "code"
    return "scifact" if suite.name == "scifact" else "memory"


def score_case(
    case: Case, suite: Suite, hits: list[Hit], indexed: set[str]
) -> dict[str, float]:
    kind = family(suite)
    metrics: dict[str, float] = {}
    if kind == "code":
        files = dedupe(h.path for h in hits)
        gold_files = set(case.gold_units)
        metrics["file_ndcg@10"] = ndcg_at(files, gold_files, 10)
        metrics["file_mrr@10"] = mrr_at(files, gold_files, 10)
        metrics["file_recall@10"] = recall_at(files, gold_files, 10)
        metrics["file_acc@5"] = acc_at(files, gold_files, 5)
        metrics["gold_indexed"] = len(gold_files & indexed) / len(gold_files)
        gold_lines = sum(len(v) for v in case.gold_lines.values())
        for budget in BUDGETS:
            out = render(hits, budget)
            metrics[f"file_recall@{budget}"] = len(gold_files & set(out.paths)) / len(
                gold_files
            )
            covered = sum(
                len(lines & out.lines.get(path, set()))
                for path, lines in case.gold_lines.items()
            )
            metrics[f"line_recall@{budget}"] = (
                covered / gold_lines if gold_lines else 0.0
            )
            if case.gold_functions:
                touched = sum(out.touches(p, s, e) for p, s, e in case.gold_functions)
                metrics[f"fn_hit@{budget}"] = touched / len(case.gold_functions)
            metrics[f"tokens@{budget}"] = out.tokens
    elif kind == "scifact":
        docs = dedupe(h.path for h in hits)
        metrics["ndcg@10"] = ndcg_at(docs, case.gold_units, 10)
        metrics["recall@100"] = recall_at(docs, set(case.gold_units), 100)
        metrics["mrr@10"] = mrr_at(docs, set(case.gold_units), 10)
        metrics["gold_indexed"] = len(set(case.gold_units) & indexed) / len(
            case.gold_units
        )
    else:
        gold = set(case.gold_units)
        pattern = suite.unit_pattern
        if pattern:
            ranked = render(hits, 10**9, unit_pattern=pattern).units
        else:
            ranked = dedupe(h.path for h in hits)
        top = set(ranked[:10])
        metrics["unit_recall@10"] = len(gold & top) / len(gold)
        metrics["unit_any@10"] = 1.0 if gold & top else 0.0
        metrics["unit_all@10"] = 1.0 if gold <= top else 0.0
        for budget in BUDGETS:
            out = render(hits, budget, unit_pattern=pattern)
            seen = set(out.units) if pattern else set(out.paths)
            metrics[f"unit_recall@{budget}"] = len(gold & seen) / len(gold)
            metrics[f"tokens@{budget}"] = out.tokens
        gold_sessions = set(case.meta.get("gold_sessions", []))
        if gold_sessions:
            sessions = dedupe(unit.split("#t")[0] for unit in ranked)[:10]
            metrics["session_recall@10"] = len(gold_sessions & set(sessions)) / len(
                gold_sessions
            )
        if not pattern:
            metrics["gold_indexed"] = len(gold & indexed) / len(gold)
    return metrics


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()


def _cluster(case: Case, suite: Suite) -> str | None:
    if suite.name == "swebench":
        return str(case.meta.get("repo"))
    if suite.name == "locomo":
        return case.corpus
    return None


def guard_test_split(split: str) -> bool:
    """Return whether the tree is dirty; refuse a test-split run on a dirty tree (RFC-0003)."""
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    if split == "test" and dirty:
        raise SystemExit(
            "refusing --split test on a dirty tree (RFC-0003): commit first"
        )
    return dirty


def record_test_run(
    suite: str, arms: list[str], report: dict[str, Any], target: Path
) -> None:
    """Append every test-split run to the committed ledger, so none can go unreported."""
    entry = {
        "utc": report["provenance"]["started_utc"],
        "sha": report["provenance"]["sha"],
        "suite": suite,
        "arms": arms,
        "rfc_sha256": hashlib.sha256(RFC.read_bytes()).hexdigest(),
        "summary": report["summary"],
        "results": str(target.relative_to(REPO_ROOT)),
    }
    with LEDGER.open("a") as ledger:
        ledger.write(json.dumps(entry, sort_keys=True) + "\n")


def _prefetch(suite: Suite, corpora: list[str], arms: list[Any], jobs: int) -> None:
    """Build subprocess-arm indexes for many corpora at once to warm their caches.

    Errors are ignored here: the main loop calls ``index`` again, which
    returns the cached build or raises the failure where it is recorded.
    """
    heavy = [arm for arm in arms if arm.name in PREFETCH]
    if jobs <= 1 or not heavy:
        return

    def build(corpus: str) -> None:
        root = suite.materialize(corpus)
        for arm in heavy:
            try:
                arm.index(corpus, root, suite)
            except Exception:  # noqa: BLE001, S110 - re-raised by the main loop
                pass

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for number, _ in enumerate(pool.map(build, corpora), 1):
            print(f"  prefetched {number}/{len(corpora)}", file=sys.stderr)


@dataclass
class Retrieved:
    hits: list[Hit]
    latency_ms: float
    indexed: set[str]


def collect(
    suite: Suite, arms: list[Any], cases: list[Case], jobs: int = 1
) -> tuple[dict[tuple[str, str], Retrieved | str], dict[str, list[float]]]:
    """Index every corpus the cases need, per arm, and search each case's query.

    Returns ``(arm, case id) -> Retrieved``, or the error text when that arm
    failed on the case's corpus, plus per-arm index build seconds.
    """
    by_corpus: dict[str, list[Case]] = defaultdict(list)
    for case in cases:
        by_corpus[case.corpus].append(case)
    corpora = sorted(by_corpus)
    k = 100 if suite.name == "scifact" else 50
    out: dict[tuple[str, str], Retrieved | str] = {}
    index_seconds: dict[str, list[float]] = defaultdict(list)
    _prefetch(suite, corpora, arms, jobs)
    for number, corpus in enumerate(corpora, 1):
        root = suite.materialize(corpus)
        group = by_corpus[corpus]
        for arm in arms:
            t0 = time.perf_counter()
            try:
                handle = arm.index(corpus, root, suite)
                built = getattr(arm, "build_seconds", lambda h: None)(handle)
                index_seconds[arm.name].append(
                    built if built is not None else time.perf_counter() - t0
                )
                indexed = arm.indexed_paths(handle)
                results = arm.search(handle, [c.query for c in group], k)
            except Exception as exc:  # noqa: BLE001 - a failure is recorded per case, not raised
                detail = "".join(
                    traceback.format_exception_only(type(exc), exc)
                ).strip()[-500:]
                print(f"  ! {arm.name} failed on {corpus}: {detail}", file=sys.stderr)
                out.update({(arm.name, c.id): detail for c in group})
                continue
            for case, (hits, latency) in zip(group, results):
                out[(arm.name, case.id)] = Retrieved(hits, latency, indexed)
        print(
            f"[{number}/{len(corpora)}] {corpus}: {len(group)} cases", file=sys.stderr
        )
    return out, index_seconds


def select_cases(
    suite: Suite, split: str, limit: int | None = None, corpora_limit: int | None = None
) -> list[Case]:
    cases = [c for c in suite.cases if split == "all" or c.split == split]
    if corpora_limit:
        keep = set(sorted({c.corpus for c in cases})[:corpora_limit])
        cases = [c for c in cases if c.corpus in keep]
    return cases[:limit] if limit else cases


def applicable_arms(
    suite: Suite, arm_names: list[str], answers: bool = False
) -> list[Any]:
    # graphify is the AST-only code graph; its text path is the graphify-text
    # competitor. bm25-paths is the pointer-output control for code localization.
    # Competitors rewrite content, so they have no source spans to score outside
    # Level B (RFC-0003 amendment).
    rewriting = sorted(set(arm_names) & set(COMPETITORS))
    if rewriting and not answers:
        raise SystemExit(
            f"{', '.join(rewriting)}: Level B only (python -m evals answer)"
        )
    code_only = {"graphify", "bm25-paths"}
    return [make_arm(name) for name in arm_names if suite.code or name not in code_only]


@dataclass
class RecordedArm:
    """An arm replayed from an earlier results file, for paired before/after comparisons."""

    name: str
    source: str

    def config(self) -> dict[str, Any]:
        return {"recorded_from": self.source}


def recorded(
    path: Path, live: set[str], case_ids: set[str]
) -> tuple[list[RecordedArm], list[dict[str, Any]]]:
    """Arms replayed from an earlier results file for the given cases.

    The earlier ``inquiry`` arm is renamed ``inquiry@<sha>`` so it pairs with
    the live one; other arms keep their names and are skipped when run live.
    """
    report = json.loads(path.read_text())
    sha = report["provenance"]["sha"][:8]
    arms: list[RecordedArm] = []
    rows: list[dict[str, Any]] = []
    for name in report["summary"]:
        label = f"{name}@{sha}" if name == "inquiry" else name
        if label in live:
            continue
        arms.append(RecordedArm(label, str(path)))
        rows += [
            dict(r, arm=label)
            for r in report["rows"]
            if r["arm"] == name and r["case"] in case_ids
        ]
    return arms, rows


def run(
    suite_name: str,
    arm_names: list[str],
    split: str,
    limit: int | None = None,
    corpora_limit: int | None = None,
    jobs: int = 1,
    baseline: Path | None = None,
) -> Path:
    dirty = guard_test_split(split)
    suite = LOADERS[suite_name]()
    cases = select_cases(suite, split, limit, corpora_limit)
    arms = applicable_arms(suite, arm_names)
    arm_names = [arm.name for arm in arms]
    started = datetime.now(timezone.utc)
    retrieved, index_seconds = collect(suite, arms, cases, jobs)
    rows: list[dict[str, Any]] = []
    for arm in arms:
        for case in cases:
            got = retrieved[(arm.name, case.id)]
            if isinstance(got, str):
                rows.append({"arm": arm.name, "case": case.id, "error": got})
            else:
                metrics = score_case(case, suite, got.hits, got.indexed)
                rows.append(
                    {
                        "arm": arm.name,
                        "case": case.id,
                        "latency_ms": round(got.latency_ms, 2),
                        "metrics": metrics,
                    }
                )
    if baseline is not None:
        replay, replay_rows = recorded(
            baseline, {a.name for a in arms}, {c.id for c in cases}
        )
        arms = [*arms, *replay]
        rows.extend(replay_rows)

    report = _report(suite, cases, arms, rows, split, started, dirty, index_seconds)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    target = (
        RESULTS
        / suite.name
        / f"{split}-{stamp}-{_git('rev-parse', '--short=8', 'HEAD')}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    if split == "test":
        record_test_run(suite.name, arm_names, report, target)
    print_summary(report)
    print(f"results: {target.relative_to(REPO_ROOT)}", file=sys.stderr)
    return target


def _report(
    suite: Suite,
    cases: list[Case],
    arms: list[Any],
    rows: list[dict[str, Any]],
    split: str,
    started: datetime,
    dirty: bool,
    index_seconds: dict[str, list[float]],
) -> dict[str, Any]:
    by_arm: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_arm[row["arm"]][row["case"]] = row
    summary: dict[str, dict[str, Any]] = {}
    for arm in arms:
        arm_rows = by_arm.get(arm.name, {})
        ok = [r for r in arm_rows.values() if "metrics" in r]
        names = sorted({m for r in ok for m in r["metrics"]})
        means = {
            m: round(
                sum(r["metrics"][m] for r in ok if m in r["metrics"])
                / max(1, sum(1 for r in ok if m in r["metrics"])),
                4,
            )
            for m in names
        }
        latencies = sorted(r["latency_ms"] for r in ok)
        summary[arm.name] = {
            "cases": len(arm_rows),
            "failures": len(arm_rows) - len(ok),
            "failure_share": round(
                (len(arm_rows) - len(ok)) / max(1, len(arm_rows)), 4
            ),
            "p50_latency_ms": latencies[len(latencies) // 2] if latencies else None,
            "mean_index_s": round(
                sum(index_seconds[arm.name]) / len(index_seconds[arm.name]), 2
            )
            if index_seconds[arm.name]
            else None,
            "metrics": means,
        }
    reference = "inquiry" if "inquiry" in by_arm else (arms[0].name if arms else "")
    case_by_id = {c.id: c for c in cases}
    comparisons = []
    for other in arms:
        if other.name == reference:
            continue
        for metric in COMPARED[family(suite)]:
            shared = [
                cid
                for cid, r in by_arm[reference].items()
                if "metrics" in r
                and metric in r["metrics"]
                and "metrics" in by_arm[other.name].get(cid, {})
                and metric in by_arm[other.name][cid]["metrics"]
            ]
            if not shared:
                continue
            a = [by_arm[reference][cid]["metrics"][metric] for cid in shared]
            b = [by_arm[other.name][cid]["metrics"][metric] for cid in shared]
            clusters = [_cluster(case_by_id[cid], suite) for cid in shared]
            use_clusters = (
                None if any(c is None for c in clusters) else [str(c) for c in clusters]
            )
            stats = paired(a, b, seed=SEED, clusters=use_clusters)
            valid = (
                summary[reference]["failure_share"] <= MAX_FAILURE_SHARE
                and summary[other.name]["failure_share"] <= MAX_FAILURE_SHARE
            )
            comparisons.append(
                {
                    "metric": metric,
                    "a": reference,
                    "b": other.name,
                    "valid": valid,
                    "clustered": use_clusters is not None,
                    **stats,
                }
            )
    return {
        "schema": "InquiryEval/v1",
        "suite": suite.name,
        "split": split,
        "budget_tokens": PRIMARY_BUDGET,
        "provenance": {
            "sha": _git("rev-parse", "HEAD"),
            "dirty": dirty,
            "started_utc": started.isoformat(timespec="seconds"),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "seed": SEED,
            "rfc_sha256": hashlib.sha256(RFC.read_bytes()).hexdigest(),
            "datasets": suite.data_sha256,
            "dropped": suite.dropped,
            "arms": {arm.name: arm.config() for arm in arms},
            "tokenizer": "tiktoken cl100k_base",
        },
        "summary": summary,
        "comparisons": comparisons,
        "rows": rows,
    }


def print_summary(report: dict[str, Any]) -> None:
    kind = (
        "code"
        if report["suite"] in ("swebench", "erpnext")
        else ("scifact" if report["suite"] == "scifact" else "memory")
    )
    metrics = COMPARED[kind]
    arms = list(report["summary"])
    width = max(len(a) for a in arms) if arms else 5
    print(
        f"\n{report['suite']} / {report['split']}  (n={max(s['cases'] for s in report['summary'].values())})"
    )
    print(
        "arm".ljust(width) + "  " + "  ".join(m.rjust(16) for m in metrics) + "  fail"
    )
    for arm in arms:
        values = report["summary"][arm]["metrics"]
        cells = "  ".join(f"{values.get(m, float('nan')):16.4f}" for m in metrics)
        print(f"{arm.ljust(width)}  {cells}  {report['summary'][arm]['failures']}")
    for comp in report["comparisons"]:
        if comp["metric"] == metrics[0]:
            flag = "" if comp["valid"] else " (invalid: failures)"
            print(
                f"  {comp['a']} - {comp['b']}: {comp['mean_diff']:+.4f} "
                f"[{comp['ci_low']:+.4f}, {comp['ci_high']:+.4f}] p={comp['p_perm']:.4f} mde={comp['mde']:.4f}{flag}"
            )
