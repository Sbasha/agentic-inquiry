"""Maintenance manager for automatic LanceDB maintenance scheduling.

This module provides the MaintenanceManager class which handles non-blocking
background maintenance tasks for LanceDB storage backends. It ensures:
- Per-project serialization to prevent concurrent maintenance runs
- Capability checking to skip non-LanceDB backends
- Non-blocking execution via asyncio.create_task

Maintenance includes:
1. Table compaction (merging small files)
2. Version cleanup (removing old MVCC versions)
"""

import asyncio
import logging
from datetime import timedelta
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_inquiry.events.system import EventSystem
    from agentic_inquiry.storage.facade import StorageFacade

logger = logging.getLogger(__name__)


class MaintenanceManager:
    """Manages non-blocking auto-maintenance with per-project serialization.

    This manager schedules and runs LanceDB maintenance tasks in the background
    without blocking normal operations. It uses per-project locks to ensure
    only one maintenance operation runs per project at a time.

    Responsibilities:
    - Schedule maintenance as background tasks
    - Prevent concurrent runs per project
    - Verify provider capabilities (LanceDB-only)
    - Execute maintenance with proper ordering

    Example:
        >>> manager = MaintenanceManager()
        >>> manager.schedule_maintenance(
        ...     project_id="my_project",
        ...     db_manager=lancedb_manager,
        ...     retention_minutes=60
        ... )
    """

    def __init__(
        self,
        event_system: Optional["EventSystem"] = None,
        storage: Optional["StorageFacade"] = None,
    ):
        """Initialize maintenance manager.

        Creates empty dictionaries for tracking locks and running tasks
        per project. If event_system and storage are provided, subscribes
        to event triggers for automatic maintenance.

        Args:
            event_system: Optional EventSystem for event-driven triggers
            storage: Optional StorageFacade for accessing db_manager
        """
        # Per-project locks to prevent concurrent maintenance
        self._locks: Dict[str, asyncio.Lock] = {}

        # Track running maintenance tasks per project
        self._running_tasks: Dict[str, asyncio.Task] = {}

        # Store dependencies for event handlers
        self._event_system = event_system
        self._storage = storage

        # Subscribe to events if event_system provided
        if event_system is not None:
            from agentic_inquiry.events.types import EventTypes

            event_system.bus.subscribe(
                EventTypes.Project.CLOSED, self._on_project_closed
            )
            event_system.bus.subscribe(
                EventTypes.Indexing.COMPLETED, self._on_indexing_completed
            )
            logger.debug(
                "MaintenanceManager subscribed to project.closed and indexing.completed events"
            )

    def _get_lock(self, project_id: str) -> asyncio.Lock:
        """Get or create per-project lock to prevent concurrent maintenance.

        Args:
            project_id: Project identifier

        Returns:
            asyncio.Lock for the specified project
        """
        if project_id not in self._locks:
            self._locks[project_id] = asyncio.Lock()
        return self._locks[project_id]

    def _supports_maintenance(self, provider) -> bool:
        """Check if provider supports maintenance (LanceDB capability check).

        This method verifies that the provider has the required LanceDB
        maintenance methods (compact_tables and cleanup_old_versions).
        Non-LanceDB backends (PostgreSQL, cloud) will return False.

        Args:
            provider: Storage provider to check

        Returns:
            True if provider supports maintenance, False otherwise
        """
        # Check if provider has _db_manager attribute
        if not hasattr(provider, "_db_manager"):
            logger.debug("Provider does not have _db_manager attribute")
            return False

        db_manager = provider._db_manager

        # Verify LanceDB maintenance methods exist
        has_compact = hasattr(db_manager, "compact_tables")
        has_cleanup = hasattr(db_manager, "cleanup_old_versions")

        if not (has_compact and has_cleanup):
            logger.debug(
                "Provider db_manager missing maintenance methods: "
                "compact_tables=%s, cleanup_old_versions=%s",
                has_compact,
                has_cleanup,
            )
            return False

        logger.debug("Provider supports maintenance")
        return True

    async def _run_maintenance_task(
        self, project_id: str, db_manager, retention_minutes: int
    ) -> dict:
        """Execute maintenance with lock serialization.

        Runs maintenance operations (compact then cleanup) for the specified
        project. Uses per-project lock to ensure only one maintenance run
        at a time. Handles errors gracefully without corrupting data.

        Args:
            project_id: Project identifier
            db_manager: LanceDB manager instance with maintenance methods
            retention_minutes: Cleanup retention window in minutes

        Returns:
            Dict with maintenance results including compaction and cleanup status
        """
        lock = self._get_lock(project_id)

        async with lock:
            try:
                logger.info(
                    "Starting maintenance for project %s (retention: %d minutes)",
                    project_id,
                    retention_minutes,
                )

                # Call run_maintenance with proper retention
                retention = timedelta(minutes=retention_minutes)
                result = await db_manager.run_maintenance(cleanup_older_than=retention)

                logger.info(
                    "Maintenance completed for project %s: %s", project_id, result
                )

                return result

            except Exception as e:
                logger.warning(
                    "Auto-maintenance failed for project %s: %s",
                    project_id,
                    e,
                    exc_info=True,
                )
                # Return error dict without propagating exception
                # This ensures maintenance failures don't corrupt data
                return {"error": str(e)}

    def schedule_maintenance(
        self, project_id: str, db_manager, retention_minutes: int
    ) -> None:
        """Schedule maintenance as background task (non-blocking).

        Creates an asyncio task to run maintenance in the background without
        blocking the caller. If maintenance is already running for the project,
        this method does nothing (avoids duplicate scheduling).

        Args:
            project_id: Project identifier
            db_manager: LanceDB manager instance with maintenance methods
            retention_minutes: Cleanup retention window in minutes
        """
        # Prevent duplicate scheduling
        if project_id in self._running_tasks:
            task = self._running_tasks[project_id]
            if not task.done():
                logger.debug(
                    "Maintenance already scheduled for project %s, skipping", project_id
                )
                return

        logger.debug("Scheduling maintenance for project %s", project_id)

        # Create background task
        task = asyncio.create_task(
            self._run_maintenance_task(project_id, db_manager, retention_minutes)
        )

        # Track the task
        self._running_tasks[project_id] = task

    async def _on_project_closed(self, event_data: Dict[str, Any]) -> None:
        """Handle project.closed event.

        Triggered when a project session is closed. If maintenance trigger is
        set to "project.closed", schedules maintenance for the project.

        Args:
            event_data: Event data containing project_id
        """
        from agentic_inquiry.config import Config

        # Load current config
        config = Config.load()

        # Check if maintenance is enabled
        if not config.maintenance.enabled:
            logger.debug("Maintenance disabled, skipping project.closed trigger")
            return

        # Check if trigger matches
        if config.maintenance.trigger != "project.closed":
            logger.debug(
                "Maintenance trigger is %s, not project.closed, skipping",
                config.maintenance.trigger,
            )
            return

        # Extract project_id from event data
        project_id = event_data.get("project_id")
        if not project_id:
            logger.warning(
                "project.closed event missing project_id, cannot trigger maintenance"
            )
            return

        # Verify we have storage
        if self._storage is None:
            logger.warning(
                "MaintenanceManager has no storage, cannot trigger maintenance"
            )
            return

        # Use facade to run maintenance
        # Facade handles capability check internally or we can try/except
        try:
            logger.info(
                "project.closed event triggered maintenance for project %s", project_id
            )
            # Run maintenance directly via storage facade
            await self._storage.run_maintenance(
                project_id=project_id,
                cleanup_older_than=timedelta(
                    minutes=config.maintenance.cleanup_retention_minutes
                ),
            )

        except Exception as e:
            logger.error("Failed to run maintenance for project %s: %s", project_id, e)

    async def _on_indexing_completed(self, event_data: Dict[str, Any]) -> None:
        """Handle indexing.completed event.

        Triggered when indexing completes. If maintenance trigger is set to
        "indexing.completed", schedules maintenance for the project.

        Args:
            event_data: Event data containing project_id and other metadata
        """
        from agentic_inquiry.config import Config

        # Load current config
        config = Config.load()

        # Check if maintenance is enabled
        if not config.maintenance.enabled:
            logger.debug("Maintenance disabled, skipping indexing.completed trigger")
            return

        # Check if trigger matches
        if config.maintenance.trigger != "indexing.completed":
            logger.debug(
                "Maintenance trigger is %s, not indexing.completed, skipping",
                config.maintenance.trigger,
            )
            return

        # Extract project_id from event data
        project_id = event_data.get("project_id")
        if not project_id:
            logger.warning(
                "indexing.completed event missing project_id, cannot trigger maintenance"
            )
            return

        # Verify we have storage
        if self._storage is None:
            logger.warning(
                "MaintenanceManager has no storage, cannot trigger maintenance"
            )
            return

        # Use facade to run maintenance
        try:
            logger.info(
                "indexing.completed event triggered maintenance for project %s",
                project_id,
            )
            # Run maintenance directly via storage facade
            await self._storage.run_maintenance(
                project_id=project_id,
                cleanup_older_than=timedelta(
                    minutes=config.maintenance.cleanup_retention_minutes
                ),
            )

        except Exception as e:
            logger.error("Failed to run maintenance for project %s: %s", project_id, e)


# Global instance for use by event handlers
# NOTE: This instance has no dependencies and won't respond to events.
# For event-driven maintenance, create MaintenanceManager with event_system and storage.
_maintenance_manager = MaintenanceManager()
