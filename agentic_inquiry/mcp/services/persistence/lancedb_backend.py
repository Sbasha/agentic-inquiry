"""LanceDB session storage backend.

This module provides a LanceDB-backed implementation of SessionStorageProtocol.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agentic_inquiry.database.filters import eq
from agentic_inquiry.database.filter_helpers import combine_filters
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.mcp.models.session import Session
from agentic_inquiry.mcp.services.persistence.protocol import (
    SessionStorageProtocol,
    StorageError,
)

logger = logging.getLogger(__name__)


class LanceDBSessionStorage(SessionStorageProtocol):
    """LanceDB-backed session storage.

    Stores sessions in the 'mcp_sessions' table using LanceDBManager.
    Provides upsert semantics for persistence and advanced filtering for queries.
    """

    TABLE_NAME = "mcp_sessions"

    def __init__(self, db_manager: StorageFacade):
        """Initialize LanceDB session storage.

        Args:
            db_manager: StorageFacade instance providing unified storage access.
                Must be configured with a LanceDB backend.

        Raises:
            ValueError: If the storage backend is not LanceDB.
        """
        # Guard: this backend is LanceDB-specific; reject non-LanceDB backends early
        backend_type = db_manager.get_backend_type() if hasattr(db_manager, "get_backend_type") else "lancedb"
        if backend_type != "lancedb":
            raise ValueError(
                f"LanceDBSessionStorage requires lancedb backend, got {backend_type!r}"
            )
        # Lazy import only when we know it is LanceDB (acceptable use per architecture doc)
        self.db_manager = db_manager.get_db_manager()
        logger.debug("LanceDBSessionStorage obtained LanceDBManager via get_db_manager()")

    async def persist_session(self, session: Session) -> None:
        """Persist session to LanceDB.

        Uses session.to_db_record() to convert to database format and
        db_manager.upsert() to insert or update the record.

        Args:
            session: Session to persist

        Raises:
            StorageError: If persistence fails
        """
        try:
            record = session.to_db_record()
            await self.db_manager.upsert(
                table_name=self.TABLE_NAME,
                data=[record],
                key_field="session_id"
            )
            logger.debug("Persisted session %s to database", session.session_id)
        except Exception as e:
            logger.error("Error persisting session %s: %s", session.session_id, e)
            message = f"Failed to persist session {session.session_id}"
            null_columns = await self._null_typed_columns()
            if null_columns:
                message += (
                    f": the {self.TABLE_NAME} table was created with null-typed "
                    f"columns {null_columns} and rejects values in them. Delete "
                    f"the {self.TABLE_NAME} table from the LanceDB directory; "
                    "sessions are recreated on demand."
                )
            raise StorageError(message, cause=e) from e

    async def _null_typed_columns(self) -> List[str]:
        """Columns an older release inferred as null from a session without values."""
        try:
            table = await self.db_manager.get_table(self.TABLE_NAME)
            if table is None:
                return []
            return [field.name for field in table.schema if str(field.type) == "null"]
        except Exception:
            return []

    async def load_session(self, session_id: str) -> Optional[Session]:
        """Load session from LanceDB by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session object or None if not found

        Raises:
            StorageError: If loading fails due to database issues
        """
        try:
            results = await self.db_manager.advanced_filter(
                table_name=self.TABLE_NAME,
                filters=eq("session_id", session_id),
                limit=1,
                project_id=None  # Search across all projects
            )

            if results:
                return Session.from_db_record(results[0])
            return None

        except Exception as e:
            logger.error(
                "Error loading session %s from database: %s",
                session_id, e
            )
            raise StorageError(
                f"Failed to load session {session_id}",
                cause=e
            ) from e

    async def delete_session(self, session_id: str) -> bool:
        """Delete session from LanceDB.

        Note: LanceDB doesn't have native delete, so we mark as expired.

        Args:
            session_id: Session identifier

        Returns:
            True if session was marked expired, False if not found
        """
        try:
            session = await self.load_session(session_id)
            if session:
                session.mark_expired()
                await self.persist_session(session)
                logger.debug("Marked session %s as deleted (expired)", session_id)
                return True
            return False
        except StorageError:
            return False
        except Exception as e:
            logger.error("Error deleting session %s: %s", session_id, e)
            raise StorageError(
                f"Failed to delete session {session_id}",
                cause=e
            ) from e

    async def list_sessions(
        self,
        project_id: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List sessions with optional filtering.

        Args:
            project_id: Filter by project ID (optional)
            include_expired: Whether to include expired sessions
            limit: Maximum number of sessions to return

        Returns:
            List of session metadata dictionaries
        """
        try:
            filter_ast = combine_filters(
                eq("project_id", project_id) if project_id else None,
                eq("is_expired", False) if not include_expired else None,
            )

            results = await self.db_manager.advanced_filter(
                table_name=self.TABLE_NAME,
                filters=filter_ast,
                limit=limit,
                project_id=None,  # project_id above is a column filter, not the manager scope
            )

            sessions = []
            for record in results:
                session = Session.from_db_record(record)
                sessions.append({
                    "session_id": session.session_id,
                    "project_id": session.project_id,
                    "created_at": session.created_at.isoformat(),
                    "last_active": session.last_active.isoformat(),
                    "description": session.description,
                    "is_expired": session.is_expired,
                    "age_hours": session.get_age_hours(),
                    "inactive_hours": session.get_inactive_hours()
                })

            # Sort by last_active (most recent first)
            sessions.sort(key=lambda s: str(s["last_active"]), reverse=True)

            return sessions

        except Exception as e:
            logger.error("Error listing sessions: %s", e)
            raise StorageError("Failed to list sessions", cause=e) from e

    async def find_expired_sessions(
        self,
        ttl_hours: float,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Find sessions that have exceeded TTL.

        Args:
            ttl_hours: Time-to-live in hours
            limit: Maximum number to return

        Returns:
            List of expired session info dictionaries
        """
        try:
            # Get all non-expired sessions
            results = await self.db_manager.advanced_filter(
                table_name=self.TABLE_NAME,
                filters=eq("is_expired", False),
                limit=limit,
                project_id=None,  # Sessions of every project expire
            )

            # Check each for expiry
            expired = []
            cutoff_time = datetime.now() - timedelta(hours=ttl_hours)

            for record in results:
                last_active = record.get("last_active")

                # Skip records without last_active timestamp
                if last_active is None:
                    continue

                # Convert to datetime if needed
                if isinstance(last_active, str):
                    last_active = datetime.fromisoformat(last_active)

                if last_active < cutoff_time:
                    session = Session.from_db_record(record)
                    expired.append({
                        "session_id": session.session_id,
                        "project_id": session.project_id,
                        "age_hours": session.get_age_hours(),
                        "inactive_hours": session.get_inactive_hours()
                    })

            return expired

        except Exception as e:
            logger.error("Error finding expired sessions: %s", e)
            raise StorageError("Failed to find expired sessions", cause=e) from e

    async def mark_session_expired(self, session_id: str) -> bool:
        """Mark session as expired in LanceDB.

        Args:
            session_id: Session identifier

        Returns:
            True if marked, False if session not found
        """
        try:
            session = await self.load_session(session_id)
            if session:
                session.mark_expired()
                await self.persist_session(session)
                logger.debug("Marked session %s as expired", session_id)
                return True
            return False
        except StorageError:
            return False
        except Exception as e:
            logger.error(
                "Error marking session %s as expired: %s",
                session_id, e
            )
            raise StorageError(
                f"Failed to mark session {session_id} as expired",
                cause=e
            ) from e
