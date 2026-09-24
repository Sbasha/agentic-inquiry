"""Per-event hook orchestrator.

Ledger-only events import nothing beyond the standard library, sqlite3 and the
path validator. The evidence stage imports the store lazily, and only when the
deadline still has 2.5 seconds.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any, BinaryIO

from agentic_inquiry.integration.contract import (
    CLIENTS,
    EVENTS,
    MAX_HOOK_INPUT_BYTES,
    ContractError,
    apply_context,
    bound_response,
    deadline_for,
    durable_id,
    empty_context,
    error_object,
    finalize,
    ledger_key,
    matches_exclusion,
    new_response,
    parse_content,
    parse_envelope,
    payload_fingerprint,
    prepare_body,
    safe_relative,
    serialise,
)
from agentic_inquiry.integration.state import (
    Binding,
    Ledger,
    StateError,
    inquiry_home,
    marker_claims_enabled,
    read_identity,
    stored_namespace_ok,
)
from agentic_inquiry.mcp.utils.validation import PathValidationError, validate_file_path

_ALWAYS_NOTIFY = frozenset({"durable_store_absent"})
_EVIDENCE_RESERVE = 2.5
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_SNIFF_BYTES = 8192


def parse_hook_argv(argv: list[str]) -> tuple[str | None, str | None, str | None]:
    """Return ``(client, event, error_code)``.

    A missing or repeated ``--client`` is ``unsupported_client``. Any other
    malformed invocation is ``unsupported_event``. argparse never sees these
    arguments, so a hook's stderr stays empty.
    """
    client: str | None = None
    event: str | None = None
    seen_client = 0
    seen_event = 0
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--client" and index + 1 < len(argv):
            seen_client += 1
            client = argv[index + 1]
            index += 2
            continue
        if token == "--event" and index + 1 < len(argv):
            seen_event += 1
            event = argv[index + 1]
            index += 2
            continue
        if seen_client == 0:
            return None, None, "unsupported_client"
        return None, None, "unsupported_event"
    if seen_client != 1:
        return None, None, "unsupported_client"
    if seen_event != 1 or client is None or event is None:
        return None, None, "unsupported_event"
    if client not in CLIENTS:
        return client, event, "unsupported_client"
    if event not in EVENTS:
        return client, event, "unsupported_event"
    return client, event, None


def hook(
    client: str,
    event: str,
    stdin: bytes | BinaryIO,
    *,
    deadline: float | None = None,
) -> tuple[dict[str, Any], int]:
    """Answer one lifecycle event. Always returns a complete response document."""
    started = time.monotonic()
    try:
        response, code = _run(client, event, stdin, deadline=deadline, started=started)
        return response, code
    except Exception as exc:
        response = new_response()
        response["status"] = "error"
        response["errors"] = [
            error_object("internal_error", type(exc).__name__, notify=True)
        ]
        return response, 2


def _run(
    client: str,
    event: str,
    stdin: bytes | BinaryIO,
    *,
    deadline: float | None,
    started: float,
) -> tuple[dict[str, Any], int]:
    limit = (
        deadline
        if deadline is not None
        else deadline_for(event, os.environ.get("INQUIRY_HOOK_DEADLINE_SECONDS"))
    )
    response = new_response()
    refusal: ContractError | None = None
    partial = False
    ledger: Ledger | None = None
    try:
        try:
            raw = _read_limited(stdin)
            if len(raw) > MAX_HOOK_INPUT_BYTES:
                raise ContractError(
                    "payload_too_large", "request exceeds 1048576 bytes"
                )
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ContractError(
                    "invalid_payload", "request must be a JSON object"
                ) from None
            envelope = parse_envelope(parsed)
            root = Path(envelope["project_root"])
            try:
                identity = read_identity(root)
            except StateError as exc:
                raise ContractError(
                    "project_identity_invalid", "project identity is not valid"
                ) from exc
            if identity is None:
                _inert_without_identity(response, root, client, event)
                return _finish(response, refusal, partial=False)
            try:
                ledger = Ledger.open(
                    identity,
                    timeout=_remaining(limit, started),
                    create=False,
                    heal=False,
                )
            except FileNotFoundError:
                _inert_absent(response, root, client, event)
                return _finish(response, refusal, partial=False)
            except StateError as exc:
                if exc.code == "ledger_unavailable":
                    return _ledger_down(response, parsed, event, stage="binding")
                raise
            except sqlite3.OperationalError:
                return _ledger_down(response, parsed, event, stage="binding")
            if ledger.untrusted_home:
                carried = _carried(parsed)
                response["context"] = empty_context(0)
                response["errors"] = [
                    error_object(
                        "ledger_unavailable",
                        "the ledger could not be read in time",
                        notify=False,
                        stage="binding",
                    )
                ]
                response["_session_id"] = str(envelope.get("session_id") or "")
                _apply_notify(response, ledger, client)
                if carried:
                    refusal = ContractError(
                        "ledger_unavailable",
                        "the ledger could not be read in time",
                        stage="binding",
                    )
                    return _finish(response, refusal, partial=False)
                return _finish(response, None, partial=True)
            else:
                binding = _load_binding(ledger, client, envelope["project_root"])
                if binding is None:
                    response["status"] = "inert"
                    return _finish(response, refusal, partial=False)
                if binding.owner != envelope["owner"]:
                    raise ContractError(
                        "owner_conflict",
                        "this client is enabled for a different owner",
                        configured_owner=binding.owner,
                        requested_owner=envelope["owner"],
                    )
                content = parse_content(envelope)
                content["_event"] = event
            kept, ignored, missing = _confine(
                root, content.get("artifacts") or [], binding
            )
            observations = content.get("observations") or []
            if (observations or kept) and not content.get("event_id"):
                raise ContractError(
                    "event_id_required",
                    "observations and artifacts need an event_id; use ai memory save for a one-off note",
                )
            policy = binding.policy
            if observations and not policy.get("capture", False):
                raise ContractError(
                    "capture_disabled", "capture is disabled for this client"
                )
            if kept and not policy.get("refresh", False):
                raise ContractError(
                    "refresh_disabled", "refresh is disabled for this client"
                )
            redelivered = _record(
                response,
                ledger,
                binding,
                envelope,
                content,
                observations,
                kept,
                missing,
            )
            if event in {"SessionStart", "UserPromptSubmit"} and policy.get(
                "recall", False
            ):
                partial = (
                    _read_stage(
                        response,
                        ledger,
                        binding,
                        event,
                        content.get("query")
                        if isinstance(content.get("query"), str)
                        else None,
                        limit,
                        started,
                    )
                    or partial
                )
            else:
                response["context"] = empty_context(0)
            for item in ignored:
                response["errors"].append(
                    error_object(
                        "artifact_ignored",
                        "artifact was not captured",
                        notify=False,
                        path=safe_relative(item),
                    )
                )
            if not redelivered:
                for item in missing:
                    response["errors"].append(
                        error_object(
                            "artifact_ignored",
                            "artifact was not captured",
                            notify=False,
                            path=safe_relative(item),
                        )
                    )
            listed, total = ledger.pending(client)
            response["pending"] = listed
            response["pending_total"] = total
            if ledger.has_open_rows(client):
                partial = True
            if event == "SessionStart":
                exhausted = ledger.exhausted_ids(client)
                if exhausted:
                    shown = ", ".join(exhausted[:3])
                    response["errors"].append(
                        error_object(
                            "capture_exhausted",
                            (
                                f"{len(exhausted)} rows are exhausted ({shown}); "
                                "run ai integration reconcile --retry <durable_id> or purge"
                            ),
                            notify=False,
                        )
                    )
        except ContractError as exc:
            refusal = exc
            response["errors"].insert(
                0,
                error_object(exc.code, exc.message, notify=True, **exc.fields),
            )
        response["_session_id"] = (
            locals().get("envelope", {}).get("session_id", "")
            if "envelope" in locals()
            else ""
        )
        _apply_notify(response, ledger, client)
        if (
            refusal is None
            and response["status"] != "inert"
            and not partial
            and not ledger_partial(response)
        ):
            response["status"] = "ok"
        elif (
            refusal is None
            and response["status"] != "inert"
            and (partial or ledger_partial(response))
        ):
            response["status"] = "partial"
            partial = True
        bound_response(response)
        code = finalize(response, refusal, partial=partial)
        return response, code
    finally:
        if ledger is not None:
            ledger.close()


def ledger_partial(response: dict[str, Any]) -> bool:
    return any(
        item.get("code") in {"budget_exhausted", "ledger_unavailable"}
        for item in response["errors"]
    )


def _finish(
    response: dict[str, Any], refusal: ContractError | None, *, partial: bool
) -> tuple[dict[str, Any], int]:
    bound_response(response)
    return response, finalize(response, refusal, partial=partial)


def _read_limited(stdin: bytes | BinaryIO) -> bytes:
    if isinstance(stdin, (bytes, bytearray)):
        return bytes(stdin[: MAX_HOOK_INPUT_BYTES + 1])
    return stdin.read(MAX_HOOK_INPUT_BYTES + 1)


def _remaining(limit: float, started: float) -> float:
    return max(0.0, min(10.0, limit - (time.monotonic() - started)))


def _carried(parsed: object) -> bool:
    if not isinstance(parsed, dict):
        return False
    observations = parsed.get("observations")
    artifacts = parsed.get("artifacts")
    return bool(observations) or bool(artifacts)


def _inert_without_identity(
    response: dict[str, Any], root: Path, client: str, event: str
) -> None:
    response["status"] = "inert"
    response["context"] = empty_context(0)
    if event == "SessionStart" and marker_claims_enabled(root, client):
        response["errors"].append(
            error_object(
                "durable_store_absent",
                "the ledger for this project is not on this machine",
                notify=True,
            )
        )


def _inert_absent(
    response: dict[str, Any], root: Path, client: str, event: str
) -> None:
    response["status"] = "inert"
    response["context"] = empty_context(0)
    if event == "SessionStart" and marker_claims_enabled(root, client):
        response["errors"].append(
            error_object(
                "durable_store_absent",
                "the ledger for this project is not on this machine",
                notify=True,
            )
        )


def _ledger_down(
    response: dict[str, Any], parsed: object, event: str, *, stage: str
) -> tuple[dict[str, Any], int]:
    """A ledger that cannot be used inside the deadline."""
    del event
    error = error_object(
        "ledger_unavailable",
        "the ledger could not be read in time",
        notify=True,
        stage=stage,
    )
    if _carried(parsed):
        response["errors"] = [error]
        response["status"] = "error"
        bound_response(response)
        return response, 2
    response["errors"] = [error]
    response["status"] = "partial"
    response["context"] = empty_context(0)
    bound_response(response)
    return response, 1


def _load_binding(ledger: Ledger, client: str, project_root: str) -> Binding | None:
    try:
        binding = ledger.binding(client)
    except StateError as exc:
        raise ContractError(
            "project_identity_invalid", "project identity is not valid"
        ) from exc
    except sqlite3.OperationalError as exc:
        raise ContractError(
            "ledger_unavailable",
            "the ledger could not be read in time",
            stage="binding",
        ) from exc
    if binding is None or not binding.enabled:
        return None
    if binding.project_root != project_root or not Path(binding.project_root).is_dir():
        raise ContractError(
            "project_identity_invalid", "project identity is bound to a different root"
        )
    if not stored_namespace_ok(binding):
        raise ContractError("project_identity_invalid", "project identity is not valid")
    return binding


def _confine(
    root: Path, artifacts: list[str], binding: Binding
) -> tuple[list[str], list[str], list[str]]:
    patterns = tuple(binding.policy.get("ignore_patterns") or [])
    kept: list[str] = []
    ignored: list[str] = []
    missing: list[str] = []
    for artifact in artifacts:
        requested = _request_relative(artifact, root)
        try:
            resolved = validate_file_path(artifact, root)
        except PathValidationError:
            raise ContractError(
                "artifact_escape",
                "artifact resolves outside the project",
                path=safe_relative(requested),
            ) from None
        relative = resolved.relative_to(root.resolve()).as_posix()
        if not resolved.exists():
            missing.append(relative)
        elif _ignored(resolved, relative, patterns):
            ignored.append(relative)
        else:
            kept.append(relative)
    return kept, ignored, missing


def _ignored(resolved: Path, relative: str, extra: tuple[str, ...]) -> bool:
    from agentic_inquiry.integration.contract import EXCLUSION_FLOOR

    if matches_exclusion(relative, EXCLUSION_FLOOR) or (
        extra and matches_exclusion(relative, extra)
    ):
        return True
    try:
        info = resolved.lstat() if resolved.is_symlink() else resolved.stat()
    except OSError:
        return True
    if not stat.S_ISREG(info.st_mode):
        return True
    if info.st_size > _MAX_ARTIFACT_BYTES:
        return True
    try:
        with resolved.open("rb") as handle:
            sample = handle.read(_SNIFF_BYTES)
    except OSError:
        return True
    return b"\x00" in sample


def _request_relative(artifact: str, root: Path) -> str | None:
    path = Path(artifact)
    if path.is_absolute():
        try:
            relative = path.relative_to(root)
        except ValueError:
            return None
    else:
        relative = path
    if ".." in relative.parts:
        return None
    return relative.as_posix()


def _record(
    response: dict[str, Any],
    ledger: Ledger,
    binding: Binding,
    envelope: dict[str, Any],
    content: dict[str, Any],
    observations: list[dict[str, Any]],
    kept: list[str],
    missing: list[str] | None = None,
) -> bool:
    missing = missing or []
    if not observations and not kept and not missing:
        return False
    kind = "capture" if observations else "refresh"
    payload: list[Any] = observations if observations else (kept or missing)
    event_id = str(content.get("event_id") or "")
    event = str(content["_event"])
    if not event_id:
        return False
    key = ledger_key(
        envelope["owner"],
        binding.client,
        binding.project_id,
        envelope["session_id"],
        event,
        event_id,
    )
    receipt = {"kind": "queued", "durable_id": durable_id(kind, key)}
    try:
        if not observations and not kept:
            outcome = ledger.redeliver_only(
                key=key,
                input_hash=payload_fingerprint(observations, missing),
            )
            if outcome is None:
                return False
        else:
            outcome = ledger.record_event(
                key=key,
                client=binding.client,
                owner=envelope["owner"],
                session_id=envelope["session_id"],
                event=event,
                event_id=event_id,
                kind=kind,
                payload=payload,
                input_hash=payload_fingerprint(observations, kept),
                receipt=receipt,
            )
    except sqlite3.OperationalError as exc:
        raise ContractError(
            "ledger_unavailable",
            "the ledger could not be written in time",
            stage="record",
        ) from exc
    if outcome.outcome == "conflict":
        raise ContractError(
            "event_id_conflict",
            "event_id was already delivered with a different payload",
        )
    if outcome.outcome == "purged":
        response["errors"].append(
            error_object("event_purged", outcome.durable_id, notify=False)
        )
        return True
    emitted = dict(outcome.receipt or receipt)
    if outcome.outcome == "duplicate":
        emitted["duplicate"] = True
        emitted["deliveries"] = outcome.deliveries
    response["receipts"].append(emitted)
    return True


def _read_stage(
    response: dict[str, Any],
    ledger: Ledger,
    binding: Binding,
    event: str,
    query: str | None,
    limit: float,
    started: float,
) -> bool:
    budget = int(binding.policy.get("context_budget") or 0)
    if event == "UserPromptSubmit":
        budget = 3 * budget // 4
    if event == "SessionStart":
        try:
            entries = _recall(ledger, binding)
        except sqlite3.OperationalError:
            response["context"] = empty_context(budget)
            response["errors"].append(
                error_object(
                    "ledger_unavailable",
                    "the ledger could not be read in time",
                    notify=True,
                    stage="recall",
                )
            )
            return True
        apply_context(response, entries, budget)
        return False
    from agentic_inquiry.integration.session_recall import has_question

    if not isinstance(query, str) or not has_question(query):
        apply_context(response, [], budget)
        return False
    if _remaining(limit, started) < _EVIDENCE_RESERVE:
        entries = _lexical_entries(ledger, binding, query)
        apply_context(response, entries, budget)
        response["errors"].append(
            error_object(
                "budget_exhausted",
                "the evidence stage was skipped",
                notify=False,
                stage="evidence",
            )
        )
        return True
    entries, dropped, embedded_down = _prompt_entries(
        ledger, binding, query, Path(binding.project_root), limit, started
    )
    apply_context(response, entries, budget)
    if dropped:
        from agentic_inquiry.integration.contract import sanitize_header

        response["context"]["omitted"].extend(
            sanitize_header(item) for item in dropped if item
        )
    if embedded_down:
        response["errors"].append(
            error_object(
                "embedded_unavailable",
                "the embedded half did not run",
                notify=False,
                stage="embedded",
            )
        )
    return False


def _lexical_entries(
    ledger: Ledger, binding: Binding, query: str
) -> list[dict[str, Any]]:
    from agentic_inquiry.integration.session_recall import (
        items_from_captures,
        select_items,
    )

    try:
        rows = ledger.capture_rows(binding.owner, ledger.enabled_clients(binding.owner))
    except sqlite3.OperationalError:
        return []
    chosen = select_items(query, items_from_captures(rows))
    return [item.entry for item in chosen if item.entry and item.kind == "memory"]


def _prompt_entries(
    ledger: Ledger,
    binding: Binding,
    query: str,
    root: Path,
    limit: float,
    started: float,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Union ledger captures with hybrid search.

    Full-text runs only when the warm service does not answer, and the
    response then carries ``embedded_unavailable``. A repeated question
    against the same stamp is the cached ranked list.
    """
    from agentic_inquiry.integration.session_recall import (
        Item,
        index_stamp,
        items_from_captures,
        prompt_stamp,
        read_cache,
        select_items,
        server_marker,
        warm_search,
        write_cache,
    )

    try:
        rows = ledger.capture_rows(binding.owner, ledger.enabled_clients(binding.owner))
    except sqlite3.OperationalError:
        rows = []
    index = index_stamp(root)
    stamp = prompt_stamp(query, rows, index, server_marker())
    cached = read_cache(inquiry_home(), stamp)
    if cached is not None:
        return _cached_entries(cached, root)
    memories = items_from_captures(rows)
    remaining = _remaining(limit, started)
    raw = warm_search(query, timeout=min(1.0, remaining))
    dropped: list[str] = []
    embedded_down = raw is None
    if raw is None:
        evidence, dropped = _evidence(binding, query, root)
    else:
        evidence, dropped = _warm_entries(raw, root)
    evidence_items = [
        Item(
            id=str(entry["id"]),
            text=str(entry.get("body") or ""),
            created="",
            kind="evidence",
            score=float((entry.get("data") or {}).get("score") or 0.0),
            entry=entry,
        )
        for entry in evidence
    ]
    chosen = select_items(query, [*memories, *evidence_items])
    entries = [item.entry for item in chosen if item.entry]
    write_cache(inquiry_home(), stamp, entries, dropped, embedded_down, index=index)
    return entries, dropped, embedded_down


