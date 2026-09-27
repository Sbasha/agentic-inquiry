"""Unit tests for SessionManager service."""

import pytest

pytestmark = pytest.mark.integration
import pytest_asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inquiry.database.filters import Filter, FilterOperator
from agentic_inquiry.mcp.services.session_manager import (
    SessionManager,
    SessionCleanupManager,
)
from agentic_inquiry.mcp.models.session import Session, SessionState
from agentic_inquiry.config import Config


def _filter_matches(filter_obj, field: str, value) -> bool:
    """Check if a Filter AST matches a field=value condition.

    Handles both simple EQ filters and AND combinations.
    """
    if filter_obj is None:
        return False

    if isinstance(filter_obj, Filter):
        # Check direct EQ match
        if filter_obj.operator == FilterOperator.EQ:
            return filter_obj.field == field and filter_obj.value == value
        # Check AND - recursively check both sides
        elif filter_obj.operator == FilterOperator.AND:
            return _filter_matches(filter_obj.left, field, value) or _filter_matches(
                filter_obj.right, field, value
            )
    return False


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager (raw LanceDBManager).

    This mock represents the raw LanceDBManager obtained via get_db_manager().
    The SessionManager uses this for:
    - advanced_filter: gathering statistics (files, chunks, entities)
    - count_records: counting records for statistics
    """
    mock_db_manager = MagicMock()
    mock_db_manager.advanced_filter = AsyncMock(return_value=[])
    mock_db_manager.count_records = AsyncMock(return_value=0)
    mock_db_manager.upsert = AsyncMock()
    return mock_db_manager


@pytest.fixture
def mock_storage_facade(mock_db_manager):
    """Create a mock StorageFacade that wraps the mock_db_manager.

    Note: LanceDBSessionStorage extracts the raw db_manager via get_db_manager()
    and calls upsert/advanced_filter on it, not on the facade.
    """
    mock_storage = MagicMock()
    mock_storage.get_db_manager = MagicMock(return_value=mock_db_manager)
    # Configure backend type so SessionManager uses LanceDBSessionStorage
    mock_storage.get_backend_type = MagicMock(return_value="lancedb")
    return mock_storage


@pytest.fixture
def mock_config():
    """Create a test configuration."""
    return Config.load()


@pytest_asyncio.fixture
async def session_manager(mock_storage_facade, mock_db_manager, mock_config):
    """Create a SessionManager instance for testing."""
    return SessionManager(mock_storage_facade, mock_config)


class TestSessionCreation:
    """Tests for session creation functionality."""

    @pytest.mark.asyncio
    async def test_create_session_empty_project(self, session_manager, mock_db_manager):
        """Test session creation for empty project."""
        # Mock empty project (no chunks)
        mock_db_manager.advanced_filter.return_value = []

        result = await session_manager.create_session(
            project_id="test_project", description="Test session"
        )

        # Verify session metadata
        assert "session_id" in result
        assert result["project_id"] == "test_project"
        assert result["status"] == "empty"
        assert "guidance" in result
        assert "next_steps" in result
        assert len(result["next_steps"]) > 0

        # Verify statistics
        stats = result["statistics"]
        assert stats["total_chunks"] == 0
        assert stats["total_files"] == 0
        assert stats["index_health"] == "empty"

        # Verify session was persisted via LanceDBSessionStorage
        # LanceDBSessionStorage extracts db_manager via get_db_manager() and calls upsert on it
        assert mock_db_manager.upsert.called

    @pytest.mark.asyncio
    async def test_create_session_indexed_project(
        self, session_manager, mock_db_manager
    ):
        """Test session creation for indexed project."""
        # Mock indexed project with chunks
        mock_chunks = [
            {
                "id": "chunk1",
                "file_path": "src/main.py",
                "language": "python",
                "created_at": datetime.now().isoformat(),
            },
            {
                "id": "chunk2",
                "file_path": "src/utils.py",
                "language": "python",
                "created_at": datetime.now().isoformat(),
            },
        ]

        async def mock_filter(*args, **kwargs):
            table_name = kwargs.get("table_name")
            if table_name == "document_chunks":
                return mock_chunks
            return []

        async def mock_count(*args, **kwargs):
            table_name = kwargs.get("table_name")
            if table_name == "document_chunks":
                return len(mock_chunks)
            return 0

        mock_db_manager.advanced_filter = mock_filter
        mock_db_manager.count_records = mock_count

        result = await session_manager.create_session(project_id="test_project")

        # Verify session metadata
        assert result["status"] == "ready"
        assert result["statistics"]["total_chunks"] == 2
        assert result["statistics"]["total_files"] == 2
        assert result["statistics"]["index_health"] == "healthy"

    @pytest.mark.asyncio
    async def test_create_session_with_description(
        self, session_manager, mock_db_manager
    ):
        """Test session creation with description."""
        mock_db_manager.advanced_filter.return_value = []

        description = "Working on authentication feature"
        result = await session_manager.create_session(
            project_id="test_project", description=description
        )

        # Verify session is in memory cache
        session_id = result["session_id"]
        assert session_id in session_manager.active_sessions

        session = session_manager.active_sessions[session_id]
        assert session.description == description


class TestSessionValidation:
    """Tests for session validation."""

    @pytest.mark.asyncio
    async def test_validate_existing_session(self, session_manager, mock_db_manager):
        """Test validation of existing session."""
        # Create a session first
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        # Validate it
        is_valid = await session_manager.validate_session(session_id)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_validate_nonexistent_session(self, session_manager, mock_db_manager):
        """Test validation of non-existent session."""
        mock_db_manager.advanced_filter.return_value = []

        is_valid = await session_manager.validate_session("nonexistent-id")
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_validate_expired_session(self, session_manager, mock_db_manager):
        """Test validation of expired session."""
        # Create a session
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        # Mark it as expired
        session = session_manager.active_sessions[session_id]
        session.mark_expired()

        # Validate it
        is_valid = await session_manager.validate_session(session_id)
        assert is_valid is False


class TestSessionRetrieval:
    """Tests for session retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_session(self, session_manager, mock_db_manager):
        """Test retrieving a session."""
        # Create a session
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        # Retrieve it
        session = await session_manager.get_session(session_id)
        assert session is not None
        assert session.session_id == session_id
        assert session.project_id == "test_project"

    @pytest.mark.asyncio
    async def test_get_session_without_history(self, session_manager, mock_db_manager):
        """Test retrieving session without history for efficiency."""
        # Create a session with history
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        session = session_manager.active_sessions[session_id]
        session.add_to_history("test_tool", {"param": "value"})

        # Retrieve without history
        retrieved = await session_manager.get_session(session_id, include_history=False)
        assert retrieved is not None
        assert len(retrieved.history) == 0

    @pytest.mark.asyncio
    async def test_list_sessions(self, session_manager, mock_db_manager):
        """Test listing sessions."""
        # Mock database response
        mock_sessions = [
            {
                "session_id": "session1",
                "project_id": "project1",
                "created_at": datetime.now(),
                "last_active": datetime.now(),
                "description": "Session 1",
                "state_json": "{}",
                "history_json": "[]",
                "log_file": "/path/to/log",
                "is_expired": False,
            }
        ]
        mock_db_manager.advanced_filter.return_value = mock_sessions

        sessions = await session_manager.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "session1"

    @pytest.mark.asyncio
    async def test_list_sessions_by_project(self, session_manager, mock_db_manager):
        """Test listing sessions filtered by project."""
        mock_db_manager.advanced_filter.return_value = []

        await session_manager.list_sessions(project_id="test_project")

        # Verify filter was applied (now uses Filter AST)
        call_args = mock_db_manager.advanced_filter.call_args
        filters = call_args[1]["filters"]
        assert _filter_matches(filters, "project_id", "test_project")

    @pytest.mark.asyncio
    async def test_resume_session(self, session_manager, mock_db_manager):
        """Test resuming an existing session."""
        # Create a session
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        # Resume it
        resumed = await session_manager.resume_session(session_id)

        assert resumed["session_id"] == session_id
        assert "state" in resumed
        assert "history_count" in resumed

    @pytest.mark.asyncio
    async def test_resume_nonexistent_session(self, session_manager, mock_db_manager):
        """Test resuming non-existent session raises error."""
        mock_db_manager.advanced_filter.return_value = []

        # Use valid UUID format that doesn't exist in database
        nonexistent_uuid = "00000000-0000-4000-8000-000000000000"
        with pytest.raises(ValueError, match="not found"):
            await session_manager.resume_session(nonexistent_uuid)

    @pytest.mark.asyncio
    async def test_get_session_history(self, session_manager, mock_db_manager):
        """Test retrieving session history."""
        # Create a session with history
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        session = session_manager.active_sessions[session_id]
        session.add_to_history("tool1", {"param": "value1"})
        session.add_to_history("tool2", {"param": "value2"})

        # Get history
        history = await session_manager.get_session_history(session_id)
        assert len(history) == 2
        assert history[0]["tool"] == "tool1"
        assert history[1]["tool"] == "tool2"

    @pytest.mark.asyncio
    async def test_get_session_history_with_limit(
        self, session_manager, mock_db_manager
    ):
        """Test retrieving limited session history."""
        # Create a session with history
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        session = session_manager.active_sessions[session_id]
        for i in range(5):
            session.add_to_history(f"tool{i}", {"param": f"value{i}"})

        # Get limited history (most recent 2)
        history = await session_manager.get_session_history(session_id, limit=2)
        assert len(history) == 2
        assert history[0]["tool"] == "tool3"
        assert history[1]["tool"] == "tool4"


