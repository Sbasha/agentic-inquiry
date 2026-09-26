"""CLI honesty for ai memory save / list / recall.

STUB: AC3-AC6 — exit 0 only after a same-project list/recall can see the id;
working-memory and in-memory fallback exit 1; table names come from config.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agentic_inquiry.cli import memory as memory_cli
from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.embeddings.hashing import HashingEmbedder
from agentic_inquiry.embeddings.registry import embedding_registry
from agentic_inquiry.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter

pytestmark = pytest.mark.integration

_DIMS = 384


def _test_config(tmp_path: Path) -> Config:
    return Config(
        storage=StorageConfig(
            root=str(tmp_path / "storage"),
            default_project_id="demo",
            backend="lancedb",
        )
    )


def _save_args(
    summary: str,
    *,
    importance: float,
    project: str = "demo",
) -> argparse.Namespace:
    return argparse.Namespace(
        summary=[summary],
        tags=None,
        importance=importance,
        project=project,
    )


def _list_args(*, project: str = "demo", tier: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        project=project,
        tier=tier,
        limit=50,
        json=True,
    )


def _recall_args(query: str, *, project: str = "demo") -> argparse.Namespace:
    return argparse.Namespace(
        query=[query],
        project=project,
        limit=10,
        tags=None,
        json=True,
    )


@pytest.fixture
def hashing_embedder() -> HashingEmbedder:
    embedder = HashingEmbedder(ndims=_DIMS)
    embedding_registry.configure_default_embedder(embedder, ndims=_DIMS)
    return embedder


@pytest.fixture
def memory_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    config = _test_config(tmp_path)
    monkeypatch.setattr(memory_cli, "load_config_for_environment", lambda: config)
    return config


@pytest.mark.asyncio
async def test_save_episodic_then_list_and_recall_same_project(
    hashing_embedder: HashingEmbedder,
    memory_config: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # STUB: AC3, AC4
    _ = hashing_embedder
    summary = "episodic persistence check for honesty"
    code = await memory_cli.save_command(
        _save_args(summary, importance=0.85, project="demo")
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Memory saved:" in out
    assert "episodic" in out.lower()
    saved_id = out.split("Memory saved:", 1)[1].split()[0].strip()

    capsys.readouterr()
    list_code = await memory_cli.list_command(_list_args(project="demo"))
    listed = capsys.readouterr().out
    assert list_code == 0
    assert saved_id in listed

    capsys.readouterr()
    recall_code = await memory_cli.recall_command(
        _recall_args("persistence check", project="demo")
    )
    recalled = capsys.readouterr().out
    assert recall_code == 0
    assert saved_id in recalled

    lance_root = memory_config.storage.get_lancedb_path()
    assert (lance_root / "memory_episodic_medium.lance").exists()


@pytest.mark.asyncio
async def test_save_semantic_uses_canonical_table(
    hashing_embedder: HashingEmbedder,
    memory_config: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # STUB: AC3, AC4
    _ = hashing_embedder
    code = await memory_cli.save_command(
        _save_args("semantic fact about honesty", importance=0.9, project="demo")
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Memory saved:" in out
    assert "semantic" in out.lower()
    lance_root = memory_config.storage.get_lancedb_path()
    assert (lance_root / "memory_semantic_high.lance").exists()


@pytest.mark.asyncio
async def test_working_memory_save_exits_1_session_only(
    hashing_embedder: HashingEmbedder,
    memory_config: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # STUB: AC5
    _ = hashing_embedder
    code = await memory_cli.save_command(
        _save_args("volatile thought", importance=0.5, project="demo")
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "Memory saved:" not in captured.out
    combined = captured.out + captured.err
    assert "session-only" in combined.lower() or "not persisted" in combined.lower()


@pytest.mark.asyncio
async def test_in_memory_fallback_exits_1(
    hashing_embedder: HashingEmbedder,
    memory_config: Config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # STUB: AC4
    _ = hashing_embedder
    _ = memory_config

    class _NoPersist:
        def get_connection_manager(self) -> None:
            return None

        def get_backend_type(self) -> str:
            return "unknown"

        async def close(self) -> None:
            return None

    async def _from_config(*_args: Any, **_kwargs: Any) -> _NoPersist:
        return _NoPersist()

    monkeypatch.setattr(
        "agentic_inquiry.storage.facade.StorageFacade.from_config",
        _from_config,
    )
    code = await memory_cli.save_command(
        _save_args("should not claim success", importance=0.85, project="demo")
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "Memory saved:" not in captured.out


@pytest.mark.asyncio
async def test_missing_readback_exits_1(
    hashing_embedder: HashingEmbedder,
    memory_config: Config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # STUB: AC4
    _ = hashing_embedder
    _ = memory_config
    original_create = memory_cli.create_memory_system

    async def _create_then_hide_row(config: Any, project_id: str) -> Any:
        memory_system, storage = await original_create(config, project_id)
        memory_system.episodic_memory.get_by_id = AsyncMock(return_value=None)
        memory_system.semantic_memory.get_by_id = AsyncMock(return_value=None)
        return memory_system, storage

    monkeypatch.setattr(memory_cli, "create_memory_system", _create_then_hide_row)
    code = await memory_cli.save_command(
        _save_args("row vanishes on read-back", importance=0.85, project="demo")
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "Memory saved:" not in captured.out


@pytest.mark.asyncio
async def test_project_filter_on_list_and_recall(
    hashing_embedder: HashingEmbedder,
    memory_config: Config,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # STUB: AC6
    _ = hashing_embedder
    _ = memory_config
    code = await memory_cli.save_command(
        _save_args("project scoped memory row", importance=0.85, project="demo")
    )
    out = capsys.readouterr().out
    assert code == 0
    saved_id = out.split("Memory saved:", 1)[1].split()[0].strip()

    capsys.readouterr()
    await memory_cli.list_command(_list_args(project="demo"))
    assert saved_id in capsys.readouterr().out

    capsys.readouterr()
    await memory_cli.list_command(_list_args(project="other"))
    assert saved_id not in capsys.readouterr().out

    capsys.readouterr()
    await memory_cli.recall_command(_recall_args("project scoped", project="demo"))
    assert saved_id in capsys.readouterr().out

    capsys.readouterr()
    await memory_cli.recall_command(_recall_args("project scoped", project="other"))
    assert saved_id not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_adapter_initialize_creates_configured_table(tmp_path: Path) -> None:
    # STUB: AC3
    from agentic_inquiry.database.lancedb_manager import LanceDBManager

    config = _test_config(tmp_path)
    manager = LanceDBManager(config=config, project_id="demo")
    await manager.connect()
    try:
        adapter = LanceDBMemoryAdapter(
            manager=manager,
            table_name=config.memory.episodic_memory.table_name,
            embedding_dims=_DIMS,
        )
        await adapter.initialize()
        table = await manager.get_table(config.memory.episodic_memory.table_name)
        assert table is not None
        assert config.memory.episodic_memory.table_name == "memory_episodic_medium"
        assert config.memory.semantic_memory.table_name == "memory_semantic_high"
    finally:
        await manager.close()


def _aiosqlite_threads() -> set[threading.Thread]:
    import aiosqlite

    return {t for t in threading.enumerate() if isinstance(t, aiosqlite.Connection)}


@pytest.mark.asyncio
async def test_create_memory_system_closes_storage_when_setup_fails(
    hashing_embedder: HashingEmbedder, tmp_path: Path
) -> None:
    before = _aiosqlite_threads()

    with patch(
        "agentic_inquiry.memory.system.MemorySystem.initialize",
        AsyncMock(side_effect=RuntimeError("initialize failed")),
    ):
        with pytest.raises(RuntimeError, match="initialize failed"):
            await memory_cli.create_memory_system(_test_config(tmp_path), "demo")

    assert _aiosqlite_threads() - before == set()


def test_memory_commands_exit_after_printing(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("INQUIRY_")},
        "HOME": str(tmp_path / "home"),
        "INQUIRY_EMBEDDINGS_DEFAULT_PROVIDER": "hashing",
        # recall embeds its query at 384 dims whatever the hashing size.
        "INQUIRY_EMBEDDINGS_HASHING_NDIMS": "384",
    }
    for args in (
        ["save", "exit probe fact", "--importance", "0.9"],
        ["list"],
        ["recall", "exit probe fact"],
    ):
        completed = subprocess.run(
            [sys.executable, "-m", "agentic_inquiry.cli", "memory", *args],
            capture_output=True,
            cwd=project,
            env=env,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr.decode(errors="replace")

