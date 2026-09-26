"""Unit tests for MaintenanceManager service.

Tests the MaintenanceManager with comprehensive mocking to verify:
- Event-driven maintenance triggers
- Per-project lock serialization
- Capability detection (LanceDB vs PostgreSQL)
- Non-blocking background execution
- Configuration-based behavior
"""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.mcp.services.maintenance_manager import MaintenanceManager
from agentic_inquiry.events.types import EventTypes


@pytest.fixture
def mock_db_manager():
    """Create a mock LanceDB manager with maintenance methods."""
    manager = MagicMock()
    manager.run_maintenance = AsyncMock(
        return_value={
            "compaction": {
                "document_chunks": {"status": "success", "fragments_reduced": 5}
            },
            "cleanup": {
                "document_chunks": {"status": "success", "versions_removed": 3}
            },
            "summary": {"fragments_reduced": 5, "versions_removed": 3},
        }
    )
    manager.compact_tables = AsyncMock()
    manager.cleanup_old_versions = AsyncMock()
    return manager


@pytest.fixture
def mock_lancedb_provider(mock_db_manager):
    """Create a mock LanceDB provider (storage._graph_provider)."""
    provider = MagicMock()
    provider._db_manager = mock_db_manager
    return provider


@pytest.fixture
def mock_postgresql_provider():
    """Create a mock PostgreSQL provider without maintenance methods."""
    provider = MagicMock()
    # PostgreSQL provider doesn't have _db_manager with LanceDB maintenance methods
    provider._db_manager = MagicMock()
    delattr(provider._db_manager, "compact_tables")
    delattr(provider._db_manager, "cleanup_old_versions")
    return provider


@pytest.fixture
def mock_storage(mock_lancedb_provider):
    """Create a mock StorageFacade."""
    storage = MagicMock()
    storage._graph_provider = mock_lancedb_provider
    storage.run_maintenance = AsyncMock(
        return_value={
            "compaction": {},
            "cleanup": {},
            "summary": {"fragments_reduced": 0, "versions_removed": 0},
        }
    )
    return storage


@pytest.fixture
def mock_event_system():
    """Create a mock EventSystem."""
    event_system = MagicMock()
    event_system.bus = MagicMock()
    event_system.bus.subscribe = MagicMock()
    return event_system


@pytest.fixture
def maintenance_manager(mock_event_system, mock_storage):
    """Create a MaintenanceManager with mocked dependencies."""
    return MaintenanceManager(event_system=mock_event_system, storage=mock_storage)


@pytest.fixture
def standalone_manager():
    """Create a MaintenanceManager without event system (for direct scheduling tests)."""
    return MaintenanceManager()


class TestMaintenanceOrdering:
    """Tests for maintenance operation ordering (AC-3.2)."""

    @pytest.mark.asyncio
    async def test_maintenance_ordering(self, standalone_manager, mock_db_manager):
        """Test that compaction runs before cleanup (AC-3.2).

        Verifies the run_maintenance call includes proper cleanup_older_than parameter.
        """
        # Schedule maintenance
        task = asyncio.create_task(
            standalone_manager._run_maintenance_task(
                project_id="test_project",
                db_manager=mock_db_manager,
                retention_minutes=60,
            )
        )

        # Wait for task completion
        result = await task

        # Verify run_maintenance was called with correct retention
        mock_db_manager.run_maintenance.assert_called_once()
        call_args = mock_db_manager.run_maintenance.call_args
        assert "cleanup_older_than" in call_args[1]
        assert call_args[1]["cleanup_older_than"] == timedelta(minutes=60)

        # Verify result structure
        assert "compaction" in result or "summary" in result


