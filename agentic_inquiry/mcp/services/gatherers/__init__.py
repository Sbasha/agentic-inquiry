# agentic_inquiry/mcp/services/gatherers/__init__.py
"""Context gatherer implementations.

This module provides a protocol-based abstraction for gathering context
from different sources (code, documentation, memories, relationships).

Usage:
    from agentic_inquiry.mcp.services.gatherers import (
        ContextGathererProtocol,
        GatherContext,
        CodeGatherer,
        DocsGatherer,
        MemoryGatherer,
        GraphGatherer,
    )

    # Create gatherers with dependencies
    code_gatherer = CodeGatherer(search_service, token_optimizer)
    docs_gatherer = DocsGatherer(search_service, token_optimizer)
    memory_gatherer = MemoryGatherer(memory_system, token_optimizer)
    graph_gatherer = GraphGatherer(search_service)

    # Use with GatherContext
    context = GatherContext(
        query="authentication",
        budget=token_budget,
        depth="broad",
        project_id="my_project",
        session_id="session_123"
    )

    code_items = await code_gatherer.gather(context)
"""
from .protocol import ContextGathererProtocol, GatherContext
from .code_gatherer import CodeGatherer
from .docs_gatherer import DocsGatherer
from .memory_gatherer import MemoryGatherer
from .graph_gatherer import GraphGatherer

__all__ = [
    "ContextGathererProtocol",
    "GatherContext",
    "CodeGatherer",
    "DocsGatherer",
    "MemoryGatherer",
    "GraphGatherer",
]
