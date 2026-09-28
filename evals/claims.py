"""RFC-0004 claims: run one claim once and report correctness, time and cost per arm.

``python -m evals claim c1|c2|c3 --split dev|test`` writes
``evals/results/claims/<claim>-<split>-<utc>-<sha8>.json``. Every item is
scored pass/fail; a failure anywhere in an arm's pipeline is a fail. Each
comparison is ``inquiry`` against one other arm: an exact McNemar test with
Holm correction within the claim, plus paired ratios of time and cost.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.data import SEED, Case
from evals.metrics import Hit, holm, mcnemar, ratio_interval, render
from evals.run import RESULTS, _git

BUDGET = 2000
# USD per million input and output tokens, published by the provider on 2026-09-27 (RFC-0004).
PRICES = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
}
CLAIMS_DIR = RESULTS / "claims"


def dollars(model: str, input_tokens: float, output_tokens: float) -> float:
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


_OVERHEAD: dict[tuple[str, bool], dict[str, int]] = {}


def cli_overhead(model: str, schema: bool = False) -> dict[str, int]:
    """Input tokens and API milliseconds ``claude -p`` adds to one call of this shape,
    measured once on a one-character prompt."""
    if (model, schema) not in _OVERHEAD:
        from evals.answer import _claude

        probe = _claude(
            model,
            "x",
            {"type": "object", "properties": {"x": {"type": "string"}}}
            if schema
            else None,
        )
        _OVERHEAD[(model, schema)] = {
            "input_tokens": max(0, int(probe["input_tokens"]) - 1),
            "api_ms": int(probe.get("api_ms", 0)),
        }
    return _OVERHEAD[(model, schema)]


def usage_cost(model: str, usage: dict[str, int]) -> dict[str, float]:
    """Cost of a tool's calls counted by the shim, minus the CLI's per-call overhead."""
    plain, schema = cli_overhead(model), cli_overhead(model, schema=True)
    schema_calls = usage.get("schema_calls", 0)
    plain_calls = usage.get("calls", 0) - schema_calls
    overhead_in = (
        plain_calls * plain["input_tokens"] + schema_calls * schema["input_tokens"]
    )
    overhead_ms = plain_calls * plain["api_ms"] + schema_calls * schema["api_ms"]
    input_tokens = max(0, usage.get("input_tokens", 0) - overhead_in)
    output_tokens = usage.get("output_tokens", 0)
    return {
        "calls": usage.get("calls", 0),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "api_s": round(max(0, usage.get("api_ms", 0) - overhead_ms) / 1000, 3),
        "dollars": round(dollars(model, input_tokens, output_tokens), 6),
    }


def call_cost(record: dict[str, Any], model: str) -> dict[str, float]:
    """One call made on a tool's behalf (answering, judging), minus CLI overhead."""
    return usage_cost(
        model,
        {
            "calls": 1,
            "input_tokens": int(record.get("input_tokens", 0)),
            "output_tokens": int(record.get("output_tokens", 0)),
            "api_ms": int(record.get("api_ms", 0)),
        },
    )


INFRA_ERROR = re.compile(
    r"timeout|timed out|TimeoutExpired|rate limit|overloaded|usage limit|too many requests|529",
    re.I,
)
MAX_INFRA_FAILURE_SHARE = 0.05


def compare(
    rows: list[dict[str, Any]], arms: Sequence[str], reference: str = "inquiry"
) -> list[dict[str, Any]]:
    """``reference`` against every other arm on the items both have."""
    by_arm: dict[str, dict[str, dict[str, Any]]] = {arm: {} for arm in arms}
    for row in rows:
        by_arm[row["arm"]][row["item"]] = row
    tests: dict[str, dict[str, Any]] = {}
    for other in arms:
        if other == reference:
            continue
        items = sorted(set(by_arm[reference]) & set(by_arm[other]))
        a = [by_arm[reference][i] for i in items]
        b = [by_arm[other][i] for i in items]
        tests[other] = {
            "a": reference,
            "b": other,
            **mcnemar([r["correct"] for r in a], [r["correct"] for r in b]),
            "seconds_ratio": ratio_interval(
                [r["seconds"] for r in a], [r["seconds"] for r in b], seed=SEED
            ),
            "dollars_ratio": ratio_interval(
                [r["dollars"] for r in a], [r["dollars"] for r in b], seed=SEED
            ),
            "tokens_ratio": ratio_interval(
                [r["tokens"] for r in a], [r["tokens"] for r in b], seed=SEED
            ),
        }
    adjusted = holm({other: t["p"] for other, t in tests.items()})
    out = []
    for other, test in tests.items():
        infra = {
            arm: sum(1 for r in by_arm[arm].values() if r.get("infra"))
            / max(1, len(by_arm[arm]))
            for arm in (reference, other)
        }
        test["infra_failure_share"] = {k: round(v, 4) for k, v in infra.items()}
        test["valid"] = all(v <= MAX_INFRA_FAILURE_SHARE for v in infra.values())
        test["p_holm"] = adjusted[other]
        test["decided"] = test["valid"] and adjusted[other] < 0.05
        test["significant"] = test["decided"] and test["a_only"] > test["b_only"]
        out.append(test)
    return out


