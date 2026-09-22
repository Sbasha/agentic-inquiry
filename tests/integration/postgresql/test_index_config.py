"""Index Configuration Tests (T7.1).

Tests for FR-1: Configurable Vector Index Strategy

Test Coverage:
- AC-1: HNSW index can be selected via index_type="hnsw"
- AC-2: ivfflat lists parameter calculated from row count
- AC-3: ivfflat lists parameter can be explicitly overridden
- AC-15: rebuild_index fails inside transaction
- AC-16: ivfflat lists capped at 10000

Design:
    - Uses pytest-asyncio for async test support
    - Mocks database connections to avoid real DB dependency
    - Tests formula validation and SQL generation
    - Verifies SQL injection prevention
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.postgresql.index_config import (
    IndexConfigStrategy,
    IndexType,
    IndexConfig,
    IVFFlatParams,
    HNSWParams,
    ConfigurationError,
)
from agent_vault.storage.providers.postgresql.maintenance import (
    PostgresMaintenanceService,
    IndexRebuildError,
)
from agent_vault.storage.providers.postgresql.schemas import SchemaGenerator


class TestAC1HNSWIndexSelection:
    """AC-1: HNSW index can be selected via index_type='hnsw'."""

    @pytest.mark.asyncio
    async def test_hnsw_index_created_when_configured(self):
        """Test that HNSW index is created when index_type='hnsw'."""
        # Arrange
        BackendConfig(
            type="postgresql",
            connection_string="postgresql://test",
            index_type="hnsw",
            index_params={"m": 16, "ef_construction": 64},
        )

        schema_gen = SchemaGenerator(
            prefix="test_",
            embedding_dim=768,
        )

        # Act
        index_config = IndexConfig(
            index_type=IndexType.HNSW,
            hnsw_params=HNSWParams(m=16, ef_construction=64),
        )
        sql = schema_gen.generate_vector_index(
            table_name="test_v_chunks",
            column_name="embedding",
            index_config=index_config,
            row_count=10000,
        )

        # Assert
        assert "USING hnsw" in sql
        assert "m = 16" in sql or "m=16" in sql
        assert "ef_construction = 64" in sql or "ef_construction=64" in sql

    @pytest.mark.asyncio
    async def test_hnsw_is_default_for_new_deployments(self):
        """Test that HNSW is the default index type for new deployments (FR-1.3)."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://test",
            # No index_type specified - should default to "hnsw"
        )

        # Assert
        assert config.index_type == "hnsw"

    @pytest.mark.asyncio
    async def test_no_index_created_when_index_type_none(self):
        """Test that no index is created when index_type='none'."""
        # Arrange
        schema_gen = SchemaGenerator(
            prefix="test_",
            embedding_dim=768,
        )

        index_config = IndexConfig(index_type=IndexType.NONE)

        # Act
        sql = schema_gen.generate_vector_index(
            table_name="test_v_chunks",
            column_name="embedding",
            index_config=index_config,
            row_count=10000,
        )

        # Assert
        assert sql == ""


class TestAC2IVFFlatListsCalculation:
    """AC-2: ivfflat lists parameter calculated from row count."""

    @pytest.mark.parametrize(
        "row_count,expected_lists",
        [
            (1000, 31),  # sqrt(1000) = 31.6... -> floor = 31
            (10000, 100),  # sqrt(10000) = 100
            (100000, 316),  # sqrt(100000) = 316.2... -> floor = 316
            (1000000, 1000),  # sqrt(1000000) = 1000
        ],
    )
    def test_lists_calculation_formula(self, row_count, expected_lists):
        """Test lists calculation using formula: max(1, min(floor(sqrt(n)), 10000))."""
        # Act
        calculated_lists = IndexConfigStrategy.calculate_ivfflat_lists(row_count)

        # Assert
        assert calculated_lists == expected_lists

    @pytest.mark.asyncio
    async def test_lists_calculated_from_table_row_count(self):
        """Test that lists are calculated from actual table row count."""
        # Arrange
        schema_gen = SchemaGenerator(
            prefix="test_",
            embedding_dim=768,
        )

        index_config = IndexConfig(
            index_type=IndexType.IVFFLAT,
            ivfflat_params=IVFFlatParams(),  # No explicit lists
        )

        # Act
        sql = schema_gen.generate_vector_index(
            table_name="test_v_chunks",
            column_name="embedding",
            index_config=index_config,
            row_count=10000,  # Should calculate lists=100
        )

        # Assert
        assert "USING ivfflat" in sql
        assert "lists = 100" in sql or "lists=100" in sql


