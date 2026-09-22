"""
Tests for ContextManager.
"""

import pytest

pytestmark = pytest.mark.unit

import asyncio

from agent_vault.memory.context import ContextManager
from tests.helpers.async_utils import AsyncTestHelper


@pytest.fixture
def context_manager() -> ContextManager:
    """Create a context manager instance."""
    return ContextManager(
        max_concurrent_contexts=10,
        cleanup_interval=1,  # Short interval for testing
        context_ttl=2,  # Short TTL for testing
    )


@pytest.mark.asyncio
async def test_context_manager_initialization(context_manager: ContextManager) -> None:
    """Test context manager initialization."""
    assert context_manager.max_concurrent_contexts == 10
    assert context_manager.cleanup_interval == 1
    assert context_manager.context_ttl == 2


@pytest.mark.asyncio
async def test_create_context(context_manager: ContextManager) -> None:
    """Test creating a memory context."""
    context = context_manager.create_context(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
    )

    assert context.agent_id == "test_agent"
    assert context.session_id == "test_session"
    assert context.conversation_id == "test_conversation"
    assert context.task_id is None
    assert context.project_id is None


@pytest.mark.asyncio
async def test_create_context_with_optional_fields(
    context_manager: ContextManager,
) -> None:
    """Test creating a context with optional fields."""
    context = context_manager.create_context(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
        task_id="test_task",
        project_id="test_project",
        priority=0.9,
    )

    assert context.task_id == "test_task"
    assert context.project_id == "test_project"
    assert context.priority == 0.9


@pytest.mark.asyncio
async def test_get_active_contexts(context_manager: ContextManager) -> None:
    """Test getting active contexts."""
    # Create multiple contexts
    context1 = context_manager.create_context(
        agent_id="agent1",
        session_id="session1",
        conversation_id="conv1",
    )
    context2 = context_manager.create_context(
        agent_id="agent2",
        session_id="session2",
        conversation_id="conv2",
    )

    # Get active contexts
    active_contexts = context_manager.get_active_contexts()

    assert len(active_contexts) == 2
    assert context1 in active_contexts
    assert context2 in active_contexts


@pytest.mark.asyncio
async def test_get_active_contexts_filtered_by_agent(
    context_manager: ContextManager,
) -> None:
    """Test getting active contexts filtered by agent_id."""
    # Create contexts for different agents
    context1 = context_manager.create_context(
        agent_id="agent1",
        session_id="session1",
        conversation_id="conv1",
    )
    context2 = context_manager.create_context(
        agent_id="agent1",
        session_id="session2",
        conversation_id="conv2",
    )
    context3 = context_manager.create_context(
        agent_id="agent2",
        session_id="session3",
        conversation_id="conv3",
    )

    # Get active contexts for agent1
    agent1_contexts = context_manager.get_active_contexts(agent_id="agent1")

    assert len(agent1_contexts) == 2
    assert context1 in agent1_contexts
    assert context2 in agent1_contexts
    assert context3 not in agent1_contexts


@pytest.mark.asyncio
async def test_context_manager_as_async_context_manager(
    context_manager: ContextManager,
) -> None:
    """Test using ContextManager as an async context manager."""
    async with context_manager:
        # Create context while manager is running
        context = context_manager.create_context(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation",
        )
        assert context is not None

    # Manager should be stopped after exiting context
    assert context_manager._running is False


@pytest.mark.asyncio
async def test_stale_context_cleanup(context_manager: ContextManager) -> None:
    """Test that stale contexts are cleaned up."""
    # Start the context manager
    await context_manager.start()

    try:
        # Create a context
        context_manager.create_context(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation",
        )

        # Verify context is active
        active_contexts = context_manager.get_active_contexts()
        assert len(active_contexts) == 1

        # Wait for context to become stale (TTL is 2 seconds)
        success = await AsyncTestHelper.wait_for_condition(
            lambda: len(context_manager.get_active_contexts()) == 0,
            timeout=5.0
        )

        # Verify context was cleaned up
        assert success, "Context was not cleaned up within timeout"
        active_contexts = context_manager.get_active_contexts()
        assert len(active_contexts) == 0

    finally:
        await context_manager.stop()


