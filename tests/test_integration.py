"""Component boundary checks for opted-in native event handling and MCP scope."""

import json

import pytest

from agentic_inquiry.cli import main
from agentic_inquiry.integration import configure, hook
from agentic_inquiry.knowledge import dispatch
from agentic_inquiry.library import Library
from agentic_inquiry.mcp_server import scoped_invoke


def test_watcher_retains_failed_scan_at_shutdown_and_returns_partial(tmp_path, monkeypatch):
    from agentic_inquiry import integration, store

    source = tmp_path / "source"
    source.mkdir()
    db = tmp_path / "library"
    Library(db).register(source)
    report = {"complete": False, "failed": [{"path": "scan.jpg", "reason": "image_only"}]}
    monkeypatch.setattr(store, "index", lambda *args, **kwargs: report)
    result = integration.watch(db, once=True)
    checkpoint = json.loads((db / "watch-checkpoint.json").read_text())
    assert result["complete"] is False and result["reports"] == [report]
    assert checkpoint["state"] == "stopped" and checkpoint["reports"] == [report]


def test_hook_is_inert_until_enabled_and_conflicting_owner_cannot_capture(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    db = tmp_path / "library"
    payload = {
        "schema_version": 1,
        "project_root": str(root),
        "session_id": "component",
        "owner": "standalone",
    }
    assert hook(db, "pi", "SessionStart", payload)["status"] == "inert"
    assert not db.exists()
    lib = Library(db)
    c = lib.register(root, project_id="project")
    configure(db, project_root=str(root), client="pi", owner="standalone")
    with pytest.raises(ValueError, match="owner"):
        configure(db, project_root=str(root), client="pi", owner="afp")
    with pytest.raises(ValueError, match="stable"):
        hook(
            db,
            "pi",
            "PreCompact",
            payload | {"observations": [{"content": "selected observation"}]},
        )
    event = payload | {
        "event_id": "native-id",
        "observations": [{"content": "selected observation"}],
    }
    first = hook(db, "pi", "PreCompact", event)
    assert first["receipts"][0]["kind"] == "remembered"
    assert first["receipts"][0]["state"] == "committed"
    assert hook(db, "pi", "PreCompact", event)["receipts"][0]["duplicate"]
    records = dispatch(db, "memory.recall", {"project": c["project_id"]})["records"]
    assert len(records) == 1
    recall = hook(db, "pi", "SessionStart", payload)
    assert len(recall["context"]["text"].encode()) == recall["context"]["used"] <= 2048
    assert recall["context"]["text"]
    configure(db, project_root=str(root), client="pi", owner="standalone", enabled=False)
    assert hook(db, "pi", "SessionStart", payload)["status"] == "inert"


def test_unadmitted_payload_and_scope_are_rejected(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    db = tmp_path / "library"
    lib = Library(db)
    lib.register(root, project_id="one")
    payload = {
        "schema_version": 1,
        "project_root": str(root),
        "session_id": "component",
        "owner": "standalone",
    }
    with pytest.raises(ValueError, match="unadmitted"):
        hook(db, "pi", "SessionStart", payload | {"transcript_path": "/private/file"})
    assert hook(db, "codex", "TaskCompleted", payload)["status"] == "unsupported"
    with pytest.raises(ValueError, match="capabilities"):
        scoped_invoke(db, root, "one", "memory.add", {"content": "x"})
    with pytest.raises(ValueError, match="fixed"):
        scoped_invoke(db, root, "one", "memory.recall", {"project": "two"})
    with pytest.raises(ValueError, match="allowed roots"):
        scoped_invoke(db, root, "one", "search", {"query": "x", "root": "/private"})
    result = scoped_invoke(
        db, root, "one", "memory.add", {"content": "explicit local operation"}, allow_write=True
    )
    assert result["content"] == "explicit local operation"


def test_cli_input_hook_reads_stdin_once(tmp_path, monkeypatch, capsys):
    import io

    root = tmp_path / "project"
    root.mkdir()
    data = json.dumps(
        {
            "schema_version": 1,
            "project_root": str(root),
            "session_id": "component",
            "owner": "standalone",
        }
    ).encode()
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(data)))
    assert (
        main(
            [
                "integration",
                "hook",
                "--client",
                "pi",
                "--event",
                "PreCompact",
                "--db",
                str(tmp_path / "library"),
                "--input",
                "-",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "inert"


def test_mcp_read_cannot_record_contradiction(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    db = tmp_path / "library"
    Library(db).register(root, project_id="p")
    left = dispatch(db, "memory.add", {"project": "p", "content": "left assertion"})
    right = dispatch(db, "memory.add", {"project": "p", "content": "right assertion"})
    arguments = {
        "left_id": left["id"],
        "right_id": right["id"],
        "reason": "operator identified conflict",
    }
    with pytest.raises(ValueError, match="write capability"):
        scoped_invoke(db, root, "p", "memory.contradictions", arguments)
    assert scoped_invoke(db, root, "p", "memory.contradictions", {})["contradictions"] == []
    result = scoped_invoke(db, root, "p", "memory.contradictions", arguments, allow_write=True)
    assert len(result["contradictions"]) == 1


def test_selected_custom_library_resolves_without_db_and_blocks_competing_selection(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    db = tmp_path / "custom"
    Library(db).register(root, project_id="p")
    configure(db, project_root=str(root), client="pi", owner="standalone")
    event = {
        "schema_version": 1,
        "project_root": str(root),
        "session_id": "s",
        "owner": "standalone",
        "event_id": "e",
        "observations": [{"content": "selected library fact"}],
    }
    assert hook(None, "pi", "Stop", event)["receipts"][0]["kind"] == "remembered"
    other = tmp_path / "other"
    Library(other).register(root, project_id="p")
    with pytest.raises(ValueError, match="Disable"):
        configure(other, project_root=str(root), client="pi", owner="afp")


def test_mcp_rejects_nested_shared_capture_and_existing_shared_mutation(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    db = tmp_path / "library"
    Library(db).register(root, project_id="p")
    dispatch(db, "capture.enable", {"project": "p"})
    with pytest.raises(ValueError, match="shared capture"):
        scoped_invoke(
            db,
            root,
            "p",
            "capture.submit",
            {"event_id": "e", "observations": [{"content": "cross-project", "shared": True}]},
            allow_write=True,
        )
    shared = dispatch(db, "memory.add", {"project": "p", "content": "shared fact", "shared": True})
    with pytest.raises(ValueError, match="outside"):
        scoped_invoke(
            db,
            root,
            "p",
            "memory.correct",
            {
                "memory_id": shared["id"],
                "content": "changed",
                "expected_revision": 1,
                "reason": "correction",
            },
            allow_write=True,
        )
    assert (
        dispatch(
            db,
            "memory.inspect",
            {"project": "p", "memory_id": shared["id"], "include_shared": True},
        )["revision"]
        == 1
    )


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "PreCompact"])
def test_hook_recall_keeps_current_record_without_revision_history(tmp_path, event):
    root = tmp_path / "project"
    root.mkdir()
    db = tmp_path / "library"
    Library(db).register(root, project_id="p")
    configure(db, project_root=str(root), client="codex", owner="afp")
    old = dispatch(
        db,
        "memory.add",
        {
            "project": "p",
            "content": "Earlier superseded instruction. " * 100,
            "provenance": {"operator_notes": "review detail " * 300},
        },
    )
    current = dispatch(
        db,
        "memory.correct",
        {
            "project": "p",
            "memory_id": old["id"],
            "expected_revision": 1,
            "content": "Use Montréal for the current meeting.",
            "reason": "Current location",
        },
    )
    oversized = dispatch(db, "memory.add", {"project": "p", "content": "é" * 2048})
    context = hook(
        db,
        "codex",
        event,
        {
            "schema_version": 1,
            "project_root": str(root),
            "session_id": "component",
            "owner": "afp",
        },
    )["context"]
    assert context["budget"] == 2048
    assert len(context["text"].encode()) == context["used"] <= 2048
    assert [entry["data"]["id"] for entry in context["entries"]] == [old["id"]]
    recalled = context["entries"][0]["data"]
    assert recalled["content"] == current["content"]
    assert recalled["revision"] == 2
    assert recalled["origin"] == current["origin"]
    assert recalled["citations"] == current["citations"]
    assert recalled["freshness"] == current["freshness"]
    assert "Earlier superseded instruction" not in context["text"]
    assert "operator_notes" not in context["text"]
    assert context["omitted"] == [oversized["id"]]
    inspected = dispatch(db, "memory.inspect", {"project": "p", "memory_id": old["id"]})
    assert len(inspected["revisions"]) == 2
    assert inspected["revisions"][0]["content"] == old["content"]
    assert inspected["revisions"][0]["provenance"] == old["provenance"]
