"""Level B scoring helpers."""

from __future__ import annotations

import pytest

import hashlib

from evals.answer import cohen_kappa, lme_sample, parse_label, stratified, token_f1
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


def test_lme_sample_takes_lowest_question_hashes_per_type() -> None:
    cases = [
        Case(
            id=f"q{i}",
            suite="longmemeval",
            corpus=f"q{i}",
            query="",
            gold_units={},
            meta={"type": "a" if i % 3 else "b"},
        )
        for i in range(30)
    ]
    pick = lme_sample(cases, 4)
    assert len(pick) == 8
    for kind in ("a", "b"):
        ids = [c.id for c in cases if c.meta["type"] == kind]
        lowest = sorted(ids, key=lambda i: hashlib.sha256(i.encode()).hexdigest())[:4]
        assert [c.id for c in pick if c.meta["type"] == kind] == lowest
