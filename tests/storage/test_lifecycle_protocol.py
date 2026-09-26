# tests/storage/test_lifecycle_protocol.py
"""Tests for BackendLifecycle protocol and has_lifecycle_support helper."""

import pytest
from typing import Any, ClassVar, Dict

pytestmark = pytest.mark.unit

from agentic_inquiry.storage.protocols import BackendLifecycle, has_lifecycle_support


class TestBackendLifecycleProtocol:
    """Tests for BackendLifecycle protocol interface."""

    def test_protocol_is_runtime_checkable(self):
        """Test that BackendLifecycle can be used with isinstance()."""

        class MockProvider:
            """A mock provider implementing BackendLifecycle."""

            SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})

            @classmethod
            def from_config(
                cls, config: Dict[str, Any], project_id: str, **kwargs: Any
            ) -> "MockProvider":
                return cls()

            async def initialize(self) -> None:
                pass

            async def close(self) -> None:
                pass

            async def health_check(self) -> Dict[str, Any]:
                return {"status": "healthy", "latency_ms": 1.0}

            @property
            def is_initialized(self) -> bool:
                return True

        provider = MockProvider()
        assert isinstance(provider, BackendLifecycle)

    def test_has_lifecycle_support_with_conforming_implementation(self):
        """Test has_lifecycle_support returns True for conforming implementations."""

        class FullProvider:
            """Provider with all lifecycle methods."""

            SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector", "graph"})

            @classmethod
            def from_config(
                cls, config: Dict[str, Any], project_id: str, **kwargs: Any
            ) -> "FullProvider":
                return cls()

            async def initialize(self) -> None:
                pass

            async def close(self) -> None:
                pass

            async def health_check(self) -> Dict[str, Any]:
                return {"status": "healthy", "latency_ms": 0.5}

            @property
            def is_initialized(self) -> bool:
                return False

        provider = FullProvider()
        assert has_lifecycle_support(provider) is True

    def test_has_lifecycle_support_with_non_conforming_object(self):
        """Test has_lifecycle_support returns False for non-conforming objects."""

        class NotAProvider:
            """A class that doesn't implement the protocol."""

            pass

        obj = NotAProvider()
        assert has_lifecycle_support(obj) is False

    def test_has_lifecycle_support_with_partial_implementation(self):
        """Test has_lifecycle_support returns False for partial implementations."""

        class PartialProvider:
            """Provider missing some required methods."""

            SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})

            async def initialize(self) -> None:
                pass

            # Missing: from_config, close, health_check, is_initialized

        obj = PartialProvider()
        assert has_lifecycle_support(obj) is False

    def test_has_lifecycle_support_with_none(self):
        """Test has_lifecycle_support returns False for None."""
        assert has_lifecycle_support(None) is False

    def test_has_lifecycle_support_with_basic_types(self):
        """Test has_lifecycle_support returns False for basic types."""
        assert has_lifecycle_support("string") is False
        assert has_lifecycle_support(123) is False
        assert has_lifecycle_support([1, 2, 3]) is False
        assert has_lifecycle_support({"key": "value"}) is False


class TestBackendLifecycleCompliance:
    """Tests to verify implementations comply with the protocol contract."""

    @pytest.mark.asyncio
    async def test_mock_implementation_lifecycle(self):
        """Test that a mock implementation works through full lifecycle."""

        class TestableProvider:
            """A testable provider with tracked state."""

            SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})

            def __init__(self):
                self._initialized = False
                self._closed = False
                self._health_checks = 0

            @classmethod
            def from_config(
                cls, config: Dict[str, Any], project_id: str, **kwargs: Any
            ) -> "TestableProvider":
                instance = cls()
                instance._project_id = project_id
                instance._config = config
                return instance

            async def initialize(self) -> None:
                self._initialized = True
                self._closed = False

            async def close(self) -> None:
                self._initialized = False
                self._closed = True

            async def health_check(self) -> Dict[str, Any]:
                self._health_checks += 1
                return {
                    "status": "healthy" if self._initialized else "unhealthy",
                    "latency_ms": 1.5,
                    "details": {"checks": self._health_checks},
                }

            @property
            def is_initialized(self) -> bool:
                return self._initialized

        # Verify protocol compliance
        assert isinstance(TestableProvider, type)

        # Create from config
        config = {"uri": "/tmp/test", "dimension": 768}
        provider = TestableProvider.from_config(config, "test-project")

        assert isinstance(provider, BackendLifecycle)
        assert has_lifecycle_support(provider) is True

        # Initial state
        assert provider.is_initialized is False

        # Initialize
        await provider.initialize()
        assert provider.is_initialized is True

        # Health check
        health = await provider.health_check()
        assert health["status"] == "healthy"
        assert "latency_ms" in health

        # Idempotent initialize
        await provider.initialize()
        assert provider.is_initialized is True

        # Close
        await provider.close()
        assert provider.is_initialized is False

        # Health check after close
        health = await provider.health_check()
        assert health["status"] == "unhealthy"

    def test_supported_roles_is_class_attribute(self):
        """Test that SUPPORTED_ROLES works as a class attribute."""

        class MultiRoleProvider:
            """Provider supporting multiple roles."""

            SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset(
                {"vector", "graph", "events"}
            )

            @classmethod
            def from_config(
                cls, config: Dict[str, Any], project_id: str, **kwargs: Any
            ) -> "MultiRoleProvider":
                return cls()

            async def initialize(self) -> None:
                pass

            async def close(self) -> None:
                pass

            async def health_check(self) -> Dict[str, Any]:
                return {"status": "healthy", "latency_ms": 1.0}

            @property
            def is_initialized(self) -> bool:
                return True

        # Access as class attribute
        assert "vector" in MultiRoleProvider.SUPPORTED_ROLES
        assert "graph" in MultiRoleProvider.SUPPORTED_ROLES
        assert "events" in MultiRoleProvider.SUPPORTED_ROLES
        assert "file_tracker" not in MultiRoleProvider.SUPPORTED_ROLES

        # Access from instance
        provider = MultiRoleProvider()
        assert "vector" in provider.SUPPORTED_ROLES

    def test_from_config_receives_kwargs(self):
        """Test that from_config properly receives and uses kwargs."""

        class KwargsProvider:
            """Provider that uses kwargs in from_config."""

            SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})

            def __init__(self, extra_option: str = "default"):
                self._extra_option = extra_option

            @classmethod
            def from_config(
                cls, config: Dict[str, Any], project_id: str, **kwargs: Any
            ) -> "KwargsProvider":
                extra = kwargs.get("extra_option", "default")
                return cls(extra_option=extra)

            async def initialize(self) -> None:
                pass

            async def close(self) -> None:
                pass

            async def health_check(self) -> Dict[str, Any]:
                return {"status": "healthy", "latency_ms": 1.0}

            @property
            def is_initialized(self) -> bool:
                return True

        # Without kwargs
        provider1 = KwargsProvider.from_config({}, "proj")
        assert provider1._extra_option == "default"

        # With kwargs
        provider2 = KwargsProvider.from_config({}, "proj", extra_option="custom")
        assert provider2._extra_option == "custom"


