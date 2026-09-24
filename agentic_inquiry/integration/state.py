"""SQLite ledger, project identity and the marker file.

The binding under ``INQUIRY_HOME`` is the authority. The marker is a hint.
A hook never creates the ledger; operator verbs do.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import sqlite3
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from agentic_inquiry.integration.contract import IDENTITY_PATTERN
from agentic_inquiry.mcp.utils.validation import (
    PathValidationError,
    validate_file_path,
    validate_project_id,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS integration_config (
    project_id TEXT NOT NULL,
    client TEXT NOT NULL,
    owner TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    project_root TEXT NOT NULL,
    config_path TEXT NOT NULL,
    storage_project_id TEXT NOT NULL,
    policy TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, client)
);
CREATE TABLE IF NOT EXISTS integration_events (
    key TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    client TEXT NOT NULL,
    owner TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event TEXT NOT NULL,
    event_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('capture', 'refresh')),
    payload TEXT,
    input_hash TEXT,
    state TEXT NOT NULL CHECK (state IN ('pending', 'committing', 'committed', 'failed', 'purged')),
    attempts INTEGER NOT NULL DEFAULT 0,
    resets INTEGER NOT NULL DEFAULT 0,
    deliveries INTEGER NOT NULL DEFAULT 1,
    lease_until TEXT,
    receipt TEXT,
    result TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS integration_events_lookup
    ON integration_events (project_id, client, state, created_at);
CREATE TABLE IF NOT EXISTS integration_notified (
    project_id TEXT NOT NULL,
    client TEXT NOT NULL,
    session_id TEXT NOT NULL,
    code TEXT NOT NULL,
    first_at TEXT NOT NULL,
    PRIMARY KEY (project_id, client, session_id, code)
);
CREATE TABLE IF NOT EXISTS integration_tombstones (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    erased_at TEXT NOT NULL
);
"""

_GRAMMAR = '[project]\nid = "{identity}"\nschema = 1\n'
_CLOSED = frozenset({errno.EAGAIN, errno.EWOULDBLOCK})


