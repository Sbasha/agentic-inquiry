"""On-disk LanceDB tests for the native single-column FTS index on ``fts_text``.

AC 12: one FTS index on ``("fts_text",)``, created on new tables and on
existing tables that lack it; FTS and hybrid search match identifier
splits present only in ``fts_text``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

import lancedb
import pytest

from agent_vault.config import Config, StorageConfig
from agent_vault.database.lancedb_manager import LanceDBManager
from agent_vault.database.lancedb_schemas import get_document_chunks_schema
from agent_vault.models.document_chunk import BRANCH_INDEXING_FIELDS, DocumentChunk

pytestmark = pytest.mark.integration

_DIMS = 32
_VECTOR = [0.5] * _DIMS


def _chunk(chunk_id: str, content: str, fts_text: str) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        doc_id="doc-a",
        file_path="/src/a.py",
        project_id="demo",
        content=content,
        content_type="CODE",
        fts_text=fts_text,
        vector=list(_VECTOR),
    )


def _fts_indices(table: Any) -> List[tuple[str, ...]]:
    return [
        tuple(index.columns)
        for index in table.list_indices()
        if "fts" in str(index.index_type).lower()
    ]


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
async def manager(storage_root: Path) -> AsyncIterator[LanceDBManager]:
    config = Config(storage=StorageConfig(root=str(storage_root), backend="lancedb"))
    mgr = LanceDBManager(config=config, project_id="demo", embedding_dim=_DIMS)
    await mgr.connect()
    try:
        yield mgr
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_new_document_chunks_table_has_one_fts_index_on_fts_text(
    manager: LanceDBManager,
) -> None:
    await manager.add_document_chunks([_chunk("c1", "def parseDocument(): pass", "parseDocument parse document")])
    table = await manager.get_table("document_chunks")
    assert _fts_indices(table) == [("fts_text",)]


@pytest.mark.asyncio
async def test_opening_table_without_fts_index_creates_it(
    storage_root: Path,
) -> None:
    db_dir = storage_root / "lancedb"
    db_dir.mkdir(parents=True)
    db = lancedb.connect(str(db_dir))
    row: Dict[str, Any] = _chunk("c1", "x", "parseDocument parse document").to_dict()
    for field in BRANCH_INDEXING_FIELDS:
        row.pop(field, None)
    table = db.create_table(
        "document_chunks", data=[row], schema=get_document_chunks_schema(_DIMS)
    )
    table.create_index(
        metric="cosine", vector_column_name="vector", index_type="IVF_FLAT"
    )
    assert _fts_indices(table) == []

    config = Config(storage=StorageConfig(root=str(storage_root), backend="lancedb"))
    manager = LanceDBManager(config=config, project_id="demo", embedding_dim=_DIMS)
    await manager.connect()
    try:
        reopened = await manager.get_table("document_chunks")
        assert _fts_indices(reopened) == [("fts_text",)]
        hits = await manager.fts_search("document_chunks", "parse", limit=5)
        assert [hit["id"] for hit in hits] == ["c1"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_fts_and_hybrid_match_identifier_split_present_only_in_fts_text(
    manager: LanceDBManager,
) -> None:
    await manager.add_document_chunks(
        [
            _chunk("c1", "def parseDocument(): pass", "parseDocument parse document"),
            _chunk("c2", "def renderWidget(): pass", "renderWidget render widget"),
        ]
    )
    fts_hits = await manager.fts_search("document_chunks", "parse", limit=5)
    assert [hit["id"] for hit in fts_hits] == ["c1"]

    hybrid_hits = await manager.hybrid_search(
        "document_chunks",
        query="parse",
        query_vector=list(_VECTOR),
        vector_column_name="vector",
        limit=5,
    )
    assert hybrid_hits and hybrid_hits[0]["id"] == "c1"


@pytest.mark.asyncio
async def test_legacy_tantivy_index_dir_is_removed_and_native_index_built(
    storage_root: Path,
) -> None:
    db_dir = storage_root / "lancedb"
    db_dir.mkdir(parents=True)
    db = lancedb.connect(str(db_dir))
    row: Dict[str, Any] = _chunk("c1", "x", "parseDocument parse document").to_dict()
    for field in BRANCH_INDEXING_FIELDS:
        row.pop(field, None)
    db.create_table("document_chunks", data=[row], schema=get_document_chunks_schema(_DIMS))
    legacy = db_dir / "document_chunks.lance" / "_indices" / "fts"
    legacy.mkdir(parents=True)
    (legacy / "meta.json").write_text("{}")

    config = Config(storage=StorageConfig(root=str(storage_root), backend="lancedb"))
    manager = LanceDBManager(config=config, project_id="demo", embedding_dim=_DIMS)
    await manager.connect()
    try:
        table = await manager.get_table("document_chunks")
        assert not legacy.exists()
        assert _fts_indices(table) == [("fts_text",)]
        await manager.add_document_chunks(
            [_chunk("c2", "y", "renderWidget render widget")]
        )
        hits = await manager.fts_search("document_chunks", "render", limit=5)
        assert [hit["id"] for hit in hits] == ["c2"]
    finally:
        await manager.close()


def test_legacy_fts_removal_refuses_symlinked_index_dir(tmp_path: Path) -> None:
    from agent_vault.database.tables import remove_legacy_fts_index

    outside = tmp_path / "outside" / "fts"
    outside.mkdir(parents=True)
    (outside / "victim").write_text("x")
    db_dir = tmp_path / "lancedb"
    indices = db_dir / "document_chunks.lance" / "_indices"
    indices.mkdir(parents=True)
    (indices / "fts").symlink_to(outside, target_is_directory=True)

    remove_legacy_fts_index(str(db_dir), "document_chunks")

    assert (outside / "victim").exists()
    assert (indices / "fts").is_symlink()


def test_legacy_fts_removal_refuses_symlinked_parent(tmp_path: Path) -> None:
    from agent_vault.database.tables import remove_legacy_fts_index

    outside = tmp_path / "outside"
    (outside / "fts").mkdir(parents=True)
    (outside / "fts" / "victim").write_text("x")
    table_dir = tmp_path / "lancedb" / "document_chunks.lance"
    table_dir.mkdir(parents=True)
    (table_dir / "_indices").symlink_to(outside, target_is_directory=True)

    remove_legacy_fts_index(str(tmp_path / "lancedb"), "document_chunks")

    assert (outside / "fts" / "victim").exists()


def test_legacy_fts_removal_ignores_remote_uri(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from agent_vault.database.tables import remove_legacy_fts_index

    caplog.set_level(logging.DEBUG, logger="agent_vault.database.tables")
    remove_legacy_fts_index("s3://bucket/vault", "document_chunks")
    remove_legacy_fts_index(None, "document_chunks")
    skipped = [r for r in caplog.records if "no local database path" in r.getMessage()]
    assert len(skipped) == 2


def test_legacy_fts_removal_refuses_symlink_to_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from agent_vault.database.tables import remove_legacy_fts_index

    victim = tmp_path / "victim.txt"
    victim.write_text("x")
    indices = tmp_path / "lancedb" / "document_chunks.lance" / "_indices"
    indices.mkdir(parents=True)
    (indices / "fts").symlink_to(victim)

    remove_legacy_fts_index(str(tmp_path / "lancedb"), "document_chunks")

    assert victim.exists()
    assert any("symlink in path" in r.getMessage() for r in caplog.records)
