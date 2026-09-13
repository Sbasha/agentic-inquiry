"""Previewable project client installation with owned files and shared hook entries."""

from __future__ import annotations

import json
import re
import shlex
import sqlite3
from pathlib import Path

from filelock import FileLock

from .library import atomic_write, digest, reject_symlinks

ASSETS = Path(__file__).parent / "assets"
PRODUCT = "agentic-inquiry"


def _root(target: str | Path) -> Path:
    raw = Path(target).expanduser().absolute()
    for path in (raw, *raw.parents):
        if path.is_symlink() and not (
            str(path) in {"/tmp", "/var"}
            and str(path.resolve()) in {"/private/tmp", "/private/var"}
        ):
            raise ValueError("Client target cannot contain symlinks")
    target = raw.resolve()
    if not target.is_dir():
        raise ValueError("Client target must be an existing project directory")
    return target


def _receipt_path(client: str) -> str:
    if client == "codex":
        return ".codex/agentic-inquiry/receipt.json"
    if client == "pi":
        return ".pi/agentic-inquiry-receipt.json"
    raise ValueError("Client must be codex or pi")


def _read(target: Path, name: str) -> bytes | None:
    path = target / name
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("Invalid owned client path")
    reject_symlinks(path)
    if path.exists():
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Client configuration must be a regular file within 2 MiB")
        return path.read_bytes()
    return None


def _receipt(target: Path, client: str) -> dict | None:
    content = _read(target, _receipt_path(client))
    if content is None:
        return None
    receipt = json.loads(content)
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != 1
        or receipt.get("product") != PRODUCT
        or receipt.get("client") != client
        or receipt.get("target") != str(target)
    ):
        raise ValueError("Client ownership receipt does not match this project")
    if receipt.get("owner") != "standalone" or not isinstance(receipt.get("files"), dict):
        raise ValueError("Invalid standalone client ownership receipt")
    for name, expected in receipt["files"].items():
        if (
            not isinstance(name, str)
            or not isinstance(expected, str)
            or not re.fullmatch(r"[a-f0-9]{64}", expected)
        ):
            raise ValueError("Invalid client receipt file identity")
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Client receipt file escapes the project")
        allowed = (
            (
                name.startswith(".agents/skills/ai/")
                or name == ".codex/agentic-inquiry/codex-hook.py"
                or name
                in {
                    f".codex/agents/ai-{role}.toml"
                    for role in ("explorer", "command-guide", "setup-helper")
                }
            )
            if client == "codex"
            else name
            in {
                ".pi/extensions/agentic-inquiry/index.ts",
                ".pi/extensions/agentic-inquiry/settings.json",
            }
        )
        if not allowed:
            raise ValueError("Client receipt claims an unowned path")
    hooks = receipt.get("hooks", {})
    if not isinstance(hooks, dict):
        raise TypeError("Invalid owned hook receipt")
    for event, blocks in hooks.items():
        if client != "codex" or event not in {
            "SessionStart",
            "UserPromptSubmit",
            "PostToolUse",
            "PreCompact",
            "Stop",
            "SessionEnd",
        }:
            raise ValueError("Receipt claims an unsupported client hook")
        if not isinstance(blocks, list) or len(blocks) != 1 or not isinstance(blocks[0], dict):
            raise ValueError("Invalid owned hook block")
        handlers = blocks[0].get("hooks")
        if (
            not isinstance(handlers, list)
            or len(handlers) != 1
            or not isinstance(handlers[0], dict)
        ):
            raise ValueError("Invalid owned hook handler")
        handler = handlers[0]
        argv = shlex.split(handler.get("command", ""))
        if (
            handler.get("type") != "command"
            or len(argv) not in {4, 6}
            or argv[:4]
            != ["python3", str(target / ".codex/agentic-inquiry/codex-hook.py"), "--event", event]
            or (len(argv) == 6 and argv[4] != "--db")
        ):
            raise ValueError("Receipt claims an unowned hook command")
    return receipt


def _owner_conflict(db_path: Path, target: Path, client: str) -> bool:
    database = Path(db_path) / "records.sqlite3"
    if not database.exists():
        return False
    reject_symlinks(database.absolute())
    with sqlite3.connect(database.absolute().as_uri() + "?mode=ro", uri=True) as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='integration_config'"
        ).fetchone():
            return False
        return bool(
            connection.execute(
                "SELECT 1 FROM integration_config WHERE root=? AND client=? AND enabled=1 AND owner!='standalone'",
                (str(target), client),
            ).fetchone()
        )


