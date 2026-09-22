"""Relationship resolver service for import target resolution.

This module provides the RelationshipResolver service that resolves import
targets and other relationships using the symbol registry. It implements
multiple resolution strategies with confidence scoring.
"""

import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional, Tuple, Dict, List, Any, TYPE_CHECKING, Set, Union

from agentic_inquiry.constants import CURRENT_PROJECT_ID
from agentic_inquiry.indexing.symbol_registry import SymbolRegistry
from agentic_inquiry.metrics import get_metrics_tracker

if TYPE_CHECKING:
    from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
    from agentic_inquiry.database.lancedb_manager import LanceDBManager


logger = logging.getLogger(__name__)


def _get_entity_attr(entity: Any, attr: str, default: Any = "") -> Any:
    """Safely get attribute from entity (dict or dataclass).

    Handles both dict-style access and dataclass attribute access.

    Args:
        entity: Entity object (dict or dataclass)
        attr: Attribute name to access
        default: Default value if not found

    Returns:
        Attribute value or default
    """
    if isinstance(entity, dict):
        return entity.get(attr, default)
    return getattr(entity, attr, default)


# Common stdlib/builtin modules for cache optimization
COMMON_STDLIB_MODULES: Set[str] = {
    "builtins", "sys", "os", "io", "re", "json", "math", "time",
    "datetime", "collections", "itertools", "functools", "operator",
    "typing", "abc", "copy", "pickle", "pathlib", "shutil",
    "tempfile", "glob", "fnmatch", "stat", "os.path",
    "dataclasses", "enum", "array", "queue", "heapq", "bisect",
    "string", "textwrap", "unicodedata", "codecs",
    "decimal", "fractions", "random", "statistics",
    "asyncio", "concurrent", "threading", "multiprocessing",
    "logging", "warnings", "traceback", "pdb", "unittest",
    "urllib", "http", "email", "html", "xml", "socket", "ssl",
    "csv", "configparser", "zipfile", "tarfile", "gzip", "bz2",
    "hashlib", "secrets", "uuid", "contextlib", "inspect",
    "importlib", "pkgutil", "types", "weakref", "gc",
}


