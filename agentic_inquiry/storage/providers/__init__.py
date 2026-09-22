"""Storage provider implementations.

This module contains concrete implementations of storage protocols
for different backends.

Available providers:
- LanceDBProvider: Production provider using LanceDB
- InMemoryProvider: Testing provider with in-memory storage

Base classes:
- BaseProvider: Abstract base for all storage providers
- MaintenanceMixin: Mixin for maintenance operations
- require_initialized: Decorator for methods requiring initialization

Usage:
    from agentic_inquiry.storage.providers import LanceDBProvider

    provider = await LanceDBProvider.from_config(config, project_id)
    await provider.initialize()

Creating custom providers:
    from agentic_inquiry.storage.providers import BaseProvider, require_initialized

    class MyProvider(BaseProvider):
        @require_initialized
        async def query(self, ...):
            ...
"""

from agentic_inquiry.storage.providers.base import (
    BaseProvider,
    MaintenanceMixin,
    ProviderNotInitializedError,
    require_initialized,
)
from agentic_inquiry.storage.providers.lancedb import LanceDBProvider
from agentic_inquiry.storage.providers.memory import InMemoryProvider

__all__ = [
    # Base classes
    "BaseProvider",
    "MaintenanceMixin",
    "ProviderNotInitializedError",
    "require_initialized",
    # Providers
    "LanceDBProvider",
    "InMemoryProvider",
]
