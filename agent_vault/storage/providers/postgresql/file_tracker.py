"""PostgreSQL file tracker provider.

This module implements FileTrackerProtocol using PostgreSQL for persistent
file hash tracking, enabling change detection for incremental indexing.

Features:
    - SHA256-based content hashing for change detection
    - Project isolation via project_id
    - Sync wrappers for watchdog compatibility (using asyncio.run())
    - Efficient upsert with conflict handling

Table schema:
    - {prefix}f_file_hashes: File path to content hash mappings

Example:
    >>> manager = PostgresConnectionManager(connection_string="postgresql://...")
    >>> await manager.initialize()
    >>> tracker = PostgresFileTrackerProvider(manager, project_id="myproject")
    >>> await tracker.initialize()
    >>> if await tracker.has_changed("/path/to/file.py"):
    ...     await process_file("/path/to/file.py")
    ...     await tracker.update_hash("/path/to/file.py")
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agent_vault.storage.protocols.file_tracker import FileTrackerProtocol
from agent_vault.storage.providers.postgresql.schemas import (
    FILE_HASHES_TABLE,
    SchemaGenerator,
)

if TYPE_CHECKING:
    from agent_vault.storage.providers.postgresql.connection import (
        PostgresConnectionManager,
    )

logger = logging.getLogger(__name__)


class PostgresFileTrackerProvider(FileTrackerProtocol):
    """PostgreSQL implementation of file tracking.

    Uses asyncpg for native async PostgreSQL operations. File hashes are
    stored in a table with project isolation.

    Attributes:
        connection_manager: Shared PostgreSQL connection manager
        project_id: Project identifier for data isolation
        _initialized: Whether initialize() has been called
        _file_hashes_table: Full name of the file hashes table

    Thread Safety:
        Async operations are safe for concurrent access. For sync contexts
        (e.g., watchdog callbacks), use the *_sync methods which wrap
        async calls with asyncio.run().

        Important: The *_sync methods cannot be called from within an async
        context (e.g., from async functions or coroutines). They will raise
        RuntimeError if an event loop is already running. Use the async
        methods directly when in async code.

    Example:
        >>> tracker = PostgresFileTrackerProvider(manager, "myproject")
        >>> await tracker.initialize()
        >>> changed = await tracker.has_changed("/path/to/file.py")
    """

    SUPPORTED_ROLES = frozenset({"file_tracker"})

    def __init__(
        self,
        connection_manager: "PostgresConnectionManager",
        project_id: str,
        *,
        embedding_dim: int = 384,
    ) -> None:
        """Initialize PostgreSQL file tracker provider.

        Args:
            connection_manager: PostgresConnectionManager instance
            project_id: Project identifier for data isolation
            embedding_dim: Embedding dimension (not used for file tracker)
        """
        self._connection_manager = connection_manager
        self._project_id = project_id
        self._embedding_dim = embedding_dim
        self._initialized = False

        # Generate table names
        self._schema_generator = SchemaGenerator(
            prefix=connection_manager.table_prefix,
            embedding_dim=embedding_dim,
        )
        self._file_hashes_table = self._schema_generator.get_table_name(FILE_HASHES_TABLE)

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        project_id: str,
    ) -> "PostgresFileTrackerProvider":
        """Create provider from configuration dict.

        Supports both direct connection_string and host-based params
        (e.g. RDS direct connections with host, user, password fields).

        Args:
            config: Configuration with connection_string or host-based params
            project_id: Project ID for data isolation

        Returns:
            Configured PostgresFileTrackerProvider instance
        """
        from agent_vault.storage.providers.postgresql.connection import (
            PostgresConnectionManager,
        )
        from agent_vault.storage.providers.postgresql.vector import (
            PostgresVectorProvider,
        )

        resolved_config = dict(config)
        if not resolved_config.get("connection_string"):
            resolved_config["connection_string"] = PostgresVectorProvider._build_dsn_from_config(config)

        manager = PostgresConnectionManager.from_config(
            resolved_config,
            table_prefix=config.get("table_prefix", "agv_"),
        )

        return cls(
            connection_manager=manager,
            project_id=project_id,
            embedding_dim=config.get("embedding_dim", 384),
        )

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def project_id(self) -> str:
        """Project identifier for data isolation."""
        return self._project_id

    @property
    def db_path(self) -> str:
        """Path to database (returns connection string for PostgreSQL)."""
        return self._connection_manager.connection_string

    # =========================================================================
    # Lifecycle Operations
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize storage and create schema if needed.

        Creates the file hashes table and indexes if they don't exist.
        Idempotent - safe to call multiple times.

        Raises:
            IOError: If database initialization fails
        """
        if self._initialized:
            return

        try:
            # Ensure connection manager is initialized
            if not self._connection_manager.is_initialized:
                await self._connection_manager.initialize()

            # Create file tracker tables
            statements = self._schema_generator.get_create_statements("file_tracker")
            async with self._connection_manager.transaction() as conn:
                for stmt in statements:
                    await conn.execute(stmt)

            self._initialized = True
            logger.info(
                "PostgresFileTrackerProvider initialized for project %s",
                self._project_id,
            )

        except Exception as e:
            raise IOError(f"Failed to initialize file tracker: {e}") from e

    async def close(self) -> None:
        """Close storage connections and release resources.

        Note: Does not close the shared connection manager.
        """
        self._initialized = False
        logger.debug(
            "PostgresFileTrackerProvider closed for project %s", self._project_id
        )

    # =========================================================================
    # Hash Operations (Async)
    # =========================================================================

    async def get_hash(self, file_path: str) -> Optional[str]:
        """Get stored hash for a file in the current project.

        Args:
            file_path: Path to the file

        Returns:
            Stored hash string (SHA256 hex), or None if file not tracked
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        query = f"""
            SELECT content_hash FROM {self._file_hashes_table}
            WHERE project_id = $1 AND file_path = $2
        """

        try:
            result = await self._connection_manager.fetchval(
                query, self._project_id, file_path
            )
            return result

        except Exception as e:
            logger.error("Failed to get hash for %s: %s", file_path, e)
            return None

    async def update_hash(
        self,
        file_path: str,
        content_hash: Optional[str] = None,
    ) -> str:
        """Update or insert hash for a file in the current project.

        If content_hash is not provided, it is computed from the file.

        Args:
            file_path: Path to the file
            content_hash: Optional pre-computed hash. If None, compute from file.

        Returns:
            The hash that was stored

        Raises:
            FileNotFoundError: If file doesn't exist and hash not provided
            IOError: If file cannot be read
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        # Compute hash if not provided (use async version to avoid blocking event loop)
        if content_hash is None:
            content_hash = await self._compute_file_hash_async(file_path)

        # Get file metadata if available
        file_size = None
        modified_at = None
        try:
            stat = os.stat(file_path)
            file_size = stat.st_size
            modified_at = datetime.fromtimestamp(stat.st_mtime)
        except OSError:
            pass  # File may not exist if hash was provided

        # Generate ID for upsert
        record_id = self._generate_id(file_path)

        query = f"""
            INSERT INTO {self._file_hashes_table} (
                id, project_id, file_path, content_hash, file_size, modified_at
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (project_id, file_path) DO UPDATE SET
                content_hash = EXCLUDED.content_hash,
                file_size = EXCLUDED.file_size,
                modified_at = EXCLUDED.modified_at,
                indexed_at = NOW()
        """

        try:
            await self._connection_manager.execute(
                query,
                record_id,
                self._project_id,
                file_path,
                content_hash,
                file_size,
                modified_at,
            )
            logger.debug("Updated hash for %s: %s", file_path, content_hash[:16])
            return content_hash

        except Exception as e:
            raise IOError(f"Failed to update hash for {file_path}: {e}") from e

    async def has_changed(self, file_path: str) -> bool:
        """Check if file has changed since last tracking.

        Compares current file hash with stored hash.

        Args:
            file_path: Path to the file

        Returns:
            True if file has changed or is not tracked, False otherwise

        Note:
            If file doesn't exist or can't be read, returns True.
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        try:
            # Compute current hash (use async version to avoid blocking event loop)
            current_hash = await self._compute_file_hash_async(file_path)
        except (FileNotFoundError, IOError):
            # Conservative behavior: assume change if file can't be read
            return True

        # Get stored hash
        stored_hash = await self.get_hash(file_path)

        if stored_hash is None:
            # File not tracked = consider changed
            return True

        return current_hash != stored_hash

    async def remove_file(self, file_path: str) -> bool:
        """Remove a file from tracking in the current project.

        Args:
            file_path: Path to the file

        Returns:
            True if file was tracked and removed, False if not tracked
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        query = f"""
            DELETE FROM {self._file_hashes_table}
            WHERE project_id = $1 AND file_path = $2
        """

        try:
            result = await self._connection_manager.execute(
                query, self._project_id, file_path
            )
            # Parse "DELETE N" result
            deleted = int(result.split()[-1]) if result else 0
            return deleted > 0

        except Exception as e:
            logger.error("Failed to remove file %s: %s", file_path, e)
            return False

    async def list_tracked_files(self) -> List[Tuple[str, str]]:
        """List all tracked files and their hashes in the current project.

        Returns:
            List of (file_path, content_hash) tuples
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        query = f"""
            SELECT file_path, content_hash FROM {self._file_hashes_table}
            WHERE project_id = $1
            ORDER BY file_path
        """

        try:
            rows = await self._connection_manager.fetch(query, self._project_id)
            return [(row["file_path"], row["content_hash"]) for row in rows]

        except Exception as e:
            logger.error("Failed to list tracked files: %s", e)
            return []

    async def clear(self) -> None:
        """Clear all tracked files from the current project.

        Note: This only clears files for the current project_id.
        """
        if not self._initialized:
            raise RuntimeError("Provider not initialized. Call initialize() first.")

        query = f"""
            DELETE FROM {self._file_hashes_table}
            WHERE project_id = $1
        """

        try:
            result = await self._connection_manager.execute(query, self._project_id)
            deleted = int(result.split()[-1]) if result else 0
            logger.info(
                "Cleared %d tracked files for project %s", deleted, self._project_id
            )

        except Exception as e:
            raise IOError(f"Failed to clear tracked files: {e}") from e

    # =========================================================================
    # Synchronous Wrappers (for watchdog compatibility)
    # =========================================================================

    def _check_not_in_async_context(self, method_name: str) -> None:
        """Check that we're not being called from an async context.

        Raises RuntimeError with helpful message if called from within an
        existing event loop (e.g., from an async function or coroutine).

        Args:
            method_name: Name of the sync wrapper method for error message

        Raises:
            RuntimeError: If called from within an async context
        """
        try:
            asyncio.get_running_loop()
            # If we get here, there's a running loop - raise error
            raise RuntimeError(
                f"{method_name}() cannot be called from an async context "
                f"(existing event loop detected). Use the async version instead: "
                f"{method_name.replace('_sync', '')}()"
            )
        except RuntimeError as e:
            # "no running event loop" means we're safe to use asyncio.run()
            if "no running event loop" not in str(e):
                raise

    def get_hash_sync(self, file_path: str) -> Optional[str]:
        """Synchronous wrapper for get_hash.

        Warning:
            Cannot be called from an async context. Use get_hash() instead
            when in async code.

        Args:
            file_path: Path to the file

        Returns:
            Stored hash string, or None if file not tracked

        Raises:
            RuntimeError: If called from within an async context
        """
        self._check_not_in_async_context("get_hash_sync")
        return asyncio.run(self.get_hash(file_path))

    def update_hash_sync(
        self,
        file_path: str,
        content_hash: Optional[str] = None,
    ) -> str:
        """Synchronous wrapper for update_hash.

        Warning:
            Cannot be called from an async context. Use update_hash() instead
            when in async code.

        Args:
            file_path: Path to the file
            content_hash: Optional pre-computed hash

        Returns:
            The hash that was stored

        Raises:
            RuntimeError: If called from within an async context
        """
        self._check_not_in_async_context("update_hash_sync")
        return asyncio.run(self.update_hash(file_path, content_hash))

    def has_changed_sync(self, file_path: str) -> bool:
        """Synchronous wrapper for has_changed.

        Warning:
            Cannot be called from an async context. Use has_changed() instead
            when in async code.

        Args:
            file_path: Path to the file

        Returns:
            True if file has changed or is not tracked

        Raises:
            RuntimeError: If called from within an async context
        """
        self._check_not_in_async_context("has_changed_sync")
        return asyncio.run(self.has_changed(file_path))

    def remove_file_sync(self, file_path: str) -> bool:
        """Synchronous wrapper for remove_file.

        Warning:
            Cannot be called from an async context. Use remove_file() instead
            when in async code.

        Args:
            file_path: Path to the file

        Returns:
            True if file was tracked and removed

        Raises:
            RuntimeError: If called from within an async context
        """
        self._check_not_in_async_context("remove_file_sync")
        return asyncio.run(self.remove_file(file_path))

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _compute_file_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of file contents (blocking I/O).

        This is a synchronous method that performs blocking file I/O.
        For async contexts, use _compute_file_hash_async() instead.

        Args:
            file_path: Path to the file

        Returns:
            SHA256 hash as hex string

        Raises:
            FileNotFoundError: If file doesn't exist
            IOError: If file cannot be read
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            raise IOError(f"Failed to read file {file_path}: {e}") from e

    async def _compute_file_hash_async(self, file_path: str) -> str:
        """Compute SHA256 hash of file contents asynchronously.

        Uses asyncio.to_thread() to run blocking file I/O in a thread pool,
        preventing event loop blocking during file reads.

        Args:
            file_path: Path to the file

        Returns:
            SHA256 hash as hex string

        Raises:
            FileNotFoundError: If file doesn't exist
            IOError: If file cannot be read
        """
        return await asyncio.to_thread(self._compute_file_hash, file_path)

    def _generate_id(self, file_path: str) -> str:
        """Generate unique ID for a file record.

        Uses project_id + file_path hash for deterministic IDs.

        Args:
            file_path: Path to the file

        Returns:
            Unique ID string
        """
        combined = f"{self._project_id}:{file_path}"
        return hashlib.sha256(combined.encode()).hexdigest()[:32]

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"PostgresFileTrackerProvider("
            f"project_id={self._project_id!r}, "
            f"initialized={self._initialized})"
        )
