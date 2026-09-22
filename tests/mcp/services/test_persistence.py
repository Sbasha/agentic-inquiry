"""Tests for session persistence backends.

Tests cover:
- InMemorySessionStorage: Full coverage for testing backend
- LanceDBSessionStorage: Mock-based tests for production backend
- SessionStorageProtocol: Protocol compliance verification
"""

import pytest

pytestmark = pytest.mark.unit
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.mcp.models.session import Session
from agentic_inquiry.mcp.services.persistence import (
    SessionStorageProtocol,
    InMemorySessionStorage,
    LanceDBSessionStorage,
)
from agentic_inquiry.mcp.services.persistence.protocol import StorageError


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_session() -> Session:
    """Create a sample session for testing."""
    return Session(
        session_id="test-session-001",
        project_id="test-project",
        description="Test session",
    )


@pytest.fixture
def expired_session() -> Session:
    """Create an expired session for testing."""
    session = Session(
        session_id="expired-session-001",
        project_id="test-project",
        description="Expired test session",
    )
    # Set last_active to 48 hours ago
    session.last_active = datetime.now() - timedelta(hours=48)
    return session


@pytest.fixture
def memory_storage() -> InMemorySessionStorage:
    """Create an in-memory storage instance."""
    return InMemorySessionStorage()


@pytest.fixture
def mock_db_manager() -> MagicMock:
    """Create a mock LanceDB manager."""
    manager = MagicMock()
    manager.upsert = AsyncMock()
    manager.advanced_filter = AsyncMock(return_value=[])
    return manager


@pytest.fixture
def mock_storage_facade(mock_db_manager: MagicMock) -> MagicMock:
    """Create a mock StorageFacade wrapping the mock db_manager."""
    facade = MagicMock()
    facade.get_db_manager = MagicMock(return_value=mock_db_manager)
    return facade


@pytest.fixture
def lancedb_storage(mock_storage_facade: MagicMock) -> LanceDBSessionStorage:
    """Create a LanceDB storage instance with mocked StorageFacade."""
    return LanceDBSessionStorage(mock_storage_facade)


# =============================================================================
# Protocol Compliance Tests
# =============================================================================


class TestProtocolCompliance:
    """Verify implementations satisfy SessionStorageProtocol."""

    def test_in_memory_is_protocol_compliant(self):
        """InMemorySessionStorage implements SessionStorageProtocol."""
        storage = InMemorySessionStorage()
        assert isinstance(storage, SessionStorageProtocol)

    def test_lancedb_is_protocol_compliant(self, mock_storage_facade: MagicMock):
        """LanceDBSessionStorage implements SessionStorageProtocol."""
        storage = LanceDBSessionStorage(mock_storage_facade)
        assert isinstance(storage, SessionStorageProtocol)


# =============================================================================
# InMemorySessionStorage Tests
# =============================================================================


