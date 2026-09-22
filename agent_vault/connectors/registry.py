"""Connector registry.

Provides thread-safe registration and retrieval of connector implementations.
Uses a singleton pattern with RLock for concurrent access safety.

See: docs/design/connector-architecture.md
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Union, overload

from agent_vault.connectors.protocols import ConnectorProtocol

logger = logging.getLogger(__name__)

# Type for connector factory functions
ConnectorFactory = Callable[..., ConnectorProtocol]


class ConnectorRegistry:
    """Thread-safe registry for connector implementations.

    A singleton registry that manages connector factories with thread-safe
    access using RLock. Supports both class-based and factory-based registration.

    The registry uses double-checked locking for thread-safe singleton creation
    and RLock for all registry operations to support reentrant access.

    Example:
        >>> registry = ConnectorRegistry.get_instance()
        >>> registry.register("filesystem", FileSystemConnector)
        >>> connector = registry.get("filesystem", root="/path")
    """

    _instance: Optional["ConnectorRegistry"] = None
    _creation_lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the registry.

        Note: Use get_instance() to get the singleton instance.
        Direct instantiation is allowed for testing but not recommended
        for production use.
        """
        self._connectors: Dict[str, ConnectorFactory] = {}
        self._registry_lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "ConnectorRegistry":
        """Get the singleton registry instance (thread-safe).

        Uses double-checked locking pattern for efficient thread-safe
        singleton creation.

        Returns:
            The singleton ConnectorRegistry instance.
        """
        if cls._instance is None:
            with cls._creation_lock:
                # Double-check after acquiring lock
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance.

        Primarily used for testing to ensure clean state between tests.
        Thread-safe.
        """
        with cls._creation_lock:
            cls._instance = None

    def register(
        self,
        name: str,
        factory: ConnectorFactory,
    ) -> None:
        """Register a connector factory.

        Args:
            name: Unique name for the connector (e.g., 'filesystem', 's3').
            factory: Factory function or class that creates ConnectorProtocol instances.

        Note:
            If a connector with the same name is already registered, a warning
            is logged and the existing registration is overwritten.
        """
        with self._registry_lock:
            if name in self._connectors:
                logger.warning("Overwriting connector registration: %s", name)
            self._connectors[name] = factory
            logger.debug("Registered connector: %s", name)

    def get(self, name: str, **kwargs: Any) -> ConnectorProtocol:
        """Get a connector instance by name.

        Args:
            name: Registered connector name.
            **kwargs: Arguments to pass to the connector factory.

        Returns:
            Connector instance created by the registered factory.

        Raises:
            KeyError: If connector name is not registered.
        """
        with self._registry_lock:
            if name not in self._connectors:
                available = list(self._connectors.keys())
                raise KeyError(f"Unknown connector: {name}. Available: {available}")
            factory = self._connectors[name]

        # Call factory outside the lock to avoid holding it during construction
        return factory(**kwargs)

    def get_factory(self, name: str) -> Optional[ConnectorFactory]:
        """Get the factory for a connector without instantiating.

        Args:
            name: Registered connector name.

        Returns:
            The registered factory, or None if not found.
        """
        with self._registry_lock:
            return self._connectors.get(name)

    def list_names(self) -> List[str]:
        """List all registered connector names.

        Returns:
            List of registered connector names.
        """
        with self._registry_lock:
            return list(self._connectors.keys())

    def unregister(self, name: str) -> bool:
        """Unregister a connector.

        Args:
            name: Connector name to unregister.

        Returns:
            True if connector was unregistered, False if not found.
        """
        with self._registry_lock:
            if name in self._connectors:
                del self._connectors[name]
                logger.debug("Unregistered connector: %s", name)
                return True
            return False

    def clear(self) -> None:
        """Clear all registered connectors.

        Primarily used for testing.
        """
        with self._registry_lock:
            self._connectors.clear()

    def __contains__(self, name: str) -> bool:
        """Check if a connector is registered.

        Args:
            name: Connector name to check.

        Returns:
            True if connector is registered.
        """
        with self._registry_lock:
            return name in self._connectors

    def __len__(self) -> int:
        """Get the number of registered connectors."""
        with self._registry_lock:
            return len(self._connectors)


# ---------------------------------------------------------------------------
# Module-level API (backward compatibility)
# ---------------------------------------------------------------------------


@overload
def register_connector(name: str) -> Callable[[ConnectorFactory], ConnectorFactory]:
    ...


@overload
def register_connector(name: str, factory: ConnectorFactory) -> ConnectorFactory:
    ...


def register_connector(
    name: str,
    factory: Optional[ConnectorFactory] = None,
) -> Union[Callable[[ConnectorFactory], ConnectorFactory], ConnectorFactory]:
    """Register a connector factory.

    Can be used as a decorator or called directly.

    Args:
        name: Unique name for the connector (e.g., 'filesystem', 's3', 'gcs').
        factory: Optional factory function/class. If None, returns a decorator.

    Returns:
        Decorator if factory is None, otherwise the factory itself.

    Example:
        # As decorator
        @register_connector("my_connector")
        class MyConnector:
            ...

        # Direct call
        register_connector("filesystem", FileSystemConnector)
    """

    def decorator(factory_fn: ConnectorFactory) -> ConnectorFactory:
        ConnectorRegistry.get_instance().register(name, factory_fn)
        return factory_fn

    if factory is not None:
        return decorator(factory)
    return decorator


def get_connector(name: str, **kwargs: Any) -> ConnectorProtocol:
    """Get a connector instance by name.

    Args:
        name: Registered connector name.
        **kwargs: Arguments to pass to the connector factory.

    Returns:
        Connector instance.

    Raises:
        KeyError: If connector name is not registered.

    Example:
        >>> connector = get_connector("filesystem", root="/path/to/project")
        >>> async for item in connector.list():
        ...     process(item)
    """
    return ConnectorRegistry.get_instance().get(name, **kwargs)


def list_connectors() -> List[str]:
    """List all registered connector names.

    Returns:
        List of registered connector names.
    """
    return ConnectorRegistry.get_instance().list_names()


def unregister_connector(name: str) -> bool:
    """Unregister a connector.

    Args:
        name: Connector name to unregister.

    Returns:
        True if connector was unregistered, False if not found.
    """
    return ConnectorRegistry.get_instance().unregister(name)


def clear_registry() -> None:
    """Clear all registered connectors.

    Primarily used for testing.
    """
    ConnectorRegistry.get_instance().clear()


# ---------------------------------------------------------------------------
# Built-in connector registration
# ---------------------------------------------------------------------------


def _register_builtin_connectors() -> None:
    """Register the built-in connector implementations."""
    from agent_vault.connectors.filesystem import FileSystemConnector

    registry = ConnectorRegistry.get_instance()
    registry.register("filesystem", FileSystemConnector)
    registry.register("file", FileSystemConnector)  # Alias

    # S3 connector is registered via decorator in s3.py
    # Import here to trigger registration (optional - only if s3fs available)
    try:
        from agent_vault.connectors.s3 import S3Connector  # noqa: F401
    except ImportError:
        logger.debug("S3 connector not available (s3fs not installed)")

    # GCS connector is registered via decorator in gcs.py. Importing the module
    # fires the decorator; the gcsfs dependency is only checked at construction
    # time, so this registers "gcs" even when gcsfs is not installed.
    try:
        from agent_vault.connectors.gcs import GCSConnector  # noqa: F401
    except ImportError:
        logger.debug("GCS connector not available (gcsfs not installed)")


# Auto-register when module is imported
_register_builtin_connectors()
