"""ai setup enables the AFP lifecycle and a following hook is no longer inert."""

from __future__ import annotations

import json
from pathlib import Path

from agentic_inquiry.cli.setup.local_setup import LocalSetup
from agentic_inquiry.cli.setup_wizard import guide_lifecycle, run_setup
from agentic_inquiry.integration.hooks import hook


def _session_start(root: Path) -> dict:
    payload = json.dumps(
        {
            "schema_version": 1,
            "owner": "afp",
            "project_root": str(root),
            "session_id": "setup-guide",
        }
    ).encode()
    response, _code = hook("claude-code", "SessionStart", payload)
    return response


def test_setup_client_enables_hooks(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "inquiry-home"
    monkeypatch.setenv("INQUIRY_HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    assert LocalSetup(env_name="ai", workspace=project).run(announce=False) is True

    assert (
        run_setup(
            ["local", "ai", "--workspace", str(project), "--client", "claude-code"]
        )
        is True
    )

    marker = json.loads((project / ".agentic-inquiry" / "integration.json").read_text())
    assert marker["clients"]["claude-code"]["enabled"] is True
    assert (project / ".agentic-inquiry" / "project.toml").is_file()
    response = _session_start(project.resolve())
    assert response["status"] in {"ok", "partial"}


def test_discovered_client_stays_off_without_a_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("INQUIRY_HOME", str(tmp_path / "inquiry-home"))
    project = tmp_path / "project"
    project.mkdir()
    plugin = project / ".agents" / "plugins" / "agentic-inquiry" / "claude-code"
    plugin.mkdir(parents=True)

    assert run_setup(["local", "ai", "--workspace", str(project)]) is True
    assert not (project / ".agentic-inquiry" / "integration.json").exists()


def test_standalone_plugin_blocks_enable(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("INQUIRY_HOME", str(tmp_path / "inquiry-home"))
    project = tmp_path / "project"
    project.mkdir()
    claude = project / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai@agentic-inquiry": True}}),
        encoding="utf-8",
    )
    assert LocalSetup(env_name="ai", workspace=project).run(announce=False) is True

    assert (
        guide_lifecycle(project.resolve(), clients=["claude-code"], interactive=False)
        is False
    )
    captured = capsys.readouterr()
    assert "standalone_plugin_enabled" in captured.err
    assert not (project / ".agentic-inquiry" / "integration.json").exists()
