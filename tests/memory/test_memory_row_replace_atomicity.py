"""On-disk LanceDB tests for whole-row memory writes.

Replacing a stored memory item is one commit, so two writers of the same item
leave one row (docs/specs/lancedb-single-commit-upsert/spec.md).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Union

import numpy as np
import pytest

from agentic_inquiry.config import Config
from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter
from agentic_inquiry.memory.layers.episodic import EpisodicMemory
from agentic_inquiry.memory.layers.semantic import SemanticMemory
from agentic_inquiry.memory.models import MemoryContext, MemoryItem, MemoryTier
from tests.utils.commit_hook import commit_hook

pytestmark = pytest.mark.integration

Layer = Union[EpisodicMemory, SemanticMemory]

_TABLES = {"episodic": "memory_episodic_medium", "semantic": "memory_semantic_high"}


@pytest.fixture
async def db_manager(tmp_path: Path) -> AsyncIterator[LanceDBManager]:
    config = Config.load()
    config.storage.root = str(tmp_path / "storage")
    manager = LanceDBManager(config=config)
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture(params=["episodic", "semantic"])
async def layer(request: pytest.FixtureRequest, db_manager: LanceDBManager) -> Layer:
    adapter = LanceDBMemoryAdapter(db_manager, table_name=_TABLES[request.param])
    memory: Layer = (
        EpisodicMemory(storage=adapter, limit=100)
        if request.param == "episodic"
        else SemanticMemory(storage=adapter, limit=100)
    )
    await memory.initialize()
    return memory


def _item(
    content: str = "User asked about Python", importance: float = 0.5
) -> MemoryItem:
    return MemoryItem(
        id=str(uuid.uuid4()),
        content=content,
        summary="Python question",
        context=MemoryContext(
            agent_id="agent",
            session_id="session",
            conversation_id="conversation",
            task_id="task",
            project_id="project",
        ),
        importance=importance,
        tier=MemoryTier.EPISODIC,
        creator_agent_id="agent",
        modifier_agent_id="agent",
        content_source="user_input",
        embedding=np.random.rand(384).astype(np.float32),
        summary_embedding=np.random.rand(384).astype(np.float32),
    )


async def _rows(
    manager: LanceDBManager, layer: Layer, item_id: str
) -> List[Dict[str, Any]]:
    table = await manager.get_table(layer._storage.table_name)
    assert table is not None
    return [row for row in table.to_arrow().to_pylist() if row["id"] == item_id]


def _copy(item: MemoryItem, **changes: Any) -> MemoryItem:
    clone = MemoryItem.from_dict(item.to_dict())
    clone.embedding = item.embedding
    clone.summary_embedding = item.summary_embedding
    for field, value in changes.items():
        setattr(clone, field, value)
    return clone


@pytest.mark.asyncio
async def test_concurrent_update_leaves_one_row(
    db_manager: LanceDBManager, layer: Layer
) -> None:
    item = _item()
    await layer.store(item)
    fired = False

    async def second_writer(_table: str) -> None:
        nonlocal fired
        if fired:
            return
        fired = True
        await layer.update(_copy(item, importance=0.2))

    async with commit_hook(db_manager, on_exit=second_writer):
        await layer.update(_copy(item, importance=0.9))

    assert fired
    rows = await _rows(db_manager, layer, item.id)
    assert [row["importance"] for row in rows] == [pytest.approx(0.2)]


@pytest.mark.asyncio
async def test_update_is_one_commit(db_manager: LanceDBManager, layer: Layer) -> None:
    item = _item()
    await layer.store(item)
    table = await db_manager.get_table(layer._storage.table_name)
    assert table is not None
    before = table.version

    await layer.update(_copy(item, importance=0.9))

    assert table.version == before + 1


@pytest.mark.asyncio
async def test_failed_update_leaves_row_unchanged(
    db_manager: LanceDBManager, layer: Layer
) -> None:
    item = _item(content="original", importance=0.5)
    await layer.store(item)
    broken = _copy(item, content="changed", importance=0.9)
    broken.embedding = np.random.rand(7).astype(np.float32)

    with pytest.raises(RuntimeError):
        await layer.update(broken)

    rows = await _rows(db_manager, layer, item.id)
    assert [(row["content"], row["importance"]) for row in rows] == [
        ("original", pytest.approx(0.5))
    ]


@pytest.mark.asyncio
async def test_store_existing_id_replaces_row(
    db_manager: LanceDBManager, layer: Layer
) -> None:
    item = _item(content="first")
    adapter = layer._storage
    vector = item.embedding.tolist()

    await adapter.store(item, vector)
    await adapter.store(_copy(item, content="second"), vector)

    rows = await _rows(db_manager, layer, item.id)
    assert [row["content"] for row in rows] == ["second"]