class TestHealthCheckContract:
    """Tests for the health_check return format contract."""

    @pytest.mark.asyncio
    async def test_health_check_returns_required_fields(self):
        """Test that health_check returns required fields."""

        class HealthyProvider:
            """Provider with proper health check."""

            SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})

            @classmethod
            def from_config(
                cls, config: Dict[str, Any], project_id: str, **kwargs: Any
            ) -> "HealthyProvider":
                return cls()

            async def initialize(self) -> None:
                pass

            async def close(self) -> None:
                pass

            async def health_check(self) -> Dict[str, Any]:
                return {
                    "status": "healthy",
                    "latency_ms": 5.2,
                    "details": {"tables": 4, "connections": 2},
                }

            @property
            def is_initialized(self) -> bool:
                return True

        provider = HealthyProvider()
        health = await provider.health_check()

        # Required fields
        assert "status" in health
        assert health["status"] in ("healthy", "degraded", "unhealthy")
        assert "latency_ms" in health
        assert isinstance(health["latency_ms"], (int, float))

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_includes_error(self):
        """Test that unhealthy status includes error message."""

        class UnhealthyProvider:
            """Provider that reports unhealthy status."""

            SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})

            @classmethod
            def from_config(
                cls, config: Dict[str, Any], project_id: str, **kwargs: Any
            ) -> "UnhealthyProvider":
                return cls()

            async def initialize(self) -> None:
                pass

            async def close(self) -> None:
                pass

            async def health_check(self) -> Dict[str, Any]:
                return {
                    "status": "unhealthy",
                    "latency_ms": 0,
                    "error": "Connection refused: database unavailable",
                }

            @property
            def is_initialized(self) -> bool:
                return False

        provider = UnhealthyProvider()
        health = await provider.health_check()

        assert health["status"] == "unhealthy"
        assert "error" in health
        assert isinstance(health["error"], str)


class TestRealProviderSupportedRoles:
    """Tests for SUPPORTED_ROLES compliance in actual provider implementations."""

    def test_inmemory_provider_supported_roles_constraint(self):
        """Test that InMemoryProvider only advertises roles it actually supports.

        InMemoryProvider should only support vector and graph roles, not events
        or file_tracker (those require persistent storage like SQLite).
        """
        from agentic_inquiry.storage.providers.memory import InMemoryProvider

        # Verify SUPPORTED_ROLES is exactly what we expect
        assert InMemoryProvider.SUPPORTED_ROLES == frozenset({"vector", "graph"})

        # Verify it does NOT include unsupported roles
        assert "events" not in InMemoryProvider.SUPPORTED_ROLES
        assert "file_tracker" not in InMemoryProvider.SUPPORTED_ROLES

    def test_lancedb_provider_supported_roles(self):
        """Test that LanceDBProvider advertises correct roles."""
        from agentic_inquiry.storage.providers.lancedb import LanceDBProvider

        # LanceDB supports vector and graph
        assert "vector" in LanceDBProvider.SUPPORTED_ROLES
        assert "graph" in LanceDBProvider.SUPPORTED_ROLES

        # LanceDB does not support events or file_tracker
        assert "events" not in LanceDBProvider.SUPPORTED_ROLES
        assert "file_tracker" not in LanceDBProvider.SUPPORTED_ROLES
