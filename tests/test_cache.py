"""Component checks of public cleanup and registration against filesystem libraries."""

import hashlib
import json
import sqlite3

import pytest
from filelock import Timeout

from agentic_inquiry.cli import invoke, main
from agentic_inquiry.library import Library


def test_cli_preview_and_cleanup_preserve_published_and_authored_data(tmp_path, capsys):
    db = tmp_path / "library"
    Library(db)
    memory = invoke(db, "memory.add", {"project": "review", "content": "Retain authored records"})
    invoke(
        db,
        "knowledge.write",
        {
            "project": "review",
            "page_id": "notes",
            "body": "Editable knowledge",
            "expected_hash": None,
            "citations": [],
        },
    )
    for name in ("initial", "a" * 32, "operator-backup"):
        directory = db / "index" / name
        directory.mkdir(parents=True)
        (directory / "data").write_bytes(name.encode())
    backup = db / "legacy-backup"
    backup.mkdir()
    (backup / "config.json").write_text("{}")
    before = hashlib.sha256((db / "records.sqlite3").read_bytes()).hexdigest()
    assert main(["cache", "clean", "--db", str(db)]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["applied"] is False
    assert [item["path"] for item in preview["candidates"]] == ["index/" + "a" * 32]
    assert (db / "index" / ("a" * 32) / "data").exists()
    assert main(["cache", "clean", "--db", str(db), "--apply"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["removed"] == ["index/" + "a" * 32]
    assert applied["active_generation_orphan_rows_removed"] == 0
    assert not (db / "index" / ("a" * 32)).exists()
    assert (db / "index/initial/data").read_bytes() == b"initial"
    assert (db / "index/operator-backup/data").read_bytes() == b"operator-backup"
    assert (backup / "config.json").read_text() == "{}"
    assert (db / "knowledge/notes.md").read_text() == "Editable knowledge"
    assert hashlib.sha256((db / "records.sqlite3").read_bytes()).hexdigest() == before
    assert (
        invoke(db, "memory.inspect", {"project": "review", "memory_id": memory["id"]})["content"]
        == memory["content"]
    )


def test_models_require_selection_and_symlink_targets_are_preserved(tmp_path):
    db = tmp_path / "library"
    lib = Library(db)
    model = db / "models"
    model.mkdir()
    original = tmp_path / "original-model"
    original.write_bytes(b"source model bytes")
    (model / "snapshot.onnx").symlink_to(original)
    inactive_symlink = db / "index" / ("a" * 32)
    inactive_symlink.parent.mkdir()
    inactive_symlink.symlink_to(tmp_path, target_is_directory=True)
    with lib.writer() as conn:
        conn.execute("INSERT INTO metadata VALUES('embedding_identity',?)", ('{"model":"local"}',))
    assert invoke(db, "cache.clean", {"apply": True})["candidates"] == []
    assert model.exists()
    preview = invoke(db, "cache.clean", {"models": True})
    assert [entry["path"] for entry in preview["candidates"]] == ["models"]
    assert preview["retained"][0]["path"] == "index/" + "a" * 32
    assert invoke(db, "cache.clean", {"apply": True, "models": True})["removed"] == ["models"]
    assert original.read_bytes() == b"source model bytes"
    assert inactive_symlink.is_symlink()
    with lib.connection() as conn:
        assert (
            conn.execute("SELECT value FROM metadata WHERE key='embedding_identity'").fetchone()[0]
            == '{"model":"local"}'
        )


def test_active_read_snapshot_blocks_cleanup_without_deletion(tmp_path, capsys):
    db = tmp_path / "library"
    lib = Library(db)
    inactive = db / "index" / ("b" * 32)
    inactive.mkdir(parents=True)
    with lib.connection() as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()
        assert main(["cache", "clean", "--db", str(db), "--apply"]) == 2
        assert json.loads(capsys.readouterr().err)["type"] == "OperationalError"
        assert inactive.exists()
    assert invoke(db, "cache.clean", {"apply": True})["removed"] == ["index/" + "b" * 32]


def test_writer_contention_and_wal_mode_preserve_candidates(tmp_path):
    db = tmp_path / "library"
    lib = Library(db)
    inactive = db / "index" / ("c" * 32)
    inactive.mkdir(parents=True)
    with lib.writer(), pytest.raises(Timeout):
        invoke(db, "cache.clean", {"apply": True})
    assert inactive.exists()
    with sqlite3.connect(db / "records.sqlite3") as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    assert invoke(db, "cache.clean", {})["candidates"]
    with pytest.raises(ValueError, match="read snapshots in WAL"):
        invoke(db, "cache.clean", {"apply": True})
    assert inactive.exists()


def test_failed_disposable_removal_reports_partial_scope(tmp_path, monkeypatch):
    from agentic_inquiry import cache

    db = tmp_path / "library"
    Library(db)
    inactive = db / "index" / ("a" * 32)
    inactive.mkdir(parents=True)
    model = db / "models"
    model.mkdir()
    remove = cache.shutil.rmtree

    def fail_one(path):
        if path == inactive:
            raise OSError("Cache entry is locked")
        remove(path)

    monkeypatch.setattr(cache.shutil, "rmtree", fail_one)
    result = invoke(db, "cache.clean", {"apply": True, "models": True})
    assert result["complete"] is False and result["status"] == "partial"
    assert result["removed"] == ["models"]
    assert result["failed"][0]["path"] == "index/" + "a" * 32
    assert inactive.exists()
    assert (db / "records.sqlite3").exists()


def test_cleanup_does_not_initialize_missing_library(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError, match="existing library"):
        invoke(missing, "cache.clean", {})
    assert not missing.exists()


@pytest.mark.parametrize(
    "settings",
    [
        [],
        "invalid",
        {"include": "*.md"},
        {"exclude": [1]},
        {"parser": []},
        {"parser": None},
        {"parser": {"ocr": "yes"}},
        {"unknown": True},
    ],
)
def test_register_rejects_invalid_settings_without_registering(tmp_path, settings):
    source = tmp_path / "source"
    source.mkdir()
    db = tmp_path / "library"
    with pytest.raises((ValueError, TypeError)):
        invoke(db, "collection.register", {"root": str(source), "settings": settings})
    assert invoke(db, "collection.list", {})["collections"] == []


def test_registration_and_configuration_return_consistent_settings(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    db = tmp_path / "library"
    settings = {"include": ["*.md"], "parser": {"ocr": False}}
    payload = {"root": str(source), "settings": settings}
    registered = invoke(db, "collection.register", payload)
    repeated = invoke(db, "collection.register", payload)
    configured = invoke(
        db, "collection.configure", {"collection": registered["id"], "settings": settings}
    )
    listed = invoke(db, "collection.list", {})["collections"][0]
    assert registered == repeated == configured == listed
    assert registered["settings"] == settings
    with pytest.raises(TypeError, match="parser settings must be an object"):
        invoke(
            db, "collection.configure", {"collection": registered["id"], "settings": {"parser": []}}
        )
    assert invoke(db, "collection.inspect", {"collection": registered["id"]}) == registered
