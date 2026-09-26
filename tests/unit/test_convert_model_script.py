"""Tests for model conversion script."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import sys
from pathlib import Path
from unittest.mock import patch


# Add scripts directory to path for importing
scripts_dir = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

import convert_model


class TestWorkspaceDetection:
    """Tests for workspace detection functionality."""

    def test_detect_workspace_root_with_config(self, tmp_path):
        """Test workspace detection when config file exists."""
        # Create a config directory with default.yaml
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "default.yaml").write_text("# test config")

        with patch("convert_model.Path.cwd", return_value=tmp_path):
            workspace_root = convert_model.detect_workspace_root()
            assert workspace_root == tmp_path

    def test_detect_workspace_root_with_yaml(self, tmp_path):
        """Test workspace detection when agentic-inquiry.yaml exists."""
        (tmp_path / "agentic-inquiry.yaml").write_text("# test config")

        with patch("convert_model.Path.cwd", return_value=tmp_path):
            workspace_root = convert_model.detect_workspace_root()
            assert workspace_root == tmp_path

    def test_detect_workspace_root_fallback(self, tmp_path):
        """Test workspace detection falls back to current directory."""
        with patch("convert_model.Path.cwd", return_value=tmp_path):
            workspace_root = convert_model.detect_workspace_root()
            assert workspace_root == tmp_path


class TestOutputDirectorySetup:
    """Tests for output directory setup."""

    def test_setup_output_directory(self, tmp_path):
        """Test output directory setup creates correct structure."""
        model_id = "sentence-transformers/all-MiniLM-L6-v2"

        output_dir = convert_model.setup_output_directory(tmp_path, model_id)

        # Check that models directory is created
        assert (tmp_path / "models").exists()

        # Check that model-specific directory path is correct
        expected_name = "sentence-transformers--all-MiniLM-L6-v2"
        assert output_dir == tmp_path / "models" / expected_name

    def test_setup_output_directory_safe_name(self, tmp_path):
        """Test that model ID is converted to safe directory name."""
        model_id = "org/model-name"

        output_dir = convert_model.setup_output_directory(tmp_path, model_id)

        # Check that slash is replaced with double dash
        assert output_dir.name == "org--model-name"


class TestCleanup:
    """Tests for cleanup functionality."""

    def test_cleanup_on_failure_removes_directory(self, tmp_path):
        """Test that cleanup removes the output directory."""
        output_dir = tmp_path / "test_model"
        output_dir.mkdir()
        (output_dir / "test_file.txt").write_text("test")

        convert_model.cleanup_on_failure(output_dir)

        assert not output_dir.exists()

    def test_cleanup_on_failure_handles_missing_directory(self, tmp_path):
        """Test that cleanup handles non-existent directory gracefully."""
        output_dir = tmp_path / "nonexistent"

        # Should not raise an exception
        convert_model.cleanup_on_failure(output_dir)
        assert not output_dir.exists()


class TestMainFunction:
    """Tests for main function and CLI."""

    def test_main_with_dry_run(self, tmp_path):
        """Test main function with dry-run flag."""
        with patch("sys.argv", ["convert_model.py", "test-model", "--dry-run"]):
            with patch("convert_model.detect_workspace_root", return_value=tmp_path):
                exit_code = convert_model.main()

        # Dry run should succeed without errors
        assert exit_code == 0

    def test_main_with_verbose_flag(self, tmp_path):
        """Test main function with verbose flag."""
        with patch(
            "sys.argv", ["convert_model.py", "test-model", "--verbose", "--dry-run"]
        ):
            with patch("convert_model.detect_workspace_root", return_value=tmp_path):
                exit_code = convert_model.main()

        # Verbose dry run should succeed without errors
        assert exit_code == 0

    def test_main_with_custom_output_dir(self, tmp_path):
        """Test main function with custom output directory."""
        output_dir = tmp_path / "custom_output"

        with patch(
            "sys.argv",
            [
                "convert_model.py",
                "test-model",
                "--output-dir",
                str(output_dir),
                "--dry-run",
            ],
        ):
            with patch("convert_model.detect_workspace_root", return_value=tmp_path):
                exit_code = convert_model.main()

        assert exit_code == 0
