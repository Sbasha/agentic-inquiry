"""Tests for PostgreSQL onboard metadata provider.

Uses a mock PostgresConnectionManager since tests don't require a live
PostgreSQL instance. Verifies SQL generation, parameter passing, and
row-to-model conversion.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_vault.onboard.models import OnboardRun
from agent_vault.onboard.providers.postgresql import PostgresOnboardMetadataProvider


class FakeRecord(dict):
    """Mimics asyncpg.Record with dict-like access."""

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return super().__getitem__(key)
        return list(self.values())[key]


def _make_row(
    run_id: str = "",
    project_id: str = "test-project",
    days_ago: int = 0,
    status: str = "completed",
    is_latest: bool = False,
    **kwargs: Any,
) -> FakeRecord:
    """Create a fake database row."""
    ts = datetime.now(timezone.utc)
    return FakeRecord(
        run_id=run_id or str(uuid.uuid4()),
        project_id=project_id,
        timestamp=ts,
        status=status,
        is_latest=is_latest,
        commit_sha=kwargs.get("commit_sha", "abc123"),
        file_count=kwargs.get("file_count", 100),
        chunk_count=kwargs.get("chunk_count", 500),
        entity_count=kwargs.get("entity_count", 200),
        artifact_path=kwargs.get("artifact_path", "/tmp/test"),
        error_message=kwargs.get("error_message"),
        metadata=kwargs.get("metadata", "{}"),
    )


def _make_conn_manager() -> MagicMock:
    """Create a mock PostgresConnectionManager."""
    mgr = MagicMock()
    mgr.table_prefix = "agv_"
    mgr.initialize = AsyncMock()
    mgr.execute = AsyncMock(return_value="INSERT 0 1")
    mgr.fetch = AsyncMock(return_value=[])
    mgr.fetchrow = AsyncMock(return_value=None)
    mgr.fetchval = AsyncMock(return_value=None)
    mgr.close = AsyncMock()

    # Transaction context manager
    txn_conn = AsyncMock()
    txn_conn.fetchrow = AsyncMock()
    txn_conn.execute = AsyncMock()

    class FakeTxnCtx:
        async def __aenter__(self):
            return txn_conn

        async def __aexit__(self, *args):
            pass

    mgr.transaction = MagicMock(return_value=FakeTxnCtx())
    mgr._txn_conn = txn_conn  # exposed for test assertions
    return mgr


@pytest.fixture
def conn_manager() -> MagicMock:
    return _make_conn_manager()


@pytest.fixture
def provider(conn_manager: MagicMock) -> PostgresOnboardMetadataProvider:
    return PostgresOnboardMetadataProvider(conn_manager, project_id="test-project")


class TestPostgresOnboardProvider:
    """Tests for PostgresOnboardMetadataProvider."""

    async def test_initialize_creates_schema(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        await provider.initialize()

        # Should call execute for CREATE TABLE, indexes
        assert conn_manager.initialize.called
        assert conn_manager.execute.call_count >= 3  # table + 2 indexes

        # Verify table name includes prefix
        first_call_sql = conn_manager.execute.call_args_list[0][0][0]
        assert "agv_onboard_runs" in first_call_sql

    async def test_initialize_idempotent(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        await provider.initialize()
        call_count = conn_manager.execute.call_count
        await provider.initialize()
        # Second call should not add more execute calls
        assert conn_manager.execute.call_count == call_count

    async def test_table_name_uses_prefix(self, conn_manager: MagicMock) -> None:
        conn_manager.table_prefix = "myapp_"
        p = PostgresOnboardMetadataProvider(conn_manager, project_id="test")
        assert p._table == "myapp_onboard_runs"

    async def test_create_run(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        run = OnboardRun(
            run_id="run-1",
            project_id="test-project",
            timestamp=datetime.now(timezone.utc),
            status="pending",
            artifact_path="/tmp/test",
        )
        await provider.create_run(run)

        conn_manager.execute.assert_called_once()
        call_args = conn_manager.execute.call_args
        sql = call_args[0][0]
        assert "INSERT INTO agv_onboard_runs" in sql
        # Verify parametrized ($1, $2, ...)
        assert "$1" in sql
        assert "$12" in sql

    async def test_get_run(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        row = _make_row(run_id="run-1")
        conn_manager.fetchrow.return_value = row

        result = await provider.get_run("run-1")

        assert result is not None
        assert result.run_id == "run-1"
        assert result.project_id == "test-project"
        conn_manager.fetchrow.assert_called_once()

    async def test_get_run_not_found(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        conn_manager.fetchrow.return_value = None
        result = await provider.get_run("nonexistent")
        assert result is None

    async def test_get_latest_run(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        row = _make_row(run_id="run-latest", is_latest=True, status="completed")
        conn_manager.fetchrow.return_value = row

        result = await provider.get_latest_run("test-project")

        assert result is not None
        assert result.run_id == "run-latest"
        assert result.is_latest is True
        # Verify query filters
        sql = conn_manager.fetchrow.call_args[0][0]
        assert "is_latest = TRUE" in sql
        assert "status = 'completed'" in sql

    async def test_list_runs(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        rows = [_make_row(run_id=f"run-{i}") for i in range(3)]
        conn_manager.fetch.return_value = rows

        result = await provider.list_runs("test-project", limit=3)

        assert len(result) == 3
        sql = conn_manager.fetch.call_args[0][0]
        assert "ORDER BY timestamp DESC" in sql
        assert "LIMIT $2" in sql

    async def test_update_run(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        await provider.update_run("run-1", {
            "status": "completed",
            "file_count": 100,
        })

        conn_manager.execute.assert_called_once()
        sql = conn_manager.execute.call_args[0][0]
        assert "UPDATE agv_onboard_runs SET" in sql
        assert "status = $1" in sql
        assert "file_count = $2" in sql
        assert "WHERE run_id = $3" in sql

    async def test_update_run_rejects_bad_columns(
        self, provider: PostgresOnboardMetadataProvider
    ) -> None:
        with pytest.raises(ValueError, match="Cannot update column"):
            await provider.update_run("run-1", {"run_id": "hacked"})

    async def test_update_run_metadata_jsonb(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        await provider.update_run("run-1", {
            "metadata": {"key": "value"},
        })

        sql = conn_manager.execute.call_args[0][0]
        assert "metadata = $1::jsonb" in sql
        # Value should be JSON string
        args = conn_manager.execute.call_args[0]
        assert args[1] == '{"key": "value"}'

    async def test_complete_run_uses_transaction(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        txn_conn = conn_manager._txn_conn
        txn_conn.fetchrow.return_value = FakeRecord(project_id="test-project")

        await provider.complete_run("run-1", file_count=10, chunk_count=50, entity_count=20)

        # Should use transaction context manager
        conn_manager.transaction.assert_called_once()
        # Should execute: SELECT project_id, UPDATE status, UPDATE clear latest, UPDATE set latest
        assert txn_conn.execute.call_count == 3

    async def test_mark_latest_uses_transaction(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        txn_conn = conn_manager._txn_conn
        txn_conn.fetchrow.return_value = FakeRecord(project_id="test-project")

        await provider.mark_latest("run-1")

        conn_manager.transaction.assert_called_once()
        assert txn_conn.execute.call_count == 2  # clear old + set new

    async def test_mark_latest_nonexistent_raises(
        self, provider: PostgresOnboardMetadataProvider, conn_manager: MagicMock
    ) -> None:
        txn_conn = conn_manager._txn_conn
        txn_conn.fetchrow.return_value = None

        with pytest.raises(ValueError, match="Run not found"):
            await provider.mark_latest("nonexistent")

    async def test_row_to_run_handles_json_metadata(
        self, provider: PostgresOnboardMetadataProvider
    ) -> None:
        row = _make_row(metadata='{"duration": 120}')
        result = provider._row_to_run(row)
        assert result.metadata == {"duration": 120}

    async def test_row_to_run_handles_dict_metadata(
        self, provider: PostgresOnboardMetadataProvider
    ) -> None:
        row = _make_row(metadata={"duration": 120})
        result = provider._row_to_run(row)
        assert result.metadata == {"duration": 120}

    async def test_close_resets_initialized(
        self, provider: PostgresOnboardMetadataProvider
    ) -> None:
        provider._initialized = True
        await provider.close()
        assert provider._initialized is False

    async def test_supported_roles(self) -> None:
        assert "onboard_metadata" in PostgresOnboardMetadataProvider.SUPPORTED_ROLES


class TestFromConfig:
    """Tests for from_config class method."""

    @patch(
        "agent_vault.storage.providers.postgresql.connection.PostgresConnectionManager.from_config"
    )
    async def test_from_config_with_connection_string(
        self, mock_from_config: MagicMock
    ) -> None:
        mock_mgr = _make_conn_manager()
        mock_from_config.return_value = mock_mgr

        config = {
            "connection_string": "postgresql://localhost/testdb",
            "table_prefix": "test_",
        }
        provider = PostgresOnboardMetadataProvider.from_config(config, "my-project")

        assert provider._project_id == "my-project"
        mock_from_config.assert_called_once()

    @patch(
        "agent_vault.storage.providers.postgresql.connection.PostgresConnectionManager.from_config"
    )
    @patch(
        "agent_vault.storage.providers.postgresql.vector.PostgresVectorProvider._build_dsn_from_config"
    )
    async def test_from_config_builds_dsn_from_gcp_params(
        self, mock_build_dsn: MagicMock, mock_from_config: MagicMock
    ) -> None:
        mock_mgr = _make_conn_manager()
        mock_from_config.return_value = mock_mgr
        mock_build_dsn.return_value = "postgresql://localhost:5434/agent-vault"

        config = {
            "gcp_project": "my-project",
            "gcp_region": "us-east4",
            "table_prefix": "agv_",
        }
        PostgresOnboardMetadataProvider.from_config(config, "proj")

        mock_build_dsn.assert_called_once()
        mock_from_config.assert_called_once()


class TestRegistryIntegration:
    """Tests for registry integration."""

    def test_postgresql_registry_entry(self) -> None:
        from agent_vault.storage.registry import PROVIDER_REGISTRY

        for backend in ("postgresql", "cloudsql", "alloydb"):
            assert "onboard_metadata" in PROVIDER_REGISTRY[backend], (
                f"{backend} missing onboard_metadata role"
            )
            module, cls_name = PROVIDER_REGISTRY[backend]["onboard_metadata"]
            assert module == "agent_vault.onboard.providers.postgresql"
            assert cls_name == "PostgresOnboardMetadataProvider"

    def test_sqlite_registry_entry_still_exists(self) -> None:
        from agent_vault.storage.registry import PROVIDER_REGISTRY

        assert "onboard_metadata" in PROVIDER_REGISTRY["sqlite"]

    def test_provider_class_loadable(self) -> None:
        from agent_vault.storage.registry import get_provider_class

        cls = get_provider_class("postgresql", "onboard_metadata")
        assert cls is PostgresOnboardMetadataProvider