def summarize(
    rows: list[dict[str, Any]], arms: Sequence[str], setup: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    summary = {}
    for arm in arms:
        items = [r for r in rows if r["arm"] == arm]
        correct = sum(r["correct"] for r in items)
        total_dollars = sum(r["dollars"] for r in items) + setup[arm].get(
            "dollars", 0.0
        )
        total_seconds = sum(r["seconds"] for r in items) + setup[arm].get(
            "seconds", 0.0
        )
        summary[arm] = {
            "items": len(items),
            "correct": correct,
            "accuracy": round(correct / len(items), 4) if items else 0.0,
            "failures": sum(1 for r in items if r.get("error")),
            "median_tokens": sorted(r["tokens"] for r in items)[len(items) // 2]
            if items
            else 0,
            "setup": setup[arm],
            "dollars": round(total_dollars, 4),
            "seconds": round(total_seconds, 1),
            "dollars_per_correct": round(total_dollars / correct, 4)
            if correct
            else None,
            "seconds_per_correct": round(total_seconds / correct, 1)
            if correct
            else None,
        }
    return summary


FROZEN_CODE_HASH = "a45c43efd352e8db"  # RFC-0004: e32fb55 plus the ai search exit fix


def begin(claim: str, split: str, arms: dict[str, Any], options: dict[str, Any]) -> str:
    """For a test run: refuse a dirty tree or an unfrozen ``inquiry``, then record and
    commit the start before any work, so a run cannot be dropped without trace."""
    if split != "test":
        return ""
    from evals.arms import Inquiry
    from evals.run import LEDGER, begin_test_run, guard_clean_tree

    guard_clean_tree()
    if (
        os.environ.get("EVALS_INQUIRY_CONFIG")
        or Inquiry().code_hash != FROZEN_CODE_HASH
    ):
        raise SystemExit(
            f"inquiry is not the frozen system (code_hash {Inquiry().code_hash}, "
            f"expected {FROZEN_CODE_HASH}, EVALS_INQUIRY_CONFIG unset)"
        )
    run_id = begin_test_run(f"claim-{claim}", arms, options)
    _git("add", str(LEDGER))
    _git(
        "commit",
        "--quiet",
        "-m",
        f"chore(evals): start the {claim} test run {run_id[:8]}",
    )
    if _git("status", "--porcelain"):
        raise SystemExit("could not commit the ledger start entry; resolve and rerun")
    return run_id


def environment() -> dict[str, Any]:
    """Versions a rerun must match: the Claude CLI, local models and each tool's packages."""
    import subprocess

    from evals.answer import _ollama_digest
    from evals.arms import COMPETITORS, CACHE, OLLAMA_MODEL

    def run(*args: str) -> str:
        proc = subprocess.run(args, capture_output=True, text=True)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    venvs = {name: CACHE / "venvs" / venv for name, (_, venv) in COMPETITORS.items()}
    venvs["graphify"] = CACHE / "venvs" / "graphifyy-mcp-0.9.68"
    return {
        "claude_cli": run("claude", "--version"),
        "ollama": {m: _ollama_digest(m) for m in (OLLAMA_MODEL, SECOND_JUDGE)},
        "venv_freeze_sha256": {
            name: hashlib.sha256(
                run(
                    "uv", "pip", "freeze", "--python", str(path / "bin" / "python")
                ).encode()
            ).hexdigest()
            for name, path in venvs.items()
            if (path / "bin" / "python").exists()
        },
    }


def save(
    claim: str,
    split: str,
    started: datetime,
    arms: Sequence[str],
    body: dict[str, Any],
    provenance: dict[str, Any],
    run_id: str = "",
) -> Path:
    """Write a claim's results with full provenance and, for a test run, its ledger end entry."""
    report = {
        "schema": "InquiryClaims/v1",
        "claim": claim,
        "split": split,
        "budget_tokens": BUDGET,
        "provenance": {
            "sha": _git("rev-parse", "HEAD"),
            # The ledger's own start entry is the only change a clean run carries.
            "dirty": any(
                not line.endswith("test-ledger.jsonl")
                for line in _git("status", "--porcelain").splitlines()
            ),
            "environment": environment(),
            "started_utc": started.isoformat(timespec="seconds"),
            "seed": SEED,
            "prices_per_mtok": PRICES,
            **provenance,
        },
        **body,
    }
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    target = (
        CLAIMS_DIR
        / f"{claim}-{split}-{stamp}-{_git('rev-parse', '--short=8', 'HEAD')}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    if run_id:
        from evals.run import record_test_run

        record_test_run(run_id, f"claim-{claim}", list(arms), report, target)
    print(f"results: {target.relative_to(RESULTS.parent.parent)}", file=sys.stderr)
    return target


def write_results(
    claim: str,
    split: str,
    started: datetime,
    arms: Sequence[str],
    rows: list[dict[str, Any]],
    setup: dict[str, dict[str, Any]],
    provenance: dict[str, Any],
    run_id: str = "",
    comparisons: list[dict[str, Any]] | None = None,
) -> Path:
    body = {
        "summary": summarize(rows, arms, setup),
        "comparisons": comparisons if comparisons is not None else compare(rows, arms),
        "rows": rows,
    }
    print_report({"claim": claim, "split": split, **body})
    return save(claim, split, started, arms, body, provenance, run_id)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3g}"


def print_report(report: dict[str, Any]) -> None:
    print(f"\n{report['claim']} / {report['split']}", file=sys.stderr)
    print(
        f"{'arm':10} {'items':>5} {'acc':>6} {'fail':>4} {'med tok':>7} {'$':>9} {'$/correct':>10} {'s/correct':>9}",
        file=sys.stderr,
    )
    for arm, s in report["summary"].items():
        print(
            f"{arm:10} {s['items']:5d} {s['accuracy']:6.3f} {s['failures']:4d} {s['median_tokens']:7d} "
            f"{s['dollars']:9.4f} {s['dollars_per_correct'] or 0:10.4f} {s['seconds_per_correct'] or 0:9.1f}",
            file=sys.stderr,
        )
    for c in report["comparisons"]:
        print(
            f"  {c['a']} vs {c['b']}: {c['a_only']}-{c['b_only']} discordant, "
            f"p={c['p']:.4f} holm={c['p_holm']:.4f} significant={c['significant']}; "
            f"cost x{_fmt(c['dollars_ratio']['ratio'])} time x{_fmt(c['seconds_ratio']['ratio'])}",
            file=sys.stderr,
        )


# --------------------------------------------------------------------------
# C2: code retrieval on SWE-bench Verified
# --------------------------------------------------------------------------


def found_function(case: Case, hits: list[Any]) -> bool:
    """A changed function has a rendered line, or a location line, inside it within the budget."""
    out = render(hits, BUDGET)
    return any(
        out.touches(path, start, end) for path, start, end in case.gold_functions
    )


def cli_query_seconds(arm: str, query: str, root: Path, handle: Any) -> float:
    """Wall-clock of one cold command-line query, the way an agent calls the tool."""
    import subprocess
    import time

    from evals.arms import Graphify, Inquiry

    if arm == "graphify":
        binary = Graphify(default_build=True).venv / "bin" / "graphify"
        command, cwd, env = (
            [str(binary), "query", query, "--graph", "graph.json"],
            Path(handle),
            dict(os.environ),
        )
    else:
        store, _ = handle
        command, cwd = [str(Path(sys.executable).parent / "ai"), "search", query], root
        env = dict(
            os.environ,
            INQUIRY_CONFIG=str(Inquiry().config_path),
            INQUIRY_STORAGE_ROOT=str(store),
            INQUIRY_STORAGE_DEFAULT_PROJECT_ID="eval",
            INQUIRY_STORAGE_BACKEND="lancedb",
            INQUIRY_LOGGING_LEVEL="ERROR",
            TOKENIZERS_PARALLELISM="false",
            HF_HUB_OFFLINE="1",
        )
    t0 = time.perf_counter()
    subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, check=True, timeout=600
    )
    return round(time.perf_counter() - t0, 3)


def run_c2(split: str, jobs: int, limit: int | None = None) -> Path:
    from evals.arms import Graphify, Inquiry
    from evals.data import LOADERS
    from evals.run import collect, select_cases

    suite = LOADERS["swebench"]()
    cases = select_cases(suite, split, limit)
    arms: list[Any] = [Inquiry(), Graphify(default_build=True)]
    run_id = begin(
        "c2",
        split,
        {a.name: a.config() for a in arms},
        {"items": len(cases), "jobs": jobs},
    )
    started = datetime.now(timezone.utc)
    retrieved, index_seconds = collect(suite, arms, cases, jobs)
    rows: list[dict[str, Any]] = []
    # Each task's two command-line queries run back to back, so both tools see
    # the same machine load.
    for case in cases:
        root = suite.materialize(case.corpus)
        for arm in arms:
            got = retrieved[(arm.name, case.id)]
            if isinstance(got, str):
                rows.append(_fail(arm.name, case.id, got))
                continue
            try:
                seconds = cli_query_seconds(
                    arm.name, case.query, root, arm.index(case.corpus, root, suite)
                )
            except Exception as exc:  # noqa: BLE001 - a failure scores as wrong
                rows.append(
                    _fail(arm.name, case.id, f"command-line query failed: {exc}")
                )
                continue
            rows.append(
                {
                    "arm": arm.name,
                    "item": case.id,
                    "correct": found_function(case, got.hits),
                    "seconds": seconds,
                    "in_process_seconds": round(got.latency_ms / 1000, 3),
                    "tokens": render(got.hits, BUDGET).tokens,
                    "dollars": 0.0,
                }
            )
    setup = {
        arm.name: {
            "seconds": round(sum(index_seconds[arm.name]), 1),
            "corpora": len(index_seconds[arm.name]),
            "llm_calls": 0,
            "dollars": 0.0,
        }
        for arm in arms
    }
    return write_results(
        "c2",
        split,
        started,
        [a.name for a in arms],
        rows,
        setup,
        {
            "arms": {a.name: a.config() for a in arms},
            "items": [c.id for c in cases],
            "timing": "seconds is one cold command-line query per task for both tools",
        },
        run_id,
    )


def _fail(arm: str, item: str, error: str) -> dict[str, Any]:
    return {
        "arm": arm,
        "item": item,
        "correct": False,
        "error": error[-500:],
        "infra": bool(INFRA_ERROR.search(error)),
        "seconds": 0.0,
        "tokens": 0,
        "dollars": 0.0,
    }


def sample_digest(ids: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


# --------------------------------------------------------------------------
# C1: memory retrieval on LongMemEval-S
# --------------------------------------------------------------------------

C1_ITEMS = 100
C1_ARMS = ("inquiry", "full", "dense", "hybrid", "mem0-raw", "cognee-chunks")
C1B_HISTORIES = 7
C1B_ARMS = ("inquiry", "mem0", "cognee")
ANSWERER = "claude-haiku-4-5-20251001"
JUDGE = "claude-sonnet-5"
SECOND_JUDGE = "qwen2.5:14b-instruct"

# One prompt for every arm, neutral about the context's shape (RFC-0004).
C1_ANSWER_PROMPT = """Answer a question about past conversations between a user and an assistant, using only the context below. The context may be excerpts of the conversations, facts extracted from them, or notes, and may carry dates.

Context:
{context}

Current date: {date}
Question: {question}

Answer concisely. Resolve relative times ("last week", "two months ago") against the dates in the context and the current date. If the context does not contain the answer, say that you do not know."""

# LongMemEval's official judge prompts (xiaowu0162/LongMemEval @ 9e0b455,
# src/evaluation/evaluate_qa.py, get_anscheck_prompt), MIT licence.
_LME_BASE = (
    "I will give you a question, a correct answer, and a response from a model. "
    "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
    "If the response is equivalent to the correct answer or contains all the intermediate "
    "steps to get the correct answer, you should also answer yes. If the response only "
    "contains a subset of the information required by the answer, answer no. "
)
_LME_TAIL = "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
LME_JUDGE = {
    "single-session-user": _LME_BASE + _LME_TAIL,
    "single-session-assistant": _LME_BASE + _LME_TAIL,
    "multi-session": _LME_BASE + _LME_TAIL,
    "temporal-reasoning": _LME_BASE
    + "In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct. "
    + _LME_TAIL,
    "knowledge-update": "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer."
    + _LME_TAIL,
    "single-session-preference": "I will give you a question, a rubric for desired personalized response, and a response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only.",
}


def judge_prompt(kind: str, question: str, gold: str, response: str) -> str:
    return LME_JUDGE[kind].format(question, gold, response)


def parse_yes(text: str) -> bool:
    """LongMemEval's scorer: the verdict is correct when the judge's reply contains "yes"."""
    return "yes" in text.lower()


def c1_sample(cases: Sequence[Case], n: int) -> list[Case]:
    """``n`` questions allocated to question types in proportion to their counts (largest
    remainder), taking the lowest ``sha256(SEED:question_id)`` within each type."""
    by_type: dict[str, list[Case]] = {}
    for case in cases:
        by_type.setdefault(case.meta["type"], []).append(case)
    total = sum(len(v) for v in by_type.values())
    quotas = {k: n * len(v) / total for k, v in by_type.items()}
    counts = {k: int(q) for k, q in quotas.items()}
    for kind in sorted(quotas, key=lambda k: (-(quotas[k] - counts[k]), k))[
        : n - sum(counts.values())
    ]:
        counts[kind] += 1

    def order(case: Case) -> str:
        return hashlib.sha256(f"{SEED}:{case.id}".encode()).hexdigest()

    return [
        c
        for kind in sorted(by_type)
        for c in sorted(by_type[kind], key=order)[: counts[kind]]
    ]


def full_history(root: Path) -> str:
    """Every session of a haystack, in date order, as the no-tool context."""
    from evals.competitor_worker import sessions

    return "\n".join(
        path.read_text(encoding="utf-8").rstrip("\n") for path in sessions(root)
    )


REVIEW_SAMPLE = 100


def run_c1(split: str, jobs: int, limit: int | None = None) -> Path:
    from concurrent.futures import ThreadPoolExecutor

    from evals.answer import cohen_kappa, complete
    from evals.arms import Competitor, Inquiry, make_arm
    from evals.data import LOADERS
    from evals.metrics import count_tokens

    suite = LOADERS["longmemeval"]()
    pool = [c for c in suite.cases if c.split == split]
    cases = c1_sample(pool, C1_ITEMS if split == "test" else limit or 6)
    inquiry = Inquiry()
    retrievers: dict[str, Any] = {
        "inquiry": inquiry,
        "dense": make_arm("dense"),
        "hybrid": make_arm("hybrid"),
    }
    tools = {name: Competitor(name) for name in ("mem0-raw", "cognee-chunks")}
    run_id = begin(
        "c1",
        split,
        {
            **{n: a.config() for n, a in retrievers.items()},
            **{n: t.config() for n, t in tools.items()},
        },
        {"items": len(cases), "jobs": jobs},
    )
    started = datetime.now(timezone.utc)
    contexts: dict[tuple[str, str], dict[str, Any]] = {}

    def build(case: Case) -> None:
        """Every arm's context for one question, each from its own index of the history."""
        root = suite.materialize(case.corpus)
        history = full_history(root)
        contexts[("full", case.id)] = {
            "context": history,
            "raw_tokens": count_tokens(history),
            "query_s": 0.0,
            "setup_s": 0.0,
            "setup": {},
            "query": {},
        }
        for name, arm in retrievers.items():
            try:
                t0 = time.perf_counter()
                handle = arm.index(case.corpus, root, suite)
                built = getattr(arm, "build_seconds", lambda h: None)(handle)
                setup_s = built if built is not None else time.perf_counter() - t0
                ((hits, latency_ms),) = arm.search(handle, [case.query], 50)
                rendered = render(hits, BUDGET)
                contexts[(name, case.id)] = {
                    "context": rendered.text,
                    "raw_tokens": rendered.tokens,
                    "query_s": latency_ms / 1000,
                    "setup_s": setup_s,
                    "setup": {},
                    "query": {},
                }
            except Exception as exc:  # noqa: BLE001 - a failure scores as wrong
                contexts[(name, case.id)] = {"error": str(exc)}
        for name, tool in tools.items():
            try:
                handle = tool.index(case.corpus, root, suite)
                info = tool.build_info(handle)
                (result,) = tool.query(handle, [case.query])
                if result["error"]:
                    raise RuntimeError(result["error"])
                contexts[(name, case.id)] = {
                    # Each tool's output in its own order, cut at the shared budget.
                    "context": render([Hit("", 0, 0, result["context"])], BUDGET).text,
                    "raw_tokens": count_tokens(result["context"]),
                    "query_s": result["seconds"],
                    "setup_s": info["seconds"],
                    "setup": info.get("llm", {}),
                    "query": result["llm"] or {},
                    "items_stored": info.get("items"),
                }
            except Exception as exc:  # noqa: BLE001 - a failure scores as wrong
                contexts[(name, case.id)] = {"error": str(exc)}

    def answer(item: tuple[str, Case]) -> dict[str, Any]:
        arm, case = item
        got = contexts[(arm, case.id)]
        if "error" in got:
            return _fail(arm, case.id, got["error"])
        prompt = judge_prompt
        try:
            reply = complete(
                ANSWERER,
                C1_ANSWER_PROMPT.format(
                    context=got["context"],
                    date=case.meta["question_date"],
                    question=case.query,
                ),
            )
            verdict = complete(
                JUDGE,
                prompt(
                    case.meta["type"], case.query, case.meta["answer"], reply["text"]
                ),
            )
        except Exception as exc:  # noqa: BLE001 - a failure scores as wrong
            return _fail(arm, case.id, str(exc))
        try:
            second: bool | None = parse_yes(
                complete(
                    SECOND_JUDGE,
                    prompt(
                        case.meta["type"],
                        case.query,
                        case.meta["answer"],
                        reply["text"],
                    ),
                )["text"]
            )
        except Exception:  # noqa: BLE001 - the check judge does not score items
            second = None
        setup = usage_cost(ANSWERER, got["setup"]) if got["setup"] else None
        query = usage_cost(ANSWERER, got["query"]) if got["query"] else None
        answer_cost = call_cost(reply, ANSWERER)
        llm_dollars = answer_cost["dollars"] + sum(
            c["dollars"] for c in (setup, query) if c
        )
        llm_api_s = answer_cost["api_s"] + sum(c["api_s"] for c in (setup, query) if c)
        return {
            "arm": arm,
            "item": case.id,
            "type": case.meta["type"],
            "correct": parse_yes(verdict["text"]),
            "second_judge": second,
            "answer": reply["text"],
            "gold": case.meta["answer"],
            "tokens": count_tokens(got["context"]),
            "raw_tokens": got["raw_tokens"],
            "setup_seconds": round(got["setup_s"], 3),
            "query_seconds": round(got["query_s"], 3),
            "answer_api_seconds": answer_cost["api_s"],
            # Wall-clock of this question's index or ingest and query, plus the
            # answer call's API time (the answer step is the same for every arm).
            "seconds": round(got["setup_s"] + got["query_s"] + answer_cost["api_s"], 3),
            "api_seconds": round(llm_api_s, 3),
            "setup_llm": setup,
            "query_llm": query,
            "answer_input_tokens": answer_cost["input_tokens"],
            "items_stored": got.get("items_stored"),
            "dollars": round(llm_dollars, 6),
        }

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        list(executor.map(build, cases))
    with ThreadPoolExecutor(max_workers=4) as executor:
        rows = list(
            executor.map(answer, [(arm, case) for arm in C1_ARMS for case in cases])
        )
    judged = [r for r in rows if "error" not in r]
    labelled = [r for r in judged if r["second_judge"] is not None]
    if split == "test" and len(labelled) < 0.95 * len(judged):
        raise SystemExit(
            f"the check judge labelled {len(labelled)} of {len(judged)} answers"
        )
    # Setup is attributed to each question (each has its own haystack), not added again.
    setup_totals = {arm: {"seconds": 0.0, "dollars": 0.0} for arm in C1_ARMS}
    review = sorted(
        judged,
        key=lambda r: hashlib.sha256(
            f"{SEED}:{r['arm']}:{r['item']}".encode()
        ).hexdigest(),
    )[:REVIEW_SAMPLE]
    target = write_results(
        "c1",
        split,
        started,
        C1_ARMS,
        rows,
        setup_totals,
        {
            "arms": {
                **{n: a.config() for n, a in retrievers.items()},
                **{n: t.config() for n, t in tools.items()},
            },
            "answerer": ANSWERER,
            "judge": JUDGE,
            "second_judge": SECOND_JUDGE,
            "cli_overhead": {
                f"{m}{'+schema' if sc else ''}": v for (m, sc), v in _OVERHEAD.items()
            },
            "answer_prompt_sha256": hashlib.sha256(
                C1_ANSWER_PROMPT.encode()
            ).hexdigest(),
            "full_history_max_tokens": max(
                (contexts[("full", c.id)]["raw_tokens"] for c in cases), default=0
            ),
            "judge_agreement": {
                "n": len(labelled),
                "kappa": round(
                    cohen_kappa(
                        [int(r["correct"]) for r in labelled],
                        [int(bool(r["second_judge"])) for r in labelled],
                    ),
                    4,
                ),
            },
            "items": [c.id for c in cases],
        },
        run_id,
    )
    # A person reviews these verdicts before any claim is published (RFC-0004).
    sample = target.with_name(target.stem + "-review.json")
    sample.write_text(
        json.dumps(
            [
                {
                    k: r[k]
                    for k in (
                        "arm",
                        "item",
                        "type",
                        "gold",
                        "answer",
                        "correct",
                        "second_judge",
                    )
                }
                for r in review
            ],
            indent=1,
        )
        + "\n"
    )
    return target


# --------------------------------------------------------------------------
# C1b: memory tools' ingestion cost and time
# --------------------------------------------------------------------------


def c1b_sample(cases: Sequence[Case], n: int) -> list[Case]:
    """The ``n`` questions with the lowest ``sha256(SEED:question_id)``."""
    return sorted(
        cases, key=lambda c: hashlib.sha256(f"{SEED}:{c.id}".encode()).hexdigest()
    )[:n]


def run_c1b(split: str, jobs: int, limit: int | None = None) -> Path:
    from concurrent.futures import ThreadPoolExecutor

    from evals.arms import Competitor, Inquiry
    from evals.data import LOADERS
    from evals.metrics import count_tokens

    suite = LOADERS["longmemeval"]()
    pool = [c for c in suite.cases if c.split == split]
    if split == "test":
        cases = c1b_sample(c1_sample(pool, C1_ITEMS), C1B_HISTORIES)
    else:
        cases = c1b_sample(pool, limit or 2)
    inquiry = Inquiry()
    tools = {name: Competitor(name) for name in ("mem0", "cognee")}
    run_id = begin(
        "c1b",
        split,
        {"inquiry": inquiry.config(), **{n: t.config() for n, t in tools.items()}},
        {"items": len(cases), "jobs": jobs},
    )
    started = datetime.now(timezone.utc)

    def measure(case: Case) -> list[dict[str, Any]]:
        """Each arm's ingestion of one history, normalized per million conversation tokens."""
        root = suite.materialize(case.corpus)
        tokens = count_tokens(full_history(root))
        per_m = 1_000_000 / tokens
        rows: list[dict[str, Any]] = []
        try:
            store, _ = inquiry.index(case.corpus, root, suite)
            rows.append(
                {
                    "arm": "inquiry",
                    "item": case.id,
                    "conversation_tokens": tokens,
                    "llm_calls": 0,
                    "dollars": 0.0,
                    "api_seconds": 0.0,
                    "seconds": inquiry.build_seconds((store, root)) or 0.0,
                }
            )
        except Exception as exc:  # noqa: BLE001 - recorded, never dropped
            rows.append(_fail("inquiry", case.id, str(exc)))
        for name, tool in tools.items():
            try:
                info = tool.build_info(tool.index(case.corpus, root, suite))
                cost = usage_cost(ANSWERER, info.get("llm", {}))
                rows.append(
                    {
                        "arm": name,
                        "item": case.id,
                        "conversation_tokens": tokens,
                        "llm_calls": cost["calls"],
                        "input_tokens": cost["input_tokens"],
                        "output_tokens": cost["output_tokens"],
                        "cache_hits": info.get("llm", {}).get("cache_hits", 0),
                        "items_stored": info.get("items"),
                        "dollars": cost["dollars"],
                        "api_seconds": cost["api_s"],
                        "seconds": info["seconds"],
                    }
                )
            except Exception as exc:  # noqa: BLE001 - recorded, never dropped
                rows.append(_fail(name, case.id, str(exc)))
        for row in rows:
            for key in ("dollars", "api_seconds", "seconds", "llm_calls"):
                if key in row and "error" not in row:
                    row[f"{key}_per_mtok"] = round(row[key] * per_m, 6)
        return rows

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        for part in executor.map(measure, cases):
            rows += part
    arms = ("inquiry", *tools)
    by_arm = {arm: {r["item"]: r for r in rows if r["arm"] == arm} for arm in arms}
    summary = {
        arm: {
            "histories": len(items),
            "failures": sum(1 for r in items.values() if "error" in r),
            **{
                f"mean_{key}_per_mtok": round(
                    sum(r.get(f"{key}_per_mtok", 0) for r in items.values())
                    / max(1, len(items)),
                    4,
                )
                for key in ("dollars", "api_seconds", "seconds", "llm_calls")
            },
        }
        for arm, items in by_arm.items()
    }
    tests: dict[str, dict[str, Any]] = {}
    for name in tools:
        shared = sorted(
            i
            for i in set(by_arm["inquiry"]) & set(by_arm[name])
            if "error" not in by_arm["inquiry"][i] and "error" not in by_arm[name][i]
        )
        a = [by_arm["inquiry"][i] for i in shared]
        b = [by_arm[name][i] for i in shared]
        # A failed build is not cheaper: the tool loses that history.
        failed = sum(1 for i in by_arm[name] if "error" in by_arm[name][i])
        sign = mcnemar(
            [x["dollars_per_mtok"] < y["dollars_per_mtok"] for x, y in zip(a, b)]
            + [True] * failed,
            [y["dollars_per_mtok"] < x["dollars_per_mtok"] for x, y in zip(a, b)]
            + [False] * failed,
        )
        tests[name] = {
            "a": "inquiry",
            "b": name,
            "histories": len(shared) + failed,
            "inquiry_cheaper": sign["a_only"],
            "tool_cheaper": sign["b_only"],
            "p": sign["p"],
            "dollars_ratio": ratio_interval(
                [x["dollars_per_mtok"] for x in a],
                [y["dollars_per_mtok"] for y in b],
                seed=SEED,
            ),
            "api_seconds_ratio": ratio_interval(
                [x["api_seconds_per_mtok"] for x in a],
                [y["api_seconds_per_mtok"] for y in b],
                seed=SEED,
            ),
            "seconds_ratio": ratio_interval(
                [x["seconds_per_mtok"] for x in a],
                [y["seconds_per_mtok"] for y in b],
                seed=SEED,
            ),
        }
    adjusted = holm({name: t["p"] for name, t in tests.items()})
    comparisons = []
    for name, test in tests.items():
        test["p_holm"] = adjusted[name]
        test["significant"] = (
            adjusted[name] < 0.05 and test["inquiry_cheaper"] > test["tool_cheaper"]
        )
        comparisons.append(test)
    print(f"\nc1b / {split}", file=sys.stderr)
    for arm, s in summary.items():
        print(
            f"{arm:8} histories {s['histories']}  ${s['mean_dollars_per_mtok']:.2f}/Mtok  "
            f"LLM {s['mean_api_seconds_per_mtok']:.0f}s/Mtok  wall {s['mean_seconds_per_mtok']:.0f}s/Mtok",
            file=sys.stderr,
        )
    for c in comparisons:
        print(
            f"  inquiry vs {c['b']}: cheaper on {c['inquiry_cheaper']} of {c['histories']}, "
            f"p={c['p']:.4f} holm={c['p_holm']:.4f} significant={c['significant']}",
            file=sys.stderr,
        )
    return save(
        "c1b",
        split,
        started,
        arms,
        {"summary": summary, "comparisons": comparisons, "rows": rows},
        {
            "arms": {
                "inquiry": inquiry.config(),
                **{n: t.config() for n, t in tools.items()},
            },
            "ingestion_model": ANSWERER,
            "cli_overhead": {
                f"{m}{'+schema' if sc else ''}": v for (m, sc), v in _OVERHEAD.items()
            },
            "items": [c.id for c in cases],
        },
        run_id,
    )


# --------------------------------------------------------------------------
# C3: coding-agent outcomes on fixes merged after the agent's cutoff
# --------------------------------------------------------------------------

C3_ARMS = ("floor", "inquiry", "graphify")
AGENT_MODEL = "claude-sonnet-5"
C3_PROMPT = """You are investigating a GitHub issue in the repository in your current working directory.
Find the code that would need to change to resolve it. You cannot edit files.

Issue:
{query}

You have at most {budget} tool calls. Answer before you run out, even if you are unsure.
End your reply with a line `LOCATIONS:` followed by up to 5 lines, each `path:line`
(the repository-relative path and the line number of code to change), most likely first."""

# Each tool's own agent guidance (RFC-0004): Graphify's published CLAUDE.md rules,
# verbatim; Agentic Inquiry ships its advice as a Grep hook that suggests its
# search, restated here as a standing instruction because hooks and slash
# commands do not run in a headless session.
INQUIRY_GUIDANCE = (
    "## Agentic Inquiry\n\nThis project is indexed by Agentic Inquiry. For conceptual or "
    "natural-language searches (how, what, where, why, or concepts rather than literal code symbols), "
    'run `ai search "<query>"` instead of Grep.'
)


_LOCATION = re.compile(r"([^\s`'\"()\[\]<>]+?\.[A-Za-z0-9]+):(\d+)")
MAX_LOCATIONS = 5


def cited_locations(text: str, roots: Sequence[Path]) -> list[tuple[str, int]]:
    """The first five ``path:line`` pairs after the last ``LOCATIONS:``, as repository paths.

    Agents often cite absolute paths (tool output is absolute), so any prefix
    naming the working tree or the snapshot is stripped.
    """
    tail = text.rsplit("LOCATIONS:", 1)[-1] if "LOCATIONS:" in text else text
    prefixes = sorted(
        {
            str(p).rstrip("/") + "/"
            for root in roots
            for p in (root, Path(os.path.realpath(root)))
        },
        key=len,
        reverse=True,
    )
    out: list[tuple[str, int]] = []
    for path, line in _LOCATION.findall(tail):
        for prefix in prefixes:
            if path.startswith(prefix):
                path = path[len(prefix) :]
                break
        out.append((path.removeprefix("./"), int(line)))
        if len(out) == MAX_LOCATIONS:
            break
    return out


def solved(case: Case, cited: Sequence[tuple[str, int]]) -> bool:
    """One of the cited locations falls inside a changed function."""
    return any(
        path == gold_path and start <= line <= end
        for path, line in cited
        for gold_path, start, end in case.gold_functions
    )


TOOL_COMMANDS = {
    "floor": (),
    "graphify": ("graphify query", "graphify path", "graphify explain"),
    "inquiry": ("ai search",),
}


def used_tool(arm: str, uses: Sequence[dict[str, Any]]) -> tuple[int, list[str]]:
    """Successful calls of the arm's own command line, and any other Bash command that ran."""
    allowed = TOOL_COMMANDS[arm]
    ran = [u for u in uses if u.get("name") == "Bash" and u.get("error") is False]
    own = [
        u
        for u in ran
        if str(u.get("command") or "").strip().startswith(allowed or ("\0",))
    ]
    other = [str(u.get("command")) for u in ran if u not in own]
    return len(own), other


def agent_cost(model_usage: dict[str, Any]) -> float:
    """Dollars for every model the CLI used in the run, including its auxiliary calls."""
    total = 0.0
    for model, usage in model_usage.items():
        known = next(
            (m for m in PRICES if model.startswith(m) or m.startswith(model)), None
        )
        if known is None:
            raise ValueError(f"no published price recorded for {model}")
        total += dollars(
            known,
            usage.get("inputTokens", 0)
            + usage.get("cacheReadInputTokens", 0)
            + usage.get("cacheCreationInputTokens", 0),
            usage.get("outputTokens", 0),
        )
    return total


def prepare_c3(suite: Any, cases: Sequence[Case]) -> dict[str, dict[str, Any]]:
    """Materialize and index every corpus once, serially, before any agent runs.

    Snapshots and indexes are shared across arms and cases; building them in
    one thread avoids two runs extracting the same snapshot at once.
    """
    from evals.arms import Graphify, Inquiry

    graphify, inquiry = Graphify(default_build=True), Inquiry()
    prepared: dict[str, dict[str, Any]] = {}
    for corpus in sorted({c.corpus for c in cases}):
        root = suite.materialize(corpus)
        graph = Path(graphify.index(corpus, root, suite))
        store, _ = inquiry.index(corpus, root, suite)
        prepared[corpus] = {
            "root": root,
            "graph": graph,
            "graph_s": graphify.build_seconds(graph) or 0.0,
            "store": store,
            "store_s": inquiry.build_seconds((store, root)) or 0.0,
        }
    return prepared


def c3_arm(arm: str, prepared: dict[str, Any], scratch: Path) -> dict[str, Any]:
    """Working directory, extra tools, allowed tool patterns, environment and guidance."""
    import shutil
    import subprocess

    from evals.agent import FLOOR_TOOLS
    from evals.arms import Graphify, Inquiry

    root = prepared["root"]
    if arm == "floor":
        return {
            "cwd": root,
            "tools": (),
            "allowed": list(FLOOR_TOOLS),
            "env": {},
            "guidance": "",
        }
    commands = [f"Bash({command}:*)" for command in TOOL_COMMANDS[arm]]
    if arm == "graphify":
        graphify = Graphify(default_build=True)
        cwd = scratch / "tree"
        subprocess.run(["cp", "-al", f"{root}/.", str(cwd)], check=True)
        shutil.copytree(prepared["graph"] / "graphify-out", cwd / "graphify-out")
        # Graphify writes under $HOME; a wrapper gives it a scratch home while
        # the agent keeps the same environment as every other arm.
        bin_dir, home = scratch / "bin", scratch / "home"
        bin_dir.mkdir()
        home.mkdir()
        wrapper = bin_dir / "graphify"
        wrapper.write_text(
            f'#!/bin/sh\nHOME="{home}" exec "{graphify.venv / "bin" / "graphify"}" "$@"\n'
        )
        wrapper.chmod(0o755)
        guidance = (
            graphify.venv
            / "lib"
            / "python3.12"
            / "site-packages"
            / "graphify"
            / "always_on"
            / "claude-md.md"
        ).read_text()
        return {
            "cwd": cwd,
            "tools": ("Bash",),
            "allowed": [*FLOOR_TOOLS, *commands],
            "env": {"PATH": f"{bin_dir}:{os.environ['PATH']}"},
            "guidance": guidance,
        }
    inquiry = Inquiry()
    return {
        "cwd": root,
        "tools": ("Bash",),
        "allowed": [*FLOOR_TOOLS, *commands],
        "env": {
            "PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}",
            "INQUIRY_CONFIG": str(inquiry.config_path),
            "INQUIRY_STORAGE_ROOT": str(prepared["store"]),
            "INQUIRY_STORAGE_DEFAULT_PROJECT_ID": "eval",
            "INQUIRY_STORAGE_BACKEND": "lancedb",
            "INQUIRY_LOGGING_LEVEL": "ERROR",
            "TOKENIZERS_PARALLELISM": "false",
            "HF_HUB_OFFLINE": "1",
        },
        "guidance": INQUIRY_GUIDANCE,
    }


def run_c3(split: str, jobs: int, limit: int | None = None) -> Path:
    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    from evals.agent import MAX_TURNS, run_agent
    from evals.data import LOADERS

    if split == "test":
        suite = LOADERS["fresh"]()
        cases = [c for c in suite.cases if c.split == "test"]
    else:
        # Dev smoke runs use SWE-bench dev tasks; the mined tasks are all held out.
        suite = LOADERS["swebench"]()
        cases = sorted(
            (c for c in suite.cases if c.split == "dev"),
            key=lambda c: hashlib.sha256(f"{SEED}:{c.id}".encode()).hexdigest(),
        )[: limit or 3]
    run_id = begin(
        "c3",
        split,
        {arm: {"agent_model": AGENT_MODEL} for arm in C3_ARMS},
        {"items": len(cases), "jobs": jobs, "suite": suite.name},
    )
    started = datetime.now(timezone.utc)
    prepared = prepare_c3(suite, cases)

    def one(item: tuple[str, Case]) -> dict[str, Any]:
        arm, case = item
        corpus = prepared[case.corpus]
        with tempfile.TemporaryDirectory() as scratch:
            try:
                spec = c3_arm(arm, corpus, Path(scratch))
                record = run_agent(
                    # One turn is kept for the answer itself.
                    C3_PROMPT.format(query=case.query, budget=MAX_TURNS - 1),
                    spec["cwd"],
                    {"mcpServers": {}},
                    spec["allowed"],
                    [],
                    AGENT_MODEL,
                    guidance=spec["guidance"],
                    extra_tools=spec["tools"],
                    extra_env=spec["env"],
                )
                cited = cited_locations(
                    record["text"], [Path(spec["cwd"]), corpus["root"]]
                )
                cost = agent_cost(record["model_usage"])
            except Exception as exc:  # noqa: BLE001 - a failure scores as wrong
                return _fail(arm, case.id, str(exc))
        own_calls, other_commands = used_tool(arm, record["tool_uses"])
        row = {
            "arm": arm,
            "item": case.id,
            "correct": solved(case, cited) and not record["is_error"],
            "cited": cited,
            "turns": record["turns"],
            "tool_calls": record["tool_calls"],
            "own_tool_calls": own_calls,
            "other_bash_commands": other_commands,
            "permission_denials": len(record["permission_denials"]),
            "model_usage": record["model_usage"],
            "tokens": record["input_tokens"] + record["output_tokens"],
            "seconds": round(record["duration_ms"] / 1000, 3),
            "api_seconds": round(record["api_ms"] / 1000, 3),
            "dollars": round(cost, 6),
        }
        if record["is_error"]:
            row["error"] = record["stderr"] or "agent reported an error"
        return row

    work = [(arm, case) for case in cases for arm in C3_ARMS]
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        rows = list(executor.map(one, work))
    corpora = {c.corpus for c in cases}
    setup: dict[str, dict[str, Any]] = {
        "floor": {"seconds": 0.0},
        "graphify": {"seconds": round(sum(prepared[c]["graph_s"] for c in corpora), 1)},
        "inquiry": {"seconds": round(sum(prepared[c]["store_s"] for c in corpora), 1)},
    }
    for arm in C3_ARMS:
        arm_rows = [r for r in rows if r["arm"] == arm]
        setup[arm].update(
            {
                "dollars": 0.0,
                "llm_calls": 0,
                "tool_use_rate": round(
                    sum(1 for r in arm_rows if r.get("own_tool_calls"))
                    / max(1, len(arm_rows)),
                    4,
                ),
                "runs_with_other_bash": sum(
                    1 for r in arm_rows if r.get("other_bash_commands")
                ),
            }
        )
    return write_results(
        "c3",
        split,
        started,
        C3_ARMS,
        rows,
        setup,
        {
            "agent_model": AGENT_MODEL,
            "max_turns": MAX_TURNS,
            "prompt_sha256": hashlib.sha256(C3_PROMPT.encode()).hexdigest(),
            "inquiry_guidance_sha256": hashlib.sha256(
                INQUIRY_GUIDANCE.encode()
            ).hexdigest(),
            "items": [c.id for c in cases],
            "suite": suite.name,
            "data_sha256": suite.data_sha256,
        },
        run_id,
    )


# --------------------------------------------------------------------------
# Report over every claim test run in the ledger
# --------------------------------------------------------------------------


def ledger_runs() -> list[dict[str, Any]]:
    """Every claim test run: its entries, whether it finished, and whether its results verify."""
    from evals.run import LEDGER, REPO_ROOT

    if not LEDGER.exists():
        return []
    runs: dict[str, dict[str, Any]] = {}
    for line in LEDGER.read_text().splitlines():
        entry = json.loads(line) if line.strip() else {}
        if not str(entry.get("suite", "")).startswith("claim-"):
            continue
        run = runs.setdefault(
            entry["run"], {"run": entry["run"], "suite": entry["suite"]}
        )
        run[entry["event"]] = entry
    for run in runs.values():
        end = run.get("end")
        committed = _git("log", "--oneline", f"-S{run['run']}", "--", str(LEDGER))
        if not committed:
            run["status"] = "start entry was never committed"
            continue
        if not end:
            run["status"] = "aborted"
            continue
        path = REPO_ROOT / end["results"]
        if not path.exists():
            run["status"] = "missing results"
        elif hashlib.sha256(path.read_bytes()).hexdigest() != end["results_sha256"]:
            run["status"] = "results changed since the run"
        else:
            run["status"] = "verified"
            run["report"] = json.loads(path.read_text())
    return list(runs.values())


def claims_report() -> int:
    runs = ledger_runs()
    if not runs:
        print("no claim test runs in the ledger", file=sys.stderr)
        return 0
    problems = 0
    for run in runs:
        print(
            f"\n{run['suite']} run {run['run'][:8]}: {run['status']}", file=sys.stderr
        )
        if run["status"] == "verified":
            print_report(run["report"])
        else:
            problems += 1
    return 1 if problems else 0


CLAIMS: dict[str, Callable[..., Path]] = {
    "c1": run_c1,
    "c1b": run_c1b,
    "c2": run_c2,
    "c3": run_c3,
}
