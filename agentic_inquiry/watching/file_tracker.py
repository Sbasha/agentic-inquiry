"""SQLite-based file state tracker for hash-based change detection.

This module provides a persistent tracker that stores file paths and their
content hashes in a SQLite database. It uses SHA256 hashing instead of
modification time for more reliable change detection.

The tracker supports project isolation via project_id, allowing multiple
projects to share the same database while keeping their data separate.
"""

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple, Union, Any

import aiosqlite

if TYPE_CHECKING:
    from agentic_inquiry.config import Config

logger = logging.getLogger(__name__)


class FileTracker:
    """Track file states using SQLite database with SHA256 hashing.
    
    This tracker stores file paths and their content hashes to detect changes
    more reliably than using modification time or file size.
    
    Supports project isolation via project_id, allowing multiple projects to
    share the same database while keeping their data separate.
    
    Attributes:
        db_path: Path to the SQLite database file
        project_id: Project identifier for data isolation
    """
    
    def __init__(
        self,
        config: Optional["Config"] = None,
        project_id: Optional[str] = None,
        db_path: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ):
        """Initialize the file tracker.

        Note: This constructor does NOT initialize the database. Use the async
        `initialize()` method or the factory method `from_config()` after construction.
        
        Args:
            config: Optional Config instance. If None, loads default configuration.
            project_id: Project ID for data isolation. If None, uses
                config.storage.default_project_id.
            db_path: Optional path to SQLite database file. If None, uses
                config.storage.get_file_tracker_path().
            **kwargs: Additional configuration options (ignored).
        """
        # Import here to avoid circular dependency
        from agentic_inquiry.config import Config
        
        # Load config if not provided
        if config is None:
            config = Config.load()
        
        self.config = config
        
        # Resolve project_id
        if project_id is None:
            project_id = config.storage.default_project_id
            if not project_id:
                raise ValueError(
                    "project_id must be provided or set as storage.default_project_id in configuration"
                )
        
        self.project_id = project_id
        
        # Determine database path
        if db_path is None:
            db_path = self.config.storage.get_file_tracker_path()
        
        self.db_path = str(Path(db_path).expanduser().resolve())

        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Lifecycle management
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the file tracker database (public API).

        This method initializes the database schema. It is safe to call multiple
        times - subsequent calls will be no-ops.

        This is the recommended explicit initialization method when not using
        the `from_config()` factory method.
        """
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return
            await self._init_database()
            self._initialized = True

    @classmethod
    async def from_config(
        cls,
        config: Optional["Config"] = None,
        project_id: Optional[str] = None,
        db_path: Optional[Union[str, Path]] = None,
    ) -> "FileTracker":
        """Create and initialize a FileTracker instance asynchronously.

        This is the recommended way to create a FileTracker instance as it
        properly initializes the database asynchronously.

        Args:
            config: Optional Config instance. If None, loads default configuration.
            project_id: Project ID for data isolation. If None, uses
                config.storage.default_project_id.
            db_path: Optional path to SQLite database file. If None, uses
                config.storage.get_file_tracker_path().

        Returns:
            Initialized FileTracker instance
        """
        tracker = cls(config=config, project_id=project_id, db_path=db_path)
        await tracker.initialize()
        return tracker
    
    async def _init_database(self) -> None:
        """Initialize the SQLite database schema with project isolation.
        
        Creates the file_states table with project_id column and composite
        primary key. Handles migration from legacy schema without project_id.
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.cursor()
            
            # Check if table exists and has project_id column
            await cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='file_states'
            """)
            table_exists = await cursor.fetchone() is not None
            
            if table_exists:
                # Check if project_id column exists
                await cursor.execute("PRAGMA table_info(file_states)")
                columns = [row[1] for row in await cursor.fetchall()]
                
                if 'project_id' not in columns:
                    # Migrate legacy schema to new schema with project_id
                    logger.info("Migrating FileTracker database to include project_id")
                    await self._migrate_schema(cursor)
                else:
                    logger.debug("FileTracker database already has project_id column")
            else:
                # Create new table with project_id
                await cursor.execute("""
                    CREATE TABLE file_states (
                        project_id TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (project_id, file_path)
                    )
                """)
                logger.debug("Created file_states table with project_id at %s", self.db_path)
            
            await conn.commit()
        logger.debug("Initialized file tracker database at %s", self.db_path)
    
    async def _migrate_schema(self, cursor: aiosqlite.Cursor) -> None:
        """Migrate legacy schema to include project_id column.
        
        This migration:
        1. Creates a new table with project_id
        2. Copies existing data with current project_id
        3. Drops old table
        4. Renames new table
        
        Args:
            cursor: aiosqlite cursor for executing migration queries
        """
        # Create new table with project_id
        await cursor.execute("""
            CREATE TABLE file_states_new (
                project_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (project_id, file_path)
            )
        """)
        
        # Copy existing data with current project_id
        await cursor.execute("""
            INSERT INTO file_states_new (project_id, file_path, content_hash, last_updated)
            SELECT ?, file_path, content_hash, last_updated
            FROM file_states
        """, (self.project_id,))
        
        # Drop old table
        await cursor.execute("DROP TABLE file_states")
        
        # Rename new table
        await cursor.execute("ALTER TABLE file_states_new RENAME TO file_states")
        
        logger.info("Migrated %s records to new schema with project_id=%s", cursor.rowcount, self.project_id)
    
    async def _compute_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of file content asynchronously.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Hexadecimal SHA256 hash string
            
        Raises:
            FileNotFoundError: If file doesn't exist
            IOError: If file cannot be read
        """
        def _hash_file(path: str) -> str:
            """Synchronous hash computation to run in executor."""
            sha256 = hashlib.sha256()
            with open(path, 'rb') as f:
                # Read in chunks to handle large files efficiently
                while chunk := f.read(8192):
                    sha256.update(chunk)
            return sha256.hexdigest()
        
        try:
            # Run CPU-bound hashing in executor to avoid blocking event loop
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _hash_file, file_path)
        except FileNotFoundError:
            logger.error("File not found: %s", file_path)
            raise
        except Exception as e:
            logger.error("Failed to compute hash for %s: %s", file_path, e)
            raise IOError(f"Cannot read file {file_path}") from e
    
    async def get_hash(self, file_path: str) -> Optional[str]:
        """Get stored hash for a file in the current project.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Stored hash string, or None if file not tracked in current project
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "SELECT content_hash FROM file_states WHERE project_id = ? AND file_path = ?",
                (self.project_id, file_path)
            )
            result = await cursor.fetchone()
            return result[0] if result else None
    
    async def update_hash(self, file_path: str, content_hash: Optional[str] = None) -> str:
        """Update or insert hash for a file in the current project.
        
        If content_hash is not provided, it will be computed from the file.
        
        Args:
            file_path: Path to the file
            content_hash: Optional pre-computed hash (will compute if None)
            
        Returns:
            The hash that was stored
            
        Raises:
            FileNotFoundError: If file doesn't exist and hash not provided
            IOError: If file cannot be read
        """
        if content_hash is None:
            content_hash = await self._compute_hash(file_path)
        
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.cursor()
            await cursor.execute("""
                INSERT INTO file_states (project_id, file_path, content_hash, last_updated)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(project_id, file_path) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    last_updated = CURRENT_TIMESTAMP
            """, (self.project_id, file_path, content_hash))
            await conn.commit()
        
        logger.debug("Updated hash for %s in project %s: %s...", file_path, self.project_id, content_hash[:8])
        return content_hash
    
    async def has_changed(self, file_path: str) -> bool:
        """Check if file has changed since last tracking.
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if file has changed or is not tracked, False otherwise
        """
        try:
            stored_hash = await self.get_hash(file_path)
            if stored_hash is None:
                # File not tracked yet
                return True
            
            current_hash = await self._compute_hash(file_path)
            return current_hash != stored_hash
        except (FileNotFoundError, IOError):
            # If file doesn't exist or can't be read, consider it changed
            return True
    
    async def remove_file(self, file_path: str) -> bool:
        """Remove a file from tracking in the current project.
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if file was tracked and removed, False if not tracked in current project
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "DELETE FROM file_states WHERE project_id = ? AND file_path = ?",
                (self.project_id, file_path)
            )
            await conn.commit()
            removed = cursor.rowcount > 0
        
        if removed:
            logger.debug("Removed %s from tracking in project %s", file_path, self.project_id)
        return removed
    
    async def list_tracked_files(self) -> List[Tuple[str, str]]:
        """List all tracked files and their hashes in the current project.

        Returns:
            List of (file_path, content_hash) tuples for current project
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "SELECT file_path, content_hash FROM file_states WHERE project_id = ?",
                (self.project_id,)
            )
            rows = await cursor.fetchall()
            return [(str(row[0]), str(row[1])) for row in rows]
    
    async def clear(self) -> None:
        """Clear all tracked files from the current project.
        
        Note: This only clears files for the current project_id, not all projects.
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.cursor()
            await cursor.execute("DELETE FROM file_states WHERE project_id = ?", (self.project_id,))
            await conn.commit()
        logger.info("Cleared all tracked files for project %s", self.project_id)
    
    async def close(self) -> None:
        """Close the database connection.
        
        Note: This is a no-op since we use context managers for connections.
        Provided for API compatibility.
        """
        pass

    # Synchronous wrappers for use in sync contexts (e.g., watchdog callbacks)
    
    def update_hash_sync(self, file_path: str, content_hash: Optional[str] = None) -> str:
        """Synchronous wrapper for update_hash.
        
        This method runs the async update_hash in a new event loop.
        Use this when calling from synchronous code (e.g., watchdog callbacks).
        
        Args:
            file_path: Path to the file
            content_hash: Optional pre-computed hash (will compute if None)
            
        Returns:
            The hash that was stored
        """
        return asyncio.run(self.update_hash(file_path, content_hash))
    
    def has_changed_sync(self, file_path: str) -> bool:
        """Synchronous wrapper for has_changed.
        
        This method runs the async has_changed in a new event loop.
        Use this when calling from synchronous code (e.g., watchdog callbacks).
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if file has changed or is not tracked, False otherwise
        """
        return asyncio.run(self.has_changed(file_path))
    
    def remove_file_sync(self, file_path: str) -> bool:
        """Synchronous wrapper for remove_file.
        
        This method runs the async remove_file in a new event loop.
        Use this when calling from synchronous code (e.g., watchdog callbacks).
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if file was tracked and removed, False if not tracked
        """
        return asyncio.run(self.remove_file(file_path))