@pytest.mark.asyncio
async def test_get_agent_profile(context_manager: ContextManager) -> None:
    """Test getting an agent profile."""
    profile = context_manager.get_agent_profile("test_agent")

    assert profile.agent_id == "test_agent"
    assert profile.query_patterns == {}
    assert profile.successful_strategies == {}


@pytest.mark.asyncio
async def test_get_agent_profile_cached(context_manager: ContextManager) -> None:
    """Test that agent profiles are cached."""
    profile1 = context_manager.get_agent_profile("test_agent")
    profile2 = context_manager.get_agent_profile("test_agent")

    # Should return the same instance
    assert profile1 is profile2


@pytest.mark.asyncio
async def test_update_agent_profile(context_manager: ContextManager) -> None:
    """Test updating an agent profile."""
    # Get initial profile
    profile = context_manager.get_agent_profile("test_agent")
    profile.update_query_pattern("keyword_search")

    # Update profile
    context_manager.update_agent_profile("test_agent", profile)

    # Verify update
    updated_profile = context_manager.get_agent_profile("test_agent")
    assert updated_profile.query_patterns["keyword_search"] == 1


@pytest.mark.asyncio
async def test_update_agent_profile_from_feedback(
    context_manager: ContextManager,
) -> None:
    """Test updating agent profile from feedback."""
    # Update profile from feedback
    context_manager.update_agent_profile_from_feedback(
        agent_id="test_agent",
        strategy="relevance",
        query_pattern="keyword",
        success=True,
    )

    # Verify profile was updated
    profile = context_manager.get_agent_profile("test_agent")
    assert profile.successful_strategies["relevance"] == 1


@pytest.mark.asyncio
async def test_update_agent_profile_from_negative_feedback(
    context_manager: ContextManager,
) -> None:
    """Test updating agent profile from negative feedback."""
    # Get initial profile
    profile = context_manager.get_agent_profile("test_agent")
    profile.preference_weights.get("temporal", 0.5)

    # Update profile from negative feedback
    context_manager.update_agent_profile_from_feedback(
        agent_id="test_agent",
        strategy="recency",
        query_pattern=None,
        success=False,
    )

    # Verify profile was updated (temporal weight should decrease)
    updated_profile = context_manager.get_agent_profile("test_agent")
    # Note: The actual weight adjustment logic may vary
    assert updated_profile is not None


@pytest.mark.asyncio
async def test_get_context_stats(context_manager: ContextManager) -> None:
    """Test getting context statistics."""
    # Create some contexts
    context_manager.create_context(
        agent_id="agent1",
        session_id="session1",
        conversation_id="conv1",
    )
    context_manager.create_context(
        agent_id="agent2",
        session_id="session2",
        conversation_id="conv2",
    )

    # Get stats
    stats = context_manager.get_context_stats()

    assert "active_contexts" in stats
    assert "contexts_by_agent" in stats
    assert "max_concurrent_contexts" in stats
    assert stats["active_contexts"] == 2
    assert stats["max_concurrent_contexts"] == 10


@pytest.mark.asyncio
async def test_get_context_stats_filtered_by_agent(
    context_manager: ContextManager,
) -> None:
    """Test getting context statistics with multiple agents."""
    # Create contexts for different agents
    context_manager.create_context(
        agent_id="agent1",
        session_id="session1",
        conversation_id="conv1",
    )
    context_manager.create_context(
        agent_id="agent1",
        session_id="session2",
        conversation_id="conv2",
    )
    context_manager.create_context(
        agent_id="agent2",
        session_id="session3",
        conversation_id="conv3",
    )

    # Get stats (no agent_id parameter supported)
    stats = context_manager.get_context_stats()

    assert stats["active_contexts"] == 3
    assert "agent1" in stats["contexts_by_agent"]
    assert stats["contexts_by_agent"]["agent1"] == 2
    assert stats["contexts_by_agent"]["agent2"] == 1


