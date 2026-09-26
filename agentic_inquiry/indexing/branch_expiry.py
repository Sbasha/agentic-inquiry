"""Branch expiry and pruning logic.

Provides soft-delete (expire) and hard-delete (prune) for indexed branch chunks.

Soft-delete: marks chunks is_active=False, expired_at=now() for branches that
are no longer in the active set.  The default branch is never expired.

Hard-delete (prune): permanently removes chunks that have been soft-deleted
longer than the retention window (default 30 days).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("ai.indexing.branch_expiry")

# Default retention window before hard deletion
HARD_DELETE_RETENTION_DAYS = 30


async def expire_stale_branches(
    storage: Any,  # StorageFacade
    project_id: str,
    active_branches: set[str],
    default_branch: str = "main",
) -> list[str]:
    """Soft-delete chunks for branches no longer in active_branches.

    Sets is_active=False and expired_at=now() on all active chunks that belong
    to branches absent from ``active_branches``.  The default branch is always
    exempt regardless of whether it appears in ``active_branches``.

    Supports both PostgreSQL/AlloyDB backends (via ``_execute`` + ``_chunks_table``)
    and LanceDB backends (via ``_db_manager``).  Returns an empty list when the
    schema is pre-migration (no ``is_active`` column) or when neither interface
    is available.

    Args:
        storage: StorageFacade instance.
        project_id: Project identifier used to scope the query.
        active_branches: Set of branch short-names currently eligible for indexing.
        default_branch: Default branch name — exempt from expiry.

    Returns:
        List of branch names that were soft-deleted in this call.
    """
    now = datetime.now(timezone.utc)
    vp = storage._vector_provider

    # ---- LanceDB path ----
    if hasattr(vp, "_db_manager") and vp._db_manager is not None:
        return await _expire_lancedb(
            vp=vp,
            project_id=project_id,
            active_branches=active_branches,
            default_branch=default_branch,
            now=now,
        )

    logger.warning(
        "expire_stale_branches: no supported storage interface found on %s",
        type(vp).__name__,
    )
    return []


async def _expire_lancedb(
    vp: Any,
    project_id: str,
    active_branches: set[str],
    default_branch: str,
    now: datetime,
) -> list[str]:
    """Expire stale branches on a LanceDB vector provider."""
    try:
        from agentic_inquiry.storage.providers.lancedb.vector import (
            DOCUMENT_CHUNKS_TABLE,
        )

        records = await vp._db_manager.advanced_filter(
            table_name=DOCUMENT_CHUNKS_TABLE,
            filters={"project_id": project_id, "is_active": True},
            limit=100_000,
        )
    except Exception as exc:
        logger.warning(
            "expire_stale_branches: LanceDB filter failed (schema may be pre-migration): %s",
            exc,
        )
        return []

    # Collect IDs per branch that need expiry
    branch_ids: dict[str, list[str]] = {}
    for rec in records:
        branch = rec.get("branch") or ""
        if not branch or branch == default_branch or branch in active_branches:
            continue
        chunk_id = rec.get("id") or rec.get("chunk_id") or ""
        if chunk_id:
            branch_ids.setdefault(branch, []).append(chunk_id)

    expired: list[str] = []
    for branch, ids in branch_ids.items():
        try:
            # LanceDB update: set is_active=False and expired_at on matched IDs
            table = await vp._db_manager.get_or_create_table(DOCUMENT_CHUNKS_TABLE)
            id_list = ", ".join(f"'{i}'" for i in ids)
            await table.update(
                where=f"id IN ({id_list})",
                values={"is_active": False, "expired_at": now.isoformat()},
            )
            logger.info(
                "expire_stale_branches: expired branch %r (%d chunks) for project %r",
                branch,
                len(ids),
                project_id,
            )
            expired.append(branch)
        except Exception as exc:
            logger.warning(
                "expire_stale_branches: LanceDB update failed for branch %r: %s",
                branch,
                exc,
            )

    return expired


async def prune_expired_branches(
    storage: Any,  # StorageFacade
    project_id: str,
    retention_days: int = HARD_DELETE_RETENTION_DAYS,
) -> int:
    """Hard-delete chunks that have been expired past the retention window.

    Permanently removes chunks where ``is_active=False`` AND
    ``expired_at < now() - retention_days``.

    Supports PostgreSQL/AlloyDB and LanceDB backends.  Returns 0 when the
    schema is pre-migration or the storage interface is unavailable.

    Args:
        storage: StorageFacade instance.
        project_id: Project identifier.
        retention_days: Days after expired_at before permanent deletion.

    Returns:
        Number of chunks permanently deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    vp = storage._vector_provider

    # ---- LanceDB path ----
    if hasattr(vp, "_db_manager") and vp._db_manager is not None:
        return await _prune_lancedb(vp=vp, project_id=project_id, cutoff=cutoff)

    logger.warning(
        "prune_expired_branches: no supported storage interface found on %s",
        type(vp).__name__,
    )
    return 0


async def _prune_lancedb(
    vp: Any,
    project_id: str,
    cutoff: datetime,
) -> int:
    """Hard-delete prunable chunks on LanceDB."""
    try:
        from agentic_inquiry.storage.providers.lancedb.vector import (
            DOCUMENT_CHUNKS_TABLE,
        )

        records = await vp._db_manager.advanced_filter(
            table_name=DOCUMENT_CHUNKS_TABLE,
            filters={"project_id": project_id, "is_active": False},
            limit=100_000,
        )
    except Exception as exc:
        logger.warning(
            "prune_expired_branches: LanceDB filter failed: %s",
            exc,
        )
        return 0

    cutoff_str = cutoff.isoformat()
    prunable_ids: list[str] = []
    for rec in records:
        expired_at_raw = rec.get("expired_at")
        if not expired_at_raw:
            continue
        # Normalise: expired_at may be stored as ISO string or datetime
        if isinstance(expired_at_raw, datetime):
            expired_at = expired_at_raw
            if expired_at.tzinfo is None:
                expired_at = expired_at.replace(tzinfo=timezone.utc)
        else:
            try:
                expired_at = datetime.fromisoformat(str(expired_at_raw))
                if expired_at.tzinfo is None:
                    expired_at = expired_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

        if expired_at < cutoff:
            chunk_id = rec.get("id") or rec.get("chunk_id") or ""
            if chunk_id:
                prunable_ids.append(chunk_id)

    if not prunable_ids:
        return 0

    try:
        table = await vp._db_manager.get_or_create_table(DOCUMENT_CHUNKS_TABLE)
        id_list = ", ".join(f"'{i}'" for i in prunable_ids)
        await table.delete(where=f"id IN ({id_list})")
        logger.info(
            "prune_expired_branches: hard-deleted %d LanceDB chunks for project %r",
            len(prunable_ids),
            project_id,
        )
        return len(prunable_ids)
    except Exception as exc:
        logger.warning(
            "prune_expired_branches: LanceDB delete failed: %s",
            exc,
        )
        return 0