class TestSessionPersistence:
    """Tests for session persistence (to_db_record and from_db_record)."""

    @pytest.mark.asyncio
    async def test_to_db_record_format(self, session_manager, mock_db_manager):
        """Test to_db_record creates correct format."""
        # Create a session
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(
            project_id="test_project", description="Test session"
        )
        session_id = result["session_id"]

        # Get the session and convert to DB record
        session = session_manager.active_sessions[session_id]
        record = session.to_db_record()

        # Verify all required fields are present
        assert "id" in record
        assert "session_id" in record
        assert "project_id" in record
        assert "state" in record
        assert "created_at" in record
        assert "last_active" in record
        assert "description" in record
        assert "log_file" in record
        assert "context_state_json" in record
        assert "is_expired" in record
        assert "history_json" in record
        assert "events_json" in record
        assert "status" in record

        # Verify field types and values
        assert record["id"] == session_id
        assert record["session_id"] == session_id
        assert record["project_id"] == "test_project"
        assert isinstance(record["state"], str)  # Enum converted to string
        assert isinstance(record["created_at"], str)  # DateTime converted to ISO 8601
        assert isinstance(record["last_active"], str)  # DateTime converted to ISO 8601
        assert record["description"] == "Test session"
        assert record["log_file"] is None or isinstance(
            record["log_file"], str
        )  # Path converted to string or None
        assert isinstance(
            record["context_state_json"], str
        )  # Serialized to JSON string
        assert isinstance(record["is_expired"], bool)
        assert isinstance(record["history_json"], str)  # Serialized to JSON string
        assert isinstance(record["events_json"], str)  # Serialized to JSON string

    @pytest.mark.asyncio
    async def test_to_db_record_datetime_conversion(
        self, session_manager, mock_db_manager
    ):
        """Test to_db_record converts datetime to ISO 8601 strings."""
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        session = session_manager.active_sessions[session_id]
        record = session.to_db_record()

        # Verify datetime fields are ISO 8601 strings
        assert isinstance(record["created_at"], str)
        assert isinstance(record["last_active"], str)

        # Verify they can be parsed back to datetime
        from datetime import datetime

        created_at = datetime.fromisoformat(record["created_at"])
        last_active = datetime.fromisoformat(record["last_active"])

        assert isinstance(created_at, datetime)
        assert isinstance(last_active, datetime)

    @pytest.mark.asyncio
    async def test_to_db_record_state_conversion(
        self, session_manager, mock_db_manager
    ):
        """Test to_db_record converts SessionState enum to string."""
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        session = session_manager.active_sessions[session_id]
        record = session.to_db_record()

        # Verify state is a string
        assert isinstance(record["state"], str)
        assert record["state"] in ["active", "expired", "archived"]

        # Verify it matches the enum value
        assert record["state"] == session.state.value

    @pytest.mark.asyncio
    async def test_to_db_record_path_conversion(self, session_manager, mock_db_manager):
        """Test to_db_record converts Path to string."""
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        session = session_manager.active_sessions[session_id]
        record = session.to_db_record()

        # Verify log_file is a string
        assert isinstance(record["log_file"], str)
        assert len(record["log_file"]) > 0

    @pytest.mark.asyncio
    async def test_to_db_record_with_none_log_file(self):
        """Test to_db_record handles None log_file."""
        from datetime import datetime

        session = Session(
            session_id="test_id",
            project_id="test_project",
            created_at=datetime.now(),
            last_active=datetime.now(),
            log_file=None,
        )

        record = session.to_db_record()

        # Verify log_file is None
        assert record["log_file"] is None

    @pytest.mark.asyncio
    async def test_from_db_record_reconstruction(
        self, session_manager, mock_db_manager
    ):
        """Test from_db_record reconstructs Session correctly."""
        from datetime import datetime

        # Create a database record
        now = datetime.now()
        db_record = {
            "id": "test_session_id",
            "session_id": "test_session_id",
            "project_id": "test_project",
            "state": "active",
            "created_at": now.isoformat(),
            "last_active": now.isoformat(),
            "description": "Test session",
            "log_file": "/path/to/log.log",
            "context_state": {"key": "value"},
            "is_expired": False,
            "history": [{"tool": "test", "params": {}}],
        }

        # Reconstruct session
        session = Session.from_db_record(db_record)

        # Verify all fields are correctly reconstructed
        assert session.session_id == "test_session_id"
        assert session.project_id == "test_project"
        assert isinstance(session.state, SessionState)
        assert session.state == SessionState.ACTIVE
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_active, datetime)
        assert session.description == "Test session"
        assert isinstance(session.log_file, Path)
        assert str(session.log_file) == "/path/to/log.log"
        assert session.context_state == {"key": "value"}
        assert session.is_expired is False
        assert len(session.history) == 1

    @pytest.mark.asyncio
    async def test_from_db_record_datetime_conversion(self):
        """Test from_db_record converts ISO 8601 strings to datetime."""
        from datetime import datetime

        db_record = {
            "session_id": "test_id",
            "project_id": "test_project",
            "state": "active",
            "created_at": "2024-01-15T10:30:00",
            "last_active": "2024-01-15T11:45:00",
            "description": None,
            "log_file": None,
            "context_state": {},
            "is_expired": False,
            "history": [],
        }

        session = Session.from_db_record(db_record)

        # Verify datetime conversion
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_active, datetime)
        assert session.created_at.year == 2024
        assert session.created_at.month == 1
        assert session.created_at.day == 15

    @pytest.mark.asyncio
    async def test_from_db_record_state_conversion(self):
        """Test from_db_record converts string to SessionState enum."""
        from agentic_inquiry.mcp.models.session import SessionState
        from datetime import datetime

        for state_str in ["active", "expired", "archived"]:
            db_record = {
                "session_id": "test_id",
                "project_id": "test_project",
                "state": state_str,
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
                "description": None,
                "log_file": None,
                "context_state": {},
                "is_expired": False,
                "history": [],
            }

            session = Session.from_db_record(db_record)

            # Verify state conversion
            assert isinstance(session.state, SessionState)
            assert session.state.value == state_str

    @pytest.mark.asyncio
    async def test_round_trip_persistence(self, session_manager, mock_db_manager):
        """Test round-trip: to_db_record -> from_db_record."""

        # Create a session
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(
            project_id="test_project", description="Round trip test"
        )
        session_id = result["session_id"]

        # Get original session
        original = session_manager.active_sessions[session_id]

        # Add some history
        original.add_to_history("test_tool", {"param": "value"})

        # Convert to DB record and back
        db_record = original.to_db_record()
        reconstructed = Session.from_db_record(db_record)

        # Verify all fields match
        assert reconstructed.session_id == original.session_id
        assert reconstructed.project_id == original.project_id
        assert reconstructed.state == original.state
        assert reconstructed.description == original.description
        assert reconstructed.is_expired == original.is_expired
        assert len(reconstructed.history) == len(original.history)
        assert reconstructed.context_state == original.context_state

        # Verify datetime fields are close (within 1 second)
        time_diff = abs(
            (reconstructed.created_at - original.created_at).total_seconds()
        )
        assert time_diff < 1

    @pytest.mark.asyncio
    async def test_persist_session_error_handling(
        self, session_manager, mock_db_manager
    ):
        """Test _persist_session handles errors gracefully."""
        # Create a session
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        session = session_manager.active_sessions[session_id]

        # Make upsert fail - LanceDBSessionStorage extracts db_manager via get_db_manager()
        mock_db_manager.upsert = AsyncMock(side_effect=Exception("Database error"))

        # Persist should not raise exception
        await session_manager._persist_session(session)

        # Session should still be in memory
        assert session_id in session_manager.active_sessions

    @pytest.mark.asyncio
    async def test_persist_session_uses_upsert(self, session_manager, mock_db_manager):
        """Test _persist_session uses upsert with correct parameters."""
        # Create a session
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        session = session_manager.active_sessions[session_id]

        # Reset mock to clear previous calls
        mock_db_manager.upsert.reset_mock()

        # Persist session
        await session_manager._persist_session(session)

        # Verify upsert was called with correct parameters
        # LanceDBSessionStorage extracts db_manager via get_db_manager() and calls upsert on it
        assert mock_db_manager.upsert.called
        call_args = mock_db_manager.upsert.call_args

        assert call_args[1]["table_name"] == "mcp_sessions"
        assert isinstance(call_args[1]["data"], list)
        assert len(call_args[1]["data"]) == 1
        assert call_args[1]["key_field"] == "session_id"

        # Verify record has correct structure
        record = call_args[1]["data"][0]
        assert record["session_id"] == session_id
        assert "state" in record
        assert isinstance(record["state"], str)

    @pytest.mark.asyncio
    async def test_all_required_fields_in_db_record(
        self, session_manager, mock_db_manager
    ):
        """Test that to_db_record includes ALL required fields for database schema.

        This test verifies that the database record includes all fields documented
        in docs/mcp/mcp_sessions_schema.md, including ttl_hours which was added
        in the MCP workflow fixes.

        Requirements: Req 8.1-8.5, 8.6
        """
        # Create a session
        mock_db_manager.advanced_filter.return_value = []
        result = await session_manager.create_session(
            project_id="test_project", description="Schema validation test"
        )
        session_id = result["session_id"]

        # Get the session and convert to DB record
        session = session_manager.active_sessions[session_id]
        record = session.to_db_record()

        # Verify ALL required fields from schema are present
        required_fields = [
            "id",
            "session_id",
            "project_id",
            "state",
            "status",
            "created_at",
            "last_active",
            "description",
            "log_file",
            "context_state_json",
            "is_expired",
            "history_json",
            "events_json",
            "ttl_hours",  # Added in MCP workflow fixes
        ]

        for field in required_fields:
            assert field in record, (
                f"Required field '{field}' missing from database record"
            )

        # Verify field types match schema
        assert isinstance(record["id"], str), "id must be string"
        assert isinstance(record["session_id"], str), "session_id must be string"
        assert isinstance(record["project_id"], str), "project_id must be string"
        assert isinstance(record["state"], str), "state must be string (enum value)"
        assert isinstance(record["status"], str), "status must be string"
        assert isinstance(record["created_at"], str), (
            "created_at must be ISO 8601 string"
        )
        assert isinstance(record["last_active"], str), (
            "last_active must be ISO 8601 string"
        )
        assert record["description"] is None or isinstance(
            record["description"], str
        ), "description must be string or None"
        assert record["log_file"] is None or isinstance(record["log_file"], str), (
            "log_file must be string or None"
        )
        assert isinstance(record["context_state_json"], str), (
            "context_state_json must be JSON string"
        )
        assert isinstance(record["is_expired"], bool), "is_expired must be bool"
        assert isinstance(record["history_json"], str), (
            "history_json must be JSON string"
        )
        assert isinstance(record["events_json"], str), "events_json must be JSON string"
        assert isinstance(record["ttl_hours"], int), "ttl_hours must be int"

        # Verify ttl_hours has correct default value
        assert record["ttl_hours"] == 48, "ttl_hours should default to 48"

        # Verify state is converted from enum to string value
        assert record["state"] in ["active", "expired", "archived"], (
            "state must be valid enum value"
        )

        # Verify datetime fields are ISO 8601 format
        from datetime import datetime

        try:
            datetime.fromisoformat(record["created_at"])
            datetime.fromisoformat(record["last_active"])
        except ValueError:
            pytest.fail("DateTime fields must be valid ISO 8601 format")

    @pytest.mark.asyncio
    async def test_session_loading_all_fields(self, session_manager, mock_db_manager):
        """Test that from_db_record correctly reconstructs ALL session fields.

        This test verifies that loading a session from the database correctly
        reconstructs all fields with proper types, including ttl_hours which
        was added in the MCP workflow fixes.

        Requirements: Req 8.7
        """
        from agentic_inquiry.mcp.models.session import SessionState
        from datetime import datetime
        from pathlib import Path

        # Create a complete database record with all fields
        db_record = {
            "id": "test_session_123",
            "session_id": "test_session_123",
            "project_id": "test_project",
            "state": "active",
            "created_at": "2024-01-15T10:30:00.123456",
            "last_active": "2024-01-15T10:35:00.123456",
            "description": "Test session for loading",
            "log_file": "/logs/test_session_123.log",
            "context_state": {"last_query": "test query", "refinement_count": 2},
            "is_expired": False,
            "history": [
                {
                    "tool": "add_knowledge",
                    "params": {"source": "test.py"},
                    "timestamp": "2024-01-15T10:30:00.123456",
                }
            ],
            "ttl_hours": 48,
        }

        # Reconstruct session from database record
        session = Session.from_db_record(db_record)

        # Verify all fields are correctly reconstructed
        assert session.session_id == "test_session_123", "session_id not reconstructed"
        assert session.project_id == "test_project", "project_id not reconstructed"
        assert session.description == "Test session for loading", (
            "description not reconstructed"
        )
        assert session.ttl_hours == 48, "ttl_hours not reconstructed"

        # Verify state is converted from string to enum
        assert isinstance(session.state, SessionState), (
            "state should be SessionState enum"
        )
        assert session.state == SessionState.ACTIVE, "state value incorrect"

        # Verify datetime fields are converted from ISO 8601 strings
        assert isinstance(session.created_at, datetime), (
            "created_at should be datetime object"
        )
        assert isinstance(session.last_active, datetime), (
            "last_active should be datetime object"
        )
        assert session.created_at.year == 2024, "created_at year incorrect"
        assert session.created_at.month == 1, "created_at month incorrect"
        assert session.created_at.day == 15, "created_at day incorrect"

        # Verify log_file is converted from string to Path
        assert isinstance(session.log_file, Path), "log_file should be Path object"
        assert str(session.log_file) == "/logs/test_session_123.log", (
            "log_file path incorrect"
        )

        # Verify complex fields are preserved
        assert isinstance(session.context_state, dict), "context_state should be dict"
        assert session.context_state["last_query"] == "test query", (
            "context_state content incorrect"
        )
        assert session.context_state["refinement_count"] == 2, (
            "context_state content incorrect"
        )

        assert isinstance(session.history, list), "history should be list"
        assert len(session.history) == 1, "history length incorrect"
        assert session.history[0]["tool"] == "add_knowledge", (
            "history content incorrect"
        )

        # Verify is_expired property works (not stored as field)
        assert hasattr(session, "is_expired"), "is_expired property should exist"
        assert isinstance(session.is_expired, bool), "is_expired should be bool"

    @pytest.mark.asyncio
    async def test_session_loading_with_missing_ttl_hours(
        self, session_manager, mock_db_manager
    ):
        """Test that from_db_record handles missing ttl_hours field.

        This test verifies backward compatibility when loading sessions
        from databases that don't have the ttl_hours field yet.

        Requirements: Req 8.7
        """

        # Create a database record WITHOUT ttl_hours (old schema)
        db_record = {
            "id": "test_session_456",
            "session_id": "test_session_456",
            "project_id": "test_project",
            "state": "active",
            "created_at": "2024-01-15T10:30:00.123456",
            "last_active": "2024-01-15T10:35:00.123456",
            "description": "Old schema session",
            "log_file": None,
            "context_state": {},
            "is_expired": False,
            "history": [],
            # Note: ttl_hours is missing
        }

        # Reconstruct session from database record
        session = Session.from_db_record(db_record)

        # Verify ttl_hours defaults to 48 when missing
        assert session.ttl_hours == 48, "ttl_hours should default to 48 when missing"

        # Verify other fields still work
        assert session.session_id == "test_session_456"
        assert session.project_id == "test_project"

    @pytest.mark.asyncio
    async def test_session_loading_with_null_optional_fields(
        self, session_manager, mock_db_manager
    ):
        """Test that from_db_record handles null optional fields correctly.

        Requirements: Req 8.7
        """

        # Create a database record with null optional fields
        db_record = {
            "id": "test_session_789",
            "session_id": "test_session_789",
            "project_id": "test_project",
            "state": "active",
            "created_at": "2024-01-15T10:30:00.123456",
            "last_active": "2024-01-15T10:35:00.123456",
            "description": None,  # Optional field
            "log_file": None,  # Optional field
            "context_state": {},
            "is_expired": False,
            "history": [],
            "ttl_hours": 48,
        }

        # Reconstruct session from database record
        session = Session.from_db_record(db_record)

        # Verify null optional fields are handled correctly
        assert session.description is None, "description should be None"
        assert session.log_file is None, "log_file should be None"

        # Verify required fields still work
        assert session.session_id == "test_session_789"
        assert session.ttl_hours == 48


