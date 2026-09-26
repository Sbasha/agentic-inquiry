"""Test for memory summary persistence fix in recall_memories tool."""

import pytest

pytestmark = pytest.mark.integration
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.mcp.tools.memory import recall_memories
from agentic_inquiry.mcp.services.session_manager import SessionManager
from agentic_inquiry.memory.models import (
    MemoryItem,
    MemoryContext,
    MemoryTier,
    RetrievalResult,
)
from agentic_inquiry.config import Config


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    mock_db_manager = MagicMock()
    mock_db_manager.advanced_filter = AsyncMock(return_value=[])
    mock_db_manager.insert = AsyncMock()
    mock_db_manager.upsert = AsyncMock()
    return mock_db_manager


@pytest.fixture
def mock_config():
    """Create a test configuration."""
    return Config.load()


@pytest.fixture
async def session_manager(mock_db_manager, mock_config):
    """Create a SessionManager instance for testing."""
    manager = MagicMock(spec=SessionManager)

    # Mock validate_session to return True
    manager.validate_session = AsyncMock(return_value=True)

    # Mock get_session to return a test session
    test_session = MagicMock()
    test_session.project_id = "test_project"
    manager.get_session = AsyncMock(return_value=test_session)

    return manager


@pytest.fixture
def mock_memory_system():
    """Create a mock MemorySystem with memories that have summaries."""
    memory_system = MagicMock()

    # Create mock memories with summaries as top-level fields
    mock_memories = []
    for i in range(3):
        memory = MemoryItem(
            id=f"mem_{i}",
            content=f"Full content for memory {i} with detailed information",
            summary=f"Summary {i}",  # Summary is a top-level field, NOT in metadata
            context=MemoryContext(
                agent_id="mcp_user",
                session_id="test_session_123",
                conversation_id="test_session_123",
                project_id="test_project",
            ),
            importance=0.7 + (i * 0.1),
            tier=MemoryTier.EPISODIC,
            creator_agent_id="mcp_user",
            modifier_agent_id="mcp_user",
            content_source="user_input",
            embedding=[0.1] * 768,
            summary_embedding=[0.1] * 384,
            metadata={"tags": ["test"], "session_id": "test_session_123"},
            created_at=datetime.now(timezone.utc),
            accessed_at=datetime.now(timezone.utc),
            access_count=0,
        )
        mock_memories.append(memory)

    # Mock retrieve to return these memories
    async def mock_retrieve(query, context, limit, strategy="adaptive"):
        return [
            RetrievalResult(
                item=memory,
                relevance_score=0.9 - (i * 0.1),
                retrieval_tier=MemoryTier.EPISODIC,
            )
            for i, memory in enumerate(mock_memories)
        ]

    memory_system.retrieve = AsyncMock(side_effect=mock_retrieve)

    return memory_system


@pytest.fixture
def mock_event_system():
    """Create a mock event system."""
    event_system = MagicMock()
    event_system.emit = AsyncMock()
    return event_system


@pytest.fixture
def mcp_services(
    session_manager, mock_db_manager, mock_memory_system, mock_event_system
):
    """Create mock services dictionary for tools."""
    return {
        "session_manager": session_manager,
        "mock_db_manager": mock_db_manager,
        "storage": mock_db_manager,  # Expose as storage for tools
        "memory_system": mock_memory_system,
        "event_system": mock_event_system,
    }


@pytest.mark.asyncio
async def test_recall_memories_returns_summaries_from_top_level_field(mcp_services):
    """Test that recall_memories correctly returns summaries from MemoryItem.summary field.

    This test verifies the fix for the bug where recall_memories was looking for
    summaries in metadata instead of using the top-level summary field.
    """
    # Call recall_memories
    result = await recall_memories(
        services=mcp_services,
        session_id="test_session_123",
        query="test query",
        limit=10,
    )

    # Verify response structure
    assert "memories" in result
    assert "total" in result
    assert "query" in result

    # Verify we got all 3 memories
    assert len(result["memories"]) == 3

    # Verify each memory has a summary from the top-level field
    for i, memory_result in enumerate(result["memories"]):
        # Verify summary is present
        assert "summary" in memory_result, f"Memory {i} missing summary field"

        # Verify summary is correct (from top-level field, not metadata)
        assert memory_result["summary"] == f"Summary {i}", (
            f"Memory {i} has incorrect summary: {memory_result['summary']}"
        )

        # Verify summary is not empty
        assert memory_result["summary"] != "", f"Memory {i} has empty summary"

        # Verify other fields are also present
        assert "memory_id" in memory_result
        assert "content" in memory_result
        assert "importance" in memory_result
        assert "tier" in memory_result
        assert "tags" in memory_result
        assert "created_at" in memory_result
        assert "access_count" in memory_result
        assert "relevance_score" in memory_result

    # Verify 100% of memories have non-empty summaries
    memories_with_summaries = sum(
        1 for m in result["memories"] if m.get("summary") and m["summary"] != ""
    )
    assert memories_with_summaries == len(result["memories"]), (
        f"Only {memories_with_summaries}/{len(result['memories'])} memories have summaries"
    )


@pytest.mark.asyncio
async def test_recall_memories_handles_missing_summary_gracefully(mcp_services):
    """Test that recall_memories handles memories with None summary gracefully."""
    # Create a memory with None summary
    memory_with_none_summary = MemoryItem(
        id="mem_none",
        content="Content without summary",
        summary=None,  # Explicitly None
        context=MemoryContext(
            agent_id="mcp_user",
            session_id="test_session_123",
            conversation_id="test_session_123",
            project_id="test_project",
        ),
        importance=0.7,
        tier=MemoryTier.EPISODIC,
        creator_agent_id="mcp_user",
        modifier_agent_id="mcp_user",
        content_source="user_input",
        embedding=[0.1] * 768,
        summary_embedding=[0.1] * 384,
        metadata={"tags": [], "session_id": "test_session_123"},
        created_at=datetime.now(timezone.utc),
        accessed_at=datetime.now(timezone.utc),
        access_count=0,
    )

    # Mock retrieve to return this memory
    async def mock_retrieve_with_none(query, context, limit, strategy="adaptive"):
        return [
            RetrievalResult(
                item=memory_with_none_summary,
                relevance_score=0.9,
                retrieval_tier=MemoryTier.EPISODIC,
            )
        ]

    mcp_services["memory_system"].retrieve = AsyncMock(
        side_effect=mock_retrieve_with_none
    )

    # Call recall_memories
    result = await recall_memories(
        services=mcp_services,
        session_id="test_session_123",
        query="test query",
        limit=10,
    )

    # Verify it returns empty string instead of None
    assert len(result["memories"]) == 1
    assert result["memories"][0]["summary"] == ""
    assert result["memories"][0]["summary"] is not None
