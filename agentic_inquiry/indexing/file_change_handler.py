"""File change handler for incremental re-indexing.

This module provides the FileChangeHandler class that coordinates file system
changes with the indexing pipeline to enable real-time, incremental re-indexing.

Design Reference:
    DES-S4-001 in .sessions/deep-architecture-review/009-design.md
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentic_inquiry.watching.file_tracker import FileTracker

if TYPE_CHECKING:
    from agentic_inquiry.database.protocols import IndexingDatabaseProtocol
    from agentic_inquiry.events import EventSystem
    from agentic_inquiry.indexing.pipeline import IndexingPipeline
    from agentic_inquiry.parsers.chain import ParserChain

logger = logging.getLogger(__name__)


class FileChangeHandler:
    """Handles file system changes with incremental re-indexing.

    This class coordinates between file watching infrastructure and the
    indexing pipeline to provide real-time, incremental updates when files
    are created, modified, or deleted.

    Features:
        - Debouncing: Prevents re-index storms by delaying processing and
          cancelling pending operations for the same file
        - Hash-based change detection: Uses FileTracker to detect actual
          content changes vs. metadata-only changes
        - Incremental updates: Only re-indexes changed files, not the entire
          project
        - Deletion handling: Removes all data associated with deleted files

    Attributes:
        pipeline: IndexingPipeline for re-indexing files
        db: Database adapter implementing IndexingDatabaseProtocol
        file_tracker: FileTracker for hash-based change detection
        debounce_seconds: Delay before processing file changes
        project_id: Project identifier for data isolation

    Example:
        >>> handler = FileChangeHandler(
        ...     pipeline=pipeline,
        ...     db=db_adapter,
        ...     project_id="my_project",
        ...     debounce_seconds=1.0,
        ... )
        >>> await handler.initialize()
        >>>
        >>> # Register with file watcher
        >>> watcher.register_callback(handler.on_file_change_sync)
        >>>
        >>> # Or call directly in async context
        >>> await handler.on_file_change("/path/to/file.py", "modified")
    """

    def __init__(
        self,
        pipeline: "IndexingPipeline",
        db: "IndexingDatabaseProtocol",
        project_id: str,
        *,
        parser_chain: Optional["ParserChain"] = None,
        file_tracker: Optional[FileTracker] = None,
        event_system: Optional["EventSystem"] = None,
        debounce_seconds: float = 1.0,
        project_root: Optional[str] = None,
        file_patterns: Optional[List[str]] = None,
        ignore_patterns: Optional[List[str]] = None,
    ) -> None:
        """Initialize the file change handler.

        Args:
            pipeline: IndexingPipeline instance for re-indexing
            db: Database adapter implementing IndexingDatabaseProtocol
            project_id: Project identifier for data isolation
            parser_chain: Optional ParserChain for parsing files.
                If None, creates one from config during initialization.
            file_tracker: Optional FileTracker for hash-based change detection.
                If None, creates one using project_id.
            event_system: Optional EventSystem for event emission
            debounce_seconds: Delay in seconds before processing file changes.
                Default is 1.0 second.
            project_root: Project root directory for path validation.
                Defaults to pipeline.project_root.
            file_patterns: Optional list of glob patterns for files to process.
                If None, processes all files.
            ignore_patterns: Optional list of glob patterns to ignore.
                If None, uses default ignore patterns.
        """
        self._pipeline = pipeline
        self._db = db
        self._project_id = project_id
        self._event_system = event_system
        self._debounce_seconds = debounce_seconds
        self._project_root = project_root or pipeline.project_root
        self._file_patterns = file_patterns
        self._ignore_patterns = ignore_patterns or self._default_ignore_patterns()

        # Parser chain for parsing files
        self._parser_chain = parser_chain

        # File tracker for hash-based change detection
        self._file_tracker_external = file_tracker is not None
        self._file_tracker = file_tracker

        # Pending tasks for debouncing
        self._pending_tasks: Dict[str, asyncio.Task[None]] = {}
        self._pending_lock = asyncio.Lock()

        # Statistics
        self._stats = {
            "files_created": 0,
            "files_modified": 0,
            "files_deleted": 0,
            "files_skipped_unchanged": 0,
            "files_skipped_pattern": 0,
            "errors": 0,
        }

        # Lifecycle
        self._initialized = False
        self._init_lock = asyncio.Lock()

    @staticmethod
    def _default_ignore_patterns() -> List[str]:
        """Return default patterns to ignore."""
        return [
            "*.pyc",
            "__pycache__/*",
            ".git/*",
            ".venv/*",
            "venv/*",
            "node_modules/*",
            ".pytest_cache/*",
            "*.egg-info/*",
            ".mypy_cache/*",
            ".ruff_cache/*",
            "vector_db/*",
            ".agentic-inquiry/*",
        ]

    async def initialize(self) -> None:
        """Initialize the file change handler and its dependencies.

        This method initializes the FileTracker and ParserChain if they were
        not provided to the constructor. It is safe to call multiple times.

        Raises:
            RuntimeError: If initialization fails
        """
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            try:
                # Initialize file tracker if not provided
                if self._file_tracker is None:
                    self._file_tracker = await FileTracker.from_config(
                        project_id=self._project_id,
                    )

                # Initialize parser chain if not provided
                if self._parser_chain is None:
                    from agentic_inquiry.parsers.chain import ParserChain

                    self._parser_chain = ParserChain.from_config()

                self._initialized = True
                logger.info(
                    "FileChangeHandler initialized for project %s",
                    self._project_id,
                )

            except Exception as e:
                logger.error(
                    "Failed to initialize FileChangeHandler: %s",
                    e,
                    exc_info=True,
                )
                raise RuntimeError(
                    f"FileChangeHandler initialization failed: {e}"
                ) from e

    @classmethod
    async def from_config(
        cls,
        pipeline: "IndexingPipeline",
        db: "IndexingDatabaseProtocol",
        project_id: str,
        **kwargs: Any,
    ) -> "FileChangeHandler":
        """Create and initialize a FileChangeHandler instance.

        This is the recommended way to create a FileChangeHandler as it
        properly initializes all dependencies.

        Args:
            pipeline: IndexingPipeline instance
            db: Database adapter
            project_id: Project identifier
            **kwargs: Additional arguments passed to constructor

        Returns:
            Initialized FileChangeHandler instance
        """
        handler = cls(
            pipeline=pipeline,
            db=db,
            project_id=project_id,
            **kwargs,
        )
        await handler.initialize()
        return handler

    @property
    def project_id(self) -> str:
        """Return the project ID."""
        return self._project_id

    @property
    def debounce_seconds(self) -> float:
        """Return the debounce delay in seconds."""
        return self._debounce_seconds

    @property
    def stats(self) -> Dict[str, int]:
        """Return statistics about processed files."""
        return self._stats.copy()

    @property
    def pending_count(self) -> int:
        """Return the number of pending file changes."""
        return len(self._pending_tasks)

    async def on_file_change(self, file_path: str, event_type: str) -> None:
        """Handle a file change event with debouncing.

        This method schedules file processing after a debounce delay. If
        another event arrives for the same file before the delay expires,
        the previous pending operation is cancelled.

        Args:
            file_path: Path to the changed file
            event_type: Type of event ("created", "modified", or "deleted")
        """
        if not self._initialized:
            logger.warning(
                "FileChangeHandler not initialized, ignoring event for %s",
                file_path,
            )
            return

        # Check if file matches patterns
        if not self._should_process(file_path):
            logger.debug(
                "Skipping file change for %s (pattern mismatch)",
                file_path,
            )
            self._stats["files_skipped_pattern"] += 1
            return

        logger.debug(
            "File change event: %s (%s), scheduling with %.1fs debounce",
            file_path,
            event_type,
            self._debounce_seconds,
        )

        async with self._pending_lock:
            # Cancel any pending task for this file
            if file_path in self._pending_tasks:
                self._pending_tasks[file_path].cancel()
                try:
                    await self._pending_tasks[file_path]
                except asyncio.CancelledError:
                    pass
                del self._pending_tasks[file_path]

            # Schedule new debounced task
            self._pending_tasks[file_path] = asyncio.create_task(
                self._process_after_debounce(file_path, event_type)
            )

    def on_file_change_sync(self, file_path: str, event_type: str) -> None:
        """Synchronous callback for file watcher integration.

        This method can be registered directly with FileWatcher.register_callback().
        It schedules the async handler on the event loop.

        Args:
            file_path: Path to the changed file
            event_type: Type of event ("created", "modified", or "deleted")
        """
        try:
            # Check if there's a running event loop
            loop = asyncio.get_running_loop()
            # Schedule the async handler
            loop.create_task(self.on_file_change(file_path, event_type))
        except RuntimeError:
            # No running event loop - log warning
            logger.warning(
                "Cannot schedule file change handler for %s: no event loop",
                file_path,
            )

    def _should_process(self, file_path: str) -> bool:
        """Check if a file should be processed based on patterns.

        Args:
            file_path: Path to check

        Returns:
            True if file should be processed, False otherwise
        """
        from fnmatch import fnmatch

        path = Path(file_path)

        # Check ignore patterns
        for pattern in self._ignore_patterns:
            # Match against full path and filename
            if fnmatch(str(path), pattern) or fnmatch(path.name, pattern):
                return False

            # For directory patterns (ending with /*), check if any path
            # component matches the directory name
            if pattern.endswith("/*"):
                dir_pattern = pattern[:-2]  # Remove /*
                # Check each component of the path
                for part in path.parts:
                    if fnmatch(part, dir_pattern):
                        return False

        # Check include patterns if specified
        if self._file_patterns:
            for pattern in self._file_patterns:
                if fnmatch(str(path), pattern) or fnmatch(path.name, pattern):
                    return True
            return False

        return True

    async def _process_after_debounce(
        self,
        file_path: str,
        event_type: str,
    ) -> None:
        """Process a file change after the debounce delay.

        Args:
            file_path: Path to the changed file
            event_type: Type of event
        """
        try:
            await asyncio.sleep(self._debounce_seconds)

            if event_type == "deleted":
                await self._handle_deletion(file_path)
            else:
                await self._handle_update(file_path, event_type)

        except asyncio.CancelledError:
            # Task was cancelled by a newer event - this is expected
            raise

        except Exception as e:
            logger.error(
                "Error processing file change for %s: %s",
                file_path,
                e,
                exc_info=True,
            )
            self._stats["errors"] += 1

        finally:
            # Remove from pending tasks
            async with self._pending_lock:
                if file_path in self._pending_tasks:
                    del self._pending_tasks[file_path]

    async def _handle_deletion(self, file_path: str) -> None:
        """Handle a file deletion by removing all associated data.

        Args:
            file_path: Path to the deleted file
        """
        logger.info("Handling deletion of file: %s", file_path)

        try:
            # Remove from database
            count = await self._db.delete_by_file(file_path, self._project_id)
            logger.info(
                "Removed %d records for deleted file: %s",
                count,
                file_path,
            )

            # Remove from file tracker
            if self._file_tracker:
                await self._file_tracker.remove_file(file_path)

            # Emit event if event system available
            if self._event_system:
                await self._event_system.emit(
                    "indexing.file_deleted",
                    source="FileChangeHandler",
                    file_path=file_path,
                    records_deleted=count,
                )

            self._stats["files_deleted"] += 1

        except Exception as e:
            logger.error(
                "Failed to handle deletion for %s: %s",
                file_path,
                e,
                exc_info=True,
            )
            raise

    async def _handle_update(self, file_path: str, event_type: str) -> None:
        """Handle a file creation or modification.

        This method checks if the file has actually changed using hash-based
        detection, then re-indexes if necessary.

        Args:
            file_path: Path to the created/modified file
            event_type: Either "created" or "modified"
        """
        logger.info("Handling %s for file: %s", event_type, file_path)

        try:
            # Check if file exists
            path = Path(file_path)
            if not path.exists():
                logger.warning(
                    "File no longer exists, skipping: %s",
                    file_path,
                )
                return

            if not path.is_file():
                logger.debug("Not a regular file, skipping: %s", file_path)
                return

            # For modified events, check if content actually changed
            if event_type == "modified" and self._file_tracker:
                has_changed = await self._file_tracker.has_changed(file_path)
                if not has_changed:
                    logger.debug(
                        "File content unchanged (hash match), skipping: %s",
                        file_path,
                    )
                    self._stats["files_skipped_unchanged"] += 1
                    return

            # Parse the file
            parsed_doc = await self._parse_file(file_path)
            if parsed_doc is None:
                logger.warning("Failed to parse file: %s", file_path)
                return

            # Re-index the document (removes old data and adds new)
            await self._pipeline.reindex_document(parsed_doc)

            # Flush pending relationships
            await self._pipeline.flush_pending_relationships()

            # Update file tracker hash
            if self._file_tracker:
                await self._file_tracker.update_hash(file_path)

            # Emit event
            if self._event_system:
                await self._event_system.emit(
                    f"indexing.file_{event_type}",
                    source="FileChangeHandler",
                    file_path=file_path,
                    chunks_created=len(parsed_doc.chunks),
                )

            if event_type == "created":
                self._stats["files_created"] += 1
            else:
                self._stats["files_modified"] += 1

            logger.info(
                "Successfully re-indexed file: %s (%d chunks)",
                file_path,
                len(parsed_doc.chunks),
            )

        except Exception as e:
            logger.error(
                "Failed to handle %s for %s: %s",
                event_type,
                file_path,
                e,
                exc_info=True,
            )
            raise

    async def _parse_file(self, file_path: str) -> Optional[Any]:
        """Parse a file using the parser chain.

        Args:
            file_path: Path to the file to parse

        Returns:
            ParsedDocument if successful, None otherwise
        """
        if self._parser_chain is None:
            logger.error("Parser chain not initialized")
            return None

        try:
            return await self._parser_chain.parse(
                file_path,
                db_manager=self._db,
                project_id=self._project_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to parse file %s: %s",
                file_path,
                e,
                exc_info=True,
            )
            return None

    async def wait_for_pending(self, timeout: Optional[float] = None) -> bool:
        """Wait for all pending file changes to be processed.

        This is useful for testing or graceful shutdown.

        Args:
            timeout: Maximum time to wait in seconds. If None, waits indefinitely.

        Returns:
            True if all pending tasks completed, False if timeout occurred
        """
        async with self._pending_lock:
            tasks = list(self._pending_tasks.values())

        if not tasks:
            return True

        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def cancel_pending(self) -> int:
        """Cancel all pending file change tasks.

        Returns:
            Number of tasks cancelled
        """
        async with self._pending_lock:
            count = len(self._pending_tasks)
            for task in self._pending_tasks.values():
                task.cancel()
            self._pending_tasks.clear()

        if count > 0:
            logger.info("Cancelled %d pending file change tasks", count)

        return count

    def reset_stats(self) -> None:
        """Reset all statistics to zero."""
        for key in self._stats:
            self._stats[key] = 0

    async def shutdown(self) -> None:
        """Shutdown the handler and clean up resources.

        This method cancels all pending tasks and closes the file tracker
        if it was created internally.
        """
        await self.cancel_pending()

        if not self._file_tracker_external and self._file_tracker:
            await self._file_tracker.close()

        logger.info("FileChangeHandler shutdown complete")
