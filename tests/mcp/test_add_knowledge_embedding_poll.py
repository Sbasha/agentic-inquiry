"""Single-file add_knowledge waits for server-side embeddings before READY."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_inquiry.events.types import EventTypes
from agentic_inquiry.mcp.tools.knowledge import add_knowledge
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk

pytestmark = pytest.mark.unit

PIPELINE_PATCH_PATH = "agentic_inquiry.indexing.pipeline.IndexingPipeline"
PARSER_CHAIN_PATCH_PATH = "agentic_inquiry.mcp.tools.knowledge.create_parser_chain"


def _services() -> dict:
    session_manager = AsyncMock()
    session_manager.validate_session.return_value = True
    session = MagicMock()
    session.project_id = "test_project"
    session_manager.get_session.return_value = session

    config = MagicMock()
    config.storage.root = "/test/root"
    config.progress.enabled = False

    capabilities = MagicMock()
    capabilities.needs_embedding_polling = True

    return {
        "session_manager": session_manager,
        "event_system": AsyncMock(),
        "config": config,
        "storage": AsyncMock(),
        "capabilities": capabilities,
    }


@pytest.mark.asyncio
async def test_single_file_polls_embeddings_before_ready(tmp_path, monkeypatch):
    test_file = tmp_path / "test.py"
    test_file.write_text("def test():\n    pass")
    monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))
    services = _services()
    order: list[str] = []

    async def _poll(*args, **kwargs) -> None:
        assert (args, kwargs) == ((), {})
        order.append("poll")

    async def _emit(event_type, **kwargs) -> None:
        order.append(event_type)

    services["event_system"].emit = AsyncMock(side_effect=_emit)

    with patch(PIPELINE_PATCH_PATH) as pipeline_cls, patch(PARSER_CHAIN_PATCH_PATH) as chain_factory:
        pipeline = MagicMock()
        pipeline.process_document = AsyncMock()
        pipeline.flush_pending_relationships = AsyncMock(return_value=0)
        pipeline.get_resolution_stats = MagicMock(return_value={})
        pipeline._poll_embedding_completion = AsyncMock(side_effect=_poll)
        pipeline_cls.return_value = pipeline

        chain = MagicMock()
        chain.parse = AsyncMock(
            return_value=ParsedDocument(
                doc_id="test_doc",
                file_path=str(test_file),
                chunks=[ParserChunk(content="test", line_start=1, line_end=1)],
            )
        )
        chain_factory.return_value = chain

        await add_knowledge(
            services=services,
            session_id="test_session",
            content_type="file",
            source=str(test_file),
        )

    pipeline._poll_embedding_completion.assert_awaited_once()
    assert order.index("poll") < order.index(EventTypes.Indexing.READY)
