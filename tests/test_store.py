"""Public API component checks with real Lance storage and injected embeddings."""

import subprocess
from types import SimpleNamespace

import pytest

from agentic_inquiry import store


class Tokenizer:
    @classmethod
    def from_str(cls, _):
        return cls()

    def to_str(self):
        return "tokenizer"

    def no_truncation(self):
        pass

    def no_padding(self):
        pass

    def encode(self, text):
        return SimpleNamespace(ids=list(text))


class Embeddings:
    model = SimpleNamespace(tokenizer=Tokenizer())

    def passage_embed(self, texts):
        for text in texts:
            vector = [0.0] * store.DIMENSIONS
            for character in text.lower():
                vector[ord(character) % store.DIMENSIONS] += 1
            yield vector

    def query_embed(self, query):
        return self.passage_embed([query])


@pytest.fixture
def collection(tmp_path, monkeypatch):
    root = tmp_path / "sources"
    root.mkdir()
    db = tmp_path / "index"
    calls = []

    def model(_, *, download):
        calls.append(download)
        return Embeddings()

    monkeypatch.setattr(store, "_embedding_model", model)
    return root, db, calls


def test_index_search_read_update_delete_and_preserve_source(collection):
    root, db, calls = collection
    first = root / "payments.py"
    other = root / "notes.md"
    first.write_text("def refund_payment():\n    return 'refund copper'\n")
    other.write_text("# Bookkeeping\nLedger audit evidence remains available.\n")
    report = store.index(root, db)
    assert report["complete"], report
    assert len(report["changed"]) == 2
    for mode in ("lexical", "vector", "hybrid"):
        rows = store.search(db, "refund", mode=mode)
        assert rows[0]["path"] == "payments.py"
        assert rows[0]["freshness"] == "current"
    original = store.search(db, "refund", mode="lexical")[0]
    assert store.read(db, original["id"])["text"] in first.read_text()
    assert original["line_start"] == 1 and original["line_end"] == 2
    assert any(download is False for download in calls)
    assert store.index(root, db)["unchanged"] == ["notes.md", "payments.py"]

    first.write_text("def invoice_payment():\n    return 'invoice silver'\n")
    assert store.read(db, original["id"])["freshness"] == "changed"
    assert store.index(root, db)["complete"]
    assert store.search(db, "refund", mode="lexical") == []
    assert store.search(db, "invoice", mode="lexical")[0]["freshness"] == "current"
    assert store.read(db, original["id"])["publication_state"] == "superseded"
    assert store.search(db, "ledger", mode="lexical")[0]["path"] == "notes.md"

    first.unlink()
    assert store.status(db)["stale_sources"] == [{"path": "payments.py", "freshness": "missing"}]
    assert store.index(root, db)["removed"] == ["payments.py"]
    result = store.remove(db, "notes.md")
    assert result["source_preserved"] and other.exists()
    assert store.status(db)["sources"] == 0


def test_embedding_failure_keeps_prior_rows_and_does_not_prune(collection, monkeypatch):
    root, db, _ = collection
    (root / "a.md").write_text("preserved original evidence")
    (root / "b.md").write_text("temporarily missing evidence")
    assert store.index(root, db)["complete"]
    original = store.search(db, "preserved", mode="lexical")[0]
    (root / "a.md").write_text("replacement evidence")
    (root / "b.md").unlink()

    class Broken(Embeddings):
        def passage_embed(self, texts):
            raise RuntimeError("Injected embedding failure")

    monkeypatch.setattr(store, "_embedding_model", lambda *a, **k: Broken())
    report = store.index(root, db)
    assert not report["complete"] and not report["removed"]
    assert store.read(db, original["id"])["text"] == "preserved original evidence"
    assert store.read(db, original["id"])["freshness"] == "changed"
    assert store.status(db)["sources"] == 2
    assert store.status(db)["last_index"]["failed"]


def test_reduced_structure_remains_searchable_and_parser_change_refreshes(collection):
    from agentic_inquiry.cli import invoke

    root, db, _ = collection
    (root / "unfinished.py").write_text("def unfinished(:\n    return 'recoverable evidence'\n")
    report = store.index(root, db)
    assert not report["complete"] and report["reduced_coverage"]
    assert not report["failed"] and report["changed"] == ["unfinished.py"]
    found = store.search_report(db, "recoverable", mode="lexical")
    assert found["results"][0]["path"] == "unfinished.py"
    assert not found["coverage"]["retrieval_complete"]
    again = store.index(root, db)
    assert again["unchanged"] == ["unfinished.py"] and again["reduced_coverage"]
    invoke(
        db,
        "collection.configure",
        {"collection": report["collection_id"], "settings": {"parser": {"max_nodes": 10000}}},
    )
    refreshed = store.index(root, db)
    assert refreshed["changed"] == ["unfinished.py"] and not refreshed["unchanged"]


def test_incomplete_inventory_does_not_mutate_index(collection, monkeypatch):
    root, db, _ = collection
    (root / "a.md").write_text("retained evidence")
    assert store.index(root, db)["complete"]
    before = store.search(db, "retained", mode="lexical")

    def unavailable(*args):
        raise RuntimeError("Unreadable source directory")

    monkeypatch.setattr(store, "_inventory", unavailable)
    report = store.index(root, db)
    assert not report["complete"]
    assert not report["changed"] and not report["removed"]
    assert store.search(db, "retained", mode="lexical") == before