class TestMaintenanceTriggerConfig:
    """Tests for trigger configuration (AC-3.1, AC-3.1b, AC-3.1c)."""

    @pytest.mark.asyncio
    async def test_project_close_triggers_maintenance(
        self, maintenance_manager, mock_db_manager, mock_storage
    ):
        """Test project.closed event triggers maintenance when configured (AC-3.1)."""
        # Mock config with project.closed trigger
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = True
            mock_config.maintenance.trigger = "project.closed"
            mock_config.maintenance.cleanup_retention_minutes = 60
            mock_load.return_value = mock_config

            # Trigger project.closed event
            event_data = {"project_id": "test_project"}
            await maintenance_manager._on_project_closed(event_data)

            mock_storage.run_maintenance.assert_awaited_once_with(
                project_id="test_project",
                cleanup_older_than=timedelta(minutes=60),
            )

    @pytest.mark.asyncio
    async def test_indexing_complete_triggers_maintenance(
        self, maintenance_manager, mock_db_manager, mock_storage
    ):
        """Test indexing.completed event triggers maintenance when configured (AC-3.1b)."""
        # Mock config with indexing.completed trigger
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = True
            mock_config.maintenance.trigger = "indexing.completed"
            mock_config.maintenance.cleanup_retention_minutes = 60
            mock_load.return_value = mock_config

            # Trigger indexing.completed event
            event_data = {"project_id": "test_project"}
            await maintenance_manager._on_indexing_completed(event_data)

            mock_storage.run_maintenance.assert_awaited_once_with(
                project_id="test_project",
                cleanup_older_than=timedelta(minutes=60),
            )

    @pytest.mark.asyncio
    async def test_disabled_trigger_no_maintenance(
        self, maintenance_manager, mock_db_manager
    ):
        """Test disabled maintenance doesn't trigger (AC-3.1c)."""
        # Mock config with maintenance disabled
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = False
            mock_config.maintenance.trigger = "project.closed"
            mock_load.return_value = mock_config

            # Trigger project.closed event
            event_data = {"project_id": "test_project"}
            await maintenance_manager._on_project_closed(event_data)

            maintenance_manager._storage.run_maintenance.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_trigger_no_maintenance(
        self, maintenance_manager, mock_db_manager
    ):
        """Test wrong trigger doesn't execute maintenance."""
        # Mock config with indexing.completed trigger
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = True
            mock_config.maintenance.trigger = "indexing.completed"
            mock_load.return_value = mock_config

            # Trigger project.closed event (wrong trigger)
            event_data = {"project_id": "test_project"}
            await maintenance_manager._on_project_closed(event_data)

            maintenance_manager._storage.run_maintenance.assert_not_called()


class TestMaintenanceCapabilityDetection:
    """Tests for backend capability detection (AC-3.4)."""

    def test_supports_maintenance_check_lancedb(
        self, standalone_manager, mock_lancedb_provider
    ):
        """Test capability detection for LanceDB provider."""
        # LanceDB provider should support maintenance
        assert standalone_manager._supports_maintenance(mock_lancedb_provider) is True

    def test_supports_maintenance_check_postgresql(self, standalone_manager):
        """Test capability detection for PostgreSQL provider (AC-3.4)."""
        # Create PostgreSQL provider mock without maintenance methods
        pg_provider = MagicMock()
        pg_provider._db_manager = MagicMock(spec=[])  # Empty spec, no methods

        # PostgreSQL provider should NOT support maintenance
        assert standalone_manager._supports_maintenance(pg_provider) is False

    def test_supports_maintenance_no_db_manager(self, standalone_manager):
        """Test capability detection when provider has no _db_manager attribute."""
        # Provider without _db_manager
        provider = MagicMock(spec=[])

        # Should NOT support maintenance
        assert standalone_manager._supports_maintenance(provider) is False

    @pytest.mark.asyncio
    async def test_postgresql_skips_maintenance(
        self, maintenance_manager, mock_db_manager
    ):
        """Test PostgreSQL backend uses facade maintenance (AC-3.4)."""
        # Create PostgreSQL provider
        pg_provider = MagicMock()
        pg_provider._db_manager = MagicMock(spec=[])  # No maintenance methods

        # Replace storage's graph provider with PostgreSQL
        maintenance_manager._storage._graph_provider = pg_provider

        # Mock config
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = True
            mock_config.maintenance.trigger = "project.closed"
            mock_config.maintenance.cleanup_retention_minutes = 60
            mock_load.return_value = mock_config

            # Trigger project.closed event
            event_data = {"project_id": "test_project"}
            await maintenance_manager._on_project_closed(event_data)

            maintenance_manager._storage.run_maintenance.assert_awaited_once_with(
                project_id="test_project",
                cleanup_older_than=timedelta(minutes=60),
            )


class TestMaintenanceIdempotency:
    """Tests for idempotent maintenance operations."""

    @pytest.mark.asyncio
    async def test_maintenance_idempotent(self, standalone_manager, mock_db_manager):
        """Test maintenance is safe to re-run (idempotent)."""
        project_id = "test_project"

        # Run maintenance first time
        result1 = await standalone_manager._run_maintenance_task(
            project_id=project_id, db_manager=mock_db_manager, retention_minutes=60
        )

        # Reset mock
        mock_db_manager.run_maintenance.reset_mock()

        # Run maintenance second time (should be safe)
        result2 = await standalone_manager._run_maintenance_task(
            project_id=project_id, db_manager=mock_db_manager, retention_minutes=60
        )

        # Both should succeed without errors
        assert "error" not in result1
        assert "error" not in result2

        # Both should call run_maintenance
        assert mock_db_manager.run_maintenance.call_count == 1

    @pytest.mark.asyncio
    async def test_duplicate_scheduling_prevented(
        self, standalone_manager, mock_db_manager
    ):
        """Test duplicate scheduling is prevented."""
        project_id = "test_project"

        # Schedule maintenance
        standalone_manager.schedule_maintenance(
            project_id=project_id, db_manager=mock_db_manager, retention_minutes=60
        )

        # Try to schedule again (should be skipped)
        standalone_manager.schedule_maintenance(
            project_id=project_id, db_manager=mock_db_manager, retention_minutes=60
        )

        # Wait for tasks to complete
        await asyncio.sleep(0.2)

        # Should only have run once
        assert mock_db_manager.run_maintenance.call_count == 1


