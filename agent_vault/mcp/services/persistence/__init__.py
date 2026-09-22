"""Session persistence layer.

This module provides a pluggable storage abstraction for session management.

Components:
- SessionStorageProtocol: Abstract interface for session storage
- LanceDBSessionStorage: LanceDB-backed implementation
- InMemorySessionStorage: In-memory implementation for testing
"""

from agent_vault.mcp.services.persistence.protocol import SessionStorageProtocol
from agent_vault.mcp.services.persistence.lancedb_backend import LanceDBSessionStorage
from agent_vault.mcp.services.persistence.memory_backend import InMemorySessionStorage

__all__ = [
    "SessionStorageProtocol",
    "LanceDBSessionStorage",
    "InMemorySessionStorage",
]
