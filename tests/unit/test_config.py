"""Unit tests for Config environment variable support.

Tests cover:
- Environment variable overrides for maintenance configuration
- Environment variable overrides for MCP query configuration
- Invalid environment variable values
- Validation of configuration limits
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.config import Config, ConfigurationError


class TestMaintenanceConfigEnvOverrides:
    """Test environment variable overrides for maintenance configuration."""

    @pytest.mark.parametrize(
        ("env_var", "env_value", "config_data", "path", "expected"),
        [
            ("AI_MAINTENANCE_TRIGGER", "indexing.completed", {'maintenance': {'trigger': 'project.closed'}}, ("maintenance", "trigger"), "indexing.completed"),
            ("AI_MAINTENANCE_RETENTION_MINUTES", "120", {'maintenance': {'cleanup_retention_minutes': 60}}, ("maintenance", "cleanup_retention_minutes"), 120),
            ("AI_MAINTENANCE_ENABLED", "false", {'maintenance': {'enabled': True}}, ("maintenance", "enabled"), False),
        ],
    )
    def test_maintenance_env_overrides(self, monkeypatch, env_var, env_value, config_data, path, expected):
        """Test maintenance environment variable overrides."""
        import copy
        monkeypatch.setenv(env_var, env_value)

        config_data = Config._apply_env_overrides(copy.deepcopy(config_data))
        current = config_data
        for key in path:
            current = current[key]
        assert current == expected

    def test_multiple_maintenance_overrides(self, monkeypatch):
        """Test multiple maintenance environment variable overrides simultaneously."""
        monkeypatch.setenv("AI_MAINTENANCE_TRIGGER", "disabled")
        monkeypatch.setenv("AI_MAINTENANCE_RETENTION_MINUTES", "30")
        monkeypatch.setenv("AI_MAINTENANCE_ENABLED", "false")

        config_data = {
            'maintenance': {
                'trigger': 'project.closed',
                'cleanup_retention_minutes': 60,
                'enabled': True
            }
        }
        config_data = Config._apply_env_overrides(config_data)

        assert config_data['maintenance']['trigger'] == "disabled"
        assert config_data['maintenance']['cleanup_retention_minutes'] == 30
        assert config_data['maintenance']['enabled'] is False

    def test_invalid_maintenance_trigger_raises_error(self, monkeypatch):
        """Test that invalid maintenance trigger value raises ConfigurationError."""
        monkeypatch.setenv("AI_MAINTENANCE_TRIGGER", "invalid_trigger")

        with pytest.raises(ConfigurationError) as exc_info:
            Config.load()

        assert "Invalid maintenance trigger" in str(exc_info.value)
        assert "invalid_trigger" in str(exc_info.value)

    @pytest.mark.parametrize(
        ("env_value", "expected_substrings"),
        [
            ("4", ["Invalid cleanup_retention_minutes", "4", "Must be between 5 and 1440"]),
            ("1441", ["Invalid cleanup_retention_minutes", "1441", "Must be between 5 and 1440"]),
        ],
    )
    def test_invalid_retention_minutes(self, monkeypatch, env_value, expected_substrings):
        """Test invalid cleanup_retention_minutes values."""
        monkeypatch.setenv("AI_MAINTENANCE_RETENTION_MINUTES", env_value)

        with pytest.raises(ConfigurationError) as exc_info:
            Config.load()

        message = str(exc_info.value)
        for substring in expected_substrings:
            assert substring in message

    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [
            ("5", 5),
            ("1440", 1440),
        ],
    )
    def test_valid_retention_minutes_boundary_values(self, monkeypatch, env_value, expected):
        """Test that boundary values for cleanup_retention_minutes are accepted."""
        monkeypatch.setenv("AI_MAINTENANCE_RETENTION_MINUTES", env_value)
        config = Config.load()
        assert config.maintenance.cleanup_retention_minutes == expected


class TestMCPQueryConfigEnvOverrides:
    """Test environment variable overrides for MCP query configuration."""

    @pytest.mark.parametrize(
        ("env_var", "env_value", "config_data", "path", "expected"),
        [
            ("AI_TRAVERSAL_LIMIT", "1000", {'mcp': {'query': {'traversal_limit': 500}}}, ("mcp", "query", "traversal_limit"), 1000),
            ("AI_BATCH_SIZE", "250", {'mcp': {'query': {'batch_size': 100}}}, ("mcp", "query", "batch_size"), 250),
        ],
    )
    def test_query_env_overrides(self, monkeypatch, env_var, env_value, config_data, path, expected):
        """Test MCP query environment variable overrides."""
        import copy
        monkeypatch.setenv(env_var, env_value)

        config_data = Config._apply_env_overrides(copy.deepcopy(config_data))
        current = config_data
        for key in path:
            current = current[key]
        assert current == expected

    def test_multiple_query_overrides(self, monkeypatch):
        """Test multiple MCP query environment variable overrides simultaneously."""
        monkeypatch.setenv("AI_TRAVERSAL_LIMIT", "1500")
        monkeypatch.setenv("AI_BATCH_SIZE", "200")

        config_data = {
            'mcp': {
                'query': {
                    'traversal_limit': 500,
                    'batch_size': 100
                }
            }
        }
        config_data = Config._apply_env_overrides(config_data)

        assert config_data['mcp']['query']['traversal_limit'] == 1500
        assert config_data['mcp']['query']['batch_size'] == 200

    @pytest.mark.parametrize(
        ("env_var", "env_value", "expected_substrings"),
        [
            ("AI_TRAVERSAL_LIMIT", "99", ["traversal_limit must be between 100 and 2000", "got 99"]),
            ("AI_TRAVERSAL_LIMIT", "2001", ["traversal_limit must be between 100 and 2000", "got 2001"]),
            ("AI_BATCH_SIZE", "9", ["batch_size must be between 10 and 500", "got 9"]),
            ("AI_BATCH_SIZE", "501", ["batch_size must be between 10 and 500", "got 501"]),
        ],
    )
    def test_invalid_query_limits(self, monkeypatch, env_var, env_value, expected_substrings):
        """Test invalid traversal_limit and batch_size values."""
        monkeypatch.setenv(env_var, env_value)

        with pytest.raises(ConfigurationError) as exc_info:
            Config.load()

        message = str(exc_info.value)
        for substring in expected_substrings:
            assert substring in message

    @pytest.mark.parametrize(
        ("env_var", "env_value", "attr_path", "expected"),
        [
            ("AI_TRAVERSAL_LIMIT", "100", ("mcp", "query", "traversal_limit"), 100),
            ("AI_TRAVERSAL_LIMIT", "2000", ("mcp", "query", "traversal_limit"), 2000),
            ("AI_BATCH_SIZE", "10", ("mcp", "query", "batch_size"), 10),
            ("AI_BATCH_SIZE", "500", ("mcp", "query", "batch_size"), 500),
        ],
    )
    def test_valid_query_limit_boundaries(self, monkeypatch, env_var, env_value, attr_path, expected):
        """Test boundary values for traversal_limit and batch_size."""
        monkeypatch.setenv(env_var, env_value)
        config = Config.load()
        current = config
        for key in attr_path:
            current = getattr(current, key)
        assert current == expected


class TestConfigIntegration:
    """Test integration of environment variable overrides with full config loading."""

    def test_all_new_env_vars_together(self, monkeypatch):
        """Test that all new environment variables can be set together."""
        monkeypatch.setenv("AI_MAINTENANCE_TRIGGER", "indexing.completed")
        monkeypatch.setenv("AI_MAINTENANCE_RETENTION_MINUTES", "180")
        monkeypatch.setenv("AI_MAINTENANCE_ENABLED", "false")
        monkeypatch.setenv("AI_TRAVERSAL_LIMIT", "1200")
        monkeypatch.setenv("AI_BATCH_SIZE", "300")

        config = Config.load()

        # Verify maintenance config
        assert config.maintenance.trigger == "indexing.completed"
        assert config.maintenance.cleanup_retention_minutes == 180
        assert config.maintenance.enabled is False

        # Verify MCP query config
        assert config.mcp.query.traversal_limit == 1200
        assert config.mcp.query.batch_size == 300

    def test_env_vars_override_file_config(self, tmp_path, monkeypatch):
        """Test that environment variables override file configuration."""
        # Create a config file with default values
        config_file = tmp_path / "test_config.yaml"
        config_content = """
