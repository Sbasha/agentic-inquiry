"""LanceDB adapter implementing the database abstraction protocols.

This adapter wraps the existing LanceDBManager to provide:
- VectorStorageProtocol (core CRUD operations)
- VectorSearchCapability (vector similarity search)
- FTSCapability (full-text search)
- HybridSearchCapability (combined vector + FTS)
- GraphRankingCapability (PageRank-based boosting)
- IndexingDatabaseProtocol (domain-specific indexing operations)

All search methods return SearchResult with normalized scores (0.0-1.0).

See: docs/design/database-abstraction-revised.md
     .sessions/deep-architecture-review/009-design.md (DES-S2-001)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

from agent_vault.config import Config
from agent_vault.constants import CURRENT_PROJECT_ID
from agent_vault.database.filters import Filter, is_in, translate_filter
from agent_vault.database.lancedb_manager import LanceDBManager
from agent_vault.database.query_spec import QuerySpec
from agent_vault.database.results import (
    SearchResult,
    normalize_distance_to_score,
)

from agent_vault.models.document_chunk import BRANCH_INDEXING_FIELDS

if TYPE_CHECKING:
    from agent_vault.models.document_chunk import DocumentChunk
    from agent_vault.models.graph_entity import GraphEntity
    from agent_vault.models.graph_relationship import GraphRelationship

logger = logging.getLogger(__name__)


class LanceDBAdapter:
    """LanceDB adapter implementing database abstraction protocols.

    This adapter wraps LanceDBManager to provide a protocol-compliant interface.
    It translates between the canonical types (Filter, QuerySpec, SearchResult)
    and the LanceDB-specific operations.

    Lifecycle:
        adapter = await LanceDBAdapter.from_config(config)
        await adapter.initialize()
        # ... use adapter ...
        await adapter.close()

    All search methods return List[SearchResult] with normalized scores (0.0-1.0).

    Example:
        >>> adapter = await LanceDBAdapter.from_config(config)
        >>> await adapter.initialize()
        >>> results = await adapter.vector_search(
        ...     table="document_chunks",
        ...     vector=[0.1] * 384,
        ...     limit=10
        ... )
        >>> for r in results:
        ...     print(f"{r.id}: {r.score:.3f}")
    """

    def __init__(
        self,
        manager: LanceDBManager,
        config: Optional[Config] = None,
    ) -> None:
        """Initialize adapter with a LanceDBManager instance.

        Use from_config() for standard instantiation with config.

        Args:
            manager: LanceDBManager instance to wrap
            config: Optional configuration for search weights. If not provided,
                uses default weights (0.7 vector, 0.3 FTS).
        """
        self._manager = manager
        self._config = config
        self._initialized = False

    @classmethod
    async def from_config(cls, config: Config) -> "LanceDBAdapter":
        """Create adapter from configuration.

        Args:
            config: Application configuration

        Returns:
            New LanceDBAdapter instance
        """
        manager = LanceDBManager.from_config(config)
        return cls(manager, config=config)

    # =========================================================================
    # VectorStorageProtocol Implementation (Core)
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the adapter and ensure tables exist.

        This method is idempotent - calling it multiple times is safe.
        """
        if self._initialized:
            return

        await self._manager.connect()
        await self._manager.create_tables_and_indexes()
        self._initialized = True
        logger.info("LanceDBAdapter initialized")

    async def close(self) -> None:
        """Close connections and release resources."""
        if self._manager:
            await self._manager.close()
            self._initialized = False
            logger.info("LanceDBAdapter closed")

    async def add(
        self,
        table: str,
        records: Sequence[Dict[str, Any]],
    ) -> None:
        """Add records to a table.

        Args:
            table: Logical table name
            records: Records to add (must include 'id' field)
        """
        if not records:
            return
        await self._manager.add_rows(table, list(records))

    async def delete(
        self,
        table: str,
        ids: Sequence[str],
    ) -> int:
        """Delete records by ID.

        Args:
            table: Logical table name
            ids: Record IDs to delete

        Returns:
            Number of records actually deleted
        """
        if not ids:
            return 0

        # Count how many of the requested IDs actually exist before deletion
        ids_list = list(ids)
        existing_count = 0

        try:
            # Query to count existing records with matching IDs
            existing_records = await self._manager.advanced_filter(
                table_name=table,
                filters={"id": ("IN", ids_list)},
                limit=len(ids_list),
            )
            existing_count = len(existing_records)
        except Exception:
            # Table may not exist or other error - proceed with delete anyway
            # If delete succeeds on non-existent table, count is 0
            pass

        # Perform the actual deletion
        await self._manager.delete_by_ids(table, ids_list)

        return existing_count

    async def get_by_ids(
        self,
        table: str,
        ids: Sequence[str],
    ) -> List[Dict[str, Any]]:
        """Retrieve records by ID.

        Args:
            table: Logical table name
            ids: Record IDs to retrieve

        Returns:
            List of records (may be fewer than requested if not found)
        """
        if not ids:
            return []

        # Build IN filter for IDs
        ids_list = list(ids)
        filter_ast = is_in("id", ids_list)
        filter_sql = translate_filter(filter_ast)

        results = await self._manager.advanced_filter(
            table,
            filters={"_sql": filter_sql},
            limit=len(ids_list),
        )
        return results

    async def upsert(
        self,
        table: str,
        records: Sequence[Dict[str, Any]],
        key_field: str = "id",
    ) -> None:
        """Insert or update records.

        Args:
            table: Logical table name
            records: Records to upsert
            key_field: Field to use as unique key (default: "id")
        """
        if not records:
            return
        await self._manager.upsert(table, list(records), key_field=key_field)

    async def execute(
        self,
        spec: QuerySpec,
    ) -> List[SearchResult]:
        """Execute a query specification.

        This method routes to the appropriate search method based on
        what's specified in the QuerySpec.

        Args:
            spec: Query specification

        Returns:
            List of SearchResult with normalized scores (0.0-1.0)
        """
        # Determine query type based on QuerySpec contents
        has_vector = spec.vector is not None
        has_fts = spec.fts_query is not None

        # Build filters dict for LanceDB
        filters = self._build_filters(spec)

        if has_vector and has_fts:
            # Hybrid search - use config weights if available, else defaults
            # Type assertions for mypy (we already checked these are not None)
            assert spec.vector is not None
            assert spec.fts_query is not None

            # Get weights from config or use defaults
            vector_weight = 0.7
            fts_weight = 0.3
            if self._config is not None:
                vector_weight = getattr(
                    getattr(self._config.search, "hybrid_search", None),
                    "vector_weight",
                    0.7,
                )
                fts_weight = getattr(
                    getattr(self._config.search, "hybrid_search", None),
                    "fts_weight",
                    0.3,
                )

            return await self.hybrid_search(
                table=spec.table,
                vector=spec.vector,
                query=spec.fts_query,
                limit=spec.limit,
                filters=spec.filters,
                vector_column=spec.vector_column,
                fts_columns=spec.fts_columns if spec.fts_columns else None,
                vector_weight=vector_weight,
                fts_weight=fts_weight,
                project_ids=spec.project_ids,
            )
        elif has_vector:
            # Vector search
            assert spec.vector is not None
            return await self.vector_search(
                table=spec.table,
                vector=spec.vector,
                limit=spec.limit,
                filters=spec.filters,
                vector_column=spec.vector_column,
                project_ids=spec.project_ids,
            )
        elif has_fts:
            # FTS search
            assert spec.fts_query is not None
            return await self.fts_search(
                table=spec.table,
                query=spec.fts_query,
                limit=spec.limit,
                filters=spec.filters,
                fts_columns=spec.fts_columns if spec.fts_columns else None,
                project_ids=spec.project_ids,
            )
        else:
            # Filter-only query
            return await self._filter_only_query(spec, filters)

    async def table_exists(self, table: str) -> bool:
        """Check if a table exists.

        Args:
            table: Logical table name

        Returns:
            True if table exists
        """
        tables = await self._manager.list_tables()
        return table in tables

    async def count(
        self,
        table: str,
        filters: Optional[Filter] = None,
    ) -> int:
        """Count records matching filters.

        Args:
            table: Logical table name
            filters: Optional filter criteria

        Returns:
            Number of matching records
        """
        filter_dict = None
        if filters:
            filter_sql = translate_filter(filters)
            if filter_sql:
                filter_dict = {"_sql": filter_sql}

        return await self._manager.count_records(table, filters=filter_dict)

    # =========================================================================
    # VectorSearchCapability Implementation
    # =========================================================================

    async def vector_search(
        self,
        table: str = "document_chunks",
        vector: Optional[List[float]] = None,
        limit: int = 10,
        filters: Optional[Union[Filter, Dict[str, Any]]] = None,
        vector_column: str = "vector",
        project_ids: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        query_vector: Optional[List[float]] = None,
        table_name: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform vector similarity search.

        Args:
            table: Logical table name.
            vector: Query vector.
            limit: Maximum results to return.
            filters: Optional filters (Filter AST or dict).
            vector_column: Column containing vectors.
            project_ids: Optional project scope (list).
            project_id: Optional single project ID (alternative to project_ids).
            query_vector: Backward-compatible alias for ``vector``.
            table_name: Backward-compatible alias for ``table``.

        Returns:
            List of SearchResult with normalized scores (0.0-1.0).
        """
        if query_vector is not None:
            vector = query_vector
        if table_name is not None:
            table = table_name
        if vector is None:
            raise ValueError("vector_search requires 'vector' (or 'query_vector')")

        filter_dict = self._filter_to_dict(filters)
        resolved_project_id, extra_filters = self._resolve_project_id(
            project_ids, project_id
        )
        merged_filters = self._merge_filters(filter_dict, extra_filters)

        raw_results = await self._manager.vector_search(
            table_name=table,
            query_vector=vector,
            vector_column_name=vector_column,
            limit=limit,
            filters=merged_filters,
            project_id=resolved_project_id,
        )

        return self._convert_to_search_results(raw_results, source="vector")

    # =========================================================================
    # FTSCapability Implementation
    # =========================================================================

    async def fts_search(
        self,
        table: str = "document_chunks",
        query: str = "",
        limit: int = 10,
        filters: Optional[Union[Filter, Dict[str, Any]]] = None,
        fts_columns: Optional[List[str]] = None,
        project_ids: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        table_name: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform full-text search.

        Args:
            table: Logical table name.
            query: Search query string.
            limit: Maximum results to return.
            filters: Optional filters (Filter AST or dict).
            fts_columns: Columns to search (currently ignored; uses table default).
            project_ids: Optional project scope (list).
            project_id: Optional single project ID (alternative to project_ids).
            table_name: Backward-compatible alias for ``table``.

        Returns:
            List of SearchResult with normalized scores (0.0-1.0).
        """
        if table_name is not None:
            table = table_name

        filter_dict = self._filter_to_dict(filters)
        resolved_project_id, extra_filters = self._resolve_project_id(
            project_ids, project_id
        )
        merged_filters = self._merge_filters(filter_dict, extra_filters)

        raw_results = await self._manager.fts_search(
            table_name=table,
            query=query,
            limit=limit,
            filters=merged_filters,
            project_id=resolved_project_id,
        )

        return self._convert_to_search_results(raw_results, source="fts")

    # =========================================================================
    # HybridSearchCapability Implementation
    # =========================================================================

    async def hybrid_search(
        self,
        table: str,
        vector: List[float],
        query: str,
        limit: int = 10,
        filters: Optional[Union[Filter, Dict[str, Any]]] = None,
        vector_column: str = "vector",
        fts_columns: Optional[List[str]] = None,
        vector_weight: float = 0.7,
        fts_weight: float = 0.3,
        project_ids: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Perform native hybrid search combining vector and FTS.

        Args:
            table: Logical table name
            vector: Query vector
            query: FTS query string
            limit: Maximum results to return
            filters: Optional additional filters (Filter AST or dict)
            vector_column: Column containing vectors
            fts_columns: Columns to search (currently ignored - uses table default)
            vector_weight: Weight for vector results (currently ignored by LanceDB)
            fts_weight: Weight for FTS results (currently ignored by LanceDB)
            project_ids: Optional project scope (list of project IDs)
            project_id: Optional single project ID (alternative to project_ids)

        Returns:
            List of SearchResult with normalized scores (0.0-1.0)

        Note:
            LanceDBManager.hybrid_search uses its own reranker for fusion.
            The vector_weight/fts_weight parameters are not currently passed through.
        """
        filter_dict = self._filter_to_dict(filters)
        resolved_project_id, extra_filters = self._resolve_project_id(
            project_ids, project_id
        )
        merged_filters = self._merge_filters(filter_dict, extra_filters)

        # Note: LanceDBManager.hybrid_search has different parameter names:
        # - query (not query_text) for FTS query
        # - query_vector for vector
        # - doesn't support fts_column_name, vector_weight, fts_weight directly
        raw_results = await self._manager.hybrid_search(
            table_name=table,
            query=query,
            query_vector=vector,
            vector_column_name=vector_column,
            limit=limit,
            filters=merged_filters,
            project_id=resolved_project_id,
            # reranker parameter could be used for custom fusion
        )

        return self._convert_to_search_results(raw_results, source="hybrid")

    # =========================================================================
    # Advanced Filter Capability
    # =========================================================================

    async def advanced_filter(
        self,
        table: str,
        filters: Optional[Union[Filter, Dict[str, Any]]] = None,
        limit: int = 100,
        project_ids: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Query with advanced filtering (no vector/FTS).

        This method provides filter-only queries, useful for precise lookups
        without semantic search.

        Args:
            table: Logical table name
            filters: Filter conditions (Filter AST or dict)
            limit: Maximum results to return
            project_ids: Optional project scope (list of project IDs)
            project_id: Optional single project ID (alternative to project_ids)

        Returns:
            List of SearchResult with score=1.0 (filter matches have no ranking)
        """
        filter_dict = self._filter_to_dict(filters)
        resolved_project_id, extra_filters = self._resolve_project_id(
            project_ids, project_id
        )
        merged_filters = self._merge_filters(filter_dict, extra_filters)

        raw_results = await self._manager.advanced_filter(
            table_name=table,
            filters=merged_filters,
            limit=limit,
            project_id=resolved_project_id,
        )

        return self._convert_to_search_results(raw_results, source="filter")

    async def query_raw(
        self,
        table: Optional[str] = None,
        filters: Optional[Union[Filter, Dict[str, Any]]] = None,
        limit: int = 100,
        project_ids: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        *,
        table_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query and return raw dict records (for graph operations).

        Unlike advanced_filter which returns SearchResult, this method returns
        raw dict records. Useful for graph traversal operations that need to
        work with raw entity/relationship data.

        Args:
            table: Logical table name
            filters: Filter conditions (Filter AST or dict)
            limit: Maximum results to return
            project_ids: Optional project scope (list of project IDs)
            project_id: Optional single project ID (alternative to project_ids)
            table_name: Alias for table (for LanceDBManager compatibility)

        Returns:
            List of raw dict records from the database
        """
        # Support table_name as alias for table (backward compat with LanceDBManager)
        resolved_table = table_name if table is None else table
        if resolved_table is None:
            raise ValueError("Either 'table' or 'table_name' must be provided")

        filter_dict = self._filter_to_dict(filters)
        resolved_project_id, extra_filters = self._resolve_project_id(
            project_ids, project_id
        )
        merged_filters = self._merge_filters(filter_dict, extra_filters)

        return await self._manager.advanced_filter(
            table_name=resolved_table,
            filters=merged_filters,
            limit=limit,
            project_id=resolved_project_id,
        )

    async def vector_search_raw(
        self,
        table: str,
        vector: List[float],
        limit: int = 10,
        filters: Optional[Union[Filter, Dict[str, Any]]] = None,
        vector_column: str = "vector",
        project_ids: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Perform vector search returning raw dicts (for graph operations).

        Unlike vector_search which returns SearchResult, this method returns
        raw dict records. Useful for operations that need raw entity data.

        Args:
            table: Logical table name
            vector: Query vector
            limit: Maximum results to return
            filters: Optional additional filters (Filter AST or dict)
            vector_column: Column containing vectors
            project_ids: Optional project scope (list of project IDs)
            project_id: Optional single project ID (alternative to project_ids)

        Returns:
            List of raw dict records from the database
        """
        filter_dict = self._filter_to_dict(filters)
        resolved_project_id, extra_filters = self._resolve_project_id(
            project_ids, project_id
        )
        merged_filters = self._merge_filters(filter_dict, extra_filters)

        return await self._manager.vector_search(
            table_name=table,
            query_vector=vector,
            vector_column_name=vector_column,
            limit=limit,
            filters=merged_filters,
            project_id=resolved_project_id,
        )

    # =========================================================================
    # GraphRankingCapability Implementation
    # =========================================================================

    async def has_graph_ranking(self, table: str) -> bool:
        """Check if graph ranking is available for a table.

        Args:
            table: Logical table name (not used - LanceDBManager always checks graph_entities)

        Returns:
            True if graph ranking metrics are available
        """
        # LanceDBManager.graph_ranking_available() doesn't take table param
        # It always checks the graph_entities table for ranking signals
        _ = table  # Acknowledge parameter for protocol compliance
        return await self._manager.graph_ranking_available()

    async def apply_graph_boost(
        self,
        results: List[SearchResult],
        table: str,
        boost_factor: float = 0.1,
    ) -> List[SearchResult]:
        """Apply graph-based score boosting to results.

        Boosts results based on PageRank metrics stored in the graph entities table.

        Args:
            results: Search results to boost
            table: Source table (for looking up graph metrics)
            boost_factor: How much to weight graph metrics (0.0-1.0)

        Returns:
            Results with adjusted scores (still normalized 0.0-1.0)
        """
        if not results or boost_factor <= 0:
            return results

        # Get PageRank scores for result IDs
        result_ids = [r.id for r in results]
        pagerank_scores = await self._get_pagerank_scores(result_ids)

        # Apply boost
        boosted_results = []
        for result in results:
            pagerank = pagerank_scores.get(result.id, 0.0)
            # Blend: (1 - boost_factor) * original + boost_factor * pagerank
            new_score = (1 - boost_factor) * result.score + boost_factor * pagerank
            # Ensure still in 0.0-1.0 range
            new_score = max(0.0, min(1.0, new_score))
            boosted_results.append(result.with_score(new_score, source="graph_boosted"))

        # Re-sort by new scores
        boosted_results.sort(key=lambda r: r.score, reverse=True)
        return boosted_results

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _filter_to_dict(
        self, filters: Optional[Union[Filter, Dict[str, Any]]]
    ) -> Optional[Dict[str, Any]]:
        """Convert Filter AST or dict to LanceDB filter dict.

        Args:
            filters: Either a Filter AST, a dict (passed through), or None.

        Returns:
            Dict suitable for LanceDB, or None.
        """
        if filters is None:
            return None

        # If already a dict, pass through (backward compatibility with SearchService)
        if isinstance(filters, dict):
            return filters

        # Convert Filter AST to SQL
        filter_sql = translate_filter(filters)
        if filter_sql:
            return {"_sql": filter_sql}
        return None

    def _build_filters(self, spec: QuerySpec) -> Optional[Dict[str, Any]]:
        """Build filter dict from QuerySpec."""
        return self._filter_to_dict(spec.filters)

    def _merge_filters(
        self,
        base_filters: Optional[Dict[str, Any]],
        extra_filters: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Merge two filter dictionaries.

        If both are None, returns None.
        If only one is provided, returns that one.
        If both are provided, merges them.
        """
        if base_filters is None and extra_filters is None:
            return None
        if base_filters is None:
            return extra_filters
        if extra_filters is None:
            return base_filters
        # Merge - extra_filters override base_filters for same keys
        return {**base_filters, **extra_filters}

    def _resolve_project_id(
        self,
        project_ids: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Resolve project_ids list or single project_id for LanceDB.

        Accepts either project_ids (list) or project_id (string) for flexibility.
        The project_id parameter takes precedence if both are provided.

        Returns:
            Tuple of (resolved_project_id, extra_filter):
            - For single project: (project_id, None)
            - For multiple projects: (None, {"project_id": ("IN", project_ids)})
            - For all projects: (None, None)

        LanceDB manager expects:
        - CURRENT_PROJECT_ID for configured project
        - specific ID for single project
        - None for all projects
        """
        # Single project_id takes precedence (backward compatibility)
        if project_id is not None:
            return project_id, None

        if project_ids is None:
            return None, None  # All projects
        if len(project_ids) == 0:
            return None, None  # Empty list = all projects (per documented semantics)
        if len(project_ids) == 1:
            return project_ids[0], None
        # Multiple project IDs - use IN clause filter
        # Return None for project_id (no single project filter) and add IN clause
        return None, {"project_id": ("IN", project_ids)}

    def _convert_to_search_results(
        self,
        raw_results: List[Dict[str, Any]],
        source: str,
    ) -> List[SearchResult]:
        """Convert raw LanceDB results to SearchResult instances.

        Handles score normalization using the _distance field if present.

        Args:
            raw_results: Raw results from LanceDB
            source: Source identifier (vector, fts, hybrid, filter)

        Returns:
            List of SearchResult with normalized scores
        """
        search_results = []

        for row in raw_results:
            # Extract ID
            row_id = str(row.get("id", ""))
            if not row_id:
                continue

            # Extract distance/score
            distance = row.get("_distance")
            score = row.get("_score")

            # Normalize score
            if score is not None:
                # FTS/hybrid may provide pre-computed scores
                normalized_score = max(0.0, min(1.0, float(score)))
            elif distance is not None:
                # Vector search provides distance
                normalized_score = normalize_distance_to_score(float(distance))
            else:
                # Filter-only: default score = 1.0
                normalized_score = 1.0

            # Create data dict (exclude internal fields)
            data = {k: v for k, v in row.items() if not k.startswith("_")}

            search_results.append(
                SearchResult(
                    id=row_id,
                    data=data,
                    score=normalized_score,
                    source=source,
                    distance=float(distance) if distance is not None else None,
                )
            )

        return search_results

    async def _filter_only_query(
        self,
        spec: QuerySpec,
        filters: Optional[Dict[str, Any]],
    ) -> List[SearchResult]:
        """Execute a filter-only query (no vector/FTS)."""
        resolved_project_id, extra_filters = self._resolve_project_id(spec.project_ids)
        merged_filters = self._merge_filters(filters, extra_filters)

        raw_results = await self._manager.advanced_filter(
            spec.table,
            filters=merged_filters,
            limit=spec.limit,
            project_id=resolved_project_id,
        )

        return self._convert_to_search_results(raw_results, source="filter")

    async def _get_pagerank_scores(
        self, ids: List[str]
    ) -> Dict[str, float]:
        """Get PageRank scores for a list of entity IDs."""
        if not ids:
            return {}

        try:
            # Query graph entities for PageRank
            filter_ast = is_in("id", ids)
            filter_sql = translate_filter(filter_ast)

            entities = await self._manager.advanced_filter(
                "graph_entities",
                filters={"_sql": filter_sql},
                limit=len(ids),
            )

            return {
                str(e.get("id", "")): float(e.get("pagerank", 0.0))
                for e in entities
                if e.get("id")
            }
        except Exception as e:
            logger.warning("Failed to get PageRank scores: %s", e)
            return {}

    # =========================================================================
    # IndexingDatabaseProtocol Implementation
    # =========================================================================

    async def upsert_chunks(
        self,
        chunks: Sequence["DocumentChunk"],
        project_id: str,
    ) -> int:
        """Insert or update document chunks.

        Args:
            chunks: Document chunks to upsert
            project_id: Project identifier for data isolation

        Returns:
            Number of chunks upserted
        """
        if not chunks:
            return 0

        # Convert chunks to dicts, stripping branch-indexing fields not in LanceDB schema
        chunk_dicts = []
        for chunk in chunks:
            d = chunk.to_dict()
            for field in BRANCH_INDEXING_FIELDS:
                d.pop(field, None)
            chunk_dicts.append(d)

        # LanceDBManager.add_document_chunks handles the upsert logic
        await self._manager.add_document_chunks(
            chunk_dicts,
            project_id=project_id,
            ensure_commit=True,
        )

        return len(chunks)

    async def upsert_entities(
        self,
        entities: Sequence["GraphEntity"],
        project_id: str,
    ) -> int:
        """Insert or update graph entities.

        Args:
            entities: Graph entities to upsert
            project_id: Project identifier for data isolation

        Returns:
            Number of entities upserted
        """
        if not entities:
            return 0

        # Convert entities to dicts for the manager
        entity_dicts = [entity.to_dict() for entity in entities]

        # LanceDBManager.add_graph_entities handles the upsert logic
        await self._manager.add_graph_entities(entity_dicts)

        return len(entities)

    async def upsert_relationships(
        self,
        relationships: Sequence["GraphRelationship"],
        project_id: str,
    ) -> int:
        """Insert or update graph relationships.

        Args:
            relationships: Graph relationships to upsert
            project_id: Project identifier for data isolation

        Returns:
            Number of relationships upserted
        """
        if not relationships:
            return 0

        # Convert relationships to dicts for the manager
        relationship_dicts = [rel.to_dict() for rel in relationships]

        # LanceDBManager.add_graph_relationships handles the upsert logic
        await self._manager.add_graph_relationships(relationship_dicts)

        return len(relationships)

    async def delete_by_file(
        self,
        file_path: str,
        project_id: str,
    ) -> int:
        """Delete all data associated with a file.

        Removes document chunks, graph entities, and graph relationships
        that were created from the specified file.

        Args:
            file_path: Path to the source file
            project_id: Project identifier for data isolation

        Returns:
            Total number of records deleted (chunks + entities + relationships)
        """
        total_deleted = 0

        # Delete document chunks for this file
        try:
            chunks = await self._manager.advanced_filter(
                "document_chunks",
                filters={"file_path": file_path},
                project_id=project_id,
            )
            if chunks:
                chunk_ids = [str(c.get("id", "")) for c in chunks if c.get("id")]
                if chunk_ids:
                    await self._manager.delete_document_chunks(chunk_ids)
                    total_deleted += len(chunk_ids)
        except Exception as e:
            logger.warning("Failed to delete chunks for file %s: %s", file_path, e)

        # Delete graph entities for this file
        try:
            entities = await self._manager.advanced_filter(
                "graph_entities",
                filters={"file_path": file_path},
                project_id=project_id,
            )
            if entities:
                entity_ids = [str(e.get("id", "")) for e in entities if e.get("id")]
                if entity_ids:
                    await self._manager.delete_graph_entities(entity_ids)
                    total_deleted += len(entity_ids)
        except Exception as e:
            logger.warning("Failed to delete entities for file %s: %s", file_path, e)

        # Delete graph relationships for this file
        try:
            relationships = await self._manager.advanced_filter(
                "graph_relationships",
                filters={"source_file": file_path},
                project_id=project_id,
            )
            if relationships:
                rel_ids = [str(r.get("id", "")) for r in relationships if r.get("id")]
                if rel_ids:
                    await self._manager.delete_graph_relationships(rel_ids)
                    total_deleted += len(rel_ids)
        except Exception as e:
            logger.warning("Failed to delete relationships for file %s: %s", file_path, e)

        logger.debug(
            "Deleted %d records for file %s in project %s",
            total_deleted,
            file_path,
            project_id,
        )
        return total_deleted

    # =========================================================================
    # Utility Methods (for GraphSearchService compatibility)
    # =========================================================================

    async def list_tables(self) -> List[str]:
        """List all tables in the database.

        Returns:
            List of table names
        """
        return await self._manager.list_tables()

    async def query_across_projects(
        self,
        table_name: str,
        project_ids: Sequence[str],
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query data across multiple projects.

        Used by GraphSearchService for multi-project graph traversal.

        Args:
            table_name: Logical table to query
            project_ids: List of project IDs to include
            filters: Optional filter conditions
            limit: Maximum number of results

        Returns:
            List of matching records from all specified projects
        """
        return await self._manager.query_across_projects(
            table_name=table_name,
            filters=filters or {},
            limit=limit,
            project_ids=list(project_ids),
        )

    # =========================================================================
    # IndexingPipeline Support Methods
    # =========================================================================

    async def run_maintenance(self) -> Dict[str, Any]:
        """Run database maintenance operations.

        Delegates to the underlying manager's maintenance routine which
        includes compaction, optimization, and cleanup tasks.

        Returns:
            Dict with maintenance results including summary stats
        """
        return await self._manager.run_maintenance()

    async def add_document_chunks(
        self,
        chunks: List[Any],
        project_id: str = CURRENT_PROJECT_ID,
        ensure_commit: bool = True,
    ) -> None:
        """Add document chunks to the database.

        Low-level method for batch adding chunks. Accepts either dictionaries
        or DocumentChunk objects (which have to_dict() method).
        Used by IndexingPipeline for efficient bulk inserts.

        Args:
            chunks: List of chunk dictionaries or DocumentChunk objects
            project_id: Project identifier for data isolation (default: CURRENT_PROJECT_ID)
            ensure_commit: Accepted for interface compatibility; LanceDB commits
                before the call returns
        """
        if not chunks:
            return
        await self._manager.add_document_chunks(
            chunks,
            project_id=project_id,
            ensure_commit=ensure_commit,
        )

    async def add_graph_entities(
        self,
        entities: List[Any],
    ) -> None:
        """Add graph entities to the database.

        Low-level method for batch adding entities. Accepts either dictionaries
        or GraphEntity objects (which have to_dict() method).
        Used by IndexingPipeline and GraphBuilder for efficient bulk inserts.

        Args:
            entities: List of entity dictionaries or GraphEntity objects
        """
        if not entities:
            return
        await self._manager.add_graph_entities(entities)

    async def add_graph_relationships(
        self,
        relationships: List[Any],
    ) -> None:
        """Add graph relationships to the database.

        Low-level method for batch adding relationships. Accepts either dictionaries
        or GraphRelationship objects (which have to_dict() method).
        Used by IndexingPipeline and GraphBuilder for efficient bulk inserts.

        Args:
            relationships: List of relationship dictionaries or GraphRelationship objects
        """
        if not relationships:
            return
        await self._manager.add_graph_relationships(relationships)

    async def delete_document_chunks(
        self,
        chunk_ids: List[str],
    ) -> None:
        """Delete document chunks by ID.

        Args:
            chunk_ids: List of chunk IDs to delete
        """
        if not chunk_ids:
            return
        await self._manager.delete_document_chunks(chunk_ids)

    async def delete_graph_entities(
        self,
        entity_ids: List[str],
    ) -> None:
        """Delete graph entities by ID.

        Args:
            entity_ids: List of entity IDs to delete
        """
        if not entity_ids:
            return
        await self._manager.delete_graph_entities(entity_ids)

    async def delete_graph_relationships(
        self,
        relationship_ids: List[str],
    ) -> None:
        """Delete graph relationships by ID.

        Args:
            relationship_ids: List of relationship IDs to delete
        """
        if not relationship_ids:
            return
        await self._manager.delete_graph_relationships(relationship_ids)

    async def query_entities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query graph entities with filters.

        Args:
            filters: Optional filter conditions as key-value pairs
            limit: Maximum number of results
            project_id: Optional project scope (defaults to manager's default)

        Returns:
            List of entity dictionaries matching the query
        """
        return await self._manager.query_entities(
            filters=filters,
            limit=limit,
            project_id=project_id,
        )
