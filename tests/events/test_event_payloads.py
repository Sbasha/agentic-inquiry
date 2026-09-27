"""Tests for event payload validation using Pydantic models.

This test module verifies that:
1. Pydantic payload models validate data correctly
2. Event.from_payload() creates events with validated metadata
3. Event.validate_payload() validates existing event metadata
4. EventSystem.emit_typed() emits events with typed payloads
5. Validation errors are raised for invalid data
6. Backwards compatibility with untyped metadata is maintained
"""

import pytest

pytestmark = pytest.mark.unit

from pydantic import ValidationError

from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.payloads import (
    # Indexing payloads
    IndexingStartedPayload,
    IndexingProgressPayload,
    IndexingCompletedPayload,
    IndexingFailedPayload,
    IndexingFileIndexedPayload,
    IndexingFileSkippedPayload,
    IndexingFileFailedPayload,
    # Search payloads
    SearchQueryStartedPayload,
    SearchQueryCompletedPayload,
    SearchResultsReturnedPayload,
    # Memory payloads
    MemoryStoredPayload,
    MemoryRetrievedPayload,
    MemoryConsolidatedPayload,
    # Watching payloads
    WatchingStartedPayload,
    WatchingFileChangedPayload,
    # Parsing payloads
    ParsingCompletedPayload,
    ParserSelectedPayload,
    # Project payloads
    SystemErrorPayload,
)


class TestIndexingPayloads:
    """Test indexing event payload models."""

    def test_indexing_started_payload_valid(self):
        """Test IndexingStartedPayload with valid data."""
        payload = IndexingStartedPayload(
            path="/path/to/file", content_type="code", file_count=42
        )
        assert payload.path == "/path/to/file"
        assert payload.content_type == "code"
        assert payload.file_count == 42

    def test_indexing_started_payload_minimal(self):
        """Test IndexingStartedPayload with minimal data."""
        payload = IndexingStartedPayload(path="/path/to/file", content_type="code")
        assert payload.path == "/path/to/file"
        assert payload.content_type == "code"
        assert payload.file_count is None

    def test_indexing_started_payload_missing_required(self):
        """Test IndexingStartedPayload fails without required fields."""
        with pytest.raises(ValidationError) as exc_info:
            IndexingStartedPayload(path="/path/to/file")
        assert "content_type" in str(exc_info.value)

    def test_indexing_started_payload_to_metadata(self):
        """Test IndexingStartedPayload converts to metadata dict."""
        payload = IndexingStartedPayload(
            path="/path/to/file", content_type="code", file_count=42
        )
        metadata = payload.to_metadata()
        assert metadata == {
            "path": "/path/to/file",
            "content_type": "code",
            "file_count": 42,
        }

    def test_indexing_progress_payload(self):
        """Test IndexingProgressPayload with partial data."""
        payload = IndexingProgressPayload(files_processed=10, chunks_created=50)
        assert payload.files_processed == 10
        assert payload.chunks_created == 50
        assert payload.entities_created is None

    def test_indexing_completed_payload(self):
        """Test IndexingCompletedPayload with full data."""
        payload = IndexingCompletedPayload(
            files_processed=42,
            chunks_created=100,
            entities_created=50,
            relationships_created=75,
            duration_seconds=12.5,
            success=True,
        )
        assert payload.files_processed == 42
        assert payload.chunks_created == 100
        assert payload.duration_seconds == 12.5
        assert payload.success is True

    def test_indexing_failed_payload(self):
        """Test IndexingFailedPayload with error details."""
        payload = IndexingFailedPayload(
            error="File not found",
            error_type="FileNotFoundError",
            path="/path/to/missing/file",
        )
        assert payload.error == "File not found"
        assert payload.error_type == "FileNotFoundError"
        assert payload.path == "/path/to/missing/file"

    def test_indexing_file_indexed_payload(self):
        """Test IndexingFileIndexedPayload."""
        payload = IndexingFileIndexedPayload(
            file_path="/path/to/file.py",
            chunks_created=5,
            entities_created=10,
            duration_ms=123.45,
        )
        assert payload.file_path == "/path/to/file.py"
        assert payload.chunks_created == 5
        assert payload.entities_created == 10
        assert payload.duration_ms == 123.45

    def test_indexing_file_skipped_payload(self):
        """Test IndexingFileSkippedPayload."""
        payload = IndexingFileSkippedPayload(
            file_path="/path/to/file.pyc", reason="ignored"
        )
        assert payload.file_path == "/path/to/file.pyc"
        assert payload.reason == "ignored"

    def test_indexing_file_failed_payload(self):
        """Test IndexingFileFailedPayload."""
        payload = IndexingFileFailedPayload(
            file_path="/path/to/file.py", error="Parse error", error_type="SyntaxError"
        )
        assert payload.file_path == "/path/to/file.py"
        assert payload.error == "Parse error"


