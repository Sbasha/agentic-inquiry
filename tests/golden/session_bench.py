"""Replay labelled sessions and report evidence recall. No generative model.

python tests/golden/session_bench.py
python tests/golden/session_bench.py --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agentic_inquiry.integration.contract import render_text
from agentic_inquiry.integration.session_recall import items_from_turns, select_items
from tests.golden.sessions import load_sessions

GOLDEN = Path(__file__).resolve().parent
SESSIONS = GOLDEN / "sessions.json"
LIMIT = 10

# Arms this command does not run. A published number is not a cell.
NOT_MEASURED = {
    "bm25": "no LoCoMo, LongMemEval, or SciFact retrieval run",
    "dense": "no dense retrieval run",
    "hybrid": "this bench does not call the warm embedder",
    "graphify": "not run",
    "mem0": "not hosted in this run",
    "supermemory": "not hosted in this run",
    "openkb": "document setting only; not run",
    "grep_read": "not run on a repository",
    "code_stuffing": "not run on a repository",
    "reader": "not run",
    "judge": "not run",
    "key_fact_coverage": "not run; there is no reader",
}


def recall_at(retrieved: list[str], relevant: list[str], k: int) -> float:
    if not relevant:
        raise ValueError("evidence recall needs a gold location")
    return len(set(retrieved[:k]) & set(relevant)) / len(relevant)


def ndcg_at(retrieved: list[str], relevant: list[str], k: int) -> float:
    gold = set(relevant)

    def dcg(ids: list[str]) -> float:
        total = 0.0
        for index, identifier in enumerate(ids[:k]):
            if identifier in gold:
                total += 1.0 / math.log2(index + 2)
        return total

    ideal = dcg(list(relevant))
    if ideal == 0:
        return 0.0
    return dcg(retrieved) / ideal


def injected_bytes(items: list[Any]) -> int:
    entries = []
    for item in items:
        entries.append(
            {
                "id": item.id,
                "type": "memory",
                "owner": "afp",
                "client": "claude-code",
                "created": item.created or "0",
                "body": item.text,
            }
        )
    return len(render_text(entries).encode("utf-8"))


def run(path: Path = SESSIONS) -> dict[str, Any]:
    sessions = load_sessions(path)
    rows: list[dict[str, Any]] = []
    recalls: list[float] = []
    for session in sessions:
        question = next(
            turn for turn in session["turns"] if turn.get("role") == "question"
        )
        captures = [turn for turn in session["turns"] if turn.get("role") != "question"]
        for index, turn in enumerate(captures):
            turn.setdefault("created", f"{index:04d}")
        history = items_from_turns(captures)
        started = time.perf_counter()
        chosen = select_items(str(question["query"]), history, limit=LIMIT)
        elapsed = time.perf_counter() - started
        retrieved = [item.id for item in chosen]
        history_ids = [item.id for item in history]
        abstain = bool(question.get("abstain"))
        injected = injected_bytes(chosen)
        history_bytes = injected_bytes(history)
        row: dict[str, Any] = {
            "id": session["id"],
            "setting": session.get("setting"),
            "abstain": abstain,
            "retrieved": retrieved,
            "injected_bytes": injected,
            "history_bytes": history_bytes,
            "latency_seconds": elapsed,
        }
        if abstain:
            row["evidence_recall_at_10"] = None
            row["ndcg_at_10"] = None
            row["history_evidence_present"] = None
            row["byte_regression"] = injected > history_bytes
        else:
            relevant = list(question["relevant"])
            row["evidence_recall_at_10"] = recall_at(retrieved, relevant, LIMIT)
            row["ndcg_at_10"] = ndcg_at(retrieved, relevant, LIMIT)
            present = len(set(history_ids) & set(relevant)) / len(relevant)
            row["history_evidence_present"] = present
            row["byte_regression"] = (
                row["evidence_recall_at_10"] >= present and injected > history_bytes
            )
            recalls.append(row["evidence_recall_at_10"])
        omitted = [
            item for item in question.get("must_omit") or [] if item in retrieved
        ]
        row["omitted_violations"] = omitted
        rows.append(row)
    latencies = sorted(row["latency_seconds"] for row in rows)
    p95_index = max(0, math.ceil(0.95 * len(latencies)) - 1)
    measured = [row for row in rows if not row["abstain"]]
    return {
        "sessions": rows,
        "evidence_recall_at_10": sum(recalls) / len(recalls) if recalls else None,
        "abstentions": sum(1 for row in rows if row["abstain"]),
        "latency_p95_seconds": latencies[p95_index] if latencies else None,
        "arms": {
            "full_history": {
                "status": "measured",
                "scope": "tests/golden/sessions.json",
                "evidence_present": (
                    sum(row["history_evidence_present"] for row in measured)
                    / len(measured)
                    if measured
                    else None
                ),
            },
            "session_lexical": {
                "status": "measured",
                "scope": "tests/golden/sessions.json",
                "embedder": False,
                "evidence_recall_at_10": sum(recalls) / len(recalls)
                if recalls
                else None,
            },
            "not_measured": {
                name: {"status": "not_measured", "reason": reason}
                for name, reason in NOT_MEASURED.items()
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Labelled session retrieval bench")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for row in report["sessions"]:
            recall = row["evidence_recall_at_10"]
            shown = "abstain" if row["abstain"] else f"{recall:.3f}"
            print(
                f"{row['id']}: recall@10={shown} bytes={row['injected_bytes']} "
                f"history_bytes={row['history_bytes']} "
                f"retrieved={','.join(row['retrieved']) or '-'}"
            )
        print(f"mean evidence recall@10={report['evidence_recall_at_10']}")
    failed = [
        row["id"]
        for row in report["sessions"]
        if row["omitted_violations"]
        or row["byte_regression"]
        or (
            not row["abstain"]
            and (
                row["evidence_recall_at_10"] < 1.0
                or row["evidence_recall_at_10"] < row["history_evidence_present"]
            )
        )
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