class TestAC3IVFFlatListsExplicitOverride:
    """AC-3: ivfflat lists parameter can be explicitly overridden."""

    @pytest.mark.asyncio
    async def test_explicit_lists_override_takes_precedence(self):
        """Test that explicit lists parameter overrides calculation."""
        # Arrange
        schema_gen = SchemaGenerator(
            prefix="test_",
            embedding_dim=768,
        )

        index_config = IndexConfig(
            index_type=IndexType.IVFFLAT,
            ivfflat_params=IVFFlatParams(lists=50),  # Explicit override
        )

        # Act
        sql = schema_gen.generate_vector_index(
            table_name="test_v_chunks",
            column_name="embedding",
            index_config=index_config,
            row_count=10000,  # Would calculate 100, but should use 50
        )

        # Assert
        assert "lists = 50" in sql or "lists=50" in sql

    def test_resolve_lists_prefers_explicit_value(self):
        """Test that resolve_ivfflat_lists prefers explicit value."""
        # Arrange
        config = IndexConfig(
            index_type=IndexType.IVFFLAT,
            ivfflat_params=IVFFlatParams(lists=75),
        )

        # Act
        resolved_lists = IndexConfigStrategy.resolve_ivfflat_lists(
            config=config,
            current_row_count=10000,  # Would calculate 100
        )

        # Assert
        assert resolved_lists == 75


class TestAC15RebuildIndexFailsInTransaction:
    """AC-15: rebuild_index fails inside transaction."""

    @pytest.mark.asyncio
    async def test_rebuild_index_raises_error_in_transaction(self):
        """Test that rebuild_index raises IndexRebuildError when called in transaction."""
        # Arrange
        connection_manager = MagicMock()
        service = PostgresMaintenanceService(connection_manager)

        # Mock connection in transaction
        mock_connection = AsyncMock()
        # Mock _is_in_transaction returning True (in transaction)
        mock_connection.fetchval.return_value = True

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        # Create IndexConfig for rebuild_index
        index_config = IndexConfig(
            index_type=IndexType.HNSW,
            hnsw_params=HNSWParams(m=16, ef_construction=64),
        )

        # Act & Assert
        with pytest.raises(IndexRebuildError) as exc_info:
            await service.rebuild_index(
                table_name="test_chunks",
                column_name="embedding",
                index_config=index_config,
            )

        assert "cannot run inside a transaction" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rebuild_index_succeeds_outside_transaction(self):
        """Test that rebuild_index succeeds when called outside transaction."""
        # Arrange
        connection_manager = MagicMock()
        service = PostgresMaintenanceService(connection_manager)

        # Mock connection NOT in transaction
        mock_connection = AsyncMock()
        mock_connection.fetchval.side_effect = [
            False,  # _is_in_transaction returns False
            10000,  # COUNT(*) row count
            8192,  # pg_total_relation_size (index size)
        ]
        mock_connection.execute.return_value = None

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        # Create IndexConfig for rebuild_index
        index_config = IndexConfig(
            index_type=IndexType.HNSW,
            hnsw_params=HNSWParams(m=16, ef_construction=64),
        )

        # Mock SchemaGenerator.generate_vector_index
        with patch('agent_vault.storage.providers.postgresql.schemas.SchemaGenerator') as MockSchemaGen:
            mock_generator = MagicMock()
            mock_generator.generate_vector_index.return_value = 'CREATE INDEX "idx_test_chunks_embedding" ON "test_chunks" USING hnsw ("embedding")'
            MockSchemaGen.return_value = mock_generator

            # Act
            result = await service.rebuild_index(
                table_name="test_chunks",
                column_name="embedding",
                index_config=index_config,
            )

        # Assert
        assert result is not None
        assert result.rows_indexed == 10000