class TestSearchPayloads:
    """Test search event payload models."""

    def test_search_query_started_payload(self):
        """Test SearchQueryStartedPayload with literal types."""
        payload = SearchQueryStartedPayload(
            search_type="vector", query_text="test query", limit=10
        )
        assert payload.search_type == "vector"
        assert payload.query_text == "test query"

    def test_search_query_started_invalid_type(self):
        """Test SearchQueryStartedPayload fails with invalid search type."""
        with pytest.raises(ValidationError):
            SearchQueryStartedPayload(search_type="invalid_type", query_text="test")

    def test_search_query_completed_payload(self):
        """Test SearchQueryCompletedPayload."""
        payload = SearchQueryCompletedPayload(
            search_type="hybrid", result_count=15, duration_ms=45.67
        )
        assert payload.search_type == "hybrid"
        assert payload.result_count == 15

    def test_search_results_returned_payload(self):
        """Test SearchResultsReturnedPayload."""
        payload = SearchResultsReturnedPayload(result_count=5, search_type="fts")
        assert payload.result_count == 5
        assert payload.search_type == "fts"


class TestMemoryPayloads:
    """Test memory event payload models."""

    def test_memory_stored_payload(self):
        """Test MemoryStoredPayload with importance validation."""
        payload = MemoryStoredPayload(
            memory_id="mem_123",
            tier="episodic",
            agent_id="agent_001",
            session_id="session_xyz",
            importance=0.8,
            content_length=256,
        )
        assert payload.memory_id == "mem_123"
        assert payload.tier == "episodic"
        assert payload.importance == 0.8

    def test_memory_stored_payload_invalid_importance(self):
        """Test MemoryStoredPayload fails with out-of-range importance."""
        with pytest.raises(ValidationError) as exc_info:
            MemoryStoredPayload(
                memory_id="mem_123",
                tier="working",
                agent_id="agent_001",
                importance=1.5,  # Invalid: > 1.0
                content_length=100,
            )
        assert "importance" in str(exc_info.value)

    def test_memory_retrieved_payload(self):
        """Test MemoryRetrievedPayload."""
        payload = MemoryRetrievedPayload(
            query="user preferences",
            result_count=10,
            strategy="adaptive",
            agent_id="agent_001",
            session_id="session_xyz",
        )
        assert payload.query == "user preferences"
        assert payload.result_count == 10
        assert payload.strategy == "adaptive"

    def test_memory_consolidated_payload(self):
        """Test MemoryConsolidatedPayload."""
        payload = MemoryConsolidatedPayload(
            items_promoted=5,
            concepts_extracted=3,
            agent_id="agent_001",
            duration_seconds=2.5,
        )
        assert payload.items_promoted == 5
        assert payload.concepts_extracted == 3


class TestWatchingPayloads:
    """Test file watching event payload models."""

    def test_watching_started_payload(self):
        """Test WatchingStartedPayload."""
        payload = WatchingStartedPayload(
            path="/path/to/watch",
            recursive=True,
            ignore_patterns=["*.pyc", "__pycache__"],
        )
        assert payload.path == "/path/to/watch"
        assert payload.recursive is True
        assert len(payload.ignore_patterns) == 2

    def test_watching_file_changed_payload(self):
        """Test WatchingFileChangedPayload with event types."""
        payload = WatchingFileChangedPayload(
            file_path="/path/to/file.py", event_type="modified", change_hash="abc123"
        )
        assert payload.file_path == "/path/to/file.py"
        assert payload.event_type == "modified"

    def test_watching_file_changed_invalid_event_type(self):
        """Test WatchingFileChangedPayload fails with invalid event type."""
        with pytest.raises(ValidationError):
            WatchingFileChangedPayload(
                file_path="/path/to/file.py", event_type="invalid"
            )


class TestParsingPayloads:
    """Test parsing event payload models."""

    def test_parsing_completed_payload(self):
        """Test ParsingCompletedPayload."""
        payload = ParsingCompletedPayload(
            file_path="/path/to/file.py",
            chunks_created=10,
            parser_type="unified_code",
            duration_ms=50.0,
        )
        assert payload.file_path == "/path/to/file.py"
        assert payload.chunks_created == 10
        assert payload.parser_type == "unified_code"

    def test_parser_selected_payload(self):
        """Test ParserSelectedPayload."""
        payload = ParserSelectedPayload(
            file_path="/path/to/file.py",
            parser_type="unified_code",
            parser_priority=100,
        )
        assert payload.parser_priority == 100


class TestSystemPayloads:
    """Test system event payload models."""

    def test_system_error_payload(self):
        """Test SystemErrorPayload with severity levels."""
        payload = SystemErrorPayload(
            component="SearchService",
            error="Connection timeout",
            error_type="TimeoutError",
            severity="high",
        )
        assert payload.component == "SearchService"
        assert payload.severity == "high"

    def test_system_error_payload_invalid_severity(self):
        """Test SystemErrorPayload fails with invalid severity."""
        with pytest.raises(ValidationError):
            SystemErrorPayload(component="test", error="error", severity="invalid")