class SimpleCache:
    """Simple LRU cache for relationship resolution.

    Replaces the overcomplicated EnhancedCache with a straightforward
    single-tier LRU cache using OrderedDict.
    """

    def __init__(self, max_size: int = 10000):
        """Initialize cache with max size."""
        self._max_size = max_size
        self._cache: OrderedDict[
            Tuple[str, str, str],  # (target_name, target_type, source_file)
            Optional[Tuple[str, str, float]]  # (file_path, type, confidence)
        ] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(
        self,
        target_name: str,
        target_type: str,
        source_file: str,
    ) -> Tuple[bool, Optional[Tuple[str, str, float]]]:
        """Retrieve from cache.

        Returns:
            Tuple of (found, result)
        """
        key = (target_name, target_type or "", source_file)
        if key in self._cache:
            self._cache.move_to_end(key)  # LRU update
            self._hits += 1
            return True, self._cache[key]
        self._misses += 1
        return False, None

    def put(
        self,
        target_name: str,
        target_type: str,
        source_file: str,
        result: Optional[Tuple[str, str, float]],
    ) -> None:
        """Store in cache with LRU eviction."""
        key = (target_name, target_type or "", source_file)
        self._cache[key] = result
        self._cache.move_to_end(key)

        # Evict oldest entries if over capacity
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def get_statistics(self) -> Dict[str, Any]:
        """Return cache statistics."""
        total = self._hits + self._misses
        return {
            "cache_size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": (self._hits / total * 100) if total > 0 else 0.0,
        }

    def clear(self) -> None:
        """Clear cache and reset statistics."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0


class RelationshipResolver:
    """Resolves import targets and other relationships using symbol registry.
    
    This service extracts the complex resolution logic from IndexingPipeline,
    implementing multiple strategies for resolving import targets with
    confidence scoring. It can also query the database for existing
    relationships to handle re-indexing scenarios.
    
    Resolution Strategies (in order):
    1. Database lookup - Check existing relationships from previous indexing
    2. Direct import path resolution - Use explicit import paths
    3. Exact type match - Match by name and type
    4. Module path resolution - Resolve via module paths
    5. Proximity-based resolution - Score by file proximity
    
    Attributes:
        symbol_registry: Symbol registry for lookups
        project_root: Root directory of the project
        db_manager: Optional database manager for querying existing relationships
    """
    
    def __init__(
        self,
        symbol_registry: SymbolRegistry,
        project_root: str,
        db_manager: Optional[Union["LanceDBManager", "LanceDBAdapter"]] = None,
        cache_max_size: int = 50000,
        skip_database_lookups: bool = False,
        embedding_dimensions: int = 384,
        # Deprecated parameter - kept for backwards compatibility
        enable_cache_prewarming: bool = True,
    ):
        """Initialize the relationship resolver.

        Args:
            symbol_registry: Symbol registry for symbol lookups
            project_root: Root directory of the project
            db_manager: Optional database manager for querying existing relationships
            cache_max_size: Maximum cache size (default: 10000)
            skip_database_lookups: If True, skip expensive database lookups during
                initial indexing and rely on in-memory symbol registry (default: False).
            embedding_dimensions: Embedding vector dimensions (default: 384)
            enable_cache_prewarming: Deprecated, kept for backwards compatibility
        """
        self.symbol_registry = symbol_registry
        self.project_root = Path(project_root)
        self.db_manager = db_manager
        self._skip_database_lookups = skip_database_lookups
        self._embedding_dimensions = embedding_dimensions
        self._metrics = get_metrics_tracker()

        # Simple LRU cache for resolution results
        self._cache = SimpleCache(max_size=cache_max_size)

        # Statistics tracking
        self._stats: Dict[str, Any] = {
            "total_attempts": 0,
            "resolved": 0,
            "unresolved": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "by_strategy": {
                "database": 0,
                "symbol": 0,
                "import_path": 0,
                "exact_match": 0,
                "module_path": 0,
                "proximity": 0,
            }
        }

    async def resolve_import(
        self,
        target_name: str,
        target_type: Optional[str],
        source_file: str,
        source_language: str,
        import_path: Optional[str] = None,
    ) -> Optional[Tuple[str, str, float]]:
        """Resolve an import target to (file_path, type, confidence).

        This is the main entry point for resolution. It checks the cache first,
        then delegates to _resolve_impl() for actual resolution logic.

        Args:
            target_name: Name of the imported symbol
            target_type: Optional type hint (function, class, etc.)
            source_file: File containing the import
            source_language: Programming language of source file
            import_path: Optional explicit import path
        
        Returns:
            Tuple of (target_file_path, target_type, confidence) or None if unresolved
            
        Example:
            >>> await resolver.resolve_import(
            ...     target_name="IndexingPipeline",
            ...     target_type="class",
            ...     source_file="agentic_inquiry/search/service.py",
            ...     source_language="python",
            ...     import_path="agentic_inquiry.indexing.pipeline"
            ... )
            ('agentic_inquiry/indexing/pipeline.py', 'class', 1.0)
        """
        with self._metrics.track_latency("resolver.resolve_import"):
            self._stats["total_attempts"] += 1
            
            # Check cache first (uses EnhancedCache with two-tier lookup)
            target_type_str = target_type or ""
            found, cached_result = self._cache.get(target_name, target_type_str, source_file)
            
            if found:
                self._stats["cache_hits"] += 1
                if cached_result:
                    self._stats["resolved"] += 1
                else:
                    self._stats["unresolved"] += 1
                return cached_result
            
            self._stats["cache_misses"] += 1
            
            # Perform actual resolution
            result = await self._resolve_impl(
                target_name=target_name,
                target_type=target_type,
                source_file=source_file,
                source_language=source_language,
                import_path=import_path,
            )
            
            # Cache the result (EnhancedCache will determine if it's a common import)
            self._cache.put(target_name, target_type_str, source_file, result)
            
            # Update statistics
            if result:
                self._stats["resolved"] += 1
                logger.debug("Resolved %s from %s to %s "
                    "(confidence: %.2f)", target_name, source_file, result[0], result[2])
            else:
                self._stats["unresolved"] += 1
                logger.info("Unresolved relationship target: %s from %s", target_name, source_file)
            
            return result

    async def _resolve_impl(
        self,
        target_name: str,
        target_type: Optional[str],
        source_file: str,
        source_language: str,
        import_path: Optional[str],
    ) -> Optional[Tuple[str, str, float]]:
        """Implementation of resolution logic with multiple strategies.

        Tries multiple resolution strategies in order of confidence:
        1. Database lookup (check existing relationships from previous indexing)
        2. Improved symbol resolution (exact match, fuzzy match, project-aware)
        3. Direct import path resolution (if import_path provided)
        4. Exact type match (name + type)
        5. Module path resolution (for Python imports)
        6. Proximity-based resolution (file location scoring)

        Args:
            target_name: Name of the imported symbol
            target_type: Optional type hint
            source_file: File containing the import
            source_language: Programming language
            import_path: Optional explicit import path

        Returns:
            Tuple of (file_path, type, confidence) or None if unresolved
        """
        # Define strategies in priority order
        strategies: List[Tuple[Callable, str]] = [
            (self._try_database_lookup, "database"),
            (self._try_symbol_resolution, "symbol"),
            (self._try_import_path, "import_path"),
            (self._try_exact_match, "exact_match"),
            (self._try_module_path, "module_path"),
            (self._try_proximity, "proximity"),
        ]

        logger.debug(
            "Attempting to resolve '%s' from '%s' (import_path: %s, type: %s)",
            target_name,
            source_file,
            import_path,
            target_type
        )

        # Try each strategy in order until one succeeds
        for strategy_fn, strategy_name in strategies:
            logger.debug("Trying resolution strategy: %s for '%s'", strategy_name, target_name)
            result = await strategy_fn(
                target_name,
                target_type,
                source_file,
                source_language,
                import_path,
            )
            if result:
                self._stats["by_strategy"][strategy_name] += 1  # type: ignore
                logger.debug(
                    "Successfully resolved '%s' using strategy '%s' -> %s (confidence: %.2f)",
                    target_name,
                    strategy_name,
                    result[0],
                    result[2]
                )
                return result
            else:
                logger.debug("Strategy '%s' failed to resolve '%s'", strategy_name, target_name)

        # Log failure with detailed diagnostics - use warning for visibility
        logger.warning(
            "Failed to resolve '%s' from '%s' after trying all strategies "
            "(import_path: %s, type: %s, language: %s)",
            target_name,
            source_file,
            import_path,
            target_type,
            source_language
        )

        return None

    async def _try_database_lookup(
        self,
        target_name: str,
        target_type: Optional[str],
        source_file: str,
        source_language: str,
        import_path: Optional[str],
    ) -> Optional[Tuple[str, str, float]]:
        """Try to resolve using database lookup for existing relationships.
        
        Queries the database for relationships from the source file to find
        existing resolutions. This is important during re-indexing to maintain
        consistency with previously resolved relationships.
        
        Args:
            target_name: Name of the imported symbol
            target_type: Optional type hint
            source_file: File containing the import
            source_language: Programming language
            import_path: Optional explicit import path
        
        Returns:
            Tuple of (file_path, type, confidence) or None if unresolved
        """
        if not self.db_manager or self._skip_database_lookups:
            return None
        
        try:
            result = await self._resolve_from_database(target_name, source_file)
            if result:
                logger.debug(
                    "Resolved %s via database lookup: %s",
                    target_name,
                    result[0]
                )
            return result
        except Exception as e:
            logger.debug(
                "Database lookup failed for %s: %s",
                target_name,
                e
            )
            return None
    
    async def _try_symbol_resolution(
        self,
        target_name: str,
        target_type: Optional[str],
        source_file: str,
        source_language: str,
        import_path: Optional[str],
    ) -> Optional[Tuple[str, str, float]]:
        """Try to resolve using improved symbol resolution.
        
        Uses the database to query entities by name and import path,
        with project-aware matching for better accuracy.
        
        Args:
            target_name: Name of the imported symbol
            target_type: Optional type hint
            source_file: File containing the import
            source_language: Programming language
            import_path: Optional explicit import path
        
        Returns:
            Tuple of (file_path, type, confidence) or None if unresolved
        """
        if not self.db_manager or self._skip_database_lookups:
            return None
        
        try:
            entity_id = await self._resolve_import_symbol(
                symbol_name=target_name,
                import_path=import_path,
                source_file=source_file,
                project_id=None  # Will use default from db_manager
            )
            if entity_id:
                # Get entity details to return file_path and type
                try:
                    entities = await self.db_manager.query_entities(
                        filters={"id": entity_id},
                        limit=1
                    )
                    # Validate that entities is a proper list
                    if entities and isinstance(entities, list) and len(entities) > 0:
                        entity = entities[0]
                        # Handle both dict and GraphEntity dataclass
                        file_path = _get_entity_attr(entity, "file_path", "")
                        entity_type = _get_entity_attr(entity, "type", target_type or "unknown")
                        # High confidence for improved resolution
                        confidence = 0.9
                        logger.debug(
                            "Resolved %s via improved symbol resolution: %s (type: %s, confidence: %.2f)",
                            target_name,
                            file_path,
                            entity_type,
                            confidence
                        )
                        return (file_path, entity_type, confidence)
                except Exception as e:
                    logger.debug(
                        "Error fetching entity details for %s: %s",
                        entity_id,
                        e
                    )
        except Exception as e:
            logger.debug(
                "Improved symbol resolution failed for %s: %s",
                target_name,
                e
            )
        
        return None
    
    async def _try_import_path(
        self,
        target_name: str,
        target_type: Optional[str],
        source_file: str,
        source_language: str,
        import_path: Optional[str],
    ) -> Optional[Tuple[str, str, float]]:
        """Try to resolve using explicit import path.
        
        Converts import path to file path and looks up the symbol.
        For example: "agentic_inquiry.indexing.pipeline" -> "agentic_inquiry/indexing/pipeline.py"
        
        Args:
            target_name: Name of the imported symbol
            target_type: Optional type hint
            source_file: File containing the import
            source_language: Programming language
            import_path: Optional explicit import path
        
        Returns:
            Tuple of (file_path, type, confidence) or None if unresolved
        """
        if not import_path:
            return None
        
        result = self._resolve_by_import_path(import_path, target_name)
        if result:
            logger.debug(
                "Resolved %s via import path: %s",
                target_name,
                result[0]
            )
        return result
    
    async def _try_exact_match(
        self,
        target_name: str,
        target_type: Optional[str],
        source_file: str,
        source_language: str,
        import_path: Optional[str],
    ) -> Optional[Tuple[str, str, float]]:
        """Try to resolve by exact name and type match.
        
        Looks up symbols by name and type. Returns single match with
        confidence 1.0, or filters by type if multiple matches exist.
        
        Args:
            target_name: Name of the imported symbol
            target_type: Optional type hint
            source_file: File containing the import
            source_language: Programming language
            import_path: Optional explicit import path
        
        Returns:
            Tuple of (file_path, type, confidence) or None if unresolved
        """
        if not target_type:
            return None
        
        result = self._resolve_by_exact_match(target_name, target_type)
        if result:
            logger.debug(
                "Resolved %s via exact match: %s",
                target_name,
                result[0]
            )
        return result
    
    async def _try_module_path(
        self,
        target_name: str,
        target_type: Optional[str],
        source_file: str,
        source_language: str,
        import_path: Optional[str],
    ) -> Optional[Tuple[str, str, float]]:
        """Try to resolve using module path (Python-specific).
        
        Uses the symbol registry's module path index for fast lookup.
        
        Args:
            target_name: Name of the imported symbol
            target_type: Optional type hint
            source_file: File containing the import
            source_language: Programming language
            import_path: Optional explicit import path
        
        Returns:
            Tuple of (file_path, type, confidence) or None if unresolved
        """
        if source_language != "python" or not import_path:
            return None
        
        result = self._resolve_by_module_path(import_path, target_name)
        if result:
            logger.debug(
                "Resolved %s via module path: %s",
                target_name,
                result[0]
            )
        return result
    
    async def _try_proximity(
        self,
        target_name: str,
        target_type: Optional[str],
        source_file: str,
        source_language: str,
        import_path: Optional[str],
    ) -> Optional[Tuple[str, str, float]]:
        """Try to resolve by proximity scoring.
        
        Looks up symbols by name and scores candidates by file proximity.
        Returns best match if confidence >= 0.5.
        
        Args:
            target_name: Name of the imported symbol
            target_type: Optional type hint
            source_file: File containing the import
            source_language: Programming language
            import_path: Optional explicit import path
        
        Returns:
            Tuple of (file_path, type, confidence) or None if unresolved
        """
        result = self._resolve_by_proximity(target_name, source_file)
        if result:
            logger.debug(
                "Resolved %s via proximity: %s",
                target_name,
                result[0]
            )
        return result
    
    async def _resolve_from_database(
        self,
        target_name: str,
        source_file: str,
    ) -> Optional[Tuple[str, str, float]]:
        """Resolve using existing relationships in the database.

        Queries the database for relationships from the source file to find
        existing resolutions. This is important during re-indexing to maintain
        consistency with previously resolved relationships.

        Args:
            target_name: Symbol name to resolve
            source_file: File containing the import

        Returns:
            Tuple of (file_path, type, confidence) or None
        """
        if not self.db_manager:
            return None

        try:
            logger.debug("Database lookup for %s from %s", target_name, source_file)

            # Query graph_relationships table for existing relationships from
            # the same source file to the target name. Uses exact suffix matching
            # instead of LIKE to avoid false positives (e.g., "pipeline.py" matching
            # "test_pipeline.py" with LIKE '%::pipeline.py::%').
            #
            # ID format: "{type}::{project_hash}::{file_path}::{symbol_name}"

            # Build exact suffix patterns for precise matching
            source_suffix = f"::{source_file}::"
            target_suffix = f"::{target_name}"

            results = await self.db_manager.query_raw(
                table_name="graph_relationships",
                filters={
                    "relationship_type": "imports",
                },
                limit=50,
                project_id=CURRENT_PROJECT_ID,
            )

            if not results:
                logger.debug("No import relationships found in database")
                return None

            # Filter with exact substring/suffix matching (no LIKE false positives)
            for relationship in results:
                source_id = relationship.get("source_id", "")
                target_id = relationship.get("target_id", "")

                if source_suffix in source_id and target_id.endswith(target_suffix):
                    try:
                        parts = target_id.split("::")
                        if len(parts) >= 4:
                            target_type = parts[0]
                            target_file = "::".join(parts[2:-1])

                            logger.debug(
                                "Found existing relationship: %s from %s to %s (type: %s)",
                                target_name, source_file, target_file, target_type,
                            )
                            return (target_file, target_type, 1.0)
                    except (IndexError, ValueError) as e:
                        logger.warning("Failed to parse target_id '%s': %s", target_id, e)
                        continue

            logger.debug("No matching relationship found for %s from %s", target_name, source_file)
            return None

        except Exception as e:
            logger.debug("Failed to resolve from database: %s", e)
            return None
    
    def _resolve_by_import_path(
        self,
        import_path: str,
        target_name: str,
    ) -> Optional[Tuple[str, str, float]]:
        """Resolve using explicit import path.
        
        Converts import path to file path and looks up the symbol.
        For example: "agentic_inquiry.indexing.pipeline" -> "agentic_inquiry/indexing/pipeline.py"
        
        Args:
            import_path: Import path (e.g., "package.module")
            target_name: Symbol name to resolve
        
        Returns:
            Tuple of (file_path, type, confidence) or None
        """
        try:
            module_variants = self._module_path_variations(import_path, target_name)
            if not module_variants:
                return None

            symbol_candidates = self.symbol_registry.lookup_by_name(target_name)
            if not symbol_candidates:
                return None

            seen_paths: Set[Tuple[str, ...]] = set()

            for module_variant in module_variants:
                variant_parts = tuple(module_variant.split("."))
                if not variant_parts or variant_parts in seen_paths:
                    continue
                seen_paths.add(variant_parts)

                rel_path = Path(*variant_parts)

                py_path = (self.project_root / rel_path).with_suffix(".py")
                if py_path.exists():
                    resolved = py_path.resolve()
                    for candidate in symbol_candidates:
                        try:
                            if Path(candidate.file_path).resolve() == resolved:
                                return (candidate.file_path, candidate.entity_type, 1.0)
                        except OSError:
                            if Path(candidate.file_path) == resolved:
                                return (candidate.file_path, candidate.entity_type, 1.0)

                init_path = (self.project_root / rel_path / "__init__.py")
                if init_path.exists():
                    resolved = init_path.resolve()
                    for candidate in symbol_candidates:
                        try:
                            if Path(candidate.file_path).resolve() == resolved:
                                return (candidate.file_path, candidate.entity_type, 1.0)
                        except OSError:
                            if Path(candidate.file_path) == resolved:
                                return (candidate.file_path, candidate.entity_type, 1.0)

            return None
        except Exception as e:
            logger.debug("Failed to resolve by import path %s: %s", import_path, e)
            return None
    
    def _resolve_by_module_path(
        self,
        module_path: str,
        target_name: str,
    ) -> Optional[Tuple[str, str, float]]:
        """Resolve using module path lookup in symbol registry.
        
        Uses the symbol registry's module path index for fast lookup.
        
        Args:
            module_path: Module path (e.g., "agentic_inquiry.indexing.pipeline")
            target_name: Symbol name to resolve
        
        Returns:
            Tuple of (file_path, type, confidence) or None
        """
        try:
            module_variants = self._module_path_variations(module_path, target_name)
            if not module_variants:
                return None

            symbol_candidates = self.symbol_registry.lookup_by_name(target_name)
            if not symbol_candidates:
                return None

            for variant in module_variants:
                metadata = self.symbol_registry._module_paths.get(variant)
                if not metadata:
                    continue

                metadata_path = Path(metadata.file_path)
                try:
                    metadata_resolved = metadata_path.resolve()
                except OSError:
                    metadata_resolved = metadata_path

                for candidate in symbol_candidates:
                    candidate_path = Path(candidate.file_path)
                    try:
                        candidate_resolved = candidate_path.resolve()
                    except OSError:
                        candidate_resolved = candidate_path

                    if candidate_resolved == metadata_resolved:
                        return (candidate.file_path, candidate.entity_type, 0.95)

            return None
        except Exception as e:
            logger.debug("Failed to resolve by module path %s: %s", module_path, e)
            return None

    def _module_path_variations(self, raw_path: Optional[str], target_name: str) -> List[str]:
        """Generate possible module path variations for a given import path.
        
        Creates variations by:
        1. Removing target_name from end if present
        2. Generating all suffixes of the path
        
        Args:
            raw_path: Import path (e.g., "agentic_inquiry.search.service")
            target_name: Name of the imported symbol
            
        Returns:
            List of module path variations to try
            
        Example:
            >>> _module_path_variations("agentic_inquiry.search.service", "SearchService")
            ["agentic_inquiry.search.service", "search.service", "service"]
        """
        if not raw_path:
            return []

        parts = [segment for segment in raw_path.split(".") if segment]
        if not parts:
            return []

        sequences: List[List[str]] = []
        if parts[-1] == target_name and len(parts) > 1:
            sequences.append(parts[:-1])
        sequences.append(parts)

        variations: List[str] = []
        seen: Set[str] = set()

        for sequence in sequences:
            if not sequence:
                continue
            for start in range(len(sequence)):
                candidate = ".".join(sequence[start:])
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    variations.append(candidate)

        return variations

    def _resolve_by_exact_match(
        self,
        target_name: str,
        target_type: str,
    ) -> Optional[Tuple[str, str, float]]:
        """Resolve by exact name and type match.
        
        Looks up symbols by name and type. Returns single match with
        confidence 1.0, or filters by type if multiple matches exist.
        
        Args:
            target_name: Symbol name to look up
            target_type: Entity type (class, function, module, etc.)
        
        Returns:
            Tuple of (file_path, type, confidence) or None
        """
        # Look up by name and type
        candidates = self.symbol_registry.lookup_by_name_and_type(
            target_name, target_type
        )
        
        if len(candidates) == 1:
            # Single match - high confidence
            candidate = candidates[0]
            return (candidate.file_path, candidate.entity_type, 1.0)
        
        if len(candidates) > 1:
            # Multiple matches - use additional heuristics
            # Prefer exported symbols
            exported = [c for c in candidates if c.is_exported]
            if len(exported) == 1:
                candidate = exported[0]
                return (candidate.file_path, candidate.entity_type, 0.9)
            
            # Use import frequency if available
            if exported:
                candidates = exported
            
            # Score by import frequency
            scored = []
            for candidate in candidates:
                frequency = self.symbol_registry.get_import_frequency(candidate.name)
                scored.append((candidate, frequency))
            
            scored.sort(key=lambda x: x[1], reverse=True)
            if scored and scored[0][1] > 0:
                candidate = scored[0][0]
                # Confidence based on frequency dominance
                total_freq = sum(s[1] for s in scored)
                confidence = 0.7 + (scored[0][1] / max(total_freq, 1)) * 0.2
                return (candidate.file_path, candidate.entity_type, confidence)
        
        return None

    def _resolve_by_proximity(
        self,
        target_name: str,
        source_file: str,
    ) -> Optional[Tuple[str, str, float]]:
        """Resolve by proximity scoring.
        
        Looks up symbols by name and scores candidates by file proximity.
        Returns best match if confidence >= 0.5.
        
        Args:
            target_name: Symbol name to look up
            source_file: File containing the import
        
        Returns:
            Tuple of (file_path, type, confidence) or None
        """
        candidates = self.symbol_registry.lookup_by_name(target_name)
        
        if not candidates:
            return None
        
        # Score candidates by multiple factors
        scored = []
        for candidate in candidates:
            # Calculate proximity score
            proximity_score = self._calculate_proximity_score(
                source_file, candidate.file_path
            )
            
            # Calculate file naming pattern score
            naming_score = self.symbol_registry.score_file_naming_pattern(
                target_name, candidate.file_path
            )
            
            # Calculate directory structure score
            directory_score = self.symbol_registry.score_directory_structure(
                target_name, candidate.file_path
            )
            
            # Get co-occurrence score
            co_occurrence = self.symbol_registry.get_co_occurrence_score(
                source_file, candidate.file_path
            )
            
            # Get import frequency
            frequency = self.symbol_registry.get_import_frequency(target_name)
            
            # Combine scores with weights
            # Proximity is most important for proximity-based resolution
            combined_score = (
                proximity_score * 0.4 +
                (naming_score / 100.0) * 0.25 +
                (directory_score / 100.0) * 0.15 +
                min(co_occurrence / 10.0, 1.0) * 0.15 +
                min(frequency / 50.0, 1.0) * 0.05
            )
            
            # Boost for exported symbols
            if candidate.is_exported:
                combined_score *= 1.1
            
            scored.append((candidate, combined_score))
        
        # Guard against empty scored list
        if not scored:
            return None
        
        # Sort by score
        scored.sort(key=lambda x: x[1], reverse=True)
        best_candidate, best_score = scored[0]
        
        # Only return if confidence is reasonable
        if best_score < 0.5:
            return None
        
        return (best_candidate.file_path, best_candidate.entity_type, best_score)

    def _calculate_proximity_score(
        self,
        source_file: str,
        target_file: str,
    ) -> float:
        """Calculate proximity score between two files.
        
        Scores based on directory proximity:
        - Same directory: 0.8 score
        - Calculate common path depth for other cases
        - Closer files get higher scores
        
        Args:
            source_file: Source file path
            target_file: Target file path
        
        Returns:
            Proximity score (0.0 to 1.0)
        """
        try:
            source_path = Path(source_file)
            target_path = Path(target_file)
            
            # Same file - shouldn't happen but handle it
            if source_path.resolve() == target_path.resolve():
                return 1.0
            
            # Same directory: high score
            if source_path.parent == target_path.parent:
                return 0.8
            
            # Calculate common path depth
            try:
                common = Path(os.path.commonpath([source_file, target_file]))
                source_depth = len(source_path.relative_to(common).parts)
                target_depth = len(target_path.relative_to(common).parts)
                total_depth = source_depth + target_depth
                
                # Closer files get higher scores
                # Depth 2 (one level apart) = 0.7
                # Depth 3 = 0.6, Depth 4 = 0.5, etc.
                score = max(0.3, 1.0 - (total_depth * 0.1))
                return score
            except ValueError:
                # No common path (different drives on Windows, etc.)
                return 0.3
        except Exception as e:
            logger.debug("Failed to calculate proximity score between "
                "%s and %s: %s", source_file, target_file, e)
            return 0.3

    def _import_path_to_file_path(self, import_path: str, target_name: str) -> List[str]:
        """Convert Python import path to possible file paths.
        
        Handles various import patterns and returns multiple candidates.
        
        Args:
            import_path: Python import path (e.g., "agentic_inquiry.search.service")
            target_name: Name of the imported symbol
        
        Returns:
            List of possible file paths to check
        
        Examples:
            "agentic_inquiry.search.service" -> [
                "agentic_inquiry/search/service.py",
                "agentic_inquiry/search/service/__init__.py"
            ]
        """
        candidates = []
        
        # Convert dots to path separators
        parts = import_path.split(".")
        base_path = "/".join(parts)
        
        # Try as module file
        candidates.append(f"{base_path}.py")
        
        # Try as package __init__
        candidates.append(f"{base_path}/__init__.py")
        
        # Try with target name appended (for "from X import Y" style)
        if target_name and target_name not in parts:
            candidates.append(f"{base_path}/{target_name}.py")
        
        # Try relative to project root
        for candidate in list(candidates):
            if not candidate.startswith(str(self.project_root)):
                candidates.append(str(self.project_root / candidate))
        
        return candidates

    def _extract_project_from_path(self, file_path: str) -> str:
        """Extract project/package name from file path.
        
        Args:
            file_path: File path to extract from
        
        Returns:
            Project name (first directory component)
        """
        parts = Path(file_path).parts
        if parts:
            return parts[0]
        return ""

    async def _resolve_import_symbol(
        self,
        symbol_name: str,
        import_path: Optional[str] = None,
        source_file: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve imported symbol to entity ID using multiple strategies.
        
        This is the improved resolution method that tries multiple strategies:
        1. Exact match by name and file path (using import path)
        2. Fuzzy match by name only
        3. Project-aware match (prefer same project)
        
        Args:
            symbol_name: Name of the symbol to resolve
            import_path: Optional import path (e.g., "agentic_inquiry.search.service")
            source_file: Optional source file containing the import
            project_id: Optional project ID for filtering
        
        Returns:
            Entity ID if resolved, None otherwise
        """
        # Strategy 1: Exact match with import path
        if import_path and self.db_manager:
            # Convert import path to file paths
            file_path_candidates = self._import_path_to_file_path(import_path, symbol_name)
            
            for file_path in file_path_candidates:
                try:
                    entities = await self.db_manager.query_entities(
                        filters={
                            "name": symbol_name,
                            "file_path": file_path
                        },
                        limit=1,
                        project_id=project_id
                    )
                    if entities:
                        logger.debug(
                            "Resolved %s via exact match in %s",
                            symbol_name,
                            file_path
                        )
                        self._stats["by_strategy"]["exact_match"] += 1
                        return _get_entity_attr(entities[0], "id")
                except Exception as e:
                    logger.debug(
                        "Error querying entities for %s in %s: %s",
                        symbol_name,
                        file_path,
                        e
                    )

        # Strategy 2: Fuzzy match by name
        if self.db_manager:
            try:
                entities = await self.db_manager.query_entities(
                    filters={"name": symbol_name},
                    limit=10,
                    project_id=project_id
                )

                if not entities:
                    logger.debug("No entities found for symbol: %s", symbol_name)
                    return None

                # Strategy 3: If multiple matches, prefer same project
                if len(entities) > 1 and source_file:
                    source_project = self._extract_project_from_path(source_file)
                    for entity in entities:
                        entity_project = self._extract_project_from_path(
                            _get_entity_attr(entity, "file_path", "")
                        )
                        if entity_project == source_project:
                            entity_id = _get_entity_attr(entity, "id")
                            logger.debug(
                                "Resolved %s via project match: %s",
                                symbol_name,
                                entity_id
                            )
                            self._stats["by_strategy"]["proximity"] += 1
                            return entity_id

                # Return first match
                first_entity_id = _get_entity_attr(entities[0], "id")
                logger.debug(
                    "Resolved %s via fuzzy match: %s",
                    symbol_name,
                    first_entity_id
                )
                self._stats["by_strategy"]["proximity"] += 1
                return first_entity_id
            except Exception as e:
                logger.error(
                    "Error during fuzzy match for %s: %s",
                    symbol_name,
                    e
                )
        
        return None

    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate as a percentage.
        
        Returns:
            Cache hit rate (0.0 to 100.0)
        """
        total_cache_accesses = self._stats["cache_hits"] + self._stats["cache_misses"]
        if total_cache_accesses == 0:
            return 0.0
        return (self._stats["cache_hits"] / total_cache_accesses) * 100.0
    
    def get_resolution_stats(self) -> Dict[str, Any]:
        """Get resolution statistics.

        Returns:
            Dictionary containing:
            - cache_size: Total cache entries
            - cache_hits: Number of cache hits
            - cache_misses: Number of cache misses
            - cache_hit_rate: Percentage of cache hits
            - total_attempts: Total resolution attempts
            - resolved: Number of successful resolutions
            - unresolved: Number of failed resolutions
            - resolution_rate: Percentage of successful resolutions
            - by_strategy: Breakdown of resolutions by strategy
        """
        total = self._stats["total_attempts"]
        resolved = self._stats["resolved"]
        resolution_rate = (resolved / total * 100) if total > 0 else 0.0

        cache_stats = self._cache.get_statistics()

        return {
            "cache_size": cache_stats["cache_size"],
            "cache_hits": self._stats["cache_hits"],
            "cache_misses": self._stats["cache_misses"],
            "cache_hit_rate": self.cache_hit_rate,
            "total_attempts": total,
            "resolved": resolved,
            "unresolved": self._stats["unresolved"],
            "resolution_rate": resolution_rate,
            "by_strategy": self._stats["by_strategy"].copy(),
        }
    
    def clear_cache(self) -> None:
        """Clear the resolution cache."""
        self._cache.clear()
        logger.debug("Resolution cache cleared")
