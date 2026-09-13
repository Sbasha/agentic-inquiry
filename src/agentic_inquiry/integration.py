"""Versioned local lifecycle events, explicit ownership and durable refresh queues."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from .library import Library

EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PostToolUse",
    "TaskCompleted",
    "PreCompact",
    "Stop",
    "SessionEnd",
)
CLIENT_EVENTS = {
    "codex": tuple(e for e in EVENTS if e != "TaskCompleted"),
    "pi": tuple(e for e in EVENTS if e != "TaskCompleted"),
}
DDL = (
    "CREATE TABLE IF NOT EXISTS integration_config(project TEXT,client TEXT,owner TEXT,root TEXT,enabled INTEGER,policy TEXT,PRIMARY KEY(project,client))",
    "CREATE TABLE IF NOT EXISTS refresh_events(project TEXT,event_id TEXT,payload TEXT,state TEXT,result TEXT,PRIMARY KEY(project,event_id))",
)


def capabilities() -> dict:
    from .ingestion import capabilities as ingestion_capabilities

    return {
        "schema_version": 1,
        "product": "Agentic Inquiry",
        "version": importlib.metadata.version("agentic-inquiry"),
        "contract_versions": {"cli": 1, "mcp": 1, "hook": 1},
        "hook_schema_version": 1,
        "runtime": {
            "collection": True,
            "index": True,
            "search": True,
            "context": True,
            "symbols": True,
            "relations": True,
            "memory": True,
            "knowledge": True,
            "capture": True,
            "backup": True,
            "evaluation_recording": True,
        },
        "clients": {
            client: {
                "supported_events": list(events),
                "unsupported_events": [e for e in EVENTS if e not in events],
                "activation": "explicit per-project and client owner",
                "native_observed": False,
            }
            for client, events in CLIENT_EVENTS.items()
        },
        "ingestion": ingestion_capabilities(),
        "generative_model_calls": False,
        "capture_default": "inert",
        "max_hook_input_bytes": 1048576,
    }


def _initialize(lib: Library) -> None:
    with lib.writer() as conn:
        for sql in DDL:
            conn.execute(sql)


def selected_library(project_root: Path, client: str, explicit: Path | None = None) -> Path:
    """One runtime-owned locator per project/client; policies remain in SQLite."""
    from .library import reject_symlinks

    root = Path(project_root).resolve()
    selector = root / ".agentic-inquiry" / "clients.json"
    reject_symlinks(selector)
    binding = None
    if selector.exists():
        if selector.stat().st_size > 16384:
            raise ValueError("Client library selection is oversized")
        document = json.loads(selector.read_text())
        if document.get("schema_version") != 1 or document.get("project_root") != str(root):
            raise ValueError("Invalid client library selection")
        binding = document.get("clients", {}).get(client)
        if binding and (not Path(binding).is_absolute() or str(Path(binding).resolve()) != binding):
            raise ValueError("Selected library path must be canonical and absolute")
    if explicit is not None:
        return Path(explicit).resolve()
    return Path(binding) if binding else root / ".agentic-inquiry"


@contextmanager
def _binding(project_root: Path, client: str, library: Path):
    from filelock import FileLock

    from .library import atomic_write, reject_symlinks

    root = project_root.resolve()
    directory = root / ".agentic-inquiry"
    reject_symlinks(directory)
    directory.mkdir(exist_ok=True, mode=0o700)
    selector = directory / "clients.json"
    reject_symlinks(selector)
    with FileLock(directory / "selection.lock", timeout=1):
        document = (
            json.loads(selector.read_text())
            if selector.exists()
            else {"schema_version": 1, "project_root": str(root), "clients": {}}
        )
        if document.get("schema_version") != 1 or document.get("project_root") != str(root):
            raise ValueError("Invalid client library selection")
        previous = document["clients"].get(client)
        if previous and Path(previous) != library and (Path(previous) / "records.sqlite3").exists():
            with Library(Path(previous)).connection() as conn:
                if (
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='integration_config'"
                    ).fetchone()
                    and conn.execute(
                        "SELECT 1 FROM integration_config WHERE client=? AND root=? AND enabled=1",
                        (client, str(root)),
                    ).fetchone()
                ):
                    raise ValueError(
                        "Disable the current selected library integration before selecting another"
                    )
        yield
        document["clients"][client] = str(library)
        atomic_write(selector, json.dumps(document, indent=2).encode())


def configure(
    db_path: Path,
    *,
    project_root: str,
    client: str,
    owner: str,
    enabled: bool = True,
    recall: bool = True,
    capture: bool = True,
    refresh: bool = True,
) -> dict:
    if client not in CLIENT_EVENTS or owner not in {"afp", "standalone"}:
        raise ValueError("Select codex/pi and owner afp/standalone")
    if any(type(v) is not bool for v in (enabled, recall, capture, refresh)):
        raise ValueError("Integration policy values must be booleans")
    lib = Library(db_path)
    root = Path(project_root).resolve(strict=True)
    collection = next(
        (c for c in lib.collections() if c["root"] == str(root) and c["state"] == "active"), None
    )
    if not collection:
        raise ValueError("Register project_root before enabling integration")
    _initialize(lib)
    project = collection["project_id"]
    with _binding(root, client, lib.path):
        with lib.writer() as conn:
            previous = conn.execute(
                "SELECT * FROM integration_config WHERE project=? AND client=?", (project, client)
            ).fetchone()
            if previous and previous["enabled"] and previous["owner"] != owner:
                raise ValueError(
                    "Another owner has enabled this client's integration; disable it first"
                )
            if previous and not enabled and previous["owner"] != owner:
                raise ValueError("Only the owning integration can disable its configuration")
            conn.execute(
                "INSERT OR REPLACE INTO integration_config VALUES(?,?,?,?,?,?)",
                (
                    project,
                    client,
                    owner,
                    str(root),
                    int(enabled),
                    json.dumps({"recall": recall, "capture": capture, "refresh": refresh}),
                ),
            )
        from .knowledge import dispatch

        if enabled and capture:
            dispatch(lib.path, "capture.enable", {"project": project})
    return {
        "schema_version": 1,
        "project": project,
        "client": client,
        "owner": owner,
        "enabled": enabled,
        "policy": {"recall": recall, "capture": capture, "refresh": refresh},
    }


def hook(db_path: Path | None, client: str, event: str, payload: dict) -> dict:
    response = {
        "schema_version": 1,
        "status": "inert",
        "context": {
            "text": "",
            "entries": [],
            "used": 0,
            "budget": 2048,
            "omitted": [],
            "accounting": "UTF-8 bytes as conservative token upper bound",
        },
        "receipts": [],
        "pending": [],
        "errors": [],
    }
    if client not in CLIENT_EVENTS or event not in CLIENT_EVENTS[client]:
        return response | {
            "status": "unsupported",
            "errors": [{"code": "unsupported_event", "event": event, "client": client}],
        }
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported hook schema_version")
    allowed = {
        "schema_version",
        "project_root",
        "session_id",
        "event_id",
        "owner",
        "query",
        "observations",
        "artifacts",
    }
    if set(payload) - allowed:
        raise ValueError(
            "Hook payload has unadmitted fields; transcripts and tool output are not accepted"
        )
    raw = payload.get("project_root")
    if not isinstance(raw, str) or not Path(raw).is_absolute() or str(Path(raw).resolve()) != raw:
        raise ValueError("project_root must be a canonical absolute path")
    session = payload.get("session_id")
    if not isinstance(session, str) or not session.strip() or len(session) > 300:
        raise ValueError("session_id must be nonempty and bounded")
    owner = payload.get("owner")
    if owner not in {"afp", "standalone"}:
        raise ValueError("Hook owner must be afp or standalone")
    path = selected_library(Path(raw), client, db_path)
    if not (path / "records.sqlite3").exists():
        return response
    lib = Library(path)
    collection = next(
        (c for c in lib.collections() if c["root"] == raw and c["state"] == "active"), None
    )
    if not collection:
        return response | {"errors": [{"code": "project_not_registered"}]}
    with lib.connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='integration_config'"
        ).fetchone():
            return response
    project = collection["project_id"]
    with lib.connection() as conn:
        conf = conn.execute(
            "SELECT * FROM integration_config WHERE project=? AND client=?", (project, client)
        ).fetchone()
    if not conf or not conf["enabled"]:
        return response
    if selected_library(Path(raw), client) != lib.path:
        raise ValueError("The enabled native integration belongs to a different selected library")
    if conf["owner"] != owner:
        raise ValueError("Hook owner conflicts with the explicitly enabled integration")
    policy = json.loads(conf["policy"])
    observations = payload.get("observations", [])
    artifacts = payload.get("artifacts", [])
    event_id = payload.get("event_id")
    if observations or artifacts:
        if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 300:
            raise ValueError(
                "Mutating hook requires a stable native event_id; use explicit capture fallback"
            )
        event_id = hashlib.sha256(
            json.dumps([owner, client, session, event, event_id]).encode()
        ).hexdigest()
    from .knowledge import dispatch

    if observations:
        if not policy["capture"]:
            response["errors"].append({"code": "capture_disabled"})
        else:
            result = dispatch(
                lib.path,
                "capture.submit",
                {"project": project, "event_id": event_id, "observations": observations},
            )
            if result["state"] == "committed":
                response["receipts"].append(
                    {
                        "kind": "remembered",
                        "durable_id": f"capture:{project}:{event_id}",
                        "event_id": event_id,
                        "durable": True,
                        **result,
                    }
                )
            else:
                response["pending"].append(result)
    if artifacts:
        if not policy["refresh"]:
            response["errors"].append({"code": "refresh_disabled"})
        else:
            if not isinstance(artifacts, list) or len(artifacts) > 100:
                raise ValueError("artifacts must contain at most 100 paths")
            for artifact in artifacts:
                if not isinstance(artifact, str):
                    raise TypeError("Artifacts must be local paths, never contents")
                path = Path(artifact)
                if not path.is_absolute():
                    path = Path(raw) / path
                if not path.resolve().is_relative_to(raw):
                    raise ValueError("Artifact escapes enabled project_root")
            encoded = json.dumps(
                {"collection_id": collection["id"], "artifacts": artifacts}, sort_keys=True
            )
            with lib.writer() as conn:
                previous = conn.execute(
                    "SELECT * FROM refresh_events WHERE project=? AND event_id=?",
                    (project, event_id),
                ).fetchone()
                if previous and previous["payload"] != encoded:
                    raise ValueError("Refresh event ID conflicts with earlier content")
                if not previous:
                    conn.execute(
                        "INSERT INTO refresh_events VALUES(?,?,?,'pending',NULL)",
                        (project, event_id, encoded),
                    )
                state = previous["state"] if previous else "pending"
            response["receipts"].append(
                {
                    "kind": "indexed" if state == "committed" else "queued",
                    "durable_id": f"refresh:{project}:{event_id}",
                    "event_id": event_id,
                    "durable": True,
                    "state": state,
                }
            )
    if policy["recall"] and event in {"SessionStart", "UserPromptSubmit", "PreCompact"}:
        query = payload.get("query", "")
        if not isinstance(query, str) or len(query.encode()) > 16384:
            raise ValueError("query must be bounded text")
        recalled = dispatch(
            lib.path, "memory.recall", {"project": project, "query": query, "limit": 20}
        )
        for record in recalled.get("records", []):
            current = {
                key: record[key]
                for key in (
                    "id",
                    "project",
                    "scope",
                    "kind",
                    "revision",
                    "content",
                    "origin",
                    "citations",
                    "freshness",
                )
            }
            entries = response["context"]["entries"] + [{"type": "memory", "data": current}]
            text = json.dumps(entries, ensure_ascii=False)
            cost = len(text.encode())
            if cost <= response["context"]["budget"]:
                response["context"].update(entries=entries, text=text, used=cost)
            else:
                response["context"]["omitted"].append(record["id"])
    state = dispatch(lib.path, "capture.status", {"project": project})
    response["pending"].extend(e for e in state["events"] if e["state"] != "committed")
    with lib.connection() as conn:
        response["pending"].extend(
            dict(r)
            for r in conn.execute(
                "SELECT event_id,state,result FROM refresh_events WHERE project=? AND state!='committed' LIMIT 100",
                (project,),
            )
        )
    response["status"] = "partial" if response["errors"] or response["pending"] else "ok"
    return response


def reconcile(db_path: Path, project: str | None = None) -> dict:
    from . import store
    from .knowledge import dispatch

    lib = Library(db_path)
    _initialize(lib)
    with lib.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM refresh_events WHERE state!='committed' AND (? IS NULL OR project=?) LIMIT 100",
            (project, project),
        ).fetchall()
    results = []
    for row in rows:
        payload = json.loads(row["payload"])
        report = store.index(None, lib.path, collection=payload["collection_id"])
        state = "committed" if report["complete"] else "failed"
        with lib.writer() as conn:
            conn.execute(
                "UPDATE refresh_events SET state=?,result=? WHERE project=? AND event_id=?",
                (state, json.dumps(report), row["project"], row["event_id"]),
            )
        results.append(
            {
                "event_id": row["event_id"],
                "state": state,
                "kind": "indexed" if state == "committed" else "queued",
            }
        )
    captures = []
    for c in lib.collections():
        if project and project != c["project_id"]:
            continue
        status = dispatch(lib.path, "capture.status", {"project": c["project_id"]})
        if status["enabled"]:
            captures.extend(
                dispatch(lib.path, "capture.retry", {"project": c["project_id"]})["results"]
            )
    return {"schema_version": 1, "refresh": results, "capture": captures}


def doctor(db_path: Path) -> dict:
    import platform

    from . import store

    result = {
        "schema_version": 1,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "executables": {name: shutil.which(name) for name in ("git", "tesseract", "codex", "pi")},
        "model": {
            "identity": store.IDENTITY,
            "cached": any(Path(db_path).glob("models/**/model*.onnx")),
            "search_downloads": False,
        },
        "capabilities": capabilities(),
    }
    if (Path(db_path) / "records.sqlite3").exists():
        result["library"] = store.status(db_path)
    return result


def watch(db_path: Path, *, interval: float = 2, debounce: float = 1, once: bool = False) -> dict:
    import signal

    from . import store
    from .library import atomic_write

    if not 0.1 <= interval <= 3600 or not 0 <= debounce <= 60:
        raise ValueError("Watch interval/debounce outside bounds")
    lib = Library(db_path)
    stop = False

    def halt(signum, frame):
        nonlocal stop
        stop = True

    previous = {s: signal.signal(s, halt) for s in (signal.SIGINT, signal.SIGTERM)}
    cycles = 0
    checkpoint = {"schema_version": 1, "cycles": 0, "complete": True, "reports": []}
    failed = False
    try:
        while not stop:
            reports = []
            for c in lib.collections():
                if c["state"] == "active":
                    reports.append(store.index(None, lib.path, collection=c["id"]))
            recovery = reconcile(lib.path)
            cycles += 1
            checkpoint = {
                "schema_version": 1,
                "cycles": cycles,
                "time": time.time(),
                "reports": reports,
                "recovery": recovery,
                "state": "idle",
                "complete": all(r["complete"] for r in reports)
                and all(r.get("state") == "committed" for r in recovery["refresh"])
                and all(r.get("state") == "committed" for r in recovery["capture"]),
            }
            atomic_write(lib.path / "watch-checkpoint.json", json.dumps(checkpoint).encode())
            if once:
                break
            deadline = time.monotonic() + max(interval, debounce)
            while not stop and time.monotonic() < deadline:
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    except BaseException as error:
        failed = True
        checkpoint.update(complete=False, error=type(error).__name__)
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        checkpoint.update(cycles=cycles, state="failed" if failed else "stopped", time=time.time())
        atomic_write(lib.path / "watch-checkpoint.json", json.dumps(checkpoint).encode())
    return {
        "schema_version": 1,
        "cycles": cycles,
        "state": "stopped",
        "checkpoint": str(lib.path / "watch-checkpoint.json"),
        "complete": checkpoint["complete"],
        "reports": checkpoint["reports"],
        "recovery": checkpoint.get("recovery", {}),
    }
