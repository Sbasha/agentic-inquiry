"""Test logging path resolution relative to storage.root."""

import pytest

pytestmark = pytest.mark.integration

import logging
from pathlib import Path


from agentic_inquiry.config import Config
from agentic_inquiry.utils.logging_setup import LoggingConfigurator


def test_logging_path_relative_to_storage_root():
    """Verify logs are placed under storage.root when using relative path."""
    # Load default config
    config = Config.load()

    # Setup logging
    LoggingConfigurator.setup(config.logging)

    # Get the actual log directory from handlers
    root_logger = logging.getLogger()
    log_paths = []
    for handler in root_logger.handlers:
        if hasattr(handler, "baseFilename"):
            log_path = Path(handler.baseFilename)
            log_paths.append(log_path)

    assert len(log_paths) > 0, "No log handlers found"

    # Verify logs are under storage.root
    log_dir = log_paths[0].parent

    # Expected path: storage.root / logging.directory
    storage_root = Path(config.storage.root)
    if not storage_root.is_absolute():
        storage_root = Path.cwd() / storage_root
    expected_log_dir = storage_root / config.logging.directory

    assert log_dir.resolve() == expected_log_dir.resolve(), (
        f"Logs should be under storage.root. "
        f"Expected: {expected_log_dir}, Got: {log_dir}"
    )

    # Verify it's under .agentic-inquiry
    assert ".agentic-inquiry" in str(log_dir), (
        f"Logs should be under .agentic-inquiry, got: {log_dir}"
    )


def test_default_logging_path():
    """Verify default config places logs under .agentic-inquiry/logs."""
    # Load default config
    config = Config.load()

    # Setup logging
    LoggingConfigurator.setup(config.logging)

    # Get the actual log directory from handlers
    root_logger = logging.getLogger()
    log_paths = []
    for handler in root_logger.handlers:
        if hasattr(handler, "baseFilename"):
            log_path = Path(handler.baseFilename)
            log_paths.append(log_path)

    assert len(log_paths) > 0, "No log handlers found"

    # Verify logs are under .agentic-inquiry/logs
    log_dir = log_paths[0].parent

    # Expected path: .agentic-inquiry/logs
    storage_root = Path(config.storage.root)
    if not storage_root.is_absolute():
        storage_root = Path.cwd() / storage_root
    expected_log_dir = storage_root / config.logging.directory

    assert log_dir.resolve() == expected_log_dir.resolve(), (
        f"Default logs should be under storage.root. "
        f"Expected: {expected_log_dir}, Got: {log_dir}"
    )

    # Verify it's under .agentic-inquiry
    assert ".agentic-inquiry" in str(log_dir), (
        f"Logs should be under .agentic-inquiry, got: {log_dir}"
    )
