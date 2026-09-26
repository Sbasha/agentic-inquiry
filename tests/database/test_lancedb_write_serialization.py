"""On-disk LanceDB tests for same-table write serialization.

AC 9: concurrent writes to one table never conflict and never duplicate a key.
AC 10: concurrent cold opens through one manager create each index once.
AC 11: a write is visible on return without any optimize/compaction step.
AC 13: upsert into a key that already has duplicate rows updates every copy.
AC 14: maintenance concurrent with writes neither fails nor loses rows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

import lancedb
import pytest

from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.database.lancedb_schemas import get_graph_relationships_schema
from agentic_inquiry.models.document_chunk import BRANCH_INDEXING_FIELDS, DocumentChunk
from agentic_inquiry.models.graph_entity import GraphEntity
from agentic_inquiry.models.graph_relationship import GraphRelationship

pytestmark = pytest.mark.integration

_DIMS = 32
_VECTOR = [0.25] * _DIMS
_KEYS_PER_BATCH = 300


def _relationships(tag: str) -> List[GraphRelationship]:
    return [
        GraphRelationship(
            id=f"edge_{tag}_{i}",
            source_id="src",
            target_id=f"tgt_{i}",
            type="calls",
            project_id="demo",
            vector=list(_VECTOR),
            metadata=json.dumps({"file_path": tag}),
        )
        for i in range(_KEYS_PER_BATCH)
    ]


def _entities(tag: str) -> List[GraphEntity]:
    return [
        GraphEntity(
            id=f"ent_{tag}_{i}",
            name=f"name_{tag}_{i}",
            type="function",
            file_path=f"/src/{tag}.py",
            doc_id=f"doc_{tag}",
            project_id="demo",
            vector=list(_VECTOR),
        )
        for i in range(_KEYS_PER_BATCH)
    ]


def _chunks(tag: str, count: int = _KEYS_PER_BATCH) -> List[DocumentChunk]:
    return [
        DocumentChunk(
            id=f"chunk_{tag}_{i}",
            doc_id=f"doc_{tag}",
            file_path=f"/src/{tag}.py",
            project_id="demo",
            content=f"content {tag} {i}",
            content_type="CODE",
            fts_text=f"token{tag}x{i} common",
            vector=list(_VECTOR),
        )
        for i in range(count)
    ]


def _lancedb_dir(storage_root: Path) -> Path:
    return storage_root / "lancedb"


async def _distinct_and_total(
    manager: LanceDBManager, table_name: str
) -> tuple[int, int]:
    table = await manager.get_table(table_name)
    frame = table.search().select(["id", "project_id"]).limit(10**9).to_pandas()
    return int(len(frame.drop_duplicates())), int(len(frame))


def _retry_warnings(caplog: pytest.LogCaptureFixture) -> List[str]:
    return [r.getMessage() for r in caplog.records if "retrying in" in r.getMessage()]


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


def _make_manager(storage_root: Path) -> LanceDBManager:
    config = Config(storage=StorageConfig(root=str(storage_root), backend="lancedb"))
    return LanceDBManager(config=config, project_id="demo", embedding_dim=_DIMS)


@pytest.fixture
async def manager(storage_root: Path) -> AsyncIterator[LanceDBManager]:
    mgr = _make_manager(storage_root)
    await mgr.connect()
    try:
        yield mgr
    finally:
        await mgr.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table_name", "build", "write"),
    [
        (
            "graph_relationships",
            _relationships,
            lambda mgr, rows: mgr.add_graph_relationships(rows, project_id="demo"),
        ),
        (
            "graph_entities",
            _entities,
            lambda mgr, rows: mgr.add_graph_entities(rows, project_id="demo"),
        ),
        ("document_chunks", _chunks, lambda mgr, rows: mgr.add_document_chunks(rows)),
    ],
)
async def test_concurrent_writes_never_conflict_or_duplicate_keys(
    manager: LanceDBManager,
    caplog: pytest.LogCaptureFixture,
    table_name: str,
    build: Any,
    write: Any,
) -> None:
    # STUB: AC 9
    await write(manager, build("seed"))
    caplog.set_level(logging.WARNING, logger="agentic_inquiry.database.lancedb_manager")

    batches = [build("shared") for _ in range(8)] + [
        build(f"unique{i}") for i in range(8)
    ]
    results = await asyncio.gather(
        *(write(manager, rows) for rows in batches), return_exceptions=True
    )

    assert [r for r in results if isinstance(r, BaseException)] == []
    assert _retry_warnings(caplog) == []
    distinct, total = await _distinct_and_total(manager, table_name)
    assert distinct == total == _KEYS_PER_BATCH * (1 + 1 + 8)


@pytest.mark.asyncio
async def test_concurrent_cold_opens_create_each_index_once(
    manager: LanceDBManager,
    storage_root: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # STUB: AC 10
    # Seed through raw lancedb so the table exists with rows and no indexes;
    # every concurrent write below is then a cold open that must create them.
    db_dir = _lancedb_dir(storage_root)
    db_dir.mkdir(parents=True, exist_ok=True)
    lancedb.connect(str(db_dir)).create_table(
        "document_chunks", data=[_strip(c.to_dict()) for c in _chunks("seed", 20)]
    )
    caplog.set_level(logging.INFO, logger="agentic_inquiry.database")

    writes = [manager.add_document_chunks(_chunks(f"w{i}", 20)) for i in range(16)]
    results = await asyncio.gather(*writes, return_exceptions=True)
    assert [r for r in results if isinstance(r, BaseException)] == []
    messages = [r.getMessage() for r in caplog.records]
    assert [m for m in messages if "Failed to create" in m] == []
    assert len([m for m in messages if m.startswith("Created vector index")]) == 1
    assert len([m for m in messages if m.startswith("Created FTS index")]) == 1

    table = lancedb.connect(str(db_dir)).open_table("document_chunks")
    kinds = sorted(str(index.index_type).lower() for index in table.list_indices())
    assert len(kinds) == 2
    assert table.count_rows() == 17 * 20


@pytest.mark.asyncio
async def test_loser_of_create_race_still_writes_its_rows(storage_root: Path) -> None:
    # STUB: AC 10 construction
    first = _make_manager(storage_root)
    second = _make_manager(storage_root)
    await first.connect()
    await second.connect()
    try:
        results = await asyncio.gather(
            first.add_document_chunks(_chunks("a", 20)),
            second.add_document_chunks(_chunks("b", 20)),
            return_exceptions=True,
        )
        assert [r for r in results if isinstance(r, BaseException)] == []
        table = lancedb.connect(str(_lancedb_dir(storage_root))).open_table(
            "document_chunks"
        )
        assert table.count_rows() == 40
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_lost_create_race_reports_not_created_and_rows_are_upserted(
    manager: LanceDBManager, storage_root: Path
) -> None:
    # STUB: AC 10 construction (deterministic race)
    db_dir = _lancedb_dir(storage_root)
    db_dir.mkdir(parents=True, exist_ok=True)
    seed = _chunks("seed", 2)
    lancedb.connect(str(db_dir)).create_table(
        "document_chunks", data=[_strip(c.to_dict()) for c in seed]
    )
    table_manager = manager._table_manager
    real_connection = await table_manager._conn_manager.get_connection()

    class RacingConnection:
        """Behaves as if another process created the table between our
        open_table miss and our create_table."""

        def __init__(self) -> None:
            self.opens = 0

        def open_table(self, name: str) -> Any:
            self.opens += 1
            if self.opens == 1:
                raise ValueError("Table 'document_chunks' was not found")
            return real_connection.open_table(name)

        def create_table(self, *args: Any, **kwargs: Any) -> Any:
            raise OSError("Dataset already exists")

    racing = RacingConnection()
    table_manager._conn_manager.get_connection = lambda: _coro(racing)  # type: ignore[method-assign]

    table, created = await table_manager.get_or_create_table(
        "document_chunks", [_strip(c.to_dict()) for c in _chunks("late", 2)]
    )
    assert created is False
    await manager.add_document_chunks(_chunks("late", 2))
    assert table.count_rows() == 4


def _strip(row: Dict[str, Any]) -> Dict[str, Any]:
    for field in BRANCH_INDEXING_FIELDS:
        row.pop(field, None)
    return row


async def _coro(value: Any) -> Any:
    return value


@pytest.mark.asyncio
async def test_create_table_from_schema_on_missing_table_returns(
    manager: LanceDBManager,
) -> None:
    # STUB: AC 10 construction (memory adapter initialize path)
    from agentic_inquiry.database.lancedb_schemas import get_graph_entities_schema

    await asyncio.wait_for(
        manager.create_table_from_schema(
            "graph_entities", get_graph_entities_schema(_DIMS)
        ),
        timeout=30,
    )
    assert (await manager.get_table("graph_entities")) is not None


@pytest.mark.asyncio
async def test_write_is_visible_on_return_without_optimize(
    manager: LanceDBManager,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # STUB: AC 11
    await manager.add_document_chunks(_chunks("seed", 3))
    table = await manager.get_table("document_chunks")
    forbidden: List[str] = []
    for name in ("optimize", "compact_files", "cleanup_old_versions"):
        monkeypatch.setattr(
            table, name, lambda *a, _n=name, **k: forbidden.append(_n), raising=False
        )

    await manager.add_document_chunks(_chunks("late", 1))

    assert forbidden == []
    fresh = lancedb.connect(str(_lancedb_dir(storage_root))).open_table(
        "document_chunks"
    )
    assert fresh.count_rows() == 4
    filtered = await manager.advanced_filter(
        "document_chunks", filters={"id": "chunk_late_0"}, limit=5
    )
    assert [row["id"] for row in filtered] == ["chunk_late_0"]
    hits = await manager.fts_search("document_chunks", "tokenlatex0", limit=5)
    assert [row["id"] for row in hits] == ["chunk_late_0"]


@pytest.mark.asyncio
async def test_upsert_into_duplicated_key_updates_every_copy(
    storage_root: Path,
) -> None:
    # STUB: AC 13
    db_dir = _lancedb_dir(storage_root)
    db_dir.mkdir(parents=True)
    db = lancedb.connect(str(db_dir))
    rows: List[Dict[str, Any]] = []
    for payload in ("old-a", "old-b"):
        row = _relationships("dup")[0].to_dict()
        row["metadata"] = json.dumps({"file_path": payload})
        for field in BRANCH_INDEXING_FIELDS:
            row.pop(field, None)
        rows.append(row)
    db.create_table(
        "graph_relationships", data=rows, schema=get_graph_relationships_schema(_DIMS)
    )

    manager = _make_manager(storage_root)
    await manager.connect()
    try:
        new_row = _relationships("dup")[0]
        new_row.metadata = json.dumps({"file_path": "new"})
        await manager.add_graph_relationships([new_row], project_id="demo")
        stored = await manager.advanced_filter(
            "graph_relationships", filters={"id": new_row.id}, limit=10
        )
        assert len(stored) == 2
        payloads = {
            json.loads(
                r["metadata"]
                if isinstance(r["metadata"], str)
                else json.dumps(r["metadata"])
            )["file_path"]
            for r in stored
        }
        assert payloads == {"new"}
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_maintenance_concurrent_with_writes_keeps_every_row(
    manager: LanceDBManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # STUB: AC 14
    await manager.add_graph_entities(_entities("seed"), project_id="demo")
    caplog.set_level(logging.WARNING, logger="agentic_inquiry.database.lancedb_manager")

    async def maintain() -> Dict[str, Any]:
        return await manager.run_maintenance(
            ["graph_entities"], cleanup_older_than=timedelta(0)
        )

    writes = [
        manager.add_graph_entities(_entities(f"w{i}"), project_id="demo")
        for i in range(16)
    ]
    results = await asyncio.gather(
        maintain(), *writes, maintain(), return_exceptions=True
    )

    assert [r for r in results if isinstance(r, BaseException)] == []
    assert results[0]["compact_success"] and results[-1]["compact_success"]
    assert _retry_warnings(caplog) == []
    distinct, total = await _distinct_and_total(manager, "graph_entities")
    assert distinct == total == _KEYS_PER_BATCH * 17


@pytest.mark.asyncio
async def test_write_waits_while_maintenance_holds_the_table(
    manager: LanceDBManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    # STUB: AC 14, deterministic interleaving: optimize is held open on a
    # barrier; a write issued meanwhile must not commit until it is released.
    await manager.add_graph_entities(_entities("seed"), project_id="demo")
    table = await manager.get_table("graph_entities")
    real_optimize = table.optimize
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def held_optimize(*args: Any, **kwargs: Any) -> Any:
        loop.call_soon_threadsafe(entered.set)
        release.wait(timeout=30)
        return real_optimize(*args, **kwargs)

    monkeypatch.setattr(table, "optimize", held_optimize)

    maintenance = asyncio.create_task(
        manager.run_maintenance(["graph_entities"], cleanup_older_than=timedelta(0))
    )
    await asyncio.wait_for(entered.wait(), timeout=30)
    write = asyncio.create_task(
        manager.add_graph_entities(_entities("late"), project_id="demo")
    )
    done, _ = await asyncio.wait({write}, timeout=0.5)
    assert not done, "write committed while maintenance held the table lock"

    release.set()
    await asyncio.wait_for(asyncio.gather(maintenance, write), timeout=60)
    distinct, total = await _distinct_and_total(manager, "graph_entities")
    assert distinct == total == _KEYS_PER_BATCH * 2


@pytest.mark.asyncio
async def test_run_maintenance_default_window_never_reports_negative_removals(
    manager: LanceDBManager,
) -> None:
    for i in range(6):
        await manager.add_graph_entities(_entities(f"w{i}"), project_id="demo")

    result = await manager.run_maintenance(["graph_entities"])

    assert result["compact_success"] and result["cleanup_success"]
    assert result["summary"]["versions_removed"] >= 0
    assert result["summary"]["fragments_reduced"] >= 0
    assert "fragments_before" in result["compaction"]["graph_entities"]
