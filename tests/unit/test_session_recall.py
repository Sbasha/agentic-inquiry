"""Session recall: a later correction wins, and an abstention is not a miss."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agentic_inquiry.integration.session_recall import (
    Item,
    has_question,
    items_from_turns,
    select_items,
    warm_search,
)
from agentic_inquiry.integration.state import Binding
from tests.golden.session_bench import NOT_MEASURED, run
from tests.golden.sessions import load_sessions

SESSIONS = Path(__file__).resolve().parents[1] / "golden" / "sessions.json"


def test_frozen_sessions_load_and_recall() -> None:
    report = run(SESSIONS)
    assert report["abstentions"] == 1
    assert report["evidence_recall_at_10"] == 1.0
    correction = next(row for row in report["sessions"] if row["id"] == "correction")
    assert correction["retrieved"][0] == "correction.new"
    assert "correction.old" not in correction["retrieved"]
    abstain = next(row for row in report["sessions"] if row["id"] == "abstain")
    assert abstain["evidence_recall_at_10"] is None


def test_a_question_without_a_relevant_id_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_text(
        '{"sessions":[{"id":"bare","turns":[{"id":"a","content":"fact"},'
        '{"role":"question","query":"fact?","relevant":[]}]}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no relevant id"):
        load_sessions(path)


def test_only_the_matching_wording_is_kept_when_the_correction_does_not_match() -> None:
    turns = [
        {
            "id": "old",
            "subject": "name",
            "content": "The codename is kettle.",
            "created": "0001",
        },
        {
            "id": "new",
            "subject": "name",
            "content": "The port is 8765.",
            "created": "0002",
        },
    ]
    chosen = [item.id for item in select_items("kettle", items_from_turns(turns))]
    assert chosen == ["old"]


def test_warm_search_does_not_start_a_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INQUIRY_HOME", str(tmp_path))
    assert warm_search("ledger key", timeout=0.2) is None


def test_a_second_copy_of_the_same_chunk_is_dropped() -> None:
    items = [
        Item(
            id="old-copy",
            text="The release codename is harbor.",
            created="0001",
            kind="memory",
        ),
        Item(
            id="new-copy",
            text="The release codename is harbor.",
            created="0002",
            kind="memory",
        ),
        Item(
            id="noise",
            text="The linter runs on the pre-push hook.",
            created="0003",
            kind="memory",
        ),
    ]
    chosen = [item.id for item in select_items("What is the release codename?", items)]
    assert chosen == ["new-copy"]


def test_two_spans_in_one_file_both_stay() -> None:
    first = Item(
        id="span-a",
        text="alpha token",
        created="",
        kind="evidence",
        score=1.0,
        entry={"data": {"file_path": "notes.md", "start_line": 1, "end_line": 2}},
    )
    second = Item(
        id="span-b",
        text="beta token",
        created="",
        kind="evidence",
        score=0.5,
        entry={"data": {"file_path": "notes.md", "start_line": 9, "end_line": 10}},
    )
    same = Item(
        id="span-a-copy",
        text="alpha token again",
        created="",
        kind="evidence",
        score=2.0,
        entry={"data": {"file_path": "notes.md", "start_line": 1, "end_line": 2}},
    )
    chosen = [item.id for item in select_items("token", [first, second, same])]
    assert chosen == ["span-a-copy", "span-b"]


def test_a_prompt_with_no_content_token_is_not_a_question() -> None:
    assert has_question("ok") is False
    assert has_question("the") is False
    assert has_question("   ") is False
    assert has_question("How is the ledger key formed?") is True
    assert has_question("jwt") is True


def test_labelled_sessions_cover_document_and_code_and_stay_under_history() -> None:
    report = run(SESSIONS)
    by_id = {row["id"]: row for row in report["sessions"]}
    assert by_id["document"]["retrieved"][0] == "document.spec"
    assert by_id["code-location"]["retrieved"][0] == "code.bind"
    assert all(not row["byte_regression"] for row in report["sessions"])
    assert report["arms"]["session_lexical"]["evidence_recall_at_10"] == 1.0
    assert report["arms"]["session_lexical"]["embedder"] is False
    for name, reason in NOT_MEASURED.items():
        cell = report["arms"]["not_measured"][name]
        assert cell == {"status": "not_measured", "reason": reason}
        assert "evidence_recall_at_10" not in cell


def test_a_repeated_question_reuses_the_ranked_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agentic_inquiry.integration.hooks import _prompt_entries

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("INQUIRY_HOME", str(home))
    calls: list[str] = []

    def warm(query: str, *, timeout: float) -> list[dict[str, object]]:
        calls.append(query)
        return []

    monkeypatch.setattr("agentic_inquiry.integration.session_recall.warm_search", warm)
    ledger = _Rows([_capture("The release codename is harbor.")])
    binding = _binding(tmp_path)
    query = "What is the release codename?"
    started = time.perf_counter()
    first = _prompt_entries(ledger, binding, query, tmp_path, 9.0, started)
    second = _prompt_entries(ledger, binding, query, tmp_path, 9.0, started)
    assert calls == [query]
    assert first[0] and first[0] == second[0]
    assert first[2] is False
    ledger.rows[0]["payload"] = json.dumps(
        [
            {
                "content": "The release codename is kettle.",
                "metadata": {"subject": "codename"},
            }
        ]
    )
    _prompt_entries(ledger, binding, query, tmp_path, 9.0, started)
    assert calls == [query, query]


def test_evidence_is_not_cached_without_a_manifest_stamp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agentic_inquiry.integration.hooks import _prompt_entries

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("INQUIRY_HOME", str(home))
    note = tmp_path / "notes.md"
    note.write_text("harbor codename\n", encoding="utf-8")
    store = tmp_path / ".agentic-inquiry" / "lancedb" / "not-a-table"
    store.mkdir(parents=True)
    calls: list[int] = []

    def warm(query: str, *, timeout: float) -> list[dict[str, object]]:
        calls.append(1)
        return [{"file_path": "notes.md", "content": "harbor codename", "score": 1.0}]

    monkeypatch.setattr("agentic_inquiry.integration.session_recall.warm_search", warm)
    ledger = _Rows([])
    binding = _binding(tmp_path)
    started = time.perf_counter()
    _prompt_entries(ledger, binding, "harbor codename", tmp_path, 9.0, started)
    _prompt_entries(ledger, binding, "harbor codename", tmp_path, 9.0, started)
    assert calls == [1, 1]


def test_evidence_cache_follows_the_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agentic_inquiry.integration.hooks import _prompt_entries

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("INQUIRY_HOME", str(home))
    note = tmp_path / "notes.md"
    note.write_text("harbor codename\n", encoding="utf-8")
    versions = tmp_path / ".agentic-inquiry" / "lancedb" / "chunks.lance" / "_versions"
    versions.mkdir(parents=True)
    manifest = versions / "1.manifest"
    manifest.write_bytes(b"one")
    calls: list[int] = []

    def warm(query: str, *, timeout: float) -> list[dict[str, object]]:
        calls.append(1)
        return [
            {
                "file_path": "notes.md",
                "content": "harbor codename",
                "score": 1.0,
                "start_line": 1,
                "end_line": 1,
            }
        ]

    monkeypatch.setattr("agentic_inquiry.integration.session_recall.warm_search", warm)
    ledger = _Rows([])
    binding = _binding(tmp_path)
    query = "harbor codename"
    started = time.perf_counter()
    first = _prompt_entries(ledger, binding, query, tmp_path, 9.0, started)
    second = _prompt_entries(ledger, binding, query, tmp_path, 9.0, started)
    assert len(calls) == 1
    assert first[0][0]["data"]["file_path"] == "notes.md"
    assert second[0] == first[0]
    note.unlink()
    third = _prompt_entries(ledger, binding, query, tmp_path, 9.0, started)
    assert len(calls) == 1
    assert third[0] == []
    note.write_text("harbor codename\n", encoding="utf-8")
    manifest.write_bytes(b"rewritten-manifest")
    _prompt_entries(ledger, binding, query, tmp_path, 9.0, started)
    assert len(calls) == 2


class _Rows:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def capture_rows(self, owner: str, clients: list[str]) -> list[dict[str, str]]:
        return self.rows

    def enabled_clients(self, owner: str) -> list[str]:
        return ["claude-code"]


def _capture(content: str) -> dict[str, str]:
    return {
        "key": "abc",
        "kind": "capture",
        "client": "claude-code",
        "owner": "afp",
        "created_at": "2026-09-23T00:00:00Z",
        "payload": json.dumps(
            [{"content": content, "metadata": {"subject": "codename"}}]
        ),
    }


def _binding(root: Path) -> Binding:
    return Binding(
        project_id="ab" * 8,
        client="claude-code",
        owner="afp",
        enabled=True,
        project_root=str(root),
        config_path="",
        storage_project_id="proj",
        policy={"recall": True, "context_budget": 2048},
    )
