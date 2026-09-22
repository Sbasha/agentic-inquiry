"""Tests for environment resolution module."""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from agentic_inquiry.cli.env_resolver import (
    resolve_environment,
    is_test_environment,
    get_data_dir,
    get_global_dir,
    get_local_dir,
    get_env_config_path,
    load_env_registry,
    list_environments,
    DATA_DIR_NAME,
    GLOBAL_DIR_NAME,
)


class TestIsTestEnvironment:
    """Tests for is_test_environment function."""

    def test_ai_test_prefix(self):
        """Test environments with ai-test prefix are detected as test."""
        assert is_test_environment("ai-test") is True
        assert is_test_environment("ai-test-postgres") is True
        assert is_test_environment("ai-test-123") is True

    def test_plain_test(self):
        """Test plain 'test' is detected as test environment."""
        assert is_test_environment("test") is True

    def test_test_in_name(self):
        """Test environments with 'test' in name are detected."""
        assert is_test_environment("my-test-env") is True
        assert is_test_environment("testing") is True

    def test_production_environments(self):
        """Test production environments are not detected as test."""
        assert is_test_environment("ai") is False
        assert is_test_environment("ai-prod") is False
        assert is_test_environment("gcp-prod") is False
        assert is_test_environment("production") is False

    def test_prod_with_test_in_name(self):
        """Test that 'prod' overrides 'test' in name."""
        assert is_test_environment("test-prod") is False
        assert is_test_environment("prod-test") is False



class TestGetDataDir:
    """Tests for get_data_dir and get_global_dir functions."""

    def test_default_returns_global(self):
        """Default (no workspace) returns global ~/.agentic-inquiry/ directory."""
        data_dir = get_data_dir()
        assert data_dir == Path.home() / GLOBAL_DIR_NAME

    def test_custom_workspace(self, tmp_path):
        """Custom workspace returns workspace/.agentic-inquiry/ for test isolation."""
        data_dir = get_data_dir(tmp_path)
        assert data_dir == tmp_path / GLOBAL_DIR_NAME

    def test_global_dir(self):
        """get_global_dir returns ~/.agentic-inquiry/."""
        assert get_global_dir() == Path.home() / GLOBAL_DIR_NAME

    def test_global_dir_ai_home_override(self, tmp_path):
        """INQUIRY_HOME env var overrides global dir."""
        custom = tmp_path / "custom-ai"
        with patch.dict(os.environ, {"INQUIRY_HOME": str(custom)}):
            assert get_global_dir() == custom

    def test_local_dir(self, tmp_path):
        """get_local_dir returns workspace/.agentic-inquiry/."""
        assert get_local_dir(tmp_path) == tmp_path / ".agentic-inquiry"


class TestGetEnvConfigPath:
    """Tests for get_env_config_path function."""

    def test_env_config_path(self, tmp_path):
        """Config path follows convention."""
        config_path = get_env_config_path("my-env", tmp_path)
        assert (
            config_path == tmp_path / DATA_DIR_NAME / "envs" / "my-env" / "config.yaml"
        )


class TestLoadEnvRegistry:
    """Tests for load_env_registry function."""

    def test_missing_registry(self, tmp_path):
        """Missing registry returns empty dict."""
        result = load_env_registry(tmp_path)
        assert result == {}

    def test_valid_registry(self, tmp_path):
        """Valid registry is loaded."""
        data_dir = tmp_path / DATA_DIR_NAME
        data_dir.mkdir(parents=True)
        registry_path = data_dir / "env-registry.json"

        registry_data = {
            "environments": [{"name": "test-env"}],
            "active_environment": "test-env",
        }
        registry_path.write_text(json.dumps(registry_data))

        result = load_env_registry(tmp_path)
        assert result == registry_data

    def test_invalid_json(self, tmp_path):
        """Invalid JSON returns empty dict."""
        data_dir = tmp_path / DATA_DIR_NAME
        data_dir.mkdir(parents=True)
        registry_path = data_dir / "env-registry.json"
        registry_path.write_text("not valid json")

        result = load_env_registry(tmp_path)
        assert result == {}


