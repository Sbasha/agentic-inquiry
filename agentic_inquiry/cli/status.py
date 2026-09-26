"""``ai status`` — project identity, integration counts and index sizes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from agentic_inquiry.integration.contract import SCHEMA_VERSION, product_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai status")
    parser.add_argument("--json", action="store_true")
    parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        root = Path.cwd().resolve()
        body: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "version": product_version(),
            "project": {"root": str(root), "id": _identity(root)},
            "integration": _integration(root),
            "index": _index(root),
        }
        code = 0
    except Exception as exc:
        from agentic_inquiry.integration.state import StateError

        if isinstance(exc, StateError):
            error = {"code": exc.code, "message": exc.message}
        else:
            error = {"code": "internal_error", "message": type(exc).__name__}
        body = {"schema_version": SCHEMA_VERSION, "ok": False, "errors": [error]}
        code = 1
    sys.stdout.write(json.dumps(body, separators=(",", ":"), ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()
    # Storage clients leave non-daemon threads that would block process exit.
    os._exit(code)


def _identity(root: Path) -> str | None:
    from agentic_inquiry.integration.state import StateError, read_identity

    try:
        return read_identity(root)
    except StateError:
        return None


def _integration(root: Path) -> dict[str, Any]:
    from agentic_inquiry.integration.verbs import status

    report = status(str(root))
    report["schema_version"] = SCHEMA_VERSION
    return report


def _index(root: Path) -> dict[str, int] | None:
    from agentic_inquiry.cli.env_resolver import resolve_environment

    resolved = resolve_environment(workspace=root)
    if resolved.config_path is None:
        return None

    async def _counts() -> dict[str, int]:
        from agentic_inquiry.cli.env_resolver import load_config_for_environment
        from agentic_inquiry.storage.facade import StorageFacade

        config = load_config_for_environment(str(resolved.config_path), root)
        raw_project_id = config.storage.default_project_id
        project_id = (
            raw_project_id
            if isinstance(raw_project_id, str) and raw_project_id
            else "default"
        )
        facade = await StorageFacade.from_config(config, project_id)
        try:
            return {
                "chunks": int(await facade.count_chunks()),
                "entities": int(await facade.count_entities(project_id=project_id)),
                "relationships": int(
                    await facade.count_relationships(project_id=project_id)
                ),
            }
        finally:
            close = getattr(facade, "close", None)
            if close is not None:
                result = close()
                if asyncio.iscoroutine(result):
                    await result

    return asyncio.run(_counts())
