"""SQLite event storage provider.

This module provides a protocol-compliant SQLite event storage provider
by extending the existing SQLiteEventStorage with the run_maintenance() method.

Design reference: Phase 4 GCP Connectors implementation plan
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Union
from pathlib import Path

from agentic_inquiry.events.storage.sqlite import SQLiteEventStorage

logger = logging.getLogger(__name__)


class SQLiteEventProvider(SQLiteEventStorage):
    """SQLite implementation of EventStorageProtocol.

    This provider extends SQLiteEventStorage with full protocol compliance,
    adding the run_maintenance() method required by EventStorageProtocol.

    All inherited methods from SQLiteEventStorage:
        - initialize(): Initialize storage and create schema
        - close(): Close connections and release resources
        - write_events(): Write events to storage
        - query_events(): Query events with filters
        - get_operation_events(): Get all events for an operation
        - get_operation_status(): Get aggregated status for an operation
        - count_events(): Count events matching filters
        - delete_before(): Delete events before cutoff timestamp

    Added methods:
        - run_maintenance(): Run storage optimization (VACUUM)

    Example:
        >>> provider = SQLiteEventProvider(
        ...     db_path="/path/to/events.db",
        ...     project_id="my_project",
        ... )
        >>> await provider.initialize()
        >>> await provider.write_events(events)
        >>> result = await provider.run_maintenance()
        >>> await provider.close()
    """

    SUPPORTED_ROLES: frozenset[str] = frozenset({"events"})

    def __init__(
        self,
        project_id: str,
        db_path: Union[str, Path, None] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the SQLite event provider.

        Args:
            project_id: Project identifier for data isolation
            db_path: Path to the SQLite database file
            **kwargs: Additional configuration (e.g., 'path', 'config')
        """
        # Handle 'path' and 'database_path' aliases for 'db_path' from configuration
        if db_path is None:
            db_path = kwargs.get("path") or kwargs.get("database_path")
            
        if db_path is None:
            raise ValueError("db_path or path is required for SQLiteEventProvider")
            
        super().__init__(db_path=db_path, project_id=project_id)

    async def run_maintenance(self) -> Dict[str, Any]:
        """Run storage maintenance operations.

        Performs SQLite-specific optimization:
        - VACUUM to reclaim unused space
        - WAL checkpoint (handled by vacuum)

        Returns:
            Dict with maintenance results:
                - action: "vacuum"
                - status: "completed" or "failed"
                - db_path: Path to the database file
                - error: Error message if failed (optional)

        Raises:
            RuntimeError: If storage not initialized
        """
        if not self._initialized:
            await self.initialize()

        try:
            await self.vacuum()
            logger.info(
                "SQLiteEventProvider maintenance completed: %s",
                self._db_path,
            )
            return {
                "action": "vacuum",
                "status": "completed",
                "db_path": self._db_path,
            }
        except Exception as e:
            logger.error(
                "SQLiteEventProvider maintenance failed: %s - %s",
                self._db_path,
                e,
            )
            return {
                "action": "vacuum",
                "status": "failed",
                "db_path": self._db_path,
                "error": str(e),
            }
