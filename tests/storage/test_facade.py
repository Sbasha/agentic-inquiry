"""Unit tests for StorageFacade.

Tests the updated StorageFacade that supports multiple provider types
(vector, graph, events, file_tracker) with the new registry system.
"""

import pytest

pytestmark = pytest.mark.unit
import warnings
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional, Dict, Any, List

from agentic_inquiry.storage.facade import StorageFacade


class MockVectorProvider:
    """Mock vector storage provider for testing."""

    SUPPORTED_ROLES = {"vector"}

    def __init__(self) -> None:
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def count(
        self,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> int:
        return 42

    async def query(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List[Any]:
        return []


class MockGraphProvider:
    """Mock graph storage provider for testing."""

    SUPPORTED_ROLES = {"graph"}

    def __init__(self) -> None:
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True


class MockEventsProvider:
    """Mock events storage provider for testing."""

    SUPPORTED_ROLES = {"events"}

    def __init__(self) -> None:
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def run_maintenance(self) -> Dict[str, Any]:
        return {"status": "ok", "cleaned": 0}


class MockFileTrackerProvider:
    """Mock file tracker provider for testing."""

    SUPPORTED_ROLES = {"file_tracker"}

    def __init__(self) -> None:
        self.initialized = False
        self.closed = False
        self._project_id = "test-project"

    @property
    def project_id(self) -> str:
        return self._project_id

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True


class MockPoolManager:
    """Mock pool manager for testing.

    Mirrors the real ``BackendPoolManager`` surface used by the facade:
    ``close_all()`` for teardown (the facade used to call
    ``close(backend_type)``, which was broken — pool keys are backend
    names, not types — and has been replaced with ``close_all``).
    """

    def __init__(self) -> None:
        self.closed = False

    async def close_all(self) -> int:
        self.closed = True
        return 0


class MockConfig:
    """Mock config for testing.

    Defaults to a populated ``backends`` registry because every
    ``from_config`` path now requires it — the legacy single-backend
    path was removed in task 5a. Tests that construct the facade
    directly (not via ``from_config``) can leave this alone; tests
    that exercise the missing-backends error path pass
    ``with_backends=False`` explicitly.

    ``with_backends=False`` also clears the legacy ``storage.backend``
    field — ``from_config`` now auto-migrates a populated legacy
    ``backend=`` to a synthesized registry config (with a
    ``DeprecationWarning``), so truly-empty configs need both fields
    unset to hit the ``ConfigurationError`` path.
    """

    def __init__(self, with_backends: bool = True) -> None:
        self.storage = MagicMock()
        # Empty string matches the real ``StorageConfig.backend`` default and
        # prevents the MagicMock auto-attr from looking truthy to the
        # legacy-migration branch in ``from_config``. Tests that want to
        # exercise the migration path assign a real backend string explicitly.
        self.storage.backend = ""
        if with_backends:
            self.storage.backends = {"default": {"type": "lancedb"}}
        else:
            self.storage.backends = None


class TestStorageFacadeConstructor:
    """Tests for StorageFacade constructor."""

    def test_minimal_constructor(self) -> None:
        """Test constructor with only required providers."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        assert facade._vector_provider is vector
        assert facade._graph_provider is graph
        assert facade._events_provider is None
        assert facade._file_tracker_provider is None
        assert facade._pool_manager is None
        assert facade._initialized is False

    def test_full_constructor(self) -> None:
        """Test constructor with all providers."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()
        events = MockEventsProvider()
        file_tracker = MockFileTrackerProvider()
        pool = MockPoolManager()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
            events_provider=events,
            file_tracker_provider=file_tracker,
            pool_manager=pool,
        )

        assert facade._vector_provider is vector
        assert facade._graph_provider is graph
        assert facade._events_provider is events
        assert facade._file_tracker_provider is file_tracker
        assert facade._pool_manager is pool

    def test_same_provider_for_vector_and_graph(self) -> None:
        """Test that same provider can be used for vector and graph."""
        config = MockConfig()
        provider = MockVectorProvider()
        provider.SUPPORTED_ROLES = {"vector", "graph"}

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=provider,
            graph_provider=provider,
        )

        assert facade._vector_provider is facade._graph_provider


