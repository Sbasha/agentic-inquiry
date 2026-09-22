"""Onboard artifact storage abstraction.

Supports local filesystem and GCS backends for storing onboard
markdown reports (EXPLORATION, VALIDATION, ONBOARD).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_inquiry.config import Config

logger = logging.getLogger(__name__)


class OnboardArtifactStorage(Protocol):
    """Protocol for onboard artifact storage backends."""

    async def save_report(
        self, project_id: str, run_id: str, report_name: str, content: str
    ) -> str: ...

    async def load_report(
        self, project_id: str, run_id: str, report_name: str
    ) -> str: ...

    async def list_reports(
        self, project_id: str, run_id: str
    ) -> List[str]: ...

    async def delete_run_artifacts(
        self, project_id: str, run_id: str
    ) -> int: ...


class LocalOnboardArtifactStorage:
    """Local filesystem storage for onboard artifacts.

    Stores reports as markdown files in:
        {base_path}/{project_id}/{run_id}/{REPORT_NAME}.md

    Args:
        base_path: Root directory for artifact storage.
    """

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path

    def _get_run_dir(self, project_id: str, run_id: str) -> Path:
        run_dir = (self._base_path / project_id / run_id).resolve()
        base_resolved = self._base_path.resolve()
        # Containment check: ensure resolved path stays under base_path
        # Using relative_to() which raises ValueError on escape (not prefix-based)
        try:
            run_dir.relative_to(base_resolved)
        except ValueError:
            raise ValueError(
                f"Path traversal detected: {project_id}/{run_id} "
                f"escapes base path {base_resolved}"
            )
        return run_dir

    async def save_report(
        self, project_id: str, run_id: str, report_name: str, content: str
    ) -> str:
        """Save a report file to local filesystem.

        Returns:
            Absolute path to saved file.
        """
        run_dir = self._get_run_dir(project_id, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        report_path = run_dir / f"{report_name}.md"
        await asyncio.to_thread(report_path.write_text, content, encoding="utf-8")

        logger.debug("Saved report: %s", report_path)
        return str(report_path)

    async def load_report(
        self, project_id: str, run_id: str, report_name: str
    ) -> str:
        """Load a report from local filesystem.

        Raises:
            FileNotFoundError: If report does not exist.
        """
        report_path = self._get_run_dir(project_id, run_id) / f"{report_name}.md"

        if not report_path.exists():
            raise FileNotFoundError(f"Report not found: {report_path}")

        return await asyncio.to_thread(report_path.read_text, encoding="utf-8")

    async def list_reports(
        self, project_id: str, run_id: str
    ) -> List[str]:
        """List report names for a run."""
        run_dir = self._get_run_dir(project_id, run_id)

        if not run_dir.exists():
            return []

        return sorted(p.stem for p in run_dir.glob("*.md"))

    async def delete_run_artifacts(
        self, project_id: str, run_id: str
    ) -> int:
        """Delete all artifacts for a run.

        Returns:
            Number of files deleted.
        """
        run_dir = self._get_run_dir(project_id, run_id)

        if not run_dir.exists():
            return 0

        count = 0
        for path in run_dir.iterdir():
            if path.is_file():
                await asyncio.to_thread(path.unlink)
                count += 1

        # Remove the directory
        try:
            await asyncio.to_thread(run_dir.rmdir)
        except OSError:
            pass  # Directory not empty or other issue

        return count


class GCSOnboardArtifactStorage:
    """GCS bucket storage for onboard artifacts.

    Stores reports at:
        gs://{bucket}/{prefix}/{project_id}/{run_id}/{REPORT_NAME}.md

    Requires gcsfs package: pip install gcsfs

    Args:
        bucket: GCS bucket name.
        prefix: Base prefix within bucket (default: "onboard").
        storage_options: gcsfs options (token, project, etc.).
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "onboard",
        storage_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            import gcsfs  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "gcsfs is required for GCS storage. "
                "Install with: pip install gcsfs or pip install agentic-inquiry[gcs]"
            ) from e

        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._storage_options = storage_options or {}
        self._fs: Optional[Any] = None

    @property
    def fs(self) -> Any:
        """Lazy-initialize gcsfs filesystem."""
        if self._fs is None:
            import gcsfs
            self._fs = gcsfs.GCSFileSystem(**self._storage_options)
        return self._fs

    def _get_run_path(self, project_id: str, run_id: str) -> str:
        return f"{self._bucket}/{self._prefix}/{project_id}/{run_id}"

    async def save_report(
        self, project_id: str, run_id: str, report_name: str, content: str
    ) -> str:
        """Save report to GCS.

        Returns:
            GCS URI (gs://bucket/path).
        """
        report_path = f"{self._get_run_path(project_id, run_id)}/{report_name}.md"

        def _write() -> None:
            with self.fs.open(report_path, "w") as f:
                f.write(content)

        await asyncio.to_thread(_write)
        logger.debug("Saved report to GCS: gs://%s", report_path)
        return f"gs://{report_path}"

    async def load_report(
        self, project_id: str, run_id: str, report_name: str
    ) -> str:
        """Load report from GCS.

        Raises:
            FileNotFoundError: If report does not exist.
        """
        report_path = f"{self._get_run_path(project_id, run_id)}/{report_name}.md"

        def _read() -> str:
            with self.fs.open(report_path, "r") as f:
                return f.read()

        try:
            return await asyncio.to_thread(_read)
        except FileNotFoundError:
            raise FileNotFoundError(f"Report not found: gs://{report_path}")

    async def list_reports(
        self, project_id: str, run_id: str
    ) -> List[str]:
        """List report names for a run in GCS."""
        run_path = self._get_run_path(project_id, run_id)

        def _list() -> List[str]:
            try:
                files = self.fs.ls(run_path)
                return [Path(f).stem for f in files if f.endswith(".md")]
            except FileNotFoundError:
                return []

        reports = await asyncio.to_thread(_list)
        return sorted(reports)

    async def delete_run_artifacts(
        self, project_id: str, run_id: str
    ) -> int:
        """Delete all artifacts for a run in GCS."""
        run_path = self._get_run_path(project_id, run_id)

        def _delete() -> int:
            try:
                files = self.fs.ls(run_path)
                for f in files:
                    self.fs.rm(f)
                return len(files)
            except FileNotFoundError:
                return 0

        return await asyncio.to_thread(_delete)


