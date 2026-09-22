"""Tests for agent_vault.server.lifecycle - PID file, port, auto-start."""

import json
import os
import tempfile

import pytest

from agent_vault.server.lifecycle import (
    ENV_DEFAULT,
    ENV_TEST,
    _default_port_for_env,
    all_servers_status,
    find_available_port,
    get_agv_home,
    get_lock_path,
    get_pid_path,
    is_port_available,
    is_process_alive,
    read_pid_file,
    remove_pid_file,
    server_status,
    write_pid_file,
)


@pytest.fixture
def tmp_agv_home(tmp_path, monkeypatch):
    """Use a temporary directory as agv home."""
    monkeypatch.setenv("agv_HOME", str(tmp_path))
    return tmp_path


class TestPIDFile:
    """Test PID file read/write operations."""

    def test_write_and_read(self, tmp_agv_home):
        write_pid_file(12345, 8765, "test-project")
        info = read_pid_file()
        assert info is not None
        assert info["pid"] == 12345
        assert info["port"] == 8765
        assert info["project_id"] == "test-project"
        assert "started_at" in info

    def test_read_missing_returns_none(self, tmp_agv_home):
        assert read_pid_file() is None

    def test_remove(self, tmp_agv_home):
        write_pid_file(12345, 8765, "test")
        remove_pid_file()
        assert read_pid_file() is None

    def test_remove_missing_no_error(self, tmp_agv_home):
        remove_pid_file()  # Should not raise

    def test_write_creates_directory(self, tmp_path, monkeypatch):
        nested = tmp_path / "nested" / "dir"
        monkeypatch.setenv("agv_HOME", str(nested))
        write_pid_file(1, 8765, "test")
        assert nested.exists()
        assert read_pid_file() is not None


class TestProcessChecks:
    """Test process and port availability checks."""

    def test_current_process_alive(self):
        assert is_process_alive(os.getpid())

    def test_nonexistent_process_not_alive(self):
        assert not is_process_alive(99999999)

    def test_port_available(self):
        # Find a port that's available
        port = find_available_port(49152)  # Ephemeral range
        assert is_port_available(port)

    def test_find_available_port(self):
        port = find_available_port(49152, max_retries=5)
        assert port >= 49152
        assert port < 49157

    def test_find_port_retries(self):
        # Should find a port even if preferred isn't available
        port = find_available_port(49200, max_retries=10)
        assert port >= 49200


class TestagvHome:
    """Test agv home directory resolution."""

    def test_default_home(self, monkeypatch):
        monkeypatch.delenv("agv_HOME", raising=False)
        home = get_agv_home()
        assert home.endswith(".agv")

    def test_custom_home(self, monkeypatch):
        monkeypatch.setenv("agv_HOME", "/custom/path")
        assert get_agv_home() == "/custom/path"


class TestEnvironmentAwarePaths:
    """Test environment-aware PID and lock file paths."""

    def test_default_pid_path(self, tmp_agv_home):
        path = get_pid_path()
        assert path.endswith("server.pid")
        assert "server-" not in path

    def test_test_pid_path(self, tmp_agv_home):
        path = get_pid_path(ENV_TEST)
        assert path.endswith("server-test.pid")

    def test_custom_env_pid_path(self, tmp_agv_home):
        path = get_pid_path("staging")
        assert path.endswith("server-staging.pid")

    def test_default_lock_path(self, tmp_agv_home):
        path = get_lock_path()
        assert path.endswith("server.lock")

    def test_test_lock_path(self, tmp_agv_home):
        path = get_lock_path(ENV_TEST)
        assert path.endswith("server-test.lock")

    def test_default_port(self):
        assert _default_port_for_env(ENV_DEFAULT) == 8765

    def test_test_port(self):
        assert _default_port_for_env(ENV_TEST) == 8766


class TestMultiEnvPIDFiles:
    """Test multiple PID files for different environments."""

    def test_write_read_default(self, tmp_agv_home):
        write_pid_file(100, 8765, "proj-a")
        info = read_pid_file()
        assert info["pid"] == 100
        assert info["env"] == ENV_DEFAULT

    def test_write_read_test(self, tmp_agv_home):
        write_pid_file(200, 8766, "proj-b", env=ENV_TEST)
        info = read_pid_file(env=ENV_TEST)
        assert info["pid"] == 200
        assert info["port"] == 8766
        assert info["env"] == ENV_TEST

    def test_envs_are_isolated(self, tmp_agv_home):
        write_pid_file(100, 8765, "proj-a")
        write_pid_file(200, 8766, "proj-b", env=ENV_TEST)

        default_info = read_pid_file()
        test_info = read_pid_file(env=ENV_TEST)

        assert default_info["pid"] == 100
        assert test_info["pid"] == 200

    def test_remove_one_env(self, tmp_agv_home):
        write_pid_file(100, 8765, "proj-a")
        write_pid_file(200, 8766, "proj-b", env=ENV_TEST)

        remove_pid_file(env=ENV_TEST)

        assert read_pid_file() is not None  # default still there
        assert read_pid_file(env=ENV_TEST) is None  # test removed

    def test_all_servers_status_empty(self, tmp_agv_home):
        statuses = all_servers_status()
        assert statuses == []

    def test_all_servers_status_multiple(self, tmp_agv_home):
        # Write PID files (processes won't be alive, but files exist)
        write_pid_file(99999998, 8765, "proj-a")
        write_pid_file(99999999, 8766, "proj-b", env=ENV_TEST)

        statuses = all_servers_status()
        assert len(statuses) == 2
        envs = {s["env"] for s in statuses}
        assert envs == {ENV_DEFAULT, ENV_TEST}

    def test_server_status_includes_env(self, tmp_agv_home):
        status = server_status(env=ENV_TEST)
        assert status["env"] == ENV_TEST
        assert not status["running"]
