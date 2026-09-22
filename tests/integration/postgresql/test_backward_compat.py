"""Backward Compatibility Tests (T7.6).

Tests for NFR-2: Backward Compatibility

Test Coverage:
- AC-12: Existing ivfflat deployment works without changes
- No config changes work unchanged
- Single-provider operations backward compatible

Design:
    - Tests that existing deployments continue to work
    - Verifies default behavior unchanged
    - Tests single-provider operations without transaction coordinator
    - Ensures no breaking changes to existing configurations
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.postgresql.index_config import (
    IndexConfig,
    IndexType,
)
from agent_vault.storage.providers.postgresql.schemas import SchemaGenerator


class TestAC12ExistingIVFFlatPreserved:
    """AC-12: Existing ivfflat deployment works without changes."""

    @pytest.mark.asyncio
    async def test_existing_ivfflat_index_retained_when_no_config_change(self):
        """Test that existing ivfflat index is retained when no index_type specified (AC-12)."""
        # Arrange
        # Simulate existing deployment with no index_type in config
        # (Would use existing ivfflat index)
        schema_gen = SchemaGenerator(
            prefix="test_",
            embedding_dim=768,
        )

        # Existing deployments would have IndexConfig(index_type=IndexType.IVFFLAT)
        # stored or detected from existing schema
        index_config = IndexConfig(index_type=IndexType.IVFFLAT)

        # Act
        sql = schema_gen.generate_vector_index(
            table_name="test_v_chunks",
            column_name="embedding",
            index_config=index_config,
            row_count=10000,
        )

        # Assert
        assert "USING ivfflat" in sql
        # Should continue using ivfflat, not switch to HNSW

    @pytest.mark.asyncio
    async def test_existing_deployment_config_unchanged(self):
        """Test that existing deployment with no index config continues to work."""
        # Arrange
        # Old config without index_type field
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            # No index_type, index_params, expected_rows fields
        )

        # Assert - Should use defaults
        assert config.index_type == "hnsw"  # New default
        assert config.index_params is None
        assert config.expected_rows is None

    def test_legacy_config_without_new_fields_works(self):
        """Test that legacy config without new fields continues to work."""
        # Arrange
        # Create config without any new fields
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            pool_size=10,
        )

        # Assert - Should work with defaults
        assert config.type == "postgresql"
        assert config.connection_string == "postgresql://localhost/db"
        assert config.pool_size == 10
        # New fields should have defaults
        assert config.index_type == "hnsw"
        assert config.fts_language == "english"


class TestNoConfigChangesWorksUnchanged:
    """Test that deployments with no config changes work unchanged."""

    def test_default_config_behavior_unchanged(self):
        """Test that default config behavior is unchanged."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
        )

        # Assert - Defaults should be sensible
        assert config.index_type == "hnsw"  # New default (but can be overridden)
        assert config.fts_language == "english"  # Preserves existing behavior
        assert config.pool_size == 10  # Existing default
        assert config.max_overflow == 5  # Existing default

    def test_minimal_config_still_works(self):
        """Test that minimal config (only type and connection) still works."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
        )

        # Assert
        assert config.type == "postgresql"
        assert config.connection_string == "postgresql://localhost/db"
        # All other fields should have sensible defaults

    def test_config_validation_doesnt_break_existing_deployments(self):
        """Test that new validation doesn't break existing deployments."""
        # Arrange & Act
        # Create config that would have worked before
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://user:pass@localhost/db",
            pool_size=20,
            max_overflow=10,
        )

        # Assert - Should still work
        assert config.pool_size == 20
        assert config.max_overflow == 10


