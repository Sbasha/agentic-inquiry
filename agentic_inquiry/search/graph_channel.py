"""Graph retrieval channel: chunks holding the callers and callees of the top results.

After the vector and full-text lists are fused, the definitions inside the
best few results seed a one-hop walk over ``calls`` and ``inherits``
relationships. The chunks that contain the neighbouring definitions form a
third ranked list for fusion, ordered by the rank of the seed they came from.
This surfaces code the query words do not name, such as the helper a public
method delegates to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from agentic_inquiry.database.filters import and_, is_in, or_

if TYPE_CHECKING:
    from agentic_inquiry.storage.facade import StorageFacade

logger = logging.getLogger(__name__)

DEFINITION_TYPES = frozenset({"function", "method", "class", "interface", "struct"})
RELATIONS = frozenset({"calls", "inherits"})
_ROW_LIMIT = 20_000


def _line(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _inside(entity: Dict[str, Any], row: Dict[str, Any]) -> bool:
    start, end = _line(row.get("line_start")), _line(row.get("line_end"))
    return start > 0 and start <= _line(entity.get("line_start")) <= end


async def graph_candidates(
    storage: "StorageFacade",
    seeds: Sequence[Dict[str, Any]],
    project_id: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Chunk rows for one-hop neighbours of definitions in ``seeds``, best seed first."""
    files = sorted({str(s.get("file_path")) for s in seeds if s.get("file_path")})
    if not files:
        return []
    entities = await storage.advanced_filter(
        "graph_entities",
        is_in("file_path", files),
        limit=_ROW_LIMIT,
        project_id=project_id,
    )
    seed_ids: List[str] = []
    for seed in seeds:
        for entity in entities:
            if (
                entity.get("type") in DEFINITION_TYPES
                and entity.get("file_path") == seed.get("file_path")
                and _inside(entity, seed)
                and entity["id"] not in seed_ids
            ):
                seed_ids.append(entity["id"])
    if not seed_ids:
        return []
    edges = await storage.advanced_filter(
        "graph_relationships",
        and_(
            is_in("type", sorted(RELATIONS)),
            or_(is_in("source_id", seed_ids), is_in("target_id", seed_ids)),
        ),
        limit=_ROW_LIMIT,
        project_id=project_id,
    )
    order = {entity_id: rank for rank, entity_id in enumerate(seed_ids)}
    neighbours: Dict[str, int] = {}
    for edge in edges:
        for here, there in (
            (edge.get("source_id"), edge.get("target_id")),
            (edge.get("target_id"), edge.get("source_id")),
        ):
            if here in order and there not in order and there:
                neighbours[there] = min(neighbours.get(there, len(order)), order[here])
    if not neighbours:
        return []
    ranked_ids = sorted(neighbours, key=lambda entity_id: neighbours[entity_id])[
        : limit * 2
    ]
    targets = await storage.advanced_filter(
        "graph_entities",
        is_in("id", ranked_ids),
        limit=len(ranked_ids),
        project_id=project_id,
    )
    by_id = {
        e["id"]: e
        for e in targets
        if e.get("type") in DEFINITION_TYPES and _line(e.get("line_start")) > 0
    }
    target_files = sorted({str(e["file_path"]) for e in by_id.values()})
    if not target_files:
        return []
    rows = await storage.advanced_filter(
        "document_chunks",
        is_in("file_path", target_files),
        limit=_ROW_LIMIT,
        project_id=project_id,
    )
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for entity_id in ranked_ids:
        entity = by_id.get(entity_id)
        if entity is None:
            continue
        for row in rows:
            if (
                row.get("file_path") == entity.get("file_path")
                and _inside(entity, row)
                and row["id"] not in seen
            ):
                seen.add(row["id"])
                out.append(row)
                break
        if len(out) >= limit:
            break
    logger.debug(
        "Graph channel: %d seeds, %d neighbours, %d chunks",
        len(seed_ids),
        len(neighbours),
        len(out),
    )
    return out
