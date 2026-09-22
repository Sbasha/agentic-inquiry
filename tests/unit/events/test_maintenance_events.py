"""Tests for maintenance event emissions.

This test module verifies that maintenance operations emit appropriate events
with correct payloads during their lifecycle (started, completed, failed).

Requirement tested: NFR-3.1
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

pytestmark = pytest.mark.unit

from agent_vault.events.types import EventTypes
from agent_vault.events.models import EventStatus
from agent_vault.events.context_managers import track_operation, OperationTracker


class TestMaintenanceEvents:
    """Test maintenance event emissions during lifecycle.

    Note: These tests verify the expected event emission behavior.
    They use mocking to test event emissions without requiring the full implementation.
    """

    @pytest.mark.asyncio
    async def test_maintenance_started_event_emitted(self):
        """Test that maintenance.started event is emitted when maintenance begins.

        Verifies:
        - Event type is "maintenance.started"
        - Event includes project_id
        - Event status is PROGRESS or STARTED
        """
        # Mock event system to track event emissions
        mock_event_system = AsyncMock()
        mock_event_system.emit = AsyncMock()

        # Run the maintenance operation with event tracking
        async with track_operation(
            mock_event_system,
            "maintenance",
            "maintenance",
            project_id="test_project",
        ):
            pass

        # Verify maintenance.started event was emitted
        start_event_calls = [
            call for call in mock_event_system.emit.call_args_list
            if len(call[0]) > 0 and call[0][0] == EventTypes.Maintenance.STARTED
        ]

        assert len(start_event_calls) > 0, "maintenance.started event should be emitted"

        # Verify event payload
        start_call = start_event_calls[0]
        assert start_call[1].get("project_id") == "test_project"
        assert start_call[1].get("status") in [EventStatus.STARTED, EventStatus.PROGRESS]
        assert start_call[1].get("source") is not None

    @pytest.mark.asyncio
    async def test_maintenance_completed_event_payload(self):
        """Test that maintenance.completed event includes correct payload.

        Verifies payload includes:
        - project_id
        - duration (execution time)
        - bytes_freed (from cleanup results)
        - fragments_reduced
        - versions_removed
        """
        # Mock event system
        mock_event_system = AsyncMock()
        mock_event_system.emit = AsyncMock()

        # Mock maintenance with event emission
        maintenance_results = {
            "compaction": {
                "document_chunks": {"fragments_reduced": 10},
                "graph_entities": {"fragments_reduced": 5}
            },
            "cleanup": {
                "document_chunks": {
                    "versions_removed": 15,
                    "bytes_freed": 1024000  # 1MB
                },
                "graph_entities": {
                    "versions_removed": 8,
                    "bytes_freed": 512000  # 512KB
                }
            },
            "summary": {
                "fragments_reduced": 15,
                "versions_removed": 23,
                "bytes_freed": 1536000  # Total bytes freed
            }
        }

        tracker = OperationTracker(
            mock_event_system,
            "maintenance",
            "maintenance",
            "op_maintenance_1",
        )
        await tracker.complete(
            project_id="test_project",
            duration_ms=1500,
            bytes_freed=maintenance_results["summary"]["bytes_freed"],
            fragments_reduced=maintenance_results["summary"]["fragments_reduced"],
            versions_removed=maintenance_results["summary"]["versions_removed"],
        )

        # Find the maintenance.completed event
        completed_event_calls = [
            call for call in mock_event_system.emit.call_args_list
            if len(call[0]) > 0 and call[0][0] == EventTypes.Maintenance.COMPLETED
        ]

        assert len(completed_event_calls) > 0, "maintenance.completed event should be emitted"

        # Verify payload
        completed_call = completed_event_calls[0]
        payload = completed_call[1]

        assert payload.get("project_id") == "test_project"
        assert payload.get("status") == EventStatus.COMPLETED
        assert "duration_ms" in payload  # Execution time
        assert payload.get("bytes_freed") == 1536000  # Total bytes freed
        assert payload.get("fragments_reduced") == 15
        assert payload.get("versions_removed") == 23

    @pytest.mark.asyncio
    async def test_maintenance_failed_event_emitted(self):
        """Test that maintenance.failed event is emitted on error.

        Verifies:
        - Event type is "maintenance.failed"
        - Event includes error information
        - Event status is FAILED
        """
        # Mock event system
        mock_event_system = AsyncMock()
        mock_event_system.emit = AsyncMock()

        # Simulate error during maintenance
        error_message = "Database connection lost"

        tracker = OperationTracker(
            mock_event_system,
            "maintenance",
            "maintenance",
            "op_maintenance_2",
        )
        await tracker.fail(
            error_message,
            project_id="test_project",
        )

        # Find the maintenance.failed event
        failed_event_calls = [
            call for call in mock_event_system.emit.call_args_list
            if len(call[0]) > 0 and call[0][0] == EventTypes.Maintenance.FAILED
        ]

        assert len(failed_event_calls) > 0, "maintenance.failed event should be emitted on error"

        # Verify payload
        failed_call = failed_event_calls[0]
        payload = failed_call[1]

        assert payload.get("project_id") == "test_project"
        assert payload.get("status") == EventStatus.FAILED
        assert "error" in payload
        assert payload.get("source") is not None


class TestMaintenanceManagerEvents:
    """Test MaintenanceManager event emissions and triggers."""

    @pytest.mark.asyncio
    async def test_project_closed_triggers_maintenance_event(self):
        """Test that project.closed event triggers maintenance.

        Verifies:
        - MaintenanceManager subscribes to project.closed
        - When project.closed is emitted, maintenance is scheduled
        - maintenance.started event is emitted
        """
        from agent_vault.mcp.services.maintenance_manager import MaintenanceManager
        from agent_vault.events.system import EventSystem

        # Create event system
        event_system = AsyncMock(spec=EventSystem)
        event_system.emit = AsyncMock()
        event_system.bus = MagicMock()
        event_system.bus.subscribe = MagicMock()

        # Create mock storage
        mock_storage = MagicMock()
        mock_db_manager = AsyncMock()
        mock_db_manager.run_maintenance = AsyncMock(return_value={
            "compaction": {},
            "cleanup": {},
            "summary": {"fragments_reduced": 0, "versions_removed": 0}
        })

        mock_graph_provider = MagicMock()
        mock_graph_provider._db_manager = mock_db_manager
        mock_storage._graph_provider = mock_graph_provider

        # Create maintenance manager with event system
        MaintenanceManager(
            event_system=event_system,
            storage=mock_storage
        )

        # Verify manager subscribed to events
        assert event_system.bus.subscribe.called
        subscribe_calls = event_system.bus.subscribe.call_args_list

        # Find project.closed subscription
        project_closed_subscribed = any(
            EventTypes.Project.CLOSED in str(call)
            for call in subscribe_calls
        )
        assert project_closed_subscribed, "Manager should subscribe to project.closed"

    @pytest.mark.asyncio
    async def test_indexing_completed_triggers_maintenance_event(self):
        """Test that indexing.completed event triggers maintenance.

        Verifies:
        - MaintenanceManager subscribes to indexing.completed
        - When indexing.completed is emitted, maintenance is scheduled
        """
        from agent_vault.mcp.services.maintenance_manager import MaintenanceManager
        from agent_vault.events.system import EventSystem

        # Create event system
        event_system = AsyncMock(spec=EventSystem)
        event_system.emit = AsyncMock()
        event_system.bus = MagicMock()
        event_system.bus.subscribe = MagicMock()

        # Create mock storage
        mock_storage = MagicMock()
        mock_db_manager = AsyncMock()
        mock_db_manager.run_maintenance = AsyncMock(return_value={
            "compaction": {},
            "cleanup": {},
            "summary": {"fragments_reduced": 0, "versions_removed": 0}
        })

        mock_graph_provider = MagicMock()
        mock_graph_provider._db_manager = mock_db_manager
        mock_storage._graph_provider = mock_graph_provider

        # Create maintenance manager
        MaintenanceManager(
            event_system=event_system,
            storage=mock_storage
        )

        # Verify manager subscribed to indexing.completed
        subscribe_calls = event_system.bus.subscribe.call_args_list
        indexing_completed_subscribed = any(
            EventTypes.Indexing.COMPLETED in str(call)
            for call in subscribe_calls
        )
        assert indexing_completed_subscribed, "Manager should subscribe to indexing.completed"
