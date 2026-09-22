"""Data models for onboard documentation tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class OnboardRun:
    """Metadata for a single onboard run.

    Attributes:
        run_id: Unique identifier (UUID4).
        project_id: Stable project identifier.
        timestamp: When onboard was executed.
        status: Run status (pending, running, completed, failed).
        is_latest: Whether this is the most recent successful run.
        commit_sha: Git commit SHA at time of onboard.
        file_count: Number of files processed.
        chunk_count: Number of chunks generated.
        entity_count: Number of entities extracted.
        artifact_path: Path to artifacts (local path or GCS URI).
        error_message: Error details if run failed.
        metadata: Additional metadata (duration, config, etc.).
    """

    run_id: str
    project_id: str
    timestamp: datetime
    status: str  # "pending", "running", "completed", "failed"
    is_latest: bool = False
    commit_sha: Optional[str] = None
    file_count: int = 0
    chunk_count: int = 0
    entity_count: int = 0
    artifact_path: str = ""
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