class TestStorageFacadeProperties:
    """Tests for StorageFacade properties."""

    def test_vector_provider_property(self) -> None:
        """Test vector_provider property."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        assert facade.vector_provider is vector

    def test_graph_provider_property(self) -> None:
        """Test graph_provider property."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        assert facade.graph_provider is graph

    def test_events_provider_property_none(self) -> None:
        """Test events_provider property when not configured."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        assert facade.events_provider is None

    def test_events_provider_property_set(self) -> None:
        """Test events_provider property when configured."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()
        events = MockEventsProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
            events_provider=events,
        )

        assert facade.events_provider is events

    def test_file_tracker_provider_property(self) -> None:
        """Test file_tracker_provider property."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()
        ft = MockFileTrackerProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
            file_tracker_provider=ft,
        )

        assert facade.file_tracker_provider is ft

    def test_pool_manager_property(self) -> None:
        """Test pool_manager property."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()
        pool = MockPoolManager()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
            pool_manager=pool,
        )

        assert facade.pool_manager is pool


class TestStorageFacadeLifecycle:
    """Tests for StorageFacade lifecycle methods."""

    @pytest.mark.asyncio
    async def test_initialize_all_providers(self) -> None:
        """Test initialize() initializes all providers."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()
        events = MockEventsProvider()
        ft = MockFileTrackerProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
            events_provider=events,
            file_tracker_provider=ft,
        )

        await facade.initialize()

        assert vector.initialized is True
        assert graph.initialized is True
        assert events.initialized is True
        assert ft.initialized is True
        assert facade._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self) -> None:
        """Test initialize() is idempotent."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        await facade.initialize()
        await facade.initialize()  # Second call should be no-op

        assert facade._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_shared_provider_once(self) -> None:
        """Test initialize() only initializes shared provider once."""
        config = MockConfig()
        provider = MockVectorProvider()
        provider.init_count = 0
        original_init = provider.initialize

        async def counting_init():
            provider.init_count += 1
            await original_init()

        provider.initialize = counting_init

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=provider,
            graph_provider=provider,  # Same instance
        )

        await facade.initialize()

        # Should only be called once since vector and graph are same instance
        assert provider.init_count == 1

    @pytest.mark.asyncio
    async def test_close_all_providers(self) -> None:
        """Test close() closes all providers."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()
        events = MockEventsProvider()
        ft = MockFileTrackerProvider()
        pool = MockPoolManager()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
            events_provider=events,
            file_tracker_provider=ft,
            pool_manager=pool,
        )
        facade._initialized = True

        await facade.close()

        assert vector.closed is True
        assert graph.closed is True
        assert events.closed is True
        assert ft.closed is True
        assert pool.closed is True
        assert facade._initialized is False

    @pytest.mark.asyncio
    async def test_close_shared_provider_once(self) -> None:
        """Test close() only closes shared provider once."""
        config = MockConfig()
        provider = MockVectorProvider()
        provider.close_count = 0
        original_close = provider.close

        async def counting_close():
            provider.close_count += 1
            await original_close()

        provider.close = counting_close

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=provider,
            graph_provider=provider,  # Same instance
        )
        facade._initialized = True

        await facade.close()

        # Should only be called once since vector and graph are same instance
        assert provider.close_count == 1

    @pytest.mark.asyncio
    async def test_close_not_initialized(self) -> None:
        """Test close() is no-op when not initialized."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        await facade.close()

        assert vector.closed is False  # Should not be closed


