"""Tests for AzureSetup handler."""

from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from agent_vault.cli.setup.azure_setup import AzureSetup
from agent_vault.cli.env_resolver import DATA_DIR_NAME

# Mark all tests in this module as unit tests
pytestmark = [pytest.mark.unit]


class TestAzureSetup:
    """Tests for AzureSetup class."""

    def test_init_with_params(self, tmp_path):
        """Test initialization with explicit parameters."""
        setup = AzureSetup(
            env_name="azure-test",
            workspace=tmp_path,
            host="my-server.postgres.database.azure.com",
            database="agv_db",
            user="admin",
            password="password123",
            embedding_strategy="server_side",
            embedding_model="text-embedding-3-small"
        )
        
        assert setup.env_name == "azure-test"
        assert setup.backend_type == "azure"
        assert setup._host == "my-server.postgres.database.azure.com"
        assert setup._database == "agv_db"
        assert setup._user == "admin"
        assert setup._password == "password123"
        assert setup._embedding_strategy == "server_side"
        assert setup._embedding_model == "text-embedding-3-small"

    @patch("agent_vault.cli.setup.azure_setup.prompt_input")
    @patch("agent_vault.cli.setup.azure_setup.prompt_confirm")
    @patch("agent_vault.cli.setup.azure_setup.getpass.getpass")
    @patch("agent_vault.cli.setup.azure_setup.run_async")
    @patch("agent_vault.cli.setup.base.BaseSetup.register_environment")
    @patch("agent_vault.cli.setup.base.BaseSetup.set_active")
    def test_run_success(self, mock_set_active, mock_register, mock_run_async, mock_getpass, mock_confirm, mock_input, tmp_path):
        """Test successful setup run with prompts."""
        setup = AzureSetup(env_name="azure-test", workspace=tmp_path)
        
        # Mock user inputs in the order the wizard prompts them
        mock_input.side_effect = [
            "my-server.postgres.database.azure.com",  # Host
            "agent-vault",                           # Database
            "admin",                                  # User
            "text-embedding-3-small",                 # Deployment / model
            "1536",                                   # Embedding dim (default for the model)
        ]
        mock_getpass.return_value = "password123"
        mock_confirm.return_value = True # Enable server-side embeddings
        mock_run_async.return_value = True # Connection test success

        success = setup.run()

        assert success is True

        # Verify config was saved
        config_path = tmp_path / DATA_DIR_NAME / "envs" / "azure-test" / "config.yaml"
        assert config_path.exists()

        # Verify .env was saved
        env_path = tmp_path / DATA_DIR_NAME / "envs" / "azure-test" / ".env"
        assert env_path.exists()
        env_content = env_path.read_text()
        assert "DB_PASSWORD=password123" in env_content
        assert "AZURE_POSTGRES_HOST=my-server.postgres.database.azure.com" in env_content

        # Verify the rendered config has the AOAI deployment + dim, and
        # the embeddings block tracks the server-side path.
        import yaml as _yaml

        rendered = _yaml.safe_load(config_path.read_text())
        azure_backend = rendered["storage"]["backends"]["azure_db"]
        assert azure_backend["embedding_strategy"] == "server_side"
        assert azure_backend["embedding_model"] == "text-embedding-3-small"
        assert azure_backend["embedding_dim"] == 1536
        assert rendered["embeddings"]["default_provider"] == "none"
        assert rendered["embeddings"]["default_dimensions"] == 1536

    @patch("agent_vault.storage.providers.postgresql.connection.PostgresConnectionManager")
    @patch("agent_vault.storage.providers.postgresql.adapter.AzurePostgresAdapter")
    @pytest.mark.asyncio
    async def test_verify_and_initialize(self, mock_adapter_cls, mock_manager_cls, tmp_path):
        """Test the connection and extension verification logic."""
        setup = AzureSetup(
            env_name="azure-test",
            workspace=tmp_path,
            host="host",
            user="user",
            password="pass",
            embedding_strategy="server_side",
            embedding_model="model"
        )
        
        # Mock connection manager
        mock_manager = mock_manager_cls.return_value
        mock_manager.initialize = AsyncMock()
        mock_manager.ensure_extension = AsyncMock()
        mock_manager.fetch = AsyncMock()
        mock_manager.close = AsyncMock()
        
        # Mock adapter. ``required_extensions`` is now a method (takes
        # the embedding strategy) — return ``["vector", "azure_ai"]``
        # for the server-side path the test exercises.
        mock_adapter = mock_adapter_cls.return_value
        mock_adapter.required_extensions = MagicMock(
            return_value=["vector", "azure_ai"]
        )
        mock_adapter.get_embedding_sql.return_value = "azure_ai.generate_embeddings(...)"
        
        success = await setup._verify_and_initialize()
        
        assert success is True
        mock_manager.initialize.assert_awaited_once()
        assert mock_manager.ensure_extension.await_count == 2
        mock_manager.fetch.assert_awaited_once()
        mock_manager.close.assert_awaited_once()
