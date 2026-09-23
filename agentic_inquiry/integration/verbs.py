"""Operator verbs: enable, disable, status and purge.

The hook never calls this module. It opens the environment and the memory
store, which the hot path is not allowed to import.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from agentic_inquiry.integration.contract import (
    DEFAULT_CONTEXT_BUDGET,
    MAX_CONTEXT_BUDGET,
)
from agentic_inquiry.integration.state import (
    Binding,
    Ledger,
    StateError,
    check_project_files,
    new_identity,
    project_lock,
    public_policy,
    read_identity,
    read_marker,
    update_marker_enabled,
    write_identity,
    write_marker,
)
from agentic_inquiry.mcp.utils.validation import (
    PathValidationError,
    validate_file_path,
    validate_project_id,
)

_SETTINGS_LIMIT = 1024 * 1024


def enable(
    project_root: str,
    *,
    client: str,
    owner: str,
    recall: bool = True,
    capture: bool = True,
    refresh: bool = True,
    context_budget: int = DEFAULT_CONTEXT_BUDGET,
) -> dict[str, Any]:
    """Bind one client. Writes the identity and the marker only after the checks pass."""
    root = _canonical_root(project_root)
    if not isinstance(context_budget, int) or isinstance(context_budget, bool):
        raise StateError(
            "policy_invalid", "context budget must be an integer from 0 to 16384"
        )
    if not 0 <= context_budget <= MAX_CONTEXT_BUDGET:
        raise StateError(
            "policy_invalid", "context budget must be an integer from 0 to 16384"
        )
    config_path, namespace, patterns = _onboarded_environment(root)
    _refuse_standalone_plugin(root)
    check_project_files(root)
    try:
        identity = read_identity(root)
    except StateError:
        raise
    creating = identity is None
    if identity is None:
        identity = new_identity()
    ledger = Ledger.open(identity, timeout=10, create=True, heal=True)
    try:
        ledger.sweep_tombstones()
        if ledger.any_root_mismatch(str(root)):
            raise StateError(
                "project_identity_invalid",
                "this project identity is bound to a different root",
            )
        existing = ledger.binding(client)
        if existing is not None and existing.owner != owner:
            if existing.enabled or ledger.event_count() > 0:
                raise StateError(
                    "owner_conflict",
                    "disable and purge this client before enabling a different owner",
                )
        if creating:
            write_identity(root, identity)
        policy = {
            "recall": recall,
            "capture": capture,
            "refresh": refresh,
            "context_budget": context_budget,
            "ignore_patterns": patterns,
        }
        ledger.upsert_binding(
            Binding(
                project_id=identity,
                client=client,
                owner=owner,
                enabled=True,
                project_root=str(root),
                config_path=str(config_path),
                storage_project_id=namespace,
                policy=policy,
            )
        )
        marker = read_marker(root) or {}
        clients = dict(marker.get("clients") or {})
        clients[client] = {"owner": owner, "enabled": True}
        write_marker(root, identity, clients)
    finally:
        ledger.close()
    return {
        "client": client,
        "owner": owner,
        "enabled": True,
        "gitignore": [".agentic-inquiry/*", "!.agentic-inquiry/project.toml"],
    }


def disable(project_root: str, *, client: str, owner: str) -> dict[str, Any]:
    root = _canonical_root(project_root)
    identity = _optional_identity(root)
    if identity is None:
        return {"client": client, "owner": None, "enabled": False, "changed": False}
    ledger = Ledger.open(identity, timeout=10, create=True, heal=True)
    try:
        ledger.sweep_tombstones()
        _require_same_root(ledger, root)
        binding = ledger.binding(client)
        if binding is None:
            return {"client": client, "owner": None, "enabled": False, "changed": False}
        if binding.owner != owner:
            raise StateError(
                "owner_mismatch", "disable must name the owner that enabled this client"
            )
        ledger.set_enabled(client, False)
        update_marker_enabled(root, client, owner=binding.owner, enabled=False)
    finally:
        ledger.close()
    return {
        "client": client,
        "owner": owner,
        "enabled": False,
        "changed": True,
        "hint": f"ai integration purge --project-root {root}",
    }


def status(project_root: str) -> dict[str, Any]:
    root = Path(project_root)
    if root.exists():
        root = root.resolve()
    identity = _optional_identity(root) if root.is_dir() else None
    empty_events = {
        "pending": 0,
        "committed": 0,
        "failed": 0,
        "exhausted": 0,
        "purged": 0,
    }
    if identity is None:
        return {
            "project_id": None,
            "storage_project_id": None,
            "bindings": [],
            "events": empty_events,
        }
    ledger = Ledger.open(identity, timeout=10, create=True, heal=True)
    try:
        bindings = ledger.bindings()
        namespace = bindings[0].storage_project_id if bindings else None
        return {
            "project_id": identity,
            "storage_project_id": namespace,
            "bindings": [
                {
                    "client": item.client,
                    "owner": item.owner,
                    "enabled": item.enabled,
                    "policy": public_policy(item.policy),
                }
                for item in bindings
            ],
            "events": ledger.counts(),
        }
    finally:
        ledger.close()


def purge(
    project_root: str,
    *,
    yes: bool,
    wait: float,
    answer: str | None,
    batch_size: int = 100,
) -> dict[str, Any]:
    """Erase retained records. ``answer`` is the confirmation line when ``yes`` is false."""
    root = Path(project_root)
    resolved = root.resolve() if root.exists() else root
    identity = _optional_identity(resolved) if resolved.is_dir() else None
    if identity is None:
        return {"project_root": None, "events": 0, "notifications": 0, "memories": 0}
    ledger = Ledger.open(identity, timeout=10, create=True, heal=True)
    try:
        ledger.sweep_tombstones()
        _require_same_root(ledger, resolved)
    finally:
        ledger.close()
    if not yes:
        if answer != "yes":
            raise StateError(
                "confirmation_declined", "purge proceeds only when the answer is yes"
            )
    with project_lock(identity, shared=False, timeout=wait):
        return _purge_locked(identity, resolved, batch_size=batch_size)


def _purge_locked(identity: str, root: Path, *, batch_size: int) -> dict[str, Any]:
    import asyncio

    ledger = Ledger.open(identity, timeout=10, create=True, heal=True)
    try:
        notifications = ledger.notification_count()
        ledger.null_payloads()
        rows = ledger.purged_capture_rows()
        memory_ids: list[str] = []
        keys: list[str] = []
        for row in rows:
            keys.append(str(row["key"]))
            if row["result"]:
                try:
                    parsed = json.loads(row["result"])
                except json.JSONDecodeError:
                    parsed = {}
                memory_ids.extend(
                    str(item) for item in (parsed.get("memory_ids") or [])
                )
        binding = next(iter(ledger.bindings()), None)
    finally:
        ledger.close()
    deleted = 0
    committed = [row for row in rows if row["result"]]
    if binding is not None and committed:
        try:
            deleted = asyncio.run(
                _delete_memories(binding, memory_ids, keys, batch_size=batch_size)
            )
        except StateError:
            raise
        except Exception as exc:
            raise StateError(
                "memories_failed",
                f"memory deletion failed after removing {deleted} items ({type(exc).__name__})",
            ) from exc
    ledger = Ledger.open(identity, timeout=10, create=True, heal=True)
    try:
        events = ledger.purge_rows()
    finally:
        ledger.close()
    return {
        "project_root": str(root),
        "events": events,
        "notifications": notifications,
        "memories": deleted,
    }


async def _delete_memories(
    binding: Binding,
    memory_ids: list[str],
    keys: list[str],
    *,
    batch_size: int,
) -> int:
    from agentic_inquiry.cli.env_resolver import load_config_for_environment
    from agentic_inquiry.cli.memory import create_memory_system

    config = load_config_for_environment(
        binding.config_path, Path(binding.project_root)
    )
    _configure_embedder(config)
    memory, storage = await create_memory_system(config, binding.storage_project_id)
    deleted = 0
    seen: set[str] = set()
    for memory_id in memory_ids:
        if memory_id in seen:
            continue
        seen.add(memory_id)
        removed = await memory.delete(memory_id)
        if removed:
            deleted += 1
    for key in keys:
        deleted += await _sweep_task(memory, key, batch_size=batch_size, seen=seen)
    deleted += await _sweep_concepts(memory, seen, batch_size=batch_size)
    await _compact(storage, config)
    return deleted


async def _sweep_task(memory: Any, key: str, *, batch_size: int, seen: set[str]) -> int:
    deleted = 0
    for _ in range(1000):
        found = []
        for layer in (memory.episodic_memory, memory.semantic_memory):
            storage = getattr(layer, "_storage", None)
            if storage is None or not hasattr(storage, "query"):
                continue
            found.extend(await storage.query({"task_id": key}, limit=batch_size))
        fresh = [item for item in found if getattr(item, "id", None) not in seen]
        if not fresh:
            return deleted
        for item in fresh:
            seen.add(item.id)
            removed = await memory.delete(item.id)
            if removed:
                deleted += 1
    raise StateError(
        "memories_failed",
        f"task sweep still returned rows after 1000 batches; deleted {deleted}",
    )


async def _sweep_concepts(
    memory: Any, deleted_ids: set[str], *, batch_size: int
) -> int:
    if not deleted_ids:
        return 0
    removed = 0
    storage = getattr(memory.semantic_memory, "_storage", None)
    if storage is None or not hasattr(storage, "query"):
        return 0
    for _ in range(1000):
        rows = await storage.query(
            {"content_source": "consolidation_engine"}, limit=batch_size
        )
        victims = []
        for item in rows:
            sources = (getattr(item, "metadata", None) or {}).get("source_items") or []
            if any(source in deleted_ids for source in sources):
                victims.append(item)
        if not victims:
            return removed
        progressed = False
        for item in victims:
            if await memory.delete(item.id):
                removed += 1
                progressed = True
        if not progressed:
            return removed
    raise StateError(
        "memories_failed",
        f"concept sweep exceeded 1000 batches after deleting {removed}",
    )


async def _compact(storage: Any, config: Any) -> None:
    manager = storage.get_db_manager() if hasattr(storage, "get_db_manager") else None
    if manager is None:
        return
    from datetime import timedelta

    tables = [
        config.memory.episodic_memory.table_name,
        config.memory.semantic_memory.table_name,
    ]
    compacted = await manager.compact_tables(tables)
    for name, result in compacted.items():
        if result.get("status") == "error":
            raise StateError("memories_failed", f"compaction failed for {name}")
    cleaned = await manager.cleanup_old_versions(
        tables, older_than=timedelta(0), delete_unverified=True
    )
    for name, result in cleaned.items():
        if result.get("status") == "error":
            raise StateError("memories_failed", f"version cleanup failed for {name}")


def _configure_embedder(config: Any) -> None:
    provider = getattr(config.embeddings, "default_provider", "")
    from agentic_inquiry.embeddings.registry import embedding_registry

    if embedding_registry._default_configured:
        return
    if provider == "hashing":
        from agentic_inquiry.embeddings.hashing import HashingEmbedder

        ndims = config.embeddings.hashing.ndims or config.embeddings.default_dimensions
        embedding_registry.configure_default_embedder(
            HashingEmbedder(ndims=ndims), ndims=ndims
        )
        return
    from agentic_inquiry.embeddings.factory import configure_embedder_for_backend

    configure_embedder_for_backend(config, quiet=True)


def _canonical_root(project_root: str) -> Path:
    path = Path(project_root)
    if not path.is_absolute() or str(project_root).endswith("/"):
        raise StateError(
            "project_identity_invalid", "project root must be a canonical directory"
        )
    resolved = path.resolve()
    if str(resolved) != project_root or not resolved.is_dir():
        raise StateError(
            "project_identity_invalid", "project root must be a canonical directory"
        )
    return resolved


def _optional_identity(root: Path) -> str | None:
    try:
        return read_identity(root)
    except StateError:
        raise


def _require_same_root(ledger: Ledger, root: Path) -> None:
    bindings = ledger.bindings()
    if not bindings:
        return
    stored = bindings[0].project_root
    if stored != str(root) or not Path(stored).is_dir():
        raise StateError(
            "project_identity_invalid", "project root does not match the binding"
        )


def _onboarded_environment(root: Path) -> tuple[Path, str, list[str]]:
    from agentic_inquiry.cli.env_resolver import (
        load_config_for_environment,
        resolve_environment,
    )

    resolved = resolve_environment(workspace=root)
    config_path = resolved.config_path
    if config_path is None:
        raise StateError(
            "project_not_onboarded",
            f"this project has no local environment; run ai setup local ai --workspace {root}",
        )
    path = Path(config_path).resolve()
    base = (root / ".agentic-inquiry").resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise StateError(
            "project_not_onboarded",
            f"the active environment is not local to this project; run ai setup local ai --workspace {root}",
        ) from exc
    config = load_config_for_environment(str(path), root)
    namespace = getattr(getattr(config, "storage", None), "default_project_id", None)
    if not isinstance(namespace, str) or namespace == "":
        raise StateError(
            "storage_namespace_invalid",
            "the environment has no storage.default_project_id",
        )
    try:
        validate_project_id(namespace, normalize=False)
    except Exception as exc:
        raise StateError(
            "storage_namespace_invalid",
            "storage.default_project_id is not a valid project id",
        ) from exc
    filesystem = getattr(getattr(config, "connectors", None), "filesystem", None)
    patterns = list(getattr(filesystem, "ignore_patterns", None) or [])
    return path, namespace, patterns


def _refuse_standalone_plugin(root: Path) -> None:
    path = root / ".claude" / "settings.json"
    if not path.exists() and not path.is_symlink():
        return
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise StateError(
            "settings_unreadable", "claude settings could not be read"
        ) from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise StateError(
            "settings_unreadable",
            "claude settings must be a regular file inside the project",
        )
    try:
        validate_file_path(path, root)
    except PathValidationError as exc:
        raise StateError(
            "settings_unreadable",
            "claude settings must be a regular file inside the project",
        ) from exc
    if info.st_size > _SETTINGS_LIMIT:
        raise StateError("settings_unreadable", "claude settings exceed 1 MiB")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateError("settings_unreadable", "claude settings are not JSON") from exc
    plugins = parsed.get("enabledPlugins") if isinstance(parsed, dict) else None
    if isinstance(plugins, dict) and plugins.get("ai@agentic-inquiry") is True:
        raise StateError(
            "standalone_plugin_enabled",
            "disable ai@agentic-inquiry in .claude/settings.json before enabling the AFP integration",
        )


def confirmation_prompt(project_root: str) -> str:
    return (
        f"About to purge integration records for {project_root}.\n"
        "Confirm no other writer (ai index, ai memory save, an MCP tool call, or a server) "
        "may be running against this environment.\n"
        "Type yes to continue:\n"
    )
