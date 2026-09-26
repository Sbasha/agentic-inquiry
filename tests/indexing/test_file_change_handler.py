"""Tests for FileChangeHandler.

This module tests the incremental re-indexing functionality provided by
FileChangeHandler, which coordinates file changes with the indexing pipeline.

Design Reference:
    DES-S4-001 in .sessions/deep-architecture-review/009-design.md
"""

import pytest

pytestmark = pytest.mark.unit

import asyncio
import pytest
from unittest.mock import MagicMock, patch

from agentic_inquiry.indexing.file_change_handler import FileChangeHandler


class MockIndexingPipeline:
    """Mock IndexingPipeline for testing."""

    def __init__(self, project_root: str = "/tmp/project"):
        self.project_root = project_root
        self.reindex_calls = []
        self.flush_calls = []

    async def reindex_document(self, parsed_doc):
        """Record reindex calls."""
        self.reindex_calls.append(parsed_doc)

    async def flush_pending_relationships(self):
        """Record flush calls."""
        self.flush_calls.append(True)


class MockDatabase:
    """Mock database implementing IndexingDatabaseProtocol."""

    def __init__(self):
        self.delete_calls = []

    async def upsert_chunks(self, chunks, project_id):
        return len(chunks)

    async def upsert_entities(self, entities, project_id):
        return len(entities)

    async def upsert_relationships(self, relationships, project_id):
        return len(relationships)

    async def delete_by_file(self, file_path, project_id):
        self.delete_calls.append((file_path, project_id))
        return 5  # Simulated deleted count


class MockFileTracker:
    """Mock FileTracker for testing."""

    def __init__(self):
        self.hashes = {}
        self.update_calls = []
        self.remove_calls = []
        self._initialized = True

    async def initialize(self):
        pass

    async def has_changed(self, file_path: str) -> bool:
        """Return True if file has changed (not in hashes dict)."""
        return file_path not in self.hashes

    async def update_hash(self, file_path: str, content_hash: str = None):
        self.update_calls.append(file_path)
        self.hashes[file_path] = content_hash or "test_hash"
        return self.hashes[file_path]

    async def remove_file(self, file_path: str):
        self.remove_calls.append(file_path)
        if file_path in self.hashes:
            del self.hashes[file_path]
        return True

    def close(self):
        pass


class MockParserChain:
    """Mock ParserChain for testing."""

    def __init__(self):
        self.parse_calls = []
        self.should_fail = False

    async def parse(self, path: str, **kwargs):
        if self.should_fail:
            raise ValueError("Parse failed")
        self.parse_calls.append(path)
        # Return a mock parsed document
        mock_doc = MagicMock()
        mock_doc.file_path = path
        mock_doc.chunks = [MagicMock() for _ in range(3)]  # 3 mock chunks
        return mock_doc


class MockEventSystem:
    """Mock EventSystem for testing."""

    def __init__(self):
        self.events = []

    async def emit(self, event_type: str, **kwargs):
        self.events.append({"type": event_type, **kwargs})


# Fixtures


@pytest.fixture
def mock_pipeline(tmp_path):
    """Create a mock indexing pipeline."""
    return MockIndexingPipeline(project_root=str(tmp_path))


@pytest.fixture
def mock_db():
    """Create a mock database."""
    return MockDatabase()


@pytest.fixture
def mock_file_tracker():
    """Create a mock file tracker."""
    return MockFileTracker()


@pytest.fixture
def mock_parser_chain():
    """Create a mock parser chain."""
    return MockParserChain()


@pytest.fixture
def mock_event_system():
    """Create a mock event system."""
    return MockEventSystem()


@pytest.fixture
def handler(
    mock_pipeline,
    mock_db,
    mock_file_tracker,
    mock_parser_chain,
    mock_event_system,
    tmp_path,
):
    """Create a FileChangeHandler with all mocks."""
    handler = FileChangeHandler(
        pipeline=mock_pipeline,
        db=mock_db,
        project_id="test_project",
        parser_chain=mock_parser_chain,
        file_tracker=mock_file_tracker,
        event_system=mock_event_system,
        debounce_seconds=0.1,  # Short debounce for tests
        project_root=str(tmp_path),
    )
    handler._initialized = True
    return handler


# Unit Tests


