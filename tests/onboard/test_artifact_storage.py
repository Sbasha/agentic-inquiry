"""Tests for onboard artifact storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from agent_vault.onboard.artifact_storage import (
    LocalOnboardArtifactStorage,
    create_onboard_artifact_storage,
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalOnboardArtifactStorage:
    """Create a local artifact storage in a temp directory."""
    return LocalOnboardArtifactStorage(base_path=tmp_path / "onboard")


class TestLocalArtifactStorage:
    """Tests for LocalOnboardArtifactStorage."""

    async def test_save_and_load_report(
        self, storage: LocalOnboardArtifactStorage
    ) -> None:
        content = "# Exploration Report\n\nThis is a test."
        path = await storage.save_report(
            "project-1", "run-1", "EXPLORATION", content
        )
        assert Path(path).exists()
        assert path.endswith("EXPLORATION.md")

        loaded = await storage.load_report("project-1", "run-1", "EXPLORATION")
        assert loaded == content

    async def test_list_reports(
        self, storage: LocalOnboardArtifactStorage
    ) -> None:
        await storage.save_report("project-1", "run-1", "EXPLORATION", "# Explore")
        await storage.save_report("project-1", "run-1", "VALIDATION", "# Validate")
        await storage.save_report("project-1", "run-1", "ONBOARD", "# Onboard")

        reports = await storage.list_reports("project-1", "run-1")
        assert sorted(reports) == ["EXPLORATION", "ONBOARD", "VALIDATION"]

    async def test_list_empty(
        self, storage: LocalOnboardArtifactStorage
    ) -> None:
        reports = await storage.list_reports("nonexistent", "none")
        assert reports == []

    async def test_load_nonexistent_raises(
        self, storage: LocalOnboardArtifactStorage
    ) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.load_report("project-1", "run-1", "MISSING")

    async def test_delete_run_artifacts(
        self, storage: LocalOnboardArtifactStorage
    ) -> None:
        await storage.save_report("project-1", "run-1", "EXPLORATION", "content")
        await storage.save_report("project-1", "run-1", "VALIDATION", "content")

        count = await storage.delete_run_artifacts("project-1", "run-1")
        assert count == 2

        reports = await storage.list_reports("project-1", "run-1")
        assert reports == []

    async def test_delete_nonexistent(
        self, storage: LocalOnboardArtifactStorage
    ) -> None:
        count = await storage.delete_run_artifacts("nonexistent", "none")
        assert count == 0

    async def test_multiple_projects_isolated(
        self, storage: LocalOnboardArtifactStorage
    ) -> None:
        await storage.save_report("project-a", "run-1", "EXPLORATION", "Project A")
        await storage.save_report("project-b", "run-1", "EXPLORATION", "Project B")

        a = await storage.load_report("project-a", "run-1", "EXPLORATION")
        b = await storage.load_report("project-b", "run-1", "EXPLORATION")

        assert a == "Project A"
        assert b == "Project B"


class TestCreateOnboardArtifactStorage:
    """Tests for the factory function."""

    def test_default_local_storage(self, tmp_path: Path) -> None:
        """Default config produces LocalOnboardArtifactStorage."""
        from agent_vault.config import Config

        config = Config()
        # Override storage root so it doesn't use the default
        config.storage.root = str(tmp_path)

        storage = create_onboard_artifact_storage(config)
        assert isinstance(storage, LocalOnboardArtifactStorage)

    def test_explicit_local_type(self, tmp_path: Path) -> None:
        """Explicit type=local produces LocalOnboardArtifactStorage."""
        from agent_vault.config import Config

        config = Config()
        config.storage.root = str(tmp_path)
        config.onboard.artifact_storage.type = "local"

        storage = create_onboard_artifact_storage(config)
        assert isinstance(storage, LocalOnboardArtifactStorage)

    def test_gcs_type_without_gcsfs_raises(self) -> None:
        """GCS config with missing gcsfs raises ImportError."""
        from agent_vault.config import Config

        config = Config()
        config.onboard.artifact_storage.type = "gcs"
        config.onboard.artifact_storage.gcs_bucket = "my-bucket"

        # GCS will try to import gcsfs which is likely not installed in test env
        # This should raise ImportError, NOT silently fall back
        with pytest.raises(ImportError):
            create_onboard_artifact_storage(config)

    def test_no_onboard_attr_falls_back_to_local(self, tmp_path: Path) -> None:
        """Config without onboard attribute still produces local storage."""

        @dataclass
        class MinimalStorageConfig:
            root: str = ""

        @dataclass
        class MinimalConfig:
            storage: MinimalStorageConfig = field(
                default_factory=MinimalStorageConfig
            )

        config = MinimalConfig()
        config.storage.root = str(tmp_path)

        storage = create_onboard_artifact_storage(config)  # type: ignore[arg-type]
        assert isinstance(storage, LocalOnboardArtifactStorage)


class TestOnboardConfig:
    """Tests for OnboardConfig dataclass."""

    def test_defaults(self) -> None:
        from agent_vault.config import OnboardConfig

        cfg = OnboardConfig()
        assert cfg.gate_enabled is True
        assert cfg.staleness.days_threshold == 7
        assert cfg.artifact_storage.type == "local"
        assert cfg.artifact_storage.gcs_bucket is None

    def test_invalid_storage_type_raises(self) -> None:
        from agent_vault.config import OnboardArtifactStorageConfig
        from agent_vault.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="Invalid artifact storage type"):
            OnboardArtifactStorageConfig(type="s3")

    def test_gcs_without_bucket_raises(self) -> None:
        from agent_vault.config import OnboardArtifactStorageConfig
        from agent_vault.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="gcs_bucket is required"):
            OnboardArtifactStorageConfig(type="gcs", gcs_bucket=None)

    def test_config_class_has_onboard(self) -> None:
        from agent_vault.config import Config

        config = Config()
        assert hasattr(config, "onboard")
        assert config.onboard.gate_enabled is True
