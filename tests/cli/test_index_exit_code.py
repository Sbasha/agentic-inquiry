"""Tests for ai index process exit codes."""

from __future__ import annotations

import pytest

from agentic_inquiry.cli.index import exit_code_for_index_result


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"status": "completed", "chunks_created": 10}, 0),
        ({"status": "completed", "chunks_created": 0}, 1),
        ({"status": "completed"}, 1),
        ({"status": "completed_with_errors", "chunks_created": 12}, 1),
        ({"status": "all_files_failed", "chunks_created": 0}, 1),
        ({"status": "failed", "chunks_created": 5}, 1),
        ({"status": "no_files_found", "chunks_created": 0}, 1),
        ({"status": "partial_failure", "chunks_created": 0}, 1),
    ],
)
def test_exit_code_for_index_result(result: dict, expected: int) -> None:
    assert exit_code_for_index_result(result) == expected