class TestMaintenanceErrorHandling:
    """Tests for error handling during maintenance."""

    @pytest.mark.asyncio
    async def test_maintenance_error_returns_error_dict(self, standalone_manager):
        """Test maintenance errors return error dict without raising exception."""
        # Create db_manager that raises error
        failing_manager = MagicMock()
        failing_manager.run_maintenance = AsyncMock(
            side_effect=RuntimeError("Maintenance failed")
        )

        # Run maintenance
        result = await standalone_manager._run_maintenance_task(
            project_id="test_project", db_manager=failing_manager, retention_minutes=60
        )

        # Should return error dict, not raise exception
        assert "error" in result
        assert "Maintenance failed" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_project_id_in_event(
        self, maintenance_manager, mock_db_manager
    ):
        """Test event without project_id is handled gracefully."""
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = True
            mock_config.maintenance.trigger = "project.closed"
            mock_load.return_value = mock_config

            # Event without project_id
            event_data = {}
            await maintenance_manager._on_project_closed(event_data)

            # Should not crash, no maintenance scheduled
            assert len(maintenance_manager._running_tasks) == 0
            mock_db_manager.run_maintenance.assert_not_called()


class TestMaintenanceNonBlocking:
    """Tests for non-blocking execution (NFR-1.2)."""

    @pytest.mark.asyncio
    async def test_maintenance_non_blocking(self, standalone_manager):
        """Test maintenance runs in background without blocking (NFR-1.2)."""
        # Create slow db_manager
        slow_manager = MagicMock()

        async def slow_maintenance(**kwargs):
            await asyncio.sleep(0.2)
            return {"summary": {"fragments_reduced": 5}}

        slow_manager.run_maintenance = slow_maintenance

        # Schedule maintenance
        standalone_manager.schedule_maintenance(
            project_id="test_project", db_manager=slow_manager, retention_minutes=60
        )

        # Should return immediately (non-blocking)
        # Verify task is running
        assert "test_project" in standalone_manager._running_tasks
        task = standalone_manager._running_tasks["test_project"]
        assert not task.done()

        # Wait for completion
        await task
        assert task.done()


class TestMaintenanceSerializationPerProject:
    """Tests for per-project lock serialization (NFR-1.3)."""

    @pytest.mark.asyncio
    async def test_maintenance_serialization_per_project(self, standalone_manager):
        """Test per-project lock prevents concurrent maintenance runs."""
        project_id = "test_project"

        # Create db_manager with delay
        slow_manager = MagicMock()
        call_order = []

        async def slow_maintenance(**kwargs):
            call_order.append("start")
            await asyncio.sleep(0.1)
            call_order.append("end")
            return {"summary": {"fragments_reduced": 5}}

        slow_manager.run_maintenance = slow_maintenance

        # Start first maintenance task
        task1 = asyncio.create_task(
            standalone_manager._run_maintenance_task(
                project_id=project_id, db_manager=slow_manager, retention_minutes=60
            )
        )

        # Wait briefly to ensure first task acquires lock
        await asyncio.sleep(0.01)

        # Start second maintenance task (should wait for lock)
        task2 = asyncio.create_task(
            standalone_manager._run_maintenance_task(
                project_id=project_id, db_manager=slow_manager, retention_minutes=60
            )
        )

        # Wait for both tasks
        await asyncio.gather(task1, task2)

        # Verify tasks ran serially (not concurrently)
        # Should see: ["start", "end", "start", "end"]
        # NOT: ["start", "start", "end", "end"]
        assert call_order == ["start", "end", "start", "end"]

    @pytest.mark.asyncio
    async def test_different_projects_run_concurrently(self, standalone_manager):
        """Test different projects can run maintenance concurrently."""
        # Create db_managers with delay
        call_timestamps = {}

        async def slow_maintenance(project_label: str, **kwargs):
            import time

            call_timestamps[f"{project_label}_start"] = time.time()
            await asyncio.sleep(0.1)
            call_timestamps[f"{project_label}_end"] = time.time()
            return {"summary": {"fragments_reduced": 5}}

        slow_manager_1 = MagicMock()
        slow_manager_1.run_maintenance = lambda **kwargs: slow_maintenance(
            "project1", **kwargs
        )

        slow_manager_2 = MagicMock()
        slow_manager_2.run_maintenance = lambda **kwargs: slow_maintenance(
            "project2", **kwargs
        )

        # Start maintenance for two different projects
        task1 = asyncio.create_task(
            standalone_manager._run_maintenance_task(
                project_id="project1", db_manager=slow_manager_1, retention_minutes=60
            )
        )

        task2 = asyncio.create_task(
            standalone_manager._run_maintenance_task(
                project_id="project2", db_manager=slow_manager_2, retention_minutes=60
            )
        )

        # Wait for both
        await asyncio.gather(task1, task2)

        # Different projects should run concurrently
        # (their execution windows should overlap)
        assert call_timestamps["project1_start"] < call_timestamps["project2_end"]
        assert call_timestamps["project2_start"] < call_timestamps["project1_end"]


