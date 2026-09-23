"""``ai integration`` — parse arguments and print. The work lives in ``integration``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from agentic_inquiry.integration.contract import SCHEMA_VERSION
from agentic_inquiry.integration.state import StateError


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "hook":
        return _hook(args[1:])
    parser = _parser()
    try:
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return 1 if code is None else int(code)
    try:
        code = _dispatch(parsed)
    except StateError as exc:
        _emit_error(exc, verb=parsed.verb)
        code = 1
    except Exception as exc:
        _emit(
            {
                "schema_version": SCHEMA_VERSION,
                "ok": False,
                "errors": [{"code": "internal_error", "message": type(exc).__name__}],
            }
        )
        code = 2
    sys.stdout.flush()
    sys.stderr.flush()
    # Lance and the file watcher leave non-daemon threads behind. A normal
    # interpreter shutdown waits for them, so the CLI would not return.
    os._exit(code)


def _hook(argv: list[str]) -> int:
    from agentic_inquiry.integration.contract import empty_context, error_object, new_response
    from agentic_inquiry.integration.hooks import emit, hook, parse_hook_argv
    from agentic_inquiry.integration.contract import bound_response

    client, event, code = parse_hook_argv(argv)
    if code is not None:
        response = new_response()
        response["status"] = "unsupported"
        response["context"] = empty_context(0)
        response["errors"] = [error_object(code, code, notify=True)]
        bound_response(response)
        sys.stdout.write(emit(response))
        return 1
    assert client is not None and event is not None
    raw = sys.stdin.buffer.read(1_048_577)
    response, status = hook(client, event, raw)
    sys.stdout.write(emit(response))
    return status


def _dispatch(parsed: argparse.Namespace) -> int:
    root = _root(parsed.project_root)
    if parsed.verb == "enable":
        from agentic_inquiry.integration.verbs import enable

        result = enable(
            root,
            client=parsed.client,
            owner=parsed.owner,
            recall=not parsed.no_recall,
            capture=not parsed.no_capture,
            refresh=not parsed.no_refresh,
            context_budget=parsed.context_budget,
        )
        if parsed.json:
            _emit({"schema_version": SCHEMA_VERSION, "ok": True, **result})
        else:
            for line in result["gitignore"]:
                print(line)
        return 0
    if parsed.verb == "disable":
        from agentic_inquiry.integration.verbs import disable

        result = disable(root, client=parsed.client, owner=parsed.owner)
        if parsed.json:
            _emit({"schema_version": SCHEMA_VERSION, "ok": True, **result})
        else:
            print(result.get("hint") or "ai integration purge")
        return 0
    if parsed.verb == "status":
        from agentic_inquiry.integration.verbs import status

        _emit({"schema_version": SCHEMA_VERSION, "ok": True, **status(root)})
        return 0
    if parsed.verb == "reconcile":
        from agentic_inquiry.integration.reconcile import reconcile

        report = asyncio.run(
            reconcile(root, retry=parsed.retry, lock_timeout=parsed.lock_wait, force=parsed.force)
        )
        _emit({"schema_version": SCHEMA_VERSION, "ok": True, **report})
        return 1 if report["failed"] else 0
    if parsed.verb == "purge":
        from agentic_inquiry.integration.verbs import confirmation_prompt, purge

        answer = None
        if not parsed.yes:
            prompt = confirmation_prompt(root)
            if parsed.json:
                sys.stderr.write(prompt)
            else:
                sys.stdout.write(prompt)
            answer = sys.stdin.readline()
            if answer.endswith("\n"):
                answer = answer[:-1]
        result = purge(root, yes=parsed.yes, wait=parsed.wait, answer=answer)
        _emit({"schema_version": SCHEMA_VERSION, "ok": True, **result})
        return 0
    return 1


def _emit_error(exc: StateError, *, verb: str) -> None:
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "errors": [{"code": exc.code, "message": exc.message}],
    }
    if verb == "reconcile":
        body.update(
            {
                "committed": 0,
                "failed": 0,
                "skipped": 0,
                "exhausted": 0,
                "lost": 0,
                "remaining": 0,
                "rows": [],
            }
        )
    _emit(body)


def _emit(body: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(body, separators=(",", ":"), ensure_ascii=False))
    sys.stdout.write("\n")


def _root(value: str | None) -> str:
    path = Path(value) if value else Path.cwd()
    return str(path.resolve()) if path.exists() else str(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai integration")
    sub = parser.add_subparsers(dest="verb", required=True)

    enable = sub.add_parser("enable")
    _common(enable, owner=True)
    enable.add_argument("--no-capture", action="store_true")
    enable.add_argument("--no-refresh", action="store_true")
    enable.add_argument("--no-recall", action="store_true")
    enable.add_argument("--context-budget", type=int, default=2048)

    disable = sub.add_parser("disable")
    _common(disable, owner=True)

    status = sub.add_parser("status")
    _common(status, owner=False)

    reconcile = sub.add_parser("reconcile")
    _common(reconcile, owner=False)
    reconcile.add_argument("--retry", default=None)
    reconcile.add_argument("--force", action="store_true")
    reconcile.add_argument("--lock-wait", type=float, default=30.0)

    purge = sub.add_parser("purge")
    _common(purge, owner=False)
    purge.add_argument("--yes", action="store_true")
    purge.add_argument("--wait", type=float, default=0.0)
    return parser


def _common(parser: argparse.ArgumentParser, *, owner: bool) -> None:
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--json", action="store_true")
    if owner:
        parser.add_argument("--client", required=True)
        parser.add_argument("--owner", required=True)
