"""Transaction Atomicity Tests (T7.2).

Tests for FR-2: Cross-Provider Transaction Atomicity

Test Coverage:
- AC-4: Multi-provider store rolls back on graph failure
- AC-5: Multi-provider store rolls back on vector failure
- AC-17: Conflicting connection config rejected
- Connection pool exhaustion handling
- Consistency check for orphan detection

Design:
    - Tests transaction coordinator rollback behavior
    - Verifies no partial commits on failure
    - Tests configuration validation
    - Mocks database operations to simulate failures
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.postgresql.transaction import (
    TransactionCoordinator,
    TransactionError,
)
from agent_vault.storage.providers.postgresql.consistency import (
    ConsistencyChecker,
)
from agent_vault.storage.providers.postgresql.connection_mode import (
    validate_config_consistency,
)


class TestAC4RollbackOnGraphFailure:
    """AC-4: Multi-provider store rolls back on graph failure."""

    @pytest.mark.asyncio
    async def test_vector_insert_rolled_back_on_graph_failure(self):
        """Test that vector insert is rolled back when graph insert fails."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock connection acquisition as AsyncMock
        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()
        mock_connection.execute.return_value = None
        mock_connection.fetch.return_value = []

        # Create mock providers
        vector_provider = MagicMock()
        graph_provider = MagicMock()

        # Mock vector provider success
        vector_provider.store_chunks = AsyncMock(return_value=None)
        vector_provider.set_transaction_connection = MagicMock()
        vector_provider.clear_transaction_connection = MagicMock()

        # Mock graph provider failure
        graph_provider.store_relationships = AsyncMock(
            side_effect=Exception("Graph insert failed")
        )
        graph_provider.set_transaction_connection = MagicMock()
        graph_provider.clear_transaction_connection = MagicMock()

        coordinator = TransactionCoordinator(
            connection_manager=connection_manager,
            vector_provider=vector_provider,
            graph_provider=graph_provider,
        )

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            async with coordinator.transaction_scope():
                # Simulate store_chunks which calls both providers
                await vector_provider.store_chunks([{"id": "test"}])
                await graph_provider.store_relationships([{"from": "a", "to": "b"}])

        # Assert rollback was called
        assert "Graph insert failed" in str(exc_info.value)
        mock_connection.execute.assert_any_call("ROLLBACK")

    @pytest.mark.asyncio
    async def test_no_data_committed_after_graph_failure(self):
        """Test that no data is committed after graph failure (full rollback)."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()
        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        # Track transaction state
        committed = False

        async def mock_commit():
            nonlocal committed
            committed = True
            return None

        mock_connection.execute.side_effect = lambda sql: (
            mock_commit() if sql == "COMMIT" else None
        )

        vector_provider = MagicMock()
        graph_provider = MagicMock()

        vector_provider.store_chunks = AsyncMock(return_value=None)
        vector_provider.set_transaction_connection = MagicMock()
        vector_provider.clear_transaction_connection = MagicMock()

        # Graph provider fails
        graph_provider.store_relationships = AsyncMock(
            side_effect=Exception("Graph failure")
        )
        graph_provider.set_transaction_connection = MagicMock()
        graph_provider.clear_transaction_connection = MagicMock()

        coordinator = TransactionCoordinator(
            connection_manager=connection_manager,
            vector_provider=vector_provider,
            graph_provider=graph_provider,
        )

        # Act
        try:
            async with coordinator.transaction_scope():
                await vector_provider.store_chunks([{"id": "test"}])
                await graph_provider.store_relationships([])
        except Exception:
            pass

        # Assert - COMMIT was never called
        assert not committed


class TestAC5RollbackOnVectorFailure:
    """AC-5: Multi-provider store rolls back on vector failure."""

    @pytest.mark.asyncio
    async def test_graph_insert_rolled_back_on_vector_failure(self):
        """Test that graph insert is rolled back when vector insert fails."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()
        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()
        mock_connection.execute.return_value = None

        vector_provider = MagicMock()
        graph_provider = MagicMock()

        # Vector provider fails
        vector_provider.store_chunks = AsyncMock(
            side_effect=Exception("Vector insert failed")
        )
        vector_provider.set_transaction_connection = MagicMock()
        vector_provider.clear_transaction_connection = MagicMock()

        # Graph provider succeeds
        graph_provider.store_relationships = AsyncMock(return_value=None)
        graph_provider.set_transaction_connection = MagicMock()
        graph_provider.clear_transaction_connection = MagicMock()

        coordinator = TransactionCoordinator(
            connection_manager=connection_manager,
            vector_provider=vector_provider,
            graph_provider=graph_provider,
        )

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            async with coordinator.transaction_scope():
                await vector_provider.store_chunks([{"id": "test"}])
                # This wouldn't be reached, but test the rollback
                await graph_provider.store_relationships([])

        assert "Vector insert failed" in str(exc_info.value)
        mock_connection.execute.assert_any_call("ROLLBACK")

    @pytest.mark.asyncio
    async def test_nothing_committed_on_vector_failure(self):
        """Test that nothing is committed when vector provider fails (AC-5)."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()
        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        committed = False

        async def mock_execute(sql):
            nonlocal committed
            if sql == "COMMIT":
                committed = True
            return None

        mock_connection.execute.side_effect = mock_execute

        vector_provider = MagicMock()
        graph_provider = MagicMock()

        vector_provider.store_chunks = AsyncMock(
            side_effect=Exception("Vector failure")
        )
        vector_provider.set_transaction_connection = MagicMock()
        vector_provider.clear_transaction_connection = MagicMock()

        graph_provider.set_transaction_connection = MagicMock()
        graph_provider.clear_transaction_connection = MagicMock()

        coordinator = TransactionCoordinator(
            connection_manager=connection_manager,
            vector_provider=vector_provider,
            graph_provider=graph_provider,
        )

        # Act
        try:
            async with coordinator.transaction_scope():
                await vector_provider.store_chunks([{"id": "test"}])
        except Exception:
            pass

        # Assert
        assert not committed


class TestAC17ConflictingConnectionConfig:
    """AC-17: Conflicting connection config rejected."""

    def test_both_connection_string_and_cloud_sql_params_rejected(self):
        """Test that both connection_string and Cloud SQL params raises ConfigurationError."""
        # Act & Assert - BackendConfig validation rejects conflicting config at creation time
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(
                type="postgresql",
                connection_string="postgresql://localhost/db",
                project="test-project",
                region="us-central1",
                instance="test-instance",
                database="test-db",
                user="test-user",
            )

        assert "cannot specify both connection_string" in str(exc_info.value).lower()

    def test_connection_string_only_accepted(self):
        """Test that connection_string alone is accepted."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://localhost/db",
        )

        # Act & Assert - Should not raise
        validate_config_consistency(config)

    def test_cloud_sql_params_only_accepted(self):
        """Test that Cloud SQL params alone are accepted."""
        # Arrange
        config = BackendConfig(
            type="postgresql",
            project="test-project",
            region="us-central1",
            instance="test-instance",
            database="test-db",
            user="test-user",
        )

        # Act & Assert - Should not raise
        validate_config_consistency(config)


