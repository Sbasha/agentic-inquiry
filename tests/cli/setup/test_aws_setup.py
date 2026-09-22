"""Tests for AWSSetup (RDS) handler."""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from agent_vault.cli.setup.aws_setup import AWSSetup
from agent_vault.cli.setup.aws_utils import AWSAuthInfo, RDSInstance
from agent_vault.cli.env_resolver import (
    DATA_DIR_NAME,
    REGISTRY_FILE_NAME,
)
from agent_vault.storage.config import BackendConfig
from agent_vault.storage.capabilities import get_capabilities_for_backend
from agent_vault.storage.capabilities import get_capabilities_for_backend
from agent_vault.storage.registry import PROVIDER_REGISTRY


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_aws_auth():
    """Mock AWS authentication checks."""
    with patch(
        "agent_vault.cli.setup.aws_setup.check_aws_cli_installed",
        return_value=True,
    ), patch(
        "agent_vault.cli.setup.aws_setup.check_aws_auth",
        return_value=AWSAuthInfo(
            account_id="123456789012",
            arn="arn:aws:iam::123456789012:user/alice",
            user_id="AIDAXXX",
        ),
    ):
        yield


@pytest.fixture
def mock_aws_resources():
    """Mock AWS resource discovery."""
    instances = [
        RDSInstance(
            identifier="test-db",
            engine="postgres",
            engine_version="15.3",
            status="available",
            endpoint_host="test-db.xxxxx.us-east-1.rds.amazonaws.com",
            endpoint_port=5432,
            region="us-east-1",
            db_name="agent-vault",
        )
    ]

    with patch(
        "agent_vault.cli.setup.aws_setup.get_current_region",
        return_value="us-east-1",
    ), patch(
        "agent_vault.cli.setup.aws_setup.list_rds_instances",
        return_value=instances,
    ), patch(
        "agent_vault.cli.setup.aws_setup.check_iam_auth_enabled",
        return_value=False,
    ):
        yield


# ---------------------------------------------------------------------------
# Basic initialisation tests
# ---------------------------------------------------------------------------

class TestAWSSetupInit:
    """Tests for AWSSetup initialisation."""

    def test_init_with_all_params(self, tmp_path):
        """Test initialisation with all parameters provided."""
        setup = AWSSetup(
            env_name="aws-test",
            workspace=tmp_path,
            region="us-east-1",
            instance="test-db",
            host="test-db.xxxxx.us-east-1.rds.amazonaws.com",
            database="agent-vault",
            user="admin",
            password="secret",
        )
        assert setup.env_name == "aws-test"
        assert setup.backend_type == "rds"
        assert setup._region == "us-east-1"
        assert setup._instance == "test-db"
        assert setup._host == "test-db.xxxxx.us-east-1.rds.amazonaws.com"
        assert setup._database == "agent-vault"
        assert setup._user == "admin"
        assert setup._password == "secret"
        assert setup._use_iam_auth is False

    def test_init_with_iam_auth(self, tmp_path):
        """Test initialisation with IAM authentication."""
        setup = AWSSetup(
            env_name="aws-iam",
            workspace=tmp_path,
            region="us-east-1",
            instance="test-db",
            host="test-db.xxxxx.us-east-1.rds.amazonaws.com",
            database="agent-vault",
            user="admin",
            use_iam_auth=True,
        )
        assert setup._use_iam_auth is True
        assert setup._password is None

    def test_init_defaults(self, tmp_path):
        """Test initialisation with default values."""
        setup = AWSSetup(env_name="aws-defaults", workspace=tmp_path)
        assert setup._database is None
        assert setup._table_prefix == "agv_"
        assert setup._use_iam_auth is False


# ---------------------------------------------------------------------------
# Guard tests (auth / CLI check failures)
# ---------------------------------------------------------------------------

