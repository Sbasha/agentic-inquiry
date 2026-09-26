"""On-disk LanceDB tests for session persistence.

Persisting a changed session replaces its row in one upsert, and the change
reads back (docs/specs/lancedb-single-commit-upsert/spec.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest

from agentic_inquiry.config import Config
from agentic_inquiry.mcp.models.session import Session
from agentic_inquiry.mcp.services.persistence.lancedb_backend import (
    LanceDBSessionStorage,
)
from agentic_inquiry.storage.facade import StorageFacade

pytestmark = pytest.mark.integration


@pytest.fixture
async def storage(tmp_path: Path) -> AsyncIterator[LanceDBSessionStorage]:
    config = Config.load()
    config.storage.root = str(tmp_path / "storage")
    facade = await StorageFacade.from_config(config, project_id="proj")
    try:
        yield LanceDBSessionStorage(facade)
    finally:
        await facade.close()


@pytest.mark.asyncio
async def test_persist_changed_session_keeps_one_row(
    storage: LanceDBSessionStorage, tmp_path: Path
) -> None:
    session = Session(
        session_id="sess-1",
        project_id="proj",
        description="first",
        log_file=tmp_path / "session.log",
    )
    await storage.persist_session(session)

    session.status = "closed"
    session.description = "second"
    session.context_state = {"query": "retry policy"}
    session.history.append({"tool": "search", "timestamp": "t1"})
    await storage.persist_session(session)

    loaded = await storage.load_session("sess-1")
    assert loaded is not None
    assert loaded.status == "closed"
    assert loaded.description == "second"
    assert loaded.context_state == {"query": "retry policy"}
    assert loaded.history == [{"tool": "search", "timestamp": "t1"}]
    table = await storage.db_manager.get_table(LanceDBSessionStorage.TABLE_NAME)
    assert table is not None
    rows = [r for r in table.to_arrow().to_pylist() if r["session_id"] == "sess-1"]
    assert len(rows) == 1
