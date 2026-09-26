"""Tests for InMemoryMemoryAdapter field updates."""

import uuid

import numpy as np
import pytest

from agentic_inquiry.memory.adapters.inmemory_adapter import InMemoryMemoryAdapter
from agentic_inquiry.memory.models import MemoryContext, MemoryItem, MemoryTier


@pytest.fixture
async def stored_item() -> tuple[InMemoryMemoryAdapter, MemoryItem]:
    adapter = InMemoryMemoryAdapter()
    item = MemoryItem(
        id=str(uuid.uuid4()),
        content="User prefers Python",
        summary="Python preference",
        context=MemoryContext(
            agent_id="test_agent", session_id="s", conversation_id="c"
        ),
        importance=0.8,
        tier=MemoryTier.EPISODIC,
        creator_agent_id="test_agent",
        modifier_agent_id="test_agent",
    )
    await adapter.store(item, np.zeros(384, dtype=np.float32).tolist())
    return adapter, item


@pytest.mark.asyncio
async def test_update_sets_named_fields(
    stored_item: tuple[InMemoryMemoryAdapter, MemoryItem],
) -> None:
    adapter, item = stored_item

    assert await adapter.update(item.id, {"importance": 0.95}) is True
    assert await adapter.update("no-such-id", {"importance": 0.1}) is False

    stored = await adapter.get_by_id(item.id)
    assert stored is not None
    assert stored.importance == 0.95


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["context", "embedding", "metadata", "not_a_field"])
async def test_update_rejects_fields_the_lancedb_adapter_rejects(
    stored_item: tuple[InMemoryMemoryAdapter, MemoryItem],
    field: str,
) -> None:
    adapter, item = stored_item

    with pytest.raises(ValueError, match=field):
        await adapter.update(item.id, {field: None})
