"""Unit tests for LoggingConfig.

Tests cover:
- Default values are applied correctly
- Log level validation
- Environment variable overrides for logging config
- Config loading from YAML with logging section
"""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.config import Config, LoggingConfig


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("directory", "logs"),
        ("level", "INFO"),
        ("max_bytes", 10 * 1024 * 1024),
        ("backup_count", 5),
        ("retention_hours", 24),
        ("service_levels", {}),
        ("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        ("date_format", "%Y-%m-%d %H:%M:%S"),
    ],
)
def test_logging_config_defaults(field, expected):
    """Test that default values are applied correctly."""
    config = LoggingConfig()
    assert getattr(config, field) == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("directory", "/var/log/app"),
        ("level", "DEBUG"),
        ("max_bytes", 50 * 1024 * 1024),
        ("backup_count", 10),
        ("retention_hours", 48),
        ("service_levels", {"parsers": "DEBUG", "database": "WARNING"}),
        ("format", "%(levelname)s: %(message)s"),
        ("date_format", "%Y/%m/%d %H:%M"),
    ],
)
def test_logging_config_custom_values(field, value):
    """Test that custom values can be set."""
    config = LoggingConfig(**{field: value})
    assert getattr(config, field) == value


class TestEnvironmentVariableOverrides:
    """Test environment variable overrides for logging config."""

    @pytest.mark.parametrize(
        ("env_var", "env_value", "config_data", "path", "expected"),
        [
            (
                "INQUIRY_LOGGING_DIRECTORY",
                "/tmp/custom_logs",
                {"logging": {"directory": "logs"}},
                ("logging", "directory"),
                "/tmp/custom_logs",
            ),
            (
                "INQUIRY_LOGGING_LEVEL",
                "DEBUG",
                {"logging": {"level": "INFO"}},
                ("logging", "level"),
                "DEBUG",
            ),
            (
                "INQUIRY_LOGGING_MAX_BYTES",
                "20971520",
                {"logging": {"max_bytes": 10485760}},
                ("logging", "max_bytes"),
                20971520,
            ),
            (
                "INQUIRY_LOGGING_BACKUP_COUNT",
                "10",
                {"logging": {"backup_count": 5}},
                ("logging", "backup_count"),
                10,
            ),
            (
                "INQUIRY_LOGGING_RETENTION_HOURS",
                "48",
                {"logging": {"retention_hours": 24}},
                ("logging", "retention_hours"),
                48,
            ),
            (
                "INQUIRY_LOGGING_FORMAT",
                "%(levelname)s: %(message)s",
                {"logging": {"format": "%(asctime)s - %(message)s"}},
                ("logging", "format"),
                "%(levelname)s: %(message)s",
            ),
            (
                "INQUIRY_LOGGING_DATE_FORMAT",
                "%Y/%m/%d",
                {"logging": {"date_format": "%Y-%m-%d %H:%M:%S"}},
                ("logging", "date_format"),
                "%Y/%m/%d",
            ),
            (
                "INQUIRY_LOGGING_SERVICE_LEVELS_PARSERS",
                "DEBUG",
                {"logging": {"service_levels": {}}},
                ("logging", "service_levels", "parsers"),
                "DEBUG",
            ),
            (
                "INQUIRY_LOGGING_SERVICE_LEVELS_DATABASE",
                "WARNING",
                {"logging": {"service_levels": {}}},
                ("logging", "service_levels", "database"),
                "WARNING",
            ),
        ],
    )
    def test_logging_env_overrides(
        self, monkeypatch, env_var, env_value, config_data, path, expected
    ):
        """Test logging environment variable overrides."""
        monkeypatch.setenv(env_var, env_value)

        config_data = Config._apply_env_overrides(config_data)
        current = config_data
        for key in path:
            current = current[key]
        assert current == expected

    def test_multiple_logging_overrides(self, monkeypatch):
        """Test multiple logging environment variable overrides simultaneously."""
        monkeypatch.setenv("INQUIRY_LOGGING_DIRECTORY", "/tmp/logs")
        monkeypatch.setenv("INQUIRY_LOGGING_LEVEL", "WARNING")
        monkeypatch.setenv("INQUIRY_LOGGING_MAX_BYTES", "52428800")  # 50MB
        monkeypatch.setenv("INQUIRY_LOGGING_RETENTION_HOURS", "72")
        monkeypatch.setenv("INQUIRY_LOGGING_SERVICE_LEVELS_PARSERS", "DEBUG")

        config_data = {
            "logging": {
                "directory": "logs",
                "level": "INFO",
                "max_bytes": 10485760,
                "retention_hours": 24,
                "service_levels": {},
            }
        }
        config_data = Config._apply_env_overrides(config_data)

        assert config_data["logging"]["directory"] == "/tmp/logs"
        assert config_data["logging"]["level"] == "WARNING"
        assert config_data["logging"]["max_bytes"] == 52428800
        assert config_data["logging"]["retention_hours"] == 72
        assert config_data["logging"]["service_levels"]["parsers"] == "DEBUG"

    def test_service_levels_creates_logging_section(self, monkeypatch):
        """Test that service_levels env var creates logging section if missing."""
        monkeypatch.setenv("INQUIRY_LOGGING_SERVICE_LEVELS_PARSERS", "DEBUG")

        config_data = {}
        config_data = Config._apply_env_overrides(config_data)

        assert "logging" in config_data
        assert "service_levels" in config_data["logging"]
        assert config_data["logging"]["service_levels"]["parsers"] == "DEBUG"


