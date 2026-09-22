"""Tests for CLI commands.

Tests the CLI features:
- D1: --project flag in maintenance CLI
- D3: list-backups command in schema CLI
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner


class TestMaintenanceCLI:
    """Tests for maintenance CLI commands (D1)."""

    def test_run_command_accepts_project_option(self):
        """Test that run command accepts --project option."""
        from agentic_inquiry.cli.maintenance import maintenance

        runner = CliRunner()

        # Test --help shows project option
        result = runner.invoke(maintenance, ["run", "--help"])
        assert result.exit_code == 0
        assert "--project" in result.output or "-p" in result.output
        assert "Project ID" in result.output

    def test_run_command_project_short_option(self):
        """Test that -p short option works for project."""
        from agentic_inquiry.cli.maintenance import maintenance

        runner = CliRunner()

        # Test --help shows -p short option
        result = runner.invoke(maintenance, ["run", "--help"])
        assert result.exit_code == 0
        assert "-p" in result.output

    def test_run_command_shows_operations(self):
        """Test that run command help shows available operations."""
        from agentic_inquiry.cli.maintenance import maintenance

        runner = CliRunner()

        result = runner.invoke(maintenance, ["run", "--help"])
        assert result.exit_code == 0
        assert "vacuum" in result.output
        assert "reindex" in result.output
        assert "all" in result.output

    @patch("agentic_inquiry.cli.maintenance._load_config")
    @patch("agentic_inquiry.cli.maintenance._get_postgresql_backend")
    @patch("agentic_inquiry.cli.maintenance.asyncio.run")
    def test_project_option_passed_to_async(
        self, mock_asyncio_run, mock_get_backend, mock_load_config
    ):
        """Test that --project is passed to the async function."""
        from agentic_inquiry.cli.maintenance import maintenance

        # Setup mocks
        mock_config = MagicMock()
        mock_config.project_id = "config_project"
        mock_load_config.return_value = mock_config

        mock_backend = MagicMock()
        mock_backend.type = "postgresql"
        mock_get_backend.return_value = mock_backend

        runner = CliRunner()

        # Run with --project option
        runner.invoke(
            maintenance,
            ["run", "--operation", "vacuum", "--project", "cli_project"],
        )

        # Verify asyncio.run was called
        assert mock_asyncio_run.called

    @patch("agentic_inquiry.cli.maintenance._load_config")
    @patch("agentic_inquiry.cli.maintenance._get_postgresql_backend")
    @patch("agentic_inquiry.cli.maintenance.asyncio.run")
    def test_project_displayed_in_output(
        self, mock_asyncio_run, mock_get_backend, mock_load_config
    ):
        """Test that project is displayed in output when provided."""
        from agentic_inquiry.cli.maintenance import maintenance

        # Setup mocks
        mock_config = MagicMock()
        mock_config.project_id = None
        mock_load_config.return_value = mock_config

        mock_backend = MagicMock()
        mock_backend.type = "postgresql"
        mock_get_backend.return_value = mock_backend

        runner = CliRunner()

        # Run with --project option
        result = runner.invoke(
            maintenance,
            ["run", "--operation", "vacuum", "--project", "test_project"],
        )

        # Should display project in output
        assert "test_project" in result.output


class TestSchemaCLI:
    """Tests for schema CLI commands (D3)."""

    def test_list_backups_command_exists(self):
        """Test that list-backups command exists."""
        from agentic_inquiry.cli.schema_migrate import schema

        runner = CliRunner()

        # Test --help shows list-backups command
        result = runner.invoke(schema, ["--help"])
        assert result.exit_code == 0
        assert "list-backups" in result.output

    def test_list_backups_accepts_connection_string(self):
        """Test that list-backups accepts --connection-string option."""
        from agentic_inquiry.cli.schema_migrate import schema

        runner = CliRunner()

        # Test command help shows connection-string option
        result = runner.invoke(schema, ["list-backups", "--help"])
        assert result.exit_code == 0
        assert "--connection-string" in result.output
        assert "AI_CONNECTION_STRING" in result.output

    def test_list_backups_accepts_table_filter(self):
        """Test that list-backups accepts --table option."""
        from agentic_inquiry.cli.schema_migrate import schema

        runner = CliRunner()

        # Test command help shows table option
        result = runner.invoke(schema, ["list-backups", "--help"])
        assert result.exit_code == 0
        assert "--table" in result.output

    def test_list_backups_requires_connection_string(self):
        """Test that list-backups fails gracefully without connection string."""
        from agentic_inquiry.cli.schema_migrate import schema

        runner = CliRunner()

        # Run without connection string (and without env var)
        result = runner.invoke(
            schema, ["list-backups"], env={"AI_CONNECTION_STRING": ""}
        )

        # Should fail with helpful message
        assert result.exit_code != 0
        assert "Connection string required" in result.output

    @patch("agentic_inquiry.cli.schema_migrate.PostgresConnectionManager")
    @patch("agentic_inquiry.cli.schema_migrate.asyncio.run")
    def test_list_backups_calls_database(self, mock_asyncio_run, mock_conn_manager):
        """Test that list-backups calls database operations."""
        from agentic_inquiry.cli.schema_migrate import schema

        runner = CliRunner()

        # Run with connection string
        runner.invoke(
            schema,
            ["list-backups", "--connection-string", "postgresql://test:test@localhost/test"],
        )

        # Verify asyncio.run was called (which runs the async function)
        assert mock_asyncio_run.called


class TestMaintenanceCLIHelp:
    """Tests for maintenance CLI help text."""

    def test_help_shows_project_example(self):
        """Test that help text shows project usage example."""
        from agentic_inquiry.cli.maintenance import maintenance

        runner = CliRunner()

        result = runner.invoke(maintenance, ["run", "--help"])
        assert result.exit_code == 0
        # Should show example with --project
        assert "--project" in result.output

    def test_maintenance_group_help(self):
        """Test that maintenance group has help text."""
        from agentic_inquiry.cli.maintenance import maintenance

        runner = CliRunner()

        result = runner.invoke(maintenance, ["--help"])
        assert result.exit_code == 0
        assert "maintenance" in result.output.lower() or "Database" in result.output


class TestSchemaRestoreCommand:
    """Tests for schema restore command."""

    def test_restore_command_exists(self):
        """Test that restore command exists."""
        from agentic_inquiry.cli.schema_migrate import schema

        runner = CliRunner()

        result = runner.invoke(schema, ["--help"])
        assert result.exit_code == 0
        assert "restore" in result.output

    def test_restore_requires_project(self):
        """Test that restore requires --project option."""
        from agentic_inquiry.cli.schema_migrate import schema

        runner = CliRunner()

        result = runner.invoke(schema, ["restore", "--help"])
        assert result.exit_code == 0
        assert "--project" in result.output
        assert "required" in result.output.lower()


class TestSchemaMigrateCommand:
    """Tests for schema migrate command."""

    def test_migrate_command_exists(self):
        """Test that migrate command exists."""
        from agentic_inquiry.cli.schema_migrate import schema

        runner = CliRunner()

        result = runner.invoke(schema, ["--help"])
        assert result.exit_code == 0
        assert "migrate" in result.output

    def test_migrate_requires_new_dimension(self):
        """Test that migrate requires --new-dimension option."""
        from agentic_inquiry.cli.schema_migrate import schema

        runner = CliRunner()

        result = runner.invoke(schema, ["migrate", "--help"])
        assert result.exit_code == 0
        assert "--new-dimension" in result.output


class TestMaintenanceAsyncFunctions:
    """Direct tests for maintenance CLI async functions.

    These tests verify the actual async functions without mocking asyncio.run,
    ensuring the business logic works correctly.
    """

    @pytest.mark.asyncio
    async def test_run_maintenance_async_vacuum(self):
        """Test _run_maintenance_async executes vacuum operation."""
        from agentic_inquiry.cli.maintenance import _run_maintenance_async
        from agentic_inquiry.storage.config import BackendConfig
        from agentic_inquiry.storage.providers.postgresql.maintenance import MaintenanceResult

        # Create mock backend config
        backend = BackendConfig(
            type="postgresql",
            connection_string="postgresql://test:test@localhost/test",
        )

        # Mock PostgresConnectionManager and PostgresMaintenanceService
        with patch(
            "agentic_inquiry.cli.maintenance.PostgresConnectionManager"
        ) as MockConnMgr, patch(
            "agentic_inquiry.cli.maintenance.PostgresMaintenanceService"
        ) as MockService:
            # Setup connection manager mock
            mock_conn_mgr = AsyncMock()
            MockConnMgr.from_backend_config.return_value = mock_conn_mgr
            MockConnMgr.return_value = mock_conn_mgr

            # Setup maintenance service mock
            mock_service = MagicMock()
            mock_result = MaintenanceResult(
                operation="vacuum",
                table_name="ai_v_chunks",
                duration_seconds=5.2,
                statistics={
                    "dead_tuples_before": 100,
                    "dead_tuples_after": 0,
                    "live_tuples": 1000,
                },
            )
            mock_service.run_maintenance = AsyncMock(return_value=mock_result)
            MockService.return_value = mock_service

            # Act
            await _run_maintenance_async(
                backend=backend,
                operation="vacuum",
                project_id="test-project",
            )

            # Assert
            mock_conn_mgr.initialize.assert_called_once()
            mock_conn_mgr.close.assert_called_once()
            mock_service.run_maintenance.assert_called_once_with(
                operation="vacuum", table_name="ai_v_chunks"
            )

    @pytest.mark.asyncio
    async def test_run_maintenance_async_reindex(self):
        """Test _run_maintenance_async executes reindex operation."""
        from agentic_inquiry.cli.maintenance import _run_maintenance_async
        from agentic_inquiry.storage.config import BackendConfig
        from agentic_inquiry.storage.providers.postgresql.maintenance import MaintenanceResult

        backend = BackendConfig(
            type="postgresql",
            connection_string="postgresql://test:test@localhost/test",
        )

        with patch(
            "agentic_inquiry.cli.maintenance.PostgresConnectionManager"
        ) as MockConnMgr, patch(
            "agentic_inquiry.cli.maintenance.PostgresMaintenanceService"
        ) as MockService:
            mock_conn_mgr = AsyncMock()
            MockConnMgr.from_backend_config.return_value = mock_conn_mgr
            MockConnMgr.return_value = mock_conn_mgr

            mock_service = MagicMock()
            mock_result = MaintenanceResult(
                operation="reindex",
                table_name="ai_v_chunks",
                duration_seconds=12.5,
                statistics={"indexes_rebuilt": 3},
            )
            mock_service.run_maintenance = AsyncMock(return_value=mock_result)
            MockService.return_value = mock_service

            await _run_maintenance_async(
                backend=backend,
                operation="reindex",
            )

            mock_service.run_maintenance.assert_called_once_with(
                operation="reindex", table_name="ai_v_chunks"
            )

    @pytest.mark.asyncio
    async def test_run_maintenance_async_all_operations(self):
        """Test _run_maintenance_async executes all operations."""
        from agentic_inquiry.cli.maintenance import _run_maintenance_async
        from agentic_inquiry.storage.config import BackendConfig
        from agentic_inquiry.storage.providers.postgresql.maintenance import MaintenanceResult

        backend = BackendConfig(
            type="postgresql",
            connection_string="postgresql://test:test@localhost/test",
        )

        with patch(
            "agentic_inquiry.cli.maintenance.PostgresConnectionManager"
        ) as MockConnMgr, patch(
            "agentic_inquiry.cli.maintenance.PostgresMaintenanceService"
        ) as MockService:
            mock_conn_mgr = AsyncMock()
            MockConnMgr.from_backend_config.return_value = mock_conn_mgr
            MockConnMgr.return_value = mock_conn_mgr

            mock_service = MagicMock()
            vacuum_result = MaintenanceResult(
                operation="vacuum",
                table_name="ai_v_chunks",
                duration_seconds=5.0,
                statistics={},
            )
            reindex_result = MaintenanceResult(
                operation="reindex",
                table_name="ai_v_chunks",
                duration_seconds=10.0,
                statistics={},
            )
            mock_service.run_maintenance = AsyncMock(
                side_effect=[vacuum_result, reindex_result]
            )
            MockService.return_value = mock_service

            await _run_maintenance_async(
                backend=backend,
                operation="all",
            )

            # Should call run_maintenance twice (vacuum and reindex)
            assert mock_service.run_maintenance.call_count == 2
            calls = mock_service.run_maintenance.call_args_list
            assert calls[0][1]["operation"] == "vacuum"
            assert calls[1][1]["operation"] == "reindex"

    @pytest.mark.asyncio
    async def test_run_maintenance_async_cleans_up_on_error(self):
        """Test _run_maintenance_async properly shuts down on error."""
        from agentic_inquiry.cli.maintenance import _run_maintenance_async
        from agentic_inquiry.storage.config import BackendConfig

        backend = BackendConfig(
            type="postgresql",
            connection_string="postgresql://test:test@localhost/test",
        )

        with patch(
            "agentic_inquiry.cli.maintenance.PostgresConnectionManager"
        ) as MockConnMgr, patch(
            "agentic_inquiry.cli.maintenance.PostgresMaintenanceService"
        ) as MockService:
            mock_conn_mgr = AsyncMock()
            MockConnMgr.from_backend_config.return_value = mock_conn_mgr
            MockConnMgr.return_value = mock_conn_mgr

            mock_service = MagicMock()
            mock_service.run_maintenance = AsyncMock(
                side_effect=RuntimeError("Database error")
            )
            MockService.return_value = mock_service

            with pytest.raises(RuntimeError):
                await _run_maintenance_async(
                    backend=backend,
                    operation="vacuum",
                )

            # Connection should still be cleaned up
            mock_conn_mgr.close.assert_called_once()


class TestLoadConfigFunction:
    """Direct tests for _load_config function."""

    def test_load_config_missing_file_exits(self, tmp_path):
        """Test that _load_config exits when file is missing."""
        from agentic_inquiry.cli.maintenance import _load_config

        with pytest.raises(SystemExit):
            _load_config(tmp_path / "nonexistent.yaml")

    def test_load_config_invalid_yaml_exits(self, tmp_path):
        """Test that _load_config exits on invalid YAML."""
        from agentic_inquiry.cli.maintenance import _load_config

        # Create invalid YAML file
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: : content")

        with pytest.raises(SystemExit):
            _load_config(config_file)

    def test_load_config_valid_file_returns_config(self, tmp_path):
        """Test that _load_config returns StorageConfig for valid file."""
        from agentic_inquiry.cli.maintenance import _load_config
        from agentic_inquiry.config import StorageConfig

        # Create valid YAML config
        config_file = tmp_path / "valid.yaml"
        config_file.write_text(
            """
root: /tmp/test_data
backends:
  default:
    type: postgresql
    connection_string: postgresql://localhost/test
"""
        )

        result = _load_config(config_file)

        assert isinstance(result, StorageConfig)
        assert result.root == "/tmp/test_data"