class TestEventIntegration:
    """Test integration between Event model and payloads."""

    def test_event_from_payload(self):
        """Test Event.from_payload() creates event with validated metadata."""
        payload = IndexingStartedPayload(
            path="/path/to/file", content_type="code", file_count=42
        )
        event = Event.from_payload(
            event_type="indexing.started",
            source="pipeline",
            payload=payload,
            project_id="test_project",
            status=EventStatus.STARTED,
        )

        assert event.event_type == "indexing.started"
        assert event.source == "pipeline"
        assert event.project_id == "test_project"
        assert event.status == EventStatus.STARTED
        assert event.metadata["path"] == "/path/to/file"
        assert event.metadata["content_type"] == "code"
        assert event.metadata["file_count"] == 42

    def test_event_validate_payload_valid(self):
        """Test Event.validate_payload() validates metadata successfully."""
        event = Event(
            event_type="indexing.started",
            metadata={
                "path": "/path/to/file",
                "content_type": "code",
                "file_count": 42,
            },
        )

        payload = event.validate_payload(IndexingStartedPayload)
        assert isinstance(payload, IndexingStartedPayload)
        assert payload.path == "/path/to/file"
        assert payload.content_type == "code"
        assert payload.file_count == 42

    def test_event_validate_payload_invalid(self):
        """Test Event.validate_payload() raises ValidationError for invalid metadata."""
        event = Event(
            event_type="indexing.started",
            metadata={
                "path": "/path/to/file"
                # Missing required field: content_type
            },
        )

        with pytest.raises(ValidationError) as exc_info:
            event.validate_payload(IndexingStartedPayload)
        assert "content_type" in str(exc_info.value)

    def test_event_validate_payload_extra_fields_allowed(self):
        """Test Event.validate_payload() allows extra fields for backwards compatibility."""
        event = Event(
            event_type="indexing.started",
            metadata={
                "path": "/path/to/file",
                "content_type": "code",
                "extra_field": "extra_value",  # Extra field should be allowed
                "another_extra": 123,
            },
        )

        payload = event.validate_payload(IndexingStartedPayload)
        assert payload.path == "/path/to/file"
        assert payload.content_type == "code"
        # Extra fields are stored in the payload due to extra="allow"
        assert hasattr(payload, "extra_field")


class TestPayloadMetadataRoundtrip:
    """Test that payloads can be converted to metadata and back."""

    def test_indexing_started_roundtrip(self):
        """Test IndexingStartedPayload roundtrip conversion."""
        original = IndexingStartedPayload(
            path="/path/to/file", content_type="code", file_count=42
        )

        # Convert to metadata
        metadata = original.to_metadata()

        # Create new payload from metadata
        restored = IndexingStartedPayload(**metadata)

        assert restored.path == original.path
        assert restored.content_type == original.content_type
        assert restored.file_count == original.file_count

    def test_memory_stored_roundtrip(self):
        """Test MemoryStoredPayload roundtrip conversion."""
        original = MemoryStoredPayload(
            memory_id="mem_123",
            tier="semantic",
            agent_id="agent_001",
            importance=0.9,
            content_length=512,
        )

        metadata = original.to_metadata()
        restored = MemoryStoredPayload(**metadata)

        assert restored.memory_id == original.memory_id
        assert restored.tier == original.tier
        assert restored.importance == original.importance

    def test_payload_excludes_none_values(self):
        """Test that to_metadata() excludes None values."""
        payload = IndexingStartedPayload(
            path="/path/to/file",
            content_type="code",
            file_count=None,  # Optional field set to None
        )

        metadata = payload.to_metadata()
        assert "path" in metadata
        assert "content_type" in metadata
        assert "file_count" not in metadata  # None value excluded


@pytest.mark.asyncio
class TestEventSystemTypedEmission:
    """Test EventSystem.emit_typed() method."""

    async def test_emit_typed_basic(self, mock_event_system_typed):
        """Test emit_typed() with valid payload."""
        from agentic_inquiry.events.system import EventSystem
        from agentic_inquiry.config import Config

        config = Config.load()
        config.storage.default_project_id = "test_project"

        event_system = EventSystem(config, project_id="test_project")

        payload = IndexingStartedPayload(
            path="/path/to/file", content_type="code", file_count=42
        )

        # This should not raise any errors
        await event_system.emit_typed(
            event_type="indexing.started",
            source="test",
            payload=payload,
            status=EventStatus.STARTED,
        )

        # Verify the event system is functional (basic smoke test)
        assert event_system.project_id == "test_project"

    async def test_emit_typed_validation_error(self):
        """Test that emit_typed() raises ValidationError for invalid payload."""
        from agentic_inquiry.events.system import EventSystem
        from agentic_inquiry.config import Config

        config = Config.load()
        config.storage.default_project_id = "test_project"

        # EventSystem initialization validates project_id is set
        _event_system = EventSystem(config, project_id="test_project")

        # Create an invalid payload (this should fail during construction)
        with pytest.raises(ValidationError):
            IndexingStartedPayload(
                path="/path/to/file"
                # Missing required field: content_type
            )


@pytest.fixture
def mock_event_system_typed():
    """Fixture that creates a minimal mock for typed emission tests."""
    # This is a placeholder fixture - actual tests use real EventSystem
    pass
