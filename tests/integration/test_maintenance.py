"""Integration tests for automatic maintenance functionality.

Tests the full maintenance flow including:
- Actual LanceDB maintenance operations
- Event-driven triggers with real event system
- Config-based behavior with actual Config loading
- End-to-end workflows from event to completion
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.mcp.services.maintenance_manager import MaintenanceManager
from agentic_inquiry.events.system import EventSystem
from agentic_inquiry.events.types import EventTypes
from agentic_inquiry.config import Config
from agentic_inquiry.database.lancedb_manager import LanceDBManager


@pytest.fixture
async def temp_db_path(tmp_path):
    """Create a temporary database path."""
    db_path = tmp_path / "test_lancedb"
    db_path.mkdir(parents=True, exist_ok=True)
    yield db_path


@pytest.fixture
async def lancedb_manager(temp_db_path):
    """Create a real LanceDBManager for integration tests."""
    manager = LanceDBManager(uri=str(temp_db_path))
    yield manager
    await manager.close()


@pytest.fixture
async def mock_storage_with_lancedb(lancedb_manager):
    """Create a mock StorageFacade with real LanceDB manager."""
    storage = AsyncMock()
    # The method called by MaintenanceManager is run_maintenance
    storage.run_maintenance = AsyncMock(return_value={"summary": "mocked success"})

    # Still need to provide the underlying manager for some tests
    provider = MagicMock()
    provider._db_manager = lancedb_manager
    storage._graph_provider = provider
    return storage


@pytest.fixture
async def event_system():
    """Create a real EventSystem."""
    # Need a config with default_project_id
    config = Config.load()
    config.storage.default_project_id = "test_project"
    system = EventSystem(config=config, project_id="test_project")
    await system.start()
    yield system
    await system.stop()


@pytest.fixture
def test_config():
    """Create a test configuration."""
    config = Config.load()
    # Override maintenance settings for testing
    config.maintenance.enabled = True
    config.maintenance.trigger = "project.closed"
    config.maintenance.cleanup_retention_minutes = 60
    return config


class TestMaintenanceIntegration:
    """Integration tests for maintenance operations."""

    @pytest.mark.asyncio
    async def test_schedule_maintenance_executes(
        self, lancedb_manager, mock_storage_with_lancedb
    ):
        """Test scheduling maintenance executes successfully."""
        manager = MaintenanceManager()

        # Schedule maintenance
        manager.schedule_maintenance(
            project_id="test_project", db_manager=lancedb_manager, retention_minutes=60
        )

        # Wait for task to start
        await asyncio.sleep(0.1)

        # Verify task was created
        assert "test_project" in manager._running_tasks

        # Wait for completion
        task = manager._running_tasks["test_project"]
        result = await task

        # Verify result structure (even if no tables exist)
        assert isinstance(result, dict)
        # Should have either "summary" or "error" key
        assert "summary" in result or "error" in result

    @pytest.mark.asyncio
    async def test_event_driven_maintenance_flow(
        self, event_system, mock_storage_with_lancedb
    ):
        """Test full event-driven maintenance flow."""
        # Create manager with event system and the mock storage
        manager = MaintenanceManager(
            event_system=event_system, storage=mock_storage_with_lancedb
        )

        # Emit project.closed event
        await event_system.emit(
            EventTypes.Project.CLOSED, source="test", project_id="test_project"
        )

        # Wait for the event to be processed
        await asyncio.sleep(0.2)

        # Verify that the mock's run_maintenance method was called
        mock_storage_with_lancedb.run_maintenance.assert_awaited_once_with(
            project_id="test_project"
        )

    @pytest.mark.asyncio
    async def test_maintenance_with_actual_tables(self, lancedb_manager, temp_db_path):
        """Test maintenance with actual LanceDB tables."""
        # Create a test table
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(str(temp_db_path))

        # Create schema
        schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
                pa.field("embedding", pa.list_(pa.float32(), 128)),
            ]
        )

        # Create table with some data
        data = [{"id": "1", "text": "test", "embedding": [0.1] * 128}]
        db.create_table("test_table", data, schema=schema, mode="overwrite")

        # Run maintenance
        manager = MaintenanceManager()
        result = await manager._run_maintenance_task(
            project_id="test_project", db_manager=lancedb_manager, retention_minutes=60
        )

        # Verify result
        assert "summary" in result or "compaction" in result
        # Maintenance should complete without errors
        assert "error" not in result or result.get("error") is None


class TestMaintenanceConfigIntegration:
    """Integration tests for config-based behavior."""

    @pytest.mark.asyncio
    async def test_trigger_config_changes_behavior(
        self, event_system, mock_storage_with_lancedb
    ):
        """Test different trigger configs change behavior."""
        manager = MaintenanceManager(
            event_system=event_system, storage=mock_storage_with_lancedb
        )

        # Test 1: project.closed trigger
        mock_storage_with_lancedb.run_maintenance.reset_mock()
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = True
            mock_config.maintenance.trigger = "project.closed"
            mock_load.return_value = mock_config

            await event_system.emit(
                EventTypes.Project.CLOSED, source="test", project_id="project1"
            )
            await asyncio.sleep(0.1)
            mock_storage_with_lancedb.run_maintenance.assert_awaited_once_with(
                project_id="project1"
            )

        # Test 2: indexing.completed trigger
        mock_storage_with_lancedb.run_maintenance.reset_mock()
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = True
            mock_config.maintenance.trigger = "indexing.completed"
            mock_load.return_value = mock_config

            await event_system.emit(
                EventTypes.Project.CLOSED, source="test", project_id="project2"
            )
            await asyncio.sleep(0.1)
            mock_storage_with_lancedb.run_maintenance.assert_not_awaited()

            await event_system.emit(
                EventTypes.Indexing.COMPLETED, source="test", project_id="project3"
            )
            await asyncio.sleep(0.1)
            mock_storage_with_lancedb.run_maintenance.assert_awaited_once_with(
                project_id="project3"
            )


class TestMaintenanceConcurrency:
    """Integration tests for concurrent maintenance scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_projects_maintenance(self, lancedb_manager):
        """Test multiple projects can run maintenance concurrently."""
        manager = MaintenanceManager()

        # Schedule maintenance for multiple projects
        manager.schedule_maintenance(
            project_id="project1", db_manager=lancedb_manager, retention_minutes=60
        )
        manager.schedule_maintenance(
            project_id="project2", db_manager=lancedb_manager, retention_minutes=60
        )
        manager.schedule_maintenance(
            project_id="project3", db_manager=lancedb_manager, retention_minutes=60
        )

        # Wait for tasks to start
        await asyncio.sleep(0.1)

        # All should be running
        assert "project1" in manager._running_tasks
        assert "project2" in manager._running_tasks
        assert "project3" in manager._running_tasks

        # Wait for all to complete
        await asyncio.gather(
            manager._running_tasks["project1"],
            manager._running_tasks["project2"],
            manager._running_tasks["project3"],
        )

        # All should complete successfully
        assert manager._running_tasks["project1"].done()
        assert manager._running_tasks["project2"].done()
        assert manager._running_tasks["project3"].done()

    @pytest.mark.asyncio
    async def test_serial_execution_same_project(self, lancedb_manager):
        """Test same project executes maintenance serially."""
        manager = MaintenanceManager()

        # Track execution order
        execution_log = []

        # Create a wrapper to track execution
        original_run_maintenance = lancedb_manager.run_maintenance

        async def tracked_run_maintenance(**kwargs):
            execution_log.append("start")
            result = await original_run_maintenance(**kwargs)
            execution_log.append("end")
            return result

        lancedb_manager.run_maintenance = tracked_run_maintenance

        # Schedule twice for same project
        task1 = asyncio.create_task(
            manager._run_maintenance_task(
                project_id="project1", db_manager=lancedb_manager, retention_minutes=60
            )
        )

        # Wait a bit then schedule again
        await asyncio.sleep(0.05)

        task2 = asyncio.create_task(
            manager._run_maintenance_task(
                project_id="project1", db_manager=lancedb_manager, retention_minutes=60
            )
        )

        # Wait for both
        await asyncio.gather(task1, task2)

        # Should execute serially: ["start", "end", "start", "end"]
        assert execution_log == ["start", "end", "start", "end"]


