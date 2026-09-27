"""Backend registry for lazy-loading storage provider classes.

This module provides a registry that maps backend types and roles to their
implementation classes. Providers are loaded lazily to minimize import overhead.

Design principles:
    - Lazy loading: Provider classes are only imported when needed
    - Role-based: Each backend type supports specific storage roles
    - Extensible: New backends can be registered at runtime
    - Type-safe: Returns protocol-compatible provider classes

Example:
    >>> provider_class = get_provider_class("sqlite", "events")
    >>> provider = provider_class(database_path="...")
    >>> await provider.initialize()
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any, Dict, Set, Tuple, Type

from agentic_inquiry.storage.config import BackendType, StorageRole


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


# Storage roles supported by the system
STORAGE_ROLES = frozenset(
    {"vector", "graph", "events", "file_tracker", "onboard_metadata"}
)


# Registry: backend_type -> role -> (module_path, class_name)
# This maps each backend type to the provider classes for each supported role
PROVIDER_REGISTRY: Dict[str, Dict[StorageRole, Tuple[str, str]]] = {
    "lancedb": {
        "vector": ("agentic_inquiry.storage.providers.lancedb", "LanceDBProvider"),
        "graph": ("agentic_inquiry.storage.providers.lancedb", "LanceDBProvider"),
    },
    "sqlite": {
        "events": ("agentic_inquiry.storage.providers.sqlite", "SQLiteEventProvider"),
        "file_tracker": (
            "agentic_inquiry.storage.providers.sqlite",
            "SQLiteFileTrackerProvider",
        ),
        "onboard_metadata": (
            "agentic_inquiry.onboard.providers.sqlite",
            "SQLiteOnboardMetadataProvider",
        ),
    },
    "memory": {
        "vector": (
            "agentic_inquiry.storage.providers.memory",
            "InMemoryVectorProvider",
        ),
        "graph": ("agentic_inquiry.storage.providers.memory", "InMemoryGraphProvider"),
        # Note: events and file_tracker not supported by InMemoryProvider
        # Use sqlite backend for events/file_tracker testing
    },
}


# Cache for loaded provider classes to avoid repeated imports
_provider_cache: Dict[Tuple[str, str], Type[Any]] = {}


class RegistryError(Exception):
    """Base exception for registry errors."""

    pass


class UnknownBackendError(RegistryError):
    """Raised when an unknown backend type is requested."""

    def __init__(self, backend_type: str):
        self.backend_type = backend_type
        available = list(PROVIDER_REGISTRY.keys())
        super().__init__(
            f"Unknown backend type: '{backend_type}'. Available backends: {available}"
        )


class UnsupportedRoleError(RegistryError):
    """Raised when a backend doesn't support a requested role."""

    def __init__(self, backend_type: BackendType, role: StorageRole):
        self.backend_type = backend_type
        self.role = role
        supported = get_supported_roles(backend_type)
        super().__init__(
            f"Backend '{backend_type}' does not support role '{role}'. "
            f"Supported roles: {list(supported)}"
        )


class ProviderLoadError(RegistryError):
    """Raised when a provider class cannot be loaded."""

    def __init__(self, backend_type: str, role: str, cause: Exception):
        self.backend_type = backend_type
        self.role = role
        self.cause = cause
        super().__init__(f"Failed to load provider for {backend_type}/{role}: {cause}")


def get_supported_backends() -> Set[str]:
    """Get all registered backend types.

    Returns:
        Set of backend type names (e.g., {"lancedb", "sqlite", "memory"})
    """
    return set(PROVIDER_REGISTRY.keys())


def get_supported_roles(backend_type: BackendType) -> Set[StorageRole]:
    """Get roles supported by a backend type.

    Args:
        backend_type: The backend type to check

    Returns:
        Set of supported role names

    Raises:
        UnknownBackendError: If backend_type is not registered
    """
    if backend_type not in PROVIDER_REGISTRY:
        raise UnknownBackendError(backend_type)
    return set(PROVIDER_REGISTRY[backend_type].keys())  # type: ignore[arg-type]


def is_role_supported(backend_type: BackendType, role: StorageRole) -> bool:
    """Check if a backend supports a specific role.

    Args:
        backend_type: The backend type to check
        role: The role to check (vector, graph, events, file_tracker)

    Returns:
        True if the backend supports the role

    Raises:
        UnknownBackendError: If backend_type is not registered
    """
    if backend_type not in PROVIDER_REGISTRY:
        raise UnknownBackendError(backend_type)
    return role in PROVIDER_REGISTRY[backend_type]


