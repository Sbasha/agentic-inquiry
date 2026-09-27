"""File watcher implementation using watchdog library.

This module provides a concrete implementation of the WatcherProtocol
using the watchdog library for file system monitoring, integrated with
hash-based change detection via FileTracker.
"""

import asyncio
import fnmatch
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .file_tracker import FileTracker

from agentic_inquiry.events import EventSystem
from agentic_inquiry.events.types import EventTypes

logger = logging.getLogger(__name__)


class FileWatcherHandler(FileSystemEventHandler):
    """Handle file system events with debouncing and hash-based change detection.

    This handler filters events through ignore patterns, debounces rapid changes,
    and uses hash-based detection to avoid false positives from metadata changes.
    """

    def __init__(
        self,
        callbacks: List[Callable[[str, str], None]],
        file_tracker: FileTracker,
        ignore_patterns: Optional[List[str]] = None,
        debounce_seconds: float = 0.5,
        event_system: Optional[EventSystem] = None,
        get_relative_path: Optional[Callable[[str], str]] = None,
    ):
        """Initialize the event handler.

        Args:
            callbacks: List of callback functions to invoke on file changes
            file_tracker: FileTracker instance for hash-based change detection
            ignore_patterns: Optional list of glob patterns to ignore
            debounce_seconds: Minimum time between events for the same file
            event_system: Optional EventSystem for event tracking
            get_relative_path: Optional function to convert paths to relative
        """
        super().__init__()
        self.callbacks = callbacks
        self.file_tracker = file_tracker
        self.ignore_patterns = ignore_patterns or []
        self.debounce_seconds = debounce_seconds
        self.event_system = event_system
        self.get_relative_path = get_relative_path or (lambda p: p)

        # Track last event time for each file to implement debouncing
        self._last_event_time: Dict[str, float] = {}

        # Track files being processed to avoid duplicate events
        self._processing: Set[str] = set()

    def _emit_event_sync(self, event_type: str, **metadata) -> None:
        """Emit event from synchronous context.

        This method safely emits events from watchdog's thread by creating
        a new event loop if needed.

        Args:
            event_type: Event type to emit
            **metadata: Event metadata
        """
        if self.event_system is None:
            return

        try:
            # Try to get the running event loop (Python 3.10+ preferred approach)
            asyncio.get_running_loop()  # Check if loop is running
            # Loop is running - schedule the coroutine as a task
            asyncio.create_task(
                self.event_system.emit(event_type, source="file_watcher", **metadata)
            )
        except RuntimeError:
            # No running loop - run synchronously using asyncio.run()
            try:
                asyncio.run(
                    self.event_system.emit(
                        event_type, source="file_watcher", **metadata
                    )
                )
            except Exception as e:
                logger.debug("Failed to emit event %s: %s", event_type, e)

    def _should_ignore(self, file_path: str) -> bool:
        """Check if file should be ignored based on patterns.

        Args:
            file_path: Path to check

        Returns:
            True if file should be ignored, False otherwise
        """
        path = Path(file_path)

        # Ignore directories
        if path.is_dir():
            return True

        # Ignore common temporary files
        if path.name.endswith((".swp", ".tmp", "~", "-journal", "-wal", "-shm")):
            return True

        # Check against ignore patterns
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(str(path), pattern) or fnmatch.fnmatch(
                path.name, pattern
            ):
                return True

        return False

    def _should_debounce(self, file_path: str) -> bool:
        """Check if event should be debounced.

        Args:
            file_path: Path to check

        Returns:
            True if event should be debounced, False otherwise
        """
        current_time = time.time()
        last_time = self._last_event_time.get(file_path, 0)

        if current_time - last_time < self.debounce_seconds:
            return True

        self._last_event_time[file_path] = current_time
        return False

    def _trigger_callbacks(self, file_path: str, event_type: str) -> None:
        """Trigger all registered callbacks for a file event.

        Args:
            file_path: Path to the file
            event_type: Type of event ("created", "modified", "deleted")
        """
        for callback in self.callbacks:
            try:
                callback(file_path, event_type)
            except Exception as e:
                logger.error(
                    "Callback failed for %s (%s): %s", file_path, event_type, e
                )

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events.

        Args:
            event: File system event
        """
        if event.is_directory:
            return

        file_path = (
            event.src_path
            if isinstance(event.src_path, str)
            else event.src_path.decode()
        )

        if self._should_ignore(file_path):
            return

        if self._should_debounce(file_path):
            return

        try:
            # Check if file still exists (may be temporary)
            if not Path(file_path).exists():
                logger.debug("File no longer exists (temporary): %s", file_path)
                return

            # Update tracker with new file hash
            self.file_tracker.update_hash_sync(file_path)
            logger.debug("File created: %s", file_path)

            # Emit event
            self._emit_event_sync(
                EventTypes.Watching.FILE_CREATED,
                file_path=self.get_relative_path(file_path),
            )

            self._trigger_callbacks(file_path, "created")
        except FileNotFoundError:
            # File was deleted before we could process it
            logger.debug("File deleted before processing: %s", file_path)
        except Exception as e:
            logger.error("Error handling created event for %s: %s", file_path, e)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events.

        Args:
            event: File system event
        """
        if event.is_directory:
            return

        file_path = (
            event.src_path
            if isinstance(event.src_path, str)
            else event.src_path.decode()
        )

        if self._should_ignore(file_path):
            return

        if self._should_debounce(file_path):
            return

        try:
            # Check if file still exists (may be temporary or deleted)
            if not Path(file_path).exists():
                logger.debug("File no longer exists: %s", file_path)
                return

            # Check if file actually changed using hash
            if self.file_tracker.has_changed_sync(file_path):
                self.file_tracker.update_hash_sync(file_path)
                logger.debug("File modified: %s", file_path)

                # Emit event
                self._emit_event_sync(
                    EventTypes.Watching.FILE_CHANGED,
                    file_path=self.get_relative_path(file_path),
                )

                self._trigger_callbacks(file_path, "modified")
            else:
                logger.debug(
                    "File metadata changed but content unchanged: %s", file_path
                )
        except FileNotFoundError:
            # File was deleted before we could process it
            logger.debug("File deleted before processing: %s", file_path)
        except Exception as e:
            logger.error("Error handling modified event for %s: %s", file_path, e)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deletion events.

        Args:
            event: File system event
        """
        if event.is_directory:
            return

        file_path = (
            event.src_path
            if isinstance(event.src_path, str)
            else event.src_path.decode()
        )

        if self._should_ignore(file_path):
            return

        try:
            # Emit event before removing from tracker
            self._emit_event_sync(
                EventTypes.Watching.FILE_DELETED,
                file_path=self.get_relative_path(file_path),
            )

            # Remove from tracker
            self.file_tracker.remove_file_sync(file_path)
            logger.debug("File deleted: %s", file_path)
            self._trigger_callbacks(file_path, "deleted")
        except Exception as e:
            logger.error("Error handling deleted event for %s: %s", file_path, e)


class FileWatcher:
    """File watcher implementation using watchdog library.

    This watcher monitors directories for file changes and triggers callbacks.
    It uses hash-based change detection to avoid false positives from metadata
    changes and supports debouncing, ignore patterns, and pause/resume.

    Attributes:
        file_tracker: FileTracker instance for hash-based change detection
    """

    def __init__(
        self,
        event_system: Optional["EventSystem"] = None,
        file_tracker: Optional[FileTracker] = None,
        debounce_seconds: float = 0.5,
        config: Optional[Any] = None,
        project_id: Optional[str] = None,
    ):
        """Initialize the file watcher.

        Note: This constructor does NOT initialize the FileTracker database.
        Use the async `initialize()` method or factory `from_config()` after construction.

        Args:
            event_system: Optional EventSystem instance for event emission.
                          If None, file watching still works but no events are emitted.
            file_tracker: Optional FileTracker instance (creates default if None)
            debounce_seconds: Minimum time between events for the same file
            config: Optional Config instance for event system
            project_id: Optional project ID for event tracking
        """
        self.event_system = event_system
        self._file_tracker_external = file_tracker is not None
        self.file_tracker = file_tracker or FileTracker()
        self.debounce_seconds = debounce_seconds

        self._observer = Observer()
        self._callbacks: List[Callable[[str, str], None]] = []
        self._handlers: Dict[str, FileWatcherHandler] = {}
        self._running = False
        self._paused = False
        self._project_root: Optional[Path] = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the file watcher and its dependencies (public API).

        This method initializes the FileTracker database. It is safe to call
        multiple times - subsequent calls will be no-ops.

        Must be called before `start()` if the FileTracker was not provided
        to the constructor.
        """
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return
            await self.file_tracker.initialize()
            self._initialized = True

    @classmethod
    async def from_config(
        cls,
        event_system: Optional["EventSystem"] = None,
        file_tracker: Optional[FileTracker] = None,
        debounce_seconds: float = 0.5,
        config: Optional[Any] = None,
        project_id: Optional[str] = None,
    ) -> "FileWatcher":
        """Create and initialize a FileWatcher instance asynchronously.

        This is the recommended way to create a FileWatcher instance as it
        properly initializes the FileTracker database.

        Args:
            event_system: Optional EventSystem instance for event emission.
            file_tracker: Optional pre-initialized FileTracker instance.
            debounce_seconds: Minimum time between events for the same file.
            config: Optional Config instance.
            project_id: Optional project ID for event tracking.

        Returns:
            Initialized FileWatcher instance
        """
        watcher = cls(
            event_system=event_system,
            file_tracker=file_tracker,
            debounce_seconds=debounce_seconds,
            config=config,
            project_id=project_id,
        )
        await watcher.initialize()
        return watcher

    def _get_relative_path(self, file_path: str) -> str:
        """Convert absolute path to relative path from project root.

        Args:
            file_path: Absolute file path

        Returns:
            Relative path string
        """
        if self._project_root is None:
            return file_path

        try:
            path = Path(file_path)
            return str(path.relative_to(self._project_root))
        except (ValueError, TypeError):
            # If path is not relative to project root, return as-is
            return file_path

    def _emit_event_sync(self, event_type: str, **metadata) -> None:
        """Emit event from synchronous context.

        Args:
            event_type: Event type to emit
            **metadata: Event metadata
        """
        if self.event_system is None:
            return

        try:
            # Try to get the running event loop (Python 3.10+ preferred approach)
            asyncio.get_running_loop()  # Check if loop is running
            # Loop is running - schedule the coroutine as a task
            asyncio.create_task(
                self.event_system.emit(event_type, source="file_watcher", **metadata)
            )
        except RuntimeError:
            # No running loop - run synchronously using asyncio.run()
            try:
                asyncio.run(
                    self.event_system.emit(
                        event_type, source="file_watcher", **metadata
                    )
                )
            except Exception as e:
                logger.debug("Failed to emit event %s: %s", event_type, e)

    def register_callback(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for file events.

        Args:
            callback: Function with signature callback(file_path: str, event_type: str)
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            logger.debug("Registered callback: %s", callback.__name__)

    def unregister_callback(self, callback: Callable[[str, str], None]) -> None:
        """Unregister a previously registered callback.

        Args:
            callback: The callback function to remove
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            logger.debug("Unregistered callback: %s", callback.__name__)

    def watch_directory(
        self,
        path: str,
        recursive: bool = True,
        ignore_patterns: Optional[List[str]] = None,
    ) -> None:
        """Start watching a directory for changes.

        Args:
            path: Directory path to watch
            recursive: Whether to watch subdirectories
            ignore_patterns: Optional list of glob patterns to ignore

        Raises:
            ValueError: If directory doesn't exist
        """
        dir_path = Path(path)

        if not dir_path.exists():
            raise ValueError(f"Directory does not exist: {path}")

        if not dir_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        # Set project root if not already set (use first watched directory)
        if self._project_root is None:
            self._project_root = dir_path.resolve()

        # Create handler for this directory
        handler = FileWatcherHandler(
            callbacks=self._callbacks,
            file_tracker=self.file_tracker,
            ignore_patterns=ignore_patterns,
            debounce_seconds=self.debounce_seconds,
            event_system=self.event_system,
            get_relative_path=self._get_relative_path,
        )

        # Schedule with observer
        self._observer.schedule(handler, str(dir_path), recursive=recursive)
        self._handlers[str(dir_path)] = handler

        logger.info("Watching directory: %s (recursive=%s)", path, recursive)

    def start(self) -> None:
        """Start the file watcher."""
        if not self._running:
            self._observer.start()
            self._running = True
            self._paused = False

            # Emit watching.started event
            self._emit_event_sync(
                EventTypes.Watching.STARTED,
                watched_directories=[str(path) for path in self._handlers.keys()],
            )

            logger.info("File watcher started")

    def stop(self) -> None:
        """Stop the file watcher and clean up resources."""
        if self._running:
            self._observer.stop()
            self._observer.join(timeout=30.0)  # Increased from 5s for reliable cleanup
            self._running = False
            self._paused = False

            # Emit watching.stopped event
            self._emit_event_sync(EventTypes.Watching.STOPPED)

            logger.info("File watcher stopped")

    def pause(self) -> None:
        """Pause the file watcher without stopping it.

        Note: This is implemented by temporarily clearing callbacks.
        Events are still received but not processed.
        """
        if self._running and not self._paused:
            self._paused = True
            logger.info("File watcher paused")

    def resume(self) -> None:
        """Resume a paused file watcher."""
        if self._running and self._paused:
            self._paused = False
            logger.info("File watcher resumed")

    def is_running(self) -> bool:
        """Check if the watcher is currently running.

        Returns:
            True if watcher is running, False otherwise
        """
        return self._running and not self._paused

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False
