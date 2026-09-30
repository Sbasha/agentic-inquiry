"""``ai search`` result lines (docs/specs/retrieval-core AC8)."""

from __future__ import annotations

from agentic_inquiry.cli.search import format_result


def test_result_shows_location_symbol_and_preview() -> None:
    row = {
        "file_path": "pkg/io.py",
        "line_start": 12,
        "line_end": 30,
        "score": 0.5,
        "element_name": "read_table",
        "element_type": "function",
        "content": "\ndef read_table(path):\n    return parse(path)\n",
    }
    assert format_result(row, 1).splitlines() == [
        "1. pkg/io.py:12-30  [0.500]",
        "   function: read_table",
        "   def read_table(path):",
    ]


def test_unknown_lines_show_the_path_alone() -> None:
    row = {
        "file_path": "README.md",
        "line_start": -1,
        "line_end": -1,
        "score": 0.25,
        "content": "Intro",
    }
    assert format_result(row, 2).splitlines()[0] == "2. README.md  [0.250]"