def get_provider_class(backend_type: BackendType, role: StorageRole) -> Type[Any]:
    """Lazy-load and return provider class for a backend/role combination.

    This function caches loaded classes to avoid repeated imports.
    The returned class can be instantiated with appropriate configuration.

    Args:
        backend_type: The backend type (lancedb, sqlite, memory)
        role: The storage role (vector, graph, events, file_tracker)

    Returns:
        Provider class implementing the appropriate protocol

    Raises:
        UnknownBackendError: If backend_type is not registered
        UnsupportedRoleError: If backend doesn't support the role
        ProviderLoadError: If the provider module/class cannot be loaded

    Example:
        >>> EventProvider = get_provider_class("sqlite", "events")
        >>> provider = EventProvider(db_path="./events.db")
    """
    # Validate inputs
    if backend_type not in PROVIDER_REGISTRY:
        raise UnknownBackendError(backend_type)

    role_map = PROVIDER_REGISTRY[backend_type]
    if role not in role_map:
        raise UnsupportedRoleError(backend_type, role)

    # Check cache first
    cache_key = (backend_type, role)
    if cache_key in _provider_cache:
        logger.debug("Using cached provider: %s/%s", backend_type, role)
        return _provider_cache[cache_key]

    # Load the provider class
    module_path, class_name = role_map[role]
    try:
        logger.debug("Loading provider: %s.%s", module_path, class_name)
        module = importlib.import_module(module_path)
        provider_class = getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise ProviderLoadError(backend_type, role, e) from e

    # Cache and return
    _provider_cache[cache_key] = provider_class
    return provider_class


def register_provider(
    backend_type: str,
    role: StorageRole,
    module_path: str,
    class_name: str,
) -> None:
    """Register a custom provider class for a backend/role combination.

    This allows extending the registry with custom provider implementations
    at runtime.

    Args:
        backend_type: The backend type name
        role: The storage role (must be one of STORAGE_ROLES)
        module_path: Full module path (e.g., "myproject.providers.custom")
        class_name: Class name within the module

    Raises:
        ValueError: If role is not a valid storage role

    Example:
        >>> register_provider(
        ...     "custom_db",
        ...     "events",
        ...     "myproject.storage.custom",
        ...     "CustomEventProvider",
        ... )
    """
    if role not in STORAGE_ROLES:
        raise ValueError(f"Invalid role: '{role}'. Must be one of: {STORAGE_ROLES}")

    if backend_type not in PROVIDER_REGISTRY:
        PROVIDER_REGISTRY[backend_type] = {}

    PROVIDER_REGISTRY[backend_type][role] = (module_path, class_name)

    # Invalidate cache entry if it exists
    cache_key = (backend_type, role)
    _provider_cache.pop(cache_key, None)

    logger.info(
        "Registered provider: %s/%s -> %s.%s",
        backend_type,
        role,
        module_path,
        class_name,
    )


def clear_cache() -> None:
    """Clear the provider class cache.

    This is primarily useful for testing or when reloading providers.
    """
    _provider_cache.clear()
    logger.debug("Provider cache cleared")


def get_registry_info() -> Dict[str, Dict[str, str]]:
    """Get human-readable registry information.

    Returns:
        Dict mapping backend types to role -> "module.class" strings

    Example:
        >>> info = get_registry_info()
        >>> print(info["sqlite"]["events"])
        "agentic_inquiry.storage.providers.sqlite.SQLiteEventProvider"
    """
    result: Dict[str, Dict[str, str]] = {}
    for backend_type, role_map in PROVIDER_REGISTRY.items():
        result[backend_type] = {}
        for role, (module_path, class_name) in role_map.items():
            result[backend_type][role] = f"{module_path}.{class_name}"
    return result


# Import here to avoid circular imports
if TYPE_CHECKING:
    from agentic_inquiry.config import StorageConfig


class BackendResolutionError(RegistryError):
    """Raised when backend resolution fails."""

    pass


def resolve_backend(
    storage_config: "StorageConfig",
    role: StorageRole,
) -> Tuple[str, Dict[str, Any]]:
    """Resolve a storage role to backend name and configuration.

    This function looks up which backend is assigned to a given role
    in the storage configuration and returns its configuration.

    Args:
        storage_config: The StorageConfig instance with backends configured
        role: Storage role to resolve (vector, graph, events, file_tracker)

    Returns:
        Tuple of (backend_name, backend_config_dict)

    Raises:
        BackendResolutionError: If backend name not found or role not supported

    Example:
        >>> from agentic_inquiry.config import Config
        >>> config = Config.load()
        >>> backend_name, backend_config = resolve_backend(config.storage, "events")
        >>> print(f"Using {backend_name}: {backend_config['type']}")
    """
    # Validate role
    if role not in STORAGE_ROLES:
        raise BackendResolutionError(
            f"Invalid role: '{role}'. Must be one of: {STORAGE_ROLES}"
        )

    # Check if new-style backends are configured
    if storage_config.backends is None:
        # Fall back to legacy configuration
        return _resolve_legacy_backend(storage_config, role)

    # Get backend name for this role
    role_attr = f"{role}_backend"
    if role == "file_tracker":
        # Handle the renamed field for backward compatibility
        role_attr = "file_tracker_backend_v2"

    backend_name = getattr(storage_config, role_attr, None)
    if backend_name is None:
        raise BackendResolutionError(f"No backend configured for role: {role}")

    # Get backend config from backends dict
    if backend_name not in storage_config.backends:
        available = list(storage_config.backends.keys())
        raise BackendResolutionError(
            f"Backend '{backend_name}' not found in backends configuration. "
            f"Available backends: {available}"
        )

    backend_config = storage_config.backends[backend_name]

    # Validate backend type supports this role
    backend_type = backend_config.get("type")
    if backend_type is None:
        raise BackendResolutionError(
            f"Backend '{backend_name}' has no 'type' specified"
        )

    if not is_role_supported(backend_type, role):
        supported = get_supported_roles(backend_type)
        raise BackendResolutionError(
            f"Backend type '{backend_type}' does not support role '{role}'. "
            f"Supported roles: {list(supported)}"
        )

    return backend_name, backend_config