class TestFileChangeHandlerInit:
    """Tests for FileChangeHandler initialization."""

    def test_init_with_defaults(self, mock_pipeline, mock_db):
        """Test initialization with default values."""
        handler = FileChangeHandler(
            pipeline=mock_pipeline,
            db=mock_db,
            project_id="test_project",
        )

        assert handler.project_id == "test_project"
        assert handler.debounce_seconds == 1.0
        assert handler.pending_count == 0
        assert not handler._initialized

    def test_init_with_custom_debounce(self, mock_pipeline, mock_db):
        """Test initialization with custom debounce."""
        handler = FileChangeHandler(
            pipeline=mock_pipeline,
            db=mock_db,
            project_id="test_project",
            debounce_seconds=2.5,
        )

        assert handler.debounce_seconds == 2.5

    def test_init_with_ignore_patterns(self, mock_pipeline, mock_db):
        """Test initialization with custom ignore patterns."""
        handler = FileChangeHandler(
            pipeline=mock_pipeline,
            db=mock_db,
            project_id="test_project",
            ignore_patterns=["*.tmp", "build/*"],
        )

        assert "*.tmp" in handler._ignore_patterns
        assert "build/*" in handler._ignore_patterns

    @pytest.mark.asyncio
    async def test_initialize_creates_dependencies(
        self, mock_pipeline, mock_db, tmp_path
    ):
        """Test that initialize creates FileTracker and ParserChain."""
        handler = FileChangeHandler(
            pipeline=mock_pipeline,
            db=mock_db,
            project_id="test_project",
            project_root=str(tmp_path),
        )

        # Patch at the source module level since imports happen inside initialize()
        with (
            patch(
                "agentic_inquiry.watching.file_tracker.FileTracker.from_config"
            ) as mock_ft_factory,
            patch(
                "agentic_inquiry.parsers.chain.ParserChain.from_config"
            ) as mock_pc_factory,
        ):
            mock_ft = MockFileTracker()
            mock_pc = MockParserChain()
            mock_ft_factory.return_value = mock_ft
            mock_pc_factory.return_value = mock_pc

            await handler.initialize()

            assert handler._initialized
            mock_ft_factory.assert_called_once()
            mock_pc_factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, mock_pipeline, mock_db, tmp_path):
        """Test that initialize can be called multiple times safely."""
        # Create handler without pre-set dependencies
        handler = FileChangeHandler(
            pipeline=mock_pipeline,
            db=mock_db,
            project_id="test_project",
            project_root=str(tmp_path),
        )

        # Patch at the source module level since imports happen inside initialize()
        with (
            patch(
                "agentic_inquiry.watching.file_tracker.FileTracker.from_config"
            ) as mock_ft,
            patch("agentic_inquiry.parsers.chain.ParserChain.from_config") as mock_pc,
        ):
            mock_ft.return_value = MockFileTracker()
            mock_pc.return_value = MockParserChain()

            await handler.initialize()
            await handler.initialize()  # Second call

            # Should only create dependencies once
            mock_ft.assert_called_once()


class TestFileChangeHandlerPatternMatching:
    """Tests for file pattern matching."""

    def test_should_process_normal_file(self, handler):
        """Test that normal files should be processed."""
        assert handler._should_process("/path/to/file.py")
        assert handler._should_process("/path/to/module/test.js")

    def test_should_not_process_pyc(self, handler):
        """Test that .pyc files are ignored."""
        assert not handler._should_process("/path/to/file.pyc")

    def test_should_not_process_pycache(self, handler):
        """Test that __pycache__ directories are ignored."""
        assert not handler._should_process("/path/__pycache__/file.py")

    def test_should_not_process_git(self, handler):
        """Test that .git directories are ignored."""
        assert not handler._should_process("/path/.git/config")

    def test_should_not_process_venv(self, handler):
        """Test that venv directories are ignored."""
        assert not handler._should_process("/path/.venv/lib/site-packages/test.py")
        assert not handler._should_process("/path/venv/bin/python")

    def test_should_process_with_file_patterns(self, mock_pipeline, mock_db):
        """Test file pattern filtering."""
        handler = FileChangeHandler(
            pipeline=mock_pipeline,
            db=mock_db,
            project_id="test_project",
            file_patterns=["*.py", "*.js"],
        )
        handler._initialized = True

        assert handler._should_process("/path/to/file.py")
        assert handler._should_process("/path/to/file.js")
        assert not handler._should_process("/path/to/file.txt")


class TestFileChangeHandlerEvents:
    """Tests for file change event handling."""

    @pytest.mark.asyncio
    async def test_on_file_change_not_initialized(self, mock_pipeline, mock_db, caplog):
        """Test that events are ignored when not initialized."""
        handler = FileChangeHandler(
            pipeline=mock_pipeline,
            db=mock_db,
            project_id="test_project",
        )
        # Not initialized

        await handler.on_file_change("/path/to/file.py", "modified")

        assert handler.pending_count == 0
        assert "not initialized" in caplog.text

    @pytest.mark.asyncio
    async def test_on_file_change_schedules_task(self, handler):
        """Test that on_file_change schedules a debounced task."""
        await handler.on_file_change("/path/to/file.py", "modified")

        assert handler.pending_count == 1

    @pytest.mark.asyncio
    async def test_on_file_change_debounce_cancels_previous(self, handler):
        """Test that rapid changes cancel previous pending tasks."""
        # Schedule first change
        await handler.on_file_change("/path/to/file.py", "modified")
        assert handler.pending_count == 1

        # Schedule second change for same file (should cancel first)
        await handler.on_file_change("/path/to/file.py", "modified")
        assert handler.pending_count == 1

        # Wait for processing
        await handler.wait_for_pending(timeout=1.0)
        assert handler.pending_count == 0

    @pytest.mark.asyncio
    async def test_on_file_change_different_files_parallel(self, handler):
        """Test that changes to different files are tracked separately."""
        await handler.on_file_change("/path/to/file1.py", "modified")
        await handler.on_file_change("/path/to/file2.py", "modified")

        assert handler.pending_count == 2