class TestStorageFacadeLegacyMethods:
    """Tests for deprecated legacy methods."""

    @pytest.mark.asyncio
    async def test_count_records_deprecation_warning(self) -> None:
        """Test count_records emits deprecation warning."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await facade.count_records("chunks")

            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "count_records is deprecated" in str(w[0].message)

    @pytest.mark.asyncio
    async def test_count_records_delegates_to_protocol(self) -> None:
        """Test count_records delegates to provider.count() for chunks."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = await facade.count_records("chunks")

        assert result == 42  # MockVectorProvider.count returns 42

    @pytest.mark.asyncio
    async def test_advanced_filter_deprecation_warning(self) -> None:
        """Test advanced_filter emits deprecation warning."""
        config = MockConfig()
        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await facade.advanced_filter("chunks")

            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "advanced_filter is deprecated" in str(w[0].message)

    @pytest.mark.asyncio
    async def test_run_maintenance_delegates_to_providers(self) -> None:
        """Test run_maintenance delegates to all providers and aggregates results."""
        config = MockConfig()
        vector = MockVectorProvider()
        # Mock LanceDB-style return with compaction/cleanup/summary
        vector.run_maintenance = AsyncMock(return_value={
            "compaction": {"document_chunks": {"status": "success", "fragments_before": 10, "fragments_after": 2}},
            "cleanup": {"document_chunks": {"status": "success", "versions_before": 5, "versions_after": 1}},
            "summary": {"fragments_reduced": 8, "versions_removed": 4},
        })
        graph = MockGraphProvider()
        events = MockEventsProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
            events_provider=events,
        )

        result = await facade.run_maintenance()

        # Check aggregated structure
        assert "compaction" in result
        assert "cleanup" in result
        assert "summary" in result
        assert "providers" in result

        # Check aggregated values
        assert result["summary"]["fragments_reduced"] == 8
        assert result["summary"]["versions_removed"] == 4

        # Check per-provider breakdown in providers key
        assert "vector" in result["providers"]
        assert "events" in result["providers"]
        assert result["providers"]["events"]["status"] == "ok"


