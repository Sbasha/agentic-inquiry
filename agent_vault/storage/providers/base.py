"""Base classes for storage providers.

This module provides abstract base classes and mixins for storage providers,
establishing consistent lifecycle management, error handling, and common
functionality across all storage backends.

Classes:
    BaseProvider: Abstract base for all storage providers with lifecycle management
    require_initialized: Decorator for methods that require initialization

Design principles:
    - Consistent lifecycle: All providers follow initialize() -> use -> close()
    - Idempotent operations: initialize() and close() safe to call multiple times
    - Project isolation: All data namespaced by project_id
    - Async-only: All I/O operations are async
"""

from __future__ import annotations

import functools
import logging
from abc import ABC, abstractmethod
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Coroutine,
    Dict,
    TypeVar,
    Union,
)

if TYPE_CHECKING:
    from agent_vault.config import Config

logger = logging.getLogger(__name__)

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


class ProviderNotInitializedError(RuntimeError):
    """Raised when a provider method is called before initialization."""

    def __init__(self, provider_name: str, method_name: str) -> None:
        self.provider_name = provider_name
        self.method_name = method_name
        super().__init__(
            f"{provider_name}.{method_name}() called before initialization. "
            f"Call await provider.initialize() first."
        )


def require_initialized(func: F) -> F:
    """Decorator that ensures the provider is initialized before executing the method.

    Raises:
        ProviderNotInitializedError: If provider is not initialized

    Example:
        >>> class MyProvider(BaseProvider):
        ...     @require_initialized
        ...     async def query(self):
        ...         return await self._do_query()
    """

    @functools.wraps(func)
    async def wrapper(self: "BaseProvider", *args: Any, **kwargs: Any) -> Any:
        if not self.is_initialized:
            raise ProviderNotInitializedError(
                provider_name=self.__class__.__name__,
                method_name=func.__name__,
            )
        return await func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class BaseProvider(ABC):
    """Abstract base class for all storage providers.

    Provides consistent lifecycle management, project isolation, and common
    functionality for all storage backends (LanceDB, PostgreSQL, SQLite, etc.).

    Subclasses must implement:
        - from_config(): Factory method for creating instances from configuration
        - _do_initialize(): Backend-specific initialization logic
        - _do_close(): Backend-specific cleanup logic

    Optional overrides:
        - health_check(): Return health status (default: basic status)

    Attributes:
        SUPPORTED_ROLES: Class-level set of roles this provider supports
        PROVIDER_NAME: Human-readable name for logging

    Example:
        >>> class MyVectorProvider(BaseProvider):
        ...     SUPPORTED_ROLES = frozenset({"vector"})
        ...     PROVIDER_NAME = "MyVector"
        ...
        ...     @classmethod
        ...     def from_config(cls, config, project_id, **kwargs):
        ...         return cls(project_id=project_id)
        ...
        ...     async def _do_initialize(self) -> None:
        ...         # Create tables, connections, etc.
        ...         pass
        ...
        ...     async def _do_close(self) -> None:
        ...         # Release connections, etc.
        ...         pass
    """

    # =========================================================================
    # Class Attributes - Override in subclasses
    # =========================================================================

    SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset()
    """Storage roles this provider supports.

    Common roles:
        - "vector": Vector similarity search operations
        - "graph": Knowledge graph operations
        - "events": Event persistence operations
        - "file_tracker": File state tracking operations
    """

    PROVIDER_NAME: ClassVar[str] = "BaseProvider"
    """Human-readable name for logging and debugging."""

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, project_id: str) -> None:
        """Initialize base provider state.

        Args:
            project_id: Project identifier for data namespacing
        """
        self._project_id = project_id
        self._initialized = False

    @property
    def project_id(self) -> str:
        """Get the project ID for this provider."""
        return self._project_id

    @property
    def is_initialized(self) -> bool:
        """Check if the provider is initialized and ready for operations.

        Returns:
            True if provider is ready, False otherwise
        """
        return self._initialized

    # =========================================================================
    # Factory Method
    # =========================================================================

    @classmethod
    @abstractmethod
    def from_config(
        cls,
        config: Union["Config", Dict[str, Any]],
        project_id: str,
        **kwargs: Any,
    ) -> "BaseProvider":
        """Create a provider instance from configuration.

        Factory method that constructs a provider from configuration.
        The provider is NOT initialized after construction - call initialize()
        to create resources.

        Args:
            config: Configuration object or dictionary
            project_id: Project identifier for data namespacing
            **kwargs: Additional backend-specific arguments

        Returns:
            Uninitialized provider instance

        Raises:
            ValueError: If required configuration is missing or invalid
        """
        ...

    # =========================================================================
    # Lifecycle Operations
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the provider and create required resources.

        Creates all resources needed by the provider:
            - Database connections and connection pools
            - Tables, schemas, and indexes
            - Directories for file-based backends

        This method is idempotent - safe to call multiple times.
        Subclasses should override _do_initialize() for backend-specific logic.

        Raises:
            RuntimeError: If initialization fails
        """
        if self._initialized:
            logger.debug(
                "%s already initialized for project %s",
                self.PROVIDER_NAME,
                self._project_id,
            )
            return

        logger.info(
            "Initializing %s for project %s",
            self.PROVIDER_NAME,
            self._project_id,
        )

        try:
            await self._do_initialize()
            self._initialized = True
            logger.info(
                "%s initialized successfully for project %s",
                self.PROVIDER_NAME,
                self._project_id,
            )
        except Exception as e:
            logger.error(
                "Failed to initialize %s for project %s: %s",
                self.PROVIDER_NAME,
                self._project_id,
                e,
            )
            raise

    @abstractmethod
    async def _do_initialize(self) -> None:
        """Backend-specific initialization logic.

        Override this method in subclasses to implement initialization.
        Called by initialize() after idempotency check.

        Raises:
            RuntimeError: If initialization fails
        """
        ...

    async def close(self) -> None:
        """Close the provider and release all resources.

        Releases all resources acquired during initialize():
            - Closes database connections and drains connection pools
            - Releases file handles
            - Cleans up temporary resources

        This method is idempotent - safe to call multiple times.
        Subclasses should override _do_close() for backend-specific logic.
        """
        if not self._initialized:
            logger.debug(
                "%s not initialized for project %s, nothing to close",
                self.PROVIDER_NAME,
                self._project_id,
            )
            return

        logger.info(
            "Closing %s for project %s",
            self.PROVIDER_NAME,
            self._project_id,
        )

        try:
            await self._do_close()
        except Exception as e:
            logger.warning(
                "Error during %s close for project %s: %s",
                self.PROVIDER_NAME,
                self._project_id,
                e,
            )
        finally:
            self._initialized = False

    @abstractmethod
    async def _do_close(self) -> None:
        """Backend-specific cleanup logic.

        Override this method in subclasses to implement cleanup.
        Called by close() after idempotency check.
        """
        ...

    # =========================================================================
    # Health Check
    # =========================================================================

    async def health_check(self) -> Dict[str, Any]:
        """Check provider health and connectivity.

        Performs a lightweight health check to verify the provider is
        operational. Override in subclasses for backend-specific checks.

        Returns:
            Dictionary with health information:
                - status: "healthy", "degraded", or "unhealthy"
                - provider: Provider name
                - project_id: Project identifier
                - initialized: Whether provider is initialized
                - details: Optional backend-specific info
        """
        status = "healthy" if self._initialized else "unhealthy"
        return {
            "status": status,
            "provider": self.PROVIDER_NAME,
            "project_id": self._project_id,
            "initialized": self._initialized,
        }


class MaintenanceMixin:
    """Mixin for providers that support maintenance operations.

    Provides default implementations for maintenance operations.
    Override methods as needed for backend-specific behavior.

    Example:
        >>> class MyProvider(BaseProvider, MaintenanceMixin):
        ...     async def compact(self) -> Dict[str, Any]:
        ...         # Custom compaction logic
        ...         return {"compacted": True}
    """

    async def run_maintenance(self) -> Dict[str, Any]:
        """Run periodic maintenance tasks.

        Override in subclasses for backend-specific maintenance.

        Returns:
            Dictionary with maintenance results
        """
        return {
            "status": "completed",
            "message": "No maintenance tasks configured",
        }

    async def compact(self) -> Dict[str, Any]:
        """Compact storage to reclaim space.

        Override in subclasses for backend-specific compaction.

        Returns:
            Dictionary with compaction results
        """
        return {
            "status": "skipped",
            "message": "Compaction not supported by this provider",
        }

    async def validate_integrity(self) -> Dict[str, Any]:
        """Validate data integrity.

        Override in subclasses for backend-specific validation.

        Returns:
            Dictionary with validation results
        """
        return {
            "status": "valid",
            "message": "Integrity validation not implemented",
        }

    async def cleanup_orphaned_data(self) -> Dict[str, Any]:
        """Clean up orphaned data.

        Override in subclasses for backend-specific cleanup.

        Returns:
            Dictionary with cleanup results
        """
        return {
            "status": "completed",
            "message": "No orphaned data cleanup needed",
        }


# =========================================================================
# Exports
# =========================================================================

__all__ = [
    "BaseProvider",
    "MaintenanceMixin",
    "ProviderNotInitializedError",
    "require_initialized",
]
