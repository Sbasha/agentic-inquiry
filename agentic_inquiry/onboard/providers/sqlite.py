"""SQLite-based onboard metadata provider.

Follows the pattern from agentic_inquiry/storage/providers/sqlite/ for
events and file_tracker providers.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiosqlite

from agentic_inquiry.onboard.models import OnboardRun

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS onboard_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    status TEXT NOT NULL,
    is_latest INTEGER NOT NULL DEFAULT 0,
    commit_sha TEXT,
    file_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    entity_count INTEGER NOT NULL DEFAULT 0,
    artifact_path TEXT NOT NULL DEFAULT '',
    error_message TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_onboard_project_timestamp
    ON onboard_runs(project_id, timestamp DESC)
"""

_CREATE_LATEST_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_onboard_latest_per_project
    ON onboard_runs(project_id) WHERE is_latest = 1
"""


class SQLiteOnboardMetadataProvider:
    """SQLite provider for onboard metadata storage.

    Auto-creates tables on initialize(). Uses WAL mode for
    concurrent read access.

    Args:
        db_path: Path to SQLite database file.
        project_id: Project identifier for data isolation.
    """

    def __init__(
        self,
        db_path: Union[str, Path],
        project_id: str = "",
        **kwargs: Any,
    ) -> None:
        self._db_path = Path(db_path)
        self._project_id = project_id
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Create schema and open connection."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        # PRAGMA set kept in sync with ``events/storage/sqlite.py`` and
        # ``events/store.py`` — the three SQLite writers share the same
        # tuning (WAL + NORMAL sync + 10s busy_timeout). The 10s
        # timeout was originally sized for
        # ``indexing.processing_semaphore_limit=10``; it's been kept at
        # 10s after the semaphore default rose to 20 (revisit if
        # SQLITE_BUSY surfaces at 20+ workers). The previous initialize
        # set only ``journal_mode=WAL`` and inherited SQLite's default
        # ``busy_timeout=0``, which meant any lock contention failed
        # immediately — worse than the 5s we were bumping off in the
        # other writers.
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=10000")
        await self._db.execute(_CREATE_TABLE_SQL)
        await self._db.execute(_CREATE_INDEX_SQL)
        await self._db.execute(_CREATE_LATEST_INDEX_SQL)
        await self._db.commit()
        logger.debug("Onboard metadata schema initialized at %s", self._db_path)

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Provider not initialized. Call initialize() first.")
        return self._db

    def _row_to_run(self, row: aiosqlite.Row) -> OnboardRun:
        """Convert a database row to OnboardRun."""
        return OnboardRun(
            run_id=row[0],
            project_id=row[1],
            timestamp=datetime.fromtimestamp(row[2], tz=timezone.utc),
            status=row[3],
            is_latest=bool(row[4]),
            commit_sha=row[5],
            file_count=row[6],
            chunk_count=row[7],
            entity_count=row[8],
            artifact_path=row[9],
            error_message=row[10],
            metadata=json.loads(row[11]) if row[11] else {},
        )

    async def create_run(self, run: OnboardRun) -> None:
        """Insert a new onboard run."""
        db = self._ensure_db()
        await db.execute(
            """INSERT INTO onboard_runs
               (run_id, project_id, timestamp, status, is_latest,
                commit_sha, file_count, chunk_count, entity_count,
                artifact_path, error_message, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.run_id,
                run.project_id,
                run.timestamp.timestamp(),
                run.status,
                int(run.is_latest),
                run.commit_sha,
                run.file_count,
                run.chunk_count,
                run.entity_count,
                run.artifact_path,
                run.error_message,
                json.dumps(run.metadata),
            ),
        )
        await db.commit()

    # Allowed column names for update_run to prevent SQL injection
    _UPDATABLE_COLUMNS = frozenset({
        "status", "is_latest", "commit_sha", "file_count", "chunk_count",
        "entity_count", "artifact_path", "error_message", "metadata", "timestamp",
    })

    async def update_run(self, run_id: str, updates: Dict[str, Any]) -> None:
        """Update fields on an existing run."""
        db = self._ensure_db()
        set_clauses = []
        values: list[Any] = []
        for key, value in updates.items():
            if key not in self._UPDATABLE_COLUMNS:
                raise ValueError(f"Cannot update column: {key}")
            if key == "metadata":
                set_clauses.append("metadata = ?")
                values.append(json.dumps(value))
            elif key == "is_latest":
                set_clauses.append("is_latest = ?")
                values.append(int(value))
            elif key == "timestamp":
                set_clauses.append("timestamp = ?")
                values.append(value.timestamp() if isinstance(value, datetime) else value)
            else:
                set_clauses.append(f"{key} = ?")
                values.append(value)

        if not set_clauses:
            return

        values.append(run_id)
        sql = f"UPDATE onboard_runs SET {', '.join(set_clauses)} WHERE run_id = ?"
        await db.execute(sql, values)
        await db.commit()

    async def get_run(self, run_id: str) -> Optional[OnboardRun]:
        """Get a run by ID."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT * FROM onboard_runs WHERE run_id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_run(row) if row else None

    async def get_latest_run(self, project_id: str) -> Optional[OnboardRun]:
        """Get the most recent successful run for a project."""
        db = self._ensure_db()
        cursor = await db.execute(
            """SELECT * FROM onboard_runs
               WHERE project_id = ? AND is_latest = 1 AND status = 'completed'
               LIMIT 1""",
            (project_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_run(row) if row else None

    async def list_runs(
        self, project_id: str, limit: int = 10
    ) -> List[OnboardRun]:
        """List recent runs for a project."""
        db = self._ensure_db()
        cursor = await db.execute(
            """SELECT * FROM onboard_runs
               WHERE project_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (project_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_run(row) for row in rows]

    async def complete_run(
        self,
        run_id: str,
        file_count: int = 0,
        chunk_count: int = 0,
        entity_count: int = 0,
    ) -> None:
        """Atomically mark run as completed and set as latest.

        Combines status update and latest marking in a single transaction.
        """
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT project_id FROM onboard_runs WHERE run_id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Run not found: {run_id}")

        project_id = row[0]
        await db.execute(
            """UPDATE onboard_runs
               SET status = 'completed', file_count = ?, chunk_count = ?, entity_count = ?
               WHERE run_id = ?""",
            (file_count, chunk_count, entity_count, run_id),
        )
        await db.execute(
            "UPDATE onboard_runs SET is_latest = 0 WHERE project_id = ? AND is_latest = 1",
            (project_id,),
        )
        await db.execute(
            "UPDATE onboard_runs SET is_latest = 1 WHERE run_id = ?",
            (run_id,),
        )
        await db.commit()

    async def mark_latest(self, run_id: str) -> None:
        """Mark a run as latest, clearing previous is_latest flags."""
        db = self._ensure_db()
        # Get the project_id for this run
        cursor = await db.execute(
            "SELECT project_id FROM onboard_runs WHERE run_id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Run not found: {run_id}")

        project_id = row[0]

        # Clear previous latest, then set new one
        await db.execute(
            "UPDATE onboard_runs SET is_latest = 0 WHERE project_id = ? AND is_latest = 1",
            (project_id,),
        )
        await db.execute(
            "UPDATE onboard_runs SET is_latest = 1 WHERE run_id = ?",
            (run_id,),
        )
        await db.commit()