class TestResolveEnvironment:
    """Tests for resolve_environment function."""

    def test_ai_config_env_var(self, tmp_path):
        """INQUIRY_CONFIG env var takes priority."""
        config_file = tmp_path / "custom.yaml"
        config_file.write_text("storage:\n  root: test")

        with patch.dict(os.environ, {"INQUIRY_CONFIG": str(config_file)}):
            env = resolve_environment(tmp_path)
            assert env.source == "env_var"
            assert env.config_path == config_file

    def test_ai_env_env_var(self, tmp_path):
        """INQUIRY_ENV env var selects named environment."""
        # Create env config
        data_dir = tmp_path / DATA_DIR_NAME
        env_config = data_dir / "envs" / "my-env" / "config.yaml"
        env_config.parent.mkdir(parents=True)
        env_config.write_text("storage:\n  root: test")

        with patch.dict(os.environ, {"INQUIRY_ENV": "my-env"}, clear=False):
            # Clear INQUIRY_CONFIG if set
            os.environ.pop("INQUIRY_CONFIG", None)
            env = resolve_environment(tmp_path)
            assert env.name == "my-env"
            assert env.source == "env_var"

    def test_registry_active_env(self, tmp_path):
        """Active environment from registry is used."""
        data_dir = tmp_path / DATA_DIR_NAME
        data_dir.mkdir(parents=True)

        # Create registry
        registry = {
            "environments": [{"name": "prod-env"}],
            "active_environment": "prod-env",
        }
        (data_dir / "env-registry.json").write_text(json.dumps(registry))

        # Create env config
        env_config = data_dir / "envs" / "prod-env" / "config.yaml"
        env_config.parent.mkdir(parents=True)
        env_config.write_text("storage:\n  root: test")

        # Clear env vars
        with patch.dict(os.environ, {}, clear=True):
            env = resolve_environment(tmp_path)
            assert env.name == "prod-env"
            assert env.source == "registry"

    def test_default_fallback(self, tmp_path):
        """Falls back to default when nothing configured."""
        with patch.dict(os.environ, {"INQUIRY_HOME": str(tmp_path)}, clear=True):
            env = resolve_environment(tmp_path)
            assert env.name == "default"
            assert env.source == "default"
            assert env.config_path is None


class TestListEnvironments:
    """Tests for list_environments function."""

    def test_no_envs_directory(self, tmp_path):
        """Returns empty list when no envs directory."""
        result = list_environments(tmp_path)
        assert result == []

    def test_lists_environments(self, tmp_path):
        """Lists all environment directories."""
        data_dir = tmp_path / DATA_DIR_NAME
        envs_dir = data_dir / "envs"

        # Create some envs
        (envs_dir / "env1" / "config.yaml").parent.mkdir(parents=True)
        (envs_dir / "env1" / "config.yaml").write_text("test: 1")
        (envs_dir / "env2").mkdir(parents=True)  # No config

        # Set active
        (data_dir / "env-registry.json").write_text(
            json.dumps({"active_environment": "env1"})
        )

        result = list_environments(tmp_path)
        assert len(result) == 2

        env1 = next(e for e in result if e["name"] == "env1")
        assert env1["config_exists"] is True
        assert env1["is_active"] is True

        env2 = next(e for e in result if e["name"] == "env2")
        assert env2["config_exists"] is False
        assert env2["is_active"] is False


class TestEnvironmentDotenv:
    """Tests for .agentic-inquiry/envs/<name>/.env loading."""

    def test_parse_skips_comments_and_blanks(self) -> None:
        from agentic_inquiry.cli.env_resolver import parse_dotenv_lines

        parsed = parse_dotenv_lines(
            "# comment\n\nFOO=bar\n# INQUIRY_EMBEDDING_DEVICE=cpu\nBAZ='quoted'\n"
        )
        assert parsed == {"FOO": "bar", "BAZ": "quoted"}

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        from agentic_inquiry.cli.env_resolver import load_environment_dotenv

        environ: dict[str, str] = {}
        load_environment_dotenv(tmp_path, environ=environ)
        assert environ == {}

    def test_sets_unset_keys_only(self, tmp_path: Path) -> None:
        from agentic_inquiry.cli.env_resolver import load_environment_dotenv

        (tmp_path / ".env").write_text("FOO=fromfile\nBAR=set\n", encoding="utf-8")
        environ = {"FOO": "fromshell"}
        load_environment_dotenv(tmp_path, environ=environ)
        assert environ["FOO"] == "fromshell"
        assert environ["BAR"] == "set"

    def test_values_are_not_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from agentic_inquiry.cli.env_resolver import load_environment_dotenv

        hidden = "must-not-appear-in-logs"
        (tmp_path / ".env").write_text(f"FOO={hidden}\n", encoding="utf-8")
        with caplog.at_level("DEBUG"):
            load_environment_dotenv(tmp_path, environ={})
        assert hidden not in caplog.text

    def test_symlink_escape_is_not_loaded(self, tmp_path: Path) -> None:
        from agentic_inquiry.cli.env_resolver import load_environment_dotenv

        outside = tmp_path / "outside.env"
        outside.write_text("LEAK=1\n", encoding="utf-8")
        env_dir = tmp_path / "envs" / "ai"
        env_dir.mkdir(parents=True)
        (env_dir / ".env").symlink_to(outside)
        environ: dict[str, str] = {}
        load_environment_dotenv(env_dir, environ=environ)
        assert "LEAK" not in environ
