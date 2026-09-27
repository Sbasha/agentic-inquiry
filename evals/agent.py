"""Level C: a tool-using code agent per arm, scored on the code it cites.

Every run is ``claude -p`` in the task's read-only snapshot with the floor
tools (Read, Grep, Glob) and, for the ``graphify`` and ``inquiry`` arms, that
arm's MCP server and nothing else: no user settings, plugins, hooks or other
MCP servers (RFC-0003 Level C). The agent ends with ``LOCATIONS:`` and up to
five ``path:line`` lines; scoring is deterministic against the gold labels.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.arms import Graphify, Inquiry
from evals.data import CACHE, LOADERS, SEED, Case, Suite
from evals.metrics import paired
from evals.run import REPO_ROOT, RESULTS, _git, guard_test_split, record_test_run

MODEL = "claude-sonnet-5"
MAX_TURNS = 14
MAX_CITED_FILES = 5
PARALLEL = 3
FLOOR_TOOLS = ["Read", "Grep", "Glob"]
GRAPHIFY_TOOLS = [
    "query_graph",
    "get_node",
    "get_neighbors",
    "shortest_path",
    "god_nodes",
    "graph_stats",
    "get_community",
]
# Graphify's pull-request tools need a GitHub remote; hidden so both arms offer code tools only.
GRAPHIFY_HIDDEN = ["list_prs", "get_pr_impact", "triage_prs"]
INQUIRY_TOOLS = ["search"]

# Each tool arm gets its vendor's always-on guidance, adapted from CLI commands
# to the MCP tools the agent has (Graphify's is graphify/always_on/claude-md.md).
# The two texts are written in parallel so neither arm gets a stronger nudge.
ARM_GUIDANCE = {
    "floor": "",
    "graphify": (
        "This project has a Graphify knowledge graph available through the graphify tools. For codebase "
        "questions, first call query_graph with the question; use get_node, get_neighbors and shortest_path "
        "to follow relationships. These return a scoped subgraph, usually much smaller than raw grep output."
    ),
    "inquiry": (
        "This project is indexed by Agentic Inquiry, available through the inquiry search tool. For codebase "
        "questions, first call search with the question; read the returned path:line locations to follow up. "
        "It returns the best-matching code as scoped blocks, usually much smaller than raw grep output."
    ),
}

SWEBENCH_PROMPT = """You are investigating a GitHub issue in the repository in your current working directory.
Find the code that would need to change to resolve it. You cannot edit files or run commands.

Issue:
{query}

You have at most {budget} tool calls. Answer before you run out, even if you are unsure.
End your reply with a line `LOCATIONS:` followed by up to 5 lines, each `path:line`
(the repository-relative path and the line number of code to change), most likely first."""

QUESTION_PROMPT = """Answer this question about the code in the repository in your current working directory.
You cannot edit files or run commands.

{query}

