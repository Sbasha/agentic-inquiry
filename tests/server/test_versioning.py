"""Tests for agentic_inquiry.server.versioning.git - Git-linked versioning."""

import pytest

from agentic_inquiry.server.versioning.git import GitVersionManager


@pytest.fixture
def version_manager(tmp_path):
    """Create a version manager with a temp workspace."""
    return GitVersionManager(workspace=str(tmp_path))


class TestGitVersionManager:
    """Test git-linked versioning and confidence decay."""

    def test_create_version_metadata(self, version_manager):
        meta = version_manager.create_version_metadata(
            file_paths=["src/auth.py"],
            entity_names=["AuthService"],
        )
        assert "file_paths" in meta
        assert "entity_names" in meta
        assert meta["file_paths"] == ["src/auth.py"]

    def test_check_staleness_no_memories(self, version_manager):
        result = version_manager.check_staleness([])
        assert result == []

    def test_check_staleness_preserves_memories(self, version_manager):
        memories = [
            {"content": "test memory", "confidence": 1.0, "file_paths": []},
            {"content": "another memory", "confidence": 0.8, "file_paths": []},
        ]
        result = version_manager.check_staleness(memories)
        assert len(result) == 2

    def test_calculate_decay_empty(self, version_manager):
        # With no file paths and no commits, decay should be 0
        decay = version_manager.calculate_decay(memory_file_paths=[], commits=[])
        assert decay == 0.0

    def test_calculate_decay_with_commits(self, version_manager):
        decay = version_manager.calculate_decay(
            memory_file_paths=["src/auth.py"],
            commits=[
                {"files_changed": ["src/auth.py", "src/other.py"], "is_bulk": False}
            ],
        )
        assert 0.0 < decay <= 1.0

    def test_update_last_commit(self, version_manager):
        # Should not raise even in non-git directory
        version_manager.update_last_commit()