def _resolve_legacy_backend(
    storage_config: "StorageConfig",
    role: StorageRole,
) -> Tuple[str, Dict[str, Any]]:
    """Resolve backend using legacy configuration fields.

    This provides backward compatibility with the old configuration format
    that uses string fields like 'backend', 'event_store_backend'.

    Args:
        storage_config: The StorageConfig with legacy fields
        role: Storage role to resolve

    Returns:
        Tuple of (backend_name, backend_config_dict)
    """
    if role == "vector":
        backend_type = storage_config.backend
        return backend_type, {
            "type": backend_type,
            "database_path": str(storage_config.get_lancedb_path()),
        }

    elif role == "graph":
        backend_type = storage_config.backend
        return backend_type, {
            "type": backend_type,
            "database_path": str(storage_config.get_lancedb_path()),
        }

    elif role == "events":
        backend_type = storage_config.event_store_backend
        return backend_type, {
            "type": backend_type,
            "database_path": str(storage_config.get_event_store_path()),
        }

    elif role == "file_tracker":
        backend_type = storage_config.file_tracker_backend
        return backend_type, {
            "type": backend_type,
            "database_path": str(storage_config.get_file_tracker_path()),
        }

    raise BackendResolutionError(f"Unknown role for legacy resolution: {role}")


def create_provider(
    storage_config: "StorageConfig",
    role: StorageRole,
    **extra_kwargs: Any,
) -> Any:
    """Create and return an instantiated provider for a role.

    This is a convenience function that resolves the backend configuration
    and instantiates the provider class.

    Args:
        storage_config: The StorageConfig instance
        role: Storage role (vector, graph, events, file_tracker)
        **extra_kwargs: Additional kwargs to pass to provider constructor

    Returns:
        Instantiated provider (not yet initialized - call initialize() separately)

    Raises:
        BackendResolutionError: If backend resolution fails
        ProviderLoadError: If provider class cannot be loaded

    Example:
        >>> provider = create_provider(config.storage, "events", project_id="my-project")
        >>> await provider.initialize()
    """
    backend_name, backend_config = resolve_backend(storage_config, role)
    backend_type = backend_config["type"]

    # Get the provider class
    provider_class = get_provider_class(backend_type, role)

    logger.debug(
        "Creating provider: %s/%s (backend=%s)",
        backend_type,
        role,
        backend_name,
    )

    import asyncio

    has_sync_from_config = hasattr(
        provider_class, "from_config"
    ) and not asyncio.iscoroutinefunction(provider_class.from_config)

    if has_sync_from_config:
        # Sync ``from_config`` path (PostgresVectorProvider et al.): signature
        # is ``(config: dict, project_id: str)``. The backend-config dict is
        # passed verbatim — Postgres providers dispatch on ``type`` inside
        # (alloydb/cloudsql/rds/azure/postgres), so ``type`` must stay.
        # Facade-level kwargs (``pool_manager``, ``config`` Config instance)
        # are not part of the backend-config dict, so they're dropped.
        project_id = extra_kwargs.get("project_id")
        if project_id is None:
            raise ValueError(f"project_id required for {provider_class.__name__}")
        return provider_class.from_config(dict(backend_config), project_id)

    # Direct ``__init__`` path (LanceDBProvider, InMemoryProvider, SQLite*):
    # merge backend-config + extra kwargs, then drop:
    #   - ``type``: registry discriminator, not a constructor arg. Most
    #     providers accept ``**kwargs`` and silently absorb it, but
    #     InMemoryProvider does not and raises TypeError.
    #   - ``pool_manager``: facade-level scaffolding, not wired to providers
    #     today (see facade.py comment and issue #131).
    # ``config`` is *kept* — LanceDBProvider and InMemoryProvider both take
    # a Config instance as a constructor argument.
    kwargs = {**backend_config, **extra_kwargs}
    for key in ("type", "pool_manager"):
        kwargs.pop(key, None)
    return provider_class(**kwargs)
