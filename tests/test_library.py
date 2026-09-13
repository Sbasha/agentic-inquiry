"""Publication and recovery contracts through public library operations."""

import json
import sqlite3

import pytest
from test_store import Embeddings

from agentic_inquiry import store
from agentic_inquiry.library import Library, backup, restore


def test_multiple_collections_scope_relocation_and_detach(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_embedding_model", lambda *a, **kw: Embeddings())
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "same.md").write_text("copper ledger evidence")
    (b / "same.md").write_text("silver ledger evidence")
    db = tmp_path / "library"
    lib = Library(db)
    ca = lib.register(a, project_id="alpha")
    cb = lib.register(b, project_id="beta")
    assert ca["id"] != cb["id"]
    for c in (ca, cb):
        assert store.index(None, db, collection=c["id"])["complete"]
    rows = store.search(db, "ledger", mode="lexical", project="alpha")
    assert len(rows) == 1 and rows[0]["project_id"] == "alpha"
    with pytest.raises(ValueError, match="scope"):
        store.read(db, rows[0]["id"], project="beta")
    moved = tmp_path / "moved"
    a.rename(moved)
    lib.relocate(ca["id"], moved)
    assert lib.collection(ca["id"])["project_id"] == "alpha"
    assert store.read(db, rows[0]["id"])["freshness"] == "current"
    assert lib.detach(ca["id"])["applied"] is False
    lib.detach(ca["id"], True)
    assert not store.search(db, "ledger", mode="lexical", project="alpha")
    assert (moved / "same.md").exists()


def test_public_index_project_selects_only_its_collection(tmp_path, monkeypatch):
    from agentic_inquiry.cli import invoke

    monkeypatch.setattr(store, "_embedding_model", lambda *a, **kw: Embeddings())
    db = tmp_path / "library"
    lib = Library(db)
    for project in ("alpha", "beta"):
        root = tmp_path / project
        root.mkdir()
        (root / "notes.md").write_text(project + " ledger evidence", encoding="utf-8")
        lib.register(root, project_id=project)
    result = invoke(db, "index", {"project": "alpha"})
    assert result["complete"] and result["project_id"] == "alpha"
    assert result["changed"] == ["notes.md"]
    assert not store.search(db, "ledger", mode="lexical", project="beta")
    with lib.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 1


@pytest.mark.parametrize("by_root", [False, True])
def test_index_project_mismatch_refuses_before_source_processing(tmp_path, monkeypatch, by_root):
    from agentic_inquiry.cli import invoke

    db = tmp_path / "library"
    lib = Library(db)
    root = tmp_path / "source"
    root.mkdir()
    selected = lib.register(root, project_id="alpha")
    payload = (
        {"project": "beta", "root": str(root)}
        if by_root
        else {
            "project": "beta",
            "collection": selected["id"],
        }
    )
    monkeypatch.setattr(store, "_inventory", lambda *args: pytest.fail("Wrong project was scanned"))
    with pytest.raises(ValueError, match="project scope"):
        invoke(db, "index", payload)
    with lib.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 0
    assert lib.collection(selected["id"])["project_id"] == "alpha"


def test_first_index_records_explicit_project_and_rejects_ambiguous_scope(tmp_path, monkeypatch):
    from agentic_inquiry.cli import invoke

    monkeypatch.setattr(store, "_embedding_model", lambda *a, **kw: Embeddings())
    db = tmp_path / "library"
    root = tmp_path / "source"
    root.mkdir()
    (root / "notes.md").write_text("copper ledger evidence", encoding="utf-8")
    result = invoke(db, "index", {"root": str(root), "project": "alpha"})
    assert result["complete"] and result["project_id"] == "alpha"
    other = tmp_path / "other"
    other.mkdir()
    Library(db).register(other, project_id="alpha")
    with pytest.raises(ValueError, match="Select one"):
        invoke(db, "index", {"project": "alpha"})
    assert invoke(db, "index", {"project": "alpha", "collection": result["collection_id"]})[
        "unchanged"
    ] == ["notes.md"]


def test_failed_publication_leaves_orphans_ineligible(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_embedding_model", lambda *a, **kw: Embeddings())
    root = tmp_path / "source"
    root.mkdir()
    file = root / "notes.md"
    file.write_text("old bronze evidence")
    db = tmp_path / "library"
    assert store.index(root, db)["complete"]
    old = store.search(db, "bronze", mode="lexical")[0]
    file.write_text("new silver evidence")
    from lancedb.table import LanceTable

    original = LanceTable.create_index
    monkeypatch.setattr(
        LanceTable,
        "create_index",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("crash before publish")),
    )
    assert not store.index(root, db)["complete"]
    assert store.read(db, old["id"])["text"] == "old bronze evidence"
    assert not store.search(db, "silver", mode="vector")
    monkeypatch.setattr(LanceTable, "create_index", original)
    assert store.index(root, db)["complete"]
    assert store.search(db, "silver", mode="lexical")[0]["freshness"] == "current"
    assert store.read(db, old["id"])["publication_state"] == "superseded"


def test_backup_checksum_and_newer_schema_preserve_existing_library(tmp_path):
    db = tmp_path / "library"
    lib = Library(db)
    (lib.path / "knowledge" / "manual.md").write_text("authored durable body")
    snapshot = tmp_path / "backup"
    backup(db, snapshot)
    restored = tmp_path / "restored"
    restore(snapshot, restored)
    assert (restored / "knowledge" / "manual.md").read_text() == "authored durable body"
    (snapshot / "knowledge" / "manual.md").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        restore(snapshot, restored)
    assert (restored / "knowledge" / "manual.md").read_text() == "authored durable body"
    with sqlite3.connect(db / "records.sqlite3") as conn:
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="newer schema"):
        Library(db)
    assert (db / "knowledge" / "manual.md").read_text() == "authored durable body"


def test_exclusion_revokes_evidence_without_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_embedding_model", lambda *a, **kw: Embeddings())
    root = tmp_path / "source"
    root.mkdir()
    (root / "notes.md").write_text("private copper evidence")
    db = tmp_path / "library"
    assert store.index(root, db)["complete"]
    item = store.search(db, "copper", mode="lexical")[0]
    lib = Library(db)
    with lib.writer() as conn:
        conn.execute("UPDATE collections SET settings=?", (json.dumps({"exclude": ["notes.md"]}),))
    assert not store.search(db, "copper", mode="lexical", include_stale=True)
    with pytest.raises(ValueError, match="eligible"):
        store.read(db, item["id"])