class TestAWSSetupGuards:
    """Tests for early-exit guards in AWSSetup.run()."""

    def test_fails_when_aws_cli_not_installed(self, tmp_path):
        """Setup fails if the AWS CLI is not found."""
        with patch(
            "agent_vault.cli.setup.aws_setup.check_aws_cli_installed",
            return_value=False,
        ):
            setup = AWSSetup(env_name="aws-no-cli", workspace=tmp_path)
            assert setup.run() is False

    def test_fails_when_not_authenticated(self, tmp_path):
        """Setup fails if AWS credentials are not configured."""
        with patch(
            "agent_vault.cli.setup.aws_setup.check_aws_cli_installed",
            return_value=True,
        ), patch(
            "agent_vault.cli.setup.aws_setup.check_aws_auth",
            return_value=None,
        ):
            setup = AWSSetup(env_name="aws-no-auth", workspace=tmp_path)
            assert setup.run() is False


# ---------------------------------------------------------------------------
# Config generation tests (happy path)
# ---------------------------------------------------------------------------

class TestAWSSetupConfig:
    """Tests for AWSSetup configuration generation."""

    def test_full_config_password_auth(self, tmp_path, mock_aws_auth, mock_aws_resources):
        """Test full config generation with password authentication."""
        with patch(
            "agent_vault.cli.setup.validators.validate_rds_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected successfully"),
        ):
            setup = AWSSetup(
                env_name="aws-full",
                workspace=tmp_path,
                region="us-east-1",
                instance="test-db",
                host="test-db.xxxxx.us-east-1.rds.amazonaws.com",
                database="agent-vault",
                user="admin",
                password="secret123",
                table_prefix="agv_",
            )
            result = setup.run()

        assert result is True

        import yaml
        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        rds_backend = config["storage"]["backends"]["rds"]
        assert rds_backend["type"] == "rds"
        assert rds_backend["region"] == "us-east-1"
        assert rds_backend["instance"] == "test-db"
        assert rds_backend["host"] == "test-db.xxxxx.us-east-1.rds.amazonaws.com"
        assert rds_backend["database"] == "agent-vault"
        assert rds_backend["user"] == "admin"
        assert rds_backend["password"] == "secret123"
        assert rds_backend["pool_size"] == 10

        storage = config["storage"]
        assert storage["vector_backend"] == "rds"
        assert storage["graph_backend"] == "rds"
        assert storage["events_backend"] == "rds"
        assert storage["file_tracker_backend_v2"] == "rds"

        assert config["services"]["auto_start_proxy"] is False

    def test_full_config_iam_auth(self, tmp_path, mock_aws_auth, mock_aws_resources):
        """Test full config generation with IAM authentication."""
        with patch(
            "agent_vault.cli.setup.validators.validate_rds_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected successfully via SSL (IAM token auth)"),
        ):
            setup = AWSSetup(
                env_name="aws-iam",
                workspace=tmp_path,
                region="us-east-1",
                instance="test-db",
                host="test-db.xxxxx.us-east-1.rds.amazonaws.com",
                database="agent-vault",
                user="admin",
                use_iam_auth=True,
                table_prefix="agv_",
            )
            result = setup.run()

        assert result is True

        import yaml
        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        rds_backend = config["storage"]["backends"]["rds"]
        assert rds_backend["use_iam_auth"] is True
        assert "password" not in rds_backend

    def test_registry_metadata(self, tmp_path, mock_aws_auth, mock_aws_resources):
        """Test that registry contains correct AWS metadata."""
        with patch(
            "agent_vault.cli.setup.validators.validate_rds_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected"),
        ):
            setup = AWSSetup(
                env_name="aws-meta",
                workspace=tmp_path,
                region="us-east-1",
                instance="test-db",
                host="test-db.xxxxx.us-east-1.rds.amazonaws.com",
                database="agent-vault",
                user="admin",
                password="secret",
                table_prefix="agv_",
            )
            setup.run()

        registry_path = tmp_path / DATA_DIR_NAME / REGISTRY_FILE_NAME
        with open(registry_path) as f:
            registry = json.load(f)

        env = next(e for e in registry["environments"] if e["name"] == "aws-meta")
        assert env["backend_type"] == "rds"
        assert env["metadata"]["setup_type"] == "aws"
        assert env["metadata"]["region"] == "us-east-1"
        assert env["metadata"]["instance"] == "test-db"
        assert env["metadata"]["use_iam_auth"] is False

    def test_port_stored_as_integer(self, tmp_path, mock_aws_auth, mock_aws_resources):
        """Test that the port value in the config is an integer."""
        with patch(
            "agent_vault.cli.setup.validators.validate_rds_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected"),
        ):
            setup = AWSSetup(
                env_name="aws-port",
                workspace=tmp_path,
                region="us-east-1",
                instance="test-db",
                host="test-db.xxxxx.us-east-1.rds.amazonaws.com",
                database="agent-vault",
                user="admin",
                password="secret",
                table_prefix="agv_",
            )
            setup.run()

        import yaml
        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        port = config["storage"]["backends"]["rds"]["port"]
        assert isinstance(port, int), f"Port should be int, got {type(port)}"
        assert port == 5432

    def test_duplicate_env_name_fails(self, tmp_path, mock_aws_auth, mock_aws_resources):
        """Test that creating an env that already exists fails gracefully."""
        with patch(
            "agent_vault.cli.setup.validators.validate_rds_connection",
            new_callable=AsyncMock,
            return_value=(True, "Connected"),
        ):
            setup = AWSSetup(
                env_name="aws-dup",
                workspace=tmp_path,
                region="us-east-1",
                instance="test-db",
                host="test-db.xxxxx.us-east-1.rds.amazonaws.com",
                database="agent-vault",
                user="admin",
                password="secret",
                table_prefix="agv_",
            )
            assert setup.run() is True

            # Running again with same name should fail
            setup2 = AWSSetup(
                env_name="aws-dup",
                workspace=tmp_path,
                region="us-east-1",
                instance="test-db",
                host="test-db.xxxxx.us-east-1.rds.amazonaws.com",
                database="agent-vault",
                user="admin",
                password="secret",
                table_prefix="agv_",
            )
            assert setup2.run() is False