class TestSessionCleanup:
    """Tests for session cleanup functionality."""

    @pytest_asyncio.fixture
    async def cleanup_manager(self, session_manager):
        """Create a SessionCleanupManager instance."""
        return SessionCleanupManager(session_manager)

    @pytest.mark.asyncio
    async def test_find_expired_sessions(self, cleanup_manager, mock_db_manager):
        """Test finding expired sessions."""
        # Mock sessions with different ages
        old_time = datetime.now() - timedelta(hours=50)
        recent_time = datetime.now() - timedelta(hours=1)

        mock_sessions = [
            {
                "session_id": "old_session",
                "project_id": "project1",
                "created_at": old_time,
                "last_active": old_time,
                "description": "",
                "state_json": "{}",
                "history_json": "[]",
                "log_file": "/path/to/log",
                "is_expired": False,
            },
            {
                "session_id": "recent_session",
                "project_id": "project1",
                "created_at": recent_time,
                "last_active": recent_time,
                "description": "",
                "state_json": "{}",
                "history_json": "[]",
                "log_file": "/path/to/log",
                "is_expired": False,
            },
        ]
        mock_db_manager.advanced_filter.return_value = mock_sessions

        expired = await cleanup_manager._find_expired_sessions()

        # Only old session should be expired
        assert len(expired) == 1
        assert expired[0]["session_id"] == "old_session"

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions_dry_run(
        self, cleanup_manager, mock_db_manager
    ):
        """Test dry run of cleanup."""
        old_time = datetime.now() - timedelta(hours=50)
        mock_sessions = [
            {
                "session_id": "old_session",
                "project_id": "project1",
                "created_at": old_time,
                "last_active": old_time,
                "description": "",
                "state_json": "{}",
                "history_json": "[]",
                "log_file": "/path/to/log",
                "is_expired": False,
            }
        ]
        mock_db_manager.advanced_filter.return_value = mock_sessions

        result = await cleanup_manager.cleanup_expired_sessions(dry_run=True)

        assert result["dry_run"] is True
        assert result["expired_count"] == 1
        assert len(result["expired_sessions"]) == 1

        # Verify no actual cleanup was performed
        assert not mock_db_manager.upsert.called

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, cleanup_manager, mock_db_manager):
        """Test actual cleanup of expired sessions."""
        old_time = datetime.now() - timedelta(hours=50)
        mock_sessions = [
            {
                "session_id": "old_session",
                "project_id": "project1",
                "created_at": old_time,
                "last_active": old_time,
                "description": "",
                "state_json": "{}",
                "history_json": "[]",
                "log_file": "/path/to/log",
                "is_expired": False,
            }
        ]

        async def mock_filter(*args, **kwargs):
            filters = kwargs.get("filters")
            # Handle Filter AST - check for is_expired=False
            if _filter_matches(filters, "is_expired", False):
                return mock_sessions
            return []

        mock_db_manager.advanced_filter = mock_filter

        with patch.object(cleanup_manager, "_archive_session", return_value=True):
            result = await cleanup_manager.cleanup_expired_sessions(dry_run=False)

        assert result["dry_run"] is False
        assert result["cleaned_count"] == 1
        assert result["archived_count"] == 1


