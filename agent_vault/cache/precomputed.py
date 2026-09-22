"""Pre-computed cache for fast query responses.

Pre-computes expensive queries at index time and stores results
for <100ms retrieval. Supports incremental updates on file changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from agent_vault.storage.facade import StorageFacade

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached query result."""

    key: str
    query_type: str  # symbol_deps, lineage_paths, impact_graph, service_map
    data: Any
    entity_ids: List[str] = field(default_factory=list)  # Affected entities
    file_paths: List[str] = field(default_factory=list)  # Affected files
    created_at: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int = 3600  # 1 hour default TTL
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        age = (datetime.utcnow() - self.created_at).total_seconds()
        return age > self.ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "key": self.key,
            "query_type": self.query_type,
            "data": json.dumps(self.data) if not isinstance(self.data, str) else self.data,
            "entity_ids": self.entity_ids,
            "file_paths": self.file_paths,
            "created_at": self.created_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "hit_count": self.hit_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheEntry":
        """Create from dictionary."""
        cache_data = data.get("data", {})
        if isinstance(cache_data, str):
            try:
                cache_data = json.loads(cache_data)
            except json.JSONDecodeError:
                pass

        return cls(
            key=data.get("key", ""),
            query_type=data.get("query_type", ""),
            data=cache_data,
            entity_ids=data.get("entity_ids", []),
            file_paths=data.get("file_paths", []),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at") else datetime.utcnow(),
            ttl_seconds=data.get("ttl_seconds", 3600),
            hit_count=data.get("hit_count", 0),
        )