class TestInMemorySessionStorage:
    """Tests for InMemorySessionStorage."""

    @pytest.mark.asyncio
    async def test_persist_and_load_session(
        self, memory_storage: InMemorySessionStorage, sample_session: Session
    ):
        """Persist and load a session."""
        await memory_storage.persist_session(sample_session)

        loaded = await memory_storage.load_session(sample_session.session_id)

        assert loaded is not None
        assert loaded.session_id == sample_session.session_id
        assert loaded.project_id == sample_session.project_id
        assert loaded.description == sample_session.description

    @pytest.mark.asyncio
    async def test_load_nonexistent_session(self, memory_storage: InMemorySessionStorage):
        """Loading nonexistent session returns None."""
        loaded = await memory_storage.load_session("nonexistent-id")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete_session(
        self, memory_storage: InMemorySessionStorage, sample_session: Session
    ):
        """Delete a session."""
        await memory_storage.persist_session(sample_session)

        deleted = await memory_storage.delete_session(sample_session.session_id)
        assert deleted is True

        loaded = await memory_storage.load_session(sample_session.session_id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(self, memory_storage: InMemorySessionStorage):
        """Deleting nonexistent session returns False."""
        deleted = await memory_storage.delete_session("nonexistent-id")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_sessions(self, memory_storage: InMemorySessionStorage):
        """List all sessions."""
        sessions = [
            Session(session_id=f"session-{i}", project_id="project-a")
            for i in range(3)
        ]
        for session in sessions:
            await memory_storage.persist_session(session)

        listed = await memory_storage.list_sessions()

        assert len(listed) == 3
        session_ids = {s["session_id"] for s in listed}
        assert session_ids == {"session-0", "session-1", "session-2"}

    @pytest.mark.asyncio
    async def test_list_sessions_by_project(self, memory_storage: InMemorySessionStorage):
        """List sessions filtered by project_id."""
        await memory_storage.persist_session(
            Session(session_id="s1", project_id="project-a")
        )
        await memory_storage.persist_session(
            Session(session_id="s2", project_id="project-b")
        )
        await memory_storage.persist_session(
            Session(session_id="s3", project_id="project-a")
        )

        listed = await memory_storage.list_sessions(project_id="project-a")

        assert len(listed) == 2
        session_ids = {s["session_id"] for s in listed}
        assert session_ids == {"s1", "s3"}

    @pytest.mark.asyncio
    async def test_list_sessions_excludes_expired(
        self, memory_storage: InMemorySessionStorage, expired_session: Session
    ):
        """List sessions excludes expired by default."""
        active = Session(session_id="active", project_id="test")
        expired_session.mark_expired()

        await memory_storage.persist_session(active)
        await memory_storage.persist_session(expired_session)

        listed = await memory_storage.list_sessions(include_expired=False)

        assert len(listed) == 1
        assert listed[0]["session_id"] == "active"

    @pytest.mark.asyncio
    async def test_list_sessions_includes_expired(
        self, memory_storage: InMemorySessionStorage, expired_session: Session
    ):
        """List sessions can include expired."""
        active = Session(session_id="active", project_id="test")
        expired_session.mark_expired()

        await memory_storage.persist_session(active)
        await memory_storage.persist_session(expired_session)

        listed = await memory_storage.list_sessions(include_expired=True)

        assert len(listed) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_with_limit(self, memory_storage: InMemorySessionStorage):
        """List sessions respects limit."""
        for i in range(10):
            await memory_storage.persist_session(
                Session(session_id=f"session-{i}", project_id="test")
            )

        listed = await memory_storage.list_sessions(limit=5)

        assert len(listed) == 5

    @pytest.mark.asyncio
    async def test_find_expired_sessions(
        self, memory_storage: InMemorySessionStorage, expired_session: Session
    ):
        """Find sessions that have exceeded TTL."""
        active = Session(session_id="active", project_id="test")

        await memory_storage.persist_session(active)
        await memory_storage.persist_session(expired_session)

        # TTL of 24 hours - expired_session is 48 hours old
        expired = await memory_storage.find_expired_sessions(ttl_hours=24)

        assert len(expired) == 1
        assert expired[0]["session_id"] == expired_session.session_id

    @pytest.mark.asyncio
    async def test_find_expired_sessions_none_expired(
        self, memory_storage: InMemorySessionStorage, sample_session: Session
    ):
        """Find expired sessions when none are expired."""
        await memory_storage.persist_session(sample_session)

        expired = await memory_storage.find_expired_sessions(ttl_hours=24)

        assert len(expired) == 0

    @pytest.mark.asyncio
    async def test_mark_session_expired(
        self, memory_storage: InMemorySessionStorage, sample_session: Session
    ):
        """Mark a session as expired."""
        await memory_storage.persist_session(sample_session)

        marked = await memory_storage.mark_session_expired(sample_session.session_id)
        assert marked is True

        loaded = await memory_storage.load_session(sample_session.session_id)
        assert loaded is not None
        assert loaded.is_expired is True

    @pytest.mark.asyncio
    async def test_mark_nonexistent_session_expired(
        self, memory_storage: InMemorySessionStorage
    ):
        """Marking nonexistent session returns False."""
        marked = await memory_storage.mark_session_expired("nonexistent-id")
        assert marked is False

    @pytest.mark.asyncio
    async def test_clear(self, memory_storage: InMemorySessionStorage):
        """Clear all sessions."""
        for i in range(5):
            await memory_storage.persist_session(
                Session(session_id=f"session-{i}", project_id="test")
            )

        assert memory_storage.session_count == 5

        memory_storage.clear()

        assert memory_storage.session_count == 0

    @pytest.mark.asyncio
    async def test_session_count(self, memory_storage: InMemorySessionStorage):
        """Session count property works correctly."""
        assert memory_storage.session_count == 0

        await memory_storage.persist_session(
            Session(session_id="s1", project_id="test")
        )
        assert memory_storage.session_count == 1

        await memory_storage.persist_session(
            Session(session_id="s2", project_id="test")
        )
        assert memory_storage.session_count == 2

    @pytest.mark.asyncio
    async def test_update_existing_session(
        self, memory_storage: InMemorySessionStorage, sample_session: Session
    ):
        """Persisting same session_id updates the record."""
        await memory_storage.persist_session(sample_session)

        sample_session.description = "Updated description"
        await memory_storage.persist_session(sample_session)

        loaded = await memory_storage.load_session(sample_session.session_id)
        assert loaded is not None
        assert loaded.description == "Updated description"
        assert memory_storage.session_count == 1


# =============================================================================
# LanceDBSessionStorage Tests
# =============================================================================


class TestLanceDBSessionStorage:
    """Tests for LanceDBSessionStorage with mocked db_manager."""

    @pytest.mark.asyncio
    async def test_persist_session(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
        sample_session: Session,
    ):
        """Persist session calls db_manager.upsert."""
        await lancedb_storage.persist_session(sample_session)

        mock_db_manager.upsert.assert_called_once()
        call_args = mock_db_manager.upsert.call_args
        assert call_args.kwargs["table_name"] == "mcp_sessions"
        assert call_args.kwargs["key_field"] == "session_id"
        assert len(call_args.kwargs["data"]) == 1

    @pytest.mark.asyncio
    async def test_persist_session_error(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
        sample_session: Session,
    ):
        """Persist session raises StorageError on failure."""
        mock_db_manager.upsert.side_effect = Exception("DB error")

        with pytest.raises(StorageError) as exc_info:
            await lancedb_storage.persist_session(sample_session)

        assert "Failed to persist session" in str(exc_info.value)
        assert exc_info.value.cause is not None

    @pytest.mark.asyncio
    async def test_load_session_found(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
        sample_session: Session,
    ):
        """Load session returns Session when found."""
        mock_db_manager.advanced_filter.return_value = [sample_session.to_db_record()]

        loaded = await lancedb_storage.load_session(sample_session.session_id)

        assert loaded is not None
        assert loaded.session_id == sample_session.session_id
        mock_db_manager.advanced_filter.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_session_not_found(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
    ):
        """Load session returns None when not found."""
        mock_db_manager.advanced_filter.return_value = []

        loaded = await lancedb_storage.load_session("nonexistent")

        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_session_error(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
    ):
        """Load session raises StorageError on failure."""
        mock_db_manager.advanced_filter.side_effect = Exception("DB error")

        with pytest.raises(StorageError) as exc_info:
            await lancedb_storage.load_session("test-id")

        assert "Failed to load session" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_session_found(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
        sample_session: Session,
    ):
        """Delete session marks as expired when found."""
        mock_db_manager.advanced_filter.return_value = [sample_session.to_db_record()]

        deleted = await lancedb_storage.delete_session(sample_session.session_id)

        assert deleted is True
        # Should have called upsert to persist the expired state
        mock_db_manager.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_session_not_found(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
    ):
        """Delete session returns False when not found."""
        mock_db_manager.advanced_filter.return_value = []

        deleted = await lancedb_storage.delete_session("nonexistent")

        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_sessions(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
        sample_session: Session,
    ):
        """List sessions returns formatted session data."""
        mock_db_manager.advanced_filter.return_value = [sample_session.to_db_record()]

        listed = await lancedb_storage.list_sessions()

        assert len(listed) == 1
        assert listed[0]["session_id"] == sample_session.session_id
        assert "created_at" in listed[0]
        assert "last_active" in listed[0]
        assert "age_hours" in listed[0]
        assert "inactive_hours" in listed[0]

    @pytest.mark.asyncio
    async def test_list_sessions_error(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
    ):
        """List sessions raises StorageError on failure."""
        mock_db_manager.advanced_filter.side_effect = Exception("DB error")

        with pytest.raises(StorageError) as exc_info:
            await lancedb_storage.list_sessions()

        assert "Failed to list sessions" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_find_expired_sessions(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
        expired_session: Session,
    ):
        """Find expired sessions returns sessions past TTL."""
        mock_db_manager.advanced_filter.return_value = [expired_session.to_db_record()]

        expired = await lancedb_storage.find_expired_sessions(ttl_hours=24)

        assert len(expired) == 1
        assert expired[0]["session_id"] == expired_session.session_id

    @pytest.mark.asyncio
    async def test_find_expired_sessions_error(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
    ):
        """Find expired sessions raises StorageError on failure."""
        mock_db_manager.advanced_filter.side_effect = Exception("DB error")

        with pytest.raises(StorageError) as exc_info:
            await lancedb_storage.find_expired_sessions(ttl_hours=24)

        assert "Failed to find expired sessions" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mark_session_expired_found(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
        sample_session: Session,
    ):
        """Mark session expired when found."""
        mock_db_manager.advanced_filter.return_value = [sample_session.to_db_record()]

        marked = await lancedb_storage.mark_session_expired(sample_session.session_id)

        assert marked is True
        mock_db_manager.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_session_expired_not_found(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
    ):
        """Mark session expired returns False when not found."""
        mock_db_manager.advanced_filter.return_value = []

        marked = await lancedb_storage.mark_session_expired("nonexistent")

        assert marked is False

    @pytest.mark.asyncio
    async def test_mark_session_expired_error(
        self,
        lancedb_storage: LanceDBSessionStorage,
        mock_db_manager: MagicMock,
        sample_session: Session,
    ):
        """Mark session expired returns False on StorageError (graceful degradation)."""
        mock_db_manager.advanced_filter.return_value = [sample_session.to_db_record()]
        mock_db_manager.upsert.side_effect = Exception("DB error")

        # StorageError from persist_session is caught and returns False
        result = await lancedb_storage.mark_session_expired(sample_session.session_id)
        assert result is False


# =============================================================================
# Integration Tests (SessionManager with InMemoryStorage)
# =============================================================================


class TestSessionManagerIntegration:
    """Test SessionManager with pluggable storage backend."""

    @pytest.mark.asyncio
    async def test_session_manager_with_memory_storage(self, tmp_path):
        """SessionManager works with InMemorySessionStorage."""
        from agentic_inquiry.config import Config, StorageConfig
        from agentic_inquiry.mcp.services.session_manager import SessionManager
        from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager

        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test"
        )

        # Create InMemoryLanceDBManager and wrap in mock StorageFacade
        db_manager = InMemoryLanceDBManager(uri="memory://test")
        mock_facade = MagicMock()
        mock_facade.get_backend_type = MagicMock(return_value="lancedb")
        mock_facade.get_db_manager = MagicMock(return_value=db_manager)

        memory_storage = InMemorySessionStorage()

        session_manager = SessionManager(
            db_manager=mock_facade,
            config=config,
            storage=memory_storage
        )

        # Create session - returns dict with session info
        result = await session_manager.create_session("test-project")
        assert result is not None
        assert result["project_id"] == "test-project"
        assert "session_id" in result

        # Verify stored in memory backend
        assert memory_storage.session_count == 1

        # Validate session
        is_valid = await session_manager.validate_session(result["session_id"])
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_session_manager_uses_default_storage(self, tmp_path):
        """SessionManager creates LanceDBSessionStorage by default."""
        from agentic_inquiry.config import Config, StorageConfig
        from agentic_inquiry.mcp.services.session_manager import SessionManager
        from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager

        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="test"
        )

        # Create InMemoryLanceDBManager and wrap in mock StorageFacade
        db_manager = InMemoryLanceDBManager(uri="memory://test")
        mock_facade = MagicMock()
        mock_facade.get_backend_type = MagicMock(return_value="lancedb")
        mock_facade.get_db_manager = MagicMock(return_value=db_manager)

        # Don't pass storage - should create LanceDBSessionStorage
        session_manager = SessionManager(
            db_manager=mock_facade,
            config=config
        )

        assert isinstance(session_manager.storage, LanceDBSessionStorage)
