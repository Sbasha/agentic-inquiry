"""Shared row→``GraphEntity`` conversion for Postgres providers.

Lives in its own module so both :class:`PostgresGraphProvider` (which
provisions the entity tables) and :class:`PostgresVectorProvider` (which
runs vector similarity search against the entity embedding column) can
hydrate rows without either importing from the other — the graph and
vector packages already have enough cross-talk.
"""

from __future__ import annotations

import json
from typing import Any

from agent_vault.models.graph_entity import GraphEntity


def row_to_entity(row: Any) -> GraphEntity:
    """Hydrate an asyncpg Record from the entities table into a GraphEntity.

    Handles the two shapes the ``embedding`` column can take on readout:
    pgvector's native array (``.tolist()``) or a plain list/tuple when the
    caller projects it differently. Metadata comes back as JSON string or
    dict depending on asyncpg version / codec; normalize to dict.
    """
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)

    embedding = row.get("embedding")
    if embedding is not None and hasattr(embedding, "tolist"):
        vector = embedding.tolist()
    elif isinstance(embedding, (list, tuple)):
        vector = list(embedding)
    else:
        vector = []

    return GraphEntity(
        id=row["id"],
        name=row["name"],
        type=row["entity_type"],
        file_path=row["file_path"],
        doc_id=metadata.get("doc_id", row["id"]),
        project_id=row["project_id"],
        vector=vector,
        line_start=row.get("start_line", -1) or -1,
        line_end=row.get("end_line", -1) or -1,
        pagerank=metadata.get("pagerank"),
        betweenness=metadata.get("betweenness"),
        community_id=metadata.get("community_id"),
    )


__all__ = ["row_to_entity"]
