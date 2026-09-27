"""Line packing shared by text and code chunking (docs/specs/retrieval-core)."""

from __future__ import annotations

import pytest

from agentic_inquiry.parsers.implementations.utils.chunking import pack_lines

pytestmark = pytest.mark.unit


def covered(spans: list[tuple[int, int]]) -> list[int]:
    return [line for start, end in spans for line in range(start, end + 1)]


def test_partition_covers_every_line_once_in_order() -> None:
    lines = [f"line {i:03d}" for i in range(1, 101)]
    spans = pack_lines(lines, first_line=1, budget=100)
    assert covered(spans) == list(range(1, 101))


def test_respects_budget_in_characters() -> None:
    lines = ["x" * 30] * 10
    spans = pack_lines(lines, first_line=1, budget=100)
    for start, end in spans:
        assert sum(len(lines[i - 1]) + 1 for i in range(start, end + 1)) <= 100


def test_prefers_breaking_after_a_blank_line() -> None:
    lines = ["a" * 30, "a" * 30, "", "b" * 30, "b" * 30]
    assert pack_lines(lines, first_line=1, budget=100) == [(1, 3), (4, 5)]


def test_single_long_line_stands_alone() -> None:
    lines = ["short", "y" * 500, "short"]
    assert pack_lines(lines, first_line=10, budget=100) == [
        (10, 10),
        (11, 11),
        (12, 12),
    ]


def test_offsets_by_first_line() -> None:
    assert pack_lines(["a", "b"], first_line=41, budget=1000) == [(41, 42)]
    assert pack_lines([], first_line=1, budget=100) == []
