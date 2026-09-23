"""Commit queued captures and refreshes.

``reconcile`` is the only path that opens the memory store or the indexer.
Hooks queue work and return; this module, and the MCP maintenance tick, commit it.
"""

from __future__ import annotations

import hashlib
import json
import stat
import time
from pathlib import Path
from typing import Any

from agentic_inquiry.integration.contract import EXCLUSION_FLOOR, matches_exclusion
from agentic_inquiry.integration.state import (
    Ledger,
    StateError,
    project_lock,
    read_identity,
)
from agentic_inquiry.integration.verbs import _canonical_root, _configure_embedder
from agentic_inquiry.mcp.utils.validation import PathValidationError, validate_file_path

_ROW_BUDGET = 30.0
_EMPTY = {"outcome": "skipped", "memory_ids": []}


async def reconcile(
    project_root: str,
    *,
    client: str | None = None,
    limit: int = 100,
    lock_timeout: float = 30.0,
    retry: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Commit up to ``limit`` claimable rows. Disabled clients are skipped."""
    del client  # one project lock covers every client; the binding decides each row
    root = _canonical_root(project_root)
    identity = read_identity(root)
    zeros = _zeros()
    if identity is None:
        return zeros
    preview = Ledger.open(identity, timeout=10, create=True, heal=True)
    try:
        preview.sweep_tombstones()
        bindings = preview.bindings()
        if bindings and (
            bindings[0].project_root != str(root)
            or not Path(bindings[0].project_root).is_dir()
        ):
            raise StateError(
                "project_identity_invalid", "project root does not match the binding"
            )
        if not bindings:
            return zeros
        binding = bindings[0]
    finally:
        preview.close()
    with project_lock(identity, shared=True, timeout=lock_timeout):
        if retry:
            ledger = Ledger.open(identity, timeout=10, create=True, heal=True)
            try:
                ledger.reset_for_retry(retry, force=force)
            finally:
                ledger.close()
        return await _reconcile_locked(identity, root, binding, limit=limit)


async def _reconcile_locked(
    identity: str, root: Path, binding: Any, *, limit: int
) -> dict[str, Any]:
    ledger = Ledger.open(identity, timeout=10, create=True, heal=True)
    classified = ledger.classify_uncommitted()
    candidates = [str(row["key"]) for row in ledger.claim_candidates(limit=limit)]
    rows: list[dict[str, Any]] = []
    committed = 0
    failed = 0
    lost = 0
    memory = None
    storage = None
    pipeline = None
    try:
        for key in candidates:
            lease = ledger.claim_row(key)
            if lease is None:
                continue
            row = ledger.get_event(key)
            if row is None:
                lost += 1
                continue
            started = time.monotonic()
            try:
                if memory is None and (
                    row["kind"] == "capture" or row["kind"] == "refresh"
                ):
                    memory, storage, pipeline = await _open_runtime(binding)
                outcome, result, receipt = await _commit_one(
                    ledger,
                    row,
                    lease,
                    root,
                    binding,
                    memory,
                    storage,
                    pipeline,
                    started,
                )
            except _Lost:
                lost += 1
                rows.append(
                    _row_view(row, {"outcome": "lost", "memory_ids": []}, state="lost")
                )
                continue
            if outcome == "committed":
                committed += 1
            elif outcome == "failed":
                failed += 1
            elif outcome == "lost":
                lost += 1
            fresh = ledger.get_event(key)
            rows.append(_row_view(fresh or row, result, receipt=receipt))
        for skipped in classified["skipped"]:
            rows.append(_row_view(skipped, _stored_result(skipped) or dict(_EMPTY)))
        for exhausted in classified["exhausted"]:
            rows.append(_row_view(exhausted, _stored_result(exhausted) or dict(_EMPTY)))
        remaining = ledger.remaining_claimable()
    finally:
        ledger.close()
    return {
        "committed": committed,
        "failed": failed,
        "skipped": len(classified["skipped"]),
        "exhausted": len(classified["exhausted"]),
        "lost": lost,
        "remaining": remaining,
        "rows": rows,
    }


async def _commit_one(
    ledger: Ledger,
    row: Any,
    lease: str,
    root: Path,
    binding: Any,
    memory: Any,
    storage: Any,
    pipeline: Any,
    started: float,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    if time.monotonic() - started > _ROW_BUDGET:
        return _fail(ledger, row, lease, "timeout")
    if row["kind"] == "capture":
        return await _commit_capture(ledger, row, lease, binding, memory, storage)
    return await _commit_refresh(ledger, row, lease, root, binding, pipeline)


async def _commit_capture(
    ledger: Ledger,
    row: Any,
    lease: str,
    binding: Any,
    memory: Any,
    storage: Any,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    payload = json.loads(row["payload"])
    key = str(row["key"])
    await _invalidate(storage, binding)
    found = await _by_task(memory, key)
    present = {
        int(item.metadata.get("observation_index"))
        for item in found
        if isinstance(getattr(item, "metadata", None), dict)
        and isinstance(item.metadata.get("observation_index"), int)
    }
    ids = _existing_ids(row)
    for index, observation in enumerate(payload):
        if index in present:
            continue
        meta = dict(observation.get("metadata") or {})
        meta.update(
            {
                "event_key": key,
                "event": row["event"],
                "project_identity": binding.project_id,
                "observation_index": index,
            }
        )
        importance = observation.get("importance")
        score = max(0.7, float(importance) if importance is not None else 0.7)
        context = memory.create_agent_context(
            agent_id=f"{row['owner']}:{row['client']}",
            session_id=str(row["session_id"]),
            conversation_id=str(row["session_id"]),
            task_id=key,
            project_id=binding.storage_project_id,
        )
        item = await memory.store(
            str(observation["content"]),
            context=context,
            importance=score,
            summary=observation.get("summary"),
            metadata=meta,
        )
        if not ledger.append_memory_id(key, lease, item.id):
            await _drop_if_purged(ledger, memory, key, [item.id])
            raise _Lost()
        ids.append(item.id)
        present.add(index)
    receipt = {"kind": "remembered", "durable_id": f"capture:{key}"}
    result = {"outcome": "remembered", "memory_ids": ids}
    if not ledger.mark_claimed(key, lease, "committed", result, receipt):
        raise _Lost()
    return "committed", result, receipt


async def _commit_refresh(
    ledger: Ledger,
    row: Any,
    lease: str,
    root: Path,
    binding: Any,
    pipeline: Any,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    paths = json.loads(row["payload"])
    key = str(row["key"])
    patterns = tuple(binding.policy.get("ignore_patterns") or ())
    resolved_paths: list[tuple[str, Path]] = []
    for relative in paths:
        if not isinstance(relative, str):
            return _fail(ledger, row, lease, "artifact_escape")
        full = root / relative
        if full.is_symlink() or _special_file(full):
            return (
                _fail(ledger, row, lease, "artifact_escape")
                if full.is_symlink()
                else _ignore_refresh(ledger, row, lease)
            )
        try:
            resolved = validate_file_path(full, root)
        except PathValidationError:
            return _fail(ledger, row, lease, "artifact_escape")
        again = resolved.relative_to(root.resolve()).as_posix()
        if again != relative:
            return _fail(ledger, row, lease, "artifact_escape")
        if matches_exclusion(again, EXCLUSION_FLOOR) or (
            patterns and matches_exclusion(again, patterns)
        ):
            receipt = {"kind": "queued", "durable_id": f"refresh:{key}"}
            result = {"outcome": "artifact_ignored", "memory_ids": []}
            if not ledger.mark_claimed(key, lease, "committed", result, receipt):
                raise _Lost()
            return "committed", result, receipt
        if resolved.exists() and _too_large_or_binary(resolved):
            receipt = {"kind": "queued", "durable_id": f"refresh:{key}"}
            result = {"outcome": "artifact_ignored", "memory_ids": []}
            if not ledger.mark_claimed(key, lease, "committed", result, receipt):
                raise _Lost()
            return "committed", result, receipt
        resolved_paths.append((again, resolved))
    try:
        for relative, resolved in resolved_paths:
            if not resolved.exists():
                await pipeline.remove_file_data(str(root / relative))
                continue
            from agentic_inquiry.parsers.chain import ParserChain

            document = await ParserChain(config=pipeline.config).parse(str(resolved))
            if not document.chunks:
                document = _plaintext_document(resolved)
            await pipeline.reindex_document(document)
            await pipeline.flush_pending_relationships()
            await _track(pipeline, binding, resolved)
    except Exception:
        return _fail(ledger, row, lease, "index_failed")
    receipt = {"kind": "indexed", "durable_id": f"refresh:{key}"}
    result = {"outcome": "indexed", "memory_ids": []}
    if not ledger.mark_claimed(key, lease, "committed", result, receipt):
        raise _Lost()
    return "committed", result, receipt


def _plaintext_document(path: Path) -> Any:
    """Index the file bytes as one chunk when the document parser extracts nothing.

    ``unstructured`` drops a markdown file whose first line is a ``<<`` frame, and
    that frame is exactly the text a later query has to be able to find.
    """
    from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk

    text = path.read_text(encoding="utf-8", errors="replace")
    chunks: list[Any] = []
    if text.strip():
        chunks.append(
            ParserChunk(
                content=text,
                fts_text=text,
                content_type="PROSE",
                element_type="section",
                line_start=1,
                line_end=max(text.count("\n"), 0) + 1,
            )
        )
    return ParsedDocument(
        doc_id=hashlib.md5(str(path).encode()).hexdigest(),
        file_path=str(path),
        chunks=chunks,
    )


def _special_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return not stat.S_ISREG(info.st_mode)


def _ignore_refresh(
    ledger: Ledger, row: Any, lease: str
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    key = str(row["key"])
    receipt = {"kind": "queued", "durable_id": f"refresh:{key}"}
    result = {"outcome": "artifact_ignored", "memory_ids": []}
    if not ledger.mark_claimed(key, lease, "committed", result, receipt):
        raise _Lost()
    return "committed", result, receipt


def _fail(
    ledger: Ledger, row: Any, lease: str, outcome: str
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    result = {"outcome": outcome, "memory_ids": []}
    receipt = json.loads(row["receipt"]) if row["receipt"] else None
    if not ledger.mark_claimed(str(row["key"]), lease, "failed", result, receipt):
        raise _Lost()
    return "failed", result, receipt


def _too_large_or_binary(path: Path) -> bool:
    try:
        info = path.stat()
    except OSError:
        return False
    if info.st_size > 2 * 1024 * 1024:
        return True
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(8192)
    except OSError:
        return False


async def _track(pipeline: Any, binding: Any, path: Path) -> None:
    from agentic_inquiry.watching.file_tracker import FileTracker

    tracker = await FileTracker.from_config(
        pipeline.config, project_id=binding.storage_project_id
    )
    try:
        await tracker.update_hash(str(path))
    finally:
        close = getattr(tracker, "close", None)
        if close is not None:
            await close()


async def _open_runtime(binding: Any) -> tuple[Any, Any, Any]:
    from agentic_inquiry.cli.env_resolver import load_config_for_environment
    from agentic_inquiry.cli.memory import create_memory_system
    from agentic_inquiry.indexing.pipeline import IndexingPipeline

    config = load_config_for_environment(
        binding.config_path, Path(binding.project_root)
    )
    _configure_embedder(config)
    memory, storage = await create_memory_system(config, binding.storage_project_id)
    pipeline = IndexingPipeline(
        storage,
        config,
        binding.storage_project_id,
        project_root=binding.project_root,
        auto_watch=False,
    )
    return memory, storage, pipeline


async def _invalidate(storage: Any, binding: Any) -> None:
    manager = (
        storage.get_db_manager()
        if storage is not None and hasattr(storage, "get_db_manager")
        else None
    )
    if manager is None or not hasattr(manager, "invalidate_table_cache"):
        return
    from agentic_inquiry.cli.env_resolver import load_config_for_environment

    config = load_config_for_environment(
        binding.config_path, Path(binding.project_root)
    )
    for name in (
        config.memory.episodic_memory.table_name,
        config.memory.semantic_memory.table_name,
    ):
        await manager.invalidate_table_cache(name)


async def _by_task(memory: Any, key: str) -> list[Any]:
    found: list[Any] = []
    for layer in (memory.episodic_memory, memory.semantic_memory):
        adapter = getattr(layer, "_storage", None)
        if adapter is not None and hasattr(adapter, "query"):
            found.extend(await adapter.query({"task_id": key}, limit=100))
    return found


async def _drop_if_purged(
    ledger: Ledger, memory: Any, key: str, ids: list[str]
) -> None:
    row = ledger.get_event(key)
    if row is not None and row["state"] != "purged":
        return
    for memory_id in ids:
        await memory.delete(memory_id)


def _existing_ids(row: Any) -> list[str]:
    if not row["result"]:
        return []
    try:
        parsed = json.loads(row["result"])
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed.get("memory_ids") or []]


def _stored_result(row: Any) -> dict[str, Any] | None:
    if not row["result"]:
        return None
    try:
        parsed = json.loads(row["result"])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {
        "outcome": str(parsed.get("outcome") or "skipped"),
        "memory_ids": list(parsed.get("memory_ids") or []),
    }


def _row_view(
    row: Any,
    result: dict[str, Any],
    *,
    state: str | None = None,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del receipt
    kind = str(row["kind"])
    return {
        "durable_id": f"{kind}:{row['key']}",
        "kind": kind,
        "state": state or str(row["state"]),
        "attempts": int(row["attempts"]),
        "resets": int(row["resets"]) if "resets" in row.keys() else 0,
        "result": {
            "outcome": result.get("outcome", "skipped"),
            "memory_ids": list(result.get("memory_ids") or []),
        },
    }


def _zeros() -> dict[str, Any]:
    return {
        "committed": 0,
        "failed": 0,
        "skipped": 0,
        "exhausted": 0,
        "lost": 0,
        "remaining": 0,
        "rows": [],
    }


class _Lost(Exception):
    """The lease was no longer ours."""
