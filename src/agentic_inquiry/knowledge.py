"""Scoped durable observations, capture receipts and editable cited Markdown."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

KINDS = {"observation", "decision", "preference", "correction"}
ORIGINS = {"user", "extracted", "agent"}
MAX_TEXT = 1_000_000
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS memory_records (
        id TEXT PRIMARY KEY, project TEXT NOT NULL, scope TEXT NOT NULL,
        kind TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL,
        superseded_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS memory_revisions (
        memory_id TEXT NOT NULL REFERENCES memory_records(id), revision INTEGER NOT NULL,
        content TEXT NOT NULL, origin TEXT NOT NULL, provenance TEXT NOT NULL,
        citations TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL,
        PRIMARY KEY(memory_id, revision))""",
    """CREATE TABLE IF NOT EXISTS memory_conflicts (
        left_id TEXT NOT NULL REFERENCES memory_records(id),
        right_id TEXT NOT NULL REFERENCES memory_records(id),
        reason TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(left_id, right_id))""",
    """CREATE TABLE IF NOT EXISTS capture_config (
        project TEXT PRIMARY KEY, enabled INTEGER NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS capture_events (
        project TEXT NOT NULL, event_id TEXT NOT NULL, input_hash TEXT NOT NULL,
        payload TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        record_ids TEXT NOT NULL DEFAULT '[]', error TEXT, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(project, event_id))""",
    """CREATE TABLE IF NOT EXISTS knowledge_pages (
        id TEXT PRIMARY KEY, project TEXT NOT NULL, scope TEXT NOT NULL,
        digest TEXT NOT NULL, citations TEXT NOT NULL, dependencies TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS knowledge_pending (
        page_id TEXT PRIMARY KEY, project TEXT NOT NULL, scope TEXT NOT NULL,
        expected_hash TEXT, digest TEXT NOT NULL, body TEXT NOT NULL,
        citations TEXT NOT NULL, dependencies TEXT NOT NULL, created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS memory_scope_state ON memory_records(project,scope,state,updated_at)",
    "CREATE INDEX IF NOT EXISTS capture_project_state ON capture_events(project,state)",
)


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(value: str, name: str, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise ValueError(f"{name} must be nonempty text within {maximum} bytes")
    return value


def _project(project: str) -> str:
    return _text(project, "project", 200)


def _flag(value: bool, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be explicitly true or false")
    return value


class Knowledge:
    """All mutation and scope checks shared by CLI and native client transports."""

    def __init__(self, db_path: Path, reader: Callable[[str], dict] | None = None):
        from .library import Library

        self.library = Library(Path(db_path))
        self.reader = reader
        with self.library.writer() as connection:
            for statement in SCHEMA:
                connection.execute(statement)

    def _read(self, chunk_id: str) -> dict:
        if self.reader:
            return self.reader(chunk_id)
        from .store import read

        return read(self.library.path, chunk_id)

    def _citations(self, citations: list[dict], project: str, shared: bool) -> list[dict]:
        if not isinstance(citations, list) or len(citations) > 1000:
            raise ValueError("citations must be a list of at most 1000 structured citations")
        checked = []
        required = {"id", "collection_id", "source_id", "source_version", "source_hash", "location"}
        for original in citations:
            if not isinstance(original, dict) or not required.issubset(original):
                raise ValueError(
                    "Citation requires id, collection_id, source_id, source_version, source_hash and location"
                )
            citation = {key: original[key] for key in required}
            for key in required - {"location"}:
                _text(citation[key], f"citation {key}", 300)
            if not isinstance(citation["location"], dict) or not citation["location"]:
                raise ValueError("Citation location must be a nonempty structured location")
            try:
                evidence = self._read(citation["id"])
            except (OSError, ValueError, RuntimeError) as error:
                checked.append({**citation, "status": "unresolved", "reason": type(error).__name__})
                continue
            identity = evidence.get("citation")
            identity = identity if isinstance(identity, dict) else evidence
            for key in required:
                actual = identity.get(key, evidence.get(key))
                if actual is None:
                    raise ValueError(f"Indexed evidence does not expose citation {key}")
                if actual != citation[key]:
                    raise ValueError(f"Citation {key} does not match indexed evidence")
            source_project = evidence.get("project_id", identity.get("project_id"))
            source_scope = evidence.get("scope", identity.get("scope", "project"))
            if source_project is None:
                checked.append(
                    {**citation, "status": "unresolved", "reason": "source scope unavailable"}
                )
                continue
            if source_project != project and not (shared and source_scope == "shared"):
                raise ValueError("Citation is outside the selected project scope")
            freshness = evidence.get("freshness", "unavailable")
            publication = evidence.get("publication_state", "published")
            checked.append(
                {
                    **citation,
                    "status": "current"
                    if freshness == "current" and publication == "published"
                    else "stale",
                    "freshness": freshness,
                    "publication_state": publication,
                }
            )
        return checked

    def _prepare_memory(
        self,
        project: str,
        content: str,
        kind: str = "observation",
        origin: str = "user",
        provenance: dict | None = None,
        citations: list[dict] | None = None,
        shared: bool = False,
    ) -> dict:
        _project(project)
        _text(content, "content", 65_536)
        if kind not in KINDS or origin not in ORIGINS:
            raise ValueError(
                "Use an observation/decision/preference/correction and user/extracted/agent origin"
            )
        provenance = {} if provenance is None else provenance
        if not isinstance(provenance, dict) or len(_json(provenance).encode()) > 16_384:
            raise ValueError("provenance must be a bounded object")
        _flag(shared, "shared")
        if origin == "extracted" and not citations:
            raise ValueError("Extracted observations require source citations")
        return {
            "project": project,
            "content": content,
            "kind": kind,
            "origin": origin,
            "provenance": provenance,
            "citations": self._citations(citations or [], project, shared),
            "scope": "shared" if shared else "project",
        }

    @staticmethod
    def _insert_memory(connection: sqlite3.Connection, prepared: dict) -> str:
        memory_id, now = str(uuid.uuid4()), _now()
        connection.execute(
            "INSERT INTO memory_records VALUES (?, ?, ?, ?, 'active', 1, NULL, ?, ?)",
            (memory_id, prepared["project"], prepared["scope"], prepared["kind"], now, now),
        )
        connection.execute(
            "INSERT INTO memory_revisions VALUES (?, 1, ?, ?, ?, ?, NULL, ?)",
            (
                memory_id,
                prepared["content"],
                prepared["origin"],
                _json(prepared["provenance"]),
                _json(prepared["citations"]),
                now,
            ),
        )
        return memory_id

    def add(self, project: str, content: str, **kwargs) -> dict:
        prepared = self._prepare_memory(project, content, **kwargs)
        with self.library.writer() as connection:
            memory_id = self._insert_memory(connection, prepared)
        return self.inspect(project, memory_id, include_shared=prepared["scope"] == "shared")

    @staticmethod
    def _owned(connection, project: str, memory_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM memory_records WHERE id=? AND project=?", (memory_id, _project(project))
        ).fetchone()
        if row is None:
            raise FileNotFoundError("Memory does not exist in the selected project")
        return row

    def inspect(self, project: str, memory_id: str, include_shared: bool = False) -> dict:
        _project(project)
        _flag(include_shared, "include_shared")
        with self.library.connection() as connection:
            record = connection.execute(
                "SELECT * FROM memory_records WHERE id=? AND ((project=? AND scope='project') OR (scope='shared' AND ?))",
                (memory_id, project, int(include_shared)),
            ).fetchone()
            if record is None:
                raise FileNotFoundError("Memory does not exist in the selected scope")
            revisions = connection.execute(
                "SELECT * FROM memory_revisions WHERE memory_id=? ORDER BY revision", (memory_id,)
            ).fetchall()
        result = dict(record)
        result["revisions"] = []
        for revision in revisions:
            item = dict(revision)
            item["provenance"] = json.loads(item["provenance"])
            item["citations"] = self._citations(
                json.loads(item["citations"]), record["project"], record["scope"] == "shared"
            )
            result["revisions"].append(item)
        result.update(
            {
                key: result["revisions"][-1][key]
                for key in ("content", "origin", "provenance", "citations")
            }
        )
        result["freshness"] = _freshness(result["citations"])
        return result

    def recall(
        self,
        project: str,
        query: str = "",
        include_shared: bool = False,
        limit: int = 50,
        include_stale: bool = False,
    ) -> dict:
        _project(project)
        _flag(include_shared, "include_shared")
        _flag(include_stale, "include_stale")
        if not isinstance(query, str) or not 1 <= limit <= 1000:
            raise ValueError("Use a text query and limit from 1 to 1000")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.library.connection() as connection:
            rows = connection.execute(
                """SELECT m.id FROM memory_records m JOIN memory_revisions r
                ON m.id=r.memory_id AND m.revision=r.revision
                WHERE m.state='active' AND ((m.project=? AND m.scope='project') OR (m.scope='shared' AND ?))
                AND r.content LIKE ? ESCAPE '\\' ORDER BY m.updated_at DESC, m.id LIMIT ?""",
                (project, int(include_shared), f"%{escaped}%", limit + 1),
            ).fetchall()
        records = [self.inspect(project, row["id"], include_shared) for row in rows[:limit]]
        omitted = []
        if not include_stale:
            omitted = [
                {"id": record["id"], "freshness": record["freshness"]}
                for record in records
                if record["freshness"] not in {"current", "not_source_backed"}
            ]
            records = [
                record
                for record in records
                if record["freshness"] in {"current", "not_source_backed"}
            ]
        return {
            "project": project,
            "include_shared": include_shared,
            "records": records,
            "omitted": omitted,
            "truncated": len(rows) > limit,
        }

    def correct(
        self,
        project: str,
        memory_id: str,
        content: str,
        reason: str,
        expected_revision: int,
        origin: str = "user",
        provenance: dict | None = None,
        citations: list[dict] | None = None,
    ) -> dict:
        _text(reason, "correction reason", 4096)
        with self.library.connection() as connection:
            previous = self._owned(connection, project, memory_id)
        prepared = self._prepare_memory(
            project,
            content,
            "correction",
            origin,
            provenance,
            citations,
            previous["scope"] == "shared",
        )
        with self.library.writer() as connection:
            previous = self._owned(connection, project, memory_id)
            if previous["state"] != "active" or previous["revision"] != expected_revision:
                raise ValueError("Correction requires the current active revision")
            revision, now = expected_revision + 1, _now()
            connection.execute(
                "INSERT INTO memory_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory_id,
                    revision,
                    content,
                    origin,
                    _json(prepared["provenance"]),
                    _json(prepared["citations"]),
                    reason,
                    now,
                ),
            )
            connection.execute(
                "UPDATE memory_records SET revision=?, kind='correction', updated_at=? WHERE id=?",
                (revision, now, memory_id),
            )
        return self.inspect(project, memory_id, include_shared=previous["scope"] == "shared")

    def supersede(
        self,
        project: str,
        memory_id: str,
        content: str,
        reason: str,
        expected_revision: int,
        **kwargs,
    ) -> dict:
        _text(reason, "supersession reason", 4096)
        with self.library.connection() as connection:
            previous = self._owned(connection, project, memory_id)
        kwargs["shared"] = previous["scope"] == "shared"
        kwargs.setdefault("kind", "correction")
        prepared = self._prepare_memory(project, content, **kwargs)
        with self.library.writer() as connection:
            previous = self._owned(connection, project, memory_id)
            if previous["state"] != "active" or previous["revision"] != expected_revision:
                raise ValueError("Supersession requires the current active revision")
            replacement = self._insert_memory(connection, prepared)
            connection.execute(
                "UPDATE memory_records SET state='superseded', superseded_by=?, updated_at=? WHERE id=?",
                (replacement, _now(), memory_id),
            )
            connection.execute(
                "INSERT INTO memory_conflicts VALUES (?, ?, ?, ?)",
                (memory_id, replacement, reason, _now()),
            )
        return self.inspect(project, replacement, include_shared=previous["scope"] == "shared")

    def retract(self, project: str, memory_id: str, reason: str, expected_revision: int) -> dict:
        _text(reason, "retraction reason", 4096)
        with self.library.writer() as connection:
            row = self._owned(connection, project, memory_id)
            if row["revision"] != expected_revision or row["state"] != "active":
                raise ValueError("Retraction requires the current active revision")
            connection.execute(
                "UPDATE memory_records SET state='retracted', updated_at=? WHERE id=?",
                (_now(), memory_id),
            )
            # Retraction provenance is a revision, retaining the original assertion.
            revision = connection.execute(
                "SELECT * FROM memory_revisions WHERE memory_id=? AND revision=?",
                (memory_id, expected_revision),
            ).fetchone()
            connection.execute(
                "INSERT INTO memory_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory_id,
                    expected_revision + 1,
                    revision["content"],
                    "user",
                    revision["provenance"],
                    revision["citations"],
                    reason,
                    _now(),
                ),
            )
            connection.execute(
                "UPDATE memory_records SET revision=? WHERE id=?",
                (expected_revision + 1, memory_id),
            )
        return self.inspect(project, memory_id, include_shared=row["scope"] == "shared")

    def contradictions(
        self,
        project: str,
        left_id: str | None = None,
        right_id: str | None = None,
        reason: str | None = None,
        include_shared: bool = False,
    ) -> dict:
        _project(project)
        _flag(include_shared, "include_shared")
        if left_id is not None or right_id is not None:
            if left_id == right_id or not left_id or not right_id:
                raise ValueError("A contradiction requires two different memory IDs")
            _text(reason, "contradiction reason", 4096)
            with self.library.writer() as connection:
                left = self._owned(connection, project, left_id)
                right = self._owned(connection, project, right_id)
                if not include_shared and (left["scope"] == "shared" or right["scope"] == "shared"):
                    raise ValueError("Shared contradictions require explicit include_shared")
                left_id, right_id = sorted((left_id, right_id))
                connection.execute(
                    "INSERT INTO memory_conflicts VALUES (?, ?, ?, ?) ON CONFLICT(left_id, right_id) DO UPDATE SET reason=excluded.reason",
                    (left_id, right_id, reason, _now()),
                )
        with self.library.connection() as connection:
            rows = connection.execute(
                """SELECT c.*, l.state AS left_state, r.state AS right_state
                FROM memory_conflicts c JOIN memory_records l ON l.id=c.left_id
                JOIN memory_records r ON r.id=c.right_id WHERE l.project=? AND r.project=? AND (? OR (l.scope='project' AND r.scope='project'))""",
                (project, project, int(include_shared)),
            ).fetchall()
        return {
            "contradictions": [dict(row) for row in rows],
            "detection": "explicit assertions and supersession; no semantic inference",
        }

    def forget(self, project: str, memory_ids: list[str], apply: bool = False) -> dict:
        _project(project)
        _flag(apply, "apply")
        if not isinstance(memory_ids, list) or not memory_ids or len(memory_ids) > 1000:
            raise ValueError("forget requires between 1 and 1000 explicit memory IDs")
        selected = sorted(set(memory_ids))
        with self.library.writer() as connection:
            rows = [self._owned(connection, project, memory_id) for memory_id in selected]
            count = sum(row["revision"] for row in rows)
            if apply:
                connection.executemany(
                    "UPDATE memory_records SET state='forgotten', updated_at=? WHERE id=?",
                    [(_now(), memory_id) for memory_id in selected],
                )
        return {
            "applied": apply,
            "memory_ids": selected,
            "revisions": count,
            "effect": "logical removal from recall; retained history and backups are not securely erased",
            "sources_preserved": True,
            "pages_preserved": True,
        }

    def export_memories(self, project: str, include_shared: bool = False) -> dict:
        _project(project)
        _flag(include_shared, "include_shared")
        with self.library.connection() as connection:
            rows = connection.execute(
                "SELECT id FROM memory_records WHERE state!='forgotten' AND ((project=? AND scope='project') OR (scope='shared' AND ?)) ORDER BY created_at,id",
                (project, int(include_shared)),
            ).fetchall()
        return {
            "schema_version": 1,
            "project": project,
            "records": [self.inspect(project, row["id"], include_shared) for row in rows],
            **self.contradictions(project, include_shared=include_shared),
        }

    def capture_enable(self, project: str, enabled: bool = True) -> dict:
        _project(project)
        _flag(enabled, "enabled")
        with self.library.writer() as connection:
            connection.execute(
                "INSERT INTO capture_config VALUES (?, ?, ?) ON CONFLICT(project) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at",
                (project, int(enabled), _now()),
            )
        return self.capture_status(project)

    @staticmethod
    def _enabled(connection, project: str) -> bool:
        row = connection.execute(
            "SELECT enabled FROM capture_config WHERE project=?", (project,)
        ).fetchone()
        return bool(row and row["enabled"])

    def capture_status(self, project: str) -> dict:
        _project(project)
        with self.library.connection() as connection:
            enabled = self._enabled(connection, project)
            rows = connection.execute(
                "SELECT event_id,state,attempts,record_ids,error,created_at,updated_at FROM capture_events WHERE project=? ORDER BY created_at,event_id",
                (project,),
            ).fetchall()
        events = [{**dict(row), "record_ids": json.loads(row["record_ids"])} for row in rows]
        return {
            "project": project,
            "enabled": enabled,
            "events": events,
            "pending": sum(event["state"] == "pending" for event in events),
            "failed": sum(event["state"] == "failed" for event in events),
        }

    def capture_submit(self, project: str, event_id: str, observations: list[dict]) -> dict:
        _project(project)
        _text(event_id, "event_id", 300)
        if not isinstance(observations, list) or not 1 <= len(observations) <= 100:
            raise ValueError("Capture accepts 1 to 100 selected structured observations")
        payload = _json(observations)
        if len(payload.encode()) > MAX_TEXT:
            raise ValueError("Capture payload exceeds the 1 MB limit")
        input_hash = _digest(payload.encode())
        with self.library.writer() as connection:
            existing = connection.execute(
                "SELECT * FROM capture_events WHERE project=? AND event_id=?", (project, event_id)
            ).fetchone()
            if existing:
                if existing["input_hash"] != input_hash:
                    raise ValueError("Capture event ID already belongs to different content")
                if existing["state"] == "committed":
                    return {
                        "event_id": event_id,
                        "state": "committed",
                        "duplicate": True,
                        "record_ids": json.loads(existing["record_ids"]),
                    }
            if not self._enabled(connection, project):
                raise ValueError("Capture must be explicitly enabled for this project")
            if existing is None:
                now = _now()
                connection.execute(
                    "INSERT INTO capture_events(project,event_id,input_hash,payload,state,created_at,updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                    (project, event_id, input_hash, payload, now, now),
                )
        return self._capture_process(project, event_id)

    def _capture_process(self, project: str, event_id: str) -> dict:
        with self.library.connection() as connection:
            row = connection.execute(
                "SELECT * FROM capture_events WHERE project=? AND event_id=?", (project, event_id)
            ).fetchone()
            if row is None:
                raise FileNotFoundError(event_id)
            if not self._enabled(connection, project):
                raise ValueError("Capture is disabled; pending events remain durable")
        try:
            prepared = []
            for observation in json.loads(row["payload"]):
                if not isinstance(observation, dict) or set(observation) - {
                    "content",
                    "kind",
                    "origin",
                    "provenance",
                    "citations",
                    "shared",
                }:
                    raise ValueError("Capture accepts selected memory fields only")
                item = self._prepare_memory(project, **{"origin": "agent", **observation})
                item["provenance"]["capture_event"] = {"project": project, "event_id": event_id}
                prepared.append(item)
            with self.library.writer() as connection:
                if not self._enabled(connection, project):
                    raise ValueError("Capture was disabled before publication")
                current = connection.execute(
                    "SELECT * FROM capture_events WHERE project=? AND event_id=?",
                    (project, event_id),
                ).fetchone()
                if current["state"] == "committed":
                    return {
                        "event_id": event_id,
                        "state": "committed",
                        "duplicate": True,
                        "record_ids": json.loads(current["record_ids"]),
                    }
                record_ids = [self._insert_memory(connection, item) for item in prepared]
                connection.execute(
                    "UPDATE capture_events SET state='committed', attempts=attempts+1, record_ids=?, error=NULL, updated_at=? WHERE project=? AND event_id=?",
                    (_json(record_ids), _now(), project, event_id),
                )
            return {
                "event_id": event_id,
                "state": "committed",
                "duplicate": False,
                "record_ids": record_ids,
            }
        except Exception as error:  # noqa: BLE001 - Persist failed capture processing for retry.
            # The payload and pending event committed before processing. A failed
            # publication never acknowledges a record that is absent after restart.
            with self.library.writer() as connection:
                connection.execute(
                    "UPDATE capture_events SET state='failed', attempts=attempts+1, error=?, updated_at=? WHERE project=? AND event_id=? AND state!='committed'",
                    (type(error).__name__, _now(), project, event_id),
                )
            return {
                "event_id": event_id,
                "state": "failed",
                "error": type(error).__name__,
                "retryable": True,
            }

    def capture_retry(self, project: str, event_id: str | None = None) -> dict:
        _project(project)
        with self.library.connection() as connection:
            if not self._enabled(connection, project):
                raise ValueError("Capture is disabled; pending events remain durable")
            rows = connection.execute(
                "SELECT event_id FROM capture_events WHERE project=? AND state!='committed' AND (? IS NULL OR event_id=?) ORDER BY created_at,event_id LIMIT 100",
                (project, event_id, event_id),
            ).fetchall()
        return {"results": [self._capture_process(project, row["event_id"]) for row in rows]}

    def capture_recall(self, project: str, **kwargs) -> dict:
        _project(project)
        with self.library.connection() as connection:
            if not self._enabled(connection, project):
                return {"project": project, "enabled": False, "records": []}
        return {"enabled": True, **self.recall(project, **kwargs)}

    def _page_path(self, page_id: str) -> Path:
        if (
            not isinstance(page_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", page_id)
            or page_id in {".", ".."}
        ):
            raise ValueError("Page ID must be a simple filename stem, at most 120 characters")
        directory = self.library.path / "knowledge"
        if directory.is_symlink():
            raise ValueError("Knowledge directory cannot be a symlink")
        directory.mkdir(exist_ok=True)
        path = directory / f"{page_id}.md"
        if path.is_symlink():
            raise ValueError("Knowledge page cannot be a symlink")
        return path

    @staticmethod
    def _file_hash(path: Path) -> str | None:
        if path.is_symlink():
            raise ValueError("Knowledge page cannot be a symlink")
        if not path.exists():
            return None
        with path.open("rb") as stream:
            content = stream.read(MAX_TEXT + 1)
        if len(content) > MAX_TEXT:
            raise ValueError("Knowledge page exceeds the 1 MB limit")
        return _digest(content)

    @staticmethod
    def _cycle(connection, page_id: str, dependencies: list[dict]) -> None:
        graph = {
            row["id"]: [item["page_id"] for item in json.loads(row["dependencies"])]
            for row in connection.execute("SELECT id,dependencies FROM knowledge_pages")
        }
        graph[page_id] = [item["page_id"] for item in dependencies]
        visited, active = set(), set()

        def visit(node: str):
            if node in active:
                raise ValueError("Knowledge dependency cycle")
            if node in visited:
                return
            if len(visited) >= 10_000 or len(active) >= 100:
                raise ValueError("Knowledge dependency graph exceeds validation bound")
            visited.add(node)
            active.add(node)
            for child in graph.get(node, []):
                visit(child)
            active.remove(node)

        visit(page_id)

    @staticmethod
    def _page_scope(row, project: str, include_shared: bool):
        if row is None or not (
            (row["project"] == project and row["scope"] == "project")
            or (include_shared and row["scope"] == "shared")
        ):
            raise FileNotFoundError("Knowledge page does not exist in the selected scope")

    def write_page(
        self,
        project: str,
        page_id: str,
        body: str,
        expected_hash: str | None,
        citations: list[dict],
        dependencies: list[str] | None = None,
        shared: bool = False,
    ) -> dict:
        _project(project)
        _text(body, "Markdown body")
        _flag(shared, "shared")
        if expected_hash is not None and not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
            raise ValueError("expected_hash must be a SHA-256 digest or null for a new page")
        path = self._page_path(page_id)
        checked = self._citations(citations, project, shared)
        dependencies = [] if dependencies is None else dependencies
        if not isinstance(dependencies, list) or len(dependencies) > 1000:
            raise ValueError("dependencies must be a list of at most 1000 page IDs")
        for dependency in dependencies:
            self._page_path(dependency)
        with self.library.connection() as connection:
            owner = connection.execute(
                "SELECT project FROM knowledge_pages WHERE id=? UNION ALL SELECT project FROM knowledge_pending WHERE page_id=?",
                (page_id, page_id),
            ).fetchall()
            if any(row["project"] != project for row in owner):
                raise ValueError("A page owned by another project cannot be overwritten")
        self._recover_page(page_id)
        with self.library.writer() as connection:
            previous = connection.execute(
                "SELECT * FROM knowledge_pages WHERE id=?", (page_id,)
            ).fetchone()
            if previous and previous["project"] != project:
                raise ValueError("A page owned by another project cannot be overwritten")
            if previous and previous["scope"] != ("shared" if shared else "project"):
                raise ValueError("Page scope cannot change during an update")
            if self._file_hash(path) != expected_hash:
                raise ValueError("Page content changed; inspect its current hash before writing")
            records = []
            for dependency in sorted(set(dependencies)):
                row = connection.execute(
                    "SELECT * FROM knowledge_pages WHERE id=?", (dependency,)
                ).fetchone()
                if row:
                    self._page_scope(row, project, shared)
                records.append(
                    {
                        "page_id": dependency,
                        "content_hash": self._file_hash(self._page_path(dependency))
                        if row
                        else None,
                    }
                )
            self._cycle(connection, page_id, records)
            connection.execute(
                "INSERT INTO knowledge_pending VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    page_id,
                    project,
                    "shared" if shared else "project",
                    expected_hash,
                    _digest(body.encode()),
                    body,
                    _json(checked),
                    _json(records),
                    _now(),
                ),
            )
        self._recover_page(page_id)
        return self.inspect_page(project, page_id, include_shared=shared)

    def _recover_page(self, page_id: str) -> None:
        path = self._page_path(page_id)
        with self.library.writer() as connection:
            pending = connection.execute(
                "SELECT * FROM knowledge_pending WHERE page_id=?", (page_id,)
            ).fetchone()
            if pending is None:
                return
            current = self._file_hash(path)
            if current not in {pending["expected_hash"], pending["digest"]}:
                # Keep the conflicting draft available for explicit recovery/export.
                raise ValueError(
                    "Pending publication conflicts with a manual edit; inspect the pending draft"
                )
            self._cycle(connection, page_id, json.loads(pending["dependencies"]))
            if current != pending["digest"]:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=path.parent, delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    try:
                        stream.write(pending["body"].encode())
                        stream.flush()
                        os.fsync(stream.fileno())
                        if self._file_hash(path) != pending["expected_hash"]:
                            raise ValueError(
                                "Page changed during publication; manual edit preserved"
                            )
                        os.replace(temporary, path)
                        descriptor = os.open(path.parent, os.O_RDONLY)
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                    finally:
                        temporary.unlink(missing_ok=True)
            connection.execute(
                "INSERT INTO knowledge_pages VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET digest=excluded.digest, citations=excluded.citations, dependencies=excluded.dependencies, updated_at=excluded.updated_at",
                (
                    page_id,
                    pending["project"],
                    pending["scope"],
                    pending["digest"],
                    pending["citations"],
                    pending["dependencies"],
                    _now(),
                ),
            )
            connection.execute("DELETE FROM knowledge_pending WHERE page_id=?", (page_id,))

    def inspect_page(self, project: str, page_id: str, include_shared: bool = False) -> dict:
        _project(project)
        _flag(include_shared, "include_shared")
        with self.library.connection() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_pages WHERE id=?", (page_id,)
            ).fetchone()
            pending = connection.execute(
                "SELECT * FROM knowledge_pending WHERE page_id=?", (page_id,)
            ).fetchone()
        self._page_scope(row or pending, project, include_shared)
        recovery_error = None
        try:
            self._recover_page(page_id)
        except ValueError as error:
            recovery_error = str(error)
        with self.library.connection() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_pages WHERE id=?", (page_id,)
            ).fetchone()
            pending = connection.execute(
                "SELECT * FROM knowledge_pending WHERE page_id=?", (page_id,)
            ).fetchone()
        path = self._page_path(page_id)
        digest = self._file_hash(path)
        result = dict(row or pending)
        result.update(
            {
                "id": page_id,
                "path": str(path),
                "content_hash": digest,
                "body": path.read_text() if digest else None,
                "manual_edit": bool(row and digest != row["digest"]),
                "citations": self._citations(
                    json.loads(result["citations"]), result["project"], result["scope"] == "shared"
                ),
                "dependencies": json.loads(result["dependencies"]),
                "assertions_certified": False,
                "publication_error": recovery_error,
                "pending": dict(pending) if pending else None,
            }
        )
        if result["pending"]:
            result["pending"]["citations"] = json.loads(result["pending"]["citations"])
            result["pending"]["dependencies"] = json.loads(result["pending"]["dependencies"])
        return result

    def discard_pending_page(self, project: str, page_id: str, expected_hash: str | None) -> dict:
        """Discard a retained draft only after checking the current authored file."""
        _project(project)
        path = self._page_path(page_id)
        with self.library.writer() as connection:
            pending = connection.execute(
                "SELECT * FROM knowledge_pending WHERE page_id=? AND project=?",
                (page_id, project),
            ).fetchone()
            if pending is None:
                raise FileNotFoundError("No pending page in the selected project")
            if self._file_hash(path) != expected_hash:
                raise ValueError(
                    "Page changed; inspect its current hash before discarding the draft"
                )
            connection.execute("DELETE FROM knowledge_pending WHERE page_id=?", (page_id,))
        return {"page_id": page_id, "pending_discarded": True, "authored_file_preserved": True}

    def validate_page(self, project: str, page_id: str, include_shared: bool = False) -> dict:
        _project(project)
        seen, active = {}, set()

        def validate(identifier: str) -> dict:
            if identifier in active:
                return {
                    "page_id": identifier,
                    "freshness": "stale",
                    "reasons": ["dependency cycle"],
                }
            if identifier in seen:
                return seen[identifier]
            if len(seen) + len(active) >= 1000 or len(active) >= 100:
                return {
                    "page_id": identifier,
                    "freshness": "unresolved",
                    "reasons": ["dependency validation bound reached"],
                }
            active.add(identifier)
            try:
                page = self.inspect_page(project, identifier, include_shared)
            except (OSError, ValueError) as error:
                active.remove(identifier)
                return {
                    "page_id": identifier,
                    "freshness": "unresolved",
                    "reasons": [type(error).__name__],
                }
            reasons = []
            if page["content_hash"] is None:
                reasons.append("page missing")
            if page["manual_edit"]:
                reasons.append("page has unreviewed manual edits")
            if page["pending"]:
                reasons.append("page has unresolved publication")
            for citation in page["citations"]:
                if citation["status"] != "current":
                    reasons.append(f"citation {citation['id']} is {citation['status']}")
            dependencies = []
            for dependency in page["dependencies"]:
                child = validate(dependency["page_id"])
                dependencies.append(child)
                if (
                    child["freshness"] != "current"
                    or child.get("content_hash") != dependency["content_hash"]
                ):
                    reasons.append(
                        f"dependency {dependency['page_id']} changed or lacks current support"
                    )
            active.remove(identifier)
            result = {
                "page_id": identifier,
                "content_hash": page["content_hash"],
                "freshness": "stale" if reasons else "current",
                "reasons": reasons,
                "citations": page["citations"],
                "dependencies": dependencies,
                "assertions_certified": False,
            }
            seen[identifier] = result
            return result

        # An unknown or out-of-scope top-level ID is an access error, not a page.
        self.inspect_page(project, page_id, include_shared)
        return validate(page_id)

    def stale_pages(self, project: str, include_shared: bool = False) -> dict:
        _project(project)
        _flag(include_shared, "include_shared")
        with self.library.connection() as connection:
            rows = connection.execute(
                "SELECT id FROM knowledge_pages WHERE (project=? AND scope='project') OR (scope='shared' AND ?)",
                (project, int(include_shared)),
            ).fetchall()
        pages = [self.validate_page(project, row["id"], include_shared) for row in rows]
        return {
            "project": project,
            "pages": [page for page in pages if page["freshness"] != "current"],
            "checked": len(pages),
            "action": "Return affected pages and evidence to the host for explicit revision",
        }

    def export_page(
        self,
        project: str,
        page_id: str,
        destination: str | None = None,
        include_shared: bool = False,
    ) -> dict:
        page = self.inspect_page(project, page_id, include_shared)
        result = {
            "schema_version": 1,
            "page": page,
            "validation": self.validate_page(project, page_id, include_shared),
        }
        if destination is not None:
            target = Path(destination).expanduser().absolute()
            if any(path.is_symlink() for path in (target, *target.parents)):
                raise ValueError("Export destination cannot contain symlinks")
            target.mkdir(parents=True, exist_ok=True)
            markdown = target / f"{page_id}.md"
            metadata = target / f"{page_id}.citations.json"
            if markdown.exists() or metadata.exists():
                raise FileExistsError("Export would overwrite existing files")
            markdown.write_text(page["body"] or "", encoding="utf-8")
            metadata.write_text(_json(result) + "\n", encoding="utf-8")
            result["exported"] = [str(markdown), str(metadata)]
        return result


def _freshness(citations: list[dict]) -> str:
    if not citations:
        return "not_source_backed"
    if any(citation["status"] == "unresolved" for citation in citations):
        return "unresolved"
    return "current" if all(citation["status"] == "current" for citation in citations) else "stale"


def dispatch(db_path: Path, action: str, payload: dict) -> dict:
    """Dispatch explicit JSON arguments through the same scoped application core."""
    knowledge = Knowledge(db_path)
    actions = {
        "memory.add": knowledge.add,
        "memory.recall": knowledge.recall,
        "memory.inspect": knowledge.inspect,
        "memory.correct": knowledge.correct,
        "memory.supersede": knowledge.supersede,
        "memory.retract": knowledge.retract,
        "memory.forget": knowledge.forget,
        "memory.export": knowledge.export_memories,
        "memory.contradictions": knowledge.contradictions,
        "capture.enable": knowledge.capture_enable,
        "capture.disable": lambda **kwargs: knowledge.capture_enable(**kwargs, enabled=False),
        "capture.status": knowledge.capture_status,
        "capture.submit": knowledge.capture_submit,
        "capture.retry": knowledge.capture_retry,
        "capture.recall": knowledge.capture_recall,
        "knowledge.write": knowledge.write_page,
        "knowledge.inspect": knowledge.inspect_page,
        "knowledge.validate": knowledge.validate_page,
        "knowledge.stale": knowledge.stale_pages,
        "knowledge.export": knowledge.export_page,
        "knowledge.discard-pending": knowledge.discard_pending_page,
    }
    if action not in actions:
        raise ValueError(f"Unknown memory/knowledge action: {action}")
    if not isinstance(payload, dict):
        raise TypeError("Operation payload must be an object")
    return {"schema_version": 1, **actions[action](**payload)}