class TestConfigLoadingWithLogging:
    """Test config loading from YAML with logging section."""

    def test_load_config_with_logging_section(self, tmp_path):
        """Test loading config with logging section from YAML."""
        config_file = tmp_path / "mock_config.yaml"
        config_file.write_text("""
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

memory:
  working_memory:
    capacity: 20

events:
  enabled: true

logging:
  directory: /var/log/app
  level: DEBUG
  max_bytes: 52428800
  backup_count: 10
  retention_hours: 48
  service_levels:
    parsers: DEBUG
    database: WARNING
  format: "%(levelname)s: %(message)s"
  date_format: "%Y/%m/%d %H:%M"
""")

        config = Config.load(str(config_file))

        assert config.logging.directory == "/var/log/app"
        assert config.logging.level == "DEBUG"
        assert config.logging.max_bytes == 52428800
        assert config.logging.backup_count == 10
        assert config.logging.retention_hours == 48
        assert config.logging.service_levels == {
            "parsers": "DEBUG",
            "database": "WARNING",
        }
        assert config.logging.format == "%(levelname)s: %(message)s"
        assert config.logging.date_format == "%Y/%m/%d %H:%M"

    def test_load_config_without_logging_section(self, tmp_path):
        """Test loading config without logging section uses defaults."""
        config_file = tmp_path / "mock_config.yaml"
        config_file.write_text("""
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

memory:
  working_memory:
    capacity: 20

events:
  enabled: true
""")

        config = Config.load(str(config_file))

        # Should use defaults
        assert config.logging.directory == "logs"
        assert config.logging.level == "INFO"
        assert config.logging.max_bytes == 10 * 1024 * 1024
        assert config.logging.backup_count == 5
        assert config.logging.retention_hours == 24
        assert config.logging.service_levels == {}

    def test_load_config_with_partial_logging_section(self, tmp_path):
        """Test loading config with partial logging section uses defaults for missing values."""
        config_file = tmp_path / "mock_config.yaml"
        config_file.write_text("""
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

memory:
  working_memory:
    capacity: 20

events:
  enabled: true

logging:
  directory: /custom/logs
  level: WARNING
""")

        config = Config.load(str(config_file))

        # Custom values
        assert config.logging.directory == "/custom/logs"
        assert config.logging.level == "WARNING"

        # Default values for missing fields
        assert config.logging.max_bytes == 10 * 1024 * 1024
        assert config.logging.backup_count == 5
        assert config.logging.retention_hours == 24
        assert config.logging.service_levels == {}
        assert (
            config.logging.format
            == "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        assert config.logging.date_format == "%Y-%m-%d %H:%M:%S"

    def test_env_overrides_yaml_config(self, tmp_path, monkeypatch):
        """Test that environment variables override YAML config."""
        config_file = tmp_path / "mock_config.yaml"
        config_file.write_text("""
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

memory:
  working_memory:
    capacity: 20

events:
  enabled: true

logging:
  directory: /var/log/app
  level: INFO
  max_bytes: 10485760
""")

        # Set environment overrides
        monkeypatch.setenv("INQUIRY_LOGGING_LEVEL", "DEBUG")
        monkeypatch.setenv("INQUIRY_LOGGING_MAX_BYTES", "52428800")
        monkeypatch.setenv("INQUIRY_LOGGING_SERVICE_LEVELS_PARSERS", "DEBUG")

        config = Config.load(str(config_file))

        # YAML value (not overridden)
        assert config.logging.directory == "/var/log/app"

        # Environment overrides
        assert config.logging.level == "DEBUG"
        assert config.logging.max_bytes == 52428800
        assert config.logging.service_levels == {"parsers": "DEBUG"}


class TestLogLevelValidation:
    """Test log level validation."""

    def test_valid_log_levels(self):
        """Test that valid log levels are accepted."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        for level in valid_levels:
            config = LoggingConfig(level=level)
            assert config.level == level

    def test_lowercase_log_levels(self):
        """Test that lowercase log levels are accepted."""
        # Note: The config doesn't validate case, but the logging system should handle it
        config = LoggingConfig(level="debug")
        assert config.level == "debug"

    def test_mixed_case_log_levels(self):
        """Test that mixed case log levels are accepted."""
        config = LoggingConfig(level="Debug")
        assert config.level == "Debug"

    def test_invalid_log_level_accepted_by_config(self):
        """Test that invalid log levels are accepted by config (validation happens at runtime)."""
        # The LoggingConfig dataclass doesn't validate log levels
        # Validation happens in LoggingConfigurator._get_log_level()
        config = LoggingConfig(level="INVALID")
        assert config.level == "INVALID"


class TestServiceLevelsConfiguration:
    """Test service-specific log level configuration."""

    def test_empty_service_levels(self):
        """Test that empty service_levels dict works."""
        config = LoggingConfig(service_levels={})
        assert config.service_levels == {}

    def test_single_service_level(self):
        """Test configuring a single service level."""
        config = LoggingConfig(service_levels={"parsers": "DEBUG"})
        assert config.service_levels == {"parsers": "DEBUG"}

    def test_multiple_service_levels(self):
        """Test configuring multiple service levels."""
        service_levels = {
            "parsers": "DEBUG",
            "database": "WARNING",
            "search": "INFO",
            "indexing": "ERROR",
        }
        config = LoggingConfig(service_levels=service_levels)
        assert config.service_levels == service_levels

    def test_service_levels_from_yaml(self, tmp_path):
        """Test loading service levels from YAML."""
        config_file = tmp_path / "mock_config.yaml"
        config_file.write_text("""
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

memory:
  working_memory:
    capacity: 20

events:
  enabled: true

logging:
  service_levels:
    parsers: DEBUG
    database: WARNING
    search: INFO
""")

        config = Config.load(str(config_file))

        assert config.logging.service_levels == {
            "parsers": "DEBUG",
            "database": "WARNING",
            "search": "INFO",
        }
