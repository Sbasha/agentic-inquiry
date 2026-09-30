"""Level B scoring helpers."""

from __future__ import annotations

import pytest

from evals.answer import cohen_kappa, parse_label, stratified, token_f1
from evals.data import Case


def test_token_f1_matches_locomo_normalization() -> None:
    pytest.importorskip("Stemmer", reason="needs the eval dependency group")
    assert token_f1("The 7 May 2023", "7 May 2023") == 1.0
    assert token_f1("painting", "She paints") == pytest.approx(2 * 0.5 * 1.0 / 1.5)
    assert token_f1("Not mentioned", "Sweden") == 0.0


def test_cohen_kappa() -> None:
    assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    # observed 0.5, expected 0.5 -> 0
    assert cohen_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == 0.0


def test_parse_label() -> None:
    assert parse_label('{"label": "CORRECT"}') == 1
    assert parse_label("wrong") == 0
    assert parse_label("unsure") is None


def test_stratified_is_proportional_and_seeded() -> None:
    cases = [
        Case(
            id=f"c{i}",
            suite="locomo",
            corpus="x",
            query="",
            gold_units={},
            meta={"category": i % 2 + 1},
        )
        for i in range(100)
    ]
    pick = stratified(cases, 20, "category")
    assert len(pick) == 20
    assert sum(c.meta["category"] == 1 for c in pick) == 10
    assert [c.id for c in pick] == [c.id for c in stratified(cases, 20, "category")]


def test_only_failed_calls_are_retried() -> None:
    import json
    import subprocess

    from evals.answer import _transient_failure

    def proc(
        code: int, payload: dict | None, stderr: str = ""
    ) -> subprocess.CompletedProcess[str]:
        out = json.dumps(payload) if payload is not None else ""
        return subprocess.CompletedProcess([], code, out, stderr)

    assert not _transient_failure(
        proc(0, {"is_error": False, "result": "HTTP 529 means overloaded"})
    )
    assert _transient_failure(
        proc(0, {"is_error": True, "result": "API Error: 529 overloaded"})
    )
    assert _transient_failure(proc(1, None, "rate limit reached"))
    assert not _transient_failure(proc(1, None, "invalid model"))
