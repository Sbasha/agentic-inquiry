"""Integration tests for the workspace logging system."""

import pytest


import logging
import os
import time
from pathlib import Path
from typing import Generator

import yaml

from agentic_inquiry.config import Config, LoggingConfig
from agentic_inquiry.utils.logging_setup import LogCleanupManager, LoggingConfigurator


@pytest.fixture
def temp_log_dir(tmp_path) -> Path:
    """Provide temporary log directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir


@pytest.fixture
def temp_config_file(tmp_path) -> Path:
    """Provide temporary config file path."""
    return tmp_path / "mock_config.yaml"


def create_minimal_config(tmp_path: Path, logging_config: dict) -> dict:
    """Create minimal valid configuration with logging section."""
    return {
        "storage": {
            "root": str(tmp_path / "data"),
            "lancedb": {"path": "lancedb"},
            "file_tracker": {"path": "file_tracker.db"},
            "document_cache": {"enabled": False, "path": "document_cache"}
        },
        "cache": {
            "document_cache": {"max_size": 1000}
        },
        "search": {
            "default_limit": 10,
            "max_limit": 100
        },
        "embeddings": {
            "default_provider": "sentence_transformers"
        },
        "parsers": {},
        "logging": logging_config
    }


@pytest.fixture(autouse=True)
def cleanup_logging() -> Generator[None, None, None]:
    """Clean up logging handlers after each test."""
    yield
    # Remove all handlers from root logger
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)
    
    # Reset log levels for common loggers
    root_logger.setLevel(logging.WARNING)
    for service in ["parsers", "database", "search", "indexing", "embeddings", "caching"]:
        logger = logging.getLogger(f"agentic_inquiry.{service}")
        logger.setLevel(logging.NOTSET)


@pytest.fixture(autouse=True)
def cleanup_env_vars() -> Generator[None, None, None]:
    """Clean up environment variables after each test."""
    # Store original values
    original_env = {}
    env_vars = [
        "AI_LOGGING_DIRECTORY",
        "AI_LOGGING_LEVEL",
        "AI_LOGGING_MAX_BYTES",
        "AI_LOGGING_RETENTION_HOURS",
        "AI_LOGGING_SERVICE_LEVELS_PARSERS",
        "AI_LOGGING_SERVICE_LEVELS_DATABASE",
    ]
    
    for var in env_vars:
        if var in os.environ:
            original_env[var] = os.environ[var]
    
    yield
    
    # Restore original values
    for var in env_vars:
        if var in original_env:
            os.environ[var] = original_env[var]
        elif var in os.environ:
            del os.environ[var]


class TestEndToEndLogging:
    """Test end-to-end: write logs to configured directory."""
    
    def test_writes_logs_to_configured_directory(self, temp_log_dir):
        """Test that logs are written to the configured directory."""
        config = LoggingConfig(
            directory=str(temp_log_dir),
            level="INFO"
        )
        LoggingConfigurator.setup(config)
        
        # Write some log messages
        logger = logging.getLogger("agentic_inquiry.test")
        logger.info("Test info message")
        logger.warning("Test warning message")
        logger.error("Test error message")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        # Verify main log exists and contains messages
        main_log = temp_log_dir / "main.log"
        assert main_log.exists()
        
        content = main_log.read_text()
        assert "Test info message" in content
        assert "Test warning message" in content
        assert "Test error message" in content
    
    def test_creates_both_main_and_error_logs(self, temp_log_dir):
        """Test that both main.log and error.log are created."""
        config = LoggingConfig(directory=str(temp_log_dir))
        LoggingConfigurator.setup(config)
        
        # Write a log message to trigger file creation
        logger = logging.getLogger("agentic_inquiry.test")
        logger.error("Test error")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        assert (temp_log_dir / "main.log").exists()
        assert (temp_log_dir / "error.log").exists()


class TestMainAndErrorLogSeparation:
    """Test main and error log separation (ERROR goes to both, INFO only to main)."""
    
    def test_info_only_in_main_log(self, temp_log_dir):
        """Test that INFO messages only appear in main log."""
        config = LoggingConfig(
            directory=str(temp_log_dir),
            level="INFO"
        )
        LoggingConfigurator.setup(config)
        
        logger = logging.getLogger("agentic_inquiry.test")
        logger.info("Info message")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        main_content = (temp_log_dir / "main.log").read_text()
        error_content = (temp_log_dir / "error.log").read_text()
        
        assert "Info message" in main_content
        assert "Info message" not in error_content
    
    def test_warning_only_in_main_log(self, temp_log_dir):
        """Test that WARNING messages only appear in main log."""
        config = LoggingConfig(
            directory=str(temp_log_dir),
            level="INFO"
        )
        LoggingConfigurator.setup(config)
        
        logger = logging.getLogger("agentic_inquiry.test")
        logger.warning("Warning message")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        main_content = (temp_log_dir / "main.log").read_text()
        error_content = (temp_log_dir / "error.log").read_text()
        
        assert "Warning message" in main_content
        assert "Warning message" not in error_content
    
    def test_error_in_both_logs(self, temp_log_dir):
        """Test that ERROR messages appear in both logs."""
        config = LoggingConfig(
            directory=str(temp_log_dir),
            level="INFO"
        )
        LoggingConfigurator.setup(config)
        
        logger = logging.getLogger("agentic_inquiry.test")
        logger.error("Error message")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        main_content = (temp_log_dir / "main.log").read_text()
        error_content = (temp_log_dir / "error.log").read_text()
        
        assert "Error message" in main_content
        assert "Error message" in error_content
    
    def test_critical_in_both_logs(self, temp_log_dir):
        """Test that CRITICAL messages appear in both logs."""
        config = LoggingConfig(
            directory=str(temp_log_dir),
            level="INFO"
        )
        LoggingConfigurator.setup(config)
        
        logger = logging.getLogger("agentic_inquiry.test")
        logger.critical("Critical message")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        main_content = (temp_log_dir / "main.log").read_text()
        error_content = (temp_log_dir / "error.log").read_text()
        
        assert "Critical message" in main_content
        assert "Critical message" in error_content


class TestLogRotation:
    """Test log rotation when file exceeds max_bytes."""
    
    def test_rotates_when_exceeding_max_bytes(self, temp_log_dir):
        """Test that log file rotates when exceeding max_bytes."""
        # Use very small max_bytes to trigger rotation
        config = LoggingConfig(
            directory=str(temp_log_dir),
            level="INFO",
            max_bytes=100,  # Very small to trigger rotation
            backup_count=3
        )
        LoggingConfigurator.setup(config)
        
        logger = logging.getLogger("agentic_inquiry.test")
        
        # Write enough messages to exceed max_bytes
        for i in range(20):
            logger.info(f"This is a test message number {i} with some content to fill space")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        # Check that rotation occurred
        main_log = temp_log_dir / "main.log"
        rotated_log = temp_log_dir / "main.log.1"
        
        assert main_log.exists()
        # At least one rotation should have occurred
        assert rotated_log.exists() or main_log.stat().st_size < 200
    
    def test_maintains_backup_count(self, temp_log_dir):
        """Test that backup_count is respected during rotation."""
        config = LoggingConfig(
            directory=str(temp_log_dir),
            level="INFO",
            max_bytes=50,  # Very small
            backup_count=2
        )
        LoggingConfigurator.setup(config)
        
        logger = logging.getLogger("agentic_inquiry.test")
        
        # Write many messages to trigger multiple rotations
        for i in range(50):
            logger.info(f"Message {i} with content to fill the log file")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        # Count backup files
        backup_files = list(temp_log_dir.glob("main.log.*"))
        # Should have at most backup_count files
        assert len(backup_files) <= 2


class TestLogCleanup:
    """Test cleanup after retention period expires."""
    
    def test_cleanup_deletes_old_files(self, temp_log_dir):
        """Test that cleanup deletes files older than retention period."""
        # Create old log files
        old_file1 = temp_log_dir / "main.log.1"
        old_file2 = temp_log_dir / "error.log.1"
        old_file1.write_text("old content")
        old_file2.write_text("old error content")
        
        # Set modification time to 2 hours ago
        two_hours_ago = time.time() - (2 * 3600)
        os.utime(old_file1, (two_hours_ago, two_hours_ago))
        os.utime(old_file2, (two_hours_ago, two_hours_ago))
        
        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)
        
        assert deleted_count == 2
        assert not old_file1.exists()
        assert not old_file2.exists()
    
    def test_cleanup_preserves_recent_files(self, temp_log_dir):
        """Test that cleanup preserves files within retention period."""
        # Create recent log files
        recent_file = temp_log_dir / "main.log"
        recent_file.write_text("recent content")
        
        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)
        
        assert deleted_count == 0
        assert recent_file.exists()
    
    def test_cleanup_runs_on_initialization(self, temp_log_dir):
        """Test that cleanup runs when LoggingConfigurator.setup() is called."""
        # Create old log file
        old_file = temp_log_dir / "old.log.1"
        old_file.write_text("old content")
        
        # Set modification time to 2 hours ago
        two_hours_ago = time.time() - (2 * 3600)
        os.utime(old_file, (two_hours_ago, two_hours_ago))
        
        # Setup logging with 1 hour retention
        config = LoggingConfig(
            directory=str(temp_log_dir),
            retention_hours=1
        )
        LoggingConfigurator.setup(config)
        
        # Old file should be deleted
        assert not old_file.exists()


class TestPerServiceLogLevels:
    """Test per-service log levels work correctly."""
    
    def test_service_specific_level_applied(self, temp_log_dir):
        """Test that service-specific log levels are applied correctly."""
        config = LoggingConfig(
            directory=str(temp_log_dir),
            level="WARNING",  # Global level
            service_levels={
                "parsers": "DEBUG"  # Service-specific level
            }
        )
        LoggingConfigurator.setup(config)
        
        # Test parsers logger (should log DEBUG)
        parsers_logger = logging.getLogger("agentic_inquiry.parsers")
        parsers_logger.debug("Parser debug message")
        
        # Test database logger (should use global WARNING)
        database_logger = logging.getLogger("agentic_inquiry.database")
        database_logger.debug("Database debug message")
        database_logger.warning("Database warning message")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        main_content = (temp_log_dir / "main.log").read_text()
        
        # Parser debug should be logged
        assert "Parser debug message" in main_content
        
        # Database debug should NOT be logged (below WARNING)
        assert "Database debug message" not in main_content
        
        # Database warning should be logged
        assert "Database warning message" in main_content
    
    def test_multiple_service_levels(self, temp_log_dir):
        """Test that multiple service-specific levels work together."""
        config = LoggingConfig(
            directory=str(temp_log_dir),
            level="INFO",
            service_levels={
                "parsers": "DEBUG",
                "database": "ERROR",
                "search": "WARNING"
            }
        )
        LoggingConfigurator.setup(config)
        
        # Test each service
        logging.getLogger("agentic_inquiry.parsers").debug("Parser debug")
        logging.getLogger("agentic_inquiry.database").warning("Database warning")
        logging.getLogger("agentic_inquiry.database").error("Database error")
        logging.getLogger("agentic_inquiry.search").info("Search info")
        logging.getLogger("agentic_inquiry.search").warning("Search warning")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        main_content = (temp_log_dir / "main.log").read_text()
        
        assert "Parser debug" in main_content
        assert "Database warning" not in main_content  # Below ERROR
        assert "Database error" in main_content
        assert "Search info" not in main_content  # Below WARNING
        assert "Search warning" in main_content


class TestConfigLoadingFromYAML:
    """Test config loading from YAML with logging section."""
    
    def test_loads_logging_config_from_yaml(self, temp_config_file, tmp_path):
        """Test that logging configuration is loaded from YAML file."""
        log_dir = tmp_path / "yaml_logs"
        
        config_data = create_minimal_config(tmp_path, {
            "directory": str(log_dir),
            "level": "DEBUG",
            "max_bytes": 5242880,
            "backup_count": 3,
            "retention_hours": 48,
            "service_levels": {
                "parsers": "INFO",
                "database": "WARNING"
            }
        })
        
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        
        # Load config
        config = Config.load(config_path=temp_config_file)
        
        # Verify logging config
        assert config.logging.directory == str(log_dir)
        assert config.logging.level == "DEBUG"
        assert config.logging.max_bytes == 5242880
        assert config.logging.backup_count == 3
        assert config.logging.retention_hours == 48
        assert config.logging.service_levels == {
            "parsers": "INFO",
            "database": "WARNING"
        }
    
    def test_uses_logging_config_from_yaml(self, temp_config_file, tmp_path):
        """Test that logging system uses configuration loaded from YAML."""
        log_dir = tmp_path / "yaml_logs"
        
        config_data = create_minimal_config(tmp_path, {
            "directory": str(log_dir),
            "level": "WARNING",
            "service_levels": {
                "parsers": "DEBUG"
            }
        })
        
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        
        # Load and apply config
        config = Config.load(config_path=temp_config_file)
        LoggingConfigurator.setup(config.logging)
        
        # Test logging
        logging.getLogger("agentic_inquiry.parsers").debug("Parser debug")
        logging.getLogger("agentic_inquiry.database").info("Database info")
        logging.getLogger("agentic_inquiry.database").warning("Database warning")
        
        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()
        
        # Verify logs were written to correct directory
        assert log_dir.exists()
        main_log = log_dir / "main.log"
        assert main_log.exists()
        
        content = main_log.read_text()
        assert "Parser debug" in content
        assert "Database info" not in content  # Below WARNING
        assert "Database warning" in content


class TestEnvironmentVariableOverrides:
    """Test environment variable overrides."""
    
    def test_env_var_overrides_directory(self, tmp_path, temp_config_file):
        """Test that AI_LOGGING_DIRECTORY overrides config."""
        env_log_dir = tmp_path / "env_logs"
        config_log_dir = tmp_path / "config_logs"
        
        # Set environment variable
        os.environ["AI_LOGGING_DIRECTORY"] = str(env_log_dir)
        
        config_data = create_minimal_config(tmp_path, {
            "directory": str(config_log_dir)
        })
        
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        
        config = Config.load(config_path=temp_config_file)
        
        # Environment variable should override
        assert config.logging.directory == str(env_log_dir)
    
    def test_env_var_overrides_level(self, tmp_path, temp_config_file):
        """Test that AI_LOGGING_LEVEL overrides config."""
        os.environ["AI_LOGGING_LEVEL"] = "ERROR"
        
        config_data = create_minimal_config(tmp_path, {
            "directory": str(tmp_path / "logs"),
            "level": "DEBUG"
        })
        
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        
        config = Config.load(config_path=temp_config_file)
        
        assert config.logging.level == "ERROR"
    
    def test_env_var_overrides_max_bytes(self, tmp_path, temp_config_file):
        """Test that AI_LOGGING_MAX_BYTES overrides config."""
        os.environ["AI_LOGGING_MAX_BYTES"] = "20971520"
        
        config_data = create_minimal_config(tmp_path, {
            "directory": str(tmp_path / "logs"),
            "max_bytes": 10485760
        })
        
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        
        config = Config.load(config_path=temp_config_file)
        
        assert config.logging.max_bytes == 20971520
    
    def test_env_var_overrides_retention_hours(self, tmp_path, temp_config_file):
        """Test that AI_LOGGING_RETENTION_HOURS overrides config."""
        os.environ["AI_LOGGING_RETENTION_HOURS"] = "72"
        
        config_data = create_minimal_config(tmp_path, {
            "directory": str(tmp_path / "logs"),
            "retention_hours": 24
        })
        
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        
        config = Config.load(config_path=temp_config_file)
        
        assert config.logging.retention_hours == 72
    
    def test_env_var_overrides_service_levels(self, tmp_path, temp_config_file):
        """Test that AI_LOGGING_SERVICE_LEVELS_* overrides config."""
        os.environ["AI_LOGGING_SERVICE_LEVELS_PARSERS"] = "ERROR"
        os.environ["AI_LOGGING_SERVICE_LEVELS_DATABASE"] = "CRITICAL"
        
        config_data = create_minimal_config(tmp_path, {
            "directory": str(tmp_path / "logs"),
            "service_levels": {
                "parsers": "DEBUG",
                "search": "INFO"
            }
        })
        
        with open(temp_config_file, "w") as f:
            yaml.dump(config_data, f)
        
        config = Config.load(config_path=temp_config_file)
        
        # Environment variables should override
        assert config.logging.service_levels["parsers"] == "ERROR"
        assert config.logging.service_levels["database"] == "CRITICAL"
        # Original value should be preserved
        assert config.logging.service_levels["search"] == "INFO"
