"""Factory functions for database adapter instantiation.

This module provides factory functions for creating database adapters based on
configuration. Factories ensure single source of instantiation and enable
backend selection via config.

Design principles:
- Backend selection driven by config (storage.backend)
- Single source of instantiation (no direct adapter construction)
- Factories return protocol-typed objects
- Async initialization pattern (await factory())

Usage:
    config = Config.load()

    # Create vector storage adapter
    adapter = await create_vector_adapter(config)
    await adapter.initialize()

    # Create event store
    event_store = await create_event_store(config)
    await event_store.initialize()

    # Create file tracker
    file_tracker = await create_file_tracker(config)
    await file_tracker.initialize()

See: docs/design/database-abstraction-revised.md (Integration Glue)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_vault.config import Config
    from agent_vault.database.lancedb_manager import LanceDBManager
    from agent_vault.events.store import EventStore
    from agent_vault.watching.file_tracker import FileTracker

logger = logging.getLogger(__name__)


async def create_vector_adapter(config: Config) -> LanceDBManager:
    """Create vector storage adapter based on configuration.

    Currently returns LanceDBManager (the only supported backend).
    Future backends (Qdrant, Pinecone, etc.) will be added here.

    Args:
        config: Configuration object

    Returns:
        Vector storage adapter implementing VectorStorageProtocol

    Raises:
        ValueError: If backend is not supported

    Example:
        >>> config = Config.load()
        >>> adapter = await create_vector_adapter(config)
        >>> await adapter.initialize()
        >>> # Use adapter for storage operations
        >>> await adapter.add("document_chunks", records)
    """
    from agent_vault.database.lancedb_manager import LanceDBManager

    # Get backend from config (defaults to "lancedb")
    backend = getattr(config.storage, 'backend', 'lancedb')

    if backend != 'lancedb':
        raise ValueError(
            f"Unsupported vector storage backend: {backend}. "
            f"Currently only 'lancedb' is supported."
        )

    logger.debug("Creating LanceDB adapter from config")

    # Use existing from_config factory method
    adapter = LanceDBManager.from_config(config)

    logger.info("Created vector storage adapter: backend=%s", backend)
    return adapter


async def create_event_store(config: Config) -> EventStore:
    """Create event store based on configuration.

    Currently returns SQLite-based EventStore (the only supported backend).
    Future backends (PostgreSQL, etc.) will be added here.

    Args:
        config: Configuration object

    Returns:
        Event store implementing EventStoreProtocol

    Raises:
        ValueError: If backend is not supported

    Example:
        >>> config = Config.load()
        >>> event_store = await create_event_store(config)
        >>> await event_store.initialize()
        >>> # Use event store
        >>> await event_store.add_event(event_data)
    """
    from agent_vault.events.store import EventStore

    # Get backend from config (defaults to "sqlite")
    backend = getattr(config.storage, 'event_store_backend', 'sqlite')

    if backend != 'sqlite':
        raise ValueError(
            f"Unsupported event store backend: {backend}. "
            f"Currently only 'sqlite' is supported."
        )

    logger.debug("Creating EventStore from config")

    # Use existing from_config factory method (async)
    event_store = await EventStore.from_config(config)

    logger.info("Created event store: backend=%s", backend)
    return event_store


async def create_file_tracker(config: Config) -> FileTracker:
    """Create file tracker based on configuration.

    Currently returns SQLite-based FileTracker (the only supported backend).
    Future backends (PostgreSQL, etc.) will be added here.

    Args:
        config: Configuration object

    Returns:
        File tracker implementing FileTrackerProtocol

    Raises:
        ValueError: If backend is not supported

    Example:
        >>> config = Config.load()
        >>> file_tracker = await create_file_tracker(config)
        >>> await file_tracker.initialize()
        >>> # Use file tracker
        >>> has_changed = await file_tracker.has_file_changed(file_path)
    """
    from agent_vault.watching.file_tracker import FileTracker

    # Get backend from config (defaults to "sqlite")
    backend = getattr(config.storage, 'file_tracker_backend', 'sqlite')

    if backend != 'sqlite':
        raise ValueError(
            f"Unsupported file tracker backend: {backend}. "
            f"Currently only 'sqlite' is supported."
        )

    logger.debug("Creating FileTracker from config")

    # Use existing from_config factory method
    file_tracker = await FileTracker.from_config(config)

    logger.info("Created file tracker: backend=%s", backend)
    return file_tracker


__all__ = [
    "create_vector_adapter",
    "create_event_store",
    "create_file_tracker",
]
