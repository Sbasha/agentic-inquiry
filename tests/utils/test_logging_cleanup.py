"""Tests for LogCleanupManager."""

import pytest

pytestmark = pytest.mark.integration

import time
from pathlib import Path

from agentic_inquiry.utils.logging_setup import LogCleanupManager


@pytest.fixture
def temp_log_dir(tmp_path):
    """Provide temporary log directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir


class TestCleanupDeletesOldFiles:
    """Test cleanup deletes files older than retention period."""

    def test_deletes_old_log_files(self, temp_log_dir):
        """Test that log files older than retention period are deleted."""
        # Create old log files
        old_log = temp_log_dir / "main.log.1"
        old_log.write_text("old log content")

        # Set modification time to 2 hours ago
        two_hours_ago = time.time() - (2 * 3600)
        old_log.touch()
        old_log.stat()  # Force stat cache update
        import os

        os.utime(old_log, (two_hours_ago, two_hours_ago))

        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 1
        assert not old_log.exists()

    def test_deletes_multiple_old_files(self, temp_log_dir):
        """Test that multiple old log files are deleted."""
        # Create multiple old log files
        old_files = []
        for i in range(3):
            old_log = temp_log_dir / f"main.log.{i}"
            old_log.write_text(f"old log {i}")
            old_files.append(old_log)

        # Set modification time to 2 hours ago for all
        two_hours_ago = time.time() - (2 * 3600)
        import os

        for old_log in old_files:
            os.utime(old_log, (two_hours_ago, two_hours_ago))

        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 3
        for old_log in old_files:
            assert not old_log.exists()

    def test_deletes_error_log_backups(self, temp_log_dir):
        """Test that old error log backups are deleted."""
        # Create old error log backup
        old_error_log = temp_log_dir / "error.log.1"
        old_error_log.write_text("old error log")

        # Set modification time to 2 hours ago
        two_hours_ago = time.time() - (2 * 3600)
        import os

        os.utime(old_error_log, (two_hours_ago, two_hours_ago))

        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 1
        assert not old_error_log.exists()


class TestCleanupPreservesRecentFiles:
    """Test cleanup preserves recent files."""

    def test_preserves_recent_log_files(self, temp_log_dir):
        """Test that recent log files are not deleted."""
        # Create recent log file
        recent_log = temp_log_dir / "main.log"
        recent_log.write_text("recent log content")

        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 0
        assert recent_log.exists()

    def test_preserves_files_within_retention_period(self, temp_log_dir):
        """Test that files within retention period are preserved."""
        # Create log file from 30 minutes ago
        recent_log = temp_log_dir / "main.log.1"
        recent_log.write_text("recent log")

        # Set modification time to 30 minutes ago
        thirty_minutes_ago = time.time() - (0.5 * 3600)
        import os

        os.utime(recent_log, (thirty_minutes_ago, thirty_minutes_ago))

        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 0
        assert recent_log.exists()

    def test_mixed_old_and_recent_files(self, temp_log_dir):
        """Test that only old files are deleted when mixed with recent files."""
        # Create old log file
        old_log = temp_log_dir / "main.log.2"
        old_log.write_text("old log")

        # Create recent log file
        recent_log = temp_log_dir / "main.log.1"
        recent_log.write_text("recent log")

        # Set modification times
        two_hours_ago = time.time() - (2 * 3600)
        thirty_minutes_ago = time.time() - (0.5 * 3600)
        import os

        os.utime(old_log, (two_hours_ago, two_hours_ago))
        os.utime(recent_log, (thirty_minutes_ago, thirty_minutes_ago))

        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 1
        assert not old_log.exists()
        assert recent_log.exists()


class TestHandlingNonLogFiles:
    """Test handling of non-log files (should ignore)."""

    def test_ignores_non_log_files(self, temp_log_dir):
        """Test that non-log files are not deleted."""
        # Create non-log files
        text_file = temp_log_dir / "readme.txt"
        text_file.write_text("readme content")

        config_file = temp_log_dir / "config.yaml"
        config_file.write_text("config content")

        # Set modification time to 2 hours ago
        two_hours_ago = time.time() - (2 * 3600)
        import os

        os.utime(text_file, (two_hours_ago, two_hours_ago))
        os.utime(config_file, (two_hours_ago, two_hours_ago))

        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 0
        assert text_file.exists()
        assert config_file.exists()

    def test_ignores_directories(self, temp_log_dir):
        """Test that directories are not processed."""
        # Create subdirectory
        subdir = temp_log_dir / "subdir"
        subdir.mkdir()

        # Run cleanup
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 0
        assert subdir.exists()

    def test_processes_only_log_files(self, temp_log_dir):
        """Test that only log files are processed for deletion."""
        # Create mix of files
        log_file = temp_log_dir / "main.log.1"
        log_file.write_text("log content")

        text_file = temp_log_dir / "data.txt"
        text_file.write_text("text content")

        # Set both to old
        two_hours_ago = time.time() - (2 * 3600)
        import os

        os.utime(log_file, (two_hours_ago, two_hours_ago))
        os.utime(text_file, (two_hours_ago, two_hours_ago))

        # Run cleanup with 1 hour retention
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 1
        assert not log_file.exists()
        assert text_file.exists()


class TestEmptyDirectoryHandling:
    """Test empty directory handling."""

    def test_handles_empty_directory(self, temp_log_dir):
        """Test that cleanup handles empty directory without errors."""
        # Directory is empty
        assert len(list(temp_log_dir.iterdir())) == 0

        # Run cleanup
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        assert deleted_count == 0

    def test_handles_nonexistent_directory(self, tmp_path):
        """Test that cleanup handles nonexistent directory gracefully."""
        nonexistent_dir = tmp_path / "nonexistent"
        assert not nonexistent_dir.exists()

        # Run cleanup
        deleted_count = LogCleanupManager.cleanup(nonexistent_dir, retention_hours=1)

        assert deleted_count == 0


class TestErrorHandlingPermissionErrors:
    """Test error handling for permission errors."""

    def test_continues_on_permission_error(self, temp_log_dir, monkeypatch, capsys):
        """Test that cleanup continues when file deletion fails."""
        # Create old log files
        log1 = temp_log_dir / "main.log.1"
        log1.write_text("log 1")
        log2 = temp_log_dir / "main.log.2"
        log2.write_text("log 2")

        # Set both to old
        two_hours_ago = time.time() - (2 * 3600)
        import os

        os.utime(log1, (two_hours_ago, two_hours_ago))
        os.utime(log2, (two_hours_ago, two_hours_ago))

        # Mock unlink to raise PermissionError for first file only
        original_unlink = Path.unlink
        call_count = [0]

        def mock_unlink(self, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise PermissionError("Permission denied")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", mock_unlink)

        # Run cleanup
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        # Should have deleted one file (the second one)
        assert deleted_count == 1

        # Check stderr for warning
        captured = capsys.readouterr()
        assert "Warning: Failed to delete log file" in captured.err
        assert "Permission denied" in captured.err

    def test_handles_stat_error_gracefully(self, temp_log_dir, monkeypatch, capsys):
        """Test that cleanup handles stat errors gracefully."""
        # Create old log file
        log_file = temp_log_dir / "main.log.1"
        log_file.write_text("log content")

        # Mock stat to raise OSError
        original_stat = Path.stat

        def mock_stat(self, *args, **kwargs):
            if self.name == "main.log.1":
                raise OSError("Stat failed")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", mock_stat)

        # Run cleanup - should not crash
        deleted_count = LogCleanupManager.cleanup(temp_log_dir, retention_hours=1)

        # File should not be deleted due to stat error
        assert deleted_count == 0

        # Check stderr for warning (stat error is caught by outer exception handler)
        captured = capsys.readouterr()
        assert "Warning: Error during log cleanup" in captured.err
        assert "Stat failed" in captured.err


class TestIsLogFile:
    """Test _is_log_file helper method."""

    def test_recognizes_log_extension(self, tmp_path):
        """Test that .log files are recognized."""
        log_file = tmp_path / "main.log"
        assert LogCleanupManager._is_log_file(log_file)

    def test_recognizes_rotated_log_files(self, tmp_path):
        """Test that .log.N files are recognized."""
        log_file1 = tmp_path / "main.log.1"
        log_file2 = tmp_path / "main.log.2"
        log_file10 = tmp_path / "main.log.10"

        assert LogCleanupManager._is_log_file(log_file1)
        assert LogCleanupManager._is_log_file(log_file2)
        assert LogCleanupManager._is_log_file(log_file10)

    def test_recognizes_error_log_files(self, tmp_path):
        """Test that error.log files are recognized."""
        error_log = tmp_path / "error.log"
        error_log_rotated = tmp_path / "error.log.1"

        assert LogCleanupManager._is_log_file(error_log)
        assert LogCleanupManager._is_log_file(error_log_rotated)

    def test_rejects_non_log_files(self, tmp_path):
        """Test that non-log files are not recognized."""
        text_file = tmp_path / "readme.txt"
        config_file = tmp_path / "config.yaml"
        python_file = tmp_path / "script.py"

        assert not LogCleanupManager._is_log_file(text_file)
        assert not LogCleanupManager._is_log_file(config_file)
        assert not LogCleanupManager._is_log_file(python_file)

    def test_rejects_files_with_log_in_name(self, tmp_path):
        """Test that files with 'log' in name but wrong extension are rejected."""
        log_txt = tmp_path / "log.txt"
        logger_py = tmp_path / "logger.py"

        assert not LogCleanupManager._is_log_file(log_txt)
        assert not LogCleanupManager._is_log_file(logger_py)
