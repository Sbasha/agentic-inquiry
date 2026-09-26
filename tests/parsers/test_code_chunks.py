"""Definition-aligned partition of parsed code (docs/specs/retrieval-core AC3, AC5)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from agentic_inquiry.parsers.code_chunks import partition_code_document, partition_lines, _definitions
from agentic_inquiry.parsers.implementations.unified_code import UnifiedCodeParser
from agentic_inquiry.parsers.models import ParserChunk

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parent / "samples" / "code"
FILES = [SAMPLES / "py" / "complex.py", SAMPLES / "java" / "ComplexExample.java", SAMPLES / "ts" / "complex.ts"]


def relationship_keys(chunks: list[ParserChunk]) -> Counter:
    return Counter((r.type, r.source_name, r.target_name) for c in chunks for r in c.relationships)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("budget", [120, 400, 100_000])
async def test_partition_covers_file_and_keeps_graph_data(path: Path, budget: int) -> None:
    legacy = await UnifiedCodeParser().parse(str(path))
    parted = partition_code_document(legacy, budget)
    lines = path.read_text().splitlines()

    covered: list[int] = []
    for chunk in parted.chunks:
        assert chunk.content == "\n".join(lines[chunk.line_start - 1 : chunk.line_end])
        if chunk.line_end > chunk.line_start:
            assert len(chunk.content) + 1 <= budget
        covered.extend(range(chunk.line_start, chunk.line_end + 1))
    assert covered == sorted(set(covered))
    assert {i + 1 for i, line in enumerate(lines) if line.strip()} <= set(covered)

    assert {s for c in legacy.chunks for s in c.symbols} == {s for c in parted.chunks for s in c.symbols}
    assert relationship_keys(legacy.chunks) == relationship_keys(parted.chunks)
    owners = {}
    for c in sorted(legacy.chunks, key=lambda c: c.element_type == "code_full"):
        for s in c.symbols:
            owners.setdefault(s, c.parent_id or "")
    placed = {s: c.symbol_metadata[s]["parent_scope"] for c in parted.chunks for s in c.symbols}
    assert placed == owners


def test_split_follows_definitions() -> None:
    source = ["def a():", "    return 1", "", "def b():", "    x = 1", "    return x", "", "def c():", "    pass"]
    chunk = ParserChunk(content="", symbol_metadata={
        "a": {"type": "function", "start_line": 1, "end_line": 2},
        "b": {"type": "function", "start_line": 4, "end_line": 6},
        "c": {"type": "function", "start_line": 8, "end_line": 9},
    })
    spans = partition_lines(source, _definitions([chunk], len(source)), max_chars=45)
    assert spans == [(1, 3), (4, 7), (8, 9)]
