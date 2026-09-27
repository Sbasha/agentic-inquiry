"""Tests for the REST memory store and recall routes.

Uses FastAPI TestClient with a mocked memory system, version manager and
cache so the routes run without storage infrastructure.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_inquiry.memory.models import (
    MemoryContext,
    MemoryItem,
    MemoryTier,
    RetrievalResult,
)
from agentic_inquiry.server.routes.memory import router

pytestmark = pytest.mark.unit


def _retrieval_result(content: str, category: str) -> RetrievalResult:
    item = MemoryItem(
        id="mem-1",
        content=content,
        summary=content,
        context=MemoryContext(agent_id="rest_api", session_id="s", conversation_id="s"),
        importance=0.8,
        tier=MemoryTier.EPISODIC,
        creator_agent_id="rest_api",
        modifier_agent_id="rest_api",
        metadata={"category": category, "file_paths": ["auth.py"]},
    )
    return RetrievalResult(item=item, relevance_score=0.9, retrieval_tier=MemoryTier.EPISODIC)


def _build_test_app() -> tuple[FastAPI, MagicMock]:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    memory_system = MagicMock()
    memory_system.store = AsyncMock(return_value=SimpleNamespace(id="mem-1"))
    memory_system.retrieve = AsyncMock(
        return_value=[_retrieval_result("Auth uses JWT", "decision")]
    )

    version_manager = MagicMock()
    version_manager.create_version_metadata.return_value = {}
    version_manager.check_staleness.side_effect = lambda memories: memories

    cache_manager = MagicMock()
    cache_manager.get_memories.return_value = None
    cache_manager.hash_key.return_value = "key"

    app.state.services = {"memory_system": memory_system}
    app.state.version_manager = version_manager
    app.state.cache_manager = cache_manager
    app.state.project_id = "proj-1"
    return app, memory_system


def test_store_reaches_memory_system() -> None:
    app, memory_system = _build_test_app()

    response = TestClient(app).post(
        "/api/v1/memory/store", json={"content": "Auth uses JWT"}
    )

    assert response.status_code == 200
    assert response.json() == {"id": "mem-1", "stored": True}
    context = memory_system.store.await_args.kwargs["context"]
    assert isinstance(context, MemoryContext)
    assert context.project_id == "proj-1"


def test_recall_returns_memory_system_results() -> None:
    app, memory_system = _build_test_app()

    response = TestClient(app).post(
        "/api/v1/memory/recall", json={"query": "auth"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cached"] is False
    [memory] = body["memories"]
    assert memory["content"] == "Auth uses JWT"
    assert memory["category"] == "decision"
    assert memory["importance"] == 0.8
    assert memory["file_paths"] == ["auth.py"]
    context = memory_system.retrieve.await_args.kwargs["context"]
    assert context.project_id == "proj-1"