You have at most {budget} tool calls. Answer before you run out, even if you are unsure.
End your reply with a line `LOCATIONS:` followed by up to 5 lines, each `path:line`
(the repository-relative path and line number of code your answer relies on), most important first."""

_CITATION = re.compile(r"([A-Za-z0-9_./\-]+\.[A-Za-z0-9]+):(\d+)")


def parse_citations(text: str, limit: int = MAX_CITED_FILES) -> list[tuple[str, int]]:
    """``(path, line)`` pairs after the last ``LOCATIONS:``, keeping the first ``limit`` distinct files."""
    tail = text.rsplit("LOCATIONS:", 1)[-1] if "LOCATIONS:" in text else text
    cited: list[tuple[str, int]] = []
    files: list[str] = []
    for path, line in _CITATION.findall(tail):
        path = path.lstrip("./")
        if path not in files:
            if len(files) >= limit:
                break
            files.append(path)
        cited.append((path, int(line)))
    return cited


def score(case: Case, cited: list[tuple[str, int]]) -> dict[str, float]:
    gold = set(case.gold_units)
    files = {path for path, _ in cited}
    metrics = {
        "file_recall": len(gold & files) / len(gold) if gold else 0.0,
        "file_precision": len(gold & files) / len(files) if files else 0.0,
    }
    if case.gold_functions:
        hit = sum(
            any(p == path and s <= line <= e for path, line in cited)
            for p, s, e in case.gold_functions
        )
        metrics["fn_hit"] = hit / len(case.gold_functions)
    return metrics


def select_tasks(suite: Suite, split: str, n: int) -> list[Case]:
    pool = [c for c in suite.cases if c.split == split]
    pool.sort(key=lambda c: hashlib.sha256(f"{SEED}:{c.id}".encode()).hexdigest())
    return pool[:n]


def mcp_config(
    arm: str, case: Case, suite: Suite, root: Path
) -> tuple[dict[str, Any], list[str], list[str]]:
    """MCP servers, the allowed tool names and the hidden tool names for one arm."""
    if arm == "floor":
        return {"mcpServers": {}}, list(FLOOR_TOOLS), []
    if arm == "graphify":
        graphify = Graphify()
        target = graphify.index(case.corpus, root, suite)
        server: dict[str, Any] = {
            "command": str(graphify.venv / "bin" / "graphify-mcp"),
            "args": ["--graph", str(Path(target) / "graph.json")],
        }
        return (
            {"mcpServers": {"graphify": server}},
            FLOOR_TOOLS + [f"mcp__graphify__{t}" for t in GRAPHIFY_TOOLS],
            [f"mcp__graphify__{t}" for t in GRAPHIFY_HIDDEN],
        )
    if arm == "inquiry":
        store, _ = Inquiry().index(case.corpus, root, suite)
        env = {
            "INQUIRY_CONFIG": str(Inquiry().config_path),
            "INQUIRY_STORAGE_ROOT": str(store),
            "INQUIRY_STORAGE_DEFAULT_PROJECT_ID": "eval",
            "INQUIRY_STORAGE_BACKEND": "lancedb",
            "INQUIRY_LOGGING_LEVEL": "ERROR",
            "TOKENIZERS_PARALLELISM": "false",
        }
        server = {
            "command": sys.executable,
            "args": [
                "-m",
                "agentic_inquiry.cli",
                "mcp",
                "--project-id",
                "eval",
                "--project-root",
                str(root),
                "--tools",
                ",".join(INQUIRY_TOOLS),
            ],
            "env": env,
            "cwd": str(REPO_ROOT),
        }
        return (
            {"mcpServers": {"inquiry": server}},
            FLOOR_TOOLS + [f"mcp__inquiry__{t}" for t in INQUIRY_TOOLS],
            [],
        )
    raise ValueError(f"unknown arm {arm}")


def run_agent(
    prompt: str,
    root: Path,
    config: dict[str, Any],
    allowed: list[str],
    hidden: list[str],
    model: str,
    guidance: str = "",
) -> dict[str, Any]:
    """One isolated ``claude -p`` run; returns the final text, usage and the tool manifest it saw."""
    with tempfile.TemporaryDirectory() as scratch:
        config_path = Path(scratch) / "mcp.json"
        config_path.write_text(json.dumps(config))
        command = [
            "claude",
            "-p",
            prompt,
            "--model",
            model,
            "--output-format",
            "stream-json",
            "--verbose",
            "--max-turns",
            str(MAX_TURNS),
            "--setting-sources",
            "project",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--mcp-config",
            str(config_path),
            "--tools",
            *FLOOR_TOOLS,
            "--allowedTools",
            *allowed,
        ]
        if hidden:
            command += ["--disallowedTools", *hidden]
        if guidance:
            command += ["--append-system-prompt", guidance]
        env = dict(os.environ, MCP_TIMEOUT="180000")
        for attempt in range(6):
            proc = subprocess.run(
                command, cwd=root, capture_output=True, text=True, timeout=1800, env=env
            )
            if not _transient(proc.stdout + proc.stderr):
                break
            time.sleep(min(600, 60 * 2**attempt))
    init: dict[str, Any] = {}
    result: dict[str, Any] = {}
    tool_calls: dict[str, int] = defaultdict(int)
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            init = event
        elif event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    tool_calls[block.get("name", "?")] += 1
        elif event.get("type") == "result":
            result = event
    usage = result.get("usage") or {}
    return {
        "text": str(result.get("result") or ""),
        "is_error": bool(result.get("is_error")) or proc.returncode != 0,
        "stderr": proc.stderr[-500:],
        "turns": result.get("num_turns"),
        "input_tokens": usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "tools": init.get("tools", []),
        "mcp_servers": init.get("mcp_servers", []),
        "tool_calls": dict(tool_calls),
    }


_TRANSIENT = re.compile(
    r"rate limit|rate_limit|overloaded|529|usage limit|too many requests", re.IGNORECASE
)


def _transient(output: str) -> bool:
    """A rate-limit or overload reply, worth retrying after a pause."""
    tail = output[-4000:]
    return bool(_TRANSIENT.search(tail)) and '"is_error":true' in tail.replace(" ", "")


def manifest_ok(arm: str, record: dict[str, Any]) -> bool:
    """The run saw the arm's tools and its server connected; no other MCP server."""
    tools = set(record.get("tools") or [])
    servers = {s.get("name"): s.get("status") for s in record.get("mcp_servers") or []}
    mcp_tools = {t for t in tools if t.startswith("mcp__")}
    if arm == "floor":
        return not mcp_tools and not servers
    return (
        servers == {arm: "connected"}
        and all(t.startswith(f"mcp__{arm}__") for t in mcp_tools)
        and bool(mcp_tools)
    )


