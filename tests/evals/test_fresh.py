"""RFC-0004 C3 task mining rules."""

from __future__ import annotations

from typing import Any

import pytest

from evals.fresh import candidate, is_test_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/pkg/tests/test_io.py", True),
        ("lib/testing/helpers.py", True),
        ("pkg/test_core.py", True),
        ("pkg/core_test.py", True),
        ("conftest.py", True),
        ("src/_pytest/python.py", False),
        ("sklearn/utils/_testing_helpers.py", False),
    ],
)
def test_is_test_path(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected


def _pr(issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "number": 1,
        "mergedAt": "2026-03-01T00:00:00Z",
        "mergeCommit": {"oid": "abc"},
        "closingIssuesReferences": {"nodes": issues},
    }


def _issue(
    created: str = "2026-02-10T00:00:00Z", body: str = "x" * 200
) -> dict[str, Any]:
    return {
        "number": 7,
        "createdAt": created,
        "title": "Bug",
        "body": body,
        "repository": {"nameWithOwner": "o/r"},
    }


@pytest.mark.parametrize(
    "pr",
    [
        _pr([]),
        _pr([_issue(), _issue()]),
        _pr([_issue(created="2026-01-31T23:59:59Z")]),
        _pr([_issue(body="too short")]),
        _pr([_issue(body="x" * 20_001)]),
    ],
)
def test_candidate_rejects_before_touching_git(pr: dict[str, Any]) -> None:
    assert candidate("o/r", pr) is None


def test_names_changed_file_matches_name_module_or_path() -> None:
    from evals.fresh import names_changed_file

    task = {"problem_statement": "", "gold_lines": {"src/pkg/core.py": [1]}}
    for text, expected in [
        ("see core.py line 3", True),
        ("pkg.core raises", False),
        ("src.pkg.core raises", True),
        ("in src/pkg/core.py", True),
        ("the parser breaks", False),
    ]:
        assert names_changed_file(dict(task, problem_statement=text)) is expected
