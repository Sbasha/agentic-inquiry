"""Internal provider registry and factory.

This module provides the provider registry that maps provider names
to implementation classes. It handles lazy loading and instantiation
of storage providers.

This is an internal module - use StorageFacade for public access.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Type

from agentic_inquiry.storage.exceptions import ProviderNotFoundError

if TYPE_CHECKING:
    from agentic_inquiry.config import Config
    from agentic_inquiry.storage.providers.lancedb import LanceDBProvider
    from agentic_inquiry.storage.providers.memory import InMemoryProvider

logger = logging.getLogger(__name__)


# =============================================================================
# Provider Registry
# =============================================================================

# Registry maps provider names to tuples of (module_path, class_name)
# This enables lazy loading of provider implementations
_PROVIDER_REGISTRY: Dict[str, tuple[str, str]] = {
    "lancedb": (
        "agentic_inquiry.storage.providers.lancedb",
        "LanceDBProvider",
    ),
    "memory": (
        "agentic_inquiry.storage.providers.memory",
        "InMemoryProvider",
    ),
}


def get_available_providers() -> list[str]:
    """Get list of registered provider names.

    Returns:
        List of provider names that can be instantiated
    """
    return list(_PROVIDER_REGISTRY.keys())


def register_provider(
    name: str,
    module_path: str,
    class_name: str,
) -> None:
    """Register a new provider.

    Args:
        name: Provider name for lookup
        module_path: Full module path (e.g., "agentic_inquiry.storage.providers.lancedb")
        class_name: Class name within the module

    Example:
        register_provider(
            "custom",
            "my_package.providers.custom",
            "CustomProvider",
        )
    """
    _PROVIDER_REGISTRY[name] = (module_path, class_name)
    logger.debug("Registered storage provider: %s", name)


def _load_provider_class(name: str) -> Type:
    """Load provider class by name (internal).

    Args:
        name: Provider name from registry

    Returns:
        Provider class

    Raises:
        ProviderNotFoundError: If provider is not registered
        ImportError: If provider module cannot be imported
    """
    if name not in _PROVIDER_REGISTRY:
        raise ProviderNotFoundError(
            f"Provider '{name}' not found. Available providers: "
            f"{', '.join(get_available_providers())}"
        )

    module_path, class_name = _PROVIDER_REGISTRY[name]

    try:
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except ImportError as e:
        raise ProviderNotFoundError(
            f"Failed to import provider '{name}' from {module_path}: {e}"
        ) from e
    except AttributeError as e:
        raise ProviderNotFoundError(
            f"Provider class '{class_name}' not found in {module_path}: {e}"
        ) from e


async def create_provider(
    name: str,
    config: "Config",
    project_id: str,
) -> "LanceDBProvider | InMemoryProvider":
    """Create and initialize a provider instance.

    Args:
        name: Provider name from registry
        config: Configuration instance
        project_id: Project ID for data isolation

    Returns:
        Initialized provider instance

    Raises:
        ProviderNotFoundError: If provider is not registered or fails to load
    """
    provider_class = _load_provider_class(name)
    provider = await provider_class.from_config(config, project_id)
    return provider


__all__ = [
    "get_available_providers",
    "register_provider",
    "create_provider",
]
