"""Shared dict→``GraphEntity`` conversion for LanceDB providers.

Extracted so :class:`LanceDBGraphProvider` (which provisions
``graph_entities``) and :class:`LanceDBVectorProvider` (which runs
``entity_vector_search`` against the same table) share one hydration
path without either package importing from the other.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from agentic_inquiry.models.graph_entity import GraphEntity

logger = logging.getLogger(__name__)

# Shared table constant so both providers agree on the name.
GRAPH_ENTITIES_TABLE = "graph_entities"


def dict_to_graph_entity(record: Dict[str, Any]) -> Optional[GraphEntity]:
    """Hydrate a LanceDB row dict into a GraphEntity, returning None on
    shape mismatches instead of raising — the upstream provider logs and
    skips so a single bad row doesn't take down a whole query.
    """
    try:
        return GraphEntity(
            id=record.get("id", ""),
            project_id=record.get("project_id", ""),
            name=record.get("name", ""),
            type=record.get("type", "unknown"),
            file_path=record.get("file_path", ""),
            doc_id=record.get("doc_id", ""),
            vector=record.get("vector", []),
            line_start=record.get("line_start", -1),
            line_end=record.get("line_end", -1),
            pagerank=record.get("pagerank"),
            betweenness=record.get("betweenness"),
            community_id=record.get("community_id"),
            has_ranking_signals=record.get("has_ranking_signals", False),
        )
    except Exception as e:
        logger.warning("Failed to convert record to GraphEntity: %s", e)
        return None


__all__ = ["GRAPH_ENTITIES_TABLE", "dict_to_graph_entity"]