def _layout(target: Path, client: str) -> tuple[dict[str, bytes], dict]:
    files = {}
    entries = {}
    if client == "codex":
        source = ASSETS / "codex" / PRODUCT
        for path in sorted((source / "skills" / "ai").rglob("*")):
            if path.is_file():
                files[
                    ".agents/skills/ai/" + path.relative_to(source / "skills" / "ai").as_posix()
                ] = path.read_bytes()
        for path in sorted((source / "agents").glob("*.toml")):
            files[".codex/agents/" + path.name] = path.read_bytes()
        script = ".codex/agentic-inquiry/codex-hook.py"
        files[script] = (source / "scripts" / "codex-hook.py").read_bytes()
        template = json.loads((source / "hooks" / "hooks.json").read_text())
        for event, blocks in template["hooks"].items():
            entries[event] = blocks
            for block in blocks:
                for handler in block["hooks"]:
                    handler["command"] = shlex.join(
                        ["python3", str(target / script), "--event", event]
                    )
    elif client == "pi":
        files[".pi/extensions/agentic-inquiry/index.ts"] = (ASSETS / "pi" / "index.ts").read_bytes()
    else:
        raise ValueError("Client must be codex or pi")
    return files, entries


def _encoded(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def _hooks(
    target: Path, previous: dict, desired: dict, preserve_empty: bool = False
) -> tuple[bytes | None, list[str]]:
    original = _read(target, ".codex/hooks.json")
    config = json.loads(original) if original is not None else {}
    if not isinstance(config, dict) or not isinstance(config.get("hooks", {}), dict):
        raise TypeError("Codex hooks.json must contain a hooks object")
    hooks = config.setdefault("hooks", {})
    conflicts = []
    for event, blocks in previous.items():
        current = hooks.get(event, [])
        if not isinstance(current, list):
            raise TypeError("Codex hook event must contain a list")
        for block in blocks:
            if block not in current:
                conflicts.append(f"modified or missing owned {event} hook")
            else:
                current.remove(block)
        if not current:
            hooks.pop(event, None)
    for event, blocks in desired.items():
        current = hooks.setdefault(event, [])
        if not isinstance(current, list):
            raise TypeError("Codex hook event must contain a list")
        for block in current:
            if "agentic-inquiry/codex-hook.py" in json.dumps(block):
                conflicts.append(f"unowned {event} hook collision")
        current.extend(blocks)
    if not hooks:
        config.pop("hooks", None)
    return (_encoded(config) if config or preserve_empty else None), conflicts


def _pi_collisions(target: Path, receipt: dict | None) -> list[str]:
    conflicts = []
    directory = target / ".pi" / "extensions"
    if directory.is_symlink():
        raise ValueError("Pi extensions directory cannot be a symlink")
    if not directory.exists():
        return conflicts
    examined = 0
    owned = set(receipt["files"]) if receipt else set()
    for path in directory.rglob("*"):
        examined += 1
        if examined > 10_000:
            raise ValueError("Pi extension collision scan exceeds its 10000-file bound")
        if path.is_symlink():
            conflicts.append(
                f"extension symlink requires manual inspection: {path.relative_to(target)}"
            )
        elif path.is_file() and path.suffix in {".ts", ".js", ".mjs"}:
            name = path.relative_to(target).as_posix()
            if name in owned or name == ".pi/extensions/agentic-inquiry/index.ts":
                continue
            content = _read(target, name).decode("utf-8")
            if re.search(
                r"registerCommand\s*\(\s*['\"]ai['\"]|name\s*:\s*['\"]ai_remember['\"]", content
            ):
                conflicts.append(f"Pi command/tool name collision: {name}")
    return conflicts


def _plan(
    db_path: Path, target: Path, client: str, uninstall: bool
) -> tuple[dict, dict[str, bytes | None], dict | None]:
    receipt = _receipt(target, client)
    files, entries = _layout(target, client)
    changes = {}
    conflicts = []
    if not uninstall and _owner_conflict(db_path, target, client):
        conflicts.append("another enabled integration owns this project's client")
    if uninstall and receipt is None:
        return {"installed": False, "changes": [], "conflicts": []}, {}, None
    owned = receipt["files"] if receipt else {}
    if not uninstall and receipt is None:
        namespace = ".agents/skills/ai" if client == "codex" else ".pi/extensions/agentic-inquiry"
        existing_namespace = target / namespace
        if existing_namespace.exists() and (
            not existing_namespace.is_dir()
            or any(path.is_file() or path.is_symlink() for path in existing_namespace.rglob("*"))
        ):
            conflicts.append(f"unowned client namespace collision: {namespace}")
    selected = owned if uninstall else dict.fromkeys([*owned, *files])
    for name in selected:
        current = _read(target, name)
        expected = owned.get(name)
        if current is not None and expected is None:
            conflicts.append(f"unowned file collision: {name}")
        elif current is not None and digest(current) != expected:
            conflicts.append(f"owned file has manual changes: {name}")
        replacement = None if uninstall else files.get(name)
        if current != replacement:
            changes[name] = replacement
    if client == "codex":
        replacement, hook_conflicts = _hooks(
            target,
            receipt.get("hooks", {}) if receipt else {},
            {} if uninstall else entries,
            bool(receipt and receipt.get("hooks_file_existed")),
        )
        conflicts.extend(hook_conflicts)
        original = _read(target, ".codex/hooks.json")
        if replacement != original:
            changes[".codex/hooks.json"] = replacement
    elif not uninstall:
        conflicts.extend(_pi_collisions(target, receipt))
    next_receipt = (
        None
        if uninstall
        else {
            "schema_version": 1,
            "product": PRODUCT,
            "owner": "standalone",
            "client": client,
            "target": str(target),
            "db": str(db_path),
            "files": {name: digest(content) for name, content in files.items()},
            "hooks": entries,
            "hooks_file_existed": receipt.get("hooks_file_existed", False)
            if receipt
            else _read(target, ".codex/hooks.json") is not None
            if client == "codex"
            else False,
        }
    )
    receipt_bytes = _encoded(next_receipt) if next_receipt else None
    if _read(target, _receipt_path(client)) != receipt_bytes:
        changes[_receipt_path(client)] = receipt_bytes
    report = {
        "installed": receipt is not None,
        "changes": [
            {
                "path": name,
                "operation": "remove" if data is None else "write",
                "sha256": digest(data) if data is not None else None,
            }
            for name, data in changes.items()
        ],
        "conflicts": conflicts,
    }
    return report, changes, next_receipt


def _apply(target: Path, changes: dict[str, bytes | None]) -> None:
    originals = {name: _read(target, name) for name in changes}
    applied = []
    try:
        for name, replacement in changes.items():
            if _read(target, name) != originals[name]:
                raise ValueError("Client file changed after preview; rerun installation")
            if replacement is None:
                (target / name).unlink(missing_ok=True)
            else:
                atomic_write(target / name, replacement)
            applied.append(name)
    except BaseException:
        for name in reversed(applied):
            # Never replace a concurrent edit while rolling back installation.
            if _read(target, name) == changes[name]:
                if originals[name] is None:
                    (target / name).unlink(missing_ok=True)
                else:
                    atomic_write(target / name, originals[name])
        raise


def install(db_path: Path, client: str, target: str | Path, apply: bool = False) -> dict:
    return _manage(db_path, client, target, apply, uninstall=False)


def uninstall(db_path: Path, client: str, target: str | Path, apply: bool = False) -> dict:
    return _manage(db_path, client, target, apply, uninstall=True)


def _manage(db_path: Path, client: str, target: str | Path, apply: bool, uninstall: bool) -> dict:
    if not isinstance(apply, bool):
        raise TypeError("apply must be explicitly true or false")
    target = _root(target)
    db_path = Path(db_path).expanduser().resolve()
    report, changes, _ = _plan(db_path, target, client, uninstall)
    if apply and report["conflicts"]:
        raise ValueError("Client installation conflicts: " + "; ".join(report["conflicts"]))
    if apply and changes:
        lock = target / (
            ".codex/agentic-inquiry/install.lock"
            if client == "codex"
            else ".pi/agentic-inquiry-install.lock"
        )
        reject_symlinks(lock)
        lock.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(lock, timeout=1, mode=0o600):
            report, changes, _ = _plan(db_path, target, client, uninstall)
            if report["conflicts"]:
                raise ValueError("Client installation changed while awaiting its lock")
            _apply(target, changes)
    return {
        "schema_version": 1,
        "client": client,
        "target": str(target),
        "owner": "standalone",
        "operation": "uninstall" if uninstall else "install",
        "applied": apply,
        **report,
        "installed_after": (not uninstall) if apply else report["installed"],
        "activation": "requires explicit project integration enablement; Codex hook trust is separate",
        "native_observed": False,
        "plugin_bundle": str(ASSETS / "codex" / PRODUCT) if client == "codex" else None,
    }


def inspect(db_path: Path, client: str, target: str | Path) -> dict:
    result = install(db_path, client, target)
    return {
        **result,
        "operation": "inspect",
        "current": result["installed"] and not result["changes"] and not result["conflicts"],
    }


def dispatch(db_path: Path, action: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("Client operation payload must be an object")
    arguments = dict(payload)
    if "root" in arguments:
        if "target" in arguments:
            raise ValueError("Select target or root, not both")
        arguments["target"] = arguments.pop("root")
    actions = {"install": install, "uninstall": uninstall, "inspect": inspect}
    if action not in actions:
        raise ValueError("Client action must be install, uninstall or inspect")
    return actions[action](db_path, **arguments)
