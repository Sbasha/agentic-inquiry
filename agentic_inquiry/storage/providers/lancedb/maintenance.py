"""LanceDB maintenance operations.

This module provides maintenance and optimization functions for LanceDB storage.
It implements parts of the MaintenanceProtocol for index optimization, compaction,
and integrity validation.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from agentic_inquiry.storage.providers.lancedb.connection import (
        LanceDBConnectionManager,
    )

logger = logging.getLogger(__name__)


class LanceDBMaintenanceOperations:
    """Maintenance operations for LanceDB storage.

    This class provides maintenance functionality that can be used by
    LanceDB providers for index optimization, compaction, and validation.

    Example:
        >>> manager = LanceDBConnectionManager(config, "my-project")
        >>> await manager.initialize()
        >>> maintenance = LanceDBMaintenanceOperations(manager)
        >>> results = await maintenance.run_maintenance()
    """

    def __init__(
        self,
        connection_manager: "LanceDBConnectionManager",
    ) -> None:
        """Initialize maintenance operations.

        Args:
            connection_manager: Initialized LanceDBConnectionManager
        """
        self._connection_manager = connection_manager

    @property
    def _db_manager(self):
        """Get the underlying database manager."""
        return self._connection_manager.db_manager

    @property
    def _project_id(self) -> str:
        """Get the project ID from connection manager."""
        return self._connection_manager.project_id

    async def health_check(self) -> Dict[str, Any]:
        """Check provider health.

        Returns:
            Dict with health status information:
                - status: "healthy", "degraded", or "unhealthy"
                - healthy: bool (for backward compatibility)
                - project_id: Project identifier
                - initialized: Whether provider is initialized
        """
        if self._db_manager is None:
            return {
                "status": "unhealthy",
                "healthy": False,
                "error": "Provider not initialized",
            }

        try:
            is_healthy = await self._db_manager.health_check()
            status = "healthy" if is_healthy else "unhealthy"
            return {
                "status": status,
                "healthy": is_healthy,
                "project_id": self._project_id,
                "initialized": self._connection_manager.is_initialized,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "healthy": False,
                "error": str(e),
            }

    async def run_maintenance(
        self,
        table_names: Optional[List[str]] = None,
        cleanup_older_than: Optional[timedelta] = None,
    ) -> Dict[str, Any]:
        """Run maintenance tasks.

        Args:
            table_names: List of table names to maintain. If None, maintains
                        all standard tables.
            cleanup_older_than: Only remove versions older than this duration.
                              If None, uses the manager's default (5 minutes).

        Returns:
            Dict with maintenance results including compaction, cleanup, and summary
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        # Build kwargs for manager call
        kwargs: Dict[str, Any] = {}
        if table_names is not None:
            kwargs["table_names"] = table_names
        if cleanup_older_than is not None:
            kwargs["cleanup_older_than"] = cleanup_older_than

        return await self._db_manager.run_maintenance(**kwargs)

    async def compact(self) -> Dict[str, Any]:
        """Compact storage to reclaim space.

        Returns:
            Dict with compaction results
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        return await self._db_manager.compact_tables()

    async def validate_integrity(self) -> Dict[str, Any]:
        """Validate database integrity.

        Returns:
            Dict with validation results
        """
        if self._db_manager is None:
            raise RuntimeError("Provider not initialized")

        return await self._db_manager.validate_database_integrity()

    async def cleanup_orphaned_data(
        self,
        project_id: str,
    ) -> int:
        """Clean up orphaned data.

        Args:
            project_id: Project ID for isolation

        Returns:
            Number of orphaned records cleaned up
        """
        # For now, this is a no-op - can be extended to clean up
        # relationships with missing entities, etc.
        return 0