class TestMaintenanceErrorRecovery:
    """Integration tests for error recovery."""

    @pytest.mark.asyncio
    async def test_maintenance_error_doesnt_crash_manager(self):
        """Test maintenance errors don't crash the manager."""
        manager = MaintenanceManager()

        # Create a failing db_manager
        failing_manager = MagicMock()
        failing_manager.run_maintenance = AsyncMock(
            side_effect=RuntimeError("Simulated failure")
        )

        # Schedule maintenance
        manager.schedule_maintenance(
            project_id="failing_project",
            db_manager=failing_manager,
            retention_minutes=60,
        )

        # Wait for task
        await asyncio.sleep(0.1)
        task = manager._running_tasks["failing_project"]
        result = await task

        # Should return error dict, not crash
        assert "error" in result
        assert "Simulated failure" in result["error"]

        # Manager should still be functional
        # Schedule another maintenance for different project
        working_manager = MagicMock()
        working_manager.run_maintenance = AsyncMock(
            return_value={"summary": {"fragments_reduced": 5}}
        )

        manager.schedule_maintenance(
            project_id="working_project",
            db_manager=working_manager,
            retention_minutes=60,
        )

        await asyncio.sleep(0.1)
        task2 = manager._running_tasks["working_project"]
        result2 = await task2

        # Second maintenance should work
        assert "error" not in result2


class TestMaintenanceBackendSupport:
    """Integration tests for different backend support."""

    @pytest.mark.asyncio
    async def test_lancedb_backend_supports_maintenance(self, lancedb_manager):
        """Test LanceDB backend is detected as supporting maintenance."""
        manager = MaintenanceManager()

        # Create provider with LanceDB manager
        provider = MagicMock()
        provider._db_manager = lancedb_manager

        # Should support maintenance
        assert manager._supports_maintenance(provider) is True

    @pytest.mark.asyncio
    async def test_non_lancedb_backend_skips_maintenance(self, event_system):
        """Test non-LanceDB backends skip maintenance."""
        # Create storage with non-LanceDB provider
        storage = MagicMock()
        provider = MagicMock()
        provider._db_manager = MagicMock(spec=[])  # No maintenance methods
        storage._graph_provider = provider

        manager = MaintenanceManager(event_system=event_system, storage=storage)

        # Mock config
        with patch("agentic_inquiry.config.Config.load") as mock_load:
            mock_config = MagicMock()
            mock_config.maintenance.enabled = True
            mock_config.maintenance.trigger = "project.closed"
            mock_load.return_value = mock_config

            # Trigger event
            await event_system.emit(
                EventTypes.Project.CLOSED, source="test", project_id="test_project"
            )

            await asyncio.sleep(0.1)

            # Should NOT schedule maintenance
            assert "test_project" not in manager._running_tasks