# ---------------------------------------------------------------------------
# AWS utility unit tests
# ---------------------------------------------------------------------------

class TestAWSUtils:
    """Unit tests for aws_utils.py helpers."""

    def test_check_aws_cli_installed_true(self):
        """check_aws_cli_installed returns True when aws binary exists."""
        with patch("shutil.which", return_value="/usr/local/bin/aws"):
            from agent_vault.cli.setup.aws_utils import check_aws_cli_installed
            assert check_aws_cli_installed() is True

    def test_check_aws_cli_installed_false(self):
        """check_aws_cli_installed returns False when aws binary not found."""
        with patch("shutil.which", return_value=None):
            from agent_vault.cli.setup.aws_utils import check_aws_cli_installed
            assert check_aws_cli_installed() is False

    def test_check_aws_auth_success(self):
        """check_aws_auth returns AWSAuthInfo on success."""
        import subprocess
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "UserId": "AIDAXXX",
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/alice",
        })

        with patch("subprocess.run", return_value=mock_result), \
             patch("shutil.which", return_value="/usr/local/bin/aws"):
            from agent_vault.cli.setup.aws_utils import check_aws_auth
            auth = check_aws_auth()
            assert auth is not None
            assert auth.account_id == "123456789012"
            assert auth.display_name == "alice"

    def test_check_aws_auth_failure(self):
        """check_aws_auth returns None on auth failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Unable to locate credentials"

        with patch("subprocess.run", return_value=mock_result), \
             patch("shutil.which", return_value="/usr/local/bin/aws"):
            from agent_vault.cli.setup.aws_utils import check_aws_auth
            assert check_aws_auth() is None

    def test_list_rds_instances_filters_non_postgres(self):
        """list_rds_instances only returns PostgreSQL-compatible engines."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "DBInstances": [
                {
                    "DBInstanceIdentifier": "pg-db",
                    "Engine": "postgres",
                    "EngineVersion": "15.3",
                    "DBInstanceStatus": "available",
                    "Endpoint": {
                        "Address": "pg-db.xxxxx.us-east-1.rds.amazonaws.com",
                        "Port": 5432,
                    },
                    "DBName": "mydb",
                },
                {
                    "DBInstanceIdentifier": "mysql-db",
                    "Engine": "mysql",
                    "EngineVersion": "8.0",
                    "DBInstanceStatus": "available",
                    "Endpoint": {
                        "Address": "mysql-db.xxxxx.us-east-1.rds.amazonaws.com",
                        "Port": 3306,
                    },
                },
            ]
        })

        with patch("subprocess.run", return_value=mock_result), \
             patch("shutil.which", return_value="/usr/local/bin/aws"):
            from agent_vault.cli.setup.aws_utils import list_rds_instances
            instances = list_rds_instances("us-east-1")

        assert len(instances) == 1
        assert instances[0].identifier == "pg-db"
        assert instances[0].engine == "postgres"

    def test_rds_instance_display_name(self):
        """RDSInstance.display_name contains identifier and host."""
        from agent_vault.cli.setup.aws_utils import RDSInstance
        inst = RDSInstance(
            identifier="my-db",
            engine="postgres",
            engine_version="15.3",
            status="available",
            endpoint_host="my-db.xxxxx.us-east-1.rds.amazonaws.com",
            endpoint_port=5432,
            region="us-east-1",
            db_name="agent-vault",
        )
        assert "my-db" in inst.display_name
        # Verify the full hostname appears in the display name
        display = inst.display_name
        assert display.startswith("my-db (") or "my-db.xxxxx" in display