def run_agents(
    arm_names: list[str],
    suite_names: list[str],
    split: str,
    n: int,
    repeats: int,
    model: str,
) -> Path:
    guard_test_split(split)
    started = datetime.now(timezone.utc)
    work: list[tuple[str, Suite, Case, int]] = []
    for suite_name in suite_names:
        suite = LOADERS[suite_name]()
        cases = (
            select_tasks(suite, split, n)
            if suite_name == "swebench"
            else [c for c in suite.cases if c.split == split]
        )
        for case in cases:
            for arm in arm_names:
                for repeat in range(repeats):
                    work.append((arm, suite, case, repeat))

    def one(item: tuple[str, Suite, Case, int]) -> dict[str, Any]:
        arm, suite, case, repeat = item
        template = SWEBENCH_PROMPT if suite.name == "swebench" else QUESTION_PROMPT
        prompt = template.format(query=case.query, budget=MAX_TURNS - 2)
        key = hashlib.sha256(
            json.dumps(
                [arm, case.id, repeat, model, prompt, MAX_TURNS, ARM_GUIDANCE[arm]]
            ).encode()
        ).hexdigest()
        cache = CACHE / "agent" / key[:2] / f"{key}.json"
        if cache.exists():
            record = json.loads(cache.read_text())
        else:
            try:
                root = suite.materialize(case.corpus)
                config, allowed, hidden = mcp_config(arm, case, suite, root)
                record = run_agent(
                    prompt, root, config, allowed, hidden, model, ARM_GUIDANCE[arm]
                )
            except Exception as exc:  # noqa: BLE001 - recorded per run
                record = {
                    "text": "",
                    "is_error": True,
                    "stderr": str(exc)[-500:],
                    "tools": [],
                    "mcp_servers": [],
                }
            if not record.get("is_error"):
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(record))
        cited = parse_citations(record.get("text", ""))
        valid = not record.get("is_error") and manifest_ok(arm, record)
        return {
            "arm": arm,
            "suite": suite.name,
            "case": case.id,
            "repeat": repeat,
            "valid": valid,
            "repo": case.meta.get("repo", suite.name),
            "cited": cited,
            "metrics": score(case, cited) if valid else {},
            **{
                k: record.get(k)
                for k in (
                    "turns",
                    "input_tokens",
                    "output_tokens",
                    "tool_calls",
                    "is_error",
                    "stderr",
                )
            },
        }

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        for number, row in enumerate(pool.map(one, work), 1):
            rows.append(row)
            if number % 10 == 0:
                print(f"  agent runs {number}/{len(work)}", file=sys.stderr)
    report = _agent_report(rows, arm_names, split, started, model, repeats)
    target = (
        RESULTS
        / "agent"
        / f"{split}-{started.strftime('%Y%m%dT%H%M%SZ')}-{_git('rev-parse', '--short=8', 'HEAD')}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    if split == "test":
        record_test_run("agent", arm_names, report, target)
    _print(report)
    print(f"results: {target.relative_to(REPO_ROOT)}", file=sys.stderr)
    return target


def _agent_report(
    rows: list[dict[str, Any]],
    arms: list[str],
    split: str,
    started: datetime,
    model: str,
    repeats: int,
) -> dict[str, Any]:
    per_task: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for arm in arms:
        by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if row["arm"] == arm and row["valid"]:
                by_case[row["case"]].append(row)
        for case_id, runs in by_case.items():
            names = sorted({m for r in runs for m in r["metrics"]})
            per_task[arm][case_id] = {
                "repo": runs[0]["repo"],
                **{
                    m: sum(r["metrics"].get(m, 0.0) for r in runs) / len(runs)
                    for m in names
                },
                "input_tokens": sorted(r["input_tokens"] or 0 for r in runs)[
                    len(runs) // 2
                ],
                "turns": sum(r["turns"] or 0 for r in runs) / len(runs),
            }
    summary = {}
    for arm in arms:
        tasks = list(per_task[arm].values())
        count = max(1, len(tasks))
        runs = [r for r in rows if r["arm"] == arm]
        summary[arm] = {
            "tasks": len(tasks),
            "runs": len(runs),
            "invalid_runs": sum(1 for r in runs if not r["valid"]),
            "file_recall": round(
                sum(t.get("file_recall", 0) for t in tasks) / count, 4
            ),
            "file_precision": round(
                sum(t.get("file_precision", 0) for t in tasks) / count, 4
            ),
            "fn_hit": round(
                sum(t.get("fn_hit", 0) for t in tasks if "fn_hit" in t)
                / max(1, sum(1 for t in tasks if "fn_hit" in t)),
                4,
            ),
            "median_input_tokens": sorted(t["input_tokens"] for t in tasks)[
                len(tasks) // 2
            ]
            if tasks
            else 0,
            "mean_turns": round(sum(t["turns"] for t in tasks) / count, 2),
        }
    comparisons = []
    if "inquiry" in per_task:
        for other in arms:
            if other == "inquiry":
                continue
            shared = sorted(set(per_task["inquiry"]) & set(per_task[other]))
            for metric in ("fn_hit", "file_recall", "file_precision"):
                keyed = [
                    c
                    for c in shared
                    if metric in per_task["inquiry"][c] and metric in per_task[other][c]
                ]
                if not keyed:
                    continue
                stats = paired(
                    [per_task["inquiry"][c][metric] for c in keyed],
                    [per_task[other][c][metric] for c in keyed],
                    seed=SEED,
                    clusters=[per_task["inquiry"][c]["repo"] for c in keyed],
                )
                comparisons.append(
                    {
                        "metric": metric,
                        "a": "inquiry",
                        "b": other,
                        "clustered": True,
                        **stats,
                    }
                )
            ratios = [
                per_task["inquiry"][c]["input_tokens"]
                / max(1, per_task[other][c]["input_tokens"])
                for c in shared
            ]
            if ratios:
                stats = paired(
                    ratios,
                    [1.0] * len(ratios),
                    seed=SEED,
                    clusters=[per_task["inquiry"][c]["repo"] for c in shared],
                )
                comparisons.append(
                    {
                        "metric": "input_token_ratio_minus_1",
                        "a": "inquiry",
                        "b": other,
                        "clustered": True,
                        **stats,
                    }
                )
    return {
        "schema": "InquiryEvalAgent/v1",
        "split": split,
        "provenance": {
            "sha": _git("rev-parse", "HEAD"),
            "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "started_utc": started.isoformat(timespec="seconds"),
            "model": model,
            "max_turns": MAX_TURNS,
            "repeats": repeats,
            "max_cited_files": MAX_CITED_FILES,
            "seed": SEED,
            "prompts_sha256": hashlib.sha256(
                (SWEBENCH_PROMPT + QUESTION_PROMPT).encode()
            ).hexdigest(),
            "guidance": ARM_GUIDANCE,
        },
        "summary": summary,
        "comparisons": comparisons,
        "per_task": per_task,
        "rows": rows,
    }


def _print(report: dict[str, Any]) -> None:
    print(f"\nagent / {report['split']}  model={report['provenance']['model']}")
    print(
        f"{'arm':10}  {'fn_hit':>7}  {'recall':>7}  {'prec':>6}  {'med in tok':>10}  {'turns':>5}  tasks  invalid"
    )
    for arm, s in report["summary"].items():
        print(
            f"{arm:10}  {s['fn_hit']:7.3f}  {s['file_recall']:7.3f}  {s['file_precision']:6.3f}  "
            f"{s['median_input_tokens']:10d}  {s['mean_turns']:5.1f}  {s['tasks']:5d}  {s['invalid_runs']}"
        )
    for c in report["comparisons"]:
        print(
            f"  {c['metric']}: {c['a']} - {c['b']}: {c['mean_diff']:+.4f} [{c['ci_low']:+.4f}, {c['ci_high']:+.4f}]"
        )