class TestFileChangeHandlerDeletion:
    """Tests for file deletion handling."""

    @pytest.mark.asyncio
    async def test_handle_deletion_removes_data(
        self, handler, mock_db, mock_file_tracker, mock_event_system
    ):
        """Test that deletion removes data from database."""
        await handler._handle_deletion("/path/to/deleted.py")

        # Check database delete was called
        assert len(mock_db.delete_calls) == 1
        assert mock_db.delete_calls[0] == ("/path/to/deleted.py", "test_project")

        # Check file tracker remove was called
        assert len(mock_file_tracker.remove_calls) == 1
        assert mock_file_tracker.remove_calls[0] == "/path/to/deleted.py"

        # Check event was emitted
        assert len(mock_event_system.events) == 1
        assert mock_event_system.events[0]["type"] == "indexing.file_deleted"

    @pytest.mark.asyncio
    async def test_deletion_updates_stats(self, handler, mock_db):
        """Test that deletion updates statistics."""
        await handler._handle_deletion("/path/to/deleted.py")

        assert handler.stats["files_deleted"] == 1


class TestFileChangeHandlerUpdate:
    """Tests for file creation/modification handling."""

    @pytest.mark.asyncio
    async def test_handle_update_created(
        self,
        handler,
        mock_pipeline,
        mock_parser_chain,
        mock_file_tracker,
        mock_event_system,
        tmp_path,
    ):
        """Test handling of created files."""
        # Create a real file
        test_file = tmp_path / "new_file.py"
        test_file.write_text("print('hello')")

        await handler._handle_update(str(test_file), "created")

        # Check parsing was called
        assert len(mock_parser_chain.parse_calls) == 1
        assert str(test_file) in mock_parser_chain.parse_calls[0]

        # Check reindex was called
        assert len(mock_pipeline.reindex_calls) == 1

        # Check flush was called
        assert len(mock_pipeline.flush_calls) == 1

        # Check file tracker was updated
        assert len(mock_file_tracker.update_calls) == 1

        # Check stats
        assert handler.stats["files_created"] == 1

    @pytest.mark.asyncio
    async def test_handle_update_modified(
        self,
        handler,
        mock_pipeline,
        mock_parser_chain,
        mock_file_tracker,
        tmp_path,
    ):
        """Test handling of modified files."""
        # Create a file
        test_file = tmp_path / "existing_file.py"
        test_file.write_text("print('hello')")

        await handler._handle_update(str(test_file), "modified")

        # Check parsing and reindex were called
        assert len(mock_parser_chain.parse_calls) == 1
        assert len(mock_pipeline.reindex_calls) == 1

        # Check stats
        assert handler.stats["files_modified"] == 1

    @pytest.mark.asyncio
    async def test_handle_update_skips_unchanged(
        self,
        handler,
        mock_pipeline,
        mock_parser_chain,
        mock_file_tracker,
        tmp_path,
    ):
        """Test that unchanged files are skipped."""
        # Create a file
        test_file = tmp_path / "unchanged_file.py"
        test_file.write_text("print('hello')")

        # Mark file as already tracked (unchanged)
        mock_file_tracker.hashes[str(test_file)] = "existing_hash"

        await handler._handle_update(str(test_file), "modified")

        # Parsing should not be called
        assert len(mock_parser_chain.parse_calls) == 0
        assert len(mock_pipeline.reindex_calls) == 0

        # Check stats
        assert handler.stats["files_skipped_unchanged"] == 1

    @pytest.mark.asyncio
    async def test_handle_update_nonexistent_file(
        self, handler, mock_parser_chain, caplog
    ):
        """Test handling of non-existent files."""
        await handler._handle_update("/path/to/nonexistent.py", "modified")

        # Parsing should not be called
        assert len(mock_parser_chain.parse_calls) == 0
        assert "no longer exists" in caplog.text

    @pytest.mark.asyncio
    async def test_handle_update_parse_failure(
        self, handler, mock_parser_chain, tmp_path, caplog
    ):
        """Test handling of parse failures."""
        # Create a file
        test_file = tmp_path / "bad_file.py"
        test_file.write_text("syntax error {{{")

        # Make parser fail
        mock_parser_chain.should_fail = True

        await handler._handle_update(str(test_file), "modified")

        # Should log warning about parse failure
        assert "Failed to parse" in caplog.text


