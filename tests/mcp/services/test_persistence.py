"""Tests for session persistence backends.

Tests cover:
- InMemorySessionStorage: Full coverage for testing backend
- LanceDBSessionStorage: Tests against a real temporary LanceDB
- SessionStorageProtocol: Protocol compliance verification
"""

import pytest

pytestmark = pytest.mark.unit
from datetime import datetime, timedelta

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
def lancedb_session_storage(lancedb_storage) -> LanceDBSessionStorage:
    """LanceDB session storage over a real temporary database."""
    return LanceDBSessionStorage(lancedb_storage)


def _fail(*args, **kwargs):
    raise RuntimeError("DB error")


# =============================================================================
# Protocol Compliance Tests
# =============================================================================


class TestProtocolCompliance:
    """Verify implementations satisfy SessionStorageProtocol."""

    def test_in_memory_is_protocol_compliant(self):
        """InMemorySessionStorage implements SessionStorageProtocol."""
        storage = InMemorySessionStorage()
        assert isinstance(storage, SessionStorageProtocol)

    def test_lancedb_is_protocol_compliant(
        self, lancedb_session_storage: LanceDBSessionStorage
    ):
        """LanceDBSessionStorage implements SessionStorageProtocol."""
        assert isinstance(lancedb_session_storage, SessionStorageProtocol)


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
    """Tests for LanceDBSessionStorage against a real temporary LanceDB."""

    @pytest.mark.asyncio
    async def test_persist_and_load_session(
        self, lancedb_session_storage: LanceDBSessionStorage, sample_session: Session
    ):
        """A persisted session loads back with its fields intact."""
        await lancedb_session_storage.persist_session(sample_session)

        loaded = await lancedb_session_storage.load_session(sample_session.session_id)

        assert loaded is not None
        assert loaded.session_id == sample_session.session_id
        assert loaded.project_id == sample_session.project_id
        assert loaded.description == sample_session.description

    @pytest.mark.asyncio
    async def test_persist_twice_keeps_one_record(
        self, lancedb_session_storage: LanceDBSessionStorage, sample_session: Session
    ):
        """Persisting an existing session replaces it instead of duplicating it."""
        await lancedb_session_storage.persist_session(sample_session)
        sample_session.description = "Updated"
        await lancedb_session_storage.persist_session(sample_session)

        listed = await lancedb_session_storage.list_sessions()

        assert [s["description"] for s in listed] == ["Updated"]

    @pytest.mark.asyncio
    async def test_first_session_without_description_does_not_block_later_ones(
        self, lancedb_session_storage: LanceDBSessionStorage
    ):
        """Optional columns keep their type when the first row leaves them empty."""
        await lancedb_session_storage.persist_session(
            Session(session_id="bare", project_id="p")
        )
        await lancedb_session_storage.persist_session(
            Session(session_id="full", project_id="p", description="Described", log_file="/tmp/s.log")
        )

        listed = await lancedb_session_storage.list_sessions()

        assert {s["session_id"]: s["description"] for s in listed} == {
            "bare": None,
            "full": "Described",
        }

    @pytest.mark.asyncio
    async def test_persist_into_null_typed_legacy_table_names_the_fix(
        self, lancedb_session_storage: LanceDBSessionStorage, tmp_path
    ):
        """A table an older release typed as null fails with a recovery hint."""
        import lancedb

        legacy = Session(session_id="legacy", project_id="p").to_db_record()
        lancedb.connect(str(tmp_path / "lancedb")).create_table("mcp_sessions", data=[legacy])

        with pytest.raises(StorageError) as exc_info:
            await lancedb_session_storage.persist_session(
                Session(session_id="new", project_id="p", description="Described")
            )

        assert "null-typed columns ['description', 'log_file']" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_persist_session_error(
        self,
        lancedb_session_storage: LanceDBSessionStorage,
        sample_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Persist session raises StorageError on failure."""
        monkeypatch.setattr(lancedb_session_storage.db_manager, "upsert", _fail)

        with pytest.raises(StorageError) as exc_info:
            await lancedb_session_storage.persist_session(sample_session)

        assert "Failed to persist session" in str(exc_info.value)
        assert exc_info.value.cause is not None

    @pytest.mark.asyncio
    async def test_load_session_not_found(
        self, lancedb_session_storage: LanceDBSessionStorage
    ):
        """Load session returns None when not found."""
        assert await lancedb_session_storage.load_session("nonexistent") is None

    @pytest.mark.asyncio
    async def test_load_session_error(
        self,
        lancedb_session_storage: LanceDBSessionStorage,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Load session raises StorageError on failure."""
        monkeypatch.setattr(lancedb_session_storage.db_manager, "advanced_filter", _fail)

        with pytest.raises(StorageError) as exc_info:
            await lancedb_session_storage.load_session("test-id")

        assert "Failed to load session" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_session_marks_expired(
        self, lancedb_session_storage: LanceDBSessionStorage, sample_session: Session
    ):
        """Delete marks the session expired rather than removing the record."""
        await lancedb_session_storage.persist_session(sample_session)

        deleted = await lancedb_session_storage.delete_session(sample_session.session_id)

        assert deleted is True
        loaded = await lancedb_session_storage.load_session(sample_session.session_id)
        assert loaded is not None
        assert loaded.is_expired is True

    @pytest.mark.asyncio
    async def test_delete_session_not_found(
        self, lancedb_session_storage: LanceDBSessionStorage
    ):
        """Delete session returns False when not found."""
        assert await lancedb_session_storage.delete_session("nonexistent") is False

    @pytest.mark.asyncio
    async def test_list_sessions(
        self, lancedb_session_storage: LanceDBSessionStorage, sample_session: Session
    ):
        """List sessions returns formatted session data."""
        await lancedb_session_storage.persist_session(sample_session)

        listed = await lancedb_session_storage.list_sessions()

        assert len(listed) == 1
        assert listed[0]["session_id"] == sample_session.session_id
        assert "created_at" in listed[0]
        assert "last_active" in listed[0]
        assert "age_hours" in listed[0]
        assert "inactive_hours" in listed[0]

    @pytest.mark.asyncio
    async def test_list_sessions_filters_project_and_expired(
        self, lancedb_session_storage: LanceDBSessionStorage
    ):
        """List sessions filters by project and hides expired sessions by default."""
        expired = Session(session_id="s3", project_id="project-a")
        expired.mark_expired()
        for session in (
            Session(session_id="s1", project_id="project-a"),
            Session(session_id="s2", project_id="project-b"),
            expired,
        ):
            await lancedb_session_storage.persist_session(session)

        active_a = await lancedb_session_storage.list_sessions(project_id="project-a")
        all_a = await lancedb_session_storage.list_sessions(
            project_id="project-a", include_expired=True
        )

        assert {s["session_id"] for s in active_a} == {"s1"}
        assert {s["session_id"] for s in all_a} == {"s1", "s3"}

    @pytest.mark.asyncio
    async def test_list_sessions_error(
        self,
        lancedb_session_storage: LanceDBSessionStorage,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """List sessions raises StorageError on failure."""
        monkeypatch.setattr(lancedb_session_storage.db_manager, "advanced_filter", _fail)

        with pytest.raises(StorageError) as exc_info:
            await lancedb_session_storage.list_sessions()

        assert "Failed to list sessions" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_find_expired_sessions(
        self,
        lancedb_session_storage: LanceDBSessionStorage,
        sample_session: Session,
        expired_session: Session,
    ):
        """Find expired sessions returns only sessions past TTL."""
        await lancedb_session_storage.persist_session(sample_session)
        await lancedb_session_storage.persist_session(expired_session)

        expired = await lancedb_session_storage.find_expired_sessions(ttl_hours=24)

        assert [s["session_id"] for s in expired] == [expired_session.session_id]

    @pytest.mark.asyncio
    async def test_find_expired_sessions_error(
        self,
        lancedb_session_storage: LanceDBSessionStorage,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Find expired sessions raises StorageError on failure."""
        monkeypatch.setattr(lancedb_session_storage.db_manager, "advanced_filter", _fail)

        with pytest.raises(StorageError) as exc_info:
            await lancedb_session_storage.find_expired_sessions(ttl_hours=24)

        assert "Failed to find expired sessions" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_mark_session_expired_found(
        self, lancedb_session_storage: LanceDBSessionStorage, sample_session: Session
    ):
        """Mark session expired persists the expired state."""
        await lancedb_session_storage.persist_session(sample_session)

        marked = await lancedb_session_storage.mark_session_expired(sample_session.session_id)

        assert marked is True
        loaded = await lancedb_session_storage.load_session(sample_session.session_id)
        assert loaded is not None
        assert loaded.is_expired is True

    @pytest.mark.asyncio
    async def test_mark_session_expired_not_found(
        self, lancedb_session_storage: LanceDBSessionStorage
    ):
        """Mark session expired returns False when not found."""
        assert await lancedb_session_storage.mark_session_expired("nonexistent") is False

    @pytest.mark.asyncio
    async def test_mark_session_expired_error(
        self,
        lancedb_session_storage: LanceDBSessionStorage,
        sample_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Mark session expired returns False when the write fails."""
        await lancedb_session_storage.persist_session(sample_session)
        monkeypatch.setattr(lancedb_session_storage.db_manager, "upsert", _fail)

        assert await lancedb_session_storage.mark_session_expired(sample_session.session_id) is False


# =============================================================================
# Integration Tests (SessionManager with InMemoryStorage)
# =============================================================================


class TestSessionManagerIntegration:
    """Test SessionManager with pluggable storage backend."""

    @pytest.mark.asyncio
    async def test_session_manager_with_memory_storage(self, lancedb_storage):
        """SessionManager uses an explicitly supplied storage backend."""
        from agentic_inquiry.config import Config
        from agentic_inquiry.mcp.services.session_manager import SessionManager

        memory_storage = InMemorySessionStorage()
        session_manager = SessionManager(
            db_manager=lancedb_storage,
            config=Config.load(),
            storage=memory_storage,
        )

        result = await session_manager.create_session("test-project")

        assert result["project_id"] == "test-project"
        assert memory_storage.session_count == 1
        assert await session_manager.validate_session(result["session_id"]) is True

    @pytest.mark.asyncio
    async def test_session_manager_uses_default_storage(self, lancedb_storage):
        """SessionManager persists to LanceDB when the backend is LanceDB."""
        from agentic_inquiry.config import Config
        from agentic_inquiry.mcp.services.session_manager import SessionManager

        session_manager = SessionManager(db_manager=lancedb_storage, config=Config.load())

        assert isinstance(session_manager.storage, LanceDBSessionStorage)