class TestProjectStatistics:
    """Tests for project statistics gathering."""

    @pytest.mark.asyncio
    async def test_gather_statistics_empty_project(
        self, session_manager, mock_db_manager
    ):
        """Test gathering statistics for empty project."""
        mock_db_manager.advanced_filter.return_value = []

        stats = await session_manager._gather_project_statistics("test_project")

        assert stats.total_chunks == 0
        assert stats.total_files == 0
        assert stats.index_health == "empty"
        assert stats.is_empty() is True

    @pytest.mark.asyncio
    async def test_gather_statistics_with_content(
        self, session_manager, mock_db_manager
    ):
        """Test gathering statistics for project with content."""
        mock_chunks = [
            {
                "id": "chunk1",
                "file_path": "src/main.py",
                "language": "python",
                "created_at": datetime.now().isoformat(),
            },
            {
                "id": "chunk2",
                "file_path": "src/main.py",
                "language": "python",
                "created_at": datetime.now().isoformat(),
            },
            {
                "id": "chunk3",
                "file_path": "src/utils.py",
                "language": "python",
                "created_at": datetime.now().isoformat(),
            },
        ]

        async def mock_filter(*args, **kwargs):
            table_name = kwargs.get("table_name")
            if table_name == "document_chunks":
                return mock_chunks
            return []

        async def mock_count(*args, **kwargs):
            table_name = kwargs.get("table_name")
            if table_name == "document_chunks":
                return len(mock_chunks)
            return 0

        mock_db_manager.advanced_filter = mock_filter
        mock_db_manager.count_records = mock_count

        stats = await session_manager._gather_project_statistics("test_project")

        assert stats.total_chunks == 3
        assert stats.total_files == 2
        assert stats.languages["python"] == 3
        assert stats.index_health == "healthy"

    @pytest.mark.asyncio
    async def test_gather_statistics_with_memory_system_none(
        self, session_manager: SessionManager
    ):
        """Test statistics gathering when memory_system is None."""
        # Ensure memory_system is None
        session_manager.memory_system = None

        # Mock database responses
        session_manager.db_manager.count_records = AsyncMock(
            side_effect=[
                5,  # chunks
                10,  # entities
            ]
        )
        session_manager.db_manager.advanced_filter = AsyncMock(
            return_value=[
                {
                    "file_path": "test.py",
                    "language": "python",
                    "created_at": datetime.now().isoformat(),
                }
            ]
        )

        # Gather statistics
        stats = await session_manager._gather_project_statistics("test_project")

        # Verify memory count is 0 and no errors occurred
        assert stats.total_memories == 0
        assert stats.total_chunks == 5
        assert stats.index_health == "healthy"

    @pytest.mark.asyncio
    async def test_gather_statistics_with_episodic_none(
        self, session_manager: SessionManager
    ):
        """Test statistics gathering when episodic layer is None."""
        # Create a mock memory system with None episodic layer
        mock_memory_system = MagicMock()
        mock_memory_system.episodic = None
        session_manager.memory_system = mock_memory_system

        # Mock database responses
        session_manager.db_manager.count_records = AsyncMock(
            side_effect=[
                5,  # chunks
                10,  # entities
            ]
        )
        session_manager.db_manager.advanced_filter = AsyncMock(
            return_value=[
                {
                    "file_path": "test.py",
                    "language": "python",
                    "created_at": datetime.now().isoformat(),
                }
            ]
        )

        # Gather statistics
        stats = await session_manager._gather_project_statistics("test_project")

        # Verify memory count is 0 and no errors occurred
        assert stats.total_memories == 0
        assert stats.total_chunks == 5
        assert stats.index_health == "healthy"

    @pytest.mark.asyncio
    async def test_gather_statistics_with_missing_episodic_attribute(
        self, session_manager: SessionManager
    ):
        """Test statistics gathering when memory system lacks episodic attribute."""
        # Create a mock memory system without episodic attribute
        mock_memory_system = MagicMock(spec=[])  # Empty spec, no attributes
        session_manager.memory_system = mock_memory_system

        # Mock database responses
        session_manager.db_manager.count_records = AsyncMock(
            side_effect=[
                5,  # chunks
                10,  # entities
            ]
        )
        session_manager.db_manager.advanced_filter = AsyncMock(
            return_value=[
                {
                    "file_path": "test.py",
                    "language": "python",
                    "created_at": datetime.now().isoformat(),
                }
            ]
        )

        # Gather statistics
        stats = await session_manager._gather_project_statistics("test_project")

        # Verify memory count is 0 and no errors occurred
        assert stats.total_memories == 0
        assert stats.total_chunks == 5
        assert stats.index_health == "healthy"

    @pytest.mark.asyncio
    async def test_count_memories_safe_with_none(self, session_manager: SessionManager):
        """Test _count_memories_safe with None memory system."""
        session_manager.memory_system = None

        count = await session_manager._count_memories_safe("test_project")

        assert count == 0

    @pytest.mark.asyncio
    async def test_count_memories_safe_with_attribute_error(
        self, session_manager: SessionManager
    ):
        """Test _count_memories_safe handles AttributeError gracefully."""
        # Create a mock memory system with episodic that raises AttributeError
        mock_memory_system = MagicMock()
        mock_memory_system.episodic = MagicMock()
        session_manager.memory_system = mock_memory_system

        # Make count_records raise AttributeError
        session_manager.db_manager.count_records = AsyncMock(
            side_effect=AttributeError("Missing method")
        )

        count = await session_manager._count_memories_safe("test_project")

        assert count == 0

    @pytest.mark.asyncio
    async def test_count_memories_safe_with_general_exception(
        self, session_manager: SessionManager
    ):
        """Test _count_memories_safe handles general exceptions gracefully."""
        # Create a mock memory system
        mock_memory_system = MagicMock()
        mock_memory_system.episodic = MagicMock()
        session_manager.memory_system = mock_memory_system

        # Make count_records raise a general exception
        session_manager.db_manager.count_records = AsyncMock(
            side_effect=Exception("Database error")
        )

        count = await session_manager._count_memories_safe("test_project")

        assert count == 0

    @pytest.mark.asyncio
    async def test_get_project_statistics_public_method(
        self, session_manager, mock_db_manager
    ):
        """Test public get_project_statistics method."""
        # Setup mock data
        mock_db_manager.advanced_filter.return_value = [
            {
                "file_path": "test.py",
                "language": "python",
                "created_at": "2024-01-15T10:30:00",
            }
        ]

        # Call public method
        stats = await session_manager.get_project_statistics("test_project")

        # Verify it returns ProjectStatistics object
        assert stats is not None
        assert hasattr(stats, "total_chunks")
        assert hasattr(stats, "total_files")
        assert hasattr(stats, "index_health")

        # Verify it calls the underlying private method
        assert stats.total_chunks >= 0
        assert stats.index_health in ["empty", "stale", "healthy"]


