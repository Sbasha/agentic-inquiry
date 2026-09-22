"""Tests for GCPSetup (CloudSQL) handler."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from agent_vault.cli.setup.gcp_setup import GCPSetup
from agent_vault.cli.setup.gcp_utils import GCPAuthInfo, CloudSQLInstance
from agent_vault.cli.env_resolver import (
    DATA_DIR_NAME,
    ENVS_DIR_NAME,
    REGISTRY_FILE_NAME,
)


@pytest.fixture
def mock_gcp_auth():
    """Mock GCP authentication checks."""
    with patch(
        "agent_vault.cli.setup.gcp_base.check_gcloud_installed",
        return_value=True,
    ), patch(
        "agent_vault.cli.setup.gcp_base.check_gcloud_auth",
        return_value=GCPAuthInfo(account="user@example.com"),
    ), patch(
        "agent_vault.cli.setup.gcp_base.check_adc_configured",
        return_value=(True, "ADC configured"),
    ):
        yield


@pytest.fixture
def mock_gcp_resources():
    """Mock GCP resource discovery."""
    instances = [
        CloudSQLInstance(
            name="test-instance",
            project="test-project",
            region="us-central1",
            database_version="POSTGRES_15",
            state="RUNNABLE",
            connection_name="test-project:us-central1:test-instance",
        )
    ]

    with patch(
        "agent_vault.cli.setup.gcp_base.get_current_project",
        return_value="test-project",
    ), patch(
        "agent_vault.cli.setup.gcp_setup.list_cloudsql_instances",
        return_value=instances,
    ), patch(
        "agent_vault.cli.setup.gcp_setup.list_databases",
        return_value=["postgres", "agent-vault"],
    ), patch(
        "agent_vault.cli.setup.gcp_setup.check_database_exists",
        return_value=True,
    ), patch(
        "agent_vault.cli.setup.gcp_base.get_iam_email",
        return_value="user@example.com",
    ):
        yield


class TestGCPSetup:
    """Tests for GCPSetup class."""

    def test_init_with_params(self, tmp_path):
        """Test initialization with all parameters."""
        setup = GCPSetup(
            env_name="gcp-test",
            workspace=tmp_path,
            project="my-project",
            region="us-central1",
            instance="my-instance",
            database="my-db",
            user="my-user@project.iam",
        )
        assert setup.env_name == "gcp-test"
        assert setup.backend_type == "cloudsql"
        assert setup._project == "my-project"
        assert setup._region == "us-central1"
        assert setup._instance == "my-instance"
        assert setup._database == "my-db"
        assert setup._user == "my-user@project.iam"

    def test_init_defaults(self, tmp_path):
        """Test initialization with defaults."""
        setup = GCPSetup(env_name="test", workspace=tmp_path)
        assert setup._database is None  # None = prompt user interactively
        assert setup._table_prefix == "agv_"

    def test_dev_mode_disables_auto_start(self, tmp_path, mock_gcp_auth, mock_gcp_resources):
        """Test that dev mode disables proxy auto-start."""
        with patch(
            "agent_vault.cli.setup.gcp_setup.validate_cloudsql_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected"),
        ):
            setup = GCPSetup(
                env_name="gcp-dev-test",
                is_dev=True,
                workspace=tmp_path,
                project="test-project",
                region="us-central1",
                instance="test-instance",
                database="agent-vault",
                user="user@example.com",
                table_prefix="agv_",
            )
            result = setup.run()

        assert result is True

        import yaml
        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        # Dev mode should have auto_start_proxy=False
        assert config["services"]["auto_start_proxy"] is False

    def test_gcloud_not_installed(self, tmp_path):
        """Test setup fails when gcloud is not installed."""
        with patch(
            "agent_vault.cli.setup.gcp_base.check_gcloud_installed",
            return_value=False,
        ):
            setup = GCPSetup(env_name="gcp-fail", workspace=tmp_path)
            result = setup.run()

        assert result is False

    def test_not_authenticated(self, tmp_path):
        """Test setup fails when not authenticated."""
        with patch(
            "agent_vault.cli.setup.gcp_base.check_gcloud_installed",
            return_value=True,
        ), patch(
            "agent_vault.cli.setup.gcp_base.check_gcloud_auth",
            return_value=None,
        ):
            setup = GCPSetup(env_name="gcp-noauth", workspace=tmp_path)
            result = setup.run()

        assert result is False


class TestGCPSetupConfig:
    """Tests for GCPSetup configuration generation."""

    def test_full_config(self, tmp_path, mock_gcp_auth, mock_gcp_resources):
        """Test full config generation."""
        with patch(
            "agent_vault.cli.setup.gcp_setup.validate_cloudsql_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected"),
        ):
            setup = GCPSetup(
                env_name="gcp-full",
                workspace=tmp_path,
                project="test-project",
                region="us-central1",
                instance="test-instance",
                database="agent-vault",
                user="user@example.com",
                table_prefix="agv_",
            )
            setup.run()

        import yaml
        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        # Check CloudSQL backend
        cs_backend = config["storage"]["backends"]["cloudsql"]
        assert cs_backend["type"] == "cloudsql"
        assert cs_backend["project"] == "test-project"
        assert cs_backend["region"] == "us-central1"
        assert cs_backend["instance"] == "test-instance"
        assert cs_backend["database"] == "agent-vault"
        assert cs_backend["user"] == "user@example.com"
        assert cs_backend["pool_size"] == 10

        # Check role assignments
        storage = config["storage"]
        assert storage["vector_backend"] == "cloudsql"
        assert storage["graph_backend"] == "cloudsql"
        assert storage["events_backend"] == "cloudsql"
        assert storage["file_tracker_backend_v2"] == "cloudsql"

        # Check services (non-dev mode)
        services = config["services"]
        assert services["auto_start_proxy"] is True
        assert "proxy" in services
        assert services["proxy"]["port"] == 5433

    def test_registry_metadata(self, tmp_path, mock_gcp_auth, mock_gcp_resources):
        """Test registry has correct GCP metadata."""
        with patch(
            "agent_vault.cli.setup.gcp_setup.validate_cloudsql_connection",
            new_callable=AsyncMock,
            return_value=(True, "OK"),
        ):
            setup = GCPSetup(
                env_name="gcp-meta",
                workspace=tmp_path,
                project="test-project",
                region="us-central1",
                instance="test-instance",
                database="agent-vault",
                user="user@example.com",
                table_prefix="agv_",
            )
            setup.run()

        registry_path = tmp_path / DATA_DIR_NAME / REGISTRY_FILE_NAME
        with open(registry_path) as f:
            registry = json.load(f)

        env = next(e for e in registry["environments"] if e["name"] == "gcp-meta")
        assert env["backend_type"] == "cloudsql"
        assert env["metadata"]["setup_type"] == "gcp"
        assert env["metadata"]["project"] == "test-project"
        assert env["metadata"]["region"] == "us-central1"
        assert env["metadata"]["instance"] == "test-instance"
        assert env["metadata"]["auto_start_proxy"] is True


class TestGCPSetupPresetValues:
    """Tests for GCPSetup with preset values (skip interactive prompts)."""

    def test_preset_all_values(self, tmp_path):
        """Test setup with all values preset."""
        with patch(
            "agent_vault.cli.setup.gcp_base.check_gcloud_installed",
            return_value=True,
        ), patch(
            "agent_vault.cli.setup.gcp_base.check_gcloud_auth",
            return_value=GCPAuthInfo(account="test@example.com"),
        ), patch(
            "agent_vault.cli.setup.gcp_base.check_adc_configured",
            return_value=(True, "OK"),
        ), patch(
            "agent_vault.cli.setup.gcp_setup.check_database_exists",
            return_value=True,
        ), patch(
            "agent_vault.cli.setup.gcp_setup.validate_cloudsql_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected"),
        ), patch(
            "agent_vault.cli.setup.base.prompt_input",
            return_value="agv_",
        ):
            setup = GCPSetup(
                env_name="gcp-preset",
                workspace=tmp_path,
                project="preset-project",
                region="us-west1",
                instance="preset-instance",
                database="preset-db",
                user="preset-user@project.iam",
            )
            result = setup.run()

        assert result is True

        import yaml
        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        cs_backend = config["storage"]["backends"]["cloudsql"]
        assert cs_backend["project"] == "preset-project"
        assert cs_backend["region"] == "us-west1"
        assert cs_backend["instance"] == "preset-instance"
        assert cs_backend["database"] == "preset-db"
        assert cs_backend["user"] == "preset-user@project.iam"