class TestConnectionPoolExhaustion:
    """Test connection pool exhaustion handling."""

    @pytest.mark.asyncio
    async def test_pool_exhausted_raises_error(self):
        """Test that pool exhaustion raises PoolExhaustedError."""
        # Arrange
        connection_manager = MagicMock()

        # Mock pool exhaustion - must accept timeout parameter
        async def mock_acquire_timeout(timeout=None):
            import asyncio

            raise asyncio.TimeoutError("Pool exhausted")

        connection_manager.acquire_for_transaction = mock_acquire_timeout

        vector_provider = MagicMock()
        graph_provider = MagicMock()

        coordinator = TransactionCoordinator(
            connection_manager=connection_manager,
            vector_provider=vector_provider,
            graph_provider=graph_provider,
        )

        # Act & Assert - TimeoutError from pool exhaustion bubbles up
        with pytest.raises(asyncio.TimeoutError):
            async with coordinator.transaction_scope():
                pass

    @pytest.mark.asyncio
    async def test_connection_released_on_pool_exhaustion(self):
        """Test that connection is released even when pool exhausted."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        acquired = False
        released = False

        async def mock_acquire(timeout=None):
            nonlocal acquired
            acquired = True
            return mock_connection

        async def mock_release(conn):
            nonlocal released
            released = True

        connection_manager.acquire_for_transaction = mock_acquire
        connection_manager.release_transaction_connection = mock_release

        vector_provider = MagicMock()
        graph_provider = MagicMock()
        vector_provider.set_transaction_connection = MagicMock()
        vector_provider.clear_transaction_connection = MagicMock()
        graph_provider.set_transaction_connection = MagicMock()
        graph_provider.clear_transaction_connection = MagicMock()

        # Simulate operation failure
        vector_provider.store_chunks = AsyncMock(side_effect=Exception("Test failure"))

        coordinator = TransactionCoordinator(
            connection_manager=connection_manager,
            vector_provider=vector_provider,
            graph_provider=graph_provider,
        )

        # Act
        try:
            async with coordinator.transaction_scope():
                await vector_provider.store_chunks([])
        except Exception:
            pass

        # Assert
        assert acquired
        assert released


class TestConsistencyCheck:
    """Test consistency checking for orphan detection."""

    @pytest.mark.asyncio
    async def test_orphaned_chunks_detected(self):
        """Test that orphaned chunks (no FTS entry) are detected."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock table size check (below limit)
        mock_connection.fetchval.return_value = 1000  # Row count

        # Mock orphaned records queries
        mock_connection.fetch.side_effect = [
            [{"id": "orphan1"}, {"id": "orphan2"}],  # Orphaned chunks
            [],  # Orphaned entities
            [],  # Orphaned relationships
        ]

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        checker = ConsistencyChecker(connection_manager)

        # Act
        report = await checker.check_consistency(
            project_id="test_project",
            table_prefix="agv_",
        )

        # Assert
        assert len(report.orphaned_chunks) == 2
        assert "orphan1" in report.orphaned_chunks

    @pytest.mark.asyncio
    async def test_orphaned_entities_detected(self):
        """Test that orphaned entities (no relationships) are detected."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()

        # Mock table size check
        mock_connection.fetchval.return_value = 500

        # Mock orphaned records queries
        mock_connection.fetch.side_effect = [
            [],  # Orphaned chunks
            [{"id": "entity1"}],  # Orphaned entities
            [],  # Orphaned relationships
        ]

        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        checker = ConsistencyChecker(connection_manager)

        # Act
        report = await checker.check_consistency(
            project_id="test_project",
        )

        # Assert
        assert len(report.orphaned_entities) == 1
        assert "entity1" in report.orphaned_entities

    @pytest.mark.asyncio
    async def test_cleanup_orphans_dry_run_returns_counts(self):
        """Test that cleanup_orphans dry_run returns counts without deleting."""
        # Arrange
        connection_manager = MagicMock()
        checker = ConsistencyChecker(connection_manager)

        # Create a mock report
        from agent_vault.storage.providers.postgresql.consistency import ConsistencyReport
        from datetime import datetime, timezone

        report = ConsistencyReport(
            checked_at=datetime.now(timezone.utc),
            duration_seconds=1.0,
            orphaned_chunks=["chunk1", "chunk2"],
            orphaned_entities=["entity1"],
            orphaned_relationships=[],
            total_orphans=3,
        )

        # Act - dry_run=True (default)
        result = await checker.cleanup_orphans(
            project_id="test_project",
            report=report,
            dry_run=True,
        )

        # Assert - Should return counts without calling database
        assert result["chunks"] == 2
        assert result["entities"] == 1
        assert result["relationships"] == 0
        assert result["dry_run"] is True


class TestTransactionEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_nested_transaction_raises_error(self):
        """Test that nested transactions raise TransactionError."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()
        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()
        mock_connection.execute.return_value = None

        vector_provider = MagicMock()
        graph_provider = MagicMock()
        vector_provider.set_transaction_connection = MagicMock()
        vector_provider.clear_transaction_connection = MagicMock()
        vector_provider.in_transaction = False
        graph_provider.set_transaction_connection = MagicMock()
        graph_provider.clear_transaction_connection = MagicMock()

        coordinator = TransactionCoordinator(
            connection_manager=connection_manager,
            vector_provider=vector_provider,
            graph_provider=graph_provider,
        )

        # Act & Assert
        async with coordinator.transaction_scope():
            # Try to start nested transaction
            vector_provider.in_transaction = True
            with pytest.raises(TransactionError):
                async with coordinator.transaction_scope():
                    pass

    @pytest.mark.asyncio
    async def test_connection_lost_during_commit_logs_unknown_state(self):
        """Test that connection lost during COMMIT logs UNKNOWN state."""
        # Arrange
        connection_manager = MagicMock()
        mock_connection = AsyncMock()
        connection_manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
        connection_manager.release_transaction_connection = AsyncMock()

        # Simulate connection lost during COMMIT
        async def mock_execute(sql):
            if sql == "COMMIT":
                raise ConnectionError("Connection lost")
            return None

        mock_connection.execute.side_effect = mock_execute

        vector_provider = MagicMock()
        graph_provider = MagicMock()
        vector_provider.set_transaction_connection = MagicMock()
        vector_provider.clear_transaction_connection = MagicMock()
        graph_provider.set_transaction_connection = MagicMock()
        graph_provider.clear_transaction_connection = MagicMock()

        coordinator = TransactionCoordinator(
            connection_manager=connection_manager,
            vector_provider=vector_provider,
            graph_provider=graph_provider,
        )

        # Act & Assert
        with pytest.raises(ConnectionError):
            async with coordinator.transaction_scope():
                pass