class TestStorageFacadeFromConfig:
    """Tests for StorageFacade.from_config factory method.

    ``from_config`` now requires the registry-shaped config
    (``storage.backends`` populated + ``vector_backend`` / ``graph_backend``
    pointers). The legacy single-``storage.backend`` fallback was removed
    so graph and vector roles can be served by genuinely different
    backends without one provider pretending to implement both protocols.
    """

    @pytest.mark.asyncio
    async def test_from_config_raises_when_backends_not_configured(self) -> None:
        """Missing ``backends`` dict must raise ``ConfigurationError`` with
        a pointer to ``ai setup``, not fall back to a legacy code path."""
        from agentic_inquiry.exceptions import ConfigurationError

        config = MockConfig(with_backends=False)
        with pytest.raises(ConfigurationError, match="ai setup"):
            await StorageFacade.from_config(
                config=config,
                project_id="test-project",
            )

    @pytest.mark.asyncio
    async def test_from_config_raises_when_backends_empty_dict(self) -> None:
        """Empty ``backends`` is the same misconfiguration as missing — must
        hit the same actionable ``ConfigurationError`` instead of falling
        through to a less-useful ``BackendResolutionError`` later."""
        from agentic_inquiry.exceptions import ConfigurationError

        config = MockConfig(with_backends=True)
        config.storage.backends = {}  # explicit empty dict
        with pytest.raises(ConfigurationError, match="ai setup"):
            await StorageFacade.from_config(
                config=config,
                project_id="test-project",
            )

    @pytest.mark.asyncio
    async def test_from_config_builds_facade_via_registry(self) -> None:
        """Happy path: with a populated ``backends`` dict, ``from_config``
        calls the registry for each role and returns an initialized facade."""
        from agentic_inquiry.storage.registry import BackendResolutionError

        config = MockConfig(with_backends=True)
        mock_vector = MockVectorProvider()
        mock_graph = MockGraphProvider()

        def _fake_create_provider(storage_cfg, role, **_kwargs):
            if role == "vector":
                return mock_vector
            if role == "graph":
                return mock_graph
            # events / file_tracker are optional; raising lets the facade
            # skip them without failing.
            raise BackendResolutionError(f"no {role} backend")

        with patch(
            "agentic_inquiry.storage.registry.create_provider",
            side_effect=_fake_create_provider,
        ), patch(
            "agentic_inquiry.storage.registry.resolve_backend",
            return_value=("default", {"type": "lancedb"}),
        ):
            facade = await StorageFacade.from_config(
                config=config,
                project_id="test-project",
            )

        assert facade._initialized is True
        assert facade._vector_provider is mock_vector
        assert facade._graph_provider is mock_graph
        assert mock_vector.initialized is True
        assert mock_graph.initialized is True


    @pytest.mark.asyncio
    async def test_from_config_skips_pool_manager_for_file_based_backends(
        self,
    ) -> None:
        """File-based backends (lancedb / sqlite / memory) should NOT
        allocate a ``BackendPoolManager`` — they have no pool to manage.
        """
        from agentic_inquiry.storage.registry import BackendResolutionError

        config = MockConfig(with_backends=True)
        mock_vector = MockVectorProvider()
        mock_graph = MockGraphProvider()

        def _fake_create_provider(storage_cfg, role, **_kwargs):
            if role == "vector":
                return mock_vector
            if role == "graph":
                return mock_graph
            raise BackendResolutionError(f"no {role} backend")

        with patch(
            "agentic_inquiry.storage.registry.create_provider",
            side_effect=_fake_create_provider,
        ), patch(
            "agentic_inquiry.storage.registry.resolve_backend",
            return_value=("default", {"type": "lancedb"}),
        ):
            facade = await StorageFacade.from_config(
                config=config,
                project_id="test-project",
            )

        assert facade._pool_manager is None

    @pytest.mark.asyncio
    async def test_from_config_ignores_legacy_provider_name_kwarg(
        self, caplog
    ) -> None:
        """``provider_name`` is retained on the signature for callers that
        still pass it, but no longer influences backend resolution. Passing
        it should emit BOTH a ``DeprecationWarning`` (for external test
        suites running under ``-W error::DeprecationWarning``) AND a log
        warning (for production logs where warnings filters may be
        silenced). The registry path still runs normally.

        The fake provider-factory raises ``BackendResolutionError`` for
        ``events`` / ``file_tracker`` so the optional-role skip path is
        actually exercised. A previous version returned ``mock_graph`` for
        every non-``"vector"`` role, which would have let a regression in
        the optional-provider handling silently pass.
        """
        import logging

        from agentic_inquiry.storage.registry import BackendResolutionError

        config = MockConfig(with_backends=True)
        mock_vector = MockVectorProvider()
        mock_graph = MockGraphProvider()

        def _fake_create_provider(storage_cfg, role, **_kwargs):
            if role == "vector":
                return mock_vector
            if role == "graph":
                return mock_graph
            raise BackendResolutionError(f"no {role} backend")

        caplog.set_level(logging.WARNING, logger="agentic_inquiry.storage.facade")
        with patch(
            "agentic_inquiry.storage.registry.create_provider",
            side_effect=_fake_create_provider,
        ), patch(
            "agentic_inquiry.storage.registry.resolve_backend",
            return_value=("default", {"type": "lancedb"}),
        ), pytest.warns(DeprecationWarning, match="provider_name"):
            facade = await StorageFacade.from_config(
                config=config,
                project_id="test-project",
                provider_name="lancedb",  # should be ignored with warnings
            )

        # Log warning must also fire (prod-log visibility).
        assert any(
            "ignored" in record.message and "provider_name" in record.message
            for record in caplog.records
        )
        # Optional providers must stay unset when registry can't resolve them.
        assert facade._events_provider is None
        assert facade._file_tracker_provider is None

    @pytest.mark.asyncio
    async def test_from_config_end_to_end_with_real_registry(self) -> None:
        """End-to-end ``from_config`` with the real registry — no patching.

        The other ``from_config`` tests in this class patch out
        ``storage.registry.create_provider`` so they validate the facade's
        control flow but not the registry/provider-construction wiring.
        With the legacy in-facade single-provider fallback removed, that
        wiring is the hot path for every non-test caller. This test pins
        the glue end-to-end using the ``memory`` backend (no external deps,
        no filesystem I/O) so a regression in ``registry.create_provider``
        kwarg handling (``type`` / ``config`` / ``pool_manager`` stripping)
        or provider constructor signatures surfaces here rather than in a
        downstream integration run.
        """
        from agentic_inquiry.config import Config, StorageConfig
        from agentic_inquiry.storage.providers.memory import InMemoryProvider

        config = Config(
            storage=StorageConfig(
                root="/tmp/ai-test-e2e",
                backends={"mem": {"type": "memory"}},
                vector_backend="mem",
                graph_backend="mem",
            ),
        )

        facade = await StorageFacade.from_config(
            config=config,
            project_id="e2e-test",
        )

        try:
            # Real provider instances, not mocks — the registry actually ran.
            assert isinstance(facade._vector_provider, InMemoryProvider)
            assert isinstance(facade._graph_provider, InMemoryProvider)
            # memory is not pg-compatible, so no pool manager should be
            # allocated and no connection manager should be returned.
            assert facade._pool_manager is None
            assert facade.get_connection_manager() is None
            # The facade must be initialized end-to-end.
            assert facade.is_initialized
        finally:
            await facade.close()

    @pytest.mark.asyncio
    async def test_from_config_auto_migrates_legacy_backend_field(self) -> None:
        """Programmatic callers that build ``StorageConfig(backend="memory")``
        without populating ``backends`` get an auto-synthesized registry
        config (plus a ``DeprecationWarning``). This preserves backward
        compatibility for internal fixtures without restoring the removed
        in-facade single-provider dispatch — the registry path is what
        actually constructs the provider.
        """
        from agentic_inquiry.config import Config, StorageConfig
        from agentic_inquiry.storage.providers.memory import InMemoryProvider

        config = Config(
            storage=StorageConfig(
                root="/tmp/ai-test-legacy",
                backend="memory",  # legacy field, no ``backends`` dict
            ),
        )

        with pytest.warns(DeprecationWarning, match="backend="):
            facade = await StorageFacade.from_config(
                config=config,
                project_id="legacy-test",
            )

        try:
            # Auto-migration must have produced real providers via the registry.
            assert isinstance(facade._vector_provider, InMemoryProvider)
            assert isinstance(facade._graph_provider, InMemoryProvider)
            assert facade.is_initialized
        finally:
            await facade.close()



