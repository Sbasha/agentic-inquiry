"""Unit tests for BackendConfig CloudSQL validation.

Tests cover:
- Required field validation for cloudsql backend type
- Valid configuration parsing
- Default values for pool settings
- Format validation for GCP fields (project, instance, database, user, region)
- Non-cloudsql backends ignoring GCP-specific fields
- Error messages with actionable examples

Acceptance Criteria Coverage:
- AC-2: cloudsql backend type works in configuration
- AC-16: Config accepts project, region, instance parameters
- AC-17: Config accepts database, user parameters
- AC-19: Config accepts pool_size (default 10), max_overflow (default 5)
"""

import pytest

pytestmark = pytest.mark.unit

from agent_vault.storage.config import BackendConfig


class TestCloudSQLConfigValidation:
    """Test CloudSQL-specific configuration validation."""

    def test_cloudsql_config_requires_all_fields(self):
        """ValueError on missing required fields.

        Tests that CloudSQL backend requires all mandatory fields:
        project, region, instance, database, user
        """
        # Missing all fields
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(type="cloudsql")
        error_msg = str(exc_info.value)
        assert "requires: project, region, instance, database, user" in error_msg

        # Missing individual fields
        base_config = {
            "project": "test-project",
            "region": "us-central1",
            "instance": "test-instance",
            "database": "test_db",
            "user": "test-user",
        }

        for field in ["project", "region", "instance", "database", "user"]:
            partial_config = {k: v for k, v in base_config.items() if k != field}
            with pytest.raises(ValueError) as exc_info:
                BackendConfig(type="cloudsql", **partial_config)
            error_msg = str(exc_info.value)
            assert field in error_msg, f"Error should mention missing field: {field}"

    def test_cloudsql_config_accepts_valid_config(self):
        """Parses complete valid configuration.

        Tests AC-16 and AC-17: Config accepts all required parameters
        with valid formats.
        """
        config = BackendConfig(
            type="cloudsql",
            project="my-test-project",
            region="us-central1",
            instance="my-test-instance",
            database="agent-vault",
            user="agv-service-account",
        )

        assert config.type == "cloudsql"
        assert config.project == "my-test-project"
        assert config.region == "us-central1"
        assert config.instance == "my-test-instance"
        assert config.database == "agent-vault"
        assert config.user == "agv-service-account"

    def test_cloudsql_config_defaults(self):
        """pool_size=10, max_overflow=5 by default.

        Tests AC-19: Pool configuration defaults are set correctly.
        """
        config = BackendConfig(
            type="cloudsql",
            project="test-project",
            region="us-west1",
            instance="test-instance",
            database="test_db",
            user="test_user",
        )

        assert config.pool_size == 10, "Default pool_size should be 10"
        assert config.max_overflow == 5, "Default max_overflow should be 5"

        # Test custom pool settings
        config_custom = BackendConfig(
            type="cloudsql",
            project="test-project",
            region="us-west1",
            instance="test-instance",
            database="test_db",
            user="test_user",
            pool_size=20,
            max_overflow=10,
        )

        assert config_custom.pool_size == 20
        assert config_custom.max_overflow == 10

    def test_non_cloudsql_ignores_gcp_fields(self):
        """postgresql type ignores project/region fields.

        Tests FR-4.2: Non-cloudsql backends should not require or
        validate GCP-specific fields.
        """
        # PostgreSQL backend should not require GCP fields
        pg_config = BackendConfig(
            type="postgresql",
            connection_string="postgresql://user:pass@localhost/db",
        )
        assert pg_config.type == "postgresql"
        assert pg_config.project is None
        assert pg_config.region is None

        # PostgreSQL backend should accept but ignore GCP fields
        pg_config_with_gcp = BackendConfig(
            type="postgresql",
            connection_string="postgresql://user:pass@localhost/db",
            project="ignored",
            region="ignored",
        )
        assert pg_config_with_gcp.type == "postgresql"
        assert pg_config_with_gcp.connection_string == "postgresql://user:pass@localhost/db"

        # LanceDB backend should not require GCP fields
        lance_config = BackendConfig(
            type="lancedb",
            database_path="./data/lancedb",
        )
        assert lance_config.type == "lancedb"
        assert lance_config.project is None

    def test_cloudsql_config_error_includes_example(self):
        """Error message includes example configuration.

        Tests FR-3.6: Clear error messages with actionable examples.
        """
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(type="cloudsql")

        error_msg = str(exc_info.value)
        # Should include example with all required fields
        assert "Example:" in error_msg
        assert "type='cloudsql'" in error_msg
        assert "project=" in error_msg
        assert "region=" in error_msg
        assert "instance=" in error_msg
        assert "database=" in error_msg
        assert "user=" in error_msg

    def test_cloudsql_project_id_format_validated(self):
        """Invalid project ID format rejected.

        Tests format validation for GCP project IDs:
        - Must start with lowercase letter
        - Can contain lowercase letters, numbers, hyphens
        - Must be 6-30 characters
        - Must end with letter or number
        """
        base_config = {
            "type": "cloudsql",
            "region": "us-central1",
            "instance": "test-instance",
            "database": "test_db",
            "user": "test_user",
        }

        # Invalid: too short (less than 6 chars)
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, project="abc")
        assert "Invalid GCP project ID format" in str(exc_info.value)

        # Invalid: starts with number
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, project="1test-project")
        assert "Invalid GCP project ID format" in str(exc_info.value)

        # Invalid: contains uppercase
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, project="Test-Project")
        assert "Invalid GCP project ID format" in str(exc_info.value)

        # Invalid: ends with hyphen
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, project="test-project-")
        assert "Invalid GCP project ID format" in str(exc_info.value)

        # Valid: proper format
        valid_config = BackendConfig(**base_config, project="test-project-123")
        assert valid_config.project == "test-project-123"


