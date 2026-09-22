"""Impact analyzer service for analyzing code change impact.

This module provides the ImpactAnalyzer service that analyzes the impact
of changes to code entities by traversing relationships in the knowledge graph.
"""

from typing import Any, List, Dict, Set, Optional
from dataclasses import dataclass
from collections import deque
from pathlib import Path
import logging
import time

from agent_vault.config import Config
from agent_vault.storage.facade import StorageFacade
from agent_vault.utils import get_attr as _get_attr
from agent_vault.mcp.services.entity_resolver import (
    EntityResolver,
    EntityReference,
    EntityNotFoundError
)

logger = logging.getLogger(__name__)


class PartialResultsException(Exception):
    """Exception raised when analysis times out with partial results.

    Attributes:
        partial_results: Dictionary containing partial analysis results
        elapsed_ms: Time elapsed before timeout in milliseconds
    """
    def __init__(self, partial_results: dict, elapsed_ms: int):
        self.partial_results = partial_results
        self.elapsed_ms = elapsed_ms
        super().__init__(f"Analysis timed out after {elapsed_ms}ms with partial results")


@dataclass
class DependencyNode:
    """A node in the dependency tree.

    Attributes:
        name: Entity name
        entity_type: Type of entity (class, function, etc.)
        file_path: Path to the file containing the entity
        relationship: Relationship type to parent (e.g., "imports", "calls")
        children: Child nodes (entities that this entity affects/depends on)
    """
    name: str
    entity_type: str
    file_path: str
    relationship: Optional[str] = None
    children: Optional[List["DependencyNode"]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: Dict[str, Any] = {
            "name": self.name,
            "type": self.entity_type,
            "file_path": self.file_path,
        }
        if self.relationship:
            result["relationship"] = self.relationship
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result


@dataclass
class ImpactAnalysis:
    """Result of impact analysis.

    Attributes:
        entity_name: Name of the analyzed entity
        impact_radius: Number of affected entities
        affected_files: Dictionary mapping file paths to entity counts
        affected_entities: List of affected entity references
        relationship_types: Dictionary mapping relationship types to counts
        traversal_depth: Actual depth reached during traversal
        dependency_tree: Optional tree structure of dependencies
        incoming_tree: Optional tree of entities that depend on this (reverse impact)
    """
    entity_name: str
    impact_radius: int
    affected_files: Dict[str, int]
    affected_entities: List[EntityReference]
    relationship_types: Dict[str, int]
    traversal_depth: int
    dependency_tree: Optional[DependencyNode] = None
    incoming_tree: Optional[DependencyNode] = None


class ImpactAnalyzer:
    """Analyzes the impact of changes to code entities.

    Uses breadth-first search to traverse relationships in the knowledge graph,
    identifying all entities that would be affected by changes to a given entity.
    Supports configurable depth and cycle detection to prevent infinite loops.
    """

    def __init__(
        self,
        db_manager: StorageFacade,
        entity_resolver: EntityResolver,
        config: Config
    ):
        """Initialize impact analyzer.

        Args:
            db_manager: StorageFacade instance providing unified storage access
            entity_resolver: Entity resolver for finding entities
            config: Configuration object
        """
        # Use StorageFacade directly - it provides query_entities and query_relationships
        # methods that work across all backends (LanceDB, PostgreSQL, etc.)
        self.db = db_manager
        logger.debug("ImpactAnalyzer initialized with StorageFacade")

        self.entity_resolver = entity_resolver
        self.config = config
    
    async def analyze_impact(
        self,
        entity_name: str,
        project_id: str,
        depth: Optional[int] = None,
        include_indirect: Optional[bool] = None,
        deadline: Optional[float] = None
    ) -> ImpactAnalysis:
        """Analyze impact of changing an entity.

        Traverses:
        - Incoming relationships (who depends on this)
        - Outgoing relationships (what this depends on)
        - Transitive dependencies up to depth

        Args:
            entity_name: Name of entity to analyze
            project_id: Project identifier
            depth: Traversal depth (None = use config default)
            include_indirect: Include indirect dependencies (None = use config default)
            deadline: Optional absolute time (from time.time()) to stop analysis

        Returns:
            ImpactAnalysis with affected entities and files

        Raises:
            EntityNotFoundError: If entity cannot be resolved
            PartialResultsException: If analysis times out with partial results
        """
        start_time = time.time()
        # Use config defaults if not specified (Phase 2: flattened into indexing config)
        if depth is None:
            depth = self.config.indexing.impact_default_depth
        if include_indirect is None:
            include_indirect = self.config.indexing.impact_include_indirect
        
        # Enforce max depth
        depth = min(depth, self.config.indexing.impact_max_depth)
        
        logger.debug(
            "Analyzing impact: entity=%s, project_id=%s, depth=%d, include_indirect=%s",
            entity_name,
            project_id,
            depth,
            include_indirect
        )
        
        # Resolve the entity first
        entity = await self.entity_resolver.resolve_entity(
            entity_name=entity_name,
            project_id=project_id
        )

        if not entity:
            raise EntityNotFoundError(entity_name, [])

        # Bridge entity-level to file-level IDs for traversal.
        # Relationships use file-level source_id (e.g., "file::project::/path::/path")
        # but entity resolution returns function-level IDs (e.g., "function::project::/path::name").
        # We need to traverse from the file-level ID to find relationships.
        traversal_ids = {entity.entity_id}
        if entity.file_path and entity.entity_id:
            # Build the file-level entity ID that relationships use as source_id
            parts = entity.entity_id.split("::")
            if len(parts) >= 2:
                project_hash = parts[1]
                file_id = f"file::{project_hash}::{entity.file_path}::{entity.file_path}"
                traversal_ids.add(file_id)
                # Also try module-level ID
                module_name = Path(entity.file_path).stem
                module_id = f"module::{project_hash}::{entity.file_path}::{module_name}"
                traversal_ids.add(module_id)

        logger.debug(
            "Impact analysis: entity=%s, entity_id=%s, traversal_ids=%s",
            entity_name, entity.entity_id, traversal_ids,
        )

        # Track visited entities to prevent cycles
        visited: Set[str] = set()
        visited.update(traversal_ids)

        # Collect all affected entities - accumulate incrementally for partial results
        affected_entities: List[EntityReference] = []
        relationship_types: Dict[str, int] = {}
        completed_depth = 0
        incoming_completed = False
        
        # Traverse incoming relationships (who depends on this entity)
        if include_indirect:
            # Check deadline before starting incoming traversal
            if deadline and time.time() >= deadline:
                elapsed_ms = int((time.time() - start_time) * 1000)
                raise PartialResultsException(
                    partial_results={
                        "entity_name": entity_name,
                        "affected_entities": [],
                        "relationship_types": {},
                        "completed_depth": 0,
                        "incoming_completed": False,
                        "outgoing_completed": False
                    },
                    elapsed_ms=elapsed_ms
                )

            try:
                # Traverse from all ID variants (entity-level + file-level)
                incoming: Set[str] = set()
                incoming_depth = 0
                for tid in traversal_ids:
                    tid_result, tid_depth = await self.traverse_relationships(
                        entity_id=tid,
                        project_id=project_id,
                        direction="incoming",
                        depth=depth,
                        visited=visited.copy(),
                        deadline=deadline,
                    )
                    incoming.update(tid_result)
                    incoming_depth = max(incoming_depth, tid_depth)

                # Get entity details for each affected entity
                for affected_id in incoming:
                    entity_refs = await self._get_entity_references(
                        entity_ids=[affected_id],
                        project_id=project_id,
                        relationship_type="depends_on"
                    )
                    affected_entities.extend(entity_refs)
                    relationship_types["depends_on"] = relationship_types.get("depends_on", 0) + len(entity_refs)

                incoming_completed = True
                completed_depth = max(completed_depth, incoming_depth)

            except PartialResultsException as e:
                # Propagate partial results from traversal
                raise PartialResultsException(
                    partial_results={
                        "entity_name": entity_name,
                        "affected_entities": affected_entities,
                        "relationship_types": relationship_types,
                        "completed_depth": e.partial_results.get("completed_depth", 0),
                        "incoming_completed": False,
                        "outgoing_completed": False
                    },
                    elapsed_ms=e.elapsed_ms
                )

        # Check deadline before outgoing traversal
        if deadline and time.time() >= deadline:
            elapsed_ms = int((time.time() - start_time) * 1000)
            raise PartialResultsException(
                partial_results={
                    "entity_name": entity_name,
                    "affected_entities": affected_entities,
                    "relationship_types": relationship_types,
                    "completed_depth": completed_depth,
                    "incoming_completed": incoming_completed,
                    "outgoing_completed": False
                },
                elapsed_ms=elapsed_ms
            )

        # Traverse outgoing relationships (what this entity depends on)
        try:
            outgoing: Set[str] = set()
            outgoing_depth = 0
            for tid in traversal_ids:
                tid_result, tid_depth = await self.traverse_relationships(
                    entity_id=tid,
                    project_id=project_id,
                    direction="outgoing",
                    depth=depth,
                    visited=visited.copy(),
                    deadline=deadline,
                )
                outgoing.update(tid_result)
                outgoing_depth = max(outgoing_depth, tid_depth)

            # Get entity details for dependencies
            for dep_id in outgoing:
                entity_refs = await self._get_entity_references(
                    entity_ids=[dep_id],
                    project_id=project_id,
                    relationship_type="dependency"
                )
                affected_entities.extend(entity_refs)
                relationship_types["dependency"] = relationship_types.get("dependency", 0) + len(entity_refs)

            completed_depth = max(completed_depth, outgoing_depth)

        except PartialResultsException as e:
            # Propagate partial results from traversal
            raise PartialResultsException(
                partial_results={
                    "entity_name": entity_name,
                    "affected_entities": affected_entities,
                    "relationship_types": relationship_types,
                    "completed_depth": e.partial_results.get("completed_depth", 0),
                    "incoming_completed": incoming_completed,
                    "outgoing_completed": False
                },
                elapsed_ms=e.elapsed_ms
            )
        
        # Calculate affected files
        affected_files: Dict[str, int] = {}
        for ref in affected_entities:
            file_path = ref.file_path
            affected_files[file_path] = affected_files.get(file_path, 0) + 1
        
        impact_radius = len(affected_entities)

        # Build dependency trees for visualization (optional, expensive)
        # Skip tree building if deadline is tight — trees double the query count
        # and are not needed for impact radius / affected entity calculations.
        dependency_tree = None
        incoming_tree = None
        remaining_budget = (deadline - time.time()) if deadline else float("inf")
        if remaining_budget > 10.0:  # Only build trees if >10s budget remains
            dependency_tree = await self.build_dependency_tree(
                entity_id=entity.entity_id,
                entity_name=entity.name,
                entity_type=entity.entity_type,
                file_path=entity.file_path,
                project_id=project_id,
                direction="outgoing",
                depth=depth
            )

            remaining_budget = (deadline - time.time()) if deadline else float("inf")
            if include_indirect and remaining_budget > 10.0:
                incoming_tree = await self.build_dependency_tree(
                    entity_id=entity.entity_id,
                    entity_name=entity.name,
                    entity_type=entity.entity_type,
                    file_path=entity.file_path,
                    project_id=project_id,
                    direction="incoming",
                    depth=depth
                )

        logger.debug(
            "Impact analysis complete: entity=%s, radius=%d, files=%d, depth=%d",
            entity_name,
            impact_radius,
            len(affected_files),
            depth
        )

        return ImpactAnalysis(
            entity_name=entity_name,
            impact_radius=impact_radius,
            affected_files=affected_files,
            affected_entities=affected_entities,
            relationship_types=relationship_types,
            traversal_depth=depth,
            dependency_tree=dependency_tree,
            incoming_tree=incoming_tree
        )
    
    async def traverse_relationships(
        self,
        entity_id: str,
        project_id: str,
        direction: str,
        depth: int,
        visited: Set[str],
        deadline: Optional[float] = None
    ) -> tuple[Set[str], int]:
        """Recursively traverse relationships with cycle detection.

        Uses breadth-first search to traverse relationships up to the specified depth.
        Tracks visited entities to prevent infinite loops in circular dependencies.

        Args:
            entity_id: Starting entity identifier
            project_id: Project identifier
            direction: "incoming", "outgoing", or "both"
            depth: Maximum traversal depth
            visited: Set of already visited entity IDs
            deadline: Optional absolute time (from time.time()) to stop traversal

        Returns:
            Tuple of (Set of entity IDs reached, completed depth level)

        Raises:
            PartialResultsException: If traversal times out with partial results
        """
        start_time = time.time()
        if depth <= 0:
            return set(), 0

        logger.debug(
            "Traversing relationships: entity_id=%s, direction=%s, depth=%d, visited=%d",
            entity_id,
            direction,
            depth,
            len(visited)
        )

        # Use database-level CTE traversal when available (single SQL round-trip).
        # Falls back to Python BFS for backends that don't support get_neighbors.
        MAX_TOTAL_ENTITIES = 200
        result: Set[str] = set()
        completed_depth = depth
        use_bfs = True  # Fall back to BFS if CTE returns 0 or fails

        # Use graph provider's CTE directly (bypasses facade's hardcoded project_id)
        graph_provider = getattr(self.db, '_graph_provider', None)
        if graph_provider and hasattr(graph_provider, 'get_neighbors'):
            # Try single recursive CTE query (replaces N+1 BFS round-trips)
            try:
                neighbors = await graph_provider.get_neighbors(
                    entity_id=entity_id,
                    direction=direction,
                    depth=depth,
                    project_id=project_id,
                )
                for entity_obj in neighbors[:MAX_TOTAL_ENTITIES]:
                    eid = entity_obj.id if hasattr(entity_obj, 'id') else _get_attr(entity_obj, 'id')
                    if eid and eid not in visited:
                        visited.add(eid)
                        result.add(eid)
                if result:
                    use_bfs = False
                    logger.debug(
                        "CTE traversal: entity_id=%s, direction=%s, depth=%d, found=%d",
                        entity_id, direction, depth, len(result),
                    )
                else:
                    logger.debug(
                        "CTE returned 0 results for entity_id=%s, falling back to BFS",
                        entity_id,
                    )
            except Exception as e:
                logger.warning("CTE traversal failed, falling back to BFS: %s", e)

        if use_bfs:
            # BFS fallback for backends without CTE support
            queue = deque([(entity_id, 0)])
            completed_depth = -1
            current_depth_entities = 0

            while queue:
                if deadline and time.time() >= deadline:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    raise PartialResultsException(
                        partial_results={"entities": result, "completed_depth": completed_depth},
                        elapsed_ms=elapsed_ms,
                    )

                current_id, current_depth = queue.popleft()
                if current_depth > completed_depth:
                    completed_depth = current_depth - 1 if current_depth > 0 else -1
                    current_depth_entities = 0
                if current_depth >= depth:
                    continue
                if len(result) >= MAX_TOTAL_ENTITIES:
                    break

                current_depth_entities += 1
                relationships = []

                if direction in ("incoming", "both"):
                    incoming_rels = await self.db.query_relationships(
                        project_id=project_id,
                        filters={"target_id": current_id},
                        limit=self.config.mcp.query.traversal_limit,
                    )
                    relationships.extend(incoming_rels)
                if direction in ("outgoing", "both"):
                    outgoing_rels = await self.db.query_relationships(
                        project_id=project_id,
                        filters={"source_id": current_id},
                        limit=self.config.mcp.query.traversal_limit,
                    )
                    relationships.extend(outgoing_rels)

                for rel in relationships:
                    if direction == "incoming":
                        next_id = _get_attr(rel, "source_id")
                    elif direction == "outgoing":
                        next_id = _get_attr(rel, "target_id")
                    else:
                        next_id = _get_attr(rel, "source_id") if _get_attr(rel, "target_id") == current_id else _get_attr(rel, "target_id")
                    if not next_id or next_id in visited:
                        continue
                    visited.add(next_id)
                    result.add(next_id)
                    queue.append((next_id, current_depth + 1))

            completed_depth = min(depth, max((d for _, d in [(entity_id, 0)] if result), default=0))

        logger.debug(
            "Traversal complete: entity_id=%s, found=%d entities, completed_depth=%d",
            entity_id,
            len(result),
            completed_depth
        )

        return result, completed_depth
    
    async def _get_entity_references(
        self,
        entity_ids: List[str],
        project_id: str,
        relationship_type: str
    ) -> List[EntityReference]:
        """Get entity references for a list of entity IDs using batched queries.

        Uses configurable batch_size to chunk entity lookups, preventing OOM
        and improving performance through IN clause queries.

        Args:
            entity_ids: List of entity identifiers
            project_id: Project identifier
            relationship_type: Type of relationship

        Returns:
            List of entity references
        """
        if not entity_ids:
            return []

        # Get batch size from config
        batch_size = self.config.mcp.query.batch_size

        references = []

        # Process entity_ids in chunks to prevent OOM
        for i in range(0, len(entity_ids), batch_size):
            chunk = entity_ids[i:i + batch_size]

            # Use IN filter for batch lookup
            entities = await self.db.query_entities(
                project_id=project_id,
                filters={"id": ("IN", chunk)},
                limit=len(chunk)
            )

            # Convert to EntityReference objects
            for entity_data in entities:
                references.append(EntityReference(
                    entity_id=_get_attr(entity_data, "id", ""),
                    name=_get_attr(entity_data, "name", ""),
                    entity_type=_get_attr(entity_data, "type", ""),
                    file_path=_get_attr(entity_data, "file_path", ""),
                    relationship_type=relationship_type
                ))

        return references

    async def build_dependency_tree(
        self,
        entity_id: str,
        entity_name: str,
        entity_type: str,
        file_path: str,
        project_id: str,
        direction: str,
        depth: int,
        visited: Optional[Set[str]] = None
    ) -> DependencyNode:
        """Build a tree structure of dependencies.

        Recursively builds a tree showing the dependency hierarchy.

        Args:
            entity_id: Starting entity identifier
            entity_name: Entity name for the root node
            entity_type: Type of the root entity
            file_path: File path of the root entity
            project_id: Project identifier
            direction: "incoming" (what depends on this) or "outgoing" (what this depends on)
            depth: Maximum depth to traverse
            visited: Set of visited entity IDs to prevent cycles

        Returns:
            DependencyNode representing the dependency tree
        """
        if visited is None:
            visited = set()

        # Create root node
        root = DependencyNode(
            name=entity_name,
            entity_type=entity_type,
            file_path=file_path,
            children=[]
        )

        # Stop if depth exhausted or already visited
        if depth <= 0 or entity_id in visited:
            return root

        visited.add(entity_id)

        # Query relationships based on direction
        relationships = []

        if direction == "incoming":
            # Find entities that depend on this entity
            incoming_rels = await self.db.query_relationships(
                project_id=project_id,
                filters={"target_id": entity_id},
                limit=self.config.mcp.query.tree_limit
            )
            relationships.extend(incoming_rels)
        else:  # outgoing
            # Find entities that this entity depends on
            outgoing_rels = await self.db.query_relationships(
                project_id=project_id,
                filters={"source_id": entity_id},
                limit=self.config.mcp.query.tree_limit
            )
            relationships.extend(outgoing_rels)

        # Build child nodes
        for rel in relationships:
            # Determine the related entity based on direction
            if direction == "incoming":
                related_id = _get_attr(rel, "source_id")
            else:
                related_id = _get_attr(rel, "target_id")

            if not related_id or related_id in visited:
                continue

            # Get entity details
            entities = await self.db.query_entities(
                project_id=project_id,
                filters={"id": related_id},
                limit=1
            )

            if entities:
                entity_data = entities[0]
                # Recursively build subtree
                child_node = await self.build_dependency_tree(
                    entity_id=related_id,
                    entity_name=_get_attr(entity_data, "name", "unknown"),
                    entity_type=_get_attr(entity_data, "type", "unknown"),
                    file_path=_get_attr(entity_data, "file_path", ""),
                    project_id=project_id,
                    direction=direction,
                    depth=depth - 1,
                    visited=visited.copy()  # Copy to allow sibling exploration
                )
                child_node.relationship = _get_attr(rel, "type", "uses")
                # root.children is initialized as [] in DependencyNode constructor
                if root.children is not None:
                    root.children.append(child_node)

        return root
