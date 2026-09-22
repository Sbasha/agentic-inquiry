"""Tests for database factory functions.

These tests verify that factories correctly instantiate adapters based on
configuration and handle unsupported backends appropriately.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

from agent_vault.config import Config
from agent_vault.database.factories import (
    create_event_store,
    create_file_tracker,
    create_vector_adapter,
)
from agent_vault.database.lancedb_manager import LanceDBManager
from agent_vault.events.store import EventStore
from agent_vault.watching.file_tracker import FileTracker


class TestVectorAdapterFactory:
    """Tests for create_vector_adapter factory."""

    @pytest.mark.smoke
    @pytest.mark.asyncio
    async def test_create_lancedb_adapter_default(self, integration_config: Config) -> None:
        """Test that factory creates LanceDB adapter by default."""
        adapter = await create_vector_adapter(integration_config)

        # Should return LanceDBManager instance
        assert isinstance(adapter, LanceDBManager)

    @pytest.mark.asyncio
    async def test_create_lancedb_adapter_explicit(self, integration_config: Config) -> None:
        """Test that factory creates LanceDB adapter when explicitly configured."""
        # Explicitly set backend to lancedb
        integration_config.storage.backend = "lancedb"

        adapter = await create_vector_adapter(integration_config)

        # Should return LanceDBManager instance
        assert isinstance(adapter, LanceDBManager)

    @pytest.mark.asyncio
    async def test_unsupported_backend_raises_error(self, integration_config: Config) -> None:
        """Test that unsupported backend raises ValueError."""
        # Set unsupported backend
        integration_config.storage.backend = "qdrant"

        with pytest.raises(ValueError) as exc_info:
            await create_vector_adapter(integration_config)

        assert "Unsupported vector storage backend: qdrant" in str(exc_info.value)
        assert "only 'lancedb' is supported" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_multiple_factory_calls_create_separate_instances(
        self, integration_config: Config
    ) -> None:
        """Test that multiple factory calls create separate adapter instances."""
        adapter1 = await create_vector_adapter(integration_config)
        adapter2 = await create_vector_adapter(integration_config)

        # Should be different instances
        assert adapter1 is not adapter2


class TestEventStoreFactory:
    """Tests for create_event_store factory."""

    @pytest.mark.asyncio
    async def test_create_event_store_default(self, integration_config: Config) -> None:
        """Test that factory creates EventStore by default."""
        event_store = await create_event_store(integration_config)

        # Should return EventStore instance
        assert isinstance(event_store, EventStore)

    @pytest.mark.asyncio
    async def test_create_event_store_explicit(self, integration_config: Config) -> None:
        """Test that factory creates EventStore when explicitly configured."""
        # Explicitly set backend to sqlite
        integration_config.storage.event_store_backend = "sqlite"

        event_store = await create_event_store(integration_config)

        # Should return EventStore instance
        assert isinstance(event_store, EventStore)

    @pytest.mark.asyncio
    async def test_unsupported_backend_raises_error(self, integration_config: Config) -> None:
        """Test that unsupported backend raises ValueError."""
        # Set unsupported backend
        integration_config.storage.event_store_backend = "postgresql"

        with pytest.raises(ValueError) as exc_info:
            await create_event_store(integration_config)

        assert "Unsupported event store backend: postgresql" in str(exc_info.value)
        assert "only 'sqlite' is supported" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_multiple_factory_calls_create_separate_instances(
        self, integration_config: Config
    ) -> None:
        """Test that multiple factory calls create separate event store instances."""
        event_store1 = await create_event_store(integration_config)
        event_store2 = await create_event_store(integration_config)

        # Should be different instances
        assert event_store1 is not event_store2


class TestFileTrackerFactory:
    """Tests for create_file_tracker factory."""

    @pytest.mark.asyncio
    async def test_create_file_tracker_default(self, integration_config: Config) -> None:
        """Test that factory creates FileTracker by default."""
        file_tracker = await create_file_tracker(integration_config)

        # Should return FileTracker instance
        assert isinstance(file_tracker, FileTracker)

    @pytest.mark.asyncio
    async def test_create_file_tracker_explicit(self, integration_config: Config) -> None:
        """Test that factory creates FileTracker when explicitly configured."""
        # Explicitly set backend to sqlite
        integration_config.storage.file_tracker_backend = "sqlite"

        file_tracker = await create_file_tracker(integration_config)

        # Should return FileTracker instance
        assert isinstance(file_tracker, FileTracker)

    @pytest.mark.asyncio
    async def test_unsupported_backend_raises_error(self, integration_config: Config) -> None:
        """Test that unsupported backend raises ValueError."""
        # Set unsupported backend
        integration_config.storage.file_tracker_backend = "postgresql"

        with pytest.raises(ValueError) as exc_info:
            await create_file_tracker(integration_config)

        assert "Unsupported file tracker backend: postgresql" in str(exc_info.value)
        assert "only 'sqlite' is supported" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_multiple_factory_calls_create_separate_instances(
        self, integration_config: Config
    ) -> None:
        """Test that multiple factory calls create separate file tracker instances."""
        file_tracker1 = await create_file_tracker(integration_config)
        file_tracker2 = await create_file_tracker(integration_config)

        # Should be different instances
        assert file_tracker1 is not file_tracker2


class TestFactoryConfiguration:
    """Tests for factory configuration validation."""

    @pytest.mark.asyncio
    async def test_config_roundtrip_with_backends(self, integration_config: Config) -> None:
        """Test that backend config fields survive roundtrip to/from dict."""
        # Set all backend fields
        integration_config.storage.backend = "lancedb"
        integration_config.storage.event_store_backend = "sqlite"
        integration_config.storage.file_tracker_backend = "sqlite"

        # Convert to dict and back
        config_dict = integration_config.to_dict()
        assert config_dict['storage']['backend'] == "lancedb"
        assert config_dict['storage']['event_store_backend'] == "sqlite"
        assert config_dict['storage']['file_tracker_backend'] == "sqlite"

        # Load from dict should preserve values
        loaded_config = Config._from_dict(config_dict)
        assert loaded_config.storage.backend == "lancedb"
        assert loaded_config.storage.event_store_backend == "sqlite"
        assert loaded_config.storage.file_tracker_backend == "sqlite"

    @pytest.mark.asyncio
    async def test_default_backends_from_yaml(self) -> None:
        """Test that default backends are loaded correctly from YAML."""
        # Load default config (should have backend defaults)
        config = Config.load()

        # Check defaults
        assert config.storage.backend == "lancedb"
        assert config.storage.event_store_backend == "sqlite"
        assert config.storage.file_tracker_backend == "sqlite"


class TestFactoryIntegration:
    """Integration tests for factory functions."""

    @pytest.mark.asyncio
    async def test_all_factories_create_valid_instances(
        self, integration_config: Config
    ) -> None:
        """Test that all factories create valid instances."""
        # Create all components via factories
        adapter = await create_vector_adapter(integration_config)
        event_store = await create_event_store(integration_config)
        file_tracker = await create_file_tracker(integration_config)

        # All should be valid instances of their respective classes
        assert isinstance(adapter, LanceDBManager)
        assert isinstance(event_store, EventStore)
        assert isinstance(file_tracker, FileTracker)

    @pytest.mark.asyncio
    async def test_factories_respect_independent_backend_settings(
        self, integration_config: Config
    ) -> None:
        """Test that each factory respects its own backend setting."""
        # Each backend can be configured independently
        integration_config.storage.backend = "lancedb"
        integration_config.storage.event_store_backend = "sqlite"
        integration_config.storage.file_tracker_backend = "sqlite"

        # All factories should succeed
        adapter = await create_vector_adapter(integration_config)
        event_store = await create_event_store(integration_config)
        file_tracker = await create_file_tracker(integration_config)

        assert isinstance(adapter, LanceDBManager)
        assert isinstance(event_store, EventStore)
        assert isinstance(file_tracker, FileTracker)