class TestAC16IVFFlatListsCapped:
    """AC-16: ivfflat lists capped at 10000."""

    @pytest.mark.parametrize(
        "row_count,expected_lists",
        [
            (100_000_000, 10000),  # sqrt(100M) = 10000, capped at 10000
            (1_000_000_000, 10000),  # sqrt(1B) = 31622, capped at 10000
            (10_000_000_000, 10000),  # sqrt(10B) = 100000, capped at 10000
        ],
    )
    def test_lists_capped_at_10000(self, row_count, expected_lists):
        """Test that lists are capped at 10000 for very large tables."""
        # Act
        calculated_lists = IndexConfigStrategy.calculate_ivfflat_lists(row_count)

        # Assert
        assert calculated_lists == expected_lists
        assert calculated_lists <= 10000

    def test_validate_lists_raises_error_for_out_of_range(self):
        """Test that validate_ivfflat_lists raises error for out-of-range values."""
        # Act & Assert - Too low
        with pytest.raises(ConfigurationError) as exc_info:
            IndexConfigStrategy.validate_ivfflat_lists(0)
        assert "1, 10000" in str(exc_info.value) or "must be" in str(exc_info.value).lower()

        # Act & Assert - Too high
        with pytest.raises(ConfigurationError) as exc_info:
            IndexConfigStrategy.validate_ivfflat_lists(10001)
        assert "1, 10000" in str(exc_info.value) or "must be" in str(exc_info.value).lower()

    def test_validate_lists_accepts_valid_range(self):
        """Test that validate_ivfflat_lists accepts valid range."""
        # Act & Assert - Should not raise
        IndexConfigStrategy.validate_ivfflat_lists(1)
        IndexConfigStrategy.validate_ivfflat_lists(100)
        IndexConfigStrategy.validate_ivfflat_lists(10000)


class TestSQLInjectionPrevention:
    """Test that all identifiers are properly escaped to prevent SQL injection."""

    @pytest.mark.asyncio
    async def test_table_name_escaped(self):
        """Test that table names are escaped to prevent SQL injection."""
        # Arrange
        schema_gen = SchemaGenerator(
            prefix="test_",
            embedding_dim=768,
        )

        index_config = IndexConfig(index_type=IndexType.HNSW)

        # Act - Use potentially malicious table name
        sql = schema_gen.generate_vector_index(
            table_name="test'; DROP TABLE users--",
            column_name="embedding",
            index_config=index_config,
            row_count=10000,
        )

        # Assert - The malicious string should be inside double quotes (escaped identifier)
        # SQL injection is prevented because the entire identifier is quoted
        # The output should be: ON "test'; DROP TABLE users--"
        assert '"test\'; DROP TABLE users--"' in sql
        # The SQL should NOT have an unquoted semicolon that would terminate the statement
        # (the semicolon is inside the quoted identifier, so it's safe)

    @pytest.mark.asyncio
    async def test_column_name_escaped(self):
        """Test that column names are escaped."""
        # Arrange
        schema_gen = SchemaGenerator(
            prefix="test_",
            embedding_dim=768,
        )

        index_config = IndexConfig(index_type=IndexType.HNSW)

        # Act - Use potentially malicious column name
        sql = schema_gen.generate_vector_index(
            table_name="test_v_chunks",
            column_name="embedding'; DROP TABLE users--",
            index_config=index_config,
            row_count=10000,
        )

        # Assert - The malicious column name should be inside double quotes (escaped identifier)
        # SQL injection is prevented because the entire identifier is quoted
        assert '"embedding\'; DROP TABLE users--"' in sql


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_calculate_lists_with_zero_rows(self):
        """Test lists calculation with zero rows returns minimum (1)."""
        # Act
        lists = IndexConfigStrategy.calculate_ivfflat_lists(0)

        # Assert
        assert lists == 1

    def test_calculate_lists_with_negative_rows_raises_error(self):
        """Test that negative row count raises ConfigurationError."""
        # Act & Assert
        with pytest.raises(ConfigurationError):
            IndexConfigStrategy.calculate_ivfflat_lists(-100)