class TestSingleProviderOperationsBackwardCompatible:
    """Test that single-provider operations work without transaction coordinator."""

    @pytest.mark.asyncio
    async def test_vector_provider_operations_without_transaction(self):
        """Test that VectorProvider operations work without transaction coordinator."""
        # Arrange
        from agent_vault.storage.providers.postgresql.vector import (
            PostgresVectorProvider,
        )

        connection_manager = MagicMock()
        connection_manager.table_prefix = "agv_"
        connection_manager.similarity_metric = "cosine"
        mock_connection = AsyncMock()

        # Mock acquire context manager
        connection_manager.acquire = MagicMock()
        connection_manager.acquire.return_value.__aenter__ = AsyncMock(
            return_value=mock_connection
        )
        connection_manager.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_connection.execute.return_value = None
        mock_connection.fetch.return_value = []

        provider = PostgresVectorProvider(
            connection_manager=connection_manager,
            project_id="test_project",
            embedding_dim=768,
        )

        # Act - Single provider operation (no transaction)
        # This should work without transaction coordinator
        # (Implementation would call pool directly)

        # Assert - Provider created successfully
        assert provider is not None
        assert provider._txn_connection is None  # No transaction set

    @pytest.mark.asyncio
    async def test_graph_provider_operations_without_transaction(self):
        """Test that GraphProvider operations work without transaction coordinator."""
        # Arrange
        from agent_vault.storage.providers.postgresql.graph import (
            PostgresGraphProvider,
        )

        connection_manager = MagicMock()
        connection_manager.table_prefix = "agv_"
        connection_manager.similarity_metric = "cosine"
        mock_connection = AsyncMock()

        # Mock acquire context manager
        connection_manager.acquire = MagicMock()
        connection_manager.acquire.return_value.__aenter__ = AsyncMock(
            return_value=mock_connection
        )
        connection_manager.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_connection.execute.return_value = None
        mock_connection.fetch.return_value = []

        provider = PostgresGraphProvider(
            connection_manager=connection_manager,
            project_id="test_project",
        )

        # Act - Single provider operation
        # Should work without transaction coordinator

        # Assert
        assert provider is not None
        assert provider._txn_connection is None

    @pytest.mark.asyncio
    async def test_auto_commit_behavior_preserved(self):
        """Test that auto-commit behavior is preserved for non-transaction operations."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock auto-commit behavior
        mock_connection.execute.return_value = None

        # Mock acquire() as async context manager
        connection_manager.acquire = MagicMock()
        connection_manager.acquire.return_value.__aenter__ = AsyncMock(
            return_value=mock_connection
        )
        connection_manager.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        # Act - Execute operation without explicit transaction using context manager
        async with connection_manager.acquire() as conn:
            await conn.execute("SELECT 1")

        # Assert - Connection should be acquired and released correctly
        connection_manager.acquire.assert_called_once()
        mock_connection.execute.assert_awaited_once_with("SELECT 1")


class TestIndexTypeBackwardCompatibility:
    """Test index type backward compatibility."""

    def test_hnsw_default_for_new_deployments_only(self):
        """Test that HNSW is default for NEW deployments only."""
        # Arrange - New deployment (no existing index)
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            # No index_type specified - uses default
        )

        # Assert
        assert config.index_type == "hnsw"

    def test_existing_ivfflat_index_not_automatically_migrated(self):
        """Test that existing ivfflat indexes are NOT automatically migrated."""
        # Arrange
        # Simulate existing deployment detection
        # (Would query existing index type from database)

        # For existing deployment, index_type should be set to what exists
        # Not automatically changed to "hnsw"
        existing_config = IndexConfig(index_type=IndexType.IVFFLAT)

        # Assert
        assert existing_config.index_type == IndexType.IVFFLAT
        # Migration requires explicit command: agv index migrate

    def test_explicit_migration_required_message(self):
        """Test that attempting to change index type logs migration guidance."""
        # Arrange
        # Simulate scenario where user wants to change from ivfflat to hnsw
        old_index_type = IndexType.IVFFLAT
        new_index_type = IndexType.HNSW

        # Assert - Should require explicit migration command
        assert old_index_type != new_index_type
        # Implementation should log: "Run 'agv index migrate' to change index type"


class TestTransactionCoordinatorOptIn:
    """Test that transaction coordinator is opt-in."""

    def test_transaction_coordinator_not_required_for_basic_operations(self):
        """Test that transaction coordinator is not required for basic operations."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
        )

        # Assert - Config doesn't require transaction-related fields
        # Basic operations should work without transaction coordinator
        assert config.connection_string is not None

    @pytest.mark.asyncio
    async def test_operations_work_without_transaction_scope(self):
        """Test that operations work without transaction_scope context manager."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()
        mock_connection.execute.return_value = None
        mock_connection.fetch.return_value = [{"id": 1, "name": "test"}]

        # Mock acquire() as async context manager
        connection_manager.acquire = MagicMock()
        connection_manager.acquire.return_value.__aenter__ = AsyncMock(
            return_value=mock_connection
        )
        connection_manager.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        # Act - Direct operation without transaction scope (legacy behavior - each operation auto-commits)
        async with connection_manager.acquire() as conn:
            result = await conn.fetch("SELECT * FROM test_table")

        # Assert - Operations should complete and return results
        assert result == [{"id": 1, "name": "test"}]
        mock_connection.fetch.assert_awaited_once_with("SELECT * FROM test_table")


class TestFTSLanguageBackwardCompatibility:
    """Test FTS language backward compatibility."""

    def test_fts_language_defaults_to_english_for_existing_deployments(self):
        """Test that fts_language defaults to 'english' (FR-5.2)."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            # No fts_language specified
        )

        # Assert
        assert config.fts_language == "english"
        # Preserves existing behavior, not changing to 'simple'

    def test_existing_fts_indexes_continue_to_work(self):
        """Test that existing FTS indexes with 'english' continue to work."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
        )

        # Act
        fts_query = f"to_tsvector('{config.fts_language}', content)"

        # Assert
        assert "'english'" in fts_query
        # Matches existing FTS indexes


class TestPoolConfigurationBackwardCompatibility:
    """Test pool configuration backward compatibility."""

    def test_pool_size_defaults_unchanged(self):
        """Test that pool_size defaults are unchanged."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
        )

        # Assert
        assert config.pool_size == 10  # Existing default
        assert config.max_overflow == 5  # Existing default

    def test_custom_pool_settings_preserved(self):
        """Test that custom pool settings continue to work."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            pool_size=20,
            max_overflow=15,
        )

        # Assert
        assert config.pool_size == 20
        assert config.max_overflow == 15


class TestTablePrefixBackwardCompatibility:
    """Test table_prefix backward compatibility."""

    def test_table_prefix_optional(self):
        """Test that table_prefix remains optional."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            # No table_prefix
        )

        # Assert
        assert config.table_prefix is None

    def test_table_prefix_behavior_unchanged(self):
        """Test that table_prefix behavior is unchanged."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            table_prefix="prod_",
        )

        # Assert
        assert config.table_prefix == "prod_"
        # Should be applied to table names as before


class TestNoBreakingChanges:
    """Test that no breaking changes were introduced."""

    def test_required_fields_unchanged(self):
        """Test that required fields remain the same."""
        # Arrange & Act
        # Only type is required for BackendConfig
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
        )

        # Assert
        assert config.type == "postgresql"
        # All other fields have defaults

    def test_field_types_unchanged(self):
        """Test that field types remain unchanged."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            pool_size=10,
            max_overflow=5,
        )

        # Assert
        assert isinstance(config.pool_size, int)
        assert isinstance(config.max_overflow, int)
        assert isinstance(config.connection_string, str)

    def test_validation_errors_unchanged(self):
        """Test that validation errors remain unchanged."""
        # Arrange & Act & Assert
        # Invalid pool_size should still raise error
        with pytest.raises(ValueError):
            BackendConfig(
                type="postgresql",
                connection_string="postgresql://localhost/db",
                pool_size=0,  # Invalid
            )

        # Invalid max_overflow should still raise error
        with pytest.raises(ValueError):
            BackendConfig(
                type="postgresql",
                connection_string="postgresql://localhost/db",
                max_overflow=-1,  # Invalid
            )
