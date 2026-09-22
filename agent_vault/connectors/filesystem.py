"""Local filesystem connector.

Provides a secure connector for local file access with:
- Path validation (prevents directory traversal)
- FileTracker integration (change detection)
- WatchCapability via FileWatcher integration

See: docs/design/connector-architecture.md
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from agent_vault.connectors.base import (
    DEFAULT_BINARY_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    FsspecConnector,
)
from agent_vault.connectors.protocols import (
    ChangeDetectionCapability,
    WatchCapability,
    WatchEventType,
)
from agent_vault.connectors.types import SourceContent, SourceItem

logger = logging.getLogger(__name__)


class FileSystemConnector(FsspecConnector, WatchCapability, ChangeDetectionCapability):
    """Local filesystem connector with security and change detection.

    Extends FsspecConnector with:
    - Path validation to prevent directory traversal attacks
    - FileTracker integration for hash-based change detection
    - WatchCapability for real-time file monitoring

    Security:
        All paths are validated to ensure they remain within the root
        directory. Symlinks that escape the root are rejected.

    Attributes:
        root_path: The validated root directory for all operations.
        file_tracker: Optional FileTracker for change detection.

    Example:
        >>> connector = FileSystemConnector(root="/path/to/project")
        >>> async for item in connector.list():
        ...     if await connector.has_changed(item):
        ...         content = await connector.open(item)
        ...         process(content)
        ...         await connector.mark_processed(item)
    """

    def __init__(
        self,
        root: Optional[str] = None,
        ignore_patterns: Optional[List[str]] = None,
        binary_extensions: Optional[Set[str]] = None,
        file_tracker: Optional[Any] = None,
        file_watcher: Optional[Any] = None,
    ) -> None:
        """Initialize the filesystem connector.

        Args:
            root: Root directory for all operations.
                If None, uses current working directory.
            ignore_patterns: Glob patterns to ignore.
                Defaults to DEFAULT_IGNORE_PATTERNS.
            binary_extensions: Extensions to treat as binary.
                Defaults to DEFAULT_BINARY_EXTENSIONS.
            file_tracker: Optional FileTracker for change detection.
                If provided, enables has_changed() and mark_processed().
            file_watcher: Optional FileWatcher for watch capability.
                If provided, enables watch() method.
        """
        super().__init__(
            protocol="file",
            storage_options={},
            ignore_patterns=ignore_patterns or list(DEFAULT_IGNORE_PATTERNS),
            binary_extensions=binary_extensions or set(DEFAULT_BINARY_EXTENSIONS),
        )

        # Resolve and validate root
        self._root = Path(root or os.getcwd()).resolve()
        if not self._root.exists():
            raise FileNotFoundError(f"Root directory does not exist: {self._root}")
        if not self._root.is_dir():
            raise NotADirectoryError(f"Root is not a directory: {self._root}")

        # Optional integrations
        self._file_tracker = file_tracker
        self._file_watcher = file_watcher

        # Track processed items (in-memory fallback if no tracker)
        self._processed_hashes: Dict[str, str] = {}

    @property
    def root_path(self) -> Path:
        """Get the root directory path."""
        return self._root

    async def list(self, root: str = "") -> AsyncIterator[SourceItem]:
        """Enumerate files with path validation.

        All returned paths are validated to be within the root directory.

        Args:
            root: Subdirectory under the connector's root.
                If empty string, enumerates from the connector's root.

        Yields:
            SourceItem for each valid file.

        Raises:
            ValueError: If provided root escapes the connector's root.
        """
        # Determine enumeration root
        if not root:
            enum_root = str(self._root)
        else:
            # Validate provided root
            try:
                enum_root = str(self._validate_path(root))
            except ValueError as e:
                logger.error("Invalid enumeration root: %s", e)
                raise

        # Use parent's list with validated root
        async for item in super().list(enum_root):
            # Re-validate each item (defense in depth)
            try:
                validated_path = self._validate_path(item.uri)
                # Compute hash if not provided
                content_hash = item.content_hash
                if content_hash is None:
                    content_hash = await self._compute_file_hash(str(validated_path))

                yield SourceItem(
                    uri=str(validated_path),
                    content_hash=content_hash,
                    modified_at=item.modified_at,
                    size=item.size,
                    content_type=item.content_type,
                )
            except ValueError as e:
                logger.warning("Skipping invalid path %s: %s", item.uri, e)
                continue

    async def open(self, item: SourceItem) -> SourceContent:
        """Read content with path validation.

        Args:
            item: SourceItem from list() to retrieve.

        Returns:
            SourceContent with data and metadata.

        Raises:
            ValueError: If path escapes the root directory.
            FileNotFoundError: If file does not exist.
        """
        # Validate path
        validated_path = self._validate_path(item.uri)

        # Create validated item
        validated_item = SourceItem(
            uri=str(validated_path),
            content_hash=item.content_hash,
            modified_at=item.modified_at,
            size=item.size,
            content_type=item.content_type,
        )

        return await super().open(validated_item)

    # =========================================================================
    # ChangeDetectionCapability Implementation
    # =========================================================================

    async def has_changed(self, item: SourceItem) -> bool:
        """Check if file has changed since last processing.

        Uses FileTracker if available, otherwise uses in-memory cache.

        Args:
            item: SourceItem to check.

        Returns:
            True if file has changed or is new.
        """
        if item.content_hash is None:
            # No hash = always consider changed
            return True

        # Try FileTracker first
        if self._file_tracker is not None:
            try:
                stored_hash = await self._file_tracker.get_hash(item.uri)
                return stored_hash != item.content_hash
            except Exception as e:
                logger.warning("FileTracker error for %s: %s", item.uri, e)

        # Fall back to in-memory cache
        stored_hash = self._processed_hashes.get(item.uri)
        return stored_hash != item.content_hash

    async def mark_processed(self, item: SourceItem) -> None:
        """Mark file as processed.

        Records the current hash for future change detection.

        Args:
            item: SourceItem that was processed.
        """
        if item.content_hash is None:
            return

        # Update FileTracker if available
        if self._file_tracker is not None:
            try:
                await self._file_tracker.update_hash(item.uri, item.content_hash)
            except Exception as e:
                logger.warning("FileTracker update error for %s: %s", item.uri, e)

        # Always update in-memory cache as fallback
        self._processed_hashes[item.uri] = item.content_hash

    # =========================================================================
    # WatchCapability Implementation
    # =========================================================================

    async def watch(
        self, root: str = ""
    ) -> AsyncIterator[tuple[WatchEventType, SourceItem]]:
        """Watch for file changes.

        Uses FileWatcher if available, otherwise yields nothing.

        Args:
            root: Subdirectory to watch.
                If empty string, watches the connector's root.

        Yields:
            Tuple of (WatchEventType, SourceItem) for each change.

        Note:
            This is a long-running generator. Use asyncio.create_task()
            and cancel when done watching.
        """
        if self._file_watcher is None:
            logger.warning("WatchCapability not available: no FileWatcher configured")
            return

        # Determine watch root
        if not root:
            watch_root = str(self._root)
        else:
            watch_root = str(self._validate_path(root))

        # Queue for events
        event_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

        # Callback for FileWatcher
        async def _on_event(path: str, event_type: str) -> None:
            await event_queue.put((path, event_type))

        # Register callback
        self._file_watcher.register_callback(_on_event)

        try:
            # Start watching
            self._file_watcher.watch_directory(watch_root, recursive=True)
            self._file_watcher.start()

            # Yield events
            while True:
                try:
                    path, event_type_str = await event_queue.get()

                    # Validate path
                    try:
                        validated_path = self._validate_path(path)
                    except ValueError:
                        continue

                    # Map event type
                    event_type = self._map_event_type(event_type_str)
                    if event_type is None:
                        continue

                    # Build SourceItem
                    item = await self._build_item_from_path(str(validated_path))

                    yield event_type, item
                except asyncio.CancelledError:
                    break
        finally:
            # Cleanup
            self._file_watcher.stop()
            self._file_watcher.unregister_callback(_on_event)

    # =========================================================================
    # Security Helpers
    # =========================================================================

    def _validate_path(self, path: str) -> Path:
        """Validate that a path is within the root directory.

        Prevents directory traversal attacks and symlink escapes.

        Args:
            path: Path to validate.

        Returns:
            Validated absolute Path.

        Raises:
            ValueError: If path escapes the root directory.
        """
        # Resolve to absolute path
        resolved = Path(path).resolve()

        # Check if within root
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise ValueError(
                f"Path escapes root directory: {path} -> {resolved} (root: {self._root})"
            )

        return resolved

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    async def _compute_file_hash(self, path: str) -> str:
        """Compute SHA256 hash of a file.

        Args:
            path: File path to hash.

        Returns:
            Hex-encoded SHA256 hash.
        """

        def _read_and_hash() -> str:
            import hashlib

            hasher = hashlib.sha256()
            with open(path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()

        return await asyncio.to_thread(_read_and_hash)

    async def _build_item_from_path(self, path: str) -> SourceItem:
        """Build a SourceItem from a file path.

        Args:
            path: Validated file path.

        Returns:
            SourceItem with metadata.
        """
        from datetime import datetime

        p = Path(path)

        # Get file info
        try:
            stat = await asyncio.to_thread(p.stat)
            size = stat.st_size
            modified_at = datetime.fromtimestamp(stat.st_mtime)
        except Exception:
            size = None
            modified_at = None

        # Compute hash
        try:
            content_hash = await self._compute_file_hash(path)
        except Exception:
            content_hash = None

        return SourceItem(
            uri=path,
            content_hash=content_hash,
            modified_at=modified_at,
            size=size,
            content_type=self._infer_content_type(path),
        )

    def _map_event_type(self, event_type_str: str) -> Optional[WatchEventType]:
        """Map string event type to WatchEventType enum.

        Args:
            event_type_str: Event type string from FileWatcher.

        Returns:
            WatchEventType or None if unknown.
        """
        mapping = {
            "created": WatchEventType.CREATED,
            "modified": WatchEventType.MODIFIED,
            "deleted": WatchEventType.DELETED,
            "moved": WatchEventType.MOVED,
        }
        return mapping.get(event_type_str.lower())
