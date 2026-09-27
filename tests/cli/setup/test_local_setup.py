"""Tests for LocalSetup (LanceDB) handler."""

from __future__ import annotations

import json
from unittest.mock import patch

from agentic_inquiry.cli.setup.local_setup import LocalSetup
from agentic_inquiry.cli.env_resolver import (
    DATA_DIR_NAME,
    ENVS_DIR_NAME,
    REGISTRY_FILE_NAME,
)


class TestLocalSetup:
    """Tests for LocalSetup class."""

    def test_init_with_env_name(self, tmp_path):
        """Test initialization with explicit env name."""
        setup = LocalSetup(env_name="test-env", workspace=tmp_path)
        assert setup.env_name == "test-env"
        assert setup.is_dev is False
        assert setup.backend_type == "lancedb"

    def test_init_with_dev_flag(self, tmp_path):
        """Test initialization with dev flag."""
        setup = LocalSetup(env_name="test", is_dev=True, workspace=tmp_path)
        assert setup.is_dev is True

    def test_env_dir_path(self, tmp_path):
        """Test environment directory path construction."""
        setup = LocalSetup(env_name="my-env", workspace=tmp_path)
        expected = tmp_path / DATA_DIR_NAME / ENVS_DIR_NAME / "my-env"
        assert setup.env_dir == expected

    def test_config_path(self, tmp_path):
        """Test config file path construction."""
        setup = LocalSetup(env_name="my-env", workspace=tmp_path)
        expected = tmp_path / DATA_DIR_NAME / ENVS_DIR_NAME / "my-env" / "config.yaml"
        assert setup.config_path == expected

    def test_run_success(self, tmp_path):
        """Test successful setup run."""
        setup = LocalSetup(env_name="test-local", workspace=tmp_path)

        # Mock user input (not needed since we provide env_name)
        result = setup.run()

        assert result is True

        # Verify directory structure
        env_dir = tmp_path / DATA_DIR_NAME / ENVS_DIR_NAME / "test-local"
        assert env_dir.exists()
        assert (env_dir / "lancedb").exists()
        assert (env_dir / "config.yaml").exists()
        env_file = env_dir / ".env"
        assert env_file.exists()
        env_text = env_file.read_text(encoding="utf-8")
        assert "# INQUIRY_EMBEDDING_DEVICE=mps" in env_text

        # Verify config content
        import yaml

        with open(env_dir / "config.yaml") as f:
            config = yaml.safe_load(f)

        assert config["storage"]["backends"]["default"]["type"] == "lancedb"
        assert "test-local" in config["storage"]["root"]
        assert "services" not in config

        # Verify registry
        registry_path = tmp_path / DATA_DIR_NAME / REGISTRY_FILE_NAME
        assert registry_path.exists()
        with open(registry_path) as f:
            registry = json.load(f)

        assert registry["active_environment"] == "test-local"
        assert any(e["name"] == "test-local" for e in registry["environments"])

    def test_run_existing_env_fails(self, tmp_path):
        """Test that setup fails if environment already exists."""
        # Create existing environment
        env_dir = tmp_path / DATA_DIR_NAME / ENVS_DIR_NAME / "existing"
        env_dir.mkdir(parents=True)
        (env_dir / "config.yaml").write_text("existing: true")

        setup = LocalSetup(env_name="existing", workspace=tmp_path)
        result = setup.run()

        assert result is False

    def test_dev_mode_naming(self, tmp_path):
        """Test that dev mode uses test environment naming."""
        # Mock the input function to return a name
        with patch(
            "agentic_inquiry.cli.setup.base.prompt_input", return_value="ai-test"
        ):
            setup = LocalSetup(is_dev=True, workspace=tmp_path)
            # Access env_name to trigger the prompt
            name = setup.env_name

        # Dev mode should result in test environment
        assert "test" in name.lower()

    def test_cleanup_on_failure(self, tmp_path):
        """Test that partial environment is cleaned up on failure."""
        setup = LocalSetup(env_name="fail-test", workspace=tmp_path)

        # Create directory to simulate partial setup
        setup.create_env_directory()
        assert setup.env_dir.exists()

        # Cleanup
        setup.cleanup_partial()
        assert not setup.env_dir.exists()


class TestLocalSetupConfig:
    """Tests for LocalSetup configuration generation."""

    def test_config_has_lancedb_backend(self, tmp_path):
        """Test that config has LanceDB backend configured."""
        setup = LocalSetup(env_name="test", workspace=tmp_path)
        setup.run()

        import yaml

        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        backends = config["storage"]["backends"]
        assert "default" in backends
        assert backends["default"]["type"] == "lancedb"

    def test_config_has_sqlite_metadata(self, tmp_path):
        """Test that config has SQLite metadata store."""
        setup = LocalSetup(env_name="test", workspace=tmp_path)
        setup.run()

        import yaml

        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        backends = config["storage"]["backends"]
        assert "metadata_store" in backends
        assert backends["metadata_store"]["type"] == "sqlite"

    def test_config_role_assignments(self, tmp_path):
        """Test that storage roles are correctly assigned."""
        setup = LocalSetup(env_name="test", workspace=tmp_path)
        setup.run()

        import yaml

        with open(setup.config_path) as f:
            config = yaml.safe_load(f)

        storage = config["storage"]
        assert storage["vector_backend"] == "default"
        assert storage["graph_backend"] == "default"
        assert storage["events_backend"] == "metadata_store"
        assert storage["file_tracker_backend_v2"] == "metadata_store"
