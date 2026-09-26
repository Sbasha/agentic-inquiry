"""Test logging path resolution relative to storage.root."""

import pytest

pytestmark = pytest.mark.integration

import logging
from pathlib import Path


from agentic_inquiry.config import Config
from agentic_inquiry.utils.logging_setup import LoggingConfigurator


@pytest.fixture(autouse=True)
def restore_root_handlers():
    """Remove and close the file handlers LoggingConfigurator.setup adds."""
    root_logger = logging.getLogger()
    before = list(root_logger.handlers)
    yield
    for handler in root_logger.handlers[:]:
        if handler not in before:
            root_logger.removeHandler(handler)
            handler.close()


def test_logging_path_relative_to_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The default storage root is relative to the cwd.
    monkeypatch.chdir(tmp_path)
    """Verify logs are placed under storage.root when using relative path."""
    # Load default config
    config = Config.load()
    
    # Setup logging
    LoggingConfigurator.setup(config.logging)
    
    # Get the actual log directory from handlers
    root_logger = logging.getLogger()
    # pytest's own log-file handler also carries a baseFilename (/dev/null).
    log_paths = [
        Path(handler.baseFilename)
        for handler in root_logger.handlers
        if getattr(handler, "baseFilename", "").endswith("main.log")
    ]
    
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





def test_default_logging_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The default storage root is relative to the cwd.
    monkeypatch.chdir(tmp_path)
    """Verify default config places logs under .agentic-inquiry/logs."""
    # Load default config
    config = Config.load()
    
    # Setup logging
    LoggingConfigurator.setup(config.logging)
    
    # Get the actual log directory from handlers
    root_logger = logging.getLogger()
    # pytest's own log-file handler also carries a baseFilename (/dev/null).
    log_paths = [
        Path(handler.baseFilename)
        for handler in root_logger.handlers
        if getattr(handler, "baseFilename", "").endswith("main.log")
    ]
    
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