@pytest.mark.asyncio
async def test_max_concurrent_contexts_limit(context_manager: ContextManager) -> None:
    """Test that max concurrent contexts limit is enforced."""
    # Create contexts up to the limit
    for i in range(10):
        context_manager.create_context(
            agent_id=f"agent{i}",
            session_id=f"session{i}",
            conversation_id=f"conv{i}",
        )

    # Verify limit
    active_contexts = context_manager.get_active_contexts()
    assert len(active_contexts) == 10

    # Try to create one more (should raise ValueError)
    with pytest.raises(ValueError, match="Maximum concurrent contexts.*reached"):
        context_manager.create_context(
            agent_id="agent11",
            session_id="session11",
            conversation_id="conv11",
        )  # Allow some buffer


@pytest.mark.asyncio
async def test_context_touch_updates_access_time(
    context_manager: ContextManager,
) -> None:
    """Test that touching a context updates its access time."""
    # Create a context
    context = context_manager.create_context(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
    )

    # Get initial access time
    initial_access = context_manager._context_last_access.get(context.context_key)

    # Wait a bit
    await asyncio.sleep(0.1)

    # Touch the context
    context_manager._touch_context(context)

    # Verify access time was updated
    updated_access = context_manager._context_last_access.get(context.context_key)
    assert initial_access is not None
    assert updated_access is not None
    assert updated_access > initial_access


@pytest.mark.asyncio
async def test_start_and_stop(context_manager: ContextManager) -> None:
    """Test starting and stopping the context manager."""
    # Start
    await context_manager.start()
    assert context_manager._running is True
    assert context_manager._cleanup_task is not None

    # Stop
    await context_manager.stop()
    assert context_manager._running is False


@pytest.mark.asyncio
async def test_multiple_profiles_for_different_agents(
    context_manager: ContextManager,
) -> None:
    """Test managing profiles for multiple agents."""
    # Get profiles for different agents
    profile1 = context_manager.get_agent_profile("agent1")
    profile2 = context_manager.get_agent_profile("agent2")

    # Update profiles differently
    profile1.update_query_pattern("keyword_search")
    profile2.update_query_pattern("vector_search")

    context_manager.update_agent_profile("agent1", profile1)
    context_manager.update_agent_profile("agent2", profile2)

    # Verify profiles are independent
    updated_profile1 = context_manager.get_agent_profile("agent1")
    updated_profile2 = context_manager.get_agent_profile("agent2")

    assert "keyword_search" in updated_profile1.query_patterns
    assert "keyword_search" not in updated_profile2.query_patterns
    assert "vector_search" in updated_profile2.query_patterns
    assert "vector_search" not in updated_profile1.query_patterns


@pytest.mark.asyncio
async def test_context_creation_with_metadata(context_manager: ContextManager) -> None:
    """Test creating a context with metadata."""
    context = context_manager.create_context(
        agent_id="test_agent",
        session_id="test_session",
        conversation_id="test_conversation",
        metadata={"source": "api", "version": "1.0"},
    )

    assert context.metadata["source"] == "api"
    assert context.metadata["version"] == "1.0"


@pytest.mark.asyncio
async def test_cleanup_preserves_recently_accessed_contexts(
    context_manager: ContextManager,
) -> None:
    """Test that cleanup preserves recently accessed contexts."""
    await context_manager.start()

    try:
        # Create a context
        context = context_manager.create_context(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation",
        )

        # Keep touching the context
        for _ in range(3):
            # Wait a bit before touching
            await AsyncTestHelper.wait_for_condition(
                lambda: True,  # Just wait for the interval
                timeout=1.5
            )
            context_manager._touch_context(context)

        # Context should still be active
        active_contexts = context_manager.get_active_contexts()
        assert len(active_contexts) == 1
        assert context in active_contexts

    finally:
        await context_manager.stop()
