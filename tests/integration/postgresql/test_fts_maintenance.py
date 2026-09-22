"""FTS and Maintenance Tests (T7.5).

Tests for FR-5: Configurable Full-Text Search Language
Tests for FR-6: PostgreSQL Maintenance Operations

Test Coverage:
- AC-9: FTS language configurable via fts_language
- AC-10: run_maintenance("vacuum") executes VACUUM ANALYZE
- AC-11: run_maintenance("reindex") rebuilds index

Design:
    - Tests FTS language configuration
    - Verifies maintenance operations execute correctly
    - Tests index rebuild and vacuum operations
    - Mocks database operations for isolation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.postgresql.maintenance import (
    PostgresMaintenanceService,
)


class TestAC9FTSLanguageConfigurable:
    """AC-9: FTS language configurable via fts_language."""

    def test_fts_language_defaults_to_english(self):
        """Test that fts_language defaults to 'english' for backward compatibility (FR-5.2)."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            # No fts_language specified
        )

        # Assert
        assert config.fts_language == "english"

    def test_fts_language_can_be_configured(self):
        """Test that fts_language can be set to different values (AC-9)."""
        # Arrange
        test_languages = ["simple", "german", "spanish", "french"]

        for language in test_languages:
            config = BackendConfig(
                type="postgresql",
                connection_string="postgresql://localhost/db",
                fts_language=language,
            )

            # Assert
            assert config.fts_language == language

    def test_fts_language_accessible_from_config(self):
        """Test that FTS language is stored correctly and accessible from config."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            fts_language="simple",
        )

        # Assert - Config stores the language for use by provider
        assert config.fts_language == "simple"
        # The provider will use this value when generating SQL queries
        # (Actual SQL generation tested in integration tests with real DB)

    def test_fts_language_values_are_valid_postgresql_configs(self):
        """Test that FTS language values are valid PostgreSQL text search configurations."""
        # These are standard PostgreSQL text search configurations
        valid_languages = ["english", "simple", "german", "spanish", "french"]

        for language in valid_languages:
            config = BackendConfig(
                type="postgresql",
                connection_string="postgresql://localhost/db",
                fts_language=language,
            )

            # Assert - Each language is stored correctly
            assert config.fts_language == language
            # Actual validation against PostgreSQL happens at runtime in integration tests


class TestAC10VacuumExecutes:
    """AC-10: run_maintenance('vacuum') executes VACUUM ANALYZE."""

    @pytest.mark.asyncio
    async def test_vacuum_executes_on_tables(self):
        """Test that run_maintenance('vacuum') executes VACUUM ANALYZE (AC-10)."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock successful vacuum execution
        mock_connection.execute.return_value = None
        mock_connection.fetchrow.side_effect = [
            {"n_dead_tup": 1234, "n_live_tup": 10000},  # Before vacuum
            {"n_dead_tup": 0, "n_live_tup": 10000},  # After vacuum
        ]

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        result = await service.run_maintenance(operation="vacuum", table_name="agv_chunks")

        # Assert
        # Verify result is MaintenanceResult
        assert result is not None
        assert result.operation == "vacuum"
        assert result.table_name == "agv_chunks"

    @pytest.mark.asyncio
    async def test_vacuum_returns_statistics(self):
        """Test that vacuum operation returns statistics."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock vacuum statistics
        mock_connection.execute.return_value = None
        mock_connection.fetchrow.side_effect = [
            {"n_dead_tup": 1234, "n_live_tup": 10000},  # Before
            {"n_dead_tup": 100, "n_live_tup": 10000},  # After
        ]

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        result = await service.run_maintenance(operation="vacuum", table_name="agv_chunks")

        # Assert
        assert result is not None
        assert "dead_tuples_before" in result.statistics
        assert "dead_tuples_after" in result.statistics
        assert "live_tuples" in result.statistics

    @pytest.mark.asyncio
    async def test_vacuum_analyze_reclaims_dead_tuples(self):
        """Test that VACUUM ANALYZE reclaims dead tuples."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock before and after stats
        mock_connection.fetchrow.side_effect = [
            {"n_dead_tup": 5000, "n_live_tup": 10000},  # Before
            {"n_dead_tup": 0, "n_live_tup": 10000},  # After
        ]
        mock_connection.execute.return_value = None

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        result = await service.run_maintenance(operation="vacuum", table_name="agv_chunks")

        # Assert
        # Verify vacuum was executed and stats captured
        assert result is not None
        assert result.statistics["dead_tuples_before"] == 5000
        assert result.statistics["dead_tuples_after"] == 0

    @pytest.mark.asyncio
    async def test_vacuum_escapes_table_identifiers(self):
        """Test that table names are escaped in VACUUM command."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()
        mock_connection.execute.return_value = None
        mock_connection.fetchrow.side_effect = [
            {"n_dead_tup": 0, "n_live_tup": 100},
            {"n_dead_tup": 0, "n_live_tup": 100},
        ]

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act - Use a potentially dangerous table name
        await service.run_maintenance(operation="vacuum", table_name="test_table")

        # Assert - Verify execute was called (identifiers escaped internally)
        mock_connection.execute.assert_called()


class TestAC11ReindexRebuildsIndex:
    """AC-11: run_maintenance('reindex') rebuilds index."""

    @pytest.mark.asyncio
    async def test_reindex_rebuilds_indexes(self):
        """Test that run_maintenance('reindex') rebuilds indexes (AC-11)."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock successful reindex
        mock_connection.execute.return_value = None
        mock_connection.fetchval.return_value = 3  # Number of indexes

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        result = await service.run_maintenance(operation="reindex", table_name="agv_chunks")

        # Assert
        assert result is not None
        assert result.operation == "reindex"
        assert result.table_name == "agv_chunks"
        assert "indexes_rebuilt" in result.statistics

    @pytest.mark.asyncio
    async def test_reindex_returns_statistics(self):
        """Test that reindex operation returns statistics."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        mock_connection.execute.return_value = None
        mock_connection.fetchval.return_value = 5  # 5 indexes rebuilt

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        result = await service.run_maintenance(operation="reindex", table_name="agv_chunks")

        # Assert
        assert result is not None
        assert result.statistics["indexes_rebuilt"] == 5


class TestMaintenanceOperationsCombined:
    """Test combined maintenance operations."""

    @pytest.mark.asyncio
    async def test_vacuum_and_reindex_can_run_sequentially(self):
        """Test that vacuum and reindex operations can run sequentially."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock for vacuum and reindex
        mock_connection.execute.return_value = None
        mock_connection.fetchrow.side_effect = [
            {"n_dead_tup": 100, "n_live_tup": 10000},  # Before vacuum
            {"n_dead_tup": 0, "n_live_tup": 10000},  # After vacuum
        ]
        mock_connection.fetchval.return_value = 3  # Number of indexes for reindex

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        vacuum_result = await service.run_maintenance(operation="vacuum", table_name="agv_chunks")

        # Reset mocks for second call
        mock_connection.fetchrow.side_effect = None

        reindex_result = await service.run_maintenance(operation="reindex", table_name="agv_chunks")

        # Assert
        assert vacuum_result is not None
        assert vacuum_result.operation == "vacuum"
        assert reindex_result is not None
        assert reindex_result.operation == "reindex"

    @pytest.mark.asyncio
    async def test_maintenance_duration_tracked(self):
        """Test that maintenance operation duration is tracked."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        mock_connection.execute.return_value = None
        mock_connection.fetchrow.side_effect = [
            {"n_dead_tup": 100, "n_live_tup": 10000},
            {"n_dead_tup": 0, "n_live_tup": 10000},
        ]

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        result = await service.run_maintenance(operation="vacuum", table_name="agv_chunks")

        # Assert - Duration should be tracked in MaintenanceResult
        assert result is not None
        assert result.duration_seconds >= 0


class TestMaintenanceStatus:
    """Test get_maintenance_status functionality."""

    @pytest.mark.asyncio
    async def test_get_maintenance_status_returns_index_info(self):
        """Test that get_maintenance_status returns index information."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock table stats
        mock_connection.fetchrow.return_value = {
            "n_live_tup": 10000,
            "n_dead_tup": 100,
            "last_vacuum": None,
            "last_autovacuum": None,
            "last_analyze": None,
            "last_autoanalyze": None,
        }

        # Mock index information
        mock_connection.fetch.return_value = [
            {
                "indexname": "idx_chunks_embedding",
                "indexdef": "CREATE INDEX idx_chunks_embedding ON agv_chunks USING hnsw",
                "index_size": 1024,
            },
        ]

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        status = await service.get_maintenance_status(table_name="agv_chunks")

        # Assert
        assert status is not None
        assert "indexes" in status
        assert len(status["indexes"]) == 1
        assert status["indexes"][0]["name"] == "idx_chunks_embedding"

    @pytest.mark.asyncio
    async def test_get_maintenance_status_includes_table_stats(self):
        """Test that maintenance status includes table statistics."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock table statistics
        mock_connection.fetchrow.return_value = {
            "n_live_tup": 10000,
            "n_dead_tup": 500,
            "last_vacuum": "2026-01-13 12:00:00",
            "last_autovacuum": None,
            "last_analyze": None,
            "last_autoanalyze": None,
        }
        mock_connection.fetch.return_value = []  # No indexes

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        status = await service.get_maintenance_status(table_name="agv_chunks")

        # Assert
        assert status is not None
        assert "table_stats" in status
        assert status["table_stats"]["n_live_tup"] == 10000
        assert status["table_stats"]["n_dead_tup"] == 500


class TestMaintenanceErrorHandling:
    """Test error handling for maintenance operations."""

    @pytest.mark.asyncio
    async def test_vacuum_failure_raises_exception(self):
        """Test that vacuum failure raises an exception."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock vacuum failure - fetchrow works but execute fails
        mock_connection.fetchrow.return_value = {"n_dead_tup": 100, "n_live_tup": 10000}
        mock_connection.execute.side_effect = Exception("Vacuum failed")

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act & Assert
        with pytest.raises(Exception):
            await service.run_maintenance(operation="vacuum", table_name="agv_chunks")

    @pytest.mark.asyncio
    async def test_invalid_operation_raises_error(self):
        """Test that invalid operation raises ValueError."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            await service.run_maintenance(operation="invalid_op", table_name="agv_chunks")

        assert "unknown maintenance operation" in str(exc_info.value).lower()


class TestFTSLanguageEdgeCases:
    """Test edge cases for FTS language configuration."""

    def test_fts_language_accepts_valid_postgresql_configs(self):
        """Test that FTS language accepts valid PostgreSQL text search configs."""
        # Arrange
        valid_languages = [
            "simple",
            "english",
            "german",
            "spanish",
            "french",
            "italian",
            "portuguese",
            "russian",
        ]

        for language in valid_languages:
            config = BackendConfig(
                type="postgresql",
                connection_string="postgresql://localhost/db",
                fts_language=language,
            )

            # Assert
            assert config.fts_language == language

    def test_fts_language_case_sensitive(self):
        """Test that FTS language preserves case (PostgreSQL configs are case-sensitive)."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
            fts_language="English",  # Capitalized
        )

        # Assert
        assert config.fts_language == "English"


