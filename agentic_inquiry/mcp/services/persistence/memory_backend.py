"""In-memory session storage backend.

This module provides an in-memory implementation of SessionStorageProtocol,
primarily intended for testing purposes.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agentic_inquiry.mcp.models.session import Session
from agentic_inquiry.mcp.services.persistence.protocol import SessionStorageProtocol

logger = logging.getLogger(__name__)


class InMemorySessionStorage(SessionStorageProtocol):
    """In-memory session storage for testing.

    Stores sessions in a dictionary keyed by session_id.
    All data is lost when the instance is garbage collected.

    Thread safety: Not thread-safe. Use for single-threaded tests only.
    """

    def __init__(self) -> None:
        """Initialize in-memory storage."""
        self._sessions: Dict[str, Session] = {}

    async def persist_session(self, session: Session) -> None:
        """Store session in memory.

        Args:
            session: Session to persist
        """
        self._sessions[session.session_id] = session
        logger.debug(
            "Persisted session %s to memory (total: %d)",
            session.session_id,
            len(self._sessions),
        )

    async def load_session(self, session_id: str) -> Optional[Session]:
        """Load session from memory.

        Args:
            session_id: Session identifier

        Returns:
            Session object or None if not found
        """
        session = self._sessions.get(session_id)
        if session:
            logger.debug("Loaded session %s from memory", session_id)
        else:
            logger.debug("Session %s not found in memory", session_id)
        return session

    async def delete_session(self, session_id: str) -> bool:
        """Delete session from memory.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.debug("Deleted session %s from memory", session_id)
            return True
        return False

    async def list_sessions(
        self,
        project_id: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List sessions with optional filtering.

        Args:
            project_id: Filter by project ID (optional)
            include_expired: Whether to include expired sessions
            limit: Maximum number of sessions to return

        Returns:
            List of session metadata dictionaries
        """
        sessions = []
        for session in self._sessions.values():
            # Apply project_id filter
            if project_id and session.project_id != project_id:
                continue

            # Apply expired filter
            if not include_expired and session.is_expired:
                continue

            sessions.append(
                {
                    "session_id": session.session_id,
                    "project_id": session.project_id,
                    "created_at": session.created_at.isoformat(),
                    "last_active": session.last_active.isoformat(),
                    "description": session.description,
                    "is_expired": session.is_expired,
                    "age_hours": session.get_age_hours(),
                    "inactive_hours": session.get_inactive_hours(),
                }
            )

        # Sort by last_active (most recent first)
        sessions.sort(key=lambda s: str(s["last_active"]), reverse=True)

        # Apply limit
        return sessions[:limit]

    async def find_expired_sessions(
        self, ttl_hours: float, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Find sessions that have exceeded TTL.

        Args:
            ttl_hours: Time-to-live in hours
            limit: Maximum number to return

        Returns:
            List of expired session info dictionaries
        """
        expired = []
        cutoff_time = datetime.now() - timedelta(hours=ttl_hours)

        for session in self._sessions.values():
            # Skip already-expired sessions
            if session.is_expired:
                continue

            if session.last_active < cutoff_time:
                expired.append(
                    {
                        "session_id": session.session_id,
                        "project_id": session.project_id,
                        "age_hours": session.get_age_hours(),
                        "inactive_hours": session.get_inactive_hours(),
                    }
                )

                if len(expired) >= limit:
                    break

        return expired

    async def mark_session_expired(self, session_id: str) -> bool:
        """Mark session as expired in memory.

        Args:
            session_id: Session identifier

        Returns:
            True if marked, False if not found
        """
        session = self._sessions.get(session_id)
        if session:
            session.mark_expired()
            logger.debug("Marked session %s as expired", session_id)
            return True
        return False

    def clear(self) -> None:
        """Clear all sessions from memory.

        Useful for test cleanup.
        """
        count = len(self._sessions)
        self._sessions.clear()
        logger.debug("Cleared %d sessions from memory", count)

    @property
    def session_count(self) -> int:
        """Get number of sessions in memory."""
        return len(self._sessions)
