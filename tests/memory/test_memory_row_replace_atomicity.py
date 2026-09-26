"""On-disk LanceDB tests for whole-row memory writes.

Replacing a stored memory item is one commit, so two writers of the same item
leave one row, and negate/supersede write only their own columns
(docs/specs/lancedb-single-commit-upsert/spec.md).
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Union

import numpy as np
import pytest

from agentic_inquiry.config import Config
from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter
from agentic_inquiry.memory.layers.episodic import EpisodicMemory
from agentic_inquiry.memory.layers.semantic import SemanticMemory
from agentic_inquiry.memory.models import (
    MemoryContext,
    MemoryItem,
    MemoryStatus,
    MemoryTier,
)
from agentic_inquiry.memory.system import MemorySystem
from tests.utils.commit_hook import commit_hook

pytestmark = pytest.mark.integration

Layer = Union[EpisodicMemory, SemanticMemory]

_TABLES = {"episodic": "memory_episodic_medium", "semantic": "memory_semantic_high"}


@pytest.fixture
def config(tmp_path: Path) -> Config:
    config = Config.load()
    config.storage.root = str(tmp_path / "storage")
    return config


@pytest.fixture
async def db_manager(config: Config) -> AsyncIterator[LanceDBManager]:
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


class _StubEmbeddings:
    """Random vectors, so MemorySystem.store() runs without loading a model."""

    async def embed_async(self, text: str) -> np.ndarray:
        return np.random.rand(384).astype(np.float32)


@pytest.fixture
async def system(
    config: Config, db_manager: LanceDBManager
) -> AsyncIterator[MemorySystem]:
    memory = MemorySystem(
        config=config,
        embedding_service=_StubEmbeddings(),  # type: ignore[arg-type]
        vector_store=db_manager,
        episodic_storage=LanceDBMemoryAdapter(
            db_manager, table_name=_TABLES["episodic"]
        ),
        semantic_storage=LanceDBMemoryAdapter(
            db_manager, table_name=_TABLES["semantic"]
        ),
    )
    await memory.initialize()
    try:
        yield memory
    finally:
        await memory.shutdown()


def _tier_layer(system: MemorySystem, tier: str) -> Layer:
    return system.episodic_memory if tier == "episodic" else system.semantic_memory


class _AccessBumper:
    """Before each commit on the item's table, record an access from another task.

    ``writes`` counts the accesses that reached the row, so a writer that
    rewrites the row from a stale read leaves ``access_count`` below it.
    """

    def __init__(self, manager: LanceDBManager, layer: Layer, item_id: str) -> None:
        self._manager = manager
        self._layer = layer
        self._item_id = item_id
        self.writes = 0

    async def __call__(self, table_name: str) -> None:
        if table_name != self._layer._storage.table_name:
            return
        stored = await self._layer._storage.get_by_id(self._item_id)
        if stored is None:
            return
        self.writes += await self._manager.update_by_ids(
            table_name, [self._item_id], {"access_count": stored.access_count + 1}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["episodic", "semantic"])
async def test_negate_keeps_concurrent_access_count(
    system: MemorySystem, db_manager: LanceDBManager, tier: str
) -> None:
    layer = _tier_layer(system, tier)
    item = _item(importance=0.6)
    await layer.store(item)
    bumper = _AccessBumper(db_manager, layer, item.id)

    async with commit_hook(db_manager, on_enter=bumper):
        assert await system.negate_memory(item.id)

    stored = await layer.get_by_id(item.id, update_access=False)
    assert stored is not None
    # The bumper fires once per commit on the item's table: one write.
    assert bumper.writes == 1
    assert stored.access_count == bumper.writes
    assert stored.status == MemoryStatus.NEGATED
    assert stored.importance == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["episodic", "semantic"])
async def test_supersede_keeps_concurrent_access_count(
    system: MemorySystem, db_manager: LanceDBManager, tier: str
) -> None:
    layer = _tier_layer(system, tier)
    item = _item(importance=0.5)
    await layer.store(item)
    bumper = _AccessBumper(db_manager, layer, item.id)

    async with commit_hook(db_manager, on_enter=bumper):
        new_item = await system.supersede_memory(item.id, "Python 3.13 is current")

    assert new_item is not None
    stored = await layer.get_by_id(item.id, update_access=False)
    assert stored is not None
    # The bumper fires once per commit on the item's table: one write.
    assert bumper.writes == 1
    assert stored.access_count == bumper.writes
    assert stored.status == MemoryStatus.SUPERSEDED
    assert stored.superseded_by == new_item.id


@pytest.mark.asyncio
async def test_negate_working_item(system: MemorySystem) -> None:
    item = _item(importance=0.6)
    item.tier = MemoryTier.WORKING
    await system.working_memory.store(item)

    assert await system.negate_memory(item.id)

    stored = await system.working_memory.get_by_id(item.id)
    assert stored is not None
    assert stored.status == MemoryStatus.NEGATED
    assert stored.importance == 0.0


def _after_first_read(
    monkeypatch: pytest.MonkeyPatch,
    layer: Layer,
    action: Callable[[MemoryItem], Awaitable[None]],
) -> None:
    """Run ``action`` on the item right after the layer's first read returns it."""
    real_get_by_id = layer.get_by_id
    fired = False

    async def get_then_act(
        item_id: str, update_access: bool = True
    ) -> MemoryItem | None:
        nonlocal fired
        found = await real_get_by_id(item_id, update_access=update_access)
        if found is not None and not fired:
            fired = True
            await action(found)
        return found

    monkeypatch.setattr(layer, "get_by_id", get_then_act)