class TestStorageFacadeTransaction:
    """Tests for StorageFacade.transaction() method."""

    def test_transaction_raises_error_for_local_vector_provider(self) -> None:
        """transaction() raises TransactionError for the local providers."""
        from agentic_inquiry.storage.exceptions import TransactionError

        config = MockConfig()
        # Add backend_timeouts mock to prevent AttributeError
        config.storage.backend_timeouts = MagicMock()
        config.storage.backend_timeouts.transaction_timeout = 30.0

        vector = MockVectorProvider()  # Not a transactional provider
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        with pytest.raises(TransactionError) as exc_info:
            facade.transaction()

        assert "MockVectorProvider" in str(exc_info.value)
        assert "does not support transactions" in str(exc_info.value)


    def test_transaction_uses_default_timeout_from_config(self) -> None:
        """Test that transaction() uses timeout from config when not specified."""
        from agentic_inquiry.storage.exceptions import TransactionError

        config = MockConfig()
        config.storage.backend_timeouts = MagicMock()
        config.storage.backend_timeouts.transaction_timeout = 60.0  # Custom timeout

        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        # Will raise TransactionError due to non-PostgreSQL providers,
        # but we can verify the config was accessed
        with pytest.raises(TransactionError):
            facade.transaction()

        # Config timeout was accessed (indirectly verified by no AttributeError)
        assert config.storage.backend_timeouts.transaction_timeout == 60.0

    def test_transaction_uses_custom_timeout(self) -> None:
        """Test that transaction() accepts custom timeout parameter."""
        from agentic_inquiry.storage.exceptions import TransactionError

        config = MockConfig()
        config.storage.backend_timeouts = MagicMock()
        config.storage.backend_timeouts.transaction_timeout = 30.0

        vector = MockVectorProvider()
        graph = MockGraphProvider()

        facade = StorageFacade(
            config=config,
            project_id="test-project",
            vector_provider=vector,
            graph_provider=graph,
        )

        # Will raise TransactionError due to non-PostgreSQL providers,
        # but we're testing the parameter is accepted without AttributeError
        with pytest.raises(TransactionError):
            facade.transaction(timeout=120.0)  # Custom timeout should be accepted
