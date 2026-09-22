"""High-level service for onboard metadata management.

Provides CRUD operations over the storage provider, abstracting
away backend-specific details.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, TYPE_CHECKING

from agentic_inquiry.onboard.models import OnboardRun

if TYPE_CHECKING:
    from agentic_inquiry.config import Config

logger = logging.getLogger(__name__)


class OnboardMetadataService:
    """High-level service for onboard metadata management.

    Wraps a storage provider to provide convenient CRUD operations
    for onboard runs.

    Args:
        provider: An initialized onboard metadata provider
            (SQLiteOnboardMetadataProvider or similar).
        project_id: Project identifier.
    """

    def __init__(self, provider: Any, project_id: str) -> None:
        self._provider = provider
        self._project_id = project_id

    @classmethod
    async def from_config(
        cls,
        config: Optional["Config"],
        workspace: str = "",
        project_id: Optional[str] = None,
    ) -> "OnboardMetadataService":
        """Create service from configuration.

        Auto-selects PostgreSQL provider when backend is postgresql/cloudsql/alloydb,
        falls back to SQLite for local/LanceDB backends or when config is None.

        Args:
            config: ai configuration (None uses SQLite with workspace path).
            workspace: Workspace path (for project-local DB location).
            project_id: Explicit project ID (uses config default if None).

        Returns:
            Initialized OnboardMetadataService.
        """
        pid = "default"
        if config is not None:
            pid = project_id or getattr(config.storage, "default_project_id", None) or "default"
        elif project_id:
            pid = project_id

        # Determine backend type from config
        backend_type = None
        if config is not None:
            backend_type = getattr(config.storage, "backend", None)

        pg_backends = {"postgresql", "cloudsql", "alloydb"}
        if backend_type in pg_backends:
            provider = await cls._create_pg_provider(config, pid)
        else:
            provider = await cls._create_sqlite_provider(config, workspace, pid)

        return cls(provider=provider, project_id=pid)

    @staticmethod
    async def _create_pg_provider(
        config: "Config", project_id: str
    ) -> Any:
        """Create PostgreSQL onboard metadata provider from config."""
        logger.info("Creating PG provider for project: %s", project_id)
        from agentic_inquiry.onboard.providers.postgresql import (
            PostgresOnboardMetadataProvider,
        )
        from agentic_inquiry.storage.registry import resolve_backend

        try:
            _name, backend_config = resolve_backend(
                config.storage, "onboard_metadata"
            )
            provider = PostgresOnboardMetadataProvider.from_config(
                backend_config, project_id
            )
        except Exception as e:
            # If onboard_metadata role isn't configured for PG, build from
            # the primary backend config (vector backend shares the same DB)
            logger.debug("onboard_metadata role not found, falling back to vector backend: %s", e)
            _name, backend_config = resolve_backend(config.storage, "vector")
            provider = PostgresOnboardMetadataProvider.from_config(
                backend_config, project_id
            )

        await provider.initialize()
        logger.info(
            "Onboard metadata service initialized (PostgreSQL): project=%s",
            project_id,
        )
        return provider

    @staticmethod
    async def _create_sqlite_provider(
        config: Optional["Config"], workspace: str, project_id: str
    ) -> Any:
        """Create SQLite onboard metadata provider."""
        from agentic_inquiry.onboard.providers.sqlite import (
            SQLiteOnboardMetadataProvider,
        )

        root = workspace
        if not root and config is not None:
            root = getattr(config.storage, "root", "") or ""
        root = root or ".agentic-inquiry"

        db_path = Path(root) / ".agentic-inquiry" / "onboard_metadata.db"
        # If root itself contains .agentic-inquiry, don't double it
        if ".agentic-inquiry" in str(root):
            db_path = Path(root) / "onboard_metadata.db"

        provider = SQLiteOnboardMetadataProvider(
            db_path=db_path, project_id=project_id
        )
        await provider.initialize()
        logger.info(
            "Onboard metadata service initialized (SQLite): project=%s, db=%s",
            project_id, db_path,
        )
        return provider

    async def create_onboard_run(
        self,
        artifact_path: str,
        commit_sha: Optional[str] = None,
    ) -> OnboardRun:
        """Start a new onboard run.

        Args:
            artifact_path: Path to store artifacts.
            commit_sha: Current git commit SHA.

        Returns:
            New OnboardRun with status=pending.
        """
        run = OnboardRun(
            run_id=str(uuid.uuid4()),
            project_id=self._project_id,
            timestamp=datetime.now(timezone.utc),
            status="pending",
            is_latest=False,
            commit_sha=commit_sha,
            artifact_path=artifact_path,
        )
        await self._provider.create_run(run)
        logger.info("Created onboard run %s for project %s", run.run_id, self._project_id)
        return run

    async def complete_onboard_run(
        self,
        run_id: str,
        file_count: int = 0,
        chunk_count: int = 0,
        entity_count: int = 0,
    ) -> None:
        """Mark a run as completed and set as latest.

        Args:
            run_id: Run to complete.
            file_count: Files processed.
            chunk_count: Chunks created.
            entity_count: Entities extracted.
        """
        # Use atomic complete_run if available, otherwise fall back
        if hasattr(self._provider, "complete_run"):
            await self._provider.complete_run(
                run_id,
                file_count=file_count,
                chunk_count=chunk_count,
                entity_count=entity_count,
            )
        else:
            await self._provider.update_run(run_id, {
                "status": "completed",
                "file_count": file_count,
                "chunk_count": chunk_count,
                "entity_count": entity_count,
            })
            await self._provider.mark_latest(run_id)
        logger.info(
            "Completed onboard run %s: %s files, %s chunks, %s entities",
            run_id, file_count, chunk_count, entity_count,
        )

    async def fail_onboard_run(self, run_id: str, error: str) -> None:
        """Mark a run as failed.

        Args:
            run_id: Run that failed.
            error: Error message.
        """
        await self._provider.update_run(run_id, {
            "status": "failed",
            "error_message": error,
        })
        logger.warning("Failed onboard run %s: %s", run_id, error)

    async def get_latest_onboard(self) -> Optional[OnboardRun]:
        """Get the latest successful onboard for this project."""
        return await self._provider.get_latest_run(self._project_id)

    async def list_runs(self, limit: int = 10) -> List[OnboardRun]:
        """List recent runs for this project."""
        return await self._provider.list_runs(self._project_id, limit=limit)

    async def close(self) -> None:
        """Release resources."""
        await self._provider.close()
