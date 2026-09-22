# tests/connectors/test_registry.py
"""Tests for ConnectorRegistry thread-safe implementation."""
import concurrent.futures
import threading
import pytest

pytestmark = pytest.mark.unit
from typing import AsyncIterator

from agent_vault.connectors.registry import (
    ConnectorRegistry,
    get_connector,
    list_connectors,
    register_connector,
    unregister_connector,
    clear_registry,
)
from agent_vault.connectors.types import SourceItem, SourceContent

# Snapshot of the built-in registrations, captured at import time — before any
# test body runs, when the registry holds exactly the package built-ins
# (filesystem, file, s3, gcs) and cannot have absorbed leaked test state.
# Tests in this module deliberately reset the singleton; without restoration
# that empties the registry for later test files (e.g. the S3/GCS registration
# tests). _register_builtin_connectors() cannot restore the cloud connectors
# after a reset because the @register_connector decorator only fires on first
# module import, so we re-register the captured factories instead.
_BUILTIN_CONNECTORS = {
    name: ConnectorRegistry.get_instance().get_factory(name)
    for name in ConnectorRegistry.get_instance().list_names()
}


@pytest.fixture(autouse=True)
def isolated_registry():
    """Give each test a fresh registry, then restore the built-in connectors."""
    ConnectorRegistry.reset_instance()
    yield
    ConnectorRegistry.reset_instance()
    restored = ConnectorRegistry.get_instance()
    for name, factory in _BUILTIN_CONNECTORS.items():
        if factory is not None:
            restored.register(name, factory)


