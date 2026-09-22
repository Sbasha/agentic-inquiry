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
    from agent_vault.storage.providers import LanceDBProvider

    provider = await LanceDBProvider.from_config(config, project_id)
    await provider.initialize()

Creating custom providers:
    from agent_vault.storage.providers import BaseProvider, require_initialized

    class MyProvider(BaseProvider):
        @require_initialized
        async def query(self, ...):
            ...
"""

from agent_vault.storage.providers.base import (
    BaseProvider,
    MaintenanceMixin,
    ProviderNotInitializedError,
    require_initialized,
)
from agent_vault.storage.providers.lancedb import LanceDBProvider
from agent_vault.storage.providers.memory import InMemoryProvider

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