class TestSessionFixationPrevention:
    """Tests for SEC-005: Session Fixation Prevention.

    Tests the session regeneration functionality that prevents session fixation
    attacks and cross-project data leakage.
    """

    @pytest.mark.asyncio
    async def test_regenerate_session_creates_new_id(
        self, session_manager, mock_db_manager
    ):
        """Test that regenerate_session creates a new session ID."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session
        result = await session_manager.create_session(project_id="test_project")
        old_session_id = result["session_id"]

        # Regenerate session
        new_result = await session_manager.regenerate_session(old_session_id)

        # Verify new session has different ID
        assert new_result["session_id"] != old_session_id
        assert new_result["old_session_id"] == old_session_id
        assert new_result["project_id"] == "test_project"

    @pytest.mark.asyncio
    async def test_regenerate_session_preserves_history_same_project(
        self, session_manager, mock_db_manager
    ):
        """Test that history is preserved when regenerating for same project."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session with history
        result = await session_manager.create_session(project_id="test_project")
        old_session_id = result["session_id"]

        session = session_manager.active_sessions[old_session_id]
        session.add_to_history("test_tool", {"param": "value"})
        session.add_to_history("test_tool2", {"param2": "value2"})

        # Regenerate session for same project
        new_result = await session_manager.regenerate_session(old_session_id)
        new_session_id = new_result["session_id"]

        # Verify history is preserved
        new_session = session_manager.active_sessions[new_session_id]
        assert len(new_session.history) == 2
        assert new_session.history[0]["tool"] == "test_tool"
        assert new_result["project_changed"] is False

    @pytest.mark.asyncio
    async def test_regenerate_session_clears_history_on_project_change(
        self, session_manager, mock_db_manager
    ):
        """Test that history is cleared when changing projects (SEC-005)."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session with history
        result = await session_manager.create_session(project_id="project_a")
        old_session_id = result["session_id"]

        session = session_manager.active_sessions[old_session_id]
        session.add_to_history("sensitive_tool", {"secret": "data"})

        # Regenerate session for different project
        new_result = await session_manager.regenerate_session(
            old_session_id, new_project_id="project_b"
        )
        new_session_id = new_result["session_id"]

        # Verify history is cleared to prevent cross-project data leakage
        new_session = session_manager.active_sessions[new_session_id]
        assert len(new_session.history) == 0
        assert new_result["project_changed"] is True
        assert new_result["project_id"] == "project_b"

    @pytest.mark.asyncio
    async def test_regenerate_session_clears_context_on_project_change(
        self, session_manager, mock_db_manager
    ):
        """Test that context_state is cleared when changing projects."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session with context state
        result = await session_manager.create_session(project_id="project_a")
        old_session_id = result["session_id"]

        session = session_manager.active_sessions[old_session_id]
        session.context_state = {"sensitive_key": "sensitive_value"}

        # Regenerate session for different project
        new_result = await session_manager.regenerate_session(
            old_session_id, new_project_id="project_b"
        )
        new_session_id = new_result["session_id"]

        # Verify context state is cleared
        new_session = session_manager.active_sessions[new_session_id]
        assert new_session.context_state == {}

    @pytest.mark.asyncio
    async def test_regenerate_session_marks_old_session_expired(
        self, session_manager, mock_db_manager
    ):
        """Test that old session is marked as expired after regeneration."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session
        result = await session_manager.create_session(project_id="test_project")
        old_session_id = result["session_id"]

        # Regenerate session
        await session_manager.regenerate_session(old_session_id)

        # Verify old session is no longer in active sessions
        assert old_session_id not in session_manager.active_sessions

    @pytest.mark.asyncio
    async def test_regenerate_session_rejects_nonexistent_session(
        self, session_manager, mock_db_manager
    ):
        """Test that regenerating non-existent session raises error."""
        mock_db_manager.advanced_filter.return_value = []

        # Use valid UUID format
        with pytest.raises(ValueError, match="not found"):
            await session_manager.regenerate_session(
                "00000000-0000-4000-8000-000000000000"
            )

    @pytest.mark.asyncio
    async def test_regenerate_session_rejects_expired_session(
        self, session_manager, mock_db_manager
    ):
        """Test that regenerating expired session raises error."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session
        result = await session_manager.create_session(project_id="test_project")
        old_session_id = result["session_id"]

        # Mark as expired
        session = session_manager.active_sessions[old_session_id]
        session.mark_expired()

        # Try to regenerate
        with pytest.raises(ValueError, match="has expired"):
            await session_manager.regenerate_session(old_session_id)

    @pytest.mark.asyncio
    async def test_regenerate_session_enforces_max_age(
        self, session_manager, mock_db_manager
    ):
        """Test that regeneration is rejected for sessions exceeding max age."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session
        result = await session_manager.create_session(project_id="test_project")
        old_session_id = result["session_id"]

        # Set created_at to 2 hours ago (exceeds default 1 hour max)
        session = session_manager.active_sessions[old_session_id]
        session.created_at = datetime.now() - timedelta(hours=2)

        # Try to regenerate
        with pytest.raises(ValueError, match="exceeds max age"):
            await session_manager.regenerate_session(old_session_id)

    @pytest.mark.asyncio
    async def test_regenerate_session_includes_regeneration_reason(
        self, session_manager, mock_db_manager
    ):
        """Test that regeneration result includes reason."""
        mock_db_manager.advanced_filter.return_value = []

        # Create and regenerate a session
        result = await session_manager.create_session(project_id="test_project")
        old_session_id = result["session_id"]

        new_result = await session_manager.regenerate_session(
            old_session_id, reason="security_refresh"
        )

        assert new_result["regeneration_reason"] == "security_refresh"

    @pytest.mark.asyncio
    async def test_change_project_uses_regenerate_session(
        self, session_manager, mock_db_manager
    ):
        """Test that change_project delegates to regenerate_session."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session
        result = await session_manager.create_session(project_id="project_a")
        old_session_id = result["session_id"]

        # Change project
        new_result = await session_manager.change_project(
            old_session_id, new_project_id="project_b"
        )

        # Verify project change occurred
        assert new_result["project_id"] == "project_b"
        assert new_result["project_changed"] is True
        assert new_result["regeneration_reason"] == "project_change"

    @pytest.mark.asyncio
    async def test_regenerate_session_creates_fresh_log_file(
        self, session_manager, mock_db_manager
    ):
        """Test that regenerated session has new log file path."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session
        result = await session_manager.create_session(project_id="test_project")
        old_session_id = result["session_id"]
        old_log_file = result["log_file"]

        # Regenerate session
        new_result = await session_manager.regenerate_session(old_session_id)

        # Verify new log file path
        assert new_result["log_file"] != old_log_file
        assert new_result["session_id"] in new_result["log_file"]


class TestAuditLogging:
    """Tests for SEC-005: Audit Logging functionality."""

    @pytest.mark.asyncio
    async def test_create_session_emits_audit_log(
        self, session_manager, mock_db_manager
    ):
        """Test that create_session generates audit log entry."""
        mock_db_manager.advanced_filter.return_value = []

        # Create mock event system
        mock_event_system = MagicMock()
        mock_event_system.emit = AsyncMock()
        session_manager.event_system = mock_event_system

        # Create a session
        await session_manager.create_session(
            project_id="test_project", description="Test session"
        )

        # Verify audit event was emitted
        emit_calls = mock_event_system.emit.call_args_list

        # Find the audit.session.created call
        audit_call = None
        for call in emit_calls:
            if call[0][0] == "audit.session.created":
                audit_call = call
                break

        assert audit_call is not None, "audit.session.created event not emitted"

    @pytest.mark.asyncio
    async def test_regenerate_session_emits_audit_log(
        self, session_manager, mock_db_manager
    ):
        """Test that regenerate_session generates audit log entry."""
        mock_db_manager.advanced_filter.return_value = []

        # Create mock event system
        mock_event_system = MagicMock()
        mock_event_system.emit = AsyncMock()
        session_manager.event_system = mock_event_system

        # Create and regenerate a session
        result = await session_manager.create_session(project_id="test_project")
        old_session_id = result["session_id"]

        # Clear previous calls
        mock_event_system.emit.reset_mock()

        await session_manager.regenerate_session(old_session_id, reason="test_reason")

        # Verify audit event was emitted
        emit_calls = mock_event_system.emit.call_args_list

        # Find the audit.session.regenerated call
        audit_call = None
        for call in emit_calls:
            if call[0][0] == "audit.session.regenerated":
                audit_call = call
                break

        assert audit_call is not None, "audit.session.regenerated event not emitted"

    @pytest.mark.asyncio
    async def test_audit_log_without_event_system(
        self, session_manager, mock_db_manager
    ):
        """Test that audit logging works without event system (logs to logger)."""
        mock_db_manager.advanced_filter.return_value = []

        # Ensure no event system
        session_manager.event_system = None

        # Should not raise exception
        await session_manager._audit_log(
            "session.test", session_id="test_id", data="test_data"
        )

    @pytest.mark.asyncio
    async def test_audit_log_includes_timestamp(
        self, session_manager, mock_db_manager, caplog
    ):
        """Test that audit log entries include timestamp."""
        mock_db_manager.advanced_filter.return_value = []
        session_manager.event_system = None

        import logging

        with caplog.at_level(logging.INFO):
            await session_manager._audit_log(
                "session.test_event", session_id="test_123"
            )

        # Verify log was written
        assert "AUDIT: session.test_event" in caplog.text
        assert "session_id" in caplog.text


class TestSessionSecurityValidation:
    """Tests for session ID format validation (SEC-005)."""

    @pytest.mark.asyncio
    async def test_get_session_rejects_invalid_uuid_format(
        self, session_manager, mock_db_manager
    ):
        """Test that get_session rejects invalid session ID formats."""
        mock_db_manager.advanced_filter.return_value = []

        # Try to get session with invalid format
        with pytest.raises(ValueError):
            await session_manager.get_session("invalid-session-id")

    @pytest.mark.asyncio
    async def test_get_session_rejects_sql_injection_attempt(
        self, session_manager, mock_db_manager
    ):
        """Test that get_session rejects SQL injection attempts in session ID."""
        mock_db_manager.advanced_filter.return_value = []

        # Try SQL injection in session ID
        with pytest.raises(ValueError):
            await session_manager.get_session("'; DROP TABLE sessions; --")

    @pytest.mark.asyncio
    async def test_get_session_accepts_valid_uuid(
        self, session_manager, mock_db_manager
    ):
        """Test that get_session accepts valid UUID format."""
        mock_db_manager.advanced_filter.return_value = []

        # Create a session first
        result = await session_manager.create_session(project_id="test_project")
        session_id = result["session_id"]

        # Should not raise exception
        session = await session_manager.get_session(session_id)
        assert session is not None
        assert session.session_id == session_id
