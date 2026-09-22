"""Session storage protocol definition.

This module defines the abstract interface for session storage backends.
Implementations can use LanceDB, SQLite, in-memory storage, or other backends.
"""

from abc import abstractmethod
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from agent_vault.mcp.models.session import Session


@runtime_checkable
class SessionStorageProtocol(Protocol):
    """Protocol for session storage backends.

    Defines the required operations for persisting and retrieving sessions.
    All methods are async to support both synchronous and asynchronous backends.

    Implementations:
    - LanceDBSessionStorage: Production storage using LanceDB
    - InMemorySessionStorage: Testing storage using in-memory dict
    """

    @abstractmethod
    async def persist_session(self, session: Session) -> None:
        """Persist a session to storage.

        Creates a new record or updates an existing one based on session_id.

        Args:
            session: Session object to persist

        Raises:
            StorageError: If persistence fails
        """
        ...

    @abstractmethod
    async def load_session(self, session_id: str) -> Optional[Session]:
        """Load a session from storage by ID.

        Args:
            session_id: Unique session identifier

        Returns:
            Session object if found, None otherwise

        Raises:
            StorageError: If loading fails due to storage issues
        """
        ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session from storage.

        Args:
            session_id: Unique session identifier

        Returns:
            True if deleted, False if session was not found

        Raises:
            StorageError: If deletion fails
        """
        ...

    @abstractmethod
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
            List of session metadata dictionaries with keys:
            - session_id: str
            - project_id: str
            - created_at: str (ISO format)
            - last_active: str (ISO format)
            - description: Optional[str]
            - is_expired: bool
            - age_hours: float
            - inactive_hours: float

        Raises:
            StorageError: If query fails
        """
        ...

    @abstractmethod
    async def find_expired_sessions(
        self,
        ttl_hours: float,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Find sessions that have exceeded TTL.

        Args:
            ttl_hours: Time-to-live in hours after which sessions are expired
            limit: Maximum number of expired sessions to return

        Returns:
            List of expired session info dictionaries with keys:
            - session_id: str
            - project_id: str
            - age_hours: float
            - inactive_hours: float

        Raises:
            StorageError: If query fails
        """
        ...

    @abstractmethod
    async def mark_session_expired(self, session_id: str) -> bool:
        """Mark a session as expired in storage.

        Updates the session's is_expired flag to True.

        Args:
            session_id: Unique session identifier

        Returns:
            True if marked, False if session was not found

        Raises:
            StorageError: If update fails
        """
        ...


class StorageError(Exception):
    """Exception raised when storage operations fail."""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        """Initialize storage error.

        Args:
            message: Error description
            cause: Optional underlying exception
        """
        super().__init__(message)
        self.cause = cause