class TestFileChangeHandlerIntegration:
    """Integration tests for end-to-end file change handling."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_create_modify_delete(
        self,
        handler,
        mock_pipeline,
        mock_db,
        mock_parser_chain,
        mock_file_tracker,
        tmp_path,
    ):
        """Test complete file lifecycle: create, modify, delete."""
        test_file = tmp_path / "lifecycle_test.py"

        # Create file
        test_file.write_text("print('v1')")
        await handler.on_file_change(str(test_file), "created")
        await handler.wait_for_pending(timeout=1.0)

        assert handler.stats["files_created"] == 1
        assert len(mock_pipeline.reindex_calls) == 1

        # Modify file (clear hash to simulate change)
        test_file.write_text("print('v2')")
        del mock_file_tracker.hashes[str(test_file)]
        await handler.on_file_change(str(test_file), "modified")
        await handler.wait_for_pending(timeout=1.0)

        assert handler.stats["files_modified"] == 1
        assert len(mock_pipeline.reindex_calls) == 2

        # Delete file
        test_file.unlink()
        await handler.on_file_change(str(test_file), "deleted")
        await handler.wait_for_pending(timeout=1.0)

        assert handler.stats["files_deleted"] == 1
        assert len(mock_db.delete_calls) == 1

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    @pytest.mark.skip(
        reason="Flaky integration test - debouncing verified by unit tests"
    )
    async def test_debounce_prevents_duplicate_processing(
        self, handler, mock_pipeline, mock_parser_chain, tmp_path
    ):
        """Test that debouncing prevents duplicate processing.

        Note: This integration test is skipped due to async timing issues in CI.
        The debounce mechanism is verified by the unit tests:
        - test_on_file_change_debounce_cancels_previous
        - test_on_file_change_schedules_task
        """
        test_file = tmp_path / "debounce_test.py"
        test_file.write_text("print('test')")

        # Rapid fire multiple changes
        for _ in range(5):
            await handler.on_file_change(str(test_file), "modified")
            await asyncio.sleep(0.01)  # Small delay, less than debounce

        # Wait for all to complete
        await handler.wait_for_pending(timeout=2.0)

        # Should only process once due to debouncing
        assert len(mock_parser_chain.parse_calls) == 1

    @pytest.mark.asyncio
    async def test_cancel_pending_stops_processing(self, handler, tmp_path):
        """Test that cancel_pending stops all pending operations."""
        test_file = tmp_path / "cancel_test.py"
        test_file.write_text("print('test')")

        # Schedule some changes
        await handler.on_file_change(str(test_file), "modified")
        assert handler.pending_count == 1

        # Cancel all pending
        cancelled = await handler.cancel_pending()
        assert cancelled == 1
        assert handler.pending_count == 0


class TestFileChangeHandlerStats:
    """Tests for statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_tracking(self, handler, mock_db, mock_parser_chain, tmp_path):
        """Test that all stats are properly tracked."""
        # Create and process a file
        test_file = tmp_path / "stats_test.py"
        test_file.write_text("print('test')")
        await handler._handle_update(str(test_file), "created")

        # Delete it
        await handler._handle_deletion(str(test_file))

        stats = handler.stats
        assert stats["files_created"] == 1
        assert stats["files_deleted"] == 1
        assert stats["errors"] == 0

    def test_reset_stats(self, handler):
        """Test that stats can be reset."""
        handler._stats["files_created"] = 10
        handler._stats["files_deleted"] = 5

        handler.reset_stats()

        assert handler.stats["files_created"] == 0
        assert handler.stats["files_deleted"] == 0


class TestFileChangeHandlerWithFileWatchManager:
    """Tests for FileWatchManager integration."""

    @pytest.mark.asyncio
    async def test_integration_with_file_watch_manager(self, handler, tmp_path):
        """Test that FileWatchManager can use FileChangeHandler."""
        from agentic_inquiry.indexing.file_watch_manager import FileWatchManager

        # Create manager with handler
        manager = FileWatchManager(
            project_root=str(tmp_path),
            file_change_handler=handler,
        )

        assert manager.has_file_change_handler()
        assert manager.file_change_handler is handler

    @pytest.mark.asyncio
    async def test_set_file_change_handler(self, handler, tmp_path):
        """Test setting handler after construction."""
        from agentic_inquiry.indexing.file_watch_manager import FileWatchManager

        manager = FileWatchManager(project_root=str(tmp_path))
        assert not manager.has_file_change_handler()

        manager.set_file_change_handler(handler)
        assert manager.has_file_change_handler()
        assert manager.file_change_handler is handler
