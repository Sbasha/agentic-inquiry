"""Tests for event emissions from SessionManager, MemorySystem, and ContextBuilder.

This test module verifies that SessionManager, MemorySystem, and ContextBuilder
emit appropriate events for their key operations.

Requirements tested: 4.6, 4.7, 4.8
"""

import pytest

pytestmark = pytest.mark.unit
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from agent_vault.config import Config
from agent_vault.events.system import EventSystem
from agent_vault.events.models import EventStatus
from agent_vault.mcp.services.session_manager import SessionManager
from agent_vault.memory.system import MemorySystem
from agent_vault.memory.models import MemoryContext
from agent_vault.mcp.services.context_builder import ContextBuilder


@pytest_asyncio.fixture
async def mock_event_system():
    """Create a mock EventSystem for testing."""
    event_system = AsyncMock(spec=EventSystem)
    event_system.emit = AsyncMock()
    return event_system


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    db_manager = MagicMock()
    db_manager.advanced_filter = AsyncMock(return_value=[])
    db_manager.upsert = AsyncMock()
    db_manager.count_records = AsyncMock(return_value=0)
    return db_manager


@pytest.fixture
def test_config(tmp_path: Path):
    """Create a test configuration."""
    config = Config.load()
    config.storage.root = str(tmp_path)
    config.storage.default_project_id = "test_project"
    return config


@pytest.fixture
def mock_memory_system():
    """Create a mock memory system."""
    memory = MagicMock()
    memory.episodic = MagicMock()
    return memory


class TestSessionManagerEvents:
    """Test SessionManager emits session events."""

    @pytest.mark.asyncio
    async def test_create_session_emits_event(
        self, mock_db_manager, test_config, mock_event_system, mock_memory_system
    ):
        """Test that create_session emits session.created event."""
        # Arrange
        session_manager = SessionManager(
            db_manager=mock_db_manager,
            config=test_config,
            memory_system=mock_memory_system,
            event_system=mock_event_system
        )
        
        # Act
        result = await session_manager.create_session(
            project_id="test_project",
            description="Test session"
        )
        
        # Assert - check the first emit call (session.created), not the audit emit
        assert mock_event_system.emit.called
        call_args = mock_event_system.emit.call_args_list[0]
        assert call_args[0][0] == "session.created"
        assert call_args[1]["source"] == "SessionManager"
        assert call_args[1]["status"] == EventStatus.COMPLETED
        assert call_args[1]["session_id"] == result["session_id"]
        assert call_args[1]["project_id"] == "test_project"

    @pytest.mark.asyncio
    async def test_update_session_emits_event(
        self, mock_db_manager, test_config, mock_event_system, mock_memory_system
    ):
        """Test that update_session emits session.updated event."""
        # Arrange
        session_manager = SessionManager(
            db_manager=mock_db_manager,
            config=test_config,
            memory_system=mock_memory_system,
            event_system=mock_event_system
        )
        
        # Create a session first
        result = await session_manager.create_session(
            project_id="test_project",
            description="Test session"
        )
        session = session_manager.active_sessions[result["session_id"]]
        
        # Reset mock to clear create_session call
        mock_event_system.emit.reset_mock()
        
        # Act
        await session_manager.update_session(session)
        
        # Assert
        assert mock_event_system.emit.called
        call_args = mock_event_system.emit.call_args
        assert call_args[0][0] == "session.updated"
        assert call_args[1]["source"] == "SessionManager"
        assert call_args[1]["status"] == EventStatus.COMPLETED
        assert call_args[1]["session_id"] == session.session_id

    @pytest.mark.asyncio
    async def test_list_sessions_emits_event(
        self, mock_db_manager, test_config, mock_event_system, mock_memory_system
    ):
        """Test that list_sessions emits session.queried event."""
        # Arrange
        session_manager = SessionManager(
            db_manager=mock_db_manager,
            config=test_config,
            memory_system=mock_memory_system,
            event_system=mock_event_system
        )
        
        # Act
        await session_manager.list_sessions(project_id="test_project", limit=10)
        
        # Assert
        assert mock_event_system.emit.called
        call_args = mock_event_system.emit.call_args
        assert call_args[0][0] == "session.queried"
        assert call_args[1]["source"] == "SessionManager"
        assert call_args[1]["status"] == EventStatus.COMPLETED
        assert call_args[1]["project_id"] == "test_project"
        assert call_args[1]["limit"] == 10


