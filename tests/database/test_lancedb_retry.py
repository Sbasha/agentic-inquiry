"""Tests for retryable LanceDB write conflicts."""

from __future__ import annotations

import pytest

from agent_vault.database.lancedb_manager import (
    _is_retryable_lancedb_error,
    _retry_lancedb_write,
)
from agent_vault.exceptions import StorageError


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RuntimeError("Retryable commit conflict"), True),
        (RuntimeError("commit conflict on table document_chunks"), True),
        (
            StorageError("Database operation failed: upsert_rows. Error: Retryable"),
            True,
        ),
        (RuntimeError("schema mismatch: missing column"), False),
        (PermissionError("permission denied"), False),
        (StorageError("Data schema may not match table schema."), False),
        # STUB: AC2 — Ambiguous merge is not a retryable commit conflict
        (RuntimeError("Ambiguous merge inserts are prohibited"), False),
    ],
)
def test_is_retryable_lancedb_error(exc: BaseException, expected: bool) -> None:
    assert _is_retryable_lancedb_error(exc) is expected


def test_is_retryable_follows_cause_chain() -> None:
    inner = RuntimeError("Retryable commit conflict")
    wrapped = StorageError("Database operation failed: upsert_rows")
    wrapped.__cause__ = inner
    assert _is_retryable_lancedb_error(wrapped) is True


@pytest.mark.asyncio
async def test_retry_succeeds_on_third_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_vault.database.lancedb_manager.asyncio.sleep",
        _instant_sleep,
    )
    calls = {"n": 0}

    async def flaky() -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Retryable commit conflict")

    await _retry_lancedb_write(flaky)
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_non_retryable_raises_on_first_attempt() -> None:
    calls = {"n": 0}

    async def boom() -> None:
        calls["n"] += 1
        raise RuntimeError("schema mismatch")

    with pytest.raises(RuntimeError, match="schema mismatch"):
        await _retry_lancedb_write(boom)
    assert calls["n"] == 1


async def _instant_sleep(_delay: float) -> None:
    return None
