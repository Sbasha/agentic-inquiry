"""Tests for base provider classes."""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.storage.providers.base import (
    BaseProvider,
    MaintenanceMixin,
    ProviderNotInitializedError,
    require_initialized,
)


class ConcreteProvider(BaseProvider):
    """Concrete implementation for testing."""

    SUPPORTED_ROLES = frozenset({"test"})
    PROVIDER_NAME = "TestProvider"

    def __init__(self, project_id: str = "test"):
        super().__init__(project_id)
        self.init_called = False
        self.close_called = False

    @classmethod
    def from_config(cls, config, project_id, **kwargs):
        return cls(project_id=project_id)

    async def _do_initialize(self) -> None:
        self.init_called = True

    async def _do_close(self) -> None:
        self.close_called = True

    @require_initialized
    async def query(self):
        return "query_result"


class ProviderWithMaintenance(ConcreteProvider, MaintenanceMixin):
    """Provider with maintenance mixin for testing."""

    async def compact(self):
        return {"status": "compacted", "rows": 100}


class TestBaseProvider:
    """Tests for BaseProvider class."""

    def test_initialization_state(self):
        """Test initial state before initialization."""
        provider = ConcreteProvider("proj1")
        assert provider.project_id == "proj1"
        assert not provider.is_initialized
        assert not provider.init_called

    @pytest.mark.asyncio
    async def test_initialize(self):
        """Test initialize() method."""
        provider = ConcreteProvider()
        assert not provider.is_initialized

        await provider.initialize()

        assert provider.is_initialized
        assert provider.init_called

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self):
        """Test that initialize() is idempotent."""
        provider = ConcreteProvider()
        provider.init_count = 0

        async def counting_init():
            provider.init_count += 1

        provider._do_initialize = counting_init

        await provider.initialize()
        await provider.initialize()
        await provider.initialize()

        assert provider.init_count == 1

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close() method."""
        provider = ConcreteProvider()
        await provider.initialize()
        assert provider.is_initialized

        await provider.close()

        assert not provider.is_initialized
        assert provider.close_called

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Test that close() is idempotent."""
        provider = ConcreteProvider()
        await provider.initialize()

        provider.close_count = 0

        async def counting_close():
            provider.close_count += 1

        provider._do_close = counting_close

        await provider.close()
        await provider.close()
        await provider.close()

        assert provider.close_count == 1

    @pytest.mark.asyncio
    async def test_close_before_init(self):
        """Test that close() before init is a no-op."""
        provider = ConcreteProvider()
        assert not provider.is_initialized

        await provider.close()

        assert not provider.is_initialized
        assert not provider.close_called

    @pytest.mark.asyncio
    async def test_health_check_uninitialized(self):
        """Test health check when not initialized."""
        provider = ConcreteProvider()
        health = await provider.health_check()

        assert health["status"] == "unhealthy"
        assert health["provider"] == "TestProvider"
        assert health["initialized"] is False

    @pytest.mark.asyncio
    async def test_health_check_initialized(self):
        """Test health check when initialized."""
        provider = ConcreteProvider()
        await provider.initialize()

        health = await provider.health_check()

        assert health["status"] == "healthy"
        assert health["initialized"] is True

    def test_from_config(self):
        """Test from_config factory method."""
        provider = ConcreteProvider.from_config(
            config={"key": "value"},
            project_id="test_project",
        )

        assert isinstance(provider, ConcreteProvider)
        assert provider.project_id == "test_project"
        assert not provider.is_initialized

    @pytest.mark.asyncio
    async def test_initialize_error_handling(self):
        """Test that initialization errors are propagated."""
        provider = ConcreteProvider()

        async def failing_init():
            raise ValueError("Init failed")

        provider._do_initialize = failing_init

        with pytest.raises(ValueError, match="Init failed"):
            await provider.initialize()

        assert not provider.is_initialized


class TestRequireInitialized:
    """Tests for require_initialized decorator."""

    @pytest.mark.asyncio
    async def test_blocks_uninitialized_access(self):
        """Test that decorator blocks access when not initialized."""
        provider = ConcreteProvider()
        assert not provider.is_initialized

        with pytest.raises(ProviderNotInitializedError) as exc_info:
            await provider.query()

        assert "ConcreteProvider" in str(exc_info.value)
        assert "query" in str(exc_info.value)
        assert "initialize()" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_allows_initialized_access(self):
        """Test that decorator allows access when initialized."""
        provider = ConcreteProvider()
        await provider.initialize()

        result = await provider.query()

        assert result == "query_result"

    @pytest.mark.asyncio
    async def test_blocks_after_close(self):
        """Test that decorator blocks access after close."""
        provider = ConcreteProvider()
        await provider.initialize()
        await provider.close()

        with pytest.raises(ProviderNotInitializedError):
            await provider.query()


class TestMaintenanceMixin:
    """Tests for MaintenanceMixin class."""

    @pytest.mark.asyncio
    async def test_default_run_maintenance(self):
        """Test default run_maintenance returns completed status."""
        provider = ProviderWithMaintenance()
        result = await provider.run_maintenance()

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_overridden_compact(self):
        """Test that overridden compact works."""
        provider = ProviderWithMaintenance()
        result = await provider.compact()

        assert result["status"] == "compacted"
        assert result["rows"] == 100

    @pytest.mark.asyncio
    async def test_default_validate_integrity(self):
        """Test default validate_integrity returns valid status."""
        provider = ProviderWithMaintenance()
        result = await provider.validate_integrity()

        assert result["status"] == "valid"

    @pytest.mark.asyncio
    async def test_default_cleanup_orphaned_data(self):
        """Test default cleanup_orphaned_data returns completed status."""
        provider = ProviderWithMaintenance()
        result = await provider.cleanup_orphaned_data()

        assert result["status"] == "completed"


class TestProviderNotInitializedError:
    """Tests for ProviderNotInitializedError."""

    def test_error_message(self):
        """Test error message formatting."""
        error = ProviderNotInitializedError("MyProvider", "my_method")

        assert error.provider_name == "MyProvider"
        assert error.method_name == "my_method"
        assert "MyProvider.my_method()" in str(error)
        assert "initialize()" in str(error)

    def test_is_runtime_error(self):
        """Test that error is a RuntimeError."""
        error = ProviderNotInitializedError("P", "m")
        assert isinstance(error, RuntimeError)
