"""`ai search` must close its storage, or the process never exits.

An open storage leaves aiosqlite's non-daemon connection thread running, and
the interpreter waits for it at shutdown after the results are printed.
"""

from __future__ import annotations

import argparse
import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from agentic_inquiry.cli import search as cli_search


class FakeStorage:
    def __init__(self) -> None:
        self.closed = False

    def get_capabilities(self) -> Any:
        return SimpleNamespace(uses_server_side_embedding=True)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    fake = FakeStorage()

    async def from_config(config: Any, project_id: str) -> FakeStorage:
        return fake

    config = SimpleNamespace(storage=SimpleNamespace(default_project_id="p"))
    monkeypatch.setattr(cli_search, "load_config_for_environment", lambda: config)
    monkeypatch.setattr(
        "agentic_inquiry.embeddings.factory.configure_embedder_for_backend",
        lambda config, quiet=True: None,
    )
    monkeypatch.setattr(
        "agentic_inquiry.storage.facade.StorageFacade.from_config", from_config
    )
    return fake


def _args(**extra: Any) -> argparse.Namespace:
    return argparse.Namespace(
        query=["redirects"],
        project=None,
        type="all",
        limit=2,
        json=True,
        verbose=False,
        **extra,
    )


@pytest.mark.parametrize("fails", [False, True])
def test_search_closes_storage(
    storage: FakeStorage, monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    async def hybrid_search(self: Any, **kwargs: Any) -> list[Any]:
        if fails:
            raise RuntimeError("search failed")
        return []

    monkeypatch.setattr(
        "agentic_inquiry.search.service.SearchService.__init__", lambda *a: None
    )
    monkeypatch.setattr(
        "agentic_inquiry.search.service.SearchService.hybrid_search", hybrid_search
    )
    code = asyncio.run(cli_search.search_command(_args()))
    assert code == (1 if fails else 0)
    assert storage.closed


def test_similar_closes_storage(
    storage: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hybrid_search(self: Any, **kwargs: Any) -> list[Any]:
        return []

    monkeypatch.setattr(
        "agentic_inquiry.search.service.SearchService.__init__", lambda *a: None
    )
    monkeypatch.setattr(
        "agentic_inquiry.search.service.SearchService.hybrid_search", hybrid_search
    )
    asyncio.run(cli_search.similar_command(_args(entity="Session")))
    assert storage.closed