def test_private_binary_and_symlink_sources_are_not_read(collection):
    root, db, _ = collection
    outside = root.parent / "outside.txt"
    outside.write_text("outside-needle")
    (root / "link.md").symlink_to(outside)
    (root / ".env").write_text("secret-needle")
    (root / "credentials.json").write_text("secret-needle")
    (root / ".pi").mkdir()
    (root / ".pi/settings.json").write_text('{"session": "secret-needle"}')
    (root / "binary.txt").write_bytes(b"binary-needle\0")
    (root / "safe.md").write_text("ordinary evidence")
    report = store.index(root, db)
    assert {row["path"] for row in report["skipped"]} >= {".env", "credentials.json"}
    assert store.status(db)["sources"] == 1
    assert store.search(db, "needle", mode="lexical") == []
    assert outside.read_text() == "outside-needle"


def test_long_lines_remain_complete_and_citations_match(collection):
    root, db, _ = collection
    text = "# Start\n" + "verylongidentifier " * 150 + "\nfinal evidence\n"
    (root / "long.md").write_text(text)
    assert store.index(root, db)["complete"]
    rows = store.search(db, "verylongidentifier", limit=100, mode="lexical")
    assert len(rows) > 1
    for row in rows:
        assert len(row["text"]) <= store.MAX_TOKENS
        source_lines = text.splitlines(keepends=True)
        citation_text = "".join(source_lines[row["line_start"] - 1 : row["line_end"]])
        assert row["text"] in citation_text
        assert row["freshness"] == "current"


def test_wrong_root_bad_id_and_configuration_are_rejected(collection):
    root, db, _ = collection
    (root / "a.md").write_text("valid evidence")
    assert store.index(root, db)["complete"]
    other = root.parent / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="another source root"):
        store.index(other, db)
    with pytest.raises(ValueError):
        store.remove(db, "../outside.md")
    with pytest.raises(ValueError):
        store.read(db, "' OR true")
    with pytest.raises(ValueError):
        store.search(db, "valid", mode="unrecognized")
    from agentic_inquiry.library import Library

    with Library(db).writer() as conn:
        conn.execute(
            "UPDATE metadata SET value=? WHERE key='index_identity'", ('{"dimensions":12}',)
        )
    with pytest.raises(ValueError, match="Incompatible"):
        store.status(db)


def test_git_ignored_files_and_deleted_tracked_file(collection):
    root, db, _ = collection
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("ignored.md\n")
    (root / "ignored.md").write_text("ignored-needle")
    source = root / "auth.py"
    source.write_text("def authorize_request():\n    return 'authorization evidence'\n")
    subprocess.run(["git", "-C", str(root), "add", "auth.py"], check=True)
    assert store.index(root, db)["complete"]
    assert store.status(db)["sources"] == 1
    assert store.search(db, "authorization", mode="lexical")[0]["path"] == "auth.py"
    source.unlink()
    report = store.index(root, db)
    assert report["complete"] and report["removed"] == ["auth.py"]
    assert store.status(db)["sources"] == 0


def test_model_initialization_failure_is_not_retried_per_file(collection, monkeypatch):
    root, db, _ = collection
    for name in ("a.md", "b.md", "c.md"):
        (root / name).write_text("candidate evidence")
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("Model cannot be prepared")

    monkeypatch.setattr(store, "_embedding_model", unavailable)
    result = store.index(root, db)
    assert len(calls) == 1
    assert len(result["failed"]) == 1 and len(result["unattempted"]) == 2
    assert not result["complete"]


def test_fts_failure_is_visible_and_preserves_readable_source(collection, monkeypatch):
    from lancedb.table import LanceTable

    root, db, _ = collection
    (root / "a.md").write_text("original evidence")
    assert store.index(root, db)["complete"]
    original = store.search(db, "original", mode="lexical")[0]

    def fail(*args, **kwargs):
        raise RuntimeError("Injected index failure")

    monkeypatch.setattr(LanceTable, "create_index", fail)
    result = store.index(root, db)
    assert not result["complete"] and not result["fts_ready"]
    assert store.search(db, "original", mode="hybrid")[0]["id"] == original["id"]
    assert store.read(db, original["id"])["text"] == "original evidence"
    assert store.search(db, "original", mode="vector")


def test_interrupted_preparation_retains_original_passage(collection, monkeypatch):
    root, db, _ = collection
    source = root / "a.md"
    source.write_text("original evidence")
    assert store.index(root, db)["complete"]
    original = store.search(db, "original", mode="lexical")[0]
    source.write_text("replacement evidence")

    class Interrupted(Embeddings):
        def passage_embed(self, texts):
            raise KeyboardInterrupt

    monkeypatch.setattr(store, "_embedding_model", lambda *a, **k: Interrupted())
    with pytest.raises(KeyboardInterrupt):
        store.index(root, db)
    assert store.read(db, original["id"])["text"] == "original evidence"
    assert store.status(db)["last_index"]["complete"] is False


def test_writer_lock_prevents_competing_root_and_removal(collection):
    from filelock import FileLock, Timeout

    root, db, _ = collection
    source = root / "a.md"
    source.write_text("original evidence")
    assert store.index(root, db)["complete"]
    with FileLock(db / "write.lock"):
        with pytest.raises(Timeout):
            store.remove(db, "a.md")
        with pytest.raises(Timeout):
            store.index(root, db)
    assert store.status(db)["sources"] == 1
    assert source.read_text() == "original evidence"