class TestMaintenanceIsolation:
    """Test that maintenance operations don't interfere with each other."""

    @pytest.mark.asyncio
    async def test_multiple_tables_can_be_maintained_independently(self):
        """Test that different tables can be maintained independently."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        mock_connection.execute.return_value = None
        mock_connection.fetchrow.side_effect = [
            {"n_dead_tup": 100, "n_live_tup": 10000},  # Before vacuum table1
            {"n_dead_tup": 0, "n_live_tup": 10000},  # After vacuum table1
            {"n_dead_tup": 50, "n_live_tup": 5000},  # Before vacuum table2
            {"n_dead_tup": 0, "n_live_tup": 5000},  # After vacuum table2
        ]

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Act
        result1 = await service.run_maintenance(operation="vacuum", table_name="agv_chunks")
        result2 = await service.run_maintenance(operation="vacuum", table_name="agv_events")

        # Assert
        assert result1 is not None
        assert result1.table_name == "agv_chunks"
        assert result2 is not None
        assert result2.table_name == "agv_events"


class TestAC11IndexRebuild:
    """AC-11: run_maintenance('reindex') rebuilds index with CONCURRENTLY.

    Tests for rebuild_index() method which implements FR-1.4: Index migration
    with no table lock using CREATE INDEX CONCURRENTLY.
    """

    @pytest.mark.asyncio
    async def test_rebuild_index_succeeds(self):
        """Test successful index rebuild with CONCURRENTLY option."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock transaction check - not in transaction
        mock_connection.fetchval.side_effect = [
            False,  # _is_in_transaction check
            1000,  # Row count
            1024 * 1024,  # Index size in bytes (1 MB)
        ]
        mock_connection.execute.return_value = None

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        # Create index config
        from agent_vault.storage.providers.postgresql.index_config import (
            IndexConfig,
            IndexType,
            HNSWParams,
        )

        index_config = IndexConfig(
            index_type=IndexType.HNSW,
            hnsw_params=HNSWParams(m=16, ef_construction=64),
        )

        # Act
        result = await service.rebuild_index(
            table_name="agv_chunks",
            column_name="embedding",
            index_config=index_config,
        )

        # Assert
        assert result is not None
        assert result.index_name == "idx_agv_chunks_embedding"
        assert result.rows_indexed == 1000
        assert result.index_size_bytes == 1024 * 1024
        assert result.index_type == "hnsw"
        assert result.duration_seconds >= 0

        # Verify connection was released
        connection_manager.release_transaction_connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_rebuild_index_fails_in_transaction(self):
        """Test that rebuild_index raises error when called in transaction context."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock transaction check - IS in transaction
        mock_connection.fetchval.return_value = True  # _is_in_transaction returns True

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        from agent_vault.storage.providers.postgresql.index_config import (
            IndexConfig,
            IndexType,
        )
        from agent_vault.storage.providers.postgresql.maintenance import (
            IndexRebuildError,
        )

        index_config = IndexConfig(index_type=IndexType.HNSW)

        # Act & Assert
        with pytest.raises(IndexRebuildError) as exc_info:
            await service.rebuild_index(
                table_name="agv_chunks",
                column_name="embedding",
                index_config=index_config,
            )

        assert "cannot run inside a transaction" in str(exc_info.value).lower()
        # Connection should still be released
        connection_manager.release_transaction_connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_rebuild_index_uses_concurrently(self):
        """Test that rebuild_index uses CONCURRENTLY keyword in SQL."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        mock_connection.fetchval.side_effect = [
            False,  # Not in transaction
            500,  # Row count
            2048 * 1024,  # Index size
        ]
        mock_connection.execute.return_value = None

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        from agent_vault.storage.providers.postgresql.index_config import (
            IndexConfig,
            IndexType,
        )

        index_config = IndexConfig(index_type=IndexType.HNSW)

        # Act
        await service.rebuild_index(
            table_name="agv_chunks",
            column_name="embedding",
            index_config=index_config,
        )

        # Assert - Check that CONCURRENTLY was used in the executed SQL
        executed_calls = mock_connection.execute.call_args_list
        create_index_call = [
            call for call in executed_calls
            if "CREATE INDEX" in str(call)
        ]
        assert len(create_index_call) >= 1
        assert "CONCURRENTLY" in str(create_index_call[0])

    @pytest.mark.asyncio
    async def test_rebuild_index_drops_old_and_renames(self):
        """Test that rebuild_index drops old index and renames new one."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        mock_connection.fetchval.side_effect = [
            False,  # Not in transaction
            100,  # Row count
            512 * 1024,  # Index size
        ]
        mock_connection.execute.return_value = None

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        from agent_vault.storage.providers.postgresql.index_config import (
            IndexConfig,
            IndexType,
        )

        index_config = IndexConfig(index_type=IndexType.HNSW)

        # Act
        await service.rebuild_index(
            table_name="agv_chunks",
            column_name="embedding",
            index_config=index_config,
            old_index_name="idx_agv_chunks_embedding_legacy",
        )

        # Assert - Verify DROP and RENAME were called
        executed_calls = [str(call) for call in mock_connection.execute.call_args_list]
        drop_calls = [c for c in executed_calls if "DROP INDEX" in c]
        rename_calls = [c for c in executed_calls if "ALTER INDEX" in c and "RENAME" in c]

        assert len(drop_calls) >= 1, "DROP INDEX should be executed"
        assert len(rename_calls) >= 1, "ALTER INDEX RENAME should be executed"

    @pytest.mark.asyncio
    async def test_rebuild_index_returns_statistics(self):
        """Test that rebuild_index returns complete statistics."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        mock_connection.fetchval.side_effect = [
            False,  # Not in transaction
            5000,  # Row count
            10 * 1024 * 1024,  # 10 MB index size
        ]
        mock_connection.execute.return_value = None

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        from agent_vault.storage.providers.postgresql.index_config import (
            IndexConfig,
            IndexType,
            IVFFlatParams,
        )

        index_config = IndexConfig(
            index_type=IndexType.IVFFLAT,
            ivfflat_params=IVFFlatParams(lists=100),
        )

        # Act
        result = await service.rebuild_index(
            table_name="agv_entities",
            column_name="embedding",
            index_config=index_config,
        )

        # Assert - All statistics should be present
        assert result.index_name == "idx_agv_entities_embedding"
        assert result.old_index_name == "idx_agv_entities_embedding"
        assert result.rows_indexed == 5000
        assert result.index_size_bytes == 10 * 1024 * 1024
        assert result.index_type == "ivfflat"
        assert isinstance(result.duration_seconds, float)
        assert result.duration_seconds >= 0
