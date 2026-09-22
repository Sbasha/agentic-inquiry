# agentic_inquiry/mcp/services/gatherers/graph_gatherer.py
"""Graph relationship context gatherer implementation."""
import logging
from typing import Any, Dict, List, Set

from agentic_inquiry.search.service import SearchService
from agentic_inquiry.utils import get_attr as _get_attr
from .protocol import ContextGathererProtocol, GatherContext

logger = logging.getLogger(__name__)


class GraphGatherer(ContextGathererProtocol):
    """Expands context via knowledge graph relationships.

    Traverses relationships from entities in the current context to find
    related entities. Depth determines how far to traverse.
    """

    def __init__(self, search_service: SearchService) -> None:
        """Initialize graph gatherer.

        Args:
            search_service: Search service for traversing relationships
        """
        self.search = search_service

    @property
    def gatherer_type(self) -> str:
        """Return gatherer type."""
        return "relationships"

    async def gather(self, context: GatherContext) -> List[Dict[str, Any]]:
        """Expand context via graph relationships.

        Traverses relationships from entities in the initial context to find
        related entities. Depth determines how far to traverse:
        - focused: No expansion (returns empty)
        - broad: 1 hop from current entities
        - comprehensive: 2 hops from current entities

        Args:
            context: Gather context with initial_context containing
                     code and documentation items to expand from

        Returns:
            List of relationship items with connected entities
        """
        if context.depth == "focused":
            # No relationship expansion for focused depth
            return []

        if not context.project_id:
            logger.warning("No project_id provided for graph gathering")
            return []

        # Determine max depth based on search depth
        max_depth = 1 if context.depth == "broad" else 2

        # Collect entity IDs from code and documentation items
        entity_ids: List[str] = []
        for item in context.initial_context.get("code", []):
            if item.get("id"):
                entity_ids.append(item["id"])
        for item in context.initial_context.get("documentation", []):
            if item.get("id"):
                entity_ids.append(item["id"])

        if not entity_ids:
            logger.debug("No entities to expand relationships from")
            return []

        # Limit number of entities to expand from (to avoid explosion)
        max_entities_to_expand = 5 if context.depth == "broad" else 10
        entity_ids = entity_ids[:max_entities_to_expand]

        relationship_items: List[Dict[str, Any]] = []
        discovered_entities: Set[str] = set()

        try:
            # Traverse relationships from each entity
            for entity_id in entity_ids:
                if context.budget.remaining() < 200:
                    logger.debug("Budget too low for more relationship expansion")
                    break

                # Traverse relationships
                result = await self.search.traverse_relationships(
                    entity_id=entity_id,
                    direction="both",
                    max_depth=max_depth,
                    project_id=context.project_id,
                    include_metadata=True
                )

                if not result.get("relationships"):
                    continue

                # Process relationships
                for rel in result["relationships"]:
                    # Get target entity (the one we're discovering)
                    target_id = _get_attr(rel, "target_id")
                    source_id = _get_attr(rel, "source_id")

                    # Determine which entity is new
                    new_entity_id = target_id if source_id == entity_id else source_id

                    # Skip if we've already discovered this entity
                    if new_entity_id in discovered_entities:
                        continue

                    discovered_entities.add(new_entity_id)

                    # Get entity data
                    entity_data = result["entities"].get(new_entity_id)
                    if not entity_data:
                        continue

                    # Create relationship item
                    rel_item = self._relationship_to_context_item(
                        rel=rel,
                        entity_data=entity_data,
                        new_entity_id=new_entity_id,
                        connected_to=entity_id,
                        connected_to_name=_get_attr(result["entity"], "name", "")
                    )

                    # Create snippet for token budget
                    snippet_text = f"{rel_item['name']} ({rel_item['relationship_type']})"

                    # Check budget
                    if context.budget.can_add(snippet_text):
                        context.budget.add(snippet_text)
                        relationship_items.append(rel_item)
                    else:
                        logger.debug("Skipping relationship %s - budget exceeded", new_entity_id)
                        break

            logger.info(
                "Expanded via relationships: found %s related entities from %s source entities",
                len(relationship_items), len(entity_ids)
            )
            return relationship_items

        except Exception as e:
            logger.error("Error expanding via relationships: %s", e)
            return []

    def _relationship_to_context_item(
        self,
        rel: Dict[str, Any],
        entity_data: Dict[str, Any],
        new_entity_id: str,
        connected_to: str,
        connected_to_name: str
    ) -> Dict[str, Any]:
        """Convert relationship to context item dictionary.

        Args:
            rel: Relationship data
            entity_data: Data about the discovered entity
            new_entity_id: ID of the discovered entity
            connected_to: ID of the source entity
            connected_to_name: Name of the source entity

        Returns:
            Context item dictionary
        """
        return {
            "id": new_entity_id,
            "type": "relationship",
            "name": _get_attr(entity_data, "name", "Unknown"),
            "entity_type": _get_attr(entity_data, "type", ""),
            "relationship_type": _get_attr(rel, "type", ""),
            "relationship_direction": _get_attr(rel, "direction", ""),
            "depth": _get_attr(rel, "depth", 1),
            "connected_to": connected_to,
            "connected_to_name": connected_to_name,
            "location": _get_attr(entity_data, "file_path", ""),
            "summary": _get_attr(entity_data, "summary", "")[:200],
            "metadata": _get_attr(rel, "metadata", {}),
            "relevance_score": 0.5,  # Default for relationships
            "snippet": "",
            "why_relevant": f"Related via {_get_attr(rel, 'type', 'unknown')} relationship"
        }