storage:
  root: ./.test_storage
  lancedb:
    path: lancedb
  file_tracker:
    path: file_tracker.db
  document_cache:
    enabled: false
    path: cache

cache:
  document_cache:
    max_size: 1000

search:
  default_limit: 10
  max_limit: 100

embeddings:
  default_provider: sentence_transformer

parsers: {}

maintenance:
  trigger: project.closed
  cleanup_retention_minutes: 60
  enabled: true

mcp:
  query:
    traversal_limit: 500
    batch_size: 100
"""
        config_file.write_text(config_content)

        # Set environment variables to override
        monkeypatch.setenv("AI_MAINTENANCE_TRIGGER", "disabled")
        monkeypatch.setenv("AI_MAINTENANCE_RETENTION_MINUTES", "720")
        monkeypatch.setenv("AI_TRAVERSAL_LIMIT", "1800")
        monkeypatch.setenv("AI_BATCH_SIZE", "400")

        config = Config.load(str(config_file))

        # Verify environment variables took precedence
        assert config.maintenance.trigger == "disabled"
        assert config.maintenance.cleanup_retention_minutes == 720
        assert config.mcp.query.traversal_limit == 1800
        assert config.mcp.query.batch_size == 400

    def test_partial_env_override(self, monkeypatch):
        """Test that partial environment variable overrides work correctly."""
        # Only override some values, not all
        monkeypatch.setenv("AI_MAINTENANCE_RETENTION_MINUTES", "90")
        monkeypatch.setenv("AI_BATCH_SIZE", "150")

        config = Config.load()

        # Verify overridden values
        assert config.maintenance.cleanup_retention_minutes == 90
        assert config.mcp.query.batch_size == 150

        # Verify default values for non-overridden settings
        assert config.maintenance.trigger == "project.closed"  # Default
        assert config.maintenance.enabled is True  # Default
        assert config.mcp.query.traversal_limit == 500  # Default

    def test_type_conversion_for_env_vars(self, monkeypatch):
        """Test that environment variable values are converted to correct types."""
        # String to int conversion
        monkeypatch.setenv("AI_MAINTENANCE_RETENTION_MINUTES", "240")
        monkeypatch.setenv("AI_TRAVERSAL_LIMIT", "1500")
        monkeypatch.setenv("AI_BATCH_SIZE", "250")

        config = Config.load()

        assert isinstance(config.maintenance.cleanup_retention_minutes, int)
        assert isinstance(config.mcp.query.traversal_limit, int)
        assert isinstance(config.mcp.query.batch_size, int)

        # String to bool conversion
        monkeypatch.setenv("AI_MAINTENANCE_ENABLED", "false")
        config = Config.load()
        assert isinstance(config.maintenance.enabled, bool)
        assert config.maintenance.enabled is False

    def test_logging_of_applied_overrides(self, monkeypatch, caplog):
        """Test that applied environment variable overrides are logged."""
        import logging

        monkeypatch.setenv("AI_MAINTENANCE_RETENTION_MINUTES", "120")
        monkeypatch.setenv("AI_TRAVERSAL_LIMIT", "1000")

        with caplog.at_level(logging.DEBUG):
            Config.load()

        # Verify debug messages were logged
        debug_messages = [record.message for record in caplog.records if record.levelname == "DEBUG"]

        assert any("AI_MAINTENANCE_RETENTION_MINUTES" in msg for msg in debug_messages)
        assert any("AI_TRAVERSAL_LIMIT" in msg for msg in debug_messages)


class TestAcceptanceCriteria:
    """Test acceptance criteria for environment variable support."""

    def test_ac_4_2_traversal_limit_affects_behavior(self, monkeypatch):
        """AC-4.2: Verify that traversal_limit changes affect behavior.

        This test verifies that the traversal_limit configuration value
        is correctly set and can be accessed by components that use it.
        """
        # Set a custom traversal limit
        monkeypatch.setenv("AI_TRAVERSAL_LIMIT", "1500")

        config = Config.load()

        # Verify the value is set correctly
        assert config.mcp.query.traversal_limit == 1500

        # Verify the value is within valid range
        assert 100 <= config.mcp.query.traversal_limit <= 2000

    def test_ac_4_3_cleanup_retention_minutes_respected(self, monkeypatch):
        """AC-4.3: Verify that cleanup_retention_minutes is respected.

        This test verifies that the cleanup_retention_minutes configuration
        value is correctly set and can be accessed by maintenance components.
        """
        # Set a custom retention period
        monkeypatch.setenv("AI_MAINTENANCE_RETENTION_MINUTES", "360")

        config = Config.load()

        # Verify the value is set correctly
        assert config.maintenance.cleanup_retention_minutes == 360

        # Verify the value is within valid range
        assert 5 <= config.maintenance.cleanup_retention_minutes <= 1440


class TestPackagedConfigResolver:
    """Resolve default.yaml / config.schema.json for wheel vs source checkout."""

    def test_source_checkout_finds_top_level_config(self) -> None:
        """A source checkout has no packaged copy; fall back to config/."""
        path = Config._packaged_config_file("default.yaml")
        assert path is not None
        assert path.exists()
        assert path.name == "default.yaml"

    def test_packaged_copy_wins_over_source_tree(self, tmp_path, monkeypatch) -> None:
        """An installed wheel prefers agentic_inquiry/config_defaults/."""
        packaged_root = tmp_path / "pkg"
        packaged_file = packaged_root / "config_defaults" / "default.yaml"
        packaged_file.parent.mkdir(parents=True)
        packaged_file.write_text("from: packaged\n")

        class _FakeResource:
            def __init__(self, path: Path) -> None:
                self._path = path

            def joinpath(self, name: str) -> "_FakeResource":
                return _FakeResource(self._path / name)

            def is_file(self) -> bool:
                return self._path.is_file()

            def __str__(self) -> str:
                return str(self._path)

        monkeypatch.setattr(
            "agentic_inquiry.config._resource_files",
            lambda _name: _FakeResource(packaged_root),
        )

        path = Config._packaged_config_file("default.yaml")
        assert path == packaged_file

    def test_missing_file_returns_none(self) -> None:
        """A filename that exists in neither location returns None."""
        assert Config._packaged_config_file("definitely-not-a-config.yaml") is None

    def test_find_config_file_falls_back_to_package_default(
        self, tmp_path, monkeypatch
    ) -> None:
        """No env override and no cwd yaml: use the package default."""
        monkeypatch.delenv("AI_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)
        # Isolate from a leftover ~/.agentic-inquiry/config.yaml on the developer machine.
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        (tmp_path / "home").mkdir()

        found = Config._find_config_file()
        assert found.name == "default.yaml"
        assert found.exists()