class PrecomputedCache:
    """Pre-computed cache for expensive queries.

    Stores pre-computed results for:
    - symbol_deps: Dependencies for each symbol
    - file_refs: Symbols per file with aggregates
    - def_lookup: Symbol name → file:line index
    - call_chain: Transitive dependency graph
    - lineage_paths: Pre-traced lineage from UI to DB
    - impact_graph: Reverse lineage for each entity
    - service_map: Detected architecture

    Target: <100ms retrieval for all queries.
    """

    QUERY_TYPES = {
        "symbol_deps": "Dependencies for each symbol",
        "file_refs": "Symbols per file with aggregates",
        "def_lookup": "Symbol name → file:line index",
        "call_chain": "Transitive dependency graph",
        "lineage_paths": "Pre-traced lineage from UI to DB",
        "impact_graph": "Reverse lineage for each entity",
        "service_map": "Detected architecture",
    }

    def __init__(
        self,
        storage: Optional["StorageFacade"] = None,
        project_id: Optional[str] = None,
        cache_dir: Optional[Path] = None,
    ):
        """Initialize cache.

        Args:
            storage: Optional storage facade for persistence
            project_id: Project ID for scoping
            cache_dir: Optional directory for file-based cache
        """
        self._storage = storage
        self._project_id = project_id
        self._cache_dir = cache_dir
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._stats = {"hits": 0, "misses": 0, "stores": 0}

    async def get(
        self,
        query_type: str,
        key: str,
        default: Any = None,
    ) -> Any:
        """Get cached result.

        Args:
            query_type: Type of query (symbol_deps, lineage_paths, etc.)
            key: Cache key (usually entity ID or file path)
            default: Default value if not found

        Returns:
            Cached data or default
        """
        cache_key = self._make_key(query_type, key)
        start_time = time.perf_counter()

        # Try memory cache first
        entry = self._memory_cache.get(cache_key)
        if entry and not entry.is_expired:
            entry.hit_count += 1
            self._stats["hits"] += 1
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.debug("Cache HIT (memory) for %s in %.1fms", cache_key, elapsed)
            return entry.data

        # Try file cache
        if self._cache_dir:
            cache_file = self._cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                try:
                    data = json.loads(cache_file.read_text())
                    entry = CacheEntry.from_dict(data)
                    if not entry.is_expired:
                        self._memory_cache[cache_key] = entry
                        self._stats["hits"] += 1
                        elapsed = (time.perf_counter() - start_time) * 1000
                        logger.debug("Cache HIT (file) for %s in %.1fms", cache_key, elapsed)
                        return entry.data
                except Exception as e:
                    logger.debug("File cache read failed: %s", e)

        self._stats["misses"] += 1
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.debug("Cache MISS for %s in %.1fms", cache_key, elapsed)
        return default

    async def set(
        self,
        query_type: str,
        key: str,
        data: Any,
        entity_ids: Optional[List[str]] = None,
        file_paths: Optional[List[str]] = None,
        ttl_seconds: int = 3600,
    ) -> None:
        """Store result in cache.

        Args:
            query_type: Type of query
            key: Cache key
            data: Data to cache
            entity_ids: Related entity IDs (for invalidation)
            file_paths: Related file paths (for invalidation)
            ttl_seconds: Time to live in seconds
        """
        cache_key = self._make_key(query_type, key)

        entry = CacheEntry(
            key=cache_key,
            query_type=query_type,
            data=data,
            entity_ids=entity_ids or [],
            file_paths=file_paths or [],
            ttl_seconds=ttl_seconds,
        )

        # Store in memory
        self._memory_cache[cache_key] = entry
        self._stats["stores"] += 1

        # Note: Storage backend persistence is not implemented
        # Cache uses memory + file storage for now

        # Write to file cache
        if self._cache_dir:
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file = self._cache_dir / f"{cache_key}.json"
                cache_file.write_text(json.dumps(entry.to_dict()))
            except Exception as e:
                logger.debug("File cache write failed: %s", e)

        logger.debug("Cached %s with TTL %ds", cache_key, ttl_seconds)

    async def invalidate(
        self,
        query_type: Optional[str] = None,
        key: Optional[str] = None,
        entity_id: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> int:
        """Invalidate cache entries.

        Args:
            query_type: Invalidate all entries of this type
            key: Invalidate specific key
            entity_id: Invalidate entries affecting this entity
            file_path: Invalidate entries affecting this file

        Returns:
            Number of entries invalidated
        """
        invalidated = 0

        if key and query_type:
            # Invalidate specific entry
            cache_key = self._make_key(query_type, key)
            if cache_key in self._memory_cache:
                del self._memory_cache[cache_key]
                invalidated += 1
        else:
            # Invalidate by type, entity, or file
            keys_to_remove = []
            for cache_key, entry in self._memory_cache.items():
                should_invalidate = False

                if query_type and entry.query_type == query_type:
                    should_invalidate = True
                elif entity_id and entity_id in entry.entity_ids:
                    should_invalidate = True
                elif file_path and file_path in entry.file_paths:
                    should_invalidate = True

                if should_invalidate:
                    keys_to_remove.append(cache_key)

            for cache_key in keys_to_remove:
                del self._memory_cache[cache_key]
                invalidated += 1

        logger.info("Invalidated %d cache entries", invalidated)
        return invalidated

    async def refresh_on_index(
        self,
        changed_files: List[str],
        changed_entities: Optional[List[str]] = None,
    ) -> int:
        """Incrementally update affected pre-computed data.

        Called after indexing to invalidate stale cache entries.

        Args:
            changed_files: Files that were re-indexed
            changed_entities: Entities that changed (optional)

        Returns:
            Number of entries invalidated
        """
        invalidated = 0

        # Invalidate entries affected by changed files
        for file_path in changed_files:
            invalidated += await self.invalidate(file_path=file_path)

        # Invalidate entries affected by changed entities
        if changed_entities:
            for entity_id in changed_entities:
                invalidated += await self.invalidate(entity_id=entity_id)

        logger.info(
            "Refreshed cache after index: %d entries invalidated for %d files",
            invalidated, len(changed_files)
        )
        return invalidated

    async def warm_up(
        self,
        query_types: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Pre-compute common queries to warm the cache.

        Args:
            query_types: Types to warm up (all if None)

        Returns:
            Dictionary of query_type -> entries created
        """
        types_to_warm = query_types or list(self.QUERY_TYPES.keys())
        results: Dict[str, int] = {}

        for query_type in types_to_warm:
            try:
                count = await self._warm_up_type(query_type)
                results[query_type] = count
            except Exception as e:
                logger.warning("Failed to warm up %s: %s", query_type, e)
                results[query_type] = 0

        return results

    async def _warm_up_type(self, query_type: str) -> int:
        """Warm up cache for a specific query type.

        Args:
            query_type: Type to warm up

        Returns:
            Number of entries created
        """
        if not self._storage:
            return 0

        count = 0

        if query_type == "def_lookup":
            # Build symbol name → location index
            entities = await self._storage.query_raw(
                table_name="graph_entities",
                filters={},
                limit=1000,
                project_id=self._project_id,
            )
            for entity in entities:
                name = entity.get("name")
                entity_id = entity.get("id")
                file_path = entity.get("file_path")
                if name and entity_id:
                    await self.set(
                        query_type="def_lookup",
                        key=name,
                        data={
                            "id": entity_id,
                            "file_path": file_path,
                            "line_number": entity.get("line_number"),
                            "type": entity.get("type"),
                        },
                        entity_ids=[str(entity_id)],
                        file_paths=[str(file_path)] if file_path else [],
                    )
                    count += 1

        elif query_type == "file_refs":
            # Build file → symbols index
            entities = await self._storage.query_raw(
                table_name="graph_entities",
                filters={},
                limit=5000,
                project_id=self._project_id,
            )

            by_file: Dict[str, List[Dict]] = {}
            for entity in entities:
                file_path = entity.get("file_path")
                if file_path:
                    if file_path not in by_file:
                        by_file[file_path] = []
                    by_file[file_path].append({
                        "id": entity.get("id"),
                        "name": entity.get("name"),
                        "type": entity.get("type"),
                        "line_number": entity.get("line_number"),
                    })

            for file_path, symbols in by_file.items():
                await self.set(
                    query_type="file_refs",
                    key=file_path,
                    data={
                        "file_path": file_path,
                        "symbol_count": len(symbols),
                        "symbols": symbols,
                    },
                    file_paths=[file_path],
                    entity_ids=[s["id"] for s in symbols],
                )
                count += 1

        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with hit/miss/store counts and rates
        """
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0.0

        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "stores": self._stats["stores"],
            "hit_rate": hit_rate,
            "memory_entries": len(self._memory_cache),
        }

    def _make_key(self, query_type: str, key: str) -> str:
        """Create cache key from query type and key.

        Args:
            query_type: Type of query
            key: User-provided key

        Returns:
            Combined cache key
        """
        # Hash long keys to keep them manageable
        if len(key) > 100:
            key_hash = hashlib.md5(key.encode()).hexdigest()[:16]
            key = f"{key[:50]}...{key_hash}"

        return f"{self._project_id or 'default'}:{query_type}:{key}"
