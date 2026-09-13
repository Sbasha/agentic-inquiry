"""Component checks for client installation ownership and native payload translation."""

from __future__ import annotations

import json
import runpy
import shlex

import pytest

from agentic_inquiry import clients
from agentic_inquiry.library import Library


def test_codex_preview_apply_idempotence_and_unrelated_hook_preservation(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    (target / ".codex").mkdir()
    hooks = target / ".codex/hooks.json"
    existing = {
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "existing-command"}]}]
        },
        "other": {"keep": True},
    }
    hooks.write_text(json.dumps(existing))
    original = hooks.read_bytes()
    preview = clients.install(tmp_path / "library", "codex", target)
    assert preview["applied"] is False
    assert preview["conflicts"] == []
    assert hooks.read_bytes() == original
    assert not (target / ".agents").exists()
    clients.install(tmp_path / "library", "codex", target, apply=True)
    assert clients.inspect(tmp_path / "library", "codex", target)["current"] is True
    assert clients.install(tmp_path / "library", "codex", target)["changes"] == []
    installed = json.loads(hooks.read_text())
    assert installed["hooks"]["SessionStart"][0] == existing["hooks"]["SessionStart"][0]
    installed["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "later-command"}]})
    hooks.write_text(json.dumps(installed))
    clients.uninstall(tmp_path / "library", "codex", target, apply=True)
    remaining = json.loads(hooks.read_text())
    assert remaining["hooks"]["SessionStart"] == existing["hooks"]["SessionStart"]
    assert remaining["hooks"]["Stop"] == [
        {"hooks": [{"type": "command", "command": "later-command"}]}
    ]
    assert remaining["other"] == {"keep": True}
    assert not (target / ".agents/skills/ai/SKILL.md").exists()
    clients.install(tmp_path / "library", "codex", target, apply=True)
    assert clients.inspect(tmp_path / "library", "codex", target)["current"] is True


def test_existing_empty_hook_file_is_preserved(tmp_path):
    (tmp_path / ".codex").mkdir()
    hooks = tmp_path / ".codex/hooks.json"
    hooks.write_text("{}")
    clients.install(tmp_path / "library", "codex", tmp_path, apply=True)
    clients.uninstall(tmp_path / "library", "codex", tmp_path, apply=True)
    assert json.loads(hooks.read_text()) == {}


@pytest.mark.parametrize(
    "client,path",
    [("codex", ".agents/skills/ai/SKILL.md"), ("pi", ".pi/extensions/agentic-inquiry/index.ts")],
)
def test_unowned_collision_and_modified_owned_files_are_not_overwritten(tmp_path, client, path):
    target = tmp_path / "project"
    target.mkdir()
    collision = target / path
    collision.parent.mkdir(parents=True)
    collision.write_text("user-authored")
    preview = clients.install(tmp_path / "library", client, target)
    assert preview["conflicts"]
    with pytest.raises(ValueError, match="conflicts"):
        clients.install(tmp_path / "library", client, target, apply=True)
    assert collision.read_text() == "user-authored"
    other = tmp_path / "other"
    other.mkdir()
    clients.install(tmp_path / "library", client, other, apply=True)
    owned = other / path
    owned.write_text("manual edit")
    with pytest.raises(ValueError, match="manual changes"):
        clients.uninstall(tmp_path / "library", client, other, apply=True)
    assert owned.read_text() == "manual edit"


def test_pi_command_collision_is_reported_and_unrelated_extension_preserved(tmp_path):
    extension = tmp_path / ".pi/extensions/other.ts"
    extension.parent.mkdir(parents=True)
    extension.write_text('export default pi => pi.registerCommand("ai", {});')
    assert clients.install(tmp_path / "library", "pi", tmp_path)["conflicts"]
    extension.write_text('export default pi => pi.registerCommand("other", {});')
    original = extension.read_bytes()
    clients.install(tmp_path / "library", "pi", tmp_path, apply=True)
    assert clients.inspect(tmp_path / "library", "pi", tmp_path)["current"] is True
    clients.uninstall(tmp_path / "library", "pi", tmp_path, apply=True)
    assert extension.read_bytes() == original


def test_client_target_and_file_symlinks_are_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        clients.install(tmp_path / "library", "codex", linked, apply=True)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".codex").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        clients.install(tmp_path / "library", "codex", project, apply=True)
    assert list(outside.iterdir()) == []


def test_forged_receipt_cannot_delete_unrelated_project_files(tmp_path):
    clients.install(tmp_path / "library", "pi", tmp_path, apply=True)
    important = tmp_path / "README.md"
    important.write_text("Keep this file")
    receipt_path = tmp_path / ".pi/agentic-inquiry-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["files"]["README.md"] = clients.digest(important.read_bytes())
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="unowned path"):
        clients.uninstall(tmp_path / "library", "pi", tmp_path, apply=True)
    assert important.read_text() == "Keep this file"