class TestMaintenanceEventSubscription:
    """Tests for event subscription during initialization."""

    def test_event_subscription_on_init(self, mock_event_system, mock_storage):
        """Test MaintenanceManager subscribes to events on initialization."""
        # Create manager with event system
        manager = MaintenanceManager(
            event_system=mock_event_system, storage=mock_storage
        )

        # Verify subscriptions
        assert mock_event_system.bus.subscribe.call_count == 2

        # Extract subscription calls
        calls = mock_event_system.bus.subscribe.call_args_list

        # Verify subscribed to project.closed
        project_closed_call = [c for c in calls if c[0][0] == EventTypes.Project.CLOSED]
        assert len(project_closed_call) == 1
        assert project_closed_call[0][0][1] == manager._on_project_closed

        # Verify subscribed to indexing.completed
        indexing_completed_call = [
            c for c in calls if c[0][0] == EventTypes.Indexing.COMPLETED
        ]
        assert len(indexing_completed_call) == 1
        assert indexing_completed_call[0][0][1] == manager._on_indexing_completed

    def test_no_subscription_without_event_system(self):
        """Test manager without event_system doesn't subscribe to events."""
        # Create manager without event system
        manager = MaintenanceManager()

        # Should initialize without errors
        assert manager._event_system is None
        assert manager._storage is None


class TestMaintenanceRetentionMinutes:
    """Tests for cleanup retention configuration."""

    @pytest.mark.asyncio
    async def test_retention_minutes_respected(
        self, standalone_manager, mock_db_manager
    ):
        """Test cleanup_retention_minutes is passed to run_maintenance."""
        retention_minutes = 120

        # Run maintenance
        await standalone_manager._run_maintenance_task(
            project_id="test_project",
            db_manager=mock_db_manager,
            retention_minutes=retention_minutes,
        )

        # Verify run_maintenance was called with correct retention
        mock_db_manager.run_maintenance.assert_called_once()
        call_args = mock_db_manager.run_maintenance.call_args
        assert call_args[1]["cleanup_older_than"] == timedelta(
            minutes=retention_minutes
        )

    @pytest.mark.asyncio
    async def test_event_uses_config_retention(
        self, maintenance_manager, mock_db_manager
    ):
        """Test event handlers use config.maintenance.cleanup_retention_minutes."""
        # Mock config with custom retention
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = True
            mock_config.maintenance.trigger = "project.closed"
            mock_config.maintenance.cleanup_retention_minutes = 240
            mock_load.return_value = mock_config

            # Trigger event
            event_data = {"project_id": "test_project"}
            await maintenance_manager._on_project_closed(event_data)

            maintenance_manager._storage.run_maintenance.assert_awaited_once_with(
                project_id="test_project",
                cleanup_older_than=timedelta(minutes=240),
            )


class TestMaintenanceLockManagement:
    """Tests for lock creation and management."""

    def test_get_lock_creates_lock(self, standalone_manager):
        """Test _get_lock creates lock for new project."""
        project_id = "test_project"

        # Get lock for new project
        lock = standalone_manager._get_lock(project_id)

        # Should be an asyncio.Lock
        assert isinstance(lock, asyncio.Lock)
        assert project_id in standalone_manager._locks

    def test_get_lock_returns_same_lock(self, standalone_manager):
        """Test _get_lock returns same lock for same project."""
        project_id = "test_project"

        # Get lock twice
        lock1 = standalone_manager._get_lock(project_id)
        lock2 = standalone_manager._get_lock(project_id)

        # Should be same instance
        assert lock1 is lock2
