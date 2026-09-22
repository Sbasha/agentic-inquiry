"""Lineage tracing service for data flow analysis.

Traces data paths from UI components through backend services to database
columns, and performs impact analysis for change assessment.
"""
from __future__ import annotations

import logging
import uuid
from collections import deque
from typing import TYPE_CHECKING, List, Optional, Set

from agentic_inquiry.config import Config
from agentic_inquiry.constants import CURRENT_PROJECT_ID
from agentic_inquiry.models.lineage import (
    ArchitecturalLayer,
    Confidence,
    ImpactAnalysis,
    LineagePath,
    LineageStep,
    infer_layer,
    is_pii_field,
)

if TYPE_CHECKING:
    from agentic_inquiry.storage.facade import StorageFacade

logger = logging.getLogger(__name__)


class LineageService:
    """Traces data lineage paths through the knowledge graph.

    Provides:
    - Downstream tracing: UI → Service → Repository → Database
    - Upstream tracing: Database → Repository → Service → UI
    - Gap detection: Missing connections in paths
    - Impact analysis: What changes when an entity changes

    Example:
        >>> storage = await StorageFacade.from_config(config, "my_project")
        >>> lineage = LineageService(storage, config)
        >>> paths = await lineage.trace_downstream("ui_form_field")
    """

    def __init__(
        self,
        storage: "StorageFacade",
        config: Config,
        project_id: Optional[str] = None,
    ):
        """Initialize lineage service.

        Args:
            storage: StorageFacade for graph access
            config: Configuration object
            project_id: Optional project ID override
        """
        self._storage = storage
        self._config = config
        self._project_id = project_id or storage.project_id
        # Cache keyed by (project_id, entity_id) for project isolation
        self._entity_cache: dict[tuple[str, str], dict] = {}

    def _resolve_project_id(self, project_id: Optional[str]) -> Optional[str]:
        """Resolve project ID from parameter or instance default."""
        if project_id == CURRENT_PROJECT_ID:
            return self._project_id
        return project_id

    async def _get_entity(
        self,
        entity_id: str,
        project_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Get entity by ID with caching and project isolation.

        Args:
            entity_id: Entity ID to retrieve
            project_id: Project ID for isolation (uses default if None)

        Returns:
            Entity dict or None if not found
        """
        resolved_project = project_id or self._project_id
        cache_key = (resolved_project or "", entity_id)

        if cache_key in self._entity_cache:
            return self._entity_cache[cache_key]

        # Query with project_id parameter for proper isolation
        filters: dict[str, str] = {"id": entity_id}

        try:
            entities = await self._storage.query_raw(
                table_name="graph_entities",
                filters=filters,
                limit=1,
                project_id=resolved_project,
            )
        except Exception as e:
            logger.error("Failed to get entity %s: %s", entity_id, e)
            return None

        if entities:
            self._entity_cache[cache_key] = entities[0]
            return entities[0]
        return None

    def _entity_to_step(
        self,
        entity: dict,
        relationship_type: Optional[str] = None,
        confidence: Confidence = Confidence.MEDIUM,
    ) -> LineageStep:
        """Convert entity dict to LineageStep.

        Args:
            entity: Entity dictionary from storage
            relationship_type: How this step connects to previous
            confidence: Confidence level for this step

        Returns:
            LineageStep instance
        """
        layer = infer_layer(
            entity_name=entity.get("name", ""),
            entity_type=entity.get("type", ""),
            file_path=entity.get("file_path"),
        )

        return LineageStep(
            entity_id=entity["id"],
            entity_name=entity.get("name", "unknown"),
            entity_type=entity.get("type", "unknown"),
            layer=layer,
            file_path=entity.get("file_path"),
            line_number=entity.get("line_number"),
            relationship_type=relationship_type,
            confidence=confidence,
        )

    async def _get_relationships(
        self,
        entity_id: str,
        direction: str = "outgoing",
        project_id: Optional[str] = None,
    ) -> List[dict]:
        """Get relationships for an entity with project isolation.

        Uses a higher limit to avoid edge truncation (Codex fix: limit=100 issue).
        Note: query_raw doesn't support offset, so we use a single large query.

        Args:
            entity_id: Entity to get relationships for
            direction: "outgoing" or "incoming"
            project_id: Project ID for isolation

        Returns:
            List of relationship dictionaries
        """
        resolved_project = project_id or self._project_id

        if direction == "outgoing":
            filters: dict[str, str] = {"source_id": entity_id}
        else:
            filters = {"target_id": entity_id}

        # Use a large limit to get all relationships
        # Most entities have <1000 relationships
        try:
            rels = await self._storage.query_raw(
                table_name="graph_relationships",
                filters=filters,
                limit=5000,
                project_id=resolved_project,
            )
        except Exception as e:
            logger.error("Failed to get relationships for %s: %s", entity_id, e)
            return []

        if len(rels) >= 5000:
            logger.warning(
                "Entity %s has >=5000 %s relationships, some may be truncated",
                entity_id, direction
            )

        return rels

    async def trace_downstream(
        self,
        source_id: str,
        max_depth: int = 10,
        target_layers: Optional[List[ArchitecturalLayer]] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[LineagePath]:
        """Trace lineage from source (UI) toward sink (database).

        Uses BFS with cycle detection to find all paths from source
        to target layers.

        Args:
            source_id: Starting entity ID
            max_depth: Maximum traversal depth
            target_layers: Stop when reaching these layers (default: DATABASE)
            project_id: Project ID to search in

        Returns:
            List of lineage paths found
        """
        resolved_project_id = self._resolve_project_id(project_id)

        # Get starting entity with project isolation
        start_entity = await self._get_entity(source_id, resolved_project_id)
        if not start_entity:
            logger.warning("Source entity not found: %s (project: %s)", source_id, resolved_project_id)
            return []

        paths: List[LineagePath] = []

        # BFS state: (current_id, path_steps)
        start_step = self._entity_to_step(start_entity)
        visited: Set[str] = {source_id}
        queue: deque[tuple[str, List[LineageStep]]] = deque(
            [(source_id, [start_step])]
        )

        while queue:
            current_id, path_steps = queue.popleft()

            if len(path_steps) > max_depth:
                continue

            # Get outgoing relationships with project isolation
            relationships = await self._get_relationships(
                current_id, direction="outgoing", project_id=resolved_project_id
            )

            if not relationships:
                # Leaf node — record path if it has more than just the start
                if len(path_steps) > 1:
                    paths.append(LineagePath(
                        path_id=str(uuid.uuid4()),
                        source_id=source_id,
                        sink_id=current_id,
                        steps=path_steps,
                        is_complete=target_layers is None or (
                            path_steps[-1].layer in target_layers
                            if target_layers else False
                        ),
                    ))
                continue

            for rel in relationships:
                target_id = rel.get("target_id")
                if not target_id or target_id in visited:
                    continue
                visited.add(target_id)

                # Get target entity with project isolation
                target_entity = await self._get_entity(target_id, resolved_project_id)
                if not target_entity:
                    continue

                # Create step for target
                rel_type = rel.get("type") or rel.get("relationship_type")
                target_step = self._entity_to_step(
                    target_entity,
                    relationship_type=rel_type,
                    confidence=self._infer_confidence(rel),
                )

                new_path = path_steps + [target_step]

                # If target layers specified and we reached one, record path
                if target_layers and target_step.layer in target_layers:
                    paths.append(LineagePath(
                        path_id=str(uuid.uuid4()),
                        source_id=source_id,
                        sink_id=target_id,
                        steps=new_path,
                        is_complete=True,
                    ))
                else:
                    queue.append((target_id, new_path))

        logger.info(
            "trace_downstream found %d paths from %s (max_depth=%d)",
            len(paths), source_id, max_depth
        )
        return paths

    async def trace_upstream(
        self,
        sink_id: str,
        max_depth: int = 10,
        target_layers: Optional[List[ArchitecturalLayer]] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[LineagePath]:
        """Trace lineage from sink (database) toward source (UI).

        Args:
            sink_id: Starting entity ID (typically database column)
            max_depth: Maximum traversal depth
            target_layers: Stop when reaching these layers (default: UI)
            project_id: Project ID to search in

        Returns:
            List of lineage paths found (reversed, so source is first)
        """
        resolved_project_id = self._resolve_project_id(project_id)

        # Get starting entity with project isolation
        start_entity = await self._get_entity(sink_id, resolved_project_id)
        if not start_entity:
            logger.warning("Sink entity not found: %s (project: %s)", sink_id, resolved_project_id)
            return []

        paths: List[LineagePath] = []

        # BFS with incoming relationships
        start_step = self._entity_to_step(start_entity)
        visited: Set[str] = {sink_id}
        queue: deque[tuple[str, List[LineageStep]]] = deque(
            [(sink_id, [start_step])]
        )

        while queue:
            current_id, path_steps = queue.popleft()

            if len(path_steps) > max_depth:
                continue

            # Get incoming relationships with project isolation
            relationships = await self._get_relationships(
                current_id, direction="incoming", project_id=resolved_project_id
            )

            if not relationships:
                # Leaf node — record path if it has more than just the start
                if len(path_steps) > 1:
                    paths.append(LineagePath(
                        path_id=str(uuid.uuid4()),
                        source_id=current_id,
                        sink_id=sink_id,
                        steps=path_steps,
                        is_complete=target_layers is None or (
                            path_steps[0].layer in target_layers
                            if target_layers else False
                        ),
                    ))
                continue

            for rel in relationships:
                source_entity_id = rel.get("source_id")
                if not source_entity_id or source_entity_id in visited:
                    continue
                visited.add(source_entity_id)

                # Get source entity with project isolation
                source_entity = await self._get_entity(source_entity_id, resolved_project_id)
                if not source_entity:
                    continue

                rel_type = rel.get("type") or rel.get("relationship_type")
                source_step = self._entity_to_step(
                    source_entity,
                    relationship_type=rel_type,
                    confidence=self._infer_confidence(rel),
                )

                new_path = [source_step] + path_steps

                # If target layers specified and we reached one, record path
                if target_layers and source_step.layer in target_layers:
                    paths.append(LineagePath(
                        path_id=str(uuid.uuid4()),
                        source_id=source_entity_id,
                        sink_id=sink_id,
                        steps=new_path,
                        is_complete=True,
                    ))
                else:
                    queue.append((source_entity_id, new_path))

        logger.info(
            "trace_upstream found %d paths from %s (max_depth=%d)",
            len(paths), sink_id, max_depth
        )
        return paths

    async def find_gaps(
        self,
        entity_id: str,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[str]:
        """Identify missing connections in lineage.

        Args:
            entity_id: Entity to check for gaps
            project_id: Project ID

        Returns:
            List of gap descriptions
        """
        resolved_project_id = self._resolve_project_id(project_id)
        gaps: List[str] = []

        entity = await self._get_entity(entity_id, resolved_project_id)
        if not entity:
            return [f"Entity not found: {entity_id}"]

        layer = infer_layer(
            entity.get("name", ""),
            entity.get("type", ""),
            entity.get("file_path"),
        )

        # Layer-specific gap detection
        if layer == ArchitecturalLayer.ENTITY:
            # Entities should have MAPS_TO relationship to columns
            rels = await self._get_relationships(entity_id, "outgoing", resolved_project_id)
            has_db_mapping = any(
                r.get("type") in ("maps_to", "references", "defines")
                and r.get("target_id")
                for r in rels
            )
            if not has_db_mapping:
                gaps.append(f"No database mapping for entity {entity.get('name')}")

        elif layer == ArchitecturalLayer.CONTROLLER:
            # Controllers should call services
            rels = await self._get_relationships(entity_id, "outgoing", resolved_project_id)
            has_service_call = any(
                r.get("type") in ("calls", "uses", "references")
                for r in rels
            )
            if not has_service_call:
                gaps.append(f"Controller {entity.get('name')} has no service calls")

        elif layer == ArchitecturalLayer.UI:
            # UI should have downstream connections
            rels = await self._get_relationships(entity_id, "outgoing", resolved_project_id)
            if not rels:
                gaps.append(f"UI component {entity.get('name')} has no bindings")

        return gaps

    async def analyze_impact(
        self,
        entity_id: str,
        max_depth: int = 5,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> ImpactAnalysis:
        """Analyze what would be affected by changing an entity.

        Args:
            entity_id: Entity to analyze
            max_depth: Maximum traversal depth
            project_id: Project ID

        Returns:
            ImpactAnalysis with affected entities and risk level
        """
        resolved_project_id = self._resolve_project_id(project_id)

        entity = await self._get_entity(entity_id, resolved_project_id)
        if not entity:
            return ImpactAnalysis(
                entity_id=entity_id,
                entity_name="unknown",
                risk_level="LOW",
            )

        entity_name = entity.get("name", "unknown")

        # BFS over incoming relationships to find ALL dependents,
        # regardless of architectural layer.  The previous approach
        # called trace_upstream with target_layers=[UI, CONTROLLER]
        # which filtered out SERVICE/REPOSITORY dependents and
        # returned 0 affected entities for storage-layer code.
        affected: Set[str] = set()
        affected_files: Set[str] = set()
        upstream_paths: List[LineagePath] = []

        start_step = self._entity_to_step(entity)
        visited: Set[str] = {entity_id}
        queue: deque[tuple[str, List[LineageStep]]] = deque(
            [(entity_id, [start_step])]
        )

        while queue:
            current_id, path_steps = queue.popleft()
            if len(path_steps) > max_depth:
                continue

            relationships = await self._get_relationships(
                current_id, direction="incoming", project_id=resolved_project_id
            )

            for rel in relationships:
                source_entity_id = rel.get("source_id")
                if not source_entity_id or source_entity_id in visited:
                    continue
                visited.add(source_entity_id)

                source_entity = await self._get_entity(
                    source_entity_id, resolved_project_id
                )
                if not source_entity:
                    continue

                rel_type = rel.get("type") or rel.get("relationship_type")
                source_step = self._entity_to_step(
                    source_entity,
                    relationship_type=rel_type,
                    confidence=self._infer_confidence(rel),
                )

                affected.add(source_entity_id)
                if source_step.file_path:
                    affected_files.add(source_step.file_path)

                new_path = [source_step] + path_steps
                queue.append((source_entity_id, new_path))

        # Calculate risk
        is_pii = is_pii_field(entity_name)
        risk_level = self._calculate_risk(affected, is_pii)

        return ImpactAnalysis(
            entity_id=entity_id,
            entity_name=entity_name,
            affected_entities=list(affected),
            affected_files=list(affected_files),
            affected_count=len(affected),
            risk_level=risk_level,
            paths=upstream_paths,
            is_pii=is_pii,
        )

    def _calculate_risk(
        self,
        affected: Set[str],
        is_pii: bool,
    ) -> str:
        """Calculate change risk level.

        Args:
            affected: Set of affected entity IDs
            is_pii: Whether the target is a PII field

        Returns:
            Risk level string
        """
        if is_pii:
            return "CRITICAL"
        elif len(affected) > 50:
            return "HIGH"
        elif len(affected) > 10:
            return "MEDIUM"
        else:
            return "LOW"

    def _infer_confidence(self, relationship: dict) -> Confidence:
        """Infer confidence level from relationship metadata.

        Args:
            relationship: Relationship dictionary

        Returns:
            Confidence level
        """
        # Check for explicit confidence in metadata
        metadata = relationship.get("metadata")
        if isinstance(metadata, dict):
            conf = metadata.get("confidence") or metadata.get("resolution_confidence")
            if conf is not None:
                if conf >= 0.9:
                    return Confidence.HIGH
                elif conf >= 0.7:
                    return Confidence.MEDIUM
                elif conf >= 0.5:
                    return Confidence.LOW
                else:
                    return Confidence.INFERRED

        # Default based on relationship type
        rel_type = relationship.get("type") or relationship.get("relationship_type", "")
        if rel_type in ("defines", "contains", "inherits"):
            return Confidence.HIGH
        elif rel_type in ("calls", "imports", "references"):
            return Confidence.MEDIUM
        else:
            return Confidence.LOW

    def clear_cache(self) -> None:
        """Clear the entity cache."""
        self._entity_cache.clear()
