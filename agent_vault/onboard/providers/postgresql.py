"""PostgreSQL-based onboard metadata provider.

Uses asyncpg via PostgresConnectionManager, following the same patterns
as PostgresVectorProvider and PostgresGraphProvider.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agent_vault.onboard.models import OnboardRun

if TYPE_CHECKING:
    from agent_vault.storage.providers.postgresql.connection import (
        PostgresConnectionManager,
    )

logger = logging.getLogger(__name__)

# Table name suffix (prefixed by connection manager's table_prefix)
_TABLE_SUFFIX = "onboard_runs"


class PostgresOnboardMetadataProvider:
    """PostgreSQL provider for onboard metadata storage.

    Uses the shared PostgresConnectionManager for connection pooling.
    Auto-creates tables on initialize().

    Args:
        connection_manager: PostgresConnectionManager instance.
        project_id: Project identifier for data isolation.
    """

    SUPPORTED_ROLES = frozenset({"onboard_metadata"})

    # Allowed column names for update_run to prevent SQL injection
    _UPDATABLE_COLUMNS = frozenset({
        "status", "is_latest", "commit_sha", "file_count", "chunk_count",
        "entity_count", "artifact_path", "error_message", "metadata", "timestamp",
    })

    def __init__(
        self,
        connection_manager: "PostgresConnectionManager",
        project_id: str,
    ) -> None:
        self._conn = connection_manager
        self._project_id = project_id
        self._table = f"{connection_manager.table_prefix}{_TABLE_SUFFIX}"
        self._initialized = False

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        project_id: str,
    ) -> "PostgresOnboardMetadataProvider":
        """Create provider from configuration dict.

        Supports both direct connection_string and GCP proxy params.

        Args:
            config: Configuration with connection_string or GCP params.
            project_id: Project ID for data isolation.

        Returns:
            Configured PostgresOnboardMetadataProvider instance.
        """
        from agent_vault.storage.providers.postgresql.connection import (
            PostgresConnectionManager,
        )

        resolved_config = dict(config)
        backend_type = resolved_config.get("type", "postgresql")

        if backend_type == "alloydb":
            from agent_vault.storage.providers.alloydb import AlloyDBConnectionManager
            manager = AlloyDBConnectionManager.from_config(resolved_config)
        else:
            if not resolved_config.get("connection_string"):
                # Reuse DSN builder from vector provider
                from agent_vault.storage.providers.postgresql.vector import (
                    PostgresVectorProvider,
                )
                resolved_config["connection_string"] = (
                    PostgresVectorProvider._build_dsn_from_config(config)
                )

            manager = PostgresConnectionManager.from_config(
                resolved_config,
                table_prefix=config.get("table_prefix", "agv_"),
            )
        return cls(manager, project_id)

    async def initialize(self) -> None:
        """Create schema if not exists."""
        if self._initialized:
            return

        await self._conn.initialize()

        create_table = f"""
        CREATE TABLE IF NOT EXISTS {self._table} (
            run_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL,
            is_latest BOOLEAN NOT NULL DEFAULT FALSE,
            commit_sha TEXT,
            file_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            entity_count INTEGER NOT NULL DEFAULT 0,
            artifact_path TEXT NOT NULL DEFAULT '',
            error_message TEXT,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
        )
        """
        create_idx = f"""
        CREATE INDEX IF NOT EXISTS idx_{self._table}_project_ts
            ON {self._table}(project_id, timestamp DESC)
        """
        # Partial unique index: only one is_latest=true per project
        create_latest_idx = f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_{self._table}_latest
            ON {self._table}(project_id) WHERE is_latest = TRUE
        """

        await self._conn.execute(create_table)
        await self._conn.execute(create_idx)
        await self._conn.execute(create_latest_idx)
        self._initialized = True
        logger.debug("Onboard metadata schema initialized: %s", self._table)

    async def close(self) -> None:
        """Release resources (pool is shared, not closed here)."""
        self._initialized = False

    def _row_to_run(self, row: Any) -> OnboardRun:
        """Convert an asyncpg Record to OnboardRun."""
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        return OnboardRun(
            run_id=row["run_id"],
            project_id=row["project_id"],
            timestamp=row["timestamp"],
            status=row["status"],
            is_latest=bool(row["is_latest"]),
            commit_sha=row["commit_sha"],
            file_count=row["file_count"],
            chunk_count=row["chunk_count"],
            entity_count=row["entity_count"],
            artifact_path=row["artifact_path"],
            error_message=row["error_message"],
            metadata=meta if isinstance(meta, dict) else {},
        )

    async def create_run(self, run: OnboardRun) -> None:
        """Insert a new onboard run."""
        await self._conn.execute(
            f"""INSERT INTO {self._table}
               (run_id, project_id, timestamp, status, is_latest,
                commit_sha, file_count, chunk_count, entity_count,
                artifact_path, error_message, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
            run.run_id,
            run.project_id,
            run.timestamp,
            run.status,
            run.is_latest,
            run.commit_sha,
            run.file_count,
            run.chunk_count,
            run.entity_count,
            run.artifact_path,
            run.error_message,
            json.dumps(run.metadata),
        )

    async def update_run(self, run_id: str, updates: Dict[str, Any]) -> None:
        """Update fields on an existing run."""
        set_clauses = []
        values: list[Any] = []
        idx = 1

        for key, value in updates.items():
            if key not in self._UPDATABLE_COLUMNS:
                raise ValueError(f"Cannot update column: {key}")
            if key == "metadata":
                set_clauses.append(f"metadata = ${idx}::jsonb")
                values.append(json.dumps(value))
            elif key == "is_latest":
                set_clauses.append(f"is_latest = ${idx}")
                values.append(bool(value))
            elif key == "timestamp":
                set_clauses.append(f"timestamp = ${idx}")
                values.append(
                    value if isinstance(value, datetime)
                    else datetime.fromtimestamp(value, tz=timezone.utc)
                )
            else:
                set_clauses.append(f"{key} = ${idx}")
                values.append(value)
            idx += 1

        if not set_clauses:
            return

        values.append(run_id)
        sql = (
            f"UPDATE {self._table} SET {', '.join(set_clauses)} "
            f"WHERE run_id = ${idx}"
        )
        await self._conn.execute(sql, *values)

    async def get_run(self, run_id: str) -> Optional[OnboardRun]:
        """Get a run by ID."""
        row = await self._conn.fetchrow(
            f"SELECT * FROM {self._table} WHERE run_id = $1", run_id
        )
        return self._row_to_run(row) if row else None

    async def get_latest_run(self, project_id: str) -> Optional[OnboardRun]:
        """Get the most recent successful run for a project."""
        row = await self._conn.fetchrow(
            f"""SELECT * FROM {self._table}
               WHERE project_id = $1 AND is_latest = TRUE AND status = 'completed'
               LIMIT 1""",
            project_id,
        )
        return self._row_to_run(row) if row else None

    async def list_runs(
        self, project_id: str, limit: int = 10
    ) -> List[OnboardRun]:
        """List recent runs for a project."""
        rows = await self._conn.fetch(
            f"""SELECT * FROM {self._table}
               WHERE project_id = $1
               ORDER BY timestamp DESC
               LIMIT $2""",
            project_id,
            limit,
        )
        return [self._row_to_run(row) for row in rows]

    async def complete_run(
        self,
        run_id: str,
        file_count: int = 0,
        chunk_count: int = 0,
        entity_count: int = 0,
    ) -> None:
        """Atomically mark run as completed and set as latest.

        Uses a transaction to ensure status update and latest marking
        happen together or not at all.
        """
        async with self._conn.transaction() as conn:
            row = await conn.fetchrow(
                f"SELECT project_id FROM {self._table} WHERE run_id = $1",
                run_id,
            )
            if not row:
                raise ValueError(f"Run not found: {run_id}")

            project_id = row["project_id"]
            await conn.execute(
                f"""UPDATE {self._table}
                   SET status = 'completed', file_count = $1,
                       chunk_count = $2, entity_count = $3
                   WHERE run_id = $4""",
                file_count, chunk_count, entity_count, run_id,
            )
            await conn.execute(
                f"""UPDATE {self._table}
                   SET is_latest = FALSE
                   WHERE project_id = $1 AND is_latest = TRUE""",
                project_id,
            )
            await conn.execute(
                f"UPDATE {self._table} SET is_latest = TRUE WHERE run_id = $1",
                run_id,
            )

    async def mark_latest(self, run_id: str) -> None:
        """Mark a run as latest, clearing previous is_latest flags."""
        async with self._conn.transaction() as conn:
            row = await conn.fetchrow(
                f"SELECT project_id FROM {self._table} WHERE run_id = $1",
                run_id,
            )
            if not row:
                raise ValueError(f"Run not found: {run_id}")

            project_id = row["project_id"]
            await conn.execute(
                f"""UPDATE {self._table}
                   SET is_latest = FALSE
                   WHERE project_id = $1 AND is_latest = TRUE""",
                project_id,
            )
            await conn.execute(
                f"UPDATE {self._table} SET is_latest = TRUE WHERE run_id = $1",
                run_id,
            )
