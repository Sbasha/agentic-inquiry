"""Tests for PostgresSetup handler."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from agent_vault.cli.setup.postgres_setup import PostgresSetup
from agent_vault.cli.env_resolver import (
    DATA_DIR_NAME,
    ENVS_DIR_NAME,
    REGISTRY_FILE_NAME,
)


class TestPostgresSetup:
    """Tests for PostgresSetup class."""

    def test_init_with_params(self, tmp_path):
        """Test initialization with all parameters."""
        setup = PostgresSetup(
            env_name="pg-test",
            workspace=tmp_path,
            connection_string="postgresql://user:pass@localhost/db",
            table_prefix="test_",
        )
        assert setup.env_name == "pg-test"
        assert setup.backend_type == "postgresql"
        assert setup._connection_string == "postgresql://user:pass@localhost/db"
        assert setup._table_prefix == "test_"

    def test_init_defaults(self, tmp_path):
        """Test initialization with defaults."""
        setup = PostgresSetup(env_name="test", workspace=tmp_path)
        assert setup._table_prefix == "agv_"
        assert setup._connection_string is None

    @pytest.mark.asyncio
    async def test_run_success(self, tmp_path):
        """Test successful PostgreSQL setup."""
        # Mock validation functions
        with patch(
            "agent_vault.cli.setup.postgres_setup.validate_postgres_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected successfully"),
        ), patch(
            "agent_vault.cli.setup.postgres_setup.check_pgvector_extension",
            new_callable=AsyncMock,
            return_value=True,
        ):
            # Use preset connection_string to avoid prompts
            setup = PostgresSetup(
                env_name="pg-test",
                workspace=tmp_path,
                connection_string="postgresql://localhost/db",
                table_prefix="agv_",
            )
            result = setup.run()

        assert result is True

        # Verify directory and config
        assert setup.config_path.exists()

        import yaml
        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        backends = config["storage"]["backends"]
        assert "postgres_db" in backends
        assert backends["postgres_db"]["type"] == "postgresql"

    @pytest.mark.asyncio
    async def test_run_connection_failure(self, tmp_path):
        """Test setup fails when connection validation fails."""
        with patch(
            "agent_vault.cli.setup.postgres_setup.validate_postgres_connection",
            new_callable=AsyncMock,
            return_value=(False, "Connection refused"),
        ):
            setup = PostgresSetup(
                env_name="pg-fail",
                workspace=tmp_path,
                connection_string="postgresql://localhost/db",
                table_prefix="agv_",
            )
            result = setup.run()

        assert result is False

        # Should not create environment
        assert not setup.config_path.exists()

    @pytest.mark.asyncio
    async def test_pgvector_prompt(self, tmp_path):
        """Test pgvector extension handling."""
        with patch(
            "agent_vault.cli.setup.postgres_setup.validate_postgres_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected"),
        ), patch(
            "agent_vault.cli.setup.postgres_setup.check_pgvector_extension",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "agent_vault.cli.setup.postgres_setup.create_pgvector_extension",
            new_callable=AsyncMock,
            return_value=(True, "Extension created"),
        ), patch(
            "agent_vault.cli.setup.postgres_setup.prompt_confirm",
            return_value=True,
        ):
            setup = PostgresSetup(
                env_name="pg-vector",
                workspace=tmp_path,
                connection_string="postgresql://localhost/db",
                table_prefix="agv_",
            )
            result = setup.run()

        assert result is True


class TestPostgresSetupConfig:
    """Tests for PostgresSetup configuration generation."""

    @pytest.mark.asyncio
    async def test_config_structure(self, tmp_path):
        """Test generated config structure."""
        conn_str = "postgresql://user:pass@localhost:5432/testdb"

        with patch(
            "agent_vault.cli.setup.postgres_setup.validate_postgres_connection",
            new_callable=AsyncMock,
            return_value=(True, "OK"),
        ), patch(
            "agent_vault.cli.setup.postgres_setup.check_pgvector_extension",
            new_callable=AsyncMock,
            return_value=True,
        ):
            setup = PostgresSetup(
                env_name="pg-config",
                workspace=tmp_path,
                connection_string=conn_str,
                table_prefix="myprefix_",
            )
            setup.run()

        import yaml
        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        # Check backend config
        pg_backend = config["storage"]["backends"]["postgres_db"]
        assert pg_backend["type"] == "postgresql"
        assert pg_backend["connection_string"] == conn_str
        assert pg_backend["table_prefix"] == "myprefix_"
        assert pg_backend["pool_size"] == 10

        # Check role assignments
        storage = config["storage"]
        assert storage["vector_backend"] == "postgres_db"
        assert storage["graph_backend"] == "postgres_db"
        assert storage["events_backend"] == "postgres_db"
        assert storage["file_tracker_backend_v2"] == "postgres_db"

        # Check no auto-start proxy
        assert config["services"]["auto_start_proxy"] is False

    @pytest.mark.asyncio
    async def test_registry_metadata(self, tmp_path):
        """Test registry has correct metadata."""
        with patch(
            "agent_vault.cli.setup.postgres_setup.validate_postgres_connection",
            new_callable=AsyncMock,
            return_value=(True, "OK"),
        ), patch(
            "agent_vault.cli.setup.postgres_setup.check_pgvector_extension",
            new_callable=AsyncMock,
            return_value=True,
        ):
            setup = PostgresSetup(
                env_name="pg-meta",
                workspace=tmp_path,
                connection_string="postgresql://localhost/db",
                table_prefix="agv_",
            )
            setup.run()

        registry_path = tmp_path / DATA_DIR_NAME / REGISTRY_FILE_NAME
        with open(registry_path) as f:
            registry = json.load(f)

        env = next(e for e in registry["environments"] if e["name"] == "pg-meta")
        assert env["backend_type"] == "postgresql"
        assert env["metadata"]["setup_type"] == "postgres"
        assert env["metadata"]["table_prefix"] == "agv_"