def _cached_entries(
    cached: tuple[list[dict[str, Any]], list[str], bool], root: Path
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Reuse the ranked list, dropping an evidence file that is no longer there."""
    entries, dropped, embedded_down = cached
    kept: list[dict[str, Any]] = []
    extra: list[str] = []
    for entry in entries:
        if entry.get("type") != "evidence":
            kept.append(entry)
            continue
        raw_data = entry.get("data")
        data = raw_data if isinstance(raw_data, dict) else {}
        relative = str(data.get("file_path") or entry.get("file") or "")
        if safe_relative(relative) is None or not _regular_inside(root, relative):
            extra.append(str(entry.get("id") or ""))
            continue
        kept.append(entry)
    return kept, [*dropped, *[item for item in extra if item]], embedded_down


def _warm_entries(
    results: list[dict[str, Any]], root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    from agentic_inquiry.integration.session_recall import (
        evidence_item,
        warm_identifier,
    )

    entries: list[dict[str, Any]] = []
    dropped: list[str] = []
    for result in results:
        raw_path = str(result.get("file_path") or result.get("path") or "")
        relative = _relativize(raw_path, root)
        snippet = prepare_body(
            None, str(result.get("content") or result.get("text") or "")
        )
        identifier = warm_identifier(relative, snippet)
        if safe_relative(relative) is None or not _regular_inside(root, relative):
            dropped.append(identifier)
            continue
        score = result.get("score")
        numeric = (
            float(score)
            if isinstance(score, (int, float)) and not isinstance(score, bool)
            else 0.0
        )
        extra: dict[str, Any] = {}
        for field in ("start_line", "end_line"):
            value = result.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                extra[field] = value
        entries.append(
            evidence_item(
                identifier,
                relative=relative,
                snippet=snippet,
                score=numeric,
                extra=extra,
            ).entry
        )
    return entries, dropped


def _recall(ledger: Ledger, binding: Binding) -> list[dict[str, Any]]:
    clients = ledger.enabled_clients(binding.owner)
    rows = ledger.recent_captures(binding.owner, clients, rows=20)
    entries: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        for index, observation in enumerate(payload):
            if len(entries) >= 32:
                return entries
            if not isinstance(observation, dict) or "content" not in observation:
                continue
            body = prepare_body(observation.get("summary"), str(observation["content"]))
            identifier = f"{durable_id(str(row['kind']), str(row['key']))}.{index}"
            data: dict[str, Any] = {
                "created": str(row["created_at"]),
                "owner": f"{row['owner']}:{row['client']}",
                "summary": body,
            }
            entries.append(
                {
                    "id": identifier,
                    "type": "memory",
                    "owner": str(row["owner"]),
                    "client": str(row["client"]),
                    "created": str(row["created_at"]),
                    "body": body,
                    "data": data,
                }
            )
    return entries


def _evidence(
    binding: Binding, query: str, root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    if not query:
        return [], []
    import asyncio

    from agentic_inquiry.cli.env_resolver import load_config_for_environment
    from agentic_inquiry.storage.facade import StorageFacade

    async def _search() -> list[Any]:
        config = load_config_for_environment(binding.config_path, root)
        facade = await StorageFacade.from_config(config, binding.storage_project_id)
        try:
            return await facade.fts_search(
                query, limit=5, project_id=binding.storage_project_id
            )
        finally:
            close = getattr(facade, "close", None)
            if close is not None:
                result = close()
                if asyncio.iscoroutine(result):
                    await result

    results = asyncio.run(_search())
    entries: list[dict[str, Any]] = []
    dropped: list[str] = []
    for result in results:
        data = getattr(result, "data", {}) or {}
        raw_path = str(data.get("file_path") or data.get("path") or "")
        relative = _relativize(raw_path, root)
        identifier = str(getattr(result, "id", "") or data.get("id") or "evidence")
        if safe_relative(relative) is None or not _regular_inside(root, relative):
            dropped.append(identifier)
            continue
        snippet = prepare_body(None, str(data.get("content") or data.get("text") or ""))
        entry_data: dict[str, Any] = {"file_path": relative, "snippet": snippet}
        score = getattr(result, "score", None)
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            entry_data["score"] = float(score)
        for field in ("start_line", "end_line"):
            value = data.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                entry_data[field] = value
        entries.append(
            {
                "id": identifier,
                "type": "evidence",
                "file": relative,
                "body": snippet,
                "data": entry_data,
            }
        )
    return entries, dropped


def _regular_inside(root: Path, relative: str) -> bool:
    """True when ``relative`` is a regular file that stays inside ``root``."""
    try:
        resolved = (root / relative).resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return resolved.is_file()


def _relativize(path: str, root: Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return path
    return candidate.as_posix()


def _apply_notify(response: dict[str, Any], ledger: Ledger | None, client: str) -> None:
    session = ""
    seen: set[str] = set()
    # session id is not on the response. notify_once needs it. Stash on the function via errors only.
    # The hook stores the session on response temporarily under a key we delete.
    session = str(response.pop("_session_id", "") or "")
    for error in response["errors"]:
        code = str(error["code"])
        if code in seen:
            error["notify"] = False
            continue
        seen.add(code)
        if code in _ALWAYS_NOTIFY or ledger is None:
            error["notify"] = True
            continue
        try:
            error["notify"] = ledger.notify_once(client, session, code)
        except sqlite3.Error:
            error["notify"] = True


def emit(response: dict[str, Any]) -> str:
    return serialise(response)
