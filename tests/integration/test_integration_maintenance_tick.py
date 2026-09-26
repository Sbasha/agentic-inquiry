"""The MCP maintenance tick commits queued integration rows."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, Mock

from agentic_inquiry.integration import reconcile as reconcile_module
from agentic_inquiry.mcp.factories import _maintenance_tick


def _run(
    home: Path, project: Path, *args: str, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("INQUIRY_")},
        "HOME": str(home),
        "INQUIRY_HOME": str(home / ".agentic-inquiry"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "INQUIRY_EMBEDDINGS_DEFAULT_PROVIDER": "hashing",
        "INQUIRY_EMBEDDINGS_DEFAULT_DIMENSIONS": "128",
    }
    return subprocess.run(
        [sys.executable, "-m", "agentic_inquiry.cli", *args],
        input=stdin if stdin is not None else b"",
        capture_output=True,
        cwd=str(project),
        env=env,
        timeout=120,
    )


def _row(home: Path, project: Path) -> sqlite3.Row:
    marker = json.loads(
        (project / ".agentic-inquiry" / "integration.json").read_text(encoding="utf-8")
    )
    path = (
        home
        / ".agentic-inquiry"
        / "projects"
        / marker["project_id"]
        / "records.sqlite3"
    )
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            "SELECT state, receipt FROM integration_events"
        ).fetchone()
    finally:
        connection.close()


@pytest.fixture
def queued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    home = (tmp_path / "home").resolve()
    home.mkdir(mode=0o700)
    (home / ".agentic-inquiry").mkdir(mode=0o700)
    project = (tmp_path / "project").resolve()
    (project / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    monkeypatch.chdir(project)
    from agentic_inquiry.cli.setup.local_setup import LocalSetup

    assert LocalSetup(env_name="ai", workspace=project).run() is True
    enabled = _run(
        home,
        project,
        "integration",
        "enable",
        "--client",
        "claude-code",
        "--owner",
        "afp",
        "--project-root",
        str(project),
    )
    assert enabled.returncode == 0, enabled.stdout + enabled.stderr
    payload = {
        "schema_version": 1,
        "owner": "afp",
        "project_root": str(project),
        "session_id": "tick-session",
        "event_id": "stop-tick",
        "observations": [{"content": "queued for the tick", "importance": 0.9}],
    }
    queued_hook = _run(
        home,
        project,
        "integration",
        "hook",
        "--client",
        "claude-code",
        "--event",
        "Stop",
        stdin=json.dumps(payload).encode("utf-8"),
    )
    assert queued_hook.returncode == 1, queued_hook.stdout + queued_hook.stderr
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("INQUIRY_HOME", str(home / ".agentic-inquiry"))
    monkeypatch.setenv("INQUIRY_EMBEDDINGS_DEFAULT_PROVIDER", "hashing")
    monkeypatch.setenv("INQUIRY_EMBEDDINGS_DEFAULT_DIMENSIONS", "128")
    return home, project


def test_tick_commits_a_pending_capture(queued: tuple[Path, Path]) -> None:
    home, project = queued
    row = _row(home, project)
    assert row["state"] == "pending"
    asyncio.run(_maintenance_tick(None, None, str(project)))
    committed = _row(home, project)
    assert committed["state"] == "committed"
    assert json.loads(committed["receipt"])["kind"] == "remembered"


def test_tick_skips_when_the_project_lock_is_held(
    queued: tuple[Path, Path], caplog: pytest.LogCaptureFixture
) -> None:
    home, project = queued
    marker = json.loads(
        (project / ".agentic-inquiry" / "integration.json").read_text(encoding="utf-8")
    )
    lock_path = home / ".agentic-inquiry" / "projects" / marker["project_id"] / "lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with caplog.at_level("WARNING"):
            asyncio.run(_maintenance_tick(None, None, str(project)))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert _row(home, project)["state"] == "pending"
    assert any(
        "environment_busy" in record.message or "reconcile skipped" in record.message
        for record in caplog.records
    )


def _aiosqlite_threads() -> set[threading.Thread]:
    import aiosqlite

    return {
        t
        for t in threading.enumerate()
        if isinstance(t, aiosqlite.Connection) and t.is_alive()
    }


@pytest.fixture
def consolidations(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    from agentic_inquiry.memory.consolidation import ConsolidationEngine

    consolidate = AsyncMock()
    monkeypatch.setattr(ConsolidationEngine, "consolidate", consolidate)
    return consolidate


def test_tick_releases_the_runtime_without_consolidating(
    queued: tuple[Path, Path], consolidations: AsyncMock
) -> None:
    home, project = queued
    before = _aiosqlite_threads()

    asyncio.run(_maintenance_tick(None, None, str(project)))

    assert _row(home, project)["state"] == "committed"
    consolidations.assert_not_awaited()
    assert _aiosqlite_threads() - before == set()


def test_failed_row_still_releases_the_runtime(
    queued: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, project = queued
    monkeypatch.setattr(
        reconcile_module,
        "_commit_one",
        AsyncMock(return_value=("failed", {"outcome": "failed", "memory_ids": []}, None)),
    )
    before = _aiosqlite_threads()

    result = asyncio.run(reconcile_module.reconcile(str(project), lock_timeout=0))

    assert result["failed"] == 1
    assert _aiosqlite_threads() - before == set()


def test_raising_commit_still_releases_the_runtime(
    queued: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, project = queued
    monkeypatch.setattr(
        reconcile_module, "_commit_one", AsyncMock(side_effect=RuntimeError("commit failed"))
    )
    before = _aiosqlite_threads()

    with pytest.raises(RuntimeError, match="commit failed"):
        asyncio.run(reconcile_module.reconcile(str(project), lock_timeout=0))

    assert _aiosqlite_threads() - before == set()


def test_failing_memory_shutdown_still_closes_storage(
    queued: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentic_inquiry.memory.system import MemorySystem

    home, project = queued
    monkeypatch.setattr(
        MemorySystem, "shutdown", AsyncMock(side_effect=RuntimeError("shutdown failed"))
    )
    before = _aiosqlite_threads()

    asyncio.run(_maintenance_tick(None, None, str(project)))

    assert _row(home, project)["state"] == "committed"
    assert _aiosqlite_threads() - before == set()


def test_failed_runtime_setup_closes_its_storage(
    queued: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, project = queued
    monkeypatch.setattr(
        "agentic_inquiry.indexing.pipeline.IndexingPipeline.__init__",
        Mock(side_effect=RuntimeError("pipeline failed")),
    )
    before = _aiosqlite_threads()

    with pytest.raises(RuntimeError, match="pipeline failed"):
        asyncio.run(reconcile_module.reconcile(str(project), lock_timeout=0))

    assert _aiosqlite_threads() - before == set()
