"""On-disk LanceDB tests for duplicate merge-key collapse.

STUB: AC1 — keep last row for a duplicate (id, project_id); unique keys stay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.models.graph_relationship import GraphRelationship

pytestmark = pytest.mark.integration

_VECTOR = [0.0] * 128


def _rel(
    rel_id: str,
    project_id: str,
    payload: str,
    *,
    source_id: str = "src-a",
    target_id: str = "tgt-a",
) -> GraphRelationship:
    return GraphRelationship(
        id=rel_id,
        source_id=source_id,
        target_id=target_id,
        type="calls",
        project_id=project_id,
        vector=list(_VECTOR),
        metadata=json.dumps({"file_path": payload}),
    )


@pytest.fixture
async def manager(tmp_path: Path) -> LanceDBManager:
    config = Config(
        storage=StorageConfig(root=str(tmp_path / "storage"), backend="lancedb")
    )
    mgr = LanceDBManager(config=config, project_id="demo")
    await mgr.connect()
    try:
        yield mgr
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_upsert_collapses_duplicate_merge_keys_keep_last(
    manager: LanceDBManager,
) -> None:
    # STUB: AC1
    rows = [
        _rel("edge_aaaa1111", "demo", "first"),
        _rel("edge_aaaa1111", "demo", "second"),
    ]
    await manager.add_graph_relationships(rows, project_id="demo")

    stored = await manager.advanced_filter(
        "graph_relationships",
        filters={"id": "edge_aaaa1111"},
        project_id="demo",
    )
    assert len(stored) == 1
    metadata = stored[0]["metadata"]
    if not isinstance(metadata, str):
        metadata = json.dumps(metadata)
    assert json.loads(metadata)["file_path"] == "second"


@pytest.mark.asyncio
async def test_upsert_keeps_unique_keys_in_same_batch(
    manager: LanceDBManager,
) -> None:
    # STUB: AC1
    rows = [
        _rel("edge_aaaa1111", "demo", "first"),
        _rel("edge_aaaa1111", "demo", "second"),
        _rel("edge_bbbb2222", "demo", "unique", source_id="src-b", target_id="tgt-b"),
    ]
    await manager.add_graph_relationships(rows, project_id="demo")

    stored = await manager.advanced_filter(
        "graph_relationships",
        limit=10,
        project_id="demo",
    )
    ids = {row["id"] for row in stored}
    assert ids == {"edge_aaaa1111", "edge_bbbb2222"}
    by_id = {row["id"]: row for row in stored}
    metadata = by_id["edge_aaaa1111"]["metadata"]
    if not isinstance(metadata, str):
        metadata = json.dumps(metadata)
    assert json.loads(metadata)["file_path"] == "second"
