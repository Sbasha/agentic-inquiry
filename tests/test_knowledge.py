"""Component checks for durable scope, capture and authored-page failure boundaries."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agentic_inquiry.knowledge import Knowledge, dispatch
from agentic_inquiry.library import backup, restore


def citation() -> dict:
    return {
        "id": "a" * 64,
        "collection_id": "collection-1",
        "source_id": "source-1",
        "source_version": "version-1",
        "source_hash": "b" * 64,
        "location": {"kind": "lines", "line_start": 3, "line_end": 4},
    }


def current_reader(chunk_id: str) -> dict:
    assert chunk_id == citation()["id"]
    return {"citation": citation(), "project_id": "alpha", "freshness": "current"}


def test_restart_correction_supersession_retraction_and_scope(tmp_path):
    knowledge = Knowledge(tmp_path)
    first = knowledge.add("alpha", "The release is Monday", kind="decision")
    assert Knowledge(tmp_path).recall("alpha")["records"][0]["id"] == first["id"]
    assert knowledge.recall("beta")["records"] == []
    with pytest.raises(FileNotFoundError):
        knowledge.correct("beta", first["id"], "Other", "Reason", 1)
    corrected = knowledge.correct(
        "alpha", first["id"], "The release is Tuesday", "Schedule correction", 1
    )
    assert corrected["revision"] == 2
    assert corrected["revisions"][0]["content"] == "The release is Monday"
    assert knowledge.recall("alpha", "Monday")["records"] == []
    with pytest.raises(ValueError, match="current active revision"):
        knowledge.correct("alpha", first["id"], "Stale update", "Reason", 1)
    replacement = knowledge.supersede(
        "alpha", first["id"], "The release is Wednesday", "New schedule", 2
    )
    assert knowledge.inspect("alpha", first["id"])["state"] == "superseded"
    assert [record["id"] for record in knowledge.recall("alpha")["records"]] == [replacement["id"]]
    assert knowledge.contradictions("alpha")["contradictions"][0]["left_state"] == "superseded"
    knowledge.retract("alpha", replacement["id"], "Schedule withdrawn", 1)
    assert Knowledge(tmp_path).recall("alpha")["records"] == []
    assert len(knowledge.export_memories("alpha")["records"]) == 2


def test_shared_recall_and_write_permissions_are_explicit(tmp_path):
    knowledge = Knowledge(tmp_path)
    shared = knowledge.add("alpha", "Use plain language", kind="preference", shared=True)
    assert knowledge.recall("alpha")["records"] == []
    assert knowledge.recall("beta")["records"] == []
    assert knowledge.recall("beta", include_shared=True)["records"][0]["id"] == shared["id"]
    with pytest.raises(FileNotFoundError):
        knowledge.retract("beta", shared["id"], "Unauthorized edit", 1)
    with pytest.raises(TypeError):
        knowledge.recall("beta", include_shared="false")
    with pytest.raises(ValueError):
        knowledge.add("", "No project")
    with pytest.raises(TypeError):
        knowledge.capture_enable("alpha", "false")


def test_citations_check_identity_scope_and_inherit_freshness(tmp_path):
    knowledge = Knowledge(tmp_path, current_reader)
    record = knowledge.add(
        "alpha", "The implementation uses SQLite", origin="extracted", citations=[citation()]
    )
    assert record["freshness"] == "current"
    with pytest.raises(ValueError, match="outside"):
        knowledge.add("beta", "Cross-project evidence", citations=[citation()])
    with pytest.raises(ValueError, match="does not match"):
        knowledge.add(
            "alpha", "False location", citations=[{**citation(), "location": {"line_start": 99}}]
        )
    knowledge.reader = lambda _: {
        "citation": citation(),
        "project_id": "alpha",
        "freshness": "changed",
    }
    assert knowledge.inspect("alpha", record["id"])["freshness"] == "stale"
    assert knowledge.recall("alpha")["records"] == []
    assert knowledge.recall("alpha", include_stale=True)["records"][0]["id"] == record["id"]


def test_unresolved_citations_survive_without_fabricated_user_citations(tmp_path):
    def missing(_):
        raise FileNotFoundError("unavailable chunk")

    knowledge = Knowledge(tmp_path, missing)
    unresolved = knowledge.add(
        "alpha", "Evidence awaits indexing", origin="extracted", citations=[citation()]
    )
    assert unresolved["citations"][0]["status"] == "unresolved"
    assert unresolved["freshness"] == "unresolved"
    fact = knowledge.add("alpha", "I prefer short meetings")
    assert fact["citations"] == []
    assert fact["freshness"] == "not_source_backed"
    with pytest.raises(ValueError, match="require source citations"):
        knowledge.add("alpha", "Missing evidence", origin="extracted")


def test_capture_receipt_duplicate_conflict_disable_and_restart(tmp_path):
    knowledge = Knowledge(tmp_path)
    observations = [{"content": "Selected observation", "origin": "agent"}]
    with pytest.raises(ValueError, match="explicitly enabled"):
        knowledge.capture_submit("alpha", "session:1", observations)
    knowledge.capture_enable("alpha")
    first = knowledge.capture_submit("alpha", "session:1", observations)
    assert first["state"] == "committed"
    restarted = Knowledge(tmp_path)
    duplicate = restarted.capture_submit("alpha", "session:1", observations)
    assert duplicate["duplicate"] is True
    assert duplicate["record_ids"] == first["record_ids"]
    assert len(restarted.recall("alpha")["records"]) == 1
    with pytest.raises(ValueError, match="different content"):
        restarted.capture_submit("alpha", "session:1", [{"content": "Changed event"}])
    restarted.capture_enable("alpha", False)
    assert restarted.capture_recall("alpha")["records"] == []
    assert restarted.capture_submit("alpha", "session:1", observations)["state"] == "committed"
    with pytest.raises(ValueError):
        restarted.capture_submit("alpha", "session:2", observations)


def test_capture_failure_rolls_back_records_and_retry_is_durable(tmp_path, monkeypatch):
    knowledge = Knowledge(tmp_path)
    knowledge.capture_enable("alpha")
    original = Knowledge._insert_memory
    calls = 0

    def fail_second(connection, prepared):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("storage interruption")
        return original(connection, prepared)

    with monkeypatch.context() as patch:
        patch.setattr(Knowledge, "_insert_memory", staticmethod(fail_second))
        failed = knowledge.capture_submit(
            "alpha", "session:recover", [{"content": "One"}, {"content": "Two"}]
        )
    assert failed["state"] == "failed"
    assert knowledge.recall("alpha")["records"] == []
    restarted = Knowledge(tmp_path)
    assert restarted.capture_status("alpha")["failed"] == 1
    retried = restarted.capture_retry("alpha")["results"][0]
    assert retried["state"] == "committed"
    assert len(restarted.recall("alpha")["records"]) == 2
    assert restarted.capture_status("alpha")["events"][0]["attempts"] == 2


def test_capture_crash_before_processing_retains_pending_event(tmp_path, monkeypatch):
    knowledge = Knowledge(tmp_path)
    knowledge.capture_enable("alpha")

    def interrupted(*_):
        raise KeyboardInterrupt

    monkeypatch.setattr(knowledge, "_capture_process", interrupted)
    with pytest.raises(KeyboardInterrupt):
        knowledge.capture_submit("alpha", "pending:1", [{"content": "Durable selected content"}])
    restarted = Knowledge(tmp_path)
    assert restarted.capture_status("alpha")["pending"] == 1
    assert restarted.capture_retry("alpha")["results"][0]["state"] == "committed"


def test_page_expected_hash_and_transitive_source_staleness(tmp_path):
    knowledge = Knowledge(tmp_path, current_reader)
    source = knowledge.write_page(
        "alpha", "source", "# Source\nCited assertion.\n", None, [citation()]
    )
    knowledge.write_page("alpha", "summary", "# Summary\nSee source.\n", None, [], ["source"])
    knowledge.write_page("alpha", "overview", "# Overview\nSee summary.\n", None, [], ["summary"])
    assert knowledge.validate_page("alpha", "overview")["freshness"] == "current"
    knowledge.reader = lambda _: {
        "citation": citation(),
        "project_id": "alpha",
        "freshness": "changed",
    }
    assert {page["page_id"] for page in knowledge.stale_pages("alpha")["pages"]} == {
        "source",
        "summary",
        "overview",
    }
    path = Path(source["path"])
    path.write_text("# Source\nManual correction.\n")
    with pytest.raises(ValueError, match="content changed"):
        knowledge.write_page(
            "alpha", "source", "Automated overwrite", source["content_hash"], [citation()]
        )
    assert path.read_text() == "# Source\nManual correction.\n"
    assert knowledge.inspect_page("alpha", "source")["manual_edit"] is True


def test_page_cycles_unresolved_dependencies_and_scope(tmp_path):
    knowledge = Knowledge(tmp_path)
    first = knowledge.write_page("alpha", "a", "A", None, [], ["b"])
    assert knowledge.validate_page("alpha", "a")["freshness"] == "stale"
    with pytest.raises(ValueError, match="cycle"):
        knowledge.write_page("alpha", "b", "B", None, [], ["a"])
    assert not (tmp_path / "knowledge" / "b.md").exists()
    with pytest.raises(ValueError, match="another project"):
        knowledge.write_page("beta", "a", "B", first["content_hash"], [])
    with pytest.raises(FileNotFoundError):
        knowledge.inspect_page("beta", "a")
    with pytest.raises(FileNotFoundError):
        knowledge.write_page("beta", "secret-link", "B", None, [], ["a"])


def test_page_crash_after_replace_recovers_citation_metadata(tmp_path, monkeypatch):
    knowledge = Knowledge(tmp_path, current_reader)
    original = __import__("os").replace

    def interrupted(source, destination):
        original(source, destination)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr("agentic_inquiry.knowledge.os.replace", interrupted)
        with pytest.raises(KeyboardInterrupt):
            knowledge.write_page("alpha", "recover", "# Durable page\n", None, [citation()])
    restarted = Knowledge(tmp_path, current_reader)
    page = restarted.inspect_page("alpha", "recover")
    assert page["body"] == "# Durable page\n"
    assert page["pending"] is None
    assert page["citations"][0]["status"] == "current"
    assert restarted.validate_page("alpha", "recover")["freshness"] == "current"


def test_page_pending_conflict_retains_manual_edit_and_draft(tmp_path, monkeypatch):
    knowledge = Knowledge(tmp_path)
    page = knowledge.write_page("alpha", "manual", "Original", None, [])
    original = knowledge._recover_page
    calls = 0

    def interrupted(page_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return original(page_id)

    monkeypatch.setattr(knowledge, "_recover_page", interrupted)
    with pytest.raises(KeyboardInterrupt):
        knowledge.write_page("alpha", "manual", "Pending draft", page["content_hash"], [])
    Path(page["path"]).write_text("Manual change")
    restarted = Knowledge(tmp_path)
    inspected = restarted.inspect_page("alpha", "manual")
    assert inspected["body"] == "Manual change"
    assert inspected["pending"]["body"] == "Pending draft"
    assert inspected["publication_error"]
    restarted.discard_pending_page("alpha", "manual", inspected["content_hash"])
    assert Path(page["path"]).read_text() == "Manual change"
    replacement = restarted.write_page(
        "alpha", "manual", "Merged draft", inspected["content_hash"], []
    )
    assert replacement["body"] == "Merged draft"


def test_symlink_and_path_escape_pages_are_rejected(tmp_path):
    knowledge = Knowledge(tmp_path / "library")
    outside = tmp_path / "outside.md"
    outside.write_text("Preserved")
    (knowledge.library.path / "knowledge" / "link.md").symlink_to(outside)
    for page_id in ("link", "../outside", "/absolute", "sub/page"):
        with pytest.raises(ValueError):
            knowledge.write_page("alpha", page_id, "Overwrite", None, [])
    assert outside.read_text() == "Preserved"


def test_backup_restore_retains_memories_revisions_receipts_pages_and_exports(tmp_path):
    source = tmp_path / "library"
    knowledge = Knowledge(source)
    knowledge.capture_enable("alpha")
    knowledge.capture_submit("alpha", "session:backup", [{"content": "Durable memory"}])
    record = knowledge.recall("alpha")["records"][0]
    knowledge.correct("alpha", record["id"], "Corrected durable memory", "Correction", 1)
    knowledge.write_page("alpha", "durable", "# Durable knowledge\n", None, [])
    backup(source, tmp_path / "backup")
    restore(tmp_path / "backup", tmp_path / "restored")
    restored = Knowledge(tmp_path / "restored")
    assert restored.inspect("alpha", record["id"])["revision"] == 2
    assert restored.capture_status("alpha")["events"][0]["state"] == "committed"
    exported = restored.export_page("alpha", "durable", str(tmp_path / "export"))
    assert (tmp_path / "export" / "durable.md").read_text() == "# Durable knowledge\n"
    assert exported["validation"]["assertions_certified"] is False
    with pytest.raises(FileExistsError):
        restored.export_page("alpha", "durable", str(tmp_path / "export"))


def test_forget_requires_explicit_ids_previews_and_preserves_pages(tmp_path):
    knowledge = Knowledge(tmp_path)
    record = knowledge.add("alpha", "Forget this")
    page = knowledge.write_page("alpha", "keep", "Keep this", None, [])
    preview = knowledge.forget("alpha", [record["id"]])
    assert preview["applied"] is False
    assert len(knowledge.recall("alpha")["records"]) == 1
    knowledge.forget("alpha", [record["id"]], apply=True)
    assert knowledge.recall("alpha")["records"] == []
    assert knowledge.inspect("alpha", record["id"])["state"] == "forgotten"
    assert knowledge.inspect_page("alpha", "keep")["content_hash"] == page["content_hash"]
    assert knowledge.export_memories("alpha")["records"] == []


def test_dispatch_uses_explicit_payload_and_returns_version(tmp_path):
    result = dispatch(tmp_path, "memory.add", {"project": "alpha", "content": "API observation"})
    assert result["schema_version"] == 1
    assert (
        dispatch(tmp_path, "memory.recall", {"project": "alpha"})["records"][0]["id"]
        == result["id"]
    )
    with pytest.raises(ValueError):
        dispatch(tmp_path, "knowledge.unknown", {})
    digest = hashlib.sha256(b"Page").hexdigest()
    assert (
        dispatch(
            tmp_path,
            "knowledge.write",
            {
                "project": "alpha",
                "page_id": "api",
                "body": "Page",
                "expected_hash": None,
                "citations": [],
            },
        )["content_hash"]
        == digest
    )
