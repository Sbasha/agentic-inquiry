"""Tests for LoggingConfigurator."""

import pytest

pytestmark = pytest.mark.integration

import logging
import logging.handlers
from pathlib import Path

from agent_vault.config import LoggingConfig
from agent_vault.utils.logging_setup import LoggingConfigurator


@pytest.fixture
def temp_log_dir(tmp_path):
    """Provide temporary log directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir


@pytest.fixture
def logging_config(temp_log_dir):
    """Provide test logging configuration."""
    return LoggingConfig(
        directory=str(temp_log_dir),
        level="DEBUG",
        max_bytes=1024,  # Small for testing
        backup_count=3,
        retention_hours=1,
        service_levels={},
        format="%(levelname)s - %(name)s - %(message)s",
        date_format="%Y-%m-%d %H:%M:%S"
    )


@pytest.fixture(autouse=True)
def cleanup_logging():
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
        logger = logging.getLogger(f"agent_vault.{service}")
        logger.setLevel(logging.NOTSET)


class TestHandlerCreation:
    """Test handler creation with temp directory."""
    
    def test_creates_main_and_error_handlers(self, temp_log_dir, logging_config):
        """Test that both main and error handlers are created."""
        main_handler, error_handler = LoggingConfigurator._setup_handlers(
            temp_log_dir, logging_config
        )
        
        assert main_handler is not None
        assert error_handler is not None
        assert isinstance(main_handler, logging.handlers.RotatingFileHandler)
        assert isinstance(error_handler, logging.handlers.RotatingFileHandler)
    
    def test_handlers_added_to_root_logger(self, temp_log_dir, logging_config):
        """Test that handlers are added to root logger."""
        root_logger = logging.getLogger()
        initial_handler_count = len(root_logger.handlers)
        
        LoggingConfigurator._setup_handlers(temp_log_dir, logging_config)
        
        assert len(root_logger.handlers) == initial_handler_count + 2
    
    def test_main_log_file_created(self, temp_log_dir, logging_config):
        """Test that main.log file is created."""
        LoggingConfigurator._setup_handlers(temp_log_dir, logging_config)
        
        main_log = temp_log_dir / "main.log"
        assert main_log.exists()
    
    def test_error_log_file_created(self, temp_log_dir, logging_config):
        """Test that error.log file is created."""
        LoggingConfigurator._setup_handlers(temp_log_dir, logging_config)
        
        error_log = temp_log_dir / "error.log"
        assert error_log.exists()
    
    def test_error_handler_level_set_to_error(self, temp_log_dir, logging_config):
        """Test that error handler only logs ERROR and above."""
        _, error_handler = LoggingConfigurator._setup_handlers(
            temp_log_dir, logging_config
        )
        
        assert error_handler.level == logging.ERROR


class TestLogLevelApplication:
    """Test log level application (global and per-service)."""
    
    def test_applies_global_log_level(self, logging_config):
        """Test that global log level is applied to root logger."""
        logging_config.level = "WARNING"
        
        LoggingConfigurator._apply_log_levels(logging_config)
        
        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING
    
    def test_applies_debug_level(self, logging_config):
        """Test that DEBUG level is applied correctly."""
        logging_config.level = "DEBUG"
        
        LoggingConfigurator._apply_log_levels(logging_config)
        
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG
    
    def test_applies_info_level(self, logging_config):
        """Test that INFO level is applied correctly."""
        logging_config.level = "INFO"
        
        LoggingConfigurator._apply_log_levels(logging_config)
        
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO
    
    def test_applies_error_level(self, logging_config):
        """Test that ERROR level is applied correctly."""
        logging_config.level = "ERROR"
        
        LoggingConfigurator._apply_log_levels(logging_config)
        
        root_logger = logging.getLogger()
        assert root_logger.level == logging.ERROR
    
    def test_applies_critical_level(self, logging_config):
        """Test that CRITICAL level is applied correctly."""
        logging_config.level = "CRITICAL"
        
        LoggingConfigurator._apply_log_levels(logging_config)
        
        root_logger = logging.getLogger()
        assert root_logger.level == logging.CRITICAL


class TestServiceSpecificLevelConfiguration:
    """Test service-specific level configuration."""
    
    def test_applies_service_specific_level(self, logging_config):
        """Test that service-specific log level is applied."""
        logging_config.level = "WARNING"
        logging_config.service_levels = {"parsers": "DEBUG"}
        
        LoggingConfigurator._apply_log_levels(logging_config)
        
        parsers_logger = logging.getLogger("agent_vault.parsers")
        assert parsers_logger.level == logging.DEBUG
    
    def test_applies_multiple_service_levels(self, logging_config):
        """Test that multiple service-specific levels are applied."""
        logging_config.level = "INFO"
        logging_config.service_levels = {
            "parsers": "DEBUG",
            "database": "WARNING",
            "search": "ERROR"
        }
        
        LoggingConfigurator._apply_log_levels(logging_config)
        
        assert logging.getLogger("agent_vault.parsers").level == logging.DEBUG
        assert logging.getLogger("agent_vault.database").level == logging.WARNING
        assert logging.getLogger("agent_vault.search").level == logging.ERROR
    
    def test_service_level_overrides_global_level(self, logging_config):
        """Test that service level overrides global level."""
        logging_config.level = "ERROR"
        logging_config.service_levels = {"parsers": "DEBUG"}
        
        LoggingConfigurator._apply_log_levels(logging_config)
        
        root_logger = logging.getLogger()
        parsers_logger = logging.getLogger("agent_vault.parsers")
        
        assert root_logger.level == logging.ERROR
        assert parsers_logger.level == logging.DEBUG
    
    def test_unspecified_service_uses_global_level(self, logging_config):
        """Test that services without specific level use global level."""
        logging_config.level = "WARNING"
        logging_config.service_levels = {"parsers": "DEBUG"}
        
        LoggingConfigurator._apply_log_levels(logging_config)
        
        # Database logger should inherit from root
        database_logger = logging.getLogger("agent_vault.database")
        # When not explicitly set, logger.level is NOTSET (0)
        # but effective level comes from parent
        assert database_logger.getEffectiveLevel() == logging.WARNING


class TestFormatStringApplication:
    """Test format string application."""
    
    def test_applies_custom_format(self, temp_log_dir, logging_config):
        """Test that custom format string is applied."""
        custom_format = "%(levelname)s - %(message)s"
        logging_config.format = custom_format
        
        main_handler, error_handler = LoggingConfigurator._setup_handlers(
            temp_log_dir, logging_config
        )
        
        assert main_handler.formatter._fmt == custom_format
        assert error_handler.formatter._fmt == custom_format
    
    def test_applies_custom_date_format(self, temp_log_dir, logging_config):
        """Test that custom date format is applied."""
        custom_date_format = "%Y/%m/%d %H:%M"
        logging_config.date_format = custom_date_format
        
        main_handler, error_handler = LoggingConfigurator._setup_handlers(
            temp_log_dir, logging_config
        )
        
        assert main_handler.formatter.datefmt == custom_date_format
        assert error_handler.formatter.datefmt == custom_date_format
    
    def test_applies_both_format_and_date_format(self, temp_log_dir, logging_config):
        """Test that both format and date format are applied together."""
        custom_format = "[%(levelname)s] %(name)s: %(message)s"
        custom_date_format = "%H:%M:%S"
        logging_config.format = custom_format
        logging_config.date_format = custom_date_format
        
        main_handler, _ = LoggingConfigurator._setup_handlers(
            temp_log_dir, logging_config
        )
        
        assert main_handler.formatter._fmt == custom_format
        assert main_handler.formatter.datefmt == custom_date_format


class TestDirectoryCreation:
    """Test directory creation when it doesn't exist."""
    
    def test_creates_directory_if_not_exists(self, tmp_path):
        """Test that log directory is created if it doesn't exist."""
        log_dir = tmp_path / "new_logs"
        assert not log_dir.exists()
        
        config = LoggingConfig(directory=str(log_dir))
        LoggingConfigurator.setup(config)
        
        assert log_dir.exists()
        assert log_dir.is_dir()
    
    def test_creates_nested_directories(self, tmp_path):
        """Test that nested directories are created."""
        log_dir = tmp_path / "level1" / "level2" / "logs"
        assert not log_dir.exists()
        
        config = LoggingConfig(directory=str(log_dir))
        LoggingConfigurator.setup(config)
        
        assert log_dir.exists()
        assert log_dir.is_dir()
    
    def test_works_with_existing_directory(self, temp_log_dir):
        """Test that setup works when directory already exists."""
        assert temp_log_dir.exists()
        
        config = LoggingConfig(directory=str(temp_log_dir))
        LoggingConfigurator.setup(config)
        
        # Should not raise an error
        assert temp_log_dir.exists()


