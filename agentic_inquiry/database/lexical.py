"""BM25 lexical index over a LanceDB table's text column, built with Tantivy.

LanceDB 0.25's native full-text index ranks poorly: on BEIR SciFact it scores
nDCG@10 0.20 to 0.40 depending on tokenizer settings, against 0.59 for Tantivy
BM25 over the same ``fts_text`` values (see docs/adr/0007). This module keeps a
Tantivy index as a projection of the table: it is rebuilt from the table
whenever the table's version changes, so it can never drift from the rows it
ranks, and deleting it loses nothing.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

LEXICAL_DIR = "_lexical"
# Bump when the analyzer or schema changes so existing projections rebuild.
INDEX_FORMAT = 1
_TERM = re.compile(r"\w+")


@dataclass
class _Opened:
    version: int
    rows: int
    index: Any


def query_terms(text: str) -> List[str]:
    """Lower-cased word terms; lower case keeps AND/OR/NOT from acting as operators."""
    return [term.lower() for term in _TERM.findall(text)]


class LexicalIndex:
    """Tantivy BM25 projection of ``table.<column>`` keyed by row ``id``."""

    def __init__(self, db_path: str, table_name: str, column: str = "fts_text"):
        self._root = Path(db_path) / LEXICAL_DIR / table_name
        self._column = column
        self._opened: Optional[_Opened] = None

    def search(self, table: Any, query: str, limit: int) -> List[Tuple[str, float]]:
        """Return up to ``limit`` ``(row id, BM25 score)`` pairs, best first."""
        terms = query_terms(query)
        if not terms or limit <= 0:
            return []
        index = self._current(table)
        searcher = index.searcher()
        parsed = index.parse_query(" ".join(terms), ["text"])
        return [(searcher.doc(address)["id"][0], float(score)) for score, address in searcher.search(parsed, limit).hits]

    def _current(self, table: Any) -> Any:
        version, rows = int(table.version), int(table.count_rows())
        if self._opened and (self._opened.version, self._opened.rows) == (version, rows):
            return self._opened.index
        import tantivy
        from filelock import FileLock

        self._root.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self._root) + ".lock"):
            meta = self._root / "meta.json"
            expected = {"format": INDEX_FORMAT, "version": version, "rows": rows, "column": self._column}
            if not (meta.exists() and json.loads(meta.read_text()) == expected):
                self._rebuild(table, expected)
            index = tantivy.Index.open(str(self._root / "index"))
        self._opened = _Opened(version, rows, index)
        return index

    def _rebuild(self, table: Any, meta: dict) -> None:
        import tantivy

        staging = self._root.with_name(f"{self._root.name}.{uuid.uuid4().hex}.tmp")
        (staging / "index").mkdir(parents=True)
        builder = tantivy.SchemaBuilder()
        builder.add_text_field("id", stored=True, tokenizer_name="raw")
        builder.add_text_field("text", stored=False, tokenizer_name="en_stem")
        index = tantivy.Index(builder.build(), path=str(staging / "index"))
        writer = index.writer(heap_size=128_000_000)
        for batch in _batches(table, ["id", self._column]):
            for row_id, text in zip(batch.column("id").to_pylist(), batch.column(self._column).to_pylist()):
                writer.add_document(tantivy.Document(id=str(row_id), text=text or ""))
        writer.commit()
        writer.wait_merging_threads()
        (staging / "meta.json").write_text(json.dumps(meta))
        retired = self._root.with_name(f"{self._root.name}.{uuid.uuid4().hex}.old")
        if self._root.exists():
            self._root.rename(retired)
        staging.rename(self._root)
        shutil.rmtree(retired, ignore_errors=True)
        logger.info("Rebuilt lexical index for %s at version %s (%s rows)", self._root.name, meta["version"], meta["rows"])


def _batches(table: Any, columns: List[str]) -> Any:
    """Record batches of ``columns`` without loading vector columns."""
    try:
        dataset = table.to_lance()
    except Exception:  # noqa: BLE001 - remote tables have no Lance dataset
        yield table.to_arrow().select(columns)
        return
    yield from dataset.to_batches(columns=columns, batch_size=8192)