class TestMemorySystemEvents:
    """Test MemorySystem emits memory events."""

    @pytest.mark.asyncio
    async def test_store_emits_event(
        self, test_config, mock_event_system
    ):
        """Test that store emits memory.stored event."""
        # Arrange
        import numpy as np
        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_async = AsyncMock(return_value=np.array([0.1] * 384))
        
        memory_system = MemorySystem(
            config=test_config,
            embedding_service=mock_embedding_service,
            event_system=mock_event_system
        )
        
        # Initialize the memory system
        await memory_system.initialize()
        
        context = MemoryContext(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation"
        )
        
        # Act
        await memory_system.store(
            content="Test memory content",
            context=context,
            importance=0.8
        )
        
        # Assert
        assert mock_event_system.emit.called
        call_args = mock_event_system.emit.call_args
        assert call_args[0][0] == "memory.stored"
        assert call_args[1]["source"] == "MemorySystem"
        assert call_args[1]["status"] == EventStatus.COMPLETED
        assert call_args[1]["agent_id"] == "test_agent"
        assert call_args[1]["session_id"] == "test_session"

    @pytest.mark.asyncio
    async def test_retrieve_emits_event(
        self, test_config, mock_event_system
    ):
        """Test that retrieve emits memory.retrieved event."""
        # Arrange
        import numpy as np
        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_async = AsyncMock(return_value=np.array([0.1] * 384))
        
        memory_system = MemorySystem(
            config=test_config,
            embedding_service=mock_embedding_service,
            event_system=mock_event_system
        )
        
        # Initialize the memory system
        await memory_system.initialize()
        
        context = MemoryContext(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation"
        )
        
        # Act
        await memory_system.retrieve(
            query="test query",
            context=context,
            limit=5
        )
        
        # Assert
        assert mock_event_system.emit.called
        call_args = mock_event_system.emit.call_args
        assert call_args[0][0] == "memory.retrieved"
        assert call_args[1]["source"] == "MemorySystem"
        assert call_args[1]["status"] == EventStatus.COMPLETED
        assert call_args[1]["agent_id"] == "test_agent"
        assert call_args[1]["session_id"] == "test_session"

    @pytest.mark.asyncio
    async def test_consolidate_emits_event(
        self, test_config, mock_event_system
    ):
        """Test that consolidate emits memory.consolidated event."""
        # Arrange
        import numpy as np
        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_async = AsyncMock(return_value=np.array([0.1] * 384))
        
        memory_system = MemorySystem(
            config=test_config,
            embedding_service=mock_embedding_service,
            event_system=mock_event_system
        )
        
        # Initialize the memory system
        await memory_system.initialize()
        
        context = MemoryContext(
            agent_id="test_agent",
            session_id="test_session",
            conversation_id="test_conversation"
        )
        
        # Act
        await memory_system.consolidate(context=context)
        
        # Assert
        assert mock_event_system.emit.called
        call_args = mock_event_system.emit.call_args
        assert call_args[0][0] == "memory.consolidated"
        assert call_args[1]["source"] == "MemorySystem"
        assert call_args[1]["status"] == EventStatus.COMPLETED
        assert call_args[1]["agent_id"] == "test_agent"
        assert call_args[1]["session_id"] == "test_session"


class TestContextBuilderEvents:
    """Test ContextBuilder emits context events."""

    @pytest.mark.asyncio
    async def test_build_context_emits_events(
        self, test_config, mock_event_system, mock_db_manager
    ):
        """Test that build_context emits context.building_started and context.building_completed events."""
        # Arrange
        import numpy as np
        mock_search_service = MagicMock()
        mock_search_service.search = AsyncMock(return_value=[])
        mock_search_service.embedding_service = MagicMock()
        mock_search_service.embedding_service.embed_async = AsyncMock(
            return_value=np.array([0.1] * 384)
        )
        
        mock_memory_system = MagicMock()
        mock_memory_system._initialized = True
        mock_memory_system.retrieve = AsyncMock(return_value=[])
        
        mock_session_manager = MagicMock()
        mock_session = MagicMock()
        mock_session.project_id = "test_project"
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)
        
        context_builder = ContextBuilder(
            search_service=mock_search_service,
            memory_system=mock_memory_system,
            db_manager=mock_db_manager,
            session_manager=mock_session_manager,
            config=test_config,
            event_system=mock_event_system
        )
        
        # Act
        await context_builder.build_context(
            query="test query",
            session_id="test_session",
            focus="all",
            depth="broad",
            max_tokens=4000
        )
        
        # Assert - should have been called twice (started and completed)
        assert mock_event_system.emit.call_count == 2
        
        # Check first call (started)
        first_call = mock_event_system.emit.call_args_list[0]
        assert first_call[0][0] == "context.building_started"
        assert first_call[1]["source"] == "ContextBuilder"
        assert first_call[1]["status"] == EventStatus.PROGRESS
        assert first_call[1]["session_id"] == "test_session"
        
        # Check second call (completed)
        second_call = mock_event_system.emit.call_args_list[1]
        assert second_call[0][0] == "context.building_completed"
        assert second_call[1]["source"] == "ContextBuilder"
        assert second_call[1]["status"] == EventStatus.COMPLETED
        assert second_call[1]["session_id"] == "test_session"
        assert "estimated_tokens" in second_call[1]
        assert "items_included" in second_call[1]