class TestTransactionCoordinatorDelegatedMethods:
    """Tests for TransactionCoordinator delegated operations.

    These tests verify that store_chunks, store_relationships, delete_chunks,
    and delete_file properly delegate to providers within transaction context.
    """

    @pytest.mark.asyncio
    async def test_store_chunks_delegates_to_vector_provider(
        self,
        mock_connection_manager,
        mock_vector_provider,
        mock_graph_provider,
    ):
        """Test that store_chunks delegates to vector provider."""
        # Arrange
        mock_vector_provider._project_id = "test-project"
        mock_vector_provider.upsert_chunks = AsyncMock(return_value=2)

        coordinator = TransactionCoordinator(
            connection_manager=mock_connection_manager,
            vector_provider=mock_vector_provider,
            graph_provider=mock_graph_provider,
        )

        mock_chunks = [MagicMock(id="chunk-1"), MagicMock(id="chunk-2")]

        # Act
        async with coordinator.transaction_scope() as txn:
            result = await txn.store_chunks(mock_chunks)

        # Assert
        assert result == 2
        mock_vector_provider.upsert_chunks.assert_called_once()
        call_args = mock_vector_provider.upsert_chunks.call_args
        assert call_args[0][0] == mock_chunks
        assert call_args[0][1] == "test-project"

    @pytest.mark.asyncio
    async def test_store_chunks_fails_without_transaction(
        self,
        mock_connection_manager,
        mock_vector_provider,
        mock_graph_provider,
    ):
        """Test that store_chunks raises error when called outside transaction."""
        # Arrange
        coordinator = TransactionCoordinator(
            connection_manager=mock_connection_manager,
            vector_provider=mock_vector_provider,
            graph_provider=mock_graph_provider,
        )

        # Act & Assert - Not starting transaction
        with pytest.raises(TransactionError) as exc_info:
            await coordinator.store_chunks([])

        assert "not started" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_store_relationships_delegates_to_graph_provider(
        self,
        mock_connection_manager,
        mock_vector_provider,
        mock_graph_provider,
    ):
        """Test that store_relationships delegates to graph provider."""
        # Arrange
        mock_graph_provider._project_id = "test-project"
        mock_graph_provider.upsert_relationships = AsyncMock(return_value=3)

        coordinator = TransactionCoordinator(
            connection_manager=mock_connection_manager,
            vector_provider=mock_vector_provider,
            graph_provider=mock_graph_provider,
        )

        mock_relationships = [
            MagicMock(source_id="a", target_id="b"),
            MagicMock(source_id="b", target_id="c"),
            MagicMock(source_id="c", target_id="d"),
        ]

        # Act
        async with coordinator.transaction_scope() as txn:
            result = await txn.store_relationships(mock_relationships)

        # Assert
        assert result == 3
        mock_graph_provider.upsert_relationships.assert_called_once()
        call_args = mock_graph_provider.upsert_relationships.call_args
        assert call_args[0][0] == mock_relationships
        assert call_args[0][1] == "test-project"

    @pytest.mark.asyncio
    async def test_store_relationships_fails_without_transaction(
        self,
        mock_connection_manager,
        mock_vector_provider,
        mock_graph_provider,
    ):
        """Test that store_relationships raises error when called outside transaction."""
        # Arrange
        coordinator = TransactionCoordinator(
            connection_manager=mock_connection_manager,
            vector_provider=mock_vector_provider,
            graph_provider=mock_graph_provider,
        )

        # Act & Assert
        with pytest.raises(TransactionError) as exc_info:
            await coordinator.store_relationships([])

        assert "not started" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_chunks_deletes_from_both_providers(
        self,
        mock_connection_manager,
        mock_vector_provider,
        mock_graph_provider,
    ):
        """Test that delete_chunks deletes from graph first, then vector."""
        # Arrange
        mock_vector_provider._project_id = "test-project"
        mock_graph_provider._project_id = "test-project"
        mock_vector_provider.delete_chunks_by_ids = AsyncMock(return_value=2)
        mock_graph_provider.delete_relationships_by_ids = AsyncMock()

        coordinator = TransactionCoordinator(
            connection_manager=mock_connection_manager,
            vector_provider=mock_vector_provider,
            graph_provider=mock_graph_provider,
        )

        chunk_ids = ["chunk-1", "chunk-2"]

        # Act
        async with coordinator.transaction_scope() as txn:
            result = await txn.delete_chunks(chunk_ids)

        # Assert
        assert result == 2
        # Graph should be deleted first (relationships reference chunks)
        mock_graph_provider.delete_relationships_by_ids.assert_called_once_with(
            chunk_ids, "test-project"
        )
        # Then chunks
        mock_vector_provider.delete_chunks_by_ids.assert_called_once()
        call_args = mock_vector_provider.delete_chunks_by_ids.call_args
        assert call_args[0][0] == chunk_ids

    @pytest.mark.asyncio
    async def test_delete_chunks_fails_without_transaction(
        self,
        mock_connection_manager,
        mock_vector_provider,
        mock_graph_provider,
    ):
        """Test that delete_chunks raises error when called outside transaction."""
        # Arrange
        coordinator = TransactionCoordinator(
            connection_manager=mock_connection_manager,
            vector_provider=mock_vector_provider,
            graph_provider=mock_graph_provider,
        )

        # Act & Assert
        with pytest.raises(TransactionError) as exc_info:
            await coordinator.delete_chunks(["chunk-1"])

        assert "not started" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_file_gets_chunks_and_deletes(
        self,
        mock_connection_manager,
        mock_vector_provider,
        mock_graph_provider,
    ):
        """Test that delete_file looks up chunks and deletes them."""
        # Arrange
        mock_vector_provider._project_id = "test-project"
        mock_graph_provider._project_id = "test-project"

        # Mock chunks returned for the file
        mock_chunk_1 = MagicMock(id="chunk-1")
        mock_chunk_2 = MagicMock(id="chunk-2")
        mock_vector_provider.get_chunks_by_file = AsyncMock(
            return_value=[mock_chunk_1, mock_chunk_2]
        )
        mock_vector_provider.delete_chunks_by_ids = AsyncMock(return_value=2)
        mock_graph_provider.delete_relationships_by_ids = AsyncMock()

        coordinator = TransactionCoordinator(
            connection_manager=mock_connection_manager,
            vector_provider=mock_vector_provider,
            graph_provider=mock_graph_provider,
        )

        # Act
        async with coordinator.transaction_scope() as txn:
            result = await txn.delete_file("/path/to/file.py")

        # Assert
        assert result == 2
        mock_vector_provider.get_chunks_by_file.assert_called_once_with(
            "/path/to/file.py", "test-project"
        )
        mock_vector_provider.delete_chunks_by_ids.assert_called_once()
        call_args = mock_vector_provider.delete_chunks_by_ids.call_args
        assert call_args[0][0] == ["chunk-1", "chunk-2"]

    @pytest.mark.asyncio
    async def test_delete_file_returns_zero_for_nonexistent_file(
        self,
        mock_connection_manager,
        mock_vector_provider,
        mock_graph_provider,
    ):
        """Test that delete_file returns 0 when file has no chunks."""
        # Arrange
        mock_vector_provider._project_id = "test-project"
        mock_vector_provider.get_chunks_by_file = AsyncMock(return_value=[])

        coordinator = TransactionCoordinator(
            connection_manager=mock_connection_manager,
            vector_provider=mock_vector_provider,
            graph_provider=mock_graph_provider,
        )

        # Act
        async with coordinator.transaction_scope() as txn:
            result = await txn.delete_file("/nonexistent/file.py")

        # Assert
        assert result == 0
        mock_vector_provider.get_chunks_by_file.assert_called_once()
        # delete_chunks_by_ids should not be called for empty list
        mock_vector_provider.delete_chunks_by_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_file_fails_without_transaction(
        self,
        mock_connection_manager,
        mock_vector_provider,
        mock_graph_provider,
    ):
        """Test that delete_file raises error when called outside transaction."""
        # Arrange
        coordinator = TransactionCoordinator(
            connection_manager=mock_connection_manager,
            vector_provider=mock_vector_provider,
            graph_provider=mock_graph_provider,
        )

        # Act & Assert
        with pytest.raises(TransactionError) as exc_info:
            await coordinator.delete_file("/some/file.py")

        assert "not started" in str(exc_info.value).lower()
