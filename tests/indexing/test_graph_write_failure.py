"""Graph-relationship write failures must fail the index honestly.

STUB: AC2 — do not swallow commit_batch / flush errors; status is not completed;
exit 1 even when chunks_created > 0; printed summary names the graph error.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentic_inquiry.cli.index import exit_code_for_index_result
from agentic_inquiry.exceptions import StorageError
from agentic_inquiry.indexing.relationship_batch_processor import RelationshipBatchProcessor
from agentic_inquiry.models.graph_relationship import GraphRelationship

pytestmark = pytest.mark.unit

_GRAPH_ERROR = "Ambiguous merge inserts are prohibited"


def _relationship() -> GraphRelationship:
    return GraphRelationship(
        id="edge_deadbeef",
        source_id="src",
        target_id="tgt",
        type="calls",
        project_id="demo",
        vector=[0.0] * 128,
        metadata=None,
    )


@pytest.mark.asyncio
async def test_commit_batch_does_not_swallow_graph_write_error() -> None:
    # STUB: AC2
    db_manager = MagicMock()
    db_manager.add_graph_relationships = AsyncMock(
        side_effect=StorageError(_GRAPH_ERROR)
    )
    processor = RelationshipBatchProcessor(
        db_manager=db_manager,
        pending_relationship_getter=lambda: 0,
        pending_external_getter=lambda: 0,
    )
    stats: dict[str, Any] = {"committed_count": 0, "commit_failures": 0}

    with pytest.raises(StorageError, match="Ambiguous merge"):
        await processor.commit_batch([_relationship()], batch_number=1, stats=stats)


@pytest.mark.asyncio
async def test_graph_builder_commit_batch_does_not_swallow_error() -> None:
    # STUB: AC2
    from agentic_inquiry.indexing.graph_builder import GraphBuilder

    db_manager = MagicMock()
    db_manager.add_graph_relationships = AsyncMock(
        side_effect=StorageError(_GRAPH_ERROR)
    )
    builder = GraphBuilder(
        db_manager=db_manager,
        symbol_registry=MagicMock(),
        relationship_resolver=MagicMock(),
        embedding_service=MagicMock(),
        project_id="demo",
        project_hash="abc",
        project_root="/tmp",
    )
    stats: dict[str, Any] = {"committed_count": 0, "commit_failures": 0}

    with pytest.raises(StorageError, match="Ambiguous merge"):
        await builder._commit_batch([_relationship()], batch_number=1, stats=stats)


def test_graph_write_failure_with_chunks_exits_1_and_names_error() -> None:
    # STUB: AC2
    from agentic_inquiry.indexing.models import IndexingResult
    from agentic_inquiry.indexing.pipeline import _graph_write_indexing_error

    err = _graph_write_indexing_error(StorageError(_GRAPH_ERROR))
    result = IndexingResult(
        operation_id="op-1",
        status="completed_with_errors",
        chunks_created=12,
        files_processed=1,
        errors=[err],
        message=f"Graph relationship write failed: {_GRAPH_ERROR}",
    )
    payload = result.to_dict()
    assert payload["status"] != "completed"
    assert exit_code_for_index_result(payload) == 1
    assert _GRAPH_ERROR in payload["message"]
    assert _GRAPH_ERROR in payload["errors"][0]["message"]