def _promote_to_semantic(
    system: MemorySystem,
) -> Callable[[MemoryItem], Awaitable[None]]:
    async def promote(item: MemoryItem) -> None:
        await system.semantic_memory.store(item)
        await system.episodic_memory.delete(item.id)

    return promote


def _warned_about(caplog: pytest.LogCaptureFixture, item_id: str) -> bool:
    return any(
        record.levelno == logging.WARNING and item_id in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_negate_follows_item_promoted_mid_call(
    system: MemorySystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _item(importance=0.6)
    await system.episodic_memory.store(item)
    _after_first_read(monkeypatch, system.episodic_memory, _promote_to_semantic(system))

    assert await system.negate_memory(item.id)

    stored = await system.semantic_memory.get_by_id(item.id, update_access=False)
    assert stored is not None
    assert stored.status == MemoryStatus.NEGATED
    assert stored.importance == 0.0


@pytest.mark.asyncio
async def test_negate_item_deleted_mid_call_returns_false(
    system: MemorySystem,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _item(importance=0.6)
    await system.episodic_memory.store(item)

    async def delete(found: MemoryItem) -> None:
        await system.episodic_memory.delete(found.id)

    _after_first_read(monkeypatch, system.episodic_memory, delete)

    with caplog.at_level(logging.WARNING, logger="agentic_inquiry.memory.system"):
        assert not await system.negate_memory(item.id)

    assert await system.episodic_memory.get_by_id(item.id, update_access=False) is None
    assert _warned_about(caplog, item.id)


@pytest.mark.asyncio
async def test_supersede_follows_item_promoted_mid_call(
    system: MemorySystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _item(importance=0.5)
    await system.episodic_memory.store(item)
    _after_first_read(monkeypatch, system.episodic_memory, _promote_to_semantic(system))

    new_item = await system.supersede_memory(item.id, "replacement")

    assert new_item is not None
    stored = await system.semantic_memory.get_by_id(item.id, update_access=False)
    assert stored is not None
    assert stored.status == MemoryStatus.SUPERSEDED
    assert stored.superseded_by == new_item.id


@pytest.mark.asyncio
async def test_supersede_returns_new_item_when_old_deleted(
    system: MemorySystem,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _item(importance=0.5)
    await system.episodic_memory.store(item)

    async def delete(found: MemoryItem) -> None:
        await system.episodic_memory.delete(found.id)

    _after_first_read(monkeypatch, system.episodic_memory, delete)

    with caplog.at_level(logging.WARNING, logger="agentic_inquiry.memory.system"):
        new_item = await system.supersede_memory(item.id, "replacement")

    assert new_item is not None
    assert new_item.content == "replacement"
    assert await system.episodic_memory.get_by_id(item.id, update_access=False) is None
    assert _warned_about(caplog, item.id)