# ---------------------------------------------------------------------------
# BackendConfig / storage layer tests
# ---------------------------------------------------------------------------

class TestRDSBackendConfig:
    """Tests for the rds BackendType in storage/config.py."""

    def test_rds_config_with_password(self):
        """BackendConfig validates a correct rds config with password."""
        cfg = BackendConfig(
            type="rds",
            region="us-east-1",
            instance="my-db",
            host="my-db.xxxxx.us-east-1.rds.amazonaws.com",
            database="agent-vault",
            user="admin",
            password="secret",
        )
        assert cfg.type == "rds"
        assert cfg.region == "us-east-1"

    def test_rds_config_with_iam_auth(self):
        """BackendConfig accepts use_iam_auth=True without a password."""
        cfg = BackendConfig(
            type="rds",
            region="us-east-1",
            instance="my-db",
            host="my-db.xxxxx.us-east-1.rds.amazonaws.com",
            database="agent-vault",
            user="admin",
            use_iam_auth=True,
        )
        assert cfg.use_iam_auth is True

    def test_rds_config_requires_host(self):
        """BackendConfig raises if host is missing for rds."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            BackendConfig(
                type="rds",
                region="us-east-1",
                instance="my-db",
                database="agent-vault",
                user="admin",
                password="secret",
            )

    def test_rds_config_requires_password_or_iam(self):
        """BackendConfig raises if neither password nor use_iam_auth is provided."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            BackendConfig(
                type="rds",
                region="us-east-1",
                instance="my-db",
                host="my-db.xxxxx.us-east-1.rds.amazonaws.com",
                database="agent-vault",
                user="admin",
            )

    def test_rds_config_rejects_invalid_region(self):
        """BackendConfig raises for an invalid AWS region format."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            BackendConfig(
                type="rds",
                region="us-east1",  # missing hyphen between east and 1
                instance="my-db",
                host="my-db.xxxxx.us-east1.rds.amazonaws.com",
                database="agent-vault",
                user="admin",
                password="secret",
            )

    def test_rds_display_info(self):
        """BackendConfig.get_display_info formats rds correctly."""
        cfg = BackendConfig(
            type="rds",
            region="us-east-1",
            instance="my-db",
            host="my-db.xxxxx.us-east-1.rds.amazonaws.com",
            database="agent-vault",
            user="admin",
            password="secret",
        )
        info = cfg.get_display_info()
        assert "rds" in info
        assert "us-east-1" in info
        assert "my-db" in info

    def test_rds_capabilities_no_proxy(self):
        """RDS capabilities declare no proxy required."""
        caps = get_capabilities_for_backend("rds")
        assert caps.requires_proxy is False
        assert caps.is_postgresql_compatible is True
        assert caps.backend_type == "rds"

    def test_rds_in_registry(self):
        """storage/registry.py registers PostgreSQL providers for rds."""
        assert "rds" in PROVIDER_REGISTRY
        assert "vector" in PROVIDER_REGISTRY["rds"]
        assert "events" in PROVIDER_REGISTRY["rds"]
        assert "file_tracker" in PROVIDER_REGISTRY["rds"]
