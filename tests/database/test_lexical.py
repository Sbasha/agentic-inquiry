"""Tantivy BM25 projection over a real LanceDB table."""

from __future__ import annotations

from pathlib import Path

import lancedb
import pytest

from agentic_inquiry.database.lexical import LexicalIndex, query_terms

pytestmark = pytest.mark.unit


def table(tmp_path: Path, rows: list[dict]) -> object:
    db = lancedb.connect(str(tmp_path / "db"))
    return db.create_table("chunks", data=rows)


def test_query_terms_are_lowercase_words() -> None:
    assert query_terms("Why does NOT parse_config() fail?") == [
        "why",
        "does",
        "not",
        "parse_config",
        "fail",
    ]


def test_ranks_by_bm25_and_rebuilds_when_table_changes(tmp_path: Path) -> None:
    rows = [
        {"id": "a", "fts_text": "session redirect strips authorization header"},
        {"id": "b", "fts_text": "cookie jar persistence"},
        {"id": "c", "fts_text": "redirect loop detection"},
    ]
    tbl = table(tmp_path, rows)
    lexical = LexicalIndex(str(tmp_path / "db"), "chunks")
    ranked = lexical.search(tbl, "authorization header on redirects", 10)
    assert [row_id for row_id, _ in ranked][:2] == ["a", "c"]

    tbl.add([{"id": "d", "fts_text": "authorization header authorization header"}])
    assert lexical.search(tbl, "authorization header", 1)[0][0] == "d"


def test_empty_query_returns_nothing(tmp_path: Path) -> None:
    tbl = table(tmp_path, [{"id": "a", "fts_text": "text"}])
    assert LexicalIndex(str(tmp_path / "db"), "chunks").search(tbl, "?!", 10) == []


def test_projection_survives_deletion_of_its_directory(tmp_path: Path) -> None:
    tbl = table(tmp_path, [{"id": "a", "fts_text": "alpha beta"}])
    LexicalIndex(str(tmp_path / "db"), "chunks").search(tbl, "alpha", 5)
    import shutil

    shutil.rmtree(tmp_path / "db" / "_lexical")
    assert (
        LexicalIndex(str(tmp_path / "db"), "chunks").search(tbl, "alpha", 5)[0][0]
        == "a"
    )
