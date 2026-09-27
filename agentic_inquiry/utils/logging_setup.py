"""Logging configuration and setup for the agentic-inquiry library."""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional, Tuple

from agentic_inquiry.config import Config, LoggingConfig


class LoggingConfigurator:
    """Configures file-based logging for the application."""

    @staticmethod
    def setup(config: Optional[LoggingConfig] = None) -> None:
        """
        Configure logging based on provided or loaded configuration.

        Args:
            config: LoggingConfig instance. If None, loads from Config.load()
        """
        try:
            # Load config if not provided
            full_config = None
            if config is None:
                full_config = Config.load()
                config = full_config.logging

            # Resolve log directory path
            log_dir = Path(config.directory)
            if not log_dir.is_absolute():
                # Make it relative to storage.root (like other storage components)
                if full_config is None:
                    full_config = Config.load()
                storage_root = Path(full_config.storage.root)
                if not storage_root.is_absolute():
                    storage_root = Path.cwd() / storage_root
                log_dir = storage_root / log_dir

            # Create log directory if it doesn't exist
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(
                    f"Error: Failed to create log directory {log_dir}: {e}",
                    file=sys.stderr,
                )
                print("Continuing without file logging", file=sys.stderr)
                return

            # Set up handlers
            LoggingConfigurator._setup_handlers(log_dir, config)

            # Apply log levels
            LoggingConfigurator._apply_log_levels(config)

            # Perform initial cleanup
            deleted_count = LogCleanupManager.cleanup(log_dir, config.retention_hours)
            if deleted_count > 0:
                logging.info(f"Cleaned up {deleted_count} old log file(s)")

        except Exception as e:
            print(f"Error: Failed to configure logging: {e}", file=sys.stderr)
            print("Continuing without file logging", file=sys.stderr)

    @staticmethod
    def _setup_handlers(
        log_dir: Path, config: LoggingConfig
    ) -> Tuple[logging.Handler, logging.Handler]:
        """
        Create and configure main and error log handlers.

        Args:
            log_dir: Directory for log files
            config: LoggingConfig instance with handler settings

        Returns:
            Tuple of (main_handler, error_handler)
        """
        # Create formatter
        formatter = logging.Formatter(fmt=config.format, datefmt=config.date_format)

        # Subclass RotatingFileHandler to suppress FileNotFoundError during
        # log rotation when multiple CLI processes rotate simultaneously (#54).
        class _SafeRotatingHandler(logging.handlers.RotatingFileHandler):
            def doRollover(self) -> None:
                try:
                    super().doRollover()
                except FileNotFoundError:
                    pass

        # Create main log handler (all logs at configured level)
        main_log_path = log_dir / "main.log"
        main_handler = _SafeRotatingHandler(
            filename=str(main_log_path),
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
        main_handler.setFormatter(formatter)

        # Create error log handler (ERROR and CRITICAL only)
        error_log_path = log_dir / "error.log"
        error_handler = _SafeRotatingHandler(
            filename=str(error_log_path),
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
        error_handler.setFormatter(formatter)
        error_handler.setLevel(logging.ERROR)

        # Add handlers to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(main_handler)
        root_logger.addHandler(error_handler)

        return main_handler, error_handler

    @staticmethod
    def _apply_log_levels(config: LoggingConfig) -> None:
        """
        Apply global and per-service log levels.

        Args:
            config: LoggingConfig instance with level settings
        """
        # Set root logger level
        root_logger = logging.getLogger()
        root_level = LoggingConfigurator._get_log_level(config.level)
        root_logger.setLevel(root_level)

        # Apply service-specific log levels
        for service_name, level_str in config.service_levels.items():
            # Construct full logger name (e.g., "agentic_inquiry.parsers")
            logger_name = f"agentic_inquiry.{service_name}"
            service_logger = logging.getLogger(logger_name)
            service_level = LoggingConfigurator._get_log_level(level_str)
            service_logger.setLevel(service_level)

    @staticmethod
    def _get_log_level(level_str: str) -> int:
        """
        Convert string log level to logging constant.

        Args:
            level_str: Log level as string (DEBUG, INFO, WARNING, ERROR, CRITICAL)

        Returns:
            Logging level constant (e.g., logging.INFO)
        """
        level_str_upper = level_str.upper()
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }

        if level_str_upper not in level_map:
            print(
                f"Warning: Invalid log level '{level_str}', falling back to INFO",
                file=sys.stderr,
            )
            return logging.INFO

        return level_map[level_str_upper]


class LogCleanupManager:
    """Manages cleanup of old log files."""

    @staticmethod
    def cleanup(log_dir: Path, retention_hours: int) -> int:
        """
        Remove log files older than retention period.

        Args:
            log_dir: Directory containing log files
            retention_hours: Maximum age of log files in hours

        Returns:
            Number of files deleted
        """
        import time

        if not log_dir.exists():
            return 0

        deleted_count = 0
        current_time = time.time()
        retention_seconds = retention_hours * 3600

        try:
            for file_path in log_dir.iterdir():
                if not file_path.is_file():
                    continue

                # Check if it's a log file
                if not LogCleanupManager._is_log_file(file_path):
                    continue

                # Check file age
                try:
                    file_age = current_time - file_path.stat().st_mtime
                    if file_age > retention_seconds:
                        file_path.unlink()
                        deleted_count += 1
                except Exception as e:
                    print(
                        f"Warning: Failed to delete log file {file_path}: {e}",
                        file=sys.stderr,
                    )
        except Exception as e:
            print(f"Warning: Error during log cleanup: {e}", file=sys.stderr)

        return deleted_count

    @staticmethod
    def _is_log_file(path: Path) -> bool:
        """
        Check if file is a log file (*.log or *.log.*).

        Args:
            path: File path to check

        Returns:
            True if file matches log file pattern
        """
        name = path.name
        # Match *.log or *.log.* (e.g., main.log, main.log.1)
        return name.endswith(".log") or ".log." in name
