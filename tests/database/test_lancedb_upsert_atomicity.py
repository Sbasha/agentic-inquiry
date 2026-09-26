"""On-disk LanceDB tests for LanceDBManager.upsert().

Two writers that replace the same key leave one row, and each upsert is a
single commit (docs/specs/lancedb-single-commit-upsert/spec.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

import pytest

from agentic_inquiry.database.lancedb_manager import LanceDBManager
from tests.utils.commit_hook import commit_hook

pytestmark = pytest.mark.integration

_TABLE = "mcp_sessions"


def _session(session_id: str, state: str, **extra: Any) -> Dict[str, Any]:
    return {
        "id": session_id,
        "session_id": session_id,
        "project_id": "proj",
        "state": state,
        **extra,
    }


@pytest.fixture
async def manager(tmp_path: Path) -> AsyncIterator[LanceDBManager]:
    mgr = LanceDBManager(uri=str(tmp_path / "lancedb"))
    await mgr.connect()
    try:
        yield mgr
    finally:
        await mgr.close()


async def _rows(manager: LanceDBManager, session_id: str) -> List[Dict[str, Any]]:
    table = await manager.get_table(_TABLE)
    assert table is not None
    return [
        row for row in table.to_arrow().to_pylist() if row["session_id"] == session_id
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("key_field", ["id", "session_id"])
async def test_concurrent_upsert_leaves_one_row(
    manager: LanceDBManager, key_field: str
) -> None:
    await manager.upsert(_TABLE, [_session("s1", "seed")], key_field=key_field)
    fired = False

    async def second_writer(_table: str) -> None:
        nonlocal fired
        if fired:
            return
        fired = True
        await manager.upsert(_TABLE, [_session("s1", "second")], key_field=key_field)

    async with commit_hook(manager, on_exit=second_writer):
        await manager.upsert(_TABLE, [_session("s1", "first")], key_field=key_field)

    assert fired
    rows = await _rows(manager, "s1")
    assert [row["state"] for row in rows] == ["second"]


@pytest.mark.asyncio
async def test_upsert_is_one_commit(manager: LanceDBManager) -> None:
    await manager.upsert(_TABLE, [_session("s1", "seed")], key_field="session_id")
    table = await manager.get_table(_TABLE)
    assert table is not None
    before = table.version

    await manager.upsert(_TABLE, [_session("s1", "next")], key_field="session_id")

    assert table.version == before + 1


@pytest.mark.asyncio
async def test_upsert_inserts_new_and_updates_existing(manager: LanceDBManager) -> None:
    await manager.upsert(_TABLE, [_session("s1", "seed")])

    await manager.upsert(_TABLE, [_session("s1", "updated"), _session("s2", "new")])

    assert [row["state"] for row in await _rows(manager, "s1")] == ["updated"]
    assert [row["state"] for row in await _rows(manager, "s2")] == ["new"]


@pytest.mark.asyncio
async def test_upsert_keeps_columns_a_record_omits(manager: LanceDBManager) -> None:
    await manager.upsert(_TABLE, [_session("s1", "seed", note="kept")])

    await manager.upsert(_TABLE, [_session("s1", "next")])

    rows = await _rows(manager, "s1")
    assert [(row["state"], row["note"]) for row in rows] == [("next", "kept")]


@pytest.mark.asyncio
async def test_upsert_collapses_repeated_keys_to_last(manager: LanceDBManager) -> None:
    await manager.upsert(_TABLE, [_session("s1", "seed")])

    await manager.upsert(_TABLE, [_session("s1", "one"), _session("s1", "two")])

    assert [row["state"] for row in await _rows(manager, "s1")] == ["two"]


@pytest.mark.asyncio
@pytest.mark.parametrize("key_value", ["missing", None, ""])
async def test_upsert_rejects_record_without_key(
    manager: LanceDBManager, key_value: Any
) -> None:
    await manager.upsert(_TABLE, [_session("s1", "seed")])
    table = await manager.get_table(_TABLE)
    assert table is not None
    before = table.version
    keyless = _session("s2", "new")
    if key_value == "missing":
        del keyless["session_id"]
    else:
        keyless["session_id"] = key_value

    with pytest.raises(ValueError, match="session_id"):
        await manager.upsert(
            _TABLE, [_session("s3", "new"), keyless], key_field="session_id"
        )

    assert table.version == before
    assert table.count_rows() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("note_first", [True, False])
async def test_upsert_rejects_mixed_field_sets(
    manager: LanceDBManager, note_first: bool
) -> None:
    await manager.upsert(
        _TABLE, [_session("s1", "seed", note="a"), _session("s2", "seed", note="b")]
    )
    table = await manager.get_table(_TABLE)
    assert table is not None
    before = table.version
    records = [_session("s1", "next", note="new"), _session("s2", "next")]
    if not note_first:
        records.reverse()

    with pytest.raises(ValueError, match="same fields"):
        await manager.upsert(_TABLE, records)

    assert table.version == before


@pytest.mark.asyncio
async def test_upsert_rejects_forbidden_field_with_value_error(
    manager: LanceDBManager,
) -> None:
    await manager.upsert(_TABLE, [_session("s1", "seed")])
    table = await manager.get_table(_TABLE)
    assert table is not None
    before = table.version

    with pytest.raises(ValueError, match="chunk_id"):
        await manager.upsert(_TABLE, [_session("s2", "new", chunk_id="c")])

    assert table.version == before