class StateError(Exception):
    """A ledger or project-file refusal the CLI prints in its envelope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Binding:
    project_id: str
    client: str
    owner: str
    enabled: bool
    project_root: str
    config_path: str
    storage_project_id: str
    policy: dict[str, Any]


@dataclass
class RecordOutcome:
    outcome: str
    durable_id: str
    receipt: dict[str, Any] | None
    deliveries: int
    state: str
    kind: str


def inquiry_home() -> Path:
    """Resolve ``INQUIRY_HOME`` once so a symlinked home is a real directory."""
    raw = os.environ.get("INQUIRY_HOME")
    if raw:
        return Path(raw).resolve()
    return (Path.home() / ".agentic-inquiry").resolve()


def records_path(identity: str) -> Path:
    if IDENTITY_PATTERN.fullmatch(identity) is None:
        raise StateError(
            "project_identity_invalid",
            "project identity must be 16 lowercase hex characters",
        )
    return inquiry_home() / "projects" / identity / "records.sqlite3"


def read_identity(project_root: Path) -> str | None:
    """Return the identity, ``None`` when the file is absent, or raise when it is malformed."""
    path = project_root / ".agentic-inquiry" / "project.toml"
    if not path.exists():
        return None
    data = path.read_bytes()
    if len(data) > 4096:
        raise StateError("project_identity_invalid", "project.toml exceeds 4096 bytes")
    text = data.decode("utf-8", errors="replace")
    prefix = '[project]\nid = "'
    suffix = '"\nschema = 1\n'
    if not text.startswith(prefix) or not text.endswith(suffix):
        raise StateError(
            "project_identity_invalid",
            "project.toml does not match the identity grammar",
        )
    identity = text[len(prefix) : -len(suffix)]
    if IDENTITY_PATTERN.fullmatch(identity) is None or "\n" in identity:
        raise StateError(
            "project_identity_invalid",
            "project identity must be 16 lowercase hex characters",
        )
    expected = _GRAMMAR.format(identity=identity)
    if text != expected:
        raise StateError(
            "project_identity_invalid",
            "project.toml does not match the identity grammar",
        )
    return identity


def read_marker(project_root: Path) -> dict[str, Any] | None:
    path = project_root / ".agentic-inquiry" / "integration.json"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def marker_claims_enabled(project_root: Path, client: str) -> bool:
    marker = read_marker(project_root)
    if not marker:
        return False
    clients = marker.get("clients")
    if not isinstance(clients, dict):
        return False
    entry = clients.get(client)
    if not isinstance(entry, dict):
        return False
    return entry.get("enabled") is True


def _remedy(path: Path, check: str) -> str:
    if check == "write":
        return (
            f"{path} is writable by group or other (mode). "
            f"Inspect the directory for entries you did not create, then chmod go-w {path}"
        )
    if check == "owner":
        return f"{path} is not owned by the current user (owner). Copy the ledger aside and replace it."
    if check == "type":
        return f"{path} is not a directory (type). Replace it with a directory you own under INQUIRY_HOME."
    if check == "link":
        return (
            f"{path} has more than one hard link (link count). "
            "Copy the ledger aside and replace it: "
            f"cp {path} {path.parent / 'records.new'} && mv {path.parent / 'records.new'} {path}"
        )
    if check == "link-dir":
        return f"{path} is a symbolic link (type). Replace it with a real directory."
    return f"{path} failed check {check}."


def _open_directory(path: Path, *, create: bool, heal: bool) -> None:
    """Open ``path`` with ``O_DIRECTORY | O_NOFOLLOW`` and apply the mode rules."""
    if create and not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise FileNotFoundError(path) from exc
        if exc.errno in (errno.ENOTDIR, errno.ELOOP):
            raise StateError("project_files_invalid", _remedy(path, "type")) from exc
        raise StateError(
            "project_files_invalid", f"{path} could not be opened ({exc.errno})."
        ) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            raise StateError("project_files_invalid", _remedy(path, "type"))
        if info.st_uid != os.geteuid():
            raise StateError("project_files_invalid", _remedy(path, "owner"))
        mode = info.st_mode & 0o777
        if mode & 0o022:
            raise StateError("project_files_invalid", _remedy(path, "write"))
        if heal and mode != 0o700 and (mode & 0o022) == 0:
            try:
                os.fchmod(fd, 0o700)
            except OSError as exc:
                raise StateError(
                    "project_files_invalid",
                    f"{path} could not be tightened (mode, errno {exc.errno}). chmod go-w {path}",
                ) from exc
    finally:
        os.close(fd)


def _open_directory_hook(path: Path) -> str | None:
    """Return ``ledger_unavailable`` or ``absent``. ``None`` means the directory is usable.

    A hook heals nothing. A missing directory is the absent store. A write bit,
    a foreign owner or a non-directory is ``ledger_unavailable``.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return "absent"
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return "absent"
        return "ledger_unavailable"
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            return "ledger_unavailable"
        if (info.st_mode & 0o777) & 0o022:
            return "ledger_unavailable"
    finally:
        os.close(fd)
    return None


def ensure_ledger_home(identity: str, *, heal: bool) -> Path:
    """Create and check the ledger directories. CLI verbs only."""
    if IDENTITY_PATTERN.fullmatch(identity) is None:
        raise StateError(
            "project_identity_invalid",
            "project identity must be 16 lowercase hex characters",
        )
    home = inquiry_home()
    projects = home / "projects"
    project = projects / identity
    for directory in (home, projects, project):
        _open_directory(directory, create=True, heal=heal)
    return project / "records.sqlite3"