class TestErrorHandling:
    """Test error handling for invalid directory."""
    
    def test_handles_invalid_directory_gracefully(self, tmp_path, capsys):
        """Test that invalid directory is handled gracefully."""
        # Create a file where we want a directory
        invalid_path = tmp_path / "file_not_dir"
        invalid_path.write_text("content")
        
        config = LoggingConfig(directory=str(invalid_path / "logs"))
        
        # Should not raise an error, but print to stderr
        LoggingConfigurator.setup(config)
        
        captured = capsys.readouterr()
        assert "Error: Failed to create log directory" in captured.err
        assert "Continuing without file logging" in captured.err
    
    def test_continues_without_file_logging_on_error(self, tmp_path, capsys):
        """Test that application continues when logging setup fails."""
        # Use an invalid path
        invalid_path = tmp_path / "file_not_dir"
        invalid_path.write_text("content")
        
        config = LoggingConfig(directory=str(invalid_path / "logs"))
        
        # Should not raise an error
        try:
            LoggingConfigurator.setup(config)
            # If we get here, error was handled gracefully
            assert True
        except Exception:
            pytest.fail("LoggingConfigurator.setup() should not raise exceptions")
    
    def test_handles_permission_error_gracefully(self, tmp_path, capsys, monkeypatch):
        """Test that permission errors are handled gracefully."""
        log_dir = tmp_path / "logs"
        
        # Mock mkdir to raise PermissionError
        def mock_mkdir(*args, **kwargs):
            raise PermissionError("Permission denied")
        
        monkeypatch.setattr(Path, "mkdir", mock_mkdir)
        
        config = LoggingConfig(directory=str(log_dir))
        LoggingConfigurator.setup(config)
        
        captured = capsys.readouterr()
        assert "Error: Failed to create log directory" in captured.err
        assert "Permission denied" in captured.err


