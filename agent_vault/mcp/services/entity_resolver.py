"""Entity resolver service for knowledge graph entity resolution.

This module provides the EntityResolver service that resolves entity names
to their definitions in the knowledge graph using multiple fallback strategies.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging
import re
from difflib import SequenceMatcher

from agent_vault.config import Config
from agent_vault.storage.facade import StorageFacade
from agent_vault.utils import get_attr as _get_attr

logger = logging.getLogger(__name__)


@dataclass
class EntityDefinition:
    """Complete entity information.
    
    Attributes:
        entity_id: Unique identifier
        name: Entity name
        entity_type: Type of entity (class, function, method, etc.)
        file_path: Path to file containing entity
        line_start: Starting line number
        line_end: Ending line number
        content: Entity content/code
        docstring: Entity documentation
        metadata: Additional metadata
    """
    entity_id: str
    name: str
    entity_type: str
    file_path: str
    line_start: int
    line_end: int
    content: str
    docstring: Optional[str]
    metadata: Dict[str, Any]


@dataclass
class EntityReference:
    """Reference to an entity.
    
    Attributes:
        entity_id: Unique identifier
        name: Entity name
        entity_type: Type of entity
        file_path: Path to file containing entity
        relationship_type: Type of relationship (imports, calls, inherits, etc.)
    """
    entity_id: str
    name: str
    entity_type: str
    file_path: str
    relationship_type: str


@dataclass
class UsageExample:
    """Example of where an entity is used.
    
    Attributes:
        file_path: Path to file containing usage
        line_number: Line number of usage
        context: Code context around usage
        usage_type: Type of usage (call, import, reference, etc.)
    """
    file_path: str
    line_number: int
    context: str
    usage_type: str


class EntityNotFoundError(Exception):
    """Raised when entity cannot be resolved.
    
    Attributes:
        entity_name: Name of entity that was not found
        suggestions: List of suggested entity names
    """
    
    def __init__(self, entity_name: str, suggestions: List[str]):
        self.entity_name = entity_name
        self.suggestions = suggestions
        message = f"Entity '{entity_name}' not found."
        if suggestions:
            message += f" Did you mean: {', '.join(suggestions[:3])}?"
        super().__init__(message)


class EntityResolver:
    """Resolves entity names to their definitions in the knowledge graph.

    Uses multiple fallback resolution strategies:
    1. Exact case-insensitive match on simple name
    2. CamelCase expansion match (e.g., "SearchService" -> "Search Service")
    3. Case-insensitive match
    4. Module path match (e.g., "SearchService" -> "module.SearchService")
    5. Fuzzy match with similarity threshold

    Supports caching of resolved entities per session for performance.
    """

    def __init__(
        self,
        db_manager: StorageFacade,
        config: Config
    ):
        """Initialize entity resolver.

        Args:
            db_manager: StorageFacade instance providing unified storage access
            config: Configuration object
        """
        # Use StorageFacade directly - it provides query_entities and query_relationships
        # methods that work across all backends (LanceDB, PostgreSQL, etc.)
        self.db = db_manager
        logger.debug("EntityResolver initialized with StorageFacade")

        self.config = config
        self._cache: Dict[str, Optional[EntityDefinition]] = {}
    
    async def resolve_entity(
        self,
        entity_name: str,
        project_id: str,
        entity_type: Optional[str] = None,
        include_relationships: bool = True
    ) -> Optional[EntityDefinition]:
        """Resolve entity by name with fallback strategies.
        
        Resolution order:
        1. Exact match on simple name
        2. CamelCase expansion match (e.g., "SearchService" -> "Search Service")
        3. Case-insensitive match
        4. Module path match (e.g., "SearchService" -> "module.SearchService")
        5. Fuzzy match with similarity threshold
        
        Args:
            entity_name: Name of entity to resolve
            project_id: Project identifier
            entity_type: Optional entity type filter
            include_relationships: Whether to include relationship data
        
        Returns:
            EntityDefinition if found, None otherwise
            
        Raises:
            EntityNotFoundError: If entity not found after all strategies
        """
        # Check cache first
        from agent_vault.models.graph_entity import EntityType
        entity_type = EntityType.normalize(entity_type) if entity_type else None
        
        cache_key = f"{project_id}:{entity_name}:{entity_type}"
        if self.config.entity_resolution.cache_enabled and cache_key in self._cache:
            logger.debug("Entity resolution cache hit: %s", cache_key)
            return self._cache[cache_key]
        
        logger.debug(
            "Resolving entity: name=%s, project_id=%s, entity_type=%s",
            entity_name,
            project_id,
            entity_type
        )
        
        # Strategy 1: Exact case-insensitive match
        entity = await self._exact_match(entity_name, project_id, entity_type)
        if entity:
            logger.debug("Entity resolved via exact match: %s", entity_name)
            if self.config.entity_resolution.cache_enabled:
                self._cache[cache_key] = entity
            return entity
        
        # Strategy 2: CamelCase expansion match (e.g., "SearchService" -> "Search Service")
        entity = await self._camelcase_match(entity_name, project_id, entity_type)
        if entity:
            logger.debug("Entity resolved via CamelCase match: %s", entity_name)
            if self.config.entity_resolution.cache_enabled:
                self._cache[cache_key] = entity
            return entity

        # Strategy 3: Case-insensitive LIKE query
        if self.config.entity_resolution.case_insensitive:
            entity = await self._case_insensitive_match(entity_name, project_id, entity_type)
            if entity:
                logger.debug("Entity resolved via case-insensitive match: %s", entity_name)
                if self.config.entity_resolution.cache_enabled:
                    self._cache[cache_key] = entity
                return entity

        # Strategy 4: Module path match (e.g., "SearchService" -> "mymodule.SearchService")
        entity = await self._module_path_match(entity_name, project_id, entity_type)
        if entity:
            logger.debug("Entity resolved via module path match: %s", entity_name)
            if self.config.entity_resolution.cache_enabled:
                self._cache[cache_key] = entity
            return entity

        # Strategy 5: Fuzzy match
        if self.config.entity_resolution.fuzzy_matching.enabled:
            entity = await self._fuzzy_match(entity_name, project_id, entity_type)
            if entity:
                logger.debug("Entity resolved via fuzzy match: %s", entity_name)
                if self.config.entity_resolution.cache_enabled:
                    self._cache[cache_key] = entity
                return entity
        
        # No match found - get suggestions
        suggestions = await self._get_suggestions(entity_name, project_id, entity_type)
        logger.warning(
            "Entity '%s' not found. Available entities: %s",
            entity_name,
            suggestions[:10]
        )
        
        raise EntityNotFoundError(entity_name, suggestions)
    
    async def _exact_match(
        self,
        entity_name: str,
        project_id: str,
        entity_type: Optional[str] = None
    ) -> Optional[EntityDefinition]:
        """Try exact name match with preference for internal entities.

        When no entity_type is specified, fetches multiple results and
        prioritizes internal code entities over external ones.

        Args:
            entity_name: Name to match
            project_id: Project identifier
            entity_type: Optional entity type filter

        Returns:
            EntityDefinition if found, None otherwise
        """
        from agent_vault.models.graph_entity import EntityType

        filters = {"name": entity_name}
        if entity_type:
            filters["type"] = entity_type

        # Fetch multiple results when no type filter, to enable prioritization
        limit = 1 if entity_type else 10

        results = await self.db.query_entities(
            project_id=project_id,
            filters=filters,
            limit=limit
        )

        if not results:
            return None

        # If specific type requested or only one result, return it
        if entity_type or len(results) == 1:
            return self._entity_to_definition(results[0])

        # Prioritize internal code entities over external ones
        preferred_types = [
            EntityType.CODE_CLASS.value,
            EntityType.CODE_FUNCTION.value,
            EntityType.CODE_METHOD.value,
            EntityType.CODE_MODULE.value,
            EntityType.CODE_VARIABLE.value,
            EntityType.CODE_INTERFACE.value,
            EntityType.CODE_ENUM.value,
            EntityType.CODE_STRUCT.value,
        ]

        for result in results:
            result_type = _get_attr(result, "type", "")
            if result_type in preferred_types:
                logger.debug(
                    "Prioritized internal entity type '%s' for name '%s'",
                    result_type,
                    entity_name
                )
                return self._entity_to_definition(result)

        # Fallback to first result if no preferred type found
        logger.debug(
            "No preferred entity type found for '%s', falling back to first result",
            entity_name
        )
        return self._entity_to_definition(results[0])
    
    async def _case_insensitive_match(
        self,
        entity_name: str,
        project_id: str,
        entity_type: Optional[str] = None
    ) -> Optional[EntityDefinition]:
        """Try case-insensitive match with preference for internal entities.

        Args:
            entity_name: Name to match
            project_id: Project identifier
            entity_type: Optional entity type filter

        Returns:
            EntityDefinition if found, None otherwise
        """
        from agent_vault.models.graph_entity import EntityType

        # Get all entities and filter in Python (LanceDB doesn't support case-insensitive LIKE)
        filters = {}
        if entity_type:
            filters["type"] = entity_type

        results = await self.db.query_entities(
            project_id=project_id,
            filters=filters,
            limit=self.config.mcp.query.default_limit
        )

        # Case-insensitive comparison - collect all matches
        entity_name_lower = entity_name.lower()
        matches = [r for r in results if _get_attr(r, "name", "").lower() == entity_name_lower]

        if not matches:
            return None

        # If specific type requested or only one match, return it
        if entity_type or len(matches) == 1:
            return self._entity_to_definition(matches[0])

        # Prioritize internal code entities over external ones
        preferred_types = [
            EntityType.CODE_CLASS.value,
            EntityType.CODE_FUNCTION.value,
            EntityType.CODE_METHOD.value,
            EntityType.CODE_MODULE.value,
            EntityType.CODE_VARIABLE.value,
            EntityType.CODE_INTERFACE.value,
            EntityType.CODE_ENUM.value,
            EntityType.CODE_STRUCT.value,
        ]

        for match in matches:
            match_type = _get_attr(match, "type", "")
            if match_type in preferred_types:
                logger.debug(
                    "Prioritized internal entity type '%s' for name '%s' (case-insensitive)",
                    match_type,
                    entity_name
                )
                return self._entity_to_definition(match)

        # Fallback to first match
        return self._entity_to_definition(matches[0])
    
    @staticmethod
    def _expand_camelcase(name: str) -> list[str]:
        """Split a CamelCase name into its component words.

        Handles standard CamelCase (SearchService -> [Search, Service]) and
        acronym runs (HTTPServer -> [HTTP, Server]).

        Args:
            name: Name to split (e.g., "SearchService", "HTTPServer")

        Returns:
            List of word parts. Single-word names return a one-element list.
        """
        # Insert space before uppercase letters preceded by lowercase
        parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
        # Insert space between acronym runs and the next word
        parts = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', parts)
        return parts.split()

    async def _camelcase_match(
        self,
        entity_name: str,
        project_id: str,
        entity_type: Optional[str] = None,
    ) -> Optional[EntityDefinition]:
        """Match entity by expanding CamelCase into word patterns.

        Splits "SearchService" into ["Search", "Service"] and builds an
        ILIKE pattern '%Search%Service%' to find entities stored with
        spaces or different casing.

        Args:
            entity_name: CamelCase name to match (e.g., "SearchService")
            project_id: Project identifier
            entity_type: Optional entity type filter

        Returns:
            EntityDefinition if a match is found, None otherwise
        """
        from agent_vault.models.graph_entity import EntityType

        words = self._expand_camelcase(entity_name)

        # Skip if name is a single word (no CamelCase to expand)
        if len(words) <= 1:
            return None

        # Build ILIKE pattern: '%Search%Service%'
        pattern = "%" + "%".join(words) + "%"
        logger.debug("CamelCase ILIKE pattern for '%s': %s", entity_name, pattern)

        filters: Dict[str, Any] = {"name": ("ILIKE", pattern)}
        if entity_type:
            filters["type"] = entity_type

        results = await self.db.query_entities(
            project_id=project_id,
            filters=filters,
            limit=20,
        )

        if not results:
            return None

        # Tie-breaking: prefer exact word-count match > type priority > shortest name
        preferred_types = [
            EntityType.CODE_CLASS.value,
            EntityType.CODE_FUNCTION.value,
            EntityType.CODE_METHOD.value,
            EntityType.CODE_MODULE.value,
            EntityType.CODE_VARIABLE.value,
            EntityType.CODE_INTERFACE.value,
            EntityType.CODE_ENUM.value,
            EntityType.CODE_STRUCT.value,
        ]

        word_count = len(words)

        def _sort_key(r: Any) -> tuple[int, int, int, str]:
            r_name = _get_attr(r, "name", "")
            r_type = _get_attr(r, "type", "")
            # Exact word count match scores 0, otherwise 1
            name_word_count = len(r_name.split())
            word_match = 0 if name_word_count == word_count else 1
            # Type priority (lower is better)
            type_prio = preferred_types.index(r_type) if r_type in preferred_types else len(preferred_types)
            return (word_match, type_prio, len(r_name), r_name)

        results.sort(key=_sort_key)
        best = results[0]
        logger.debug(
            "CamelCase match found: '%s' -> '%s'",
            entity_name,
            _get_attr(best, "name"),
        )
        return self._entity_to_definition(best)

    async def _module_path_match(
        self,
        entity_name: str,
        project_id: str,
        entity_type: Optional[str] = None,
    ) -> Optional[EntityDefinition]:
        """Match entity by qualified name suffix.

        Queries for entities whose qualified_name ends with the given name,
        e.g., "SearchService" matches "agent_vault.search.service.SearchService".

        Args:
            entity_name: Simple name to match as a suffix of qualified_name
            project_id: Project identifier
            entity_type: Optional entity type filter

        Returns:
            EntityDefinition if a match is found, None otherwise
        """
        from agent_vault.models.graph_entity import EntityType

        # Build ILIKE pattern for qualified name suffix
        pattern = f"%.{entity_name}"
        logger.debug("Module path ILIKE pattern for '%s': %s", entity_name, pattern)

        filters: Dict[str, Any] = {"qualified_name": ("ILIKE", pattern)}
        if entity_type:
            filters["type"] = entity_type

        results = await self.db.query_entities(
            project_id=project_id,
            filters=filters,
            limit=10,
        )

        if not results:
            return None

        # Prefer internal code entities
        preferred_types = [
            EntityType.CODE_CLASS.value,
            EntityType.CODE_FUNCTION.value,
            EntityType.CODE_METHOD.value,
            EntityType.CODE_MODULE.value,
            EntityType.CODE_VARIABLE.value,
            EntityType.CODE_INTERFACE.value,
            EntityType.CODE_ENUM.value,
            EntityType.CODE_STRUCT.value,
        ]

        for result in results:
            r_type = _get_attr(result, "type", "")
            if r_type in preferred_types:
                logger.debug(
                    "Module path match found: '%s' -> '%s' (type=%s)",
                    entity_name,
                    _get_attr(result, "qualified_name", _get_attr(result, "name", "")),
                    r_type,
                )
                return self._entity_to_definition(result)

        # Fallback to first result
        return self._entity_to_definition(results[0])

    async def _fuzzy_match(
        self,
        entity_name: str,
        project_id: str,
        entity_type: Optional[str] = None
    ) -> Optional[EntityDefinition]:
        """Try fuzzy match with similarity threshold.
        
        Args:
            entity_name: Name to match
            project_id: Project identifier
            entity_type: Optional entity type filter
        
        Returns:
            EntityDefinition if found, None otherwise
        """
        filters = {}
        if entity_type:
            filters["type"] = entity_type
        
        results = await self.db.query_entities(
            project_id=project_id,
            filters=filters,
            limit=self.config.mcp.query.default_limit
        )

        # Calculate similarity scores
        threshold = self.config.entity_resolution.fuzzy_matching.threshold
        best_match = None
        best_score = 0.0
        
        for result in results:
            name = _get_attr(result, "name", "")
            score = SequenceMatcher(None, entity_name.lower(), name.lower()).ratio()
            if score > best_score and score >= threshold:
                best_score = score
                best_match = result

        if best_match:
            logger.debug(
                "Fuzzy match found: %s -> %s (score: %.2f)",
                entity_name,
                _get_attr(best_match, "name"),
                best_score
            )
            return self._entity_to_definition(best_match)
        
        return None
    
    async def _get_suggestions(
        self,
        entity_name: str,
        project_id: str,
        entity_type: Optional[str] = None,
        limit: int = 10
    ) -> List[str]:
        """Get entity name suggestions for failed lookup.
        
        Args:
            entity_name: Name that was not found
            project_id: Project identifier
            entity_type: Optional entity type filter
            limit: Maximum number of suggestions
        
        Returns:
            List of suggested entity names
        """
        filters = {}
        if entity_type:
            filters["type"] = entity_type
        
        results = await self.db.query_entities(
            project_id=project_id,
            filters=filters,
            limit=self.config.mcp.query.traversal_limit
        )

        # Calculate similarity scores for suggestions
        suggestions = []
        for result in results:
            name = _get_attr(result, "name", "")
            score = SequenceMatcher(None, entity_name.lower(), name.lower()).ratio()
            suggestions.append((name, score))
        
        # Sort by similarity and return top N
        suggestions.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in suggestions[:limit]]
    
    def _entity_to_definition(self, entity_data: Any) -> EntityDefinition:
        """Convert entity data to EntityDefinition.

        Args:
            entity_data: Raw entity data from database (dict or dataclass)

        Returns:
            EntityDefinition instance
        """
        return EntityDefinition(
            entity_id=_get_attr(entity_data, "id", ""),
            name=_get_attr(entity_data, "name", ""),
            entity_type=_get_attr(entity_data, "type", ""),
            file_path=_get_attr(entity_data, "file_path", ""),
            line_start=_get_attr(entity_data, "line_start", -1),
            line_end=_get_attr(entity_data, "line_end", -1),
            content="",  # Will be populated by caller if needed
            docstring=None,
            metadata=entity_data if isinstance(entity_data, dict) else vars(entity_data) if hasattr(entity_data, '__dict__') else {}
        )
    
    async def get_entity_dependencies(
        self,
        entity_id: str,
        project_id: str,
        depth: int = 1
    ) -> List[EntityReference]:
        """Get entities that this entity depends on.
        
        Args:
            entity_id: Entity identifier
            project_id: Project identifier
            depth: Traversal depth (1 = direct dependencies only)
        
        Returns:
            List of entity references
        """
        logger.debug(
            "Getting dependencies: entity_id=%s, project_id=%s, depth=%d",
            entity_id,
            project_id,
            depth
        )
        
        # Query outgoing relationships (this entity -> others)
        relationships = await self.db.query_relationships(
            project_id=project_id,
            filters={"source_id": entity_id},
            limit=self.config.mcp.query.traversal_limit
        )

        dependencies = []
        seen_ids: set[str] = set()
        for rel in relationships:
            target_id = _get_attr(rel, "target_id")
            if not target_id:
                continue

            # Get target entity details
            target_entities = await self.db.query_entities(
                project_id=project_id,
                filters={"id": target_id},
                limit=1
            )

            if target_entities:
                target = target_entities[0]
                ref_id = _get_attr(target, "id", "")
                seen_ids.add(ref_id)
                dependencies.append(EntityReference(
                    entity_id=ref_id,
                    name=_get_attr(target, "name", ""),
                    entity_type=_get_attr(target, "type", ""),
                    file_path=_get_attr(target, "file_path", ""),
                    relationship_type=_get_attr(rel, "type", "")
                ))

        # Also query incoming structural relationships (others -> this entity)
        # for document entities where contains/follows are directional
        # (parent contains child, sibling follows sibling)
        _STRUCTURAL_TYPES = frozenset({
            "contains", "contained_in", "follows", "precedes",
        })
        incoming_rels = await self.db.query_relationships(
            project_id=project_id,
            filters={"target_id": entity_id},
            limit=self.config.mcp.query.traversal_limit
        )
        for rel in incoming_rels:
            rel_type = _get_attr(rel, "type", "")
            if rel_type not in _STRUCTURAL_TYPES:
                continue
            source_id = _get_attr(rel, "source_id")
            if not source_id or source_id in seen_ids:
                continue

            source_entities = await self.db.query_entities(
                project_id=project_id,
                filters={"id": source_id},
                limit=1
            )
            if source_entities:
                source = source_entities[0]
                ref_id = _get_attr(source, "id", "")
                seen_ids.add(ref_id)
                dependencies.append(EntityReference(
                    entity_id=ref_id,
                    name=_get_attr(source, "name", ""),
                    entity_type=_get_attr(source, "type", ""),
                    file_path=_get_attr(source, "file_path", ""),
                    relationship_type=rel_type
                ))
        
        # Filter out Python stdlib/builtin modules from import dependencies.
        # These add noise to blast radius analysis without actionable insight.
        _STDLIB_PREFIXES = frozenset({
            "os", "sys", "re", "io", "abc", "ast", "csv", "json", "math",
            "time", "uuid", "copy", "enum", "gzip", "html", "http",
            "email", "queue", "shutil", "signal", "socket", "sqlite3",
            "string", "struct", "typing", "urllib", "logging", "pathlib",
            "hashlib", "inspect", "asyncio", "datetime", "functools",
            "itertools", "importlib", "collections", "contextlib",
            "dataclasses", "multiprocessing", "concurrent", "unittest",
            "warnings", "textwrap", "tempfile", "threading", "traceback",
            "configparser", "argparse", "platform", "operator", "pickle",
            "pprint", "random", "secrets", "statistics", "subprocess",
        })
        pre_filter = len(dependencies)
        dependencies = [
            d for d in dependencies
            if not (
                d.file_path.startswith("builtin://")
                or d.file_path.startswith("external://")
                or (d.relationship_type == "imports" and d.name.split(".")[0] in _STDLIB_PREFIXES)
            )
        ]
        if pre_filter != len(dependencies):
            logger.debug(
                "Filtered %d stdlib/builtin dependencies for entity %s",
                pre_filter - len(dependencies), entity_id,
            )

        # Sort dependencies by relationship type priority:
        # imports/calls are more useful than contains/follows for understanding
        # what an entity depends on.
        type_priority = {
            "imports": 0,
            "calls": 1,
            "inherits": 2,
            "defines": 3,
            "contains": 4,
            "follows": 5,
        }
        dependencies.sort(
            key=lambda d: type_priority.get(d.relationship_type, 3)
        )

        logger.debug("Found %d dependencies for entity %s", len(dependencies), entity_id)
        return dependencies
    
    async def get_entity_usages(
        self,
        entity_id: str,
        project_id: str,
        limit: int = 10
    ) -> List[UsageExample]:
        """Get examples of where this entity is used.
        
        Args:
            entity_id: Entity identifier
            project_id: Project identifier
            limit: Maximum number of usage examples
        
        Returns:
            List of usage examples
        """
        logger.debug(
            "Getting usages: entity_id=%s, project_id=%s, limit=%d",
            entity_id,
            project_id,
            limit
        )
        
        # Query incoming relationships (others -> this entity)
        relationships = await self.db.query_relationships(
            project_id=project_id,
            filters={"target_id": entity_id},
            limit=limit
        )
        
        usages = []
        for rel in relationships:
            source_id = _get_attr(rel, "source_id")
            if not source_id:
                continue

            # Get source entity details
            source_entities = await self.db.query_entities(
                project_id=project_id,
                filters={"id": source_id},
                limit=1
            )

            if source_entities:
                source = source_entities[0]
                usages.append(UsageExample(
                    file_path=_get_attr(source, "file_path", ""),
                    line_number=_get_attr(source, "line_start", -1),
                    context=f"{_get_attr(source, 'name', '')} {_get_attr(rel, 'type', '')} entity",
                    usage_type=_get_attr(rel, "type", "")
                ))
        
        logger.debug("Found %d usages for entity %s", len(usages), entity_id)
        return usages