def _open_database(path: Path, *, create: bool) -> None:
    flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    if create:
        flags |= os.O_CREAT
    try:
        fd = os.open(path, flags, 0o600)
    except FileNotFoundError:
        raise
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise FileNotFoundError(path) from exc
        raise StateError(
            "project_files_invalid", f"{path} could not be opened ({exc.errno})."
        ) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise StateError("project_files_invalid", _remedy(path, "type"))
        if info.st_uid != os.geteuid():
            raise StateError("project_files_invalid", _remedy(path, "owner"))
        if info.st_nlink != 1:
            raise StateError("project_files_invalid", _remedy(path, "link"))
        mode = info.st_mode & 0o777
        if mode & 0o022:
            raise StateError("project_files_invalid", _remedy(path, "write"))
        if not create and mode != 0o600:
            raise StateError("project_files_invalid", _remedy(path, "write"))
        if create:
            try:
                os.fchmod(fd, 0o600)
            except OSError as exc:
                raise StateError(
                    "project_files_invalid",
                    f"{path} could not be tightened (mode, errno {exc.errno}).",
                ) from exc
    finally:
        os.close(fd)


class Ledger:
    """One connection to ``records.sqlite3``."""

    def __init__(
        self, connection: sqlite3.Connection, path: Path, identity: str
    ) -> None:
        self._conn = connection
        self.path = path
        self.identity = identity
        self.untrusted_home = False

    @classmethod
    def open(
        cls,
        identity: str,
        *,
        timeout: float,
        create: bool,
        heal: bool,
    ) -> Ledger:
        path = (
            ensure_ledger_home(identity, heal=heal)
            if create
            else records_path(identity)
        )
        untrusted = False
        if not create:
            home = inquiry_home()
            for directory in (home, home / "projects", home / "projects" / identity):
                found = _open_directory_hook(directory)
                if found == "absent":
                    if untrusted:
                        raise StateError(
                            "ledger_unavailable",
                            "ledger home is not usable by this user",
                        )
                    raise FileNotFoundError(directory)
                if found == "ledger_unavailable":
                    untrusted = True
            try:
                _open_database(path, create=False)
            except FileNotFoundError:
                if untrusted:
                    raise StateError(
                        "ledger_unavailable", "ledger home is not usable by this user"
                    )
                raise
            except StateError as exc:
                raise StateError(
                    "ledger_unavailable", "ledger file failed its ownership check"
                ) from exc
        else:
            _open_database(path, create=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(path, timeout=max(timeout, 0.0))
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            millis = max(0, int(timeout * 1000))
            connection.execute(f"PRAGMA busy_timeout={millis}")
            if create:
                cls._migrate(connection)
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            if create:
                raise StateError(
                    "project_files_invalid",
                    f"{path} is not a usable records.sqlite3.",
                ) from exc
            raise StateError(
                "ledger_unavailable", "ledger file failed its ownership check"
            ) from exc
        assert connection is not None
        ledger = cls(connection, path, identity)
        ledger.untrusted_home = untrusted
        return ledger

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            connection.executescript(_SCHEMA)
            connection.execute("PRAGMA user_version = 1")
            connection.commit()

    def close(self) -> None:
        self._conn.close()

    def binding(self, client: str) -> Binding | None:
        row = self._conn.execute(
            "SELECT * FROM integration_config WHERE project_id = ? AND client = ?",
            (self.identity, client),
        ).fetchone()
        if row is None:
            return None
        return _binding_from_row(row)

    def bindings(self) -> list[Binding]:
        rows = self._conn.execute(
            "SELECT * FROM integration_config WHERE project_id = ? ORDER BY client",
            (self.identity,),
        ).fetchall()
        return [_binding_from_row(row) for row in rows]

    def any_root_mismatch(self, project_root: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM integration_config WHERE project_id = ? AND project_root != ? LIMIT 1",
            (self.identity, project_root),
        ).fetchone()
        return row is not None

    def event_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM integration_events WHERE project_id = ?",
            (self.identity,),
        ).fetchone()
        return int(row["n"])

    def upsert_binding(self, binding: Binding) -> None:
        now = _now(self._conn)
        self._conn.execute(
            """
            INSERT INTO integration_config (
                project_id, client, owner, enabled, project_root, config_path,
                storage_project_id, policy, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, client) DO UPDATE SET
                owner = excluded.owner,
                enabled = excluded.enabled,
                project_root = excluded.project_root,
                config_path = excluded.config_path,
                storage_project_id = excluded.storage_project_id,
                policy = excluded.policy,
                updated_at = excluded.updated_at
            """,
            (
                binding.project_id,
                binding.client,
                binding.owner,
                1 if binding.enabled else 0,
                binding.project_root,
                binding.config_path,
                binding.storage_project_id,
                json.dumps(binding.policy, separators=(",", ":"), sort_keys=True),
                now,
            ),
        )
        self._conn.commit()

    def set_enabled(self, client: str, enabled: bool) -> bool:
        cursor = self._conn.execute(
            "UPDATE integration_config SET enabled = ?, updated_at = ? WHERE project_id = ? AND client = ?",
            (1 if enabled else 0, _now(self._conn), self.identity, client),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def record_event(
        self,
        *,
        key: str,
        client: str,
        owner: str,
        session_id: str,
        event: str,
        event_id: str,
        kind: str,
        payload: list[Any],
        input_hash: str,
        receipt: dict[str, Any],
    ) -> RecordOutcome:
        existing = self._conn.execute(
            "SELECT * FROM integration_events WHERE key = ?", (key,)
        ).fetchone()
        if existing is not None:
            return self._redeliver(existing, input_hash)
        tombstone = self.tombstone(key)
        if tombstone is not None:
            return RecordOutcome(
                "purged", f"{tombstone}:{key}", None, 1, "purged", tombstone
            )
        now = _now(self._conn)
        self._conn.execute(
            """
            INSERT INTO integration_events (
                key, project_id, client, owner, session_id, event, event_id, kind,
                payload, input_hash, state, attempts, deliveries, receipt, result,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 1, ?, NULL, ?, ?)
            """,
            (
                key,
                self.identity,
                client,
                owner,
                session_id,
                event,
                event_id,
                kind,
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                input_hash,
                json.dumps(receipt, separators=(",", ":")),
                now,
                now,
            ),
        )
        self._conn.commit()
        return RecordOutcome("new", receipt["durable_id"], receipt, 1, "pending", kind)

    def redeliver_only(self, *, key: str, input_hash: str) -> RecordOutcome | None:
        existing = self._conn.execute(
            "SELECT * FROM integration_events WHERE key = ?", (key,)
        ).fetchone()
        if existing is None:
            return None
        return self._redeliver(existing, input_hash)

    def _redeliver(self, row: sqlite3.Row, input_hash: str) -> RecordOutcome:
        kind = str(row["kind"])
        key = str(row["key"])
        durable = f"{kind}:{key}"
        if row["state"] == "purged" or row["payload"] is None:
            self._conn.execute(
                "UPDATE integration_events SET deliveries = deliveries + 1, updated_at = ? WHERE key = ?",
                (_now(self._conn), key),
            )
            self._conn.commit()
            deliveries = int(
                self._conn.execute(
                    "SELECT deliveries FROM integration_events WHERE key = ?", (key,)
                ).fetchone()["deliveries"]
            )
            return RecordOutcome("purged", durable, None, deliveries, "purged", kind)
        if row["input_hash"] != input_hash:
            return RecordOutcome(
                "conflict",
                durable,
                None,
                int(row["deliveries"]),
                str(row["state"]),
                kind,
            )
        self._conn.execute(
            "UPDATE integration_events SET deliveries = deliveries + 1, updated_at = ? WHERE key = ?",
            (_now(self._conn), key),
        )
        self._conn.commit()
        fresh = self._conn.execute(
            "SELECT * FROM integration_events WHERE key = ?", (key,)
        ).fetchone()
        receipt = json.loads(fresh["receipt"]) if fresh["receipt"] else None
        return RecordOutcome(
            "duplicate",
            durable,
            receipt,
            int(fresh["deliveries"]),
            str(fresh["state"]),
            kind,
        )

    def tombstone(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT kind FROM integration_tombstones WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return str(row["kind"])

    def pending(
        self, client: str, *, limit: int = 50
    ) -> tuple[list[dict[str, Any]], int]:
        total = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM integration_events
            WHERE project_id = ? AND client = ? AND state IN ('pending', 'committing', 'failed')
              AND NOT (state = 'failed' AND attempts >= 3)
            """,
            (self.identity, client),
        ).fetchone()["n"]
        rows = self._conn.execute(
            """
            SELECT key, kind, state, attempts FROM integration_events
            WHERE project_id = ? AND client = ? AND state IN ('pending', 'committing', 'failed')
              AND NOT (state = 'failed' AND attempts >= 3)
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (self.identity, client, limit),
        ).fetchall()
        items = [
            {
                "durable_id": f"{row['kind']}:{row['key']}",
                "kind": row["kind"],
                "state": "pending" if row["state"] == "committing" else row["state"],
                "attempts": int(row["attempts"]),
            }
            for row in rows
        ]
        return items, int(total)

    def has_open_rows(self, client: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM integration_events
            WHERE project_id = ? AND client = ? AND state IN ('pending', 'committing', 'failed')
              AND NOT (state = 'failed' AND attempts >= 3)
            LIMIT 1
            """,
            (self.identity, client),
        ).fetchone()
        return row is not None

    def recent_captures(
        self, owner: str, enabled_clients: list[str], *, rows: int = 20
    ) -> list[sqlite3.Row]:
        if not enabled_clients:
            return []
        placeholders = ",".join("?" for _ in enabled_clients)
        query = f"""
            SELECT key, kind, client, owner, payload, created_at, state FROM integration_events
            WHERE project_id = ? AND kind = 'capture' AND owner = ?
              AND client IN ({placeholders}) AND payload IS NOT NULL
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
        """
        return list(
            self._conn.execute(
                query, (self.identity, owner, *enabled_clients, rows)
            ).fetchall()
        )

    def capture_rows(
        self, owner: str, enabled_clients: list[str], *, rows: int = 200
    ) -> list[sqlite3.Row]:
        """Newest non-purged captures, committed and still queued.

        The prompt unions these with hybrid search so a row that has not been
        embedded yet is still findable, and a committed row is still findable
        when the warm ranker is down.
        """
        if not enabled_clients:
            return []
        placeholders = ",".join("?" for _ in enabled_clients)
        query = f"""
            SELECT key, kind, client, owner, payload, created_at, state FROM integration_events
            WHERE project_id = ? AND kind = 'capture' AND owner = ?
              AND client IN ({placeholders}) AND payload IS NOT NULL
              AND state != 'purged'
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
        """
        return list(
            self._conn.execute(
                query, (self.identity, owner, *enabled_clients, rows)
            ).fetchall()
        )

    def enabled_clients(self, owner: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT client FROM integration_config
            WHERE project_id = ? AND owner = ? AND enabled = 1
            ORDER BY client
            """,
            (self.identity, owner),
        ).fetchall()
        return [str(row["client"]) for row in rows]

    def notify_once(self, client: str, session_id: str, code: str) -> bool:
        try:
            self._conn.execute(
                """
                INSERT INTO integration_notified (project_id, client, session_id, code, first_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (self.identity, client, session_id, code, _now(self._conn)),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            return False
        return True

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            """
            SELECT state, COUNT(*) AS n FROM integration_events
            WHERE project_id = ? GROUP BY state
            """,
            (self.identity,),
        ).fetchall()
        found = {str(row["state"]): int(row["n"]) for row in rows}
        failed_rows = self._conn.execute(
            "SELECT attempts FROM integration_events WHERE project_id = ? AND state = 'failed'",
            (self.identity,),
        ).fetchall()
        exhausted = sum(1 for row in failed_rows if int(row["attempts"]) >= 3)
        failed = sum(1 for row in failed_rows if int(row["attempts"]) < 3)
        pending = found.get("pending", 0) + found.get("committing", 0)
        return {
            "pending": pending,
            "committed": found.get("committed", 0),
            "failed": failed,
            "exhausted": exhausted,
            "purged": found.get("purged", 0),
        }

    def exhausted_ids(self, client: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT kind, key FROM integration_events
            WHERE project_id = ? AND client = ? AND state = 'failed' AND attempts >= 3
            ORDER BY created_at ASC, rowid ASC
            """,
            (self.identity, client),
        ).fetchall()
        return [f"{row['kind']}:{row['key']}" for row in rows]

    def reset_for_retry(self, durable: str, *, force: bool = False) -> bool:
        kind, separator, key = durable.partition(":")
        if separator != ":" or not key:
            return False
        row = self._conn.execute(
            "SELECT resets, attempts, state FROM integration_events WHERE key = ? AND kind = ?",
            (key, kind),
        ).fetchone()
        if row is None or row["state"] != "failed" or int(row["attempts"]) < 3:
            return False
        if int(row["resets"]) >= 2 and not force:
            raise StateError(
                "policy_invalid", "retry limit reached; pass --force to retry again"
            )
        self._conn.execute(
            """
            UPDATE integration_events
            SET resets = resets + 1, state = 'pending', updated_at = ?
            WHERE key = ?
            """,
            (_now(self._conn), key),
        )
        self._conn.commit()
        return True

    def sweep_tombstones(self) -> None:
        self._conn.execute(
            """
            DELETE FROM integration_tombstones
            WHERE erased_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-48 hours')
            """
        )
        self._conn.commit()

    def null_payloads(self) -> int:
        self._conn.execute("PRAGMA secure_delete = ON")
        cursor = self._conn.execute(
            """
            UPDATE integration_events
            SET payload = NULL, input_hash = NULL, event_id = NULL, state = 'purged', updated_at = ?
            WHERE project_id = ? AND state != 'purged'
            """,
            (_now(self._conn), self.identity),
        )
        self._conn.commit()
        self._conn.execute("VACUUM")
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return int(cursor.rowcount)

    def purged_capture_rows(self) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                """
                SELECT key, result FROM integration_events
                WHERE project_id = ? AND state = 'purged' AND kind = 'capture'
                """,
                (self.identity,),
            ).fetchall()
        )

    def notification_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM integration_notified WHERE project_id = ?",
            (self.identity,),
        ).fetchone()
        return int(row["n"])

    def purge_rows(self) -> int:
        rows = self._conn.execute(
            "SELECT key, kind FROM integration_events WHERE project_id = ? AND state = 'purged'",
            (self.identity,),
        ).fetchall()
        now = _now(self._conn)
        self._conn.execute("PRAGMA secure_delete = ON")
        for row in rows:
            self._conn.execute(
                """
                INSERT INTO integration_tombstones (key, kind, erased_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET kind = excluded.kind, erased_at = excluded.erased_at
                """,
                (row["key"], row["kind"], now),
            )
        self._conn.execute(
            "DELETE FROM integration_events WHERE project_id = ? AND state = 'purged'",
            (self.identity,),
        )
        self._conn.execute(
            "DELETE FROM integration_notified WHERE project_id = ?", (self.identity,)
        )
        self._conn.commit()
        self._conn.execute("VACUUM")
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return len(rows)

    def claim_candidates(self, *, limit: int) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                """
                SELECT e.key FROM integration_events e
                JOIN integration_config c
                  ON c.project_id = e.project_id AND c.client = e.client
                WHERE e.project_id = ?
                  AND c.enabled = 1
                  AND e.owner = c.owner
                  AND (
                        e.state = 'pending'
                     OR (e.state = 'failed' AND e.attempts < 3)
                     OR (
                            e.state = 'committing'
                        AND (e.lease_until IS NULL OR e.lease_until < strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                     )
                  )
                ORDER BY e.created_at ASC, e.rowid ASC
                LIMIT ?
                """,
                (self.identity, limit),
            ).fetchall()
        )

    def classify_uncommitted(self) -> dict[str, list[sqlite3.Row]]:
        """Split rows a run will not claim into skipped and exhausted."""
        rows = self._conn.execute(
            "SELECT * FROM integration_events WHERE project_id = ? AND state != 'committed'",
            (self.identity,),
        ).fetchall()
        skipped: list[sqlite3.Row] = []
        exhausted: list[sqlite3.Row] = []
        for row in rows:
            binding = self.binding(str(row["client"]))
            disabled = (
                binding is None or not binding.enabled or binding.owner != row["owner"]
            )
            if row["state"] == "purged" or disabled:
                skipped.append(row)
            elif row["state"] == "failed" and int(row["attempts"]) >= 3:
                exhausted.append(row)
        return {"skipped": skipped, "exhausted": exhausted}

    def claim_row(self, key: str) -> str | None:
        """Compare-and-swap the row to ``committing``. Return the lease, or ``None``."""
        cursor = self._conn.execute(
            """
            UPDATE integration_events
            SET state = 'committing',
                attempts = attempts + 1,
                lease_until = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+40 seconds'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                result = COALESCE(result, '{"outcome":"committing","memory_ids":[]}')
            WHERE key = ?
              AND (
                    state = 'pending'
                 OR (state = 'failed' AND attempts < 3)
                 OR (
                        state = 'committing'
                    AND (lease_until IS NULL OR lease_until < strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                 )
              )
            """,
            (key,),
        )
        self._conn.commit()
        if cursor.rowcount != 1:
            return None
        row = self._conn.execute(
            "SELECT lease_until FROM integration_events WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return str(row["lease_until"])

    def get_event(self, key: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM integration_events WHERE key = ?", (key,)
        ).fetchone()

    def append_memory_id(self, key: str, lease: str, memory_id: str) -> bool:
        cursor = self._conn.execute(
            """
            UPDATE integration_events
            SET result = json_set(
                    COALESCE(result, '{"outcome":"committing","memory_ids":[]}'),
                    '$.memory_ids',
                    json_insert(
                        COALESCE(json_extract(result, '$.memory_ids'), json('[]')),
                        '$[#]',
                        ?
                    )
                ),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE key = ? AND state = 'committing' AND lease_until = ?
            """,
            (memory_id, key, lease),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def mark_claimed(
        self,
        key: str,
        lease: str,
        state: str,
        result: dict[str, Any],
        receipt: dict[str, Any] | None,
    ) -> bool:
        cursor = self._conn.execute(
            """
            UPDATE integration_events
            SET state = ?,
                result = ?,
                receipt = COALESCE(?, receipt),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE key = ? AND state = 'committing' AND lease_until = ?
            """,
            (
                state,
                json.dumps(result, separators=(",", ":")),
                json.dumps(receipt, separators=(",", ":"))
                if receipt is not None
                else None,
                key,
                lease,
            ),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def remaining_claimable(self) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM integration_events e
            JOIN integration_config c ON c.project_id = e.project_id AND c.client = e.client
            WHERE e.project_id = ? AND c.enabled = 1 AND e.owner = c.owner
              AND (
                    e.state = 'pending'
                 OR (e.state = 'failed' AND e.attempts < 3)
                 OR (
                        e.state = 'committing'
                    AND (e.lease_until IS NULL OR e.lease_until < strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                 )
              )
            """,
            (self.identity,),
        ).fetchone()
        return int(row["n"])


def _binding_from_row(row: sqlite3.Row) -> Binding:
    try:
        policy = json.loads(row["policy"])
    except (TypeError, json.JSONDecodeError):
        policy = {}
    if not isinstance(policy, dict):
        policy = {}
    namespace = str(row["storage_project_id"] or "")
    try:
        validate_project_id(namespace, normalize=False)
    except Exception as exc:
        raise StateError(
            "project_identity_invalid", "stored storage namespace is not valid"
        ) from exc
    return Binding(
        project_id=str(row["project_id"]),
        client=str(row["client"]),
        owner=str(row["owner"]),
        enabled=bool(row["enabled"]),
        project_root=str(row["project_root"]),
        config_path=str(row["config_path"]),
        storage_project_id=namespace,
        policy=_policy_view(policy),
    )


def _policy_view(policy: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when the stored policy is missing the flags."""
    if "recall" not in policy or "capture" not in policy or "refresh" not in policy:
        base = {
            "recall": False,
            "capture": False,
            "refresh": False,
            "context_budget": 0,
            "ignore_patterns": [],
        }
        base.update({key: policy[key] for key in policy if key == "ignore_patterns"})
        if "recall" in policy and "capture" in policy and "refresh" in policy:
            return policy
        # A complete policy written by enable always has the four flags.
        if all(
            key in policy for key in ("recall", "capture", "refresh", "context_budget")
        ):
            return policy
        return base
    return policy


def _now(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now') AS t"
    ).fetchone()
    return str(row["t"])


def check_project_files(project_root: Path) -> None:
    """Refuse a symlinked or escaping project directory, identity file or marker."""
    root = project_root.resolve()
    state_dir = root / ".agentic-inquiry"
    candidates = [state_dir, state_dir / "project.toml", state_dir / "integration.json"]
    for path in candidates:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            info = None
        if info is not None and stat.S_ISLNK(info.st_mode):
            raise StateError("project_files_invalid", _remedy(path, "link-dir"))
        try:
            validate_file_path(path, root)
        except PathValidationError as exc:
            raise StateError("project_files_invalid", _remedy(path, "type")) from exc


def write_identity(project_root: Path, identity: str) -> None:
    path = project_root / ".agentic-inquiry" / "project.toml"
    if path.exists():
        return
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path, flags, 0o644)
    try:
        os.write(fd, _GRAMMAR.format(identity=identity).encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def write_marker(project_root: Path, identity: str, clients: dict[str, Any]) -> None:
    state_dir = project_root / ".agentic-inquiry"
    body = json.dumps(
        {"schema_version": 1, "project_id": identity, "clients": clients},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    fd, temporary = tempfile.mkstemp(dir=state_dir)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, state_dir / "integration.json")


def update_marker_enabled(
    project_root: Path, client: str, *, owner: str, enabled: bool
) -> None:
    check_project_files(project_root)
    marker = read_marker(project_root) or {
        "schema_version": 1,
        "project_id": "",
        "clients": {},
    }
    clients = dict(marker.get("clients") or {})
    current = dict(clients.get(client) or {})
    current["owner"] = owner
    current["enabled"] = enabled
    clients[client] = current
    identity = str(marker.get("project_id") or read_identity(project_root) or "")
    write_marker(project_root, identity, clients)


@contextlib.contextmanager
def project_lock(identity: str, *, shared: bool, timeout: float) -> Iterator[None]:
    """Hold ``INQUIRY_HOME/projects/<id>/lock``. Never unlinked."""
    if IDENTITY_PATTERN.fullmatch(identity) is None:
        raise StateError(
            "project_identity_invalid",
            "project identity must be 16 lowercase hex characters",
        )
    directory = inquiry_home() / "projects" / identity
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / "lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise StateError(
            "environment_busy", f"project lock could not be opened (errno {exc.errno})"
        ) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise StateError(
                "environment_busy",
                f"project lock failed its check (errno {errno.EPERM})",
            )
        os.fchmod(fd, 0o600)
        mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in _CLOSED:
                    raise StateError(
                        "environment_busy",
                        f"project lock failed (errno {exc.errno})",
                    ) from exc
                if time.monotonic() >= deadline:
                    holder = "ai integration reconcile, an ai mcp maintenance tick"
                    raise StateError(
                        "environment_busy",
                        f"project lock is held by {holder}; retry with --wait",
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def new_identity() -> str:
    import secrets

    return secrets.token_hex(8)


def public_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "recall": bool(policy.get("recall")),
        "capture": bool(policy.get("capture")),
        "refresh": bool(policy.get("refresh")),
        "context_budget": int(policy.get("context_budget") or 0),
    }


def stored_namespace_ok(binding: Binding) -> bool:
    try:
        validate_project_id(binding.storage_project_id, normalize=False)
    except Exception:
        return False
    return binding.storage_project_id != ""