def create_onboard_artifact_storage(
    config: "Config",
) -> OnboardArtifactStorage:
    """Create artifact storage based on configuration.

    Reads ``config.onboard.artifact_storage`` to determine backend:
    - ``type: "gcs"`` + ``gcs_bucket`` → GCSOnboardArtifactStorage
    - ``type: "local"`` (default) → LocalOnboardArtifactStorage

    When GCS is explicitly configured (``type: "gcs"``), errors are raised
    (not silently swallowed) so misconfigurations surface immediately.

    Args:
        config: ai configuration.

    Returns:
        OnboardArtifactStorage implementation.

    Raises:
        ImportError: If GCS is configured but gcsfs is not installed.
        RuntimeError: If GCS initialization fails.
    """
    onboard_cfg = getattr(config, "onboard", None)
    artifact_cfg = getattr(onboard_cfg, "artifact_storage", None) if onboard_cfg else None

    # Determine storage type from new config structure
    storage_type = getattr(artifact_cfg, "type", "local") if artifact_cfg else "local"
    gcs_bucket = getattr(artifact_cfg, "gcs_bucket", None) if artifact_cfg else None

    # Legacy fallback: check old config.onboard.gcs.bucket path
    if not gcs_bucket and onboard_cfg:
        gcs_cfg = getattr(onboard_cfg, "gcs", None)
        if gcs_cfg:
            gcs_bucket = getattr(gcs_cfg, "bucket", None)
            if gcs_bucket:
                storage_type = "gcs"

    if storage_type == "gcs" and gcs_bucket:
        gcs_prefix = getattr(artifact_cfg, "gcs_prefix", "onboard/") if artifact_cfg else "onboard/"
        # Strip trailing slash for consistency
        gcs_prefix = gcs_prefix.rstrip("/") or "onboard"

        logger.info(
            "Using GCS for onboard artifacts: gs://%s/%s", gcs_bucket, gcs_prefix
        )
        # Let ImportError and initialization errors propagate —
        # explicit GCS config means the user expects GCS to work
        return GCSOnboardArtifactStorage(
            bucket=gcs_bucket,
            prefix=gcs_prefix,
        )

    # Local storage — use configured local_path, resolve relative to storage root
    local_path = getattr(artifact_cfg, "local_path", "test_results/onboard") if artifact_cfg else "test_results/onboard"
    base_path = Path(local_path)
    if not base_path.is_absolute():
        base_path = Path(config.storage.root) / local_path

    logger.info("Using local filesystem for onboard artifacts: %s", base_path)
    return LocalOnboardArtifactStorage(base_path)