def test_install_failure_rolls_back_completed_file_writes(tmp_path, monkeypatch):
    original = clients.atomic_write
    count = 0

    def interrupted(path, content):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("interrupted installation")
        original(path, content)

    monkeypatch.setattr(clients, "atomic_write", interrupted)
    with pytest.raises(OSError):
        clients.install(tmp_path / "library", "pi", tmp_path, apply=True)
    assert not (tmp_path / ".pi/extensions/agentic-inquiry/index.ts").exists()
    assert not (tmp_path / ".pi/agentic-inquiry-receipt.json").exists()
    monkeypatch.setattr(clients, "atomic_write", original)
    clients.install(tmp_path / "library", "pi", tmp_path, apply=True)
    assert clients.inspect(tmp_path / "library", "pi", tmp_path)["current"] is True


def test_enabled_external_owner_prevents_standalone_install(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    library = Library(tmp_path / "library")
    with library.writer() as connection:
        connection.execute(
            "CREATE TABLE integration_config(root TEXT,client TEXT,enabled INTEGER,owner TEXT)"
        )
        connection.execute(
            "INSERT INTO integration_config VALUES(?,?,1,'afp')", (str(target), "codex")
        )
    report = clients.install(library.path, "codex", target)
    assert report["conflicts"] == ["another enabled integration owns this project's client"]
    with pytest.raises(ValueError, match="another enabled"):
        clients.install(library.path, "codex", target, apply=True)


def test_codex_translation_filters_content_and_preserves_native_event_identity(tmp_path):
    adapter = runpy.run_path(str(clients.ASSETS / "codex/agentic-inquiry/scripts/codex-hook.py"))
    native = {
        "cwd": str(tmp_path),
        "session_id": "native-session",
        "hook_event_name": "PostToolUse",
        "tool_use_id": "native-call",
        "tool_name": "apply_patch",
        "tool_input": {
            "command": "*** Begin Patch\n*** Update File: src/example.py\n+private content\n*** End Patch"
        },
        "tool_response": "private output",
        "transcript_path": "/private/transcript",
    }
    payload, warnings = adapter["translate"]("PostToolUse", native)
    assert payload["event_id"] == "native-call"
    assert payload["artifacts"] == ["src/example.py"]
    assert warnings == []
    assert "private content" not in json.dumps(payload)
    assert "private output" not in json.dumps(payload)
    assert set(payload) == {
        "schema_version",
        "project_root",
        "session_id",
        "owner",
        "event_id",
        "artifacts",
    }
    native.pop("tool_use_id")
    payload, warnings = adapter["translate"]("PostToolUse", native)
    assert "event_id" not in payload and "artifacts" not in payload
    assert warnings


def test_codex_precompact_output_uses_only_supported_common_fields(tmp_path):
    adapter = runpy.run_path(str(clients.ASSETS / "codex/agentic-inquiry/scripts/codex-hook.py"))
    response = {"schema_version": 1, "status": "ok", "context": {"text": "Scoped recall"}}
    precompact = adapter["output"]("PreCompact", response, [])
    assert "hookSpecificOutput" not in precompact
    assert "systemMessage" in precompact
    startup = adapter["output"]("SessionStart", response, [])
    assert startup["hookSpecificOutput"] == {
        "hookEventName": "SessionStart",
        "additionalContext": "Scoped recall",
    }
    with pytest.raises(ValueError, match="Unsupported"):
        adapter["translate"]("TaskCompleted", {"cwd": str(tmp_path), "session_id": "native"})


def test_dispatch_root_alias_is_explicit_and_preview_only(tmp_path):
    result = clients.dispatch(
        tmp_path / "library", "install", {"client": "pi", "root": str(tmp_path)}
    )
    assert result["applied"] is False
    assert result["target"] == str(tmp_path)
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ValueError, match="not both"):
        clients.dispatch(
            tmp_path / "library",
            "install",
            {"client": "pi", "root": str(tmp_path), "target": str(tmp_path)},
        )


def test_legacy_owned_hook_locator_migrates_without_losing_unrelated_entries(tmp_path):
    clients.install(tmp_path / "old-library", "codex", tmp_path, apply=True)
    receipt_path = tmp_path / ".codex/agentic-inquiry/receipt.json"
    receipt = json.loads(receipt_path.read_text())
    hooks_path = tmp_path / ".codex/hooks.json"
    hooks = json.loads(hooks_path.read_text())
    for event, blocks in receipt["hooks"].items():
        command = (
            blocks[0]["hooks"][0]["command"] + " --db " + shlex.quote(str(tmp_path / "old-library"))
        )
        blocks[0]["hooks"][0]["command"] = command
        hooks["hooks"][event][0]["hooks"][0]["command"] = command
    receipt_path.write_text(json.dumps(receipt))
    hooks_path.write_text(json.dumps(hooks))
    clients.install(tmp_path / "new-library", "codex", tmp_path, apply=True)
    current = json.loads(hooks_path.read_text())
    for blocks in current["hooks"].values():
        assert "--db" not in shlex.split(blocks[0]["hooks"][0]["command"])
    clients.uninstall(tmp_path / "new-library", "codex", tmp_path, apply=True)
    assert not receipt_path.exists()
