"""Local evidence, scoped memory and authored knowledge through the ai command."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from filelock import Timeout

from . import __version__

FAMILIES = {
    "cache": ("clean",),
    "collection": ("register", "list", "inspect", "relocate", "detach", "configure"),
    "memory": (
        "add",
        "recall",
        "inspect",
        "correct",
        "supersede",
        "retract",
        "forget",
        "export",
        "contradictions",
    ),
    "knowledge": ("write", "inspect", "validate", "stale", "export", "discard-pending"),
    "capture": ("enable", "disable", "status", "submit", "retry", "recall"),
    "integration": (
        "hook",
        "enable",
        "disable",
        "reconcile",
        "install",
        "uninstall",
        "inspect",
        "library",
    ),
    "evaluation": ("freeze", "trial", "judge", "cost", "close", "inspect", "report"),
}


def input_object(filename: str | None) -> dict:
    if filename is None:
        return {}
    if filename == "-":
        data = sys.stdin.buffer.read(1048577)
    else:
        with Path(filename).open("rb") as stream:
            data = stream.read(1048577)
    if len(data) > 1048576:
        raise ValueError("JSON input exceeds the 1 MiB limit")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise TypeError("JSON input must be an object")
    return value


def invoke(db_path: Path, action: str, payload: dict) -> dict:
    """Shared public operation dispatcher used by CLI and stdio MCP."""
    from . import integration, store
    from .library import Library, backup, restore, validate_collection_settings

    if action.startswith(("memory.", "knowledge.", "capture.")):
        from .knowledge import dispatch

        return dispatch(db_path, action, payload)
    if action.startswith("evaluation."):
        from .evaluation import dispatch

        return dispatch(action.split(".", 1)[1], payload)
    if action == "cache.clean":
        from .cache import clean

        return clean(db_path, **payload)
    if action.startswith("collection."):
        lib = Library(db_path)
        op = action.split(".", 1)[1]
        if op == "register":
            return lib.register(
                Path(payload["root"]),
                payload.get("name"),
                payload.get("project"),
                payload.get("settings"),
            )
        if op == "list":
            return {"collections": lib.collections()}
        if op == "inspect":
            return lib.collection(payload.get("collection"))
        if op == "relocate":
            return lib.relocate(payload["collection"], Path(payload["root"]))
        if op == "detach":
            return lib.detach(payload["collection"], payload.get("apply", False))
        if op == "configure":
            c = lib.collection(payload["collection"])
            settings = validate_collection_settings(payload["settings"])
            with lib.writer() as conn:
                conn.execute(
                    "UPDATE collections SET settings=? WHERE id=?", (json.dumps(settings), c["id"])
                )
            return lib.collection(c["id"])
    if action == "index":
        return store.index(
            Path(payload.pop("root")) if payload.get("root") else None, db_path, **payload
        )
    if action == "search":
        return store.search_report(db_path, **payload)
    if action == "read":
        return store.read(db_path, payload.pop("id"), **payload)
    if action == "context":
        return store.context(db_path, **payload)
    if action == "remove":
        return store.remove(db_path, **payload)
    if action == "status":
        return store.status(db_path)
    if action in {"doctor", "capabilities"}:
        return (
            integration.capabilities() if action == "capabilities" else integration.doctor(db_path)
        )
    if action in {"symbols", "entity", "relations", "impact", "lineage"}:
        from . import graph
    if action == "symbols" or action == "entity":
        return graph.symbols(db_path, **payload)
    if action == "relations":
        return graph.relations(db_path, **payload)
    if action in {"impact", "lineage"}:
        return graph.traverse(db_path, direction=action, **payload)
    if action in {"patterns", "services"}:
        return {
            "evidence": store.search_report(db_path, payload.pop("query", action), **payload),
            "interpretation": "Host-authored analysis required; evidence does not establish a pattern or runtime topology",
        }
    if action == "setup":
        if payload.get("rerank"):
            store.prepare_reranker(db_path)
        c = Library(db_path).register(
            Path(payload["root"]), payload.get("name"), payload.get("project")
        )
        return {
            "collection": c,
            "diagnostics": integration.doctor(db_path),
            "next": "Run ai index with this --db and --collection",
        }
    if action == "backup":
        return backup(db_path, Path(payload["destination"]))
    if action == "restore":
        return restore(Path(payload["source"]), db_path)
    if action == "watch":
        return integration.watch(db_path, **payload)
    if action.startswith("integration."):
        op = action.split(".", 1)[1]
        if op == "library":
            return {
                "library": str(
                    integration.selected_library(
                        Path(payload.get("root", Path.cwd())), payload["client"]
                    )
                )
            }
        if op == "hook":
            return integration.hook(
                db_path, payload["client"], payload["event"], payload["payload"]
            )
        if op in {"enable", "disable"}:
            return integration.configure(db_path, enabled=op == "enable", **payload)
        if op == "reconcile":
            return integration.reconcile(db_path, **payload)
        from .clients import dispatch

        return dispatch(db_path, op, payload)
    raise ValueError(f"Unknown operation: {action}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="ai", description=__doc__)
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    names = (
        "index",
        "search",
        "read",
        "context",
        "status",
        "remove",
        "symbols",
        "relations",
        "impact",
        "lineage",
        "doctor",
        "backup",
        "restore",
        "watch",
        "mcp",
        "capabilities",
        "setup",
        "entity",
        "patterns",
        "services",
        *FAMILIES,
    )
    for name in names:
        p = commands.add_parser(name)
        if name in FAMILIES:
            p.add_argument("operation", choices=FAMILIES[name])
        p.add_argument(
            "value", nargs="?", help="Source path, query, ID or destination for this operation"
        )
        p.add_argument(
            "--db", type=Path, help="Library directory (legacy index directories supported)"
        )
        p.add_argument("--json", action="store_true", help="Emit versioned JSON (default)")
        p.add_argument("--input", help="JSON operation fields from file or - for stdin")
        p.add_argument("--project")
        p.add_argument("--collection")
        p.add_argument("--name")
        p.add_argument("--limit", type=int)
        p.add_argument("--mode", choices=("hybrid", "lexical", "vector"))
        p.add_argument("--language")
        p.add_argument("--path", dest="path_filter")
        p.add_argument("--type", dest="kind")
        p.add_argument("--budget", type=int)
        p.add_argument("--depth", type=int)
        p.add_argument("--max-nodes", type=int)
        p.add_argument("--client", choices=("codex", "pi"))
        p.add_argument("--owner", choices=("afp", "standalone"))
        p.add_argument("--event")
        p.add_argument("--root", type=Path)
        p.add_argument("--content")
        p.add_argument("--reason")
        p.add_argument("--expected-revision", type=int)
        p.add_argument("--interval", type=float)
        p.add_argument("--debounce", type=float)
        if name == "cache":
            p.add_argument(
                "--models", action="store_true", default=None, help="Include model cache"
            )
        for flag in (
            "include-stale",
            "include-shared",
            "shared",
            "apply",
            "preview",
            "rebuild",
            "rerank",
            "once",
            "allow-write",
        ):
            p.add_argument("--" + flag, action="store_true", default=None)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    action = args.command + ("." + args.operation if args.command in FAMILIES else "")
    try:
        input_payload = input_object(args.input)
        payload = dict(input_payload)
        for key, value in vars(args).items():
            if key in {"command", "operation", "value", "db", "json", "input"} or value is None:
                continue
            payload[{"path_filter": "path"}.get(key, key)] = (
                str(value) if isinstance(value, Path) else value
            )
        if args.value is not None:
            if action in {"index", "setup", "collection.register", "collection.relocate"}:
                payload["root"] = args.value
            elif action in {
                "search",
                "context",
                "symbols",
                "relations",
                "impact",
                "lineage",
                "entity",
                "patterns",
                "services",
            }:
                payload["query"] = args.value
            elif action == "read":
                payload["id"] = args.value
            elif action in {"remove", "restore"}:
                payload["source"] = args.value
            elif action == "backup":
                payload["destination"] = args.value
            elif action.startswith("collection."):
                payload["collection"] = args.value
            elif action.startswith("memory."):
                payload[
                    "content"
                    if action == "memory.add"
                    else "query"
                    if action == "memory.recall"
                    else "memory_id"
                ] = args.value
            elif action.startswith("knowledge."):
                payload["page_id"] = args.value
            else:
                raise ValueError("Use --input for this operation's fields")
        root = Path(payload.get("root", Path.cwd())) if action in {"index", "setup"} else Path.cwd()
        db_path = args.db or root / ".agentic-inquiry"
        if action == "integration.hook":
            from .integration import hook

            event_payload = input_object("-") if args.input is None else input_payload
            result = hook(args.db, args.client, args.event, event_payload)
        elif action == "mcp":
            from .mcp_server import serve

            serve(db_path, **payload)
            return 0
        else:
            result = invoke(db_path, action, payload)
        result = {"schema_version": 1, **result}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return (
            1
            if result.get("complete") is False
            or result.get("status") in {"partial", "unsupported"}
            or result.get("state") == "failed"
            else 2
            if result.get("status") == "error"
            else 0
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        ImportError,
        TypeError,
        KeyError,
        sqlite3.Error,
        Timeout,
    ) as error:
        failure = {
            "schema_version": 1,
            "status": "error",
            "error": str(error),
            "type": type(error).__name__,
        }
        if action == "integration.hook":
            failure.update(
                context={
                    "text": "",
                    "entries": [],
                    "used": 0,
                    "budget": 2048,
                    "omitted": [],
                    "accounting": "UTF-8 bytes as conservative token upper bound",
                },
                receipts=[],
                pending=[],
                errors=[{"code": type(error).__name__, "message": str(error)}],
            )
        print(json.dumps(failure), file=sys.stdout if action == "integration.hook" else sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
