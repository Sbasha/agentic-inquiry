"""Prompt recall that does not load an embedding model.

Lexical matches over ledger captures are always available. Hybrid search is a
client of the already-warm loopback service. This module does not start that
service and does not import the store.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_inquiry.integration.contract import durable_id, prepare_body

_TOKEN = re.compile(r"[A-Za-z0-9_]{3,}")
_LOOPBACK = "127.0.0.1"
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "are",
        "was",
        "were",
        "has",
        "have",
        "not",
        "but",
        "you",
        "your",
        "how",
        "what",
        "which",
        "does",
        "did",
        "can",
        "its",
        "into",
        "over",
        "than",
        "then",
        "them",
        "they",
        "who",
        "why",
        "when",
        "where",
        "will",
        "just",
        "also",
        "about",
        "after",
        "before",
    }
)


@dataclass
class Item:
    """One ranked candidate. ``created`` is the sort key, newest last-wins."""

    id: str
    text: str
    created: str
    kind: str
    score: float = 0.0
    subject: str | None = None
    entry: dict[str, Any] = field(default_factory=dict)


def has_question(query: str) -> bool:
    """True when the prompt has a content token worth retrieving."""
    return bool(query_tokens(query))


def query_tokens(query: str) -> list[str]:
    seen: list[str] = []
    for token in _TOKEN.findall(query):
        folded = token.casefold()
        if folded in _STOP or folded in seen:
            continue
        seen.append(folded)
    return seen


def token_overlap(text: str, needles: list[str]) -> int:
    if not needles:
        return 0
    folded = text.casefold()
    return sum(1 for needle in needles if needle in folded)


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def source_unit(item: Item) -> str:
    """Identity of the chunk. A second copy of the same unit is not injected."""
    if item.kind == "evidence":
        data = item.entry.get("data") if isinstance(item.entry, dict) else None
        fields = data if isinstance(data, dict) else {}
        path = str(fields.get("file_path") or "")
        start = fields.get("start_line")
        end = fields.get("end_line")
        if path and isinstance(start, int) and not isinstance(start, bool):
            end_line = (
                end if isinstance(end, int) and not isinstance(end, bool) else start
            )
            return f"evidence:{path}:{start}:{end_line}"
        digest = hashlib.sha256(_normalized(item.text).encode("utf-8")).hexdigest()[:16]
        return f"evidence:{path}:{digest}" if path else f"evidence:{digest}"
    digest = hashlib.sha256(_normalized(item.text).encode("utf-8")).hexdigest()[:16]
    return f"memory:{digest}"


def drop_superseded(items: list[Item]) -> list[Item]:
    """When two matches share a subject, keep the later one."""
    grouped: dict[str, list[Item]] = {}
    for item in items:
        if item.subject:
            grouped.setdefault(item.subject, []).append(item)
    drop: set[int] = set()
    for group in grouped.values():
        if len(group) < 2:
            continue
        winner = max(group, key=lambda item: item.created)
        for item in group:
            if item is not winner:
                drop.add(id(item))
    return [item for item in items if id(item) not in drop]


def select_items(query: str, items: list[Item], *, limit: int = 16) -> list[Item]:
    """Lexical captures plus whatever the searcher already ranked as evidence.

    The first matching capture and the first evidence hit are both kept at the
    front so one kind cannot fill the byte budget and hide the other.
    """
    needles = query_tokens(query)
    matched: list[Item] = []
    for item in items:
        if item.kind == "evidence":
            matched.append(item)
            continue
        overlap = token_overlap(item.text, needles)
        if overlap:
            item.score = float(overlap)
            matched.append(item)
    matched = drop_superseded(matched)
    memories = [item for item in matched if item.kind != "evidence"]
    evidence = [item for item in matched if item.kind == "evidence"]
    memories.sort(key=lambda item: item.created, reverse=True)
    memories.sort(key=lambda item: item.score, reverse=True)
    evidence.sort(key=lambda item: item.score, reverse=True)
    ordered: list[Item] = []
    if memories:
        ordered.append(memories[0])
    if evidence:
        ordered.append(evidence[0])
    ordered.extend(memories[1:])
    ordered.extend(evidence[1:])
    seen: set[str] = set()
    units: set[str] = set()
    unique: list[Item] = []
    for item in ordered:
        unit = source_unit(item)
        if item.id in seen or unit in units:
            continue
        seen.add(item.id)
        units.add(unit)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def items_from_turns(turns: list[dict[str, Any]]) -> list[Item]:
    """Bench and unit-test adapter. ``created`` defaults to turn order."""
    items: list[Item] = []
    for index, turn in enumerate(turns):
        if turn.get("role") == "question":
            continue
        created = str(turn.get("created") or f"{index:04d}")
        subject = turn.get("subject")
        text = str(turn.get("content") or "")
        items.append(
            Item(
                id=str(turn["id"]),
                text=text,
                created=created,
                kind="memory",
                subject=subject if isinstance(subject, str) and subject else None,
            )
        )
    return items


def items_from_captures(rows: list[Any]) -> list[Item]:
    """Ledger rows to candidates. A missing or odd payload is skipped."""
    items: list[Item] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError, KeyError):
            continue
        if not isinstance(payload, list):
            continue
        created = str(row["created_at"])
        kind = str(row["kind"])
        key = str(row["key"])
        for index, observation in enumerate(payload):
            if not isinstance(observation, dict) or "content" not in observation:
                continue
            content = str(observation["content"])
            summary = observation.get("summary")
            body = prepare_body(summary if isinstance(summary, str) else None, content)
            metadata = observation.get("metadata") or {}
            subject = metadata.get("subject") if isinstance(metadata, dict) else None
            if not isinstance(subject, str) or not subject:
                subject = None
            identifier = f"{durable_id(kind, key)}.{index}"
            sort_key = f"{created}#{index:04d}"
            data: dict[str, Any] = {
                "created": created,
                "owner": f"{row['owner']}:{row['client']}",
                "summary": body,
            }
            if subject is not None:
                data["subject"] = subject
            entry = {
                "id": identifier,
                "type": "memory",
                "owner": str(row["owner"]),
                "client": str(row["client"]),
                "created": created,
                "body": body,
                "data": data,
            }
            items.append(
                Item(
                    id=identifier,
                    text=content
                    if not isinstance(summary, str)
                    else f"{summary}\n{content}",
                    created=sort_key,
                    kind="memory",
                    subject=subject,
                    entry=entry,
                )
            )
    return items


def evidence_item(
    identifier: str,
    *,
    relative: str,
    snippet: str,
    score: float,
    extra: dict[str, Any] | None = None,
) -> Item:
    data: dict[str, Any] = {"file_path": relative, "snippet": snippet, "score": score}
    if extra:
        data.update(extra)
    entry = {
        "id": identifier,
        "type": "evidence",
        "file": relative,
        "body": snippet,
        "data": data,
    }
    return Item(
        id=identifier,
        text=snippet,
        created="",
        kind="evidence",
        score=score,
        entry=entry,
    )


def warm_search(query: str, *, timeout: float) -> list[dict[str, Any]] | None:
    """POST /api/v1/search on the running loopback server.

    ``None`` means the service did not answer. An empty list means it answered
    and found nothing. This never starts a process.
    """
    base = _server_url()
    if base is None or timeout <= 0:
        return None
    body = json.dumps({"query": query, "limit": 10}).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/api/v1/search",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    results = payload.get("results")
    if not isinstance(results, list):
        return None
    return [item for item in results if isinstance(item, dict)]


def warm_identifier(relative: str, snippet: str) -> str:
    digest = hashlib.sha256(f"{relative}\n{snippet}".encode("utf-8")).hexdigest()[:16]
    return f"warm.{digest}"


def _server_url() -> str | None:
    home = os.environ.get("INQUIRY_HOME", os.path.expanduser("~/.agentic-inquiry"))
    path = os.path.join(home, "server.pid")
    try:
        with open(path, encoding="utf-8") as handle:
            info = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(info, dict):
        return None
    pid = info.get("pid")
    port = info.get("port")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return None
    if not _alive(pid):
        return None
    return f"http://{_LOOPBACK}:{port}"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


_CACHE_NAME = "recall-cache.json"
_CACHE_LIMIT = 32


def server_marker() -> str:
    """Stable while the warm process is the same process, or while it is down."""
    url = _server_url()
    if url is None:
        return "down"
    home = os.environ.get("INQUIRY_HOME", os.path.expanduser("~/.agentic-inquiry"))
    path = os.path.join(home, "server.pid")
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        return "down"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def index_stamp(root: Path) -> str:
    """Lance manifest identity under the project store.

    ``weak`` means a directory exists whose manifests we could not name, so an
    evidence result must not be cached. ``absent`` means there is no store.
    """
    base = root / ".agentic-inquiry"
    candidates = [base / "lancedb"]
    envs = base / "envs"
    if envs.is_dir() and not envs.is_symlink():
        try:
            with os.scandir(envs) as listing:
                for entry in listing:
                    if entry.is_dir(follow_symlinks=False):
                        candidates.append(Path(entry.path) / "lancedb")
        except OSError:
            return "weak"
    parts = [_manifest_stamp(path) for path in candidates]
    if any(part == "weak" for part in parts):
        return "weak"
    if any(part.startswith("lance:") for part in parts):
        return "|".join(parts)
    return "absent"


def _manifest_stamp(path: Path) -> str:
    if path.is_symlink() or not path.is_dir():
        return "absent"
    newest = 0
    size = 0
    count = 0
    try:
        with os.scandir(path) as listing:
            tables = [entry for entry in listing if entry.is_dir(follow_symlinks=False)]
    except OSError:
        return "weak"
    for table in tables:
        if not table.name.endswith(".lance"):
            continue
        versions = Path(table.path) / "_versions"
        if versions.is_symlink() or not versions.is_dir():
            continue
        try:
            with os.scandir(versions) as listing:
                manifests = list(listing)
        except OSError:
            return "weak"
        for manifest in manifests:
            if manifest.is_symlink() or not manifest.is_file(follow_symlinks=False):
                continue
            if not manifest.name.endswith(".manifest"):
                continue
            try:
                info = manifest.stat()
            except OSError:
                return "weak"
            count += 1
            if info.st_mtime_ns >= newest:
                newest = info.st_mtime_ns
                size = info.st_size
    if count == 0:
        return "weak" if tables else "absent"
    return f"lance:{count}:{newest}:{size}"


def prompt_stamp(query: str, rows: list[Any], index: str, server: str) -> str:
    parts = [query, index, server]
    for row in rows:
        try:
            payload = row["payload"]
            key = str(row["key"])
            created = str(row["created_at"])
        except (KeyError, TypeError):
            continue
        if not isinstance(payload, str):
            payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        parts.append(f"{key}\n{created}\n{payload}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def cache_allowed(entries: list[dict[str, Any]], index: str) -> bool:
    """Evidence is cached only when the index stamp names lance manifests."""
    if any(entry.get("type") == "evidence" for entry in entries):
        return "lance:" in index and index != "weak"
    return True


def read_cache(
    home: Path, stamp: str
) -> tuple[list[dict[str, Any]], list[str], bool] | None:
    path = home / _CACHE_NAME
    try:
        if path.is_symlink() or not path.is_file():
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    rows = document.get("rows") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or row.get("stamp") != stamp:
            continue
        entries = row.get("entries")
        dropped = row.get("dropped")
        embedded = row.get("embedded_down")
        if not isinstance(entries, list) or not isinstance(dropped, list):
            return None
        if not isinstance(embedded, bool):
            return None
        if not all(isinstance(item, dict) for item in entries):
            return None
        if not all(isinstance(item, str) for item in dropped):
            return None
        return entries, dropped, embedded
    return None


def write_cache(
    home: Path,
    stamp: str,
    entries: list[dict[str, Any]],
    dropped: list[str],
    embedded_down: bool,
    *,
    index: str,
) -> None:
    if not cache_allowed(entries, index):
        return
    if home.is_symlink() or not home.is_dir():
        return
    path = home / _CACHE_NAME
    if path.is_symlink():
        return
    rows: list[dict[str, Any]] = []
    try:
        if path.is_file():
            document = json.loads(path.read_text(encoding="utf-8"))
            loaded = document.get("rows") if isinstance(document, dict) else None
            if isinstance(loaded, list):
                rows = [
                    row
                    for row in loaded
                    if isinstance(row, dict) and row.get("stamp") != stamp
                ]
    except (OSError, json.JSONDecodeError, UnicodeError):
        rows = []
    rows.insert(
        0,
        {
            "stamp": stamp,
            "entries": entries,
            "dropped": dropped,
            "embedded_down": embedded_down,
        },
    )
    payload = json.dumps({"rows": rows[:_CACHE_LIMIT]}, separators=(",", ":")).encode(
        "utf-8"
    )
    temporary = home / f".{_CACHE_NAME}.tmp"
    try:
        if temporary.is_symlink():
            return
        if temporary.exists():
            temporary.unlink()
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
    except OSError:
        return