class TestCloudSQLFieldFormatValidation:
    """Test format validation for individual CloudSQL fields."""

    def test_instance_name_format(self):
        """Validate Cloud SQL instance name format.

        Instance names must:
        - Start with lowercase letter
        - Contain only lowercase letters, numbers, hyphens
        - Be 2-64 characters
        - End with letter or number
        """
        base_config = {
            "type": "cloudsql",
            "project": "test-project",
            "region": "us-central1",
            "database": "test_db",
            "user": "test_user",
        }

        # Invalid: starts with hyphen
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, instance="-invalid")
        assert "Invalid Cloud SQL instance name" in str(exc_info.value)

        # Invalid: contains uppercase
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, instance="Invalid-Instance")
        assert "Invalid Cloud SQL instance name" in str(exc_info.value)

        # Invalid: ends with hyphen
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, instance="test-instance-")
        assert "Invalid Cloud SQL instance name" in str(exc_info.value)

        # Valid instance names
        valid_config = BackendConfig(**base_config, instance="my-instance-1")
        assert valid_config.instance == "my-instance-1"

        valid_config_short = BackendConfig(**base_config, instance="db")
        assert valid_config_short.instance == "db"

    def test_database_name_format(self):
        """Validate database name format.

        Database names must:
        - Start with lowercase letter or underscore
        - Contain only lowercase letters, numbers, underscores
        - Be 1-63 characters
        """
        base_config = {
            "type": "cloudsql",
            "project": "test-project",
            "region": "us-central1",
            "instance": "test-instance",
            "user": "test_user",
        }

        # Invalid: starts with number
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, database="1invalid")
        assert "Invalid database name" in str(exc_info.value)

        # Invalid: contains hyphen
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, database="invalid-db")
        assert "Invalid database name" in str(exc_info.value)

        # Invalid: contains uppercase
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, database="InvalidDB")
        assert "Invalid database name" in str(exc_info.value)

        # Valid database names
        valid_config = BackendConfig(**base_config, database="agent-vault")
        assert valid_config.database == "agent-vault"

        valid_config_underscore = BackendConfig(**base_config, database="_test_db_123")
        assert valid_config_underscore.database == "_test_db_123"

    def test_user_format(self):
        """Validate user format.

        User must be 1-63 characters.
        Supports both standard users and IAM format (user@project.iam).
        """
        base_config = {
            "type": "cloudsql",
            "project": "test-project",
            "region": "us-central1",
            "instance": "test-instance",
            "database": "test_db",
        }

        # Invalid: empty user (caught by required fields check)
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, user="")
        assert "requires: user" in str(exc_info.value)

        # Invalid: too long (> 63 chars)
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, user="a" * 64)
        assert "Invalid user" in str(exc_info.value)

        # Valid: standard user
        valid_config = BackendConfig(**base_config, user="postgres")
        assert valid_config.user == "postgres"

        # Valid: IAM user format
        valid_iam_config = BackendConfig(
            **base_config, user="service-account@my-project.iam"
        )
        assert valid_iam_config.user == "service-account@my-project.iam"

    def test_region_format(self):
        """Validate GCP region format.

        Region format: [geo]-[direction][zone-number][-optional-suffix]
        Examples: us-central1, europe-west1, asia-southeast1-a
        """
        base_config = {
            "type": "cloudsql",
            "project": "test-project",
            "instance": "test-instance",
            "database": "test_db",
            "user": "test_user",
        }

        # Invalid: wrong format
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, region="invalid")
        assert "Invalid GCP region format" in str(exc_info.value)

        # Invalid: uppercase
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, region="US-CENTRAL1")
        assert "Invalid GCP region format" in str(exc_info.value)

        # Invalid: missing zone number
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, region="us-central")
        assert "Invalid GCP region format" in str(exc_info.value)

        # Valid regions
        valid_regions = [
            "us-central1",
            "us-east1",
            "us-west1",
            "europe-west1",
            "asia-southeast1",
            "australia-southeast1",
            "us-central1-a",  # With zone suffix
        ]

        for region in valid_regions:
            valid_config = BackendConfig(**base_config, region=region)
            assert valid_config.region == region


class TestPoolConfigValidation:
    """Test pool configuration validation."""

    def test_pool_size_validation(self):
        """Test pool_size must be at least 1."""
        base_config = {
            "type": "cloudsql",
            "project": "test-project",
            "region": "us-central1",
            "instance": "test-instance",
            "database": "test_db",
            "user": "test_user",
        }

        # Invalid: zero pool size
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, pool_size=0)
        assert "pool_size must be at least 1" in str(exc_info.value)

        # Invalid: negative pool size
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, pool_size=-1)
        assert "pool_size must be at least 1" in str(exc_info.value)

        # Valid: pool_size >= 1
        valid_config = BackendConfig(**base_config, pool_size=1)
        assert valid_config.pool_size == 1

    def test_max_overflow_validation(self):
        """Test max_overflow must be non-negative."""
        base_config = {
            "type": "cloudsql",
            "project": "test-project",
            "region": "us-central1",
            "instance": "test-instance",
            "database": "test_db",
            "user": "test_user",
        }

        # Invalid: negative max_overflow
        with pytest.raises(ValueError) as exc_info:
            BackendConfig(**base_config, max_overflow=-1)
        assert "max_overflow must be non-negative" in str(exc_info.value)

        # Valid: max_overflow = 0
        valid_config = BackendConfig(**base_config, max_overflow=0)
        assert valid_config.max_overflow == 0

        # Valid: max_overflow > 0
        valid_config_positive = BackendConfig(**base_config, max_overflow=10)
        assert valid_config_positive.max_overflow == 10