class MockConnector:
    """Mock connector for testing."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def list(self, root: str) -> AsyncIterator[SourceItem]:
        raise NotImplementedError

    async def open(self, item: SourceItem) -> SourceContent:
        raise NotImplementedError


class TestConnectorRegistrySingleton:
    """Tests for singleton pattern."""

    def test_get_instance_returns_same_instance(self):
        """Test that get_instance always returns the same object."""
        instance1 = ConnectorRegistry.get_instance()
        instance2 = ConnectorRegistry.get_instance()
        assert instance1 is instance2

    def test_reset_instance_creates_new_instance(self):
        """Test that reset_instance allows creating a fresh instance."""
        instance1 = ConnectorRegistry.get_instance()
        ConnectorRegistry.reset_instance()
        instance2 = ConnectorRegistry.get_instance()
        assert instance1 is not instance2

    def test_singleton_thread_safety(self):
        """Test that singleton creation is thread-safe."""
        # Reset to start fresh
        ConnectorRegistry.reset_instance()

        instances = []
        errors = []

        def get_instance():
            try:
                instance = ConnectorRegistry.get_instance()
                instances.append(instance)
            except Exception as e:
                errors.append(e)

        # Create 50 threads all trying to get the instance simultaneously
        threads = [threading.Thread(target=get_instance) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All threads should get the same instance
        assert all(inst is instances[0] for inst in instances)


class TestConnectorRegistryOperations:
    """Tests for registry operations."""

    def test_register_and_get(self):
        """Test basic register and get functionality."""
        registry = ConnectorRegistry.get_instance()
        registry.register("test", MockConnector)

        connector = registry.get("test", foo="bar")
        assert isinstance(connector, MockConnector)
        assert connector.kwargs == {"foo": "bar"}

    def test_register_overwrites_with_warning(self, caplog):
        """Test that registering same name warns and overwrites."""
        registry = ConnectorRegistry.get_instance()

        class Connector1:
            pass

        class Connector2:
            pass

        registry.register("test", Connector1)
        registry.register("test", Connector2)

        assert "Overwriting connector registration: test" in caplog.text
        assert registry.get_factory("test") is Connector2

    def test_get_unknown_raises_keyerror(self):
        """Test that getting unknown connector raises KeyError."""
        registry = ConnectorRegistry.get_instance()

        with pytest.raises(KeyError) as exc_info:
            registry.get("nonexistent")

        assert "Unknown connector: nonexistent" in str(exc_info.value)

    def test_list_names(self):
        """Test listing registered connector names."""
        registry = ConnectorRegistry.get_instance()
        registry.register("alpha", MockConnector)
        registry.register("beta", MockConnector)
        registry.register("gamma", MockConnector)

        names = registry.list_names()
        assert set(names) == {"alpha", "beta", "gamma"}

    def test_unregister(self):
        """Test unregistering a connector."""
        registry = ConnectorRegistry.get_instance()
        registry.register("test", MockConnector)

        assert registry.unregister("test") is True
        assert "test" not in registry

    def test_unregister_nonexistent_returns_false(self):
        """Test unregistering nonexistent connector returns False."""
        registry = ConnectorRegistry.get_instance()
        assert registry.unregister("nonexistent") is False

    def test_clear(self):
        """Test clearing all connectors."""
        registry = ConnectorRegistry.get_instance()
        registry.register("a", MockConnector)
        registry.register("b", MockConnector)
        registry.register("c", MockConnector)

        registry.clear()

        assert len(registry) == 0
        assert registry.list_names() == []

    def test_contains(self):
        """Test __contains__ method."""
        registry = ConnectorRegistry.get_instance()
        registry.register("test", MockConnector)

        assert "test" in registry
        assert "other" not in registry

    def test_len(self):
        """Test __len__ method."""
        registry = ConnectorRegistry.get_instance()
        assert len(registry) == 0

        registry.register("a", MockConnector)
        assert len(registry) == 1

        registry.register("b", MockConnector)
        assert len(registry) == 2

    def test_get_factory(self):
        """Test getting factory without instantiation."""
        registry = ConnectorRegistry.get_instance()
        registry.register("test", MockConnector)

        factory = registry.get_factory("test")
        assert factory is MockConnector

    def test_get_factory_nonexistent_returns_none(self):
        """Test getting nonexistent factory returns None."""
        registry = ConnectorRegistry.get_instance()
        assert registry.get_factory("nonexistent") is None


class TestConnectorRegistryConcurrency:
    """Tests for concurrent access to the registry."""

    def test_concurrent_register(self):
        """Test concurrent registration from multiple threads."""
        registry = ConnectorRegistry.get_instance()
        errors = []

        def register_connector(name: str):
            try:
                class DynamicConnector:
                    connector_name = name
                registry.register(name, DynamicConnector)
            except Exception as e:
                errors.append(e)

        # Register 100 connectors concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(register_connector, f"connector_{i}")
                for i in range(100)
            ]
            concurrent.futures.wait(futures)

        assert len(errors) == 0
        assert len(registry) == 100

    def test_concurrent_get(self):
        """Test concurrent get operations."""
        registry = ConnectorRegistry.get_instance()
        registry.register("test", MockConnector)

        results = []
        errors = []

        def get_connector_instance():
            try:
                connector = registry.get("test")
                results.append(connector)
            except Exception as e:
                errors.append(e)

        # 100 concurrent gets
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(get_connector_instance)
                for _ in range(100)
            ]
            concurrent.futures.wait(futures)

        assert len(errors) == 0
        assert len(results) == 100
        # Each call should create a new instance
        assert all(isinstance(r, MockConnector) for r in results)

    def test_concurrent_mixed_operations(self):
        """Test mix of register, get, unregister, list operations."""
        registry = ConnectorRegistry.get_instance()
        errors = []

        # Pre-register some connectors
        for i in range(10):
            registry.register(f"initial_{i}", MockConnector)

        def register_op(name: str):
            try:
                registry.register(name, MockConnector)
            except Exception as e:
                errors.append(("register", e))

        def get_op(name: str):
            try:
                registry.get(name)
            except KeyError:
                pass  # Expected for some operations
            except Exception as e:
                errors.append(("get", e))

        def list_op():
            try:
                registry.list_names()
            except Exception as e:
                errors.append(("list", e))

        def unregister_op(name: str):
            try:
                registry.unregister(name)
            except Exception as e:
                errors.append(("unregister", e))

        def contains_op(name: str):
            try:
                _ = name in registry
            except Exception as e:
                errors.append(("contains", e))

        # Mix of operations
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            futures = []
            for i in range(50):
                futures.append(executor.submit(register_op, f"new_{i}"))
                futures.append(executor.submit(get_op, f"initial_{i % 10}"))
                futures.append(executor.submit(list_op))
                futures.append(executor.submit(contains_op, f"initial_{i % 10}"))
                if i % 5 == 0:
                    futures.append(executor.submit(unregister_op, f"initial_{i % 10}"))
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Errors occurred: {errors}"


class TestModuleLevelAPI:
    """Tests for backward-compatible module-level functions."""

    def test_register_connector_direct(self):
        """Test register_connector with direct call."""
        result = register_connector("test", MockConnector)
        assert result is MockConnector

        connector = get_connector("test")
        assert isinstance(connector, MockConnector)

    def test_register_connector_decorator(self):
        """Test register_connector as decorator."""
        @register_connector("decorated")
        class DecoratedConnector:
            pass

        assert "decorated" in list_connectors()

    def test_list_connectors(self):
        """Test list_connectors function."""
        register_connector("a", MockConnector)
        register_connector("b", MockConnector)

        names = list_connectors()
        assert "a" in names
        assert "b" in names

    def test_unregister_connector(self):
        """Test unregister_connector function."""
        register_connector("test", MockConnector)
        assert unregister_connector("test") is True
        assert "test" not in list_connectors()

    def test_clear_registry(self):
        """Test clear_registry function."""
        register_connector("a", MockConnector)
        register_connector("b", MockConnector)

        clear_registry()
        assert list_connectors() == []


class TestRLockBehavior:
    """Tests verifying RLock allows reentrant access."""

    def test_reentrant_access_in_factory(self):
        """Test that factory can access registry (reentrant lock)."""
        registry = ConnectorRegistry.get_instance()

        class ReentrantConnector:
            """Connector that accesses registry during construction."""

            def __init__(self):
                # This would deadlock with a regular Lock
                self.registry_names = registry.list_names()

        registry.register("other", MockConnector)
        registry.register("reentrant", ReentrantConnector)

        # This should not deadlock
        connector = registry.get("reentrant")
        assert "other" in connector.registry_names
