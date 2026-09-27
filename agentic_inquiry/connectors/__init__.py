"""Connectors package.

Pluggable content source abstraction for indexing inputs.
Supports filesystem, S3, GCS, GitHub, and other backends via fsspec.

Core Types:
    SourceItem: Metadata about discoverable content.
    SourceContent: Retrieved content with data.

Protocols:
    ConnectorProtocol: Core enumeration and retrieval.
    WatchCapability: Real-time change monitoring.
    AuthCapability: Authentication lifecycle.
    ChangeDetectionCapability: Incremental processing support.
    HashTrackerProtocol: Hash-based file tracking for deduplication.

Implementations:
    FsspecConnector: Base connector using fsspec.
    FileSystemConnector: Local filesystem connector.
    InMemoryFileTracker: Simple in-memory HashTrackerProtocol implementation.

Registry:
    register_connector: Register a connector factory.
    get_connector: Get a connector instance by name.
    list_connectors: List registered connectors.

See: docs/design/connector-architecture.md
"""

from agentic_inquiry.connectors.base import (
    DEFAULT_BINARY_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    FsspecConnector,
    InMemoryFileTracker,
)
from agentic_inquiry.connectors.cache import ContentMaterializer
from agentic_inquiry.connectors.filesystem import FileSystemConnector
from agentic_inquiry.connectors.hash_cache import BoundedHashCache, HashCacheStats
from agentic_inquiry.connectors.lru_cache import (
    CacheEntry,
    CacheStats,
    FileCacheTracker,
    LRUCache,
)

from agentic_inquiry.connectors.protocols import (
    AuthCapability,
    ChangeDetectionCapability,
    ConnectorProtocol,
    HashTrackerProtocol,
    WatchCapability,
    WatchEvent,
    WatchEventType,
    has_auth_capability,
    has_change_detection,
    has_hash_tracker,
    has_watch_capability,
)
from agentic_inquiry.connectors.registry import (
    ConnectorRegistry,
    get_connector,
    list_connectors,
    register_connector,
    unregister_connector,
)
from agentic_inquiry.connectors.types import (
    SourceContent,
    SourceItem,
    compute_content_hash,
)

__all__ = [
    # Types
    "SourceItem",
    "SourceContent",
    "compute_content_hash",
    # Protocols
    "ConnectorProtocol",
    "WatchCapability",
    "WatchEventType",
    "WatchEvent",
    "AuthCapability",
    "ChangeDetectionCapability",
    "HashTrackerProtocol",
    # Capability detection
    "has_watch_capability",
    "has_auth_capability",
    "has_change_detection",
    "has_hash_tracker",
    # Base connector
    "FsspecConnector",
    "DEFAULT_IGNORE_PATTERNS",
    "DEFAULT_BINARY_EXTENSIONS",
    # Filesystem connector
    "FileSystemConnector",
    # S3 connector (optional)
    # GCS connector (optional)
    # Cache materialization
    "ContentMaterializer",
    # LRU Cache (S5-005)
    "LRUCache",
    "CacheEntry",
    "CacheStats",
    "FileCacheTracker",
    # FileTracker implementations (S5-009)
    "InMemoryFileTracker",
    # Hash Cache (S5-011)
    "BoundedHashCache",
    "HashCacheStats",
    # Registry
    "ConnectorRegistry",
    "register_connector",
    "get_connector",
    "list_connectors",
    "unregister_connector",
]
