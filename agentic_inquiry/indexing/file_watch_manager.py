"""File watching management for automatic re-indexing.

This module handles file watching setup, event handling, and cache
invalidation for the indexing pipeline.

Design Reference:
    Integrates with FileChangeHandler (DES-S4-001) for actual re-indexing.
"""

import asyncio
import logging
from typing import Any, Coroutine, Optional, TYPE_CHECKING

from agentic_inquiry.watching import WatcherProtocol, get_watcher

if TYPE_CHECKING:
    from agentic_inquiry.cache import CacheProtocol
    from agentic_inquiry.indexing.file_change_handler import FileChangeHandler

logger = logging.getLogger(__name__)


class FileWatchManager:
    """Manages file watching for automatic re-indexing.

    This class handles the setup, event handling, and lifecycle management
    of file watchers for the indexing pipeline.

    Responsibilities:
    - Set up file watchers for project directories
    - Handle file change events (created, modified, deleted)
    - Invalidate cache entries for changed files
    - Delegate to FileChangeHandler for actual re-indexing (optional)
    - Manage watcher lifecycle (start/stop)

    Args:
        project_root: Project root directory for path validation
        cache: Optional cache for invalidation on file changes
        file_change_handler: Optional FileChangeHandler for incremental re-indexing.
            If provided, file changes will trigger actual re-indexing.
            See DES-S4-001 in .sessions/deep-architecture-review/009-design.md
    """

    def __init__(
        self,
        project_root: str,
        cache: Optional["CacheProtocol"] = None,
        file_change_handler: Optional["FileChangeHandler"] = None,
    ):
        self.project_root = project_root
        self.cache = cache
        self.file_change_handler = file_change_handler
        self.watcher: Optional[WatcherProtocol] = None
        self._watcher_name: Optional[str] = None

    def setup_file_watching(self, watcher_name: str) -> None:
        """Set up file watching for automatic re-indexing.

        Args:
            watcher_name: Name of the watcher to use
        """
        try:
            self.watcher = get_watcher(watcher_name)
            self._watcher_name = watcher_name

            # Register callback for file change events
            self.watcher.register_callback(self._on_file_change)

            # Watch the project directory recursively
            # Ignore common patterns like .git, __pycache__, node_modules, etc.
            ignore_patterns = [
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
            ]

            self.watcher.watch_directory(
                self.project_root, recursive=True, ignore_patterns=ignore_patterns
            )

            # Start the watcher
            self.watcher.start()

            logger.info(
                "File watching enabled for %s using watcher: %s",
                self.project_root,
                watcher_name,
            )
        except (ValueError, KeyError) as e:
            logger.warning(
                "Failed to set up file watcher '%s': %s. Proceeding without watcher.",
                watcher_name,
                e,
                exc_info=True,
            )
            self.watcher = None
        except Exception as e:
            logger.error("Error setting up file watcher: %s", e, exc_info=True)
            self.watcher = None

    def _on_file_change(self, file_path: str, event_type: str) -> None:
        """Handle file change events from the watcher.

        This callback is invoked by the file watcher when files are created,
        modified, or deleted. It performs the following actions:
        - Invalidates cache for the changed file
        - Delegates to FileChangeHandler for re-indexing (if configured)

        Note: This is a synchronous callback that schedules async operations.
        The actual re-indexing happens asynchronously via FileChangeHandler.

        Args:
            file_path: Path to the file that changed
            event_type: Type of event ("created", "modified", "deleted")
        """
        logger.info("File change detected: %s (%s)", file_path, event_type)

        # Always invalidate cache for changed files
        self._schedule_async(self._invalidate_cache(file_path))

        # Delegate to FileChangeHandler for actual re-indexing
        if self.file_change_handler is not None:
            # Use the sync callback which schedules the async operation
            self.file_change_handler.on_file_change_sync(file_path, event_type)
        else:
            # Legacy behavior: just log the intent
            if event_type in ("created", "modified"):
                logger.info(
                    "Re-indexing scheduled for %s (no handler configured)",
                    file_path,
                )
            elif event_type == "deleted":
                logger.info(
                    "Data removal scheduled for deleted file: %s (no handler configured)",
                    file_path,
                )

    def _schedule_async(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule an async operation from a sync context.

        Args:
            coro: Coroutine to schedule
        """
        try:
            # Try to get the running event loop
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # No running loop - run synchronously
            try:
                asyncio.run(coro)
            except Exception as e:
                logger.warning("Failed to run async operation: %s", e)

    async def _invalidate_cache(self, file_path: str) -> None:
        """Invalidate cache entry for a file.

        Args:
            file_path: Path to the file to invalidate
        """
        if self.cache is None:
            return

        try:
            await self.cache.invalidate(file_path)
            logger.debug("Invalidated cache for %s", file_path)
        except Exception as e:
            logger.warning(
                "Failed to invalidate cache for %s: %s", file_path, e, exc_info=True
            )

    def stop_watching(self) -> None:
        """Stop the file watcher and clean up resources.

        This method stops the file watcher if it's running and cleans up
        any associated resources. It's safe to call this method even if
        no watcher is active.
        """
        if self.watcher is None:
            logger.debug("No watcher to stop")
            return

        try:
            if self.watcher.is_running():
                self.watcher.stop()
                logger.info("File watcher stopped")
            else:
                logger.debug("File watcher was not running")
        except Exception as e:
            logger.error("Error stopping file watcher: %s", e, exc_info=True)
        finally:
            # Clear the watcher reference
            self.watcher = None

    def is_watching(self) -> bool:
        """Check if file watching is active.

        Returns:
            True if watcher is running, False otherwise
        """
        return self.watcher is not None and self.watcher.is_running()

    def set_file_change_handler(
        self,
        handler: "FileChangeHandler",
    ) -> None:
        """Set the FileChangeHandler for incremental re-indexing.

        This method allows configuring the handler after construction,
        which is useful when the handler depends on components that are
        created after the FileWatchManager.

        Args:
            handler: FileChangeHandler instance to use for re-indexing
        """
        self.file_change_handler = handler
        logger.debug("FileChangeHandler configured for FileWatchManager")

    def has_file_change_handler(self) -> bool:
        """Check if a FileChangeHandler is configured.

        Returns:
            True if a handler is configured, False otherwise
        """
        return self.file_change_handler is not None