class TestGetLogLevel:
    """Test _get_log_level helper method."""
    
    def test_converts_debug_string(self):
        """Test that 'DEBUG' string is converted correctly."""
        level = LoggingConfigurator._get_log_level("DEBUG")
        assert level == logging.DEBUG
    
    def test_converts_info_string(self):
        """Test that 'INFO' string is converted correctly."""
        level = LoggingConfigurator._get_log_level("INFO")
        assert level == logging.INFO
    
    def test_converts_warning_string(self):
        """Test that 'WARNING' string is converted correctly."""
        level = LoggingConfigurator._get_log_level("WARNING")
        assert level == logging.WARNING
    
    def test_converts_error_string(self):
        """Test that 'ERROR' string is converted correctly."""
        level = LoggingConfigurator._get_log_level("ERROR")
        assert level == logging.ERROR
    
    def test_converts_critical_string(self):
        """Test that 'CRITICAL' string is converted correctly."""
        level = LoggingConfigurator._get_log_level("CRITICAL")
        assert level == logging.CRITICAL
    
    def test_handles_lowercase_input(self):
        """Test that lowercase input is handled correctly."""
        level = LoggingConfigurator._get_log_level("debug")
        assert level == logging.DEBUG
    
    def test_handles_mixed_case_input(self):
        """Test that mixed case input is handled correctly."""
        level = LoggingConfigurator._get_log_level("DeBuG")
        assert level == logging.DEBUG
    
    def test_returns_info_for_invalid_level(self):
        """Test that invalid level returns INFO with warning."""
        level = LoggingConfigurator._get_log_level("INVALID")
        assert level == logging.INFO
