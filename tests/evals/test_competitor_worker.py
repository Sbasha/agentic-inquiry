"""How the memory-tool adapters present LongMemEval sessions (RFC-0004 C1 methods)."""

from __future__ import annotations

from pathlib import Path

from evals.competitor_worker import cognee_turn_pairs, mem0_messages, sessions, turns

LATE = "[a#t0] (2023/06/01 (Thu) 10:00) user: later\n"
EARLY = (
    "[b#t0] (2023/05/24 (Wed) 06:42) user: I moved to Paris\n"
    "[b#t1] (2023/05/24 (Wed) 06:42) assistant: Congratulations\n"
    "[b#t2] (2023/05/24 (Wed) 06:42) user: thanks\n"
)


def _corpus(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text(LATE)
    (tmp_path / "b.txt").write_text(EARLY)
    return tmp_path


def test_sessions_come_in_date_order_and_turns_keep_role_and_date(
    tmp_path: Path,
) -> None:
    root = _corpus(tmp_path)
    assert [p.name for p in sessions(root)] == ["b.txt", "a.txt"]
    assert turns(root / "b.txt")[:2] == [
        {
            "role": "user",
            "content": "I moved to Paris",
            "date": "2023/05/24 (Wed) 06:42",
        },
        {
            "role": "assistant",
            "content": "Congratulations",
            "date": "2023/05/24 (Wed) 06:42",
        },
    ]


def test_mem0_adds_one_pair_at_a_time_with_the_date_written_in(tmp_path: Path) -> None:
    batches = list(mem0_messages(turns(_corpus(tmp_path) / "b.txt")))
    assert [len(b) for b in batches] == [2, 1]
    assert batches[0][0] == {
        "role": "user",
        "content": "[2023/05/24 (Wed) 06:42] I moved to Paris",
    }


def test_cognee_gets_beam_style_turn_pairs(tmp_path: Path) -> None:
    items = cognee_turn_pairs("b", turns(_corpus(tmp_path) / "b.txt"))
    assert items[0] == (
        "Session: b\nTurn: 1\nTime anchor: 2023/05/24 (Wed) 06:42\n\n"
        "User:\nI moved to Paris\n\nAssistant:\nCongratulations"
    )
    assert items[1].endswith("User:\nthanks\n\nAssistant:\n")


def test_build_health_refuses_failed_or_garbled_llm_calls() -> None:
    from evals.competitor_worker import health_problem

    assert health_problem({"calls": 200, "unparseable": 2}) is None
    assert "failed" in (health_problem({"calls": 200, "upstream_errors": 1}) or "")
    assert "another model" in (health_problem({"calls": 10, "model_mismatch": 1}) or "")
    assert "unparseable" in (health_problem({"calls": 200, "unparseable": 3}) or "")
