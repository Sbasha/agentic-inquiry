"""Integration tests for daemon API and hook scripts.

Covers TS-5.x (daemon lifecycle, API contracts) and TS-6.x (hook execution).
Tests the daemon in-process without actually starting a server.
"""

import asyncio
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            )
        )
    ),
)

from extensions.claude.ai.servers.daemon.orchestrator import ServiceOrchestrator


@pytest.fixture
def orchestrator(tmp_path):
    """Create an orchestrator without ai backend (pure logic tests)."""
    return ServiceOrchestrator(
        workspace=str(tmp_path),
        project_id="test_project_123",
        config={
            "checkpoints": {"interval_turns": 5},
            "cache": {
                "context_size": 10,
                "context_ttl": 60,
                "memory_size": 10,
                "memory_ttl": 60,
            },
        },
    )


# --- TS-5.1: Orchestrator Lifecycle ---


class TestOrchestratorLifecycle:
    def test_initial_state(self, orchestrator):
        assert orchestrator.initialized is False
        assert orchestrator.turn_count == 0
        assert orchestrator.project_id == "test_project_123"

    def test_increment_turn(self, orchestrator):
        assert orchestrator.increment_turn() == 1
        assert orchestrator.increment_turn() == 2
        assert orchestrator.turn_count == 2

    def test_checkpoint_at_interval(self, orchestrator):
        for _ in range(4):
            orchestrator.increment_turn()
            assert orchestrator.is_checkpoint_due() is False

        orchestrator.increment_turn()  # Turn 5
        assert orchestrator.is_checkpoint_due() is True

    def test_checkpoint_every_5_turns(self, orchestrator):
        checkpoints = []
        for t in range(1, 26):
            orchestrator.increment_turn()
            if orchestrator.is_checkpoint_due():
                checkpoints.append(t)
        assert checkpoints == [5, 10, 15, 20, 25]


# --- TS-5.3: API Endpoint Contracts (orchestrator layer) ---


class TestOrchestratorAPI:
    def test_classify_file_config(self, orchestrator):
        assert orchestrator.classify_file_importance("config.yaml") == "config"

    def test_classify_file_entry_point(self, orchestrator):
        assert orchestrator.classify_file_importance("main.py") == "entry_point"

    def test_classify_file_test(self, orchestrator):
        assert orchestrator.classify_file_importance("test_vector.py") == "test"

    def test_classify_file_regular(self, orchestrator):
        assert orchestrator.classify_file_importance("vector.py") is None

    def test_classify_bash_test_pass(self, orchestrator):
        result = orchestrator.classify_bash_command("pytest tests/", 0, "5 passed")
        assert result["category"] == "test"
        assert result["exit_code"] == 0

    def test_classify_bash_test_fail(self, orchestrator):
        result = orchestrator.classify_bash_command("pytest tests/", 1, "FAILED")
        assert result["category"] == "test"
        assert result["should_capture"] is True
        assert "failed" in result["prompt"].lower()

    def test_task_transition_completed(self, orchestrator):
        prompt = orchestrator.get_task_transition_prompt(
            "1", "completed", "Build daemon"
        )
        assert "REQUIRED" in prompt
        assert "Build daemon" in prompt

    def test_task_transition_in_progress(self, orchestrator):
        prompt = orchestrator.get_task_transition_prompt(
            "1", "in_progress", "Build daemon"
        )
        assert "approach" in prompt.lower()

    def test_invalidate_cache(self, orchestrator):
        # Should not crash even before initialization
        orchestrator.invalidate_cache(["file1.py", "file2.py"])


# --- TS-6.1: Hook Script Execution ---


class TestHookScriptExecution:
    """Test that hook scripts execute and produce valid JSON output.

    These tests run the actual Python scripts as subprocesses,
    simulating how Claude Code invokes them.
    """

    @pytest.fixture
    def scripts_dir(self):
        return os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            "hooks",
            "scripts",
        )

    @pytest.fixture
    def project_root(self):
        return os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    )
                )
            )
        )

    def _run_hook_script(self, scripts_dir, project_root, script_name, stdin_data=None):
        """Run a hook script and return parsed JSON output."""
        script_path = os.path.join(scripts_dir, script_name)
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = "/tmp/test_project"
        env["CLAUDE_SESSION_ID"] = "test-session-123"

        result = subprocess.run(
            [sys.executable, script_path],
            input=json.dumps(stdin_data or {}),
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root,
            env=env,
        )
        assert result.returncode == 0, f"Script {script_name} failed: {result.stderr}"

        # Parse JSON output
        output = result.stdout.strip()
        if output:
            return json.loads(output)
        return {}

    def test_session_start_produces_valid_json(self, scripts_dir, project_root):
        result = self._run_hook_script(
            scripts_dir, project_root, "session_start.py", {}
        )
        assert "continue" in result
        assert result["continue"] is True
        # Should include behavioral contract
        assert "systemMessage" in result
        assert "MUST" in result["systemMessage"]

    def test_user_prompt_submit_produces_valid_json(self, scripts_dir, project_root):
        result = self._run_hook_script(
            scripts_dir,
            project_root,
            "user_prompt_submit.py",
            {"userPrompt": "How does search work?"},
        )
        assert "continue" in result
        assert result["continue"] is True

    def test_post_write_produces_valid_json(self, scripts_dir, project_root):
        result = self._run_hook_script(
            scripts_dir,
            project_root,
            "post_write.py",
            {"toolInput": {"file_path": "test.py"}, "toolName": "Write"},
        )
        assert "continue" in result
        assert result["continue"] is True

    def test_post_bash_produces_valid_json(self, scripts_dir, project_root):
        result = self._run_hook_script(
            scripts_dir,
            project_root,
            "post_bash.py",
            {
                "toolInput": {"command": "pytest tests/"},
                "toolOutput": {"exitCode": 0, "stdout": "5 passed"},
            },
        )
        assert "continue" in result
        assert result["continue"] is True

    def test_post_task_update_produces_valid_json(self, scripts_dir, project_root):
        result = self._run_hook_script(
            scripts_dir,
            project_root,
            "post_task_update.py",
            {
                "toolInput": {
                    "taskId": "1",
                    "status": "completed",
                    "subject": "Test task",
                }
            },
        )
        assert "continue" in result
        assert result["continue"] is True

    def test_pre_compact_produces_valid_json(self, scripts_dir, project_root):
        result = self._run_hook_script(
            scripts_dir,
            project_root,
            "pre_compact.py",
            {"session_id": "test-session"},
        )
        assert "continue" in result
        assert result["continue"] is True
        assert "systemMessage" in result
        assert "REQUIRED" in result["systemMessage"]

    def test_stop_produces_valid_json(self, scripts_dir, project_root):
        result = self._run_hook_script(
            scripts_dir,
            project_root,
            "stop.py",
            {"session_id": "test-session"},
        )
        assert "continue" in result
        assert result["continue"] is True
        assert "systemMessage" in result
        assert "REQUIRED" in result["systemMessage"]

    def test_user_prompt_submit_empty_prompt(self, scripts_dir, project_root):
        """Empty prompt should pass through with continue=true."""
        result = self._run_hook_script(
            scripts_dir,
            project_root,
            "user_prompt_submit.py",
            {},
        )
        assert result["continue"] is True

    def test_post_write_empty_path(self, scripts_dir, project_root):
        """Empty file path should pass through gracefully."""
        result = self._run_hook_script(
            scripts_dir,
            project_root,
            "post_write.py",
            {"toolInput": {}, "toolName": "Write"},
        )
        assert result["continue"] is True
