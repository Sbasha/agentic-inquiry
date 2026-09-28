"""RFC-0004 claims: cost accounting, comparisons, sampling and correctness rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals import claims
from evals.data import Case
from evals.metrics import Hit


def _case(
    cid: str, kind: str = "multi-session", functions: list[Any] | None = None
) -> Case:
    return Case(
        id=cid,
        suite="x",
        corpus="c",
        query="q",
        gold_units={},
        gold_functions=functions or [],
        meta={"type": kind},
    )


def test_usage_cost_subtracts_cli_overhead_per_call_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "claude-haiku-4-5-20251001"
    monkeypatch.setitem(
        claims._OVERHEAD, (model, False), {"input_tokens": 7_000, "api_ms": 1_000}
    )
    monkeypatch.setitem(
        claims._OVERHEAD, (model, True), {"input_tokens": 9_000, "api_ms": 2_000}
    )
    cost = claims.usage_cost(
        model,
        {
            "calls": 3,
            "schema_calls": 1,
            "input_tokens": 26_000,
            "output_tokens": 1_000,
            "api_ms": 10_000,
        },
    )
    # 2 plain calls and 1 schema call carry 23,000 tokens and 4 s of CLI overhead.
    assert cost == {
        "calls": 3,
        "input_tokens": 3_000,
        "output_tokens": 1_000,
        "api_s": 6.0,
        "dollars": 0.008,
    }
    floored = claims.call_cost({"input_tokens": 10}, model)
    assert floored["input_tokens"] == 0


def _row(arm: str, item: str, correct: bool, dollars: float = 1.0) -> dict[str, Any]:
    return {
        "arm": arm,
        "item": item,
        "correct": correct,
        "seconds": 1.0,
        "dollars": dollars,
        "tokens": 10,
    }


def test_compare_is_paired_holm_corrected_and_directional() -> None:
    rows = [_row("inquiry", str(i), True, 0.5) for i in range(12)]
    rows += [_row("full", str(i), False) for i in range(12)]
    rows += [_row("mem0", str(i), True) for i in range(12)]
    by_other = {c["b"]: c for c in claims.compare(rows, ["inquiry", "full", "mem0"])}
    assert by_other["full"]["a_only"] == 12 and by_other["full"]["significant"]
    assert by_other["full"]["p_holm"] == pytest.approx(
        min(1.0, 2 * by_other["full"]["p"])
    )
    assert not by_other["mem0"]["significant"]
    assert by_other["full"]["dollars_ratio"]["ratio"] == 0.5


def test_c1_sample_is_proportional_and_hash_ordered() -> None:
    cases = [_case(f"a{i}", "a") for i in range(60)] + [
        _case(f"b{i}", "b") for i in range(40)
    ]
    pick = claims.c1_sample(cases, 10)
    assert sum(c.meta["type"] == "a" for c in pick) == 6
    assert [c.id for c in pick] == [
        c.id for c in claims.c1_sample(list(reversed(cases)), 10)
    ]


def test_judge_uses_longmemeval_prompts_and_parses_yes_no() -> None:
    temporal = claims.judge_prompt("temporal-reasoning", "Q?", "18 days", "19 days")
    assert (
        "off-by-one" in temporal
        and "Q?" in temporal
        and "Correct Answer: 18 days" in temporal
    )
    assert "Rubric:" in claims.judge_prompt("single-session-preference", "Q", "R", "A")
    assert claims.parse_yes("Yes.") is True
    assert claims.parse_yes("The response is correct: yes") is True
    assert claims.parse_yes("no") is False


def test_found_function_and_solved_use_changed_function_spans() -> None:
    case = _case("t", functions=[("pkg/a.py", 10, 20)])
    inside = Hit("pkg/a.py", 15, 16, "== pkg/a.py:15-16 ==\nx\ny", 1)
    outside = Hit("pkg/a.py", 30, 31, "== pkg/a.py:30-31 ==\nx\ny", 1)
    assert claims.found_function(case, [inside])
    assert not claims.found_function(case, [outside])
    assert claims.solved(case, [("pkg/b.py", 12), ("pkg/a.py", 20)])
    assert not claims.solved(case, [("pkg/a.py", 21)])


def test_test_runs_log_start_before_work_and_bind_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evals.run as run

    monkeypatch.setattr(run, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(run, "_git", lambda *a: "")
    monkeypatch.setattr(claims, "_git", lambda *a: "")
    monkeypatch.setattr(
        "evals.arms.Inquiry.code_hash", claims.FROZEN_CODE_HASH, raising=False
    )
    run_id = claims.begin("c2", "test", {"inquiry": {"code_hash": "h"}}, {"items": 2})
    results = tmp_path / "r.json"
    results.write_text("{}")
    report = {"provenance": {"started_utc": "t", "sha": "s"}, "summary": {}}
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    run.record_test_run(run_id, "claim-c2", ["inquiry"], report, results)
    start, end = [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text().splitlines()
    ]
    assert (start["event"], end["event"], start["run"]) == ("start", "end", end["run"])
    assert (
        end["results_sha256"]
        == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    assert claims.begin("c2", "dev", {}, {}) == ""


def test_test_runs_refuse_a_dirty_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    import evals.run as run

    monkeypatch.setattr(run, "_git", lambda *a: "?? stray.json")
    with pytest.raises(SystemExit, match="dirty tree"):
        claims.begin("c1", "test", {}, {})


def test_ledger_runs_flags_aborted_and_changed_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    import evals.run as run

    results = tmp_path / "r.json"
    results.write_text('{"claim": "c2"}')
    digest = hashlib.sha256(results.read_bytes()).hexdigest()
    entries = [
        {"event": "start", "run": "a", "suite": "claim-c2"},
        {
            "event": "end",
            "run": "a",
            "suite": "claim-c2",
            "results": "r.json",
            "results_sha256": digest,
        },
        {"event": "start", "run": "b", "suite": "claim-c1"},
        {"event": "start", "run": "c", "suite": "claim-c3"},
        {
            "event": "end",
            "run": "c",
            "suite": "claim-c3",
            "results": "r.json",
            "results_sha256": "0" * 64,
        },
        {"utc": "legacy", "suite": "locomo"},
    ]
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(e) + "\n" for e in entries))
    monkeypatch.setattr(run, "LEDGER", ledger)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(claims, "_git", lambda *a: "abc1234 start")
    status = {r["run"]: r["status"] for r in claims.ledger_runs()}
    assert status == {
        "a": "verified",
        "b": "aborted",
        "c": "results changed since the run",
    }


def test_cited_locations_normalize_absolute_paths_and_keep_five(tmp_path: Path) -> None:
    root = tmp_path / "snap@abc123"
    text = (
        "notes\nLOCATIONS:\n"
        f"{root}/src/a.py:10\n"
        "`./src/b.py:20`\n"
        f"{root}/src/c.py:1\nsrc/d.py:2\nsrc/e.py:3\nsrc/f.py:4\n"
    )
    cited = claims.cited_locations(text, [root])
    assert cited == [
        ("src/a.py", 10),
        ("src/b.py", 20),
        ("src/c.py", 1),
        ("src/d.py", 2),
        ("src/e.py", 3),
    ]


def test_used_tool_counts_only_the_arms_own_successful_commands() -> None:
    uses = [
        {"name": "Bash", "command": 'ai search "redirects"', "error": False},
        {"name": "Bash", "command": "cat setup.py", "error": False},
        {"name": "Bash", "command": "ai search x", "error": True},
        {"name": "Grep", "command": None, "error": False},
    ]
    assert claims.used_tool("inquiry", uses) == (1, ["cat setup.py"])
    assert claims.used_tool("floor", uses) == (
        0,
        ['ai search "redirects"', "cat setup.py"],
    )


def test_agent_cost_prices_every_model_and_refuses_unknown_ones() -> None:
    usage = {
        "claude-sonnet-5": {"inputTokens": 1_000_000, "outputTokens": 0},
        "claude-haiku-4-5-20251001": {"inputTokens": 0, "outputTokens": 1_000_000},
    }
    assert claims.agent_cost(usage) == pytest.approx(2.0 + 5.0)
    with pytest.raises(ValueError, match="no published price"):
        claims.agent_cost({"claude-mystery": {"inputTokens": 1}})


def test_infra_failures_above_the_limit_invalidate_a_comparison() -> None:
    rows = [_row("inquiry", str(i), True) for i in range(20)]
    rows += [
        dict(claims._fail("mem0", str(i), "TimeoutExpired"), seconds=1.0)
        for i in range(2)
    ]
    rows += [_row("mem0", str(i), False) for i in range(2, 20)]
    (test,) = claims.compare(rows, ["inquiry", "mem0"])
    assert (
        test["infra_failure_share"]["mem0"] == 0.1
        and not test["valid"]
        and not test["significant"]
    )


def test_longmemeval_judge_templates_match_upstream() -> None:
    import hashlib

    digests = {
        k: hashlib.sha256(v.encode()).hexdigest()[:12]
        for k, v in claims.LME_JUDGE.items()
    }
    assert digests == PINNED_JUDGE_DIGESTS


# sha256 prefixes of LongMemEval's get_anscheck_prompt templates at 9e0b455; the
# harness templates produce byte-identical prompts (checked against upstream).
PINNED_JUDGE_DIGESTS = {
    "single-session-user": "fba020ba3d57",
    "single-session-assistant": "fba020ba3d57",
    "multi-session": "fba020ba3d57",
    "temporal-reasoning": "8d33a5fdd83a",
    "knowledge-update": "183a9b3a6197",
    "single-session-preference": "741ee3bcbea7",
}


def test_sequential_boundary_decides_either_direction() -> None:
    rows = [_row("inquiry", str(i), True) for i in range(14)] + [
        _row("mem0", str(i), False) for i in range(14)
    ]
    (won,) = claims.compare(
        rows, ["inquiry", "mem0"], boundary=(1, claims.C1_LOOKS[0][1])
    )
    assert won["decided"] and won["significant"] and won["look"] == 1
    rows = [_row("inquiry", str(i), False) for i in range(14)] + [
        _row("mem0", str(i), True) for i in range(14)
    ]
    (lost,) = claims.compare(
        rows, ["inquiry", "mem0"], boundary=(1, claims.C1_LOOKS[0][1])
    )
    assert lost["decided"] and not lost["significant"]
    rows = [_row("inquiry", str(i), True) for i in range(13)] + [
        _row("mem0", str(i), False) for i in range(13)
    ]
    (open_,) = claims.compare(
        rows, ["inquiry", "mem0"], boundary=(1, claims.C1_LOOKS[0][1])
    )
    assert not open_["decided"]
