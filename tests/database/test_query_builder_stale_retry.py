"""On-disk LanceDB tests for search recovery after a stale cached table.

When another process drops and re-creates a table (a concurrent re-index),
the manager's cached handle points at deleted data files and the next search
raises a stale-table error. Each search must invalidate the cache, re-open
the table, and return results from the re-created table.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List

import lancedb
import pytest

from agentic_inquiry.database.lancedb_manager import LanceDBManager

pytestmark = pytest.mark.integration

_TABLE = "docs"
_PROJECT = "demo"
_VECTOR = [0.5, 0.25]


def _create_table(path: Path, label: str) -> None:
    """Drop and re-create the table through a separate connection."""
    db = lancedb.connect(str(path))
    if _TABLE in db.table_names():
        db.drop_table(_TABLE)
    rows = [
        {
            "id": f"{label}-{i}",
            "project_id": _PROJECT,
            "content": f"hello {label} {i}",
            "vector": list(_VECTOR),
        }
        for i in range(3)
    ]
    table = db.create_table(_TABLE, rows)
    table.create_fts_index("content")


Search = Callable[[LanceDBManager], Awaitable[List[Dict[str, Any]]]]

_SEARCHES: Dict[str, Search] = {
    "fts": lambda m: m.fts_search(_TABLE, "hello", limit=3, project_id=_PROJECT),
    "vector": lambda m: m.vector_search(
        _TABLE, _VECTOR, "vector", limit=3, project_id=_PROJECT
    ),
    "hybrid": lambda m: m.hybrid_search(
        _TABLE, "hello", _VECTOR, "vector", limit=3, project_id=_PROJECT
    ),
    "filter": lambda m: m.advanced_filter(_TABLE, limit=3, project_id=_PROJECT),
}


@pytest.mark.parametrize("search", list(_SEARCHES.values()), ids=list(_SEARCHES))
async def test_search_recovers_after_table_recreated(
    tmp_path: Path, search: Search, caplog: pytest.LogCaptureFixture
) -> None:
    _create_table(tmp_path, "original")
    async with LanceDBManager(uri=str(tmp_path)) as manager:
        before = await search(manager)
        assert {row["id"] for row in before} <= {f"original-{i}" for i in range(3)}
        assert before

        _create_table(tmp_path, "rebuilt")
        caplog.clear()
        after = await search(manager)

    assert "Stale table detected" in caplog.text
    assert after
    assert all(row["id"].startswith("rebuilt-") for row in after)
