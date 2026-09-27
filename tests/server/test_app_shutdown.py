"""The server app closes the stores it opens when its lifespan ends.

Each open aiosqlite connection holds a non-daemon thread, and interpreter
shutdown joins those threads, so a store left open keeps the server process
alive after uvicorn stops.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from agentic_inquiry.config import Config, StorageConfig

pytestmark = pytest.mark.integration


def _store_threads() -> set[threading.Thread]:
    return {
        thread
        for thread in threading.enumerate()
        if not thread.daemon
        and thread.is_alive()
        and type(thread).__module__.startswith("aiosqlite")
    }


def _config(tmp_path) -> Config:
    config = Config()
    config.mcp.api.auth = {"enabled": False, "api_key": None}
    config.storage = StorageConfig(
        root=str(tmp_path), default_project_id="test_shutdown", backend="lancedb"
    )
    return config


async def _wait_closed(opened: set[threading.Thread]) -> None:
    for _ in range(50):
        if not opened & _store_threads():
            return
        await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_lifespan_exit_closes_the_stores_the_app_opened(tmp_path):
    from agentic_inquiry.server.app import create_app

    config = _config(tmp_path)
    before = _store_threads()

    app = await create_app(
        config=config, project_id="test_shutdown", workspace=str(tmp_path)
    )
    opened = _store_threads() - before
    assert opened, (
        "create_app opened no aiosqlite store; the test no longer checks anything"
    )

    async with app.router.lifespan_context(app):
        pass

    await _wait_closed(opened)
    assert not opened & _store_threads()


class _Interrupted(BaseException):
    """Stands in for a signal arriving while the app is being assembled."""


@pytest.mark.asyncio
async def test_interrupted_create_app_closes_the_stores_it_opened(
    tmp_path, monkeypatch
):
    from agentic_inquiry.server import app as app_module

    def interrupt(*args, **kwargs):
        raise _Interrupted()

    monkeypatch.setattr(app_module.GitVersionManager, "update_last_commit", interrupt)
    before = _store_threads()

    with pytest.raises(_Interrupted):
        await app_module.create_app(
            config=_config(tmp_path),
            project_id="test_shutdown",
            workspace=str(tmp_path),
        )

    leaked = _store_threads() - before
    await _wait_closed(leaked)
    assert not leaked & _store_threads()
