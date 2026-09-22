"""Unit tests for storage provider registry.

Tests the registry system for lazy-loading and resolving storage providers.
"""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.storage.registry import (
    PROVIDER_REGISTRY,
    STORAGE_ROLES,
    UnknownBackendError,
    UnsupportedRoleError,
    get_supported_backends,
    get_supported_roles,
    is_role_supported,
    get_provider_class,
    register_provider,
    clear_cache,
    get_registry_info,
)


class TestRegistryBasics:
    """Tests for basic registry functionality."""

    def test_storage_roles_defined(self) -> None:
        """Verify STORAGE_ROLES contains expected roles."""
        expected = {"vector", "graph", "events", "file_tracker", "onboard_metadata"}
        assert STORAGE_ROLES == frozenset(expected)

    def test_get_supported_backends_returns_all_backends(self) -> None:
        """Test get_supported_backends returns registered backend types."""
        backends = get_supported_backends()
        assert "lancedb" in backends
        assert "sqlite" in backends
        assert "memory" in backends
        assert "postgresql" not in backends

    def test_get_supported_roles_lancedb(self) -> None:
        """Test LanceDB supports vector and graph roles."""
        roles = get_supported_roles("lancedb")
        assert "vector" in roles
        assert "graph" in roles
        # LanceDB doesn't support events/file_tracker
        assert "events" not in roles
        assert "file_tracker" not in roles

    def test_get_supported_roles_sqlite(self) -> None:
        """Test SQLite supports the record roles and no vector role."""
        roles = get_supported_roles("sqlite")
        assert "events" in roles
        assert "file_tracker" in roles
        assert "onboard_metadata" in roles
        assert "vector" not in roles

    def test_get_supported_roles_memory(self) -> None:
        """Test memory backend supports vector and graph only."""
        roles = get_supported_roles("memory")
        assert "vector" in roles
        assert "graph" in roles
        assert "events" not in roles

    def test_get_supported_roles_unknown_backend_raises(self) -> None:
        """Test get_supported_roles raises for unknown backend."""
        with pytest.raises(UnknownBackendError) as exc_info:
            get_supported_roles("nonexistent")
        assert "nonexistent" in str(exc_info.value)

    def test_is_role_supported_true(self) -> None:
        """Test is_role_supported returns True for valid combination."""
        assert is_role_supported("sqlite", "events") is True
        assert is_role_supported("lancedb", "vector") is True

    def test_is_role_supported_false(self) -> None:
        """Test is_role_supported returns False for unsupported role."""
        assert is_role_supported("lancedb", "events") is False
        assert is_role_supported("memory", "file_tracker") is False


class TestProviderClassLoading:
    """Tests for lazy-loading provider classes."""

    def test_get_provider_class_lancedb_vector(self) -> None:
        """Test loading LanceDB vector provider class."""
        clear_cache()
        provider_class = get_provider_class("lancedb", "vector")
        assert provider_class.__name__ == "LanceDBProvider"

    def test_get_provider_class_memory_vector(self) -> None:
        """Test loading memory vector provider class."""
        clear_cache()
        provider_class = get_provider_class("memory", "vector")
        # InMemoryVectorProvider is an alias for InMemoryProvider
        # The __name__ attribute returns the actual class name
        assert provider_class.__name__ == "InMemoryProvider"

    def test_get_provider_class_memory_graph(self) -> None:
        """Test loading memory graph provider class."""
        clear_cache()
        provider_class = get_provider_class("memory", "graph")
        # InMemoryGraphProvider is an alias for InMemoryProvider
        # The __name__ attribute returns the actual class name
        assert provider_class.__name__ == "InMemoryProvider"

    def test_get_provider_class_unknown_backend_raises(self) -> None:
        """Test get_provider_class raises for unknown backend."""
        with pytest.raises(UnknownBackendError) as exc_info:
            get_provider_class("nonexistent", "vector")
        assert "nonexistent" in str(exc_info.value)
        assert "Available backends" in str(exc_info.value)

    def test_get_provider_class_unsupported_role_raises(self) -> None:
        """Test get_provider_class raises for unsupported role."""
        with pytest.raises(UnsupportedRoleError) as exc_info:
            get_provider_class("lancedb", "events")
        assert "lancedb" in str(exc_info.value)
        assert "events" in str(exc_info.value)
        assert "does not support role" in str(exc_info.value)

    def test_get_provider_class_caches_result(self) -> None:
        """Test provider class is cached after first load."""
        clear_cache()
        class1 = get_provider_class("memory", "vector")
        class2 = get_provider_class("memory", "vector")
        assert class1 is class2

    def test_clear_cache_invalidates(self) -> None:
        """Test clear_cache invalidates the cache."""
        # Load to populate cache
        get_provider_class("memory", "vector")
        clear_cache()
        # Cache should be empty now - we can't easily verify this
        # but the function should complete without error
        clear_cache()


class TestProviderRegistration:
    """Tests for registering custom providers."""

    def test_register_provider_new_backend(self) -> None:
        """Test registering a provider for a new backend type."""
        # Register custom backend
        register_provider(
            "custom_db",
            "events",
            "agentic_inquiry.storage.providers.memory",
            "InMemoryVectorProvider",  # Using existing class for test
        )

        # Verify it was registered
        assert "custom_db" in get_supported_backends()
        assert "events" in get_supported_roles("custom_db")

        # Clean up
        del PROVIDER_REGISTRY["custom_db"]

    def test_register_provider_existing_backend(self) -> None:
        """Test registering a provider for an existing backend/new role."""
        # Store original
        original = PROVIDER_REGISTRY["memory"].copy()

        # Add events role to memory backend
        register_provider(
            "memory",
            "events",
            "agentic_inquiry.storage.providers.memory",
            "InMemoryVectorProvider",
        )

        # Verify
        assert is_role_supported("memory", "events")

        # Clean up
        PROVIDER_REGISTRY["memory"] = original

    def test_register_provider_invalid_role_raises(self) -> None:
        """Test registering with invalid role raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            register_provider("custom", "invalid_role", "module", "Class")
        assert "invalid_role" in str(exc_info.value)
        assert "Must be one of" in str(exc_info.value)


class TestRegistryInfo:
    """Tests for registry introspection."""

    def test_get_registry_info_structure(self) -> None:
        """Test get_registry_info returns correct structure."""
        info = get_registry_info()

        assert "lancedb" in info
        assert "sqlite" in info
        assert "vector" in info["lancedb"]
        assert "graph" in info["lancedb"]

    def test_get_registry_info_format(self) -> None:
        """Test registry info values are module.class strings."""
        info = get_registry_info()

        # Check format is "module.ClassName"
        lancedb_vector = info["lancedb"]["vector"]
        assert "agentic_inquiry.storage.providers.lancedb" in lancedb_vector
        assert "LanceDBProvider" in lancedb_vector
