"""Context-pack rendering shared by the CLI and MCP search surfaces."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentic_inquiry.search.context_pack import render_context_pack

pytestmark = pytest.mark.unit


def row(path: str, start: int, end: int, content: str, scope: str = "", name: str = "") -> dict:
    return {"file_path": path, "line_start": start, "line_end": end, "content": content,
            "metadata": {"scope": scope} if scope else {}, "element_name": name}


def test_renders_relative_locations_scope_and_code(tmp_path: Path) -> None:
    rows = [row(str(tmp_path / "src" / "a.py"), 10, 11, "def f():\n    return 1", scope="class A > method f")]
    text = render_context_pack(rows, max_chars=10_000, root=tmp_path)
    assert text.splitlines()[0] == "src/a.py:10-11  class A > method f"
    assert "    return 1" in text


def test_budget_cuts_on_line_boundaries_and_reports_omissions(tmp_path: Path) -> None:
    rows = [row(str(tmp_path / f"f{i}.py"), 1, 3, "a = 1\nb = 2\nc = 3") for i in range(20)]
    text = render_context_pack(rows, max_chars=60, root=tmp_path)
    assert len(text) <= 60 + len("\n[17 more results omitted; raise max_chars]")
    assert text.endswith("more results omitted; raise max_chars]")
    assert all(not line.startswith("a = 1b") for line in text.splitlines())


def test_unknown_lines_render_path_only(tmp_path: Path) -> None:
    text = render_context_pack([row(str(tmp_path / "doc.pdf"), -1, -1, "text")], max_chars=1000, root=tmp_path)
    assert text.splitlines()[0] == "doc.pdf"


def test_no_results() -> None:
    assert render_context_pack([], max_chars=100) == "No results."
