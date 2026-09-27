"""Search service built on top of a storage provider.

Accepts StorageFacade as the storage interface. StorageFacade provides
unified access to vector and graph storage through the provider framework.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, cast, Union

from agentic_inquiry.config import Config
from agentic_inquiry.constants import CURRENT_PROJECT_ID
from agentic_inquiry.database.query_spec import QuerySpec
from agentic_inquiry.database.results import SearchResult, dicts_to_search_results
from agentic_inquiry.search.deduplicator import SearchDeduplicator
from agentic_inquiry.search.query_sanitizer import QuerySanitizer
from agentic_inquiry.storage.facade import StorageFacade

logger = logging.getLogger(__name__)


class NoOpEventSystem:
    """Minimal event system that does nothing, for standalone usage."""

    async def emit(self, *args: object, **kwargs: object) -> None:
        """No-op emit method."""
        pass


from agentic_inquiry.embeddings.registry import embedding_registry  # noqa: E402
from agentic_inquiry.events import EventSystem  # noqa: E402
from agentic_inquiry.events.context_managers import track_operation  # noqa: E402
from agentic_inquiry.events.models import EventStatus  # noqa: E402
from agentic_inquiry.events.types import EventTypes  # noqa: E402


class SearchService:
    """Provides hybrid, filtered and graph aware search capabilities.

    Requires StorageFacade as the storage interface. StorageFacade provides
    unified access to vector and graph storage through the provider framework.

    Example:
        >>> storage = await StorageFacade.from_config(config, "my_project")
        >>> search = SearchService(storage, config)
    """

    def __init__(
        self,
        storage: StorageFacade,
        config: "Config",
        event_system: Optional["EventSystem"] = None,
        project_id: Optional[str] = None,
    ):
        """Initialize SearchService with dependencies.

        Args:
            storage: StorageFacade instance providing unified storage access.
            config: Config instance.
            event_system: EventSystem instance for event emission. If None,
                creates a no-op event system for standalone usage.
            project_id: Project ID for data isolation. If None, uses
                the StorageFacade's project_id.
        """
        # Store the StorageFacade - this is the primary interface for all operations
        self._storage_facade: StorageFacade = storage

        # Extract project_id from facade if not provided
        if project_id is None:
            project_id = storage.project_id

        self.config = config
        self.event_system: EventSystem | NoOpEventSystem = event_system if event_system is not None else NoOpEventSystem()

        # Resolve project_id
        if project_id is None:
            project_id = config.storage.default_project_id
            if not project_id:
                raise ValueError(
                    "project_id must be provided or set as storage.default_project_id in configuration"
                )

        self.project_id = project_id

        # Import metrics tracker
        from agentic_inquiry.metrics import get_metrics_tracker
        self._metrics = get_metrics_tracker()

        # Initialize deduplicator with configuration
        self.deduplicator = SearchDeduplicator(
            max_results_per_file=self.config.search.deduplication.max_results_per_file,
            min_diversity_ratio=self.config.search.deduplication.min_diversity_ratio,
        )

        # Initialize query sanitizer with configuration
        self.query_sanitizer = QuerySanitizer(
            preserve_wildcards=self.config.search.query_sanitization.preserve_wildcards
        )

        # Initialize specialized search services
        from agentic_inquiry.search.graph_search import GraphSearchService
        from agentic_inquiry.search.hybrid_search import HybridSearchService

        # Pass None to sub-services if using NoOpEventSystem
        sub_event_sys: Optional[EventSystem] = None if isinstance(self.event_system, NoOpEventSystem) else self.event_system

        self._graph_search = GraphSearchService(
            storage=storage,
            config=config,
            event_system=sub_event_sys,
            project_id=project_id,
        )

        self._hybrid_search = HybridSearchService(
            storage=storage,
            config=config,
            deduplicator=self.deduplicator,
            event_system=sub_event_sys,
            project_id=project_id,
        )


    @property
    def storage_facade(self) -> StorageFacade:
        """Access the underlying StorageFacade.

        Returns the StorageFacade passed to the constructor. Use this
        property when you need access to the unified storage interface.

        Returns:
            StorageFacade instance.
        """
        return self._storage_facade

    @property
    def embedding_service(self):
        """Lazy-loaded embedding service instance.
        
        Creates and caches an EmbeddingService instance on first access.
        This avoids creating multiple instances and improves performance.
        
        Returns:
            EmbeddingService instance configured with current config
            
        Raises:
            RuntimeError: If embedder is not configured
        """
        if not hasattr(self, '_embedding_service'):
            # Check if embedder is configured
            if not embedding_registry._default_configured:
                raise RuntimeError(
                    "Embedding service not configured. "
                    "Before performing search operations, configure an embedder:\n\n"
                    "  from agentic_inquiry.embeddings.hashing import HashingEmbedder\n"
                    "  from agentic_inquiry.embeddings.registry import embedding_registry\n\n"
                    "  embedder = HashingEmbedder(ndims=128)\n"
                    "  embedding_registry.configure_default_embedder(embedder, ndims=128)\n\n"
                    "Or use the MCP factory which configures embeddings automatically:\n\n"
                    "  from agentic_inquiry.mcp.factories import create_mcp_services\n"
                    "  services = create_mcp_services(config, project_id)\n\n"
                    "See docs/mcp/configuration.md for more details."
                )
            
            from agentic_inquiry.embeddings import EmbeddingService
            self._embedding_service = EmbeddingService(self.config)
        return self._embedding_service

    @property
    def supports_vector_search(self) -> bool:
        """Check if the storage backend supports vector search capability.

        Returns:
            True if vector search is available.
        """
        return self._storage_facade.supports_vector_search()

    @property
    def supports_fts(self) -> bool:
        """Check if the storage backend supports full-text search capability.

        Returns:
            True if FTS is available.
        """
        return self._storage_facade.supports_fts()

    @property
    def supports_hybrid_search(self) -> bool:
        """Check if the storage backend supports native hybrid search capability.

        Returns:
            True if hybrid search is available.
        """
        return self._storage_facade.supports_hybrid_search()

    @property
    def supports_graph_ranking(self) -> bool:
        """Check if the storage backend supports graph ranking capability.

        Returns:
            True if graph ranking is available.
        """
        return self._storage_facade.supports_graph_ranking()

    def _resolve_project_id(self, project_id: Optional[str]) -> Optional[str]:
        """Resolve project_id parameter to actual project ID.
        
        Args:
            project_id: Project ID parameter from search method. Can be:
                       - CURRENT_PROJECT_ID: Use the project_id from ProjectContext
                       - Specific ID: Use that ID
                       - None: Search across all projects
        
        Returns:
            Resolved project ID or None for all-projects search
        """
        if project_id == CURRENT_PROJECT_ID:
            return self.project_id
        return project_id
    
    def _sanitize_fts_query(self, query: str) -> str:
        """Sanitize FTS query if sanitization is enabled.
        
        Args:
            query: Original FTS query
            
        Returns:
            Sanitized query if enabled, otherwise original query
        """
        if not self.config.search.query_sanitization.enabled:
            return query
        
        # Sanitize the query
        sanitized = self.query_sanitizer.sanitize(query)
        
        # Log if query was changed
        if sanitized != query:
            logger.info(
                "Query sanitized: original=%s, sanitized=%s",
                query,
                sanitized
            )
        
        return sanitized

    def _sanitize_query_metadata(
        self,
        query_vector: Optional[Union[List[float], str]] = None,
        query_fts: Optional[str] = None,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Sanitize query parameters for event metadata.
        
        Removes sensitive data and truncates large values to keep event metadata
        manageable and safe for logging.
        
        Args:
            query_vector: Query vector (will be summarized, not included in full)
            query_fts: Full-text search query
            limit: Result limit
            filters: Query filters
            **kwargs: Additional parameters to include
        
        Returns:
            Sanitized metadata dictionary
        """
        metadata: Dict[str, Any] = {}
        
        # Summarize vector instead of including full array
        if query_vector is not None:
            metadata["vector_dim"] = len(query_vector)
            metadata["has_vector"] = True
        
        # Include FTS query (truncate if very long)
        if query_fts is not None:
            max_query_length = 200
            if len(query_fts) > max_query_length:
                metadata["query_fts"] = query_fts[:max_query_length] + "..."
                metadata["query_fts_truncated"] = True
            else:
                metadata["query_fts"] = query_fts
        
        # Include limit
        if limit is not None:
            metadata["limit"] = limit
        
        # Sanitize filters (avoid exposing sensitive values)
        if filters is not None:
            # Handle both dict filters and Filter AST
            if isinstance(filters, dict):
                # Include filter keys but not values (values might contain sensitive data)
                metadata["filter_keys"] = list(filters.keys())
            else:
                # Filter AST - just indicate we have filters
                metadata["filter_type"] = type(filters).__name__
            metadata["has_filters"] = True
        
        # Include additional parameters
        for key, value in kwargs.items():
            # Skip large or sensitive values
            if key in ("query_vector", "search_query_vector"):
                continue
            if isinstance(value, (str, int, float, bool, type(None))):
                metadata[key] = value
            elif isinstance(value, list) and len(value) < 10:
                metadata[key] = value
        
        return metadata

    def get_metrics(self) -> Dict[str, Any]:
        """Get search service metrics.
        
        Returns:
            Dictionary containing latency metrics for search operations
        """
        return {
            "latency_metrics": self._metrics.get_all_metrics(),
        }
    
    @classmethod
    async def from_config(
        cls,
        config: Optional[Config] = None,
        project_id: Optional[str] = None,
    ) -> "SearchService":
        """Create SearchService from configuration.

        Creates a StorageFacade and SearchService from configuration.
        This is an async method because StorageFacade requires async initialization.

        Args:
            config: Optional Config instance. If None, loads default configuration.
            project_id: Optional project ID. If None, uses config.storage.default_project_id.

        Returns:
            SearchService instance configured from settings.

        Example:
            >>> from agentic_inquiry.config import Config
            >>> config = Config.load()
            >>> service = await SearchService.from_config(config=config, project_id="my_project")

            >>> # Or load default config
            >>> service = await SearchService.from_config(project_id="my_project")
        """
        if config is None:
            config = Config.load()

        if project_id is None:
            project_id = config.storage.default_project_id
            if not project_id:
                raise ValueError(
                    "project_id must be provided or set as storage.default_project_id in configuration"
                )

        storage = await StorageFacade.from_config(config, project_id)
        return cls(storage=storage, config=config)

    async def hybrid_search(
        self,
        query_vector: Union[List[float], str],
        query_fts: str,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        rerank_by_graph: Optional[bool] = None,
        vector_column_name: str = "vector",
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        project_ids: Optional[List[str]] = None,
        boost_overview: Optional[bool] = None,
        content_preference: Optional[str] = None,
        content_preference_weight: float = 0.7,
        return_ambiguity: bool = False,
        branch: Optional[str] = None,
    ) -> List[SearchResult] | Dict[str, Any]:
        """Perform hybrid search combining vector and full-text search.

        Delegates to HybridSearchService for the actual search logic.

        Args:
            boost_overview: Whether to boost documentation/overview content.
                If None (default), auto-detects based on query content.
                Set explicitly to True/False to override auto-detection.
            content_preference: Preferred content type (e.g., "code", "documentation").
                Unlike hard filtering, this boosts matching content types while
                still including all results, enabling cross-content discovery.
            content_preference_weight: Boost factor (0.0-1.0). A value of 0.7 means
                matching results score 70% higher. Default: 0.7.
            return_ambiguity: If True, returns a dict with 'results' (List[SearchResult]) 
                             and 'ambiguity' (Dict).

        Returns:
            List of SearchResult or Dict with results and ambiguity info.
        """
        # Sanitize FTS query
        sanitized_fts_query = self._sanitize_fts_query(query_fts)

        # Auto-detect overview queries if not explicitly specified
        if boost_overview is None:
            boost_overview = self._is_overview_query(query_fts)
            if boost_overview:
                logger.debug("Auto-detected overview query, enabling doc boosting: %s", query_fts)

        # Delegate to HybridSearchService (still returns List[Dict] or Dict)
        search_result = await self._hybrid_search.hybrid_search(
            query_vector=query_vector,
            query_fts=query_fts,
            sanitized_fts_query=sanitized_fts_query,
            vector_search_fn=self.vector_search,
            fts_search_fn=self.fts_search,
            limit=limit,
            filters=filters,
            rerank_by_graph=rerank_by_graph,
            graph_rerank_fn=self._rerank_by_graph if rerank_by_graph else None,
            vector_column_name=vector_column_name,
            project_id=project_id,
            project_ids=project_ids,
            boost_overview=boost_overview,
            content_preference=content_preference,
            content_preference_weight=content_preference_weight,
            return_ambiguity=return_ambiguity
        )
        
        if return_ambiguity:
            result_dict = cast(Dict[str, Any], search_result)
            return {
                "results": dicts_to_search_results(cast(List[Dict[str, Any]], result_dict["results"]), source="hybrid"),
                "ambiguity": result_dict["ambiguity"]
            }
            
        return dicts_to_search_results(cast(List[Dict[str, Any]], search_result), source="hybrid")

    def _apply_deduplication(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply deduplication to search results if enabled.
        
        Args:
            results: Search results to deduplicate
        
        Returns:
            Deduplicated results if enabled, otherwise original results
        """
        if not self.config.search.deduplication.enabled:
            return results
        
        # Calculate diversity before deduplication
        diversity_before = self.deduplicator.calculate_diversity_score(results)
        
        # Apply deduplication
        deduplicated = self.deduplicator.deduplicate_results(results)
        
        # Calculate diversity after deduplication
        diversity_after = self.deduplicator.calculate_diversity_score(deduplicated)
        
        # Log diversity metrics
        logger.info(
            "Search deduplication: %d -> %d results, diversity: %.2f -> %.2f",
            len(results),
            len(deduplicated),
            diversity_before,
            diversity_after
        )
        
        return deduplicated

    # Compiled regex patterns for overview query detection (cached for performance)
    _OVERVIEW_PATTERNS = [
        re.compile(r'\b(readme|overview|architecture|getting[.\-_\s]?started)\b', re.IGNORECASE),
        re.compile(r'\b(what\s+(does|is)|how\s+(does|to|do)|purpose|intro(duction)?)\b', re.IGNORECASE),
        re.compile(r'\b(documentation|docs|guide|tutorial|manual)\b', re.IGNORECASE),
        re.compile(r'\b(project\s+structure|codebase|explain|describe)\b', re.IGNORECASE),
    ]

    def _is_overview_query(self, query: str) -> bool:
        """Detect if query is asking for overview/documentation content.

        Automatically detects queries that would benefit from documentation
        boosting, such as questions about project purpose, architecture,
        or getting started guides.

        Args:
            query: The search query text

        Returns:
            True if the query appears to be asking for overview/documentation

        Examples:
            >>> service._is_overview_query("what does this project do")
            True
            >>> service._is_overview_query("class Config implementation")
            False
        """
        if not query:
            return False
        return any(pattern.search(query) for pattern in self._OVERVIEW_PATTERNS)

    async def vector_search(
        self,
        query_vector: Union[List[float], str],
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        vector_column_name: str = "vector",
        table_name: str = "document_chunks",
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[SearchResult]:
        """Perform vector similarity search.

        Args:
            query_vector: Query vector for similarity search, or raw query text
                for AlloyDB server-side embedding
            limit: Maximum number of results
            filters: Optional additional filters
            vector_column_name: Name of the vector column
            table_name: Name of the table to search
            project_id: Project ID to filter by. Use CURRENT_PROJECT_ID for configured project,
                       specific ID for single project, or None for all projects.

        Returns:
            List of SearchResult with normalized scores and project_id in metadata
        """
        # Track the search operation - convert NoOpEventSystem to None for track_operation
        event_sys: Optional[EventSystem] = None if isinstance(self.event_system, NoOpEventSystem) else self.event_system
        async with track_operation(
            event_sys,
            "search.query",
            source="SearchService.vector_search",
            search_type="vector",
            **self._sanitize_query_metadata(
                query_vector=query_vector,
                limit=limit,
                filters=filters,
                table_name=table_name,
                project_id=project_id,
            ),
        ):
            try:
                self._metrics.increment("search.total")
                with self._metrics.track_latency("search.vector_search"):
                    if limit is None:
                        limit = self.config.search.default_limit

                    # Resolve project_id
                    resolved_project_id = self._resolve_project_id(project_id)

                    # Use StorageFacade for protocol-compliant search
                    # (table and vector_column are handled internally by the provider)
                    search_results = await self._storage_facade.vector_search(
                        query_vector=query_vector,  # type: ignore[arg-type]  # raw text reaches a list-only provider; see docs/backlog.md mypy-clean
                        limit=limit,
                        filters=filters,
                        project_id=resolved_project_id,
                    )

                    # Emit results event
                    await self.event_system.emit(
                        EventTypes.Search.RESULTS_RETURNED,
                        source="SearchService.vector_search",
                        status=EventStatus.PROGRESS,
                        result_count=len(search_results),
                        search_type="vector",
                    )

                    # Track result quality for self-audit
                    if search_results:
                        avg_score = sum(r.score for r in search_results) / len(search_results)
                        if avg_score < 0.4: # Low confidence
                            self._metrics.increment("search.low_confidence")

                    return search_results
            except Exception:
                # Error is automatically tracked by track_operation context manager
                self._metrics.increment("search.errors")
                raise

    async def fts_search(
        self,
        query_fts: str,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        table_name: str = "document_chunks",
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[SearchResult]:
        """Perform full-text search.

        Args:
            query_fts: Full-text search query
            limit: Maximum number of results
            filters: Optional additional filters
            table_name: Name of the table to search
            project_id: Project ID to filter by. Use CURRENT_PROJECT_ID for configured project,
                       specific ID for single project, or None for all projects.

        Returns:
            List of SearchResult with normalized scores and project_id in metadata
        """
        # Track the search operation - convert NoOpEventSystem to None for track_operation
        event_sys: Optional[EventSystem] = None if isinstance(self.event_system, NoOpEventSystem) else self.event_system
        async with track_operation(
            event_sys,
            "search.query",
            source="SearchService.fts_search",
            search_type="fts",
            **self._sanitize_query_metadata(
                query_fts=query_fts,
                limit=limit,
                filters=filters,
                table_name=table_name,
                project_id=project_id,
            ),
        ):
            try:
                self._metrics.increment("search.total")
                with self._metrics.track_latency("search.fts_search"):
                    if limit is None:
                        limit = self.config.search.default_limit

                    # Sanitize FTS query to prevent syntax errors
                    sanitized_query = self._sanitize_fts_query(query_fts)

                    # Resolve project_id
                    resolved_project_id = self._resolve_project_id(project_id)

                    # Use StorageFacade for protocol-compliant search
                    # (table is handled internally by the provider)
                    search_results = await self._storage_facade.fts_search(
                        query=sanitized_query,
                        limit=limit,
                        filters=filters,
                        project_id=resolved_project_id,
                    )

                    # Emit results event
                    await self.event_system.emit(
                        EventTypes.Search.RESULTS_RETURNED,
                        source="SearchService.fts_search",
                        status=EventStatus.PROGRESS,
                        result_count=len(search_results),
                        search_type="fts",
                    )

                    # Track result quality for self-audit
                    if search_results:
                        avg_score = sum(r.score for r in search_results) / len(search_results)
                        if avg_score < 0.4: # Low confidence
                            self._metrics.increment("search.low_confidence")

                    return search_results
            except Exception:
                # Error is automatically tracked by track_operation context manager
                self._metrics.increment("search.errors")
                raise

    async def advanced_filter_search(
        self,
        table_name: str,
        filters: Dict[str, Any],
        limit: Optional[int] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Perform advanced filtering on a table.

        Args:
            table_name: Name of the table to query
            filters: Filter expressions
            limit: Maximum number of results
            project_id: Project ID to filter by. Use CURRENT_PROJECT_ID for configured project,
                       specific ID for single project, or None for all projects.

        Returns:
            Matching rows as dicts, each carrying its project_id
        """
        if limit is None:
            limit = self.config.search.max_limit

        # Resolve project_id
        resolved_project_id = self._resolve_project_id(project_id)

        # Use StorageFacade for protocol-compliant search
        return await self._storage_facade.advanced_filter(
            table_name=table_name,
            filters=filters,
            limit=limit if limit is not None else self.config.search.default_limit,
            project_id=resolved_project_id,
        )

    async def execute(self, query: QuerySpec) -> List[SearchResult]:
        """Execute a search query from a QuerySpec.

        Routes to the appropriate search method based on QuerySpec configuration:
        - Hybrid search: when both vector and fts_query are set
        - Vector search: when only vector is set
        - FTS search: when only fts_query is set
        - Filter search: when neither vector nor fts_query is set

        Args:
            query: QuerySpec defining the search parameters

        Returns:
            List of SearchResult matching the query

        Raises:
            ValueError: If multi-project query requested for non-hybrid search

        Example:
            >>> from agentic_inquiry.database.query_spec import QuerySpec
            >>> spec = QuerySpec(
            ...     table="document_chunks",
            ...     vector=[0.1] * 384,
            ...     fts_query="authentication",
            ...     limit=10,
            ...     project_ids=["project_123"]
            ... )
            >>> results = await search_service.execute(spec)
        """
        # Resolve project scope
        project_id: Optional[str] = None
        project_ids: Optional[List[str]] = None

        if query.project_ids is not None:
            if len(query.project_ids) == 0:
                # Empty list means no valid scope - return no results
                return []
            elif len(query.project_ids) == 1:
                # Single project - use project_id parameter
                project_id = query.project_ids[0]
            else:
                # Multiple projects - only supported for hybrid search
                project_ids = query.project_ids
        # else: None means cross-project (all projects) - leave project_id as None

        # Convert Filter to dict for type compatibility
        # The underlying query_builder handles both Filter AST and dict
        filters = query.filters  # type: ignore[assignment]

        # Route based on query type
        if query.is_hybrid_search():
            assert query.vector is not None  # Type narrowing
            assert query.fts_query is not None  # Type narrowing
            result = await self.hybrid_search(
                query_vector=query.vector,
                query_fts=query.fts_query,
                limit=query.limit,
                filters=filters,  # type: ignore[arg-type]
                project_id=project_id,
                project_ids=project_ids,
            )
            return cast(List[SearchResult], result)
        elif query.is_vector_search():
            # Multi-project not supported for vector-only search
            if project_ids is not None:
                raise ValueError(
                    "Multi-project search (project_ids with >1 project) "
                    "is only supported for hybrid search. "
                    "Use hybrid search or query projects individually."
                )
            assert query.vector is not None  # Type narrowing
            return await self.vector_search(
                query_vector=query.vector,
                table_name=query.table,
                limit=query.limit,
                filters=filters,  # type: ignore[arg-type]
                project_id=project_id,
            )
        elif query.is_fts_search():
            # Multi-project not supported for FTS-only search
            if project_ids is not None:
                raise ValueError(
                    "Multi-project search (project_ids with >1 project) "
                    "is only supported for hybrid search. "
                    "Use hybrid search or query projects individually."
                )
            assert query.fts_query is not None  # Type narrowing
            return await self.fts_search(
                query_fts=query.fts_query,
                table_name=query.table,
                limit=query.limit,
                filters=filters,  # type: ignore[arg-type]
                project_id=project_id,
            )
        else:
            # Filter-only query
            if project_ids is not None:
                raise ValueError(
                    "Multi-project search (project_ids with >1 project) "
                    "is only supported for hybrid search. "
                    "Use hybrid search or query projects individually."
                )
            rows = await self.advanced_filter_search(
                table_name=query.table,
                filters=filters if filters else {},  # type: ignore[arg-type]
                limit=query.limit,
                project_id=project_id,
            )
            return dicts_to_search_results(rows, source="filter")

    async def graph_filtered_search(
        self,
        graph_filters: Dict[str, Any],
        search_query_vector: Optional[List[float]] = None,
        search_query_fts: Optional[str] = None,
        limit: Optional[int] = None,
        depth: Optional[int] = None,
        vector_column_name: str = "vector",
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """Perform graph-filtered search.

        Delegates to GraphSearchService for the actual search logic.

        Returns:
            List of SearchResult with graph source
        """
        # GraphSearchService may return List[Dict] or List[SearchResult] depending on path
        results: Union[List[Dict[str, Any]], List[SearchResult]] = await self._graph_search.graph_filtered_search(
            graph_filters=graph_filters,
            search_query_vector=search_query_vector,
            search_query_fts=search_query_fts,
            hybrid_search_fn=self.hybrid_search,
            vector_search_fn=self.vector_search,
            limit=limit,
            depth=depth,
            vector_column_name=vector_column_name,
            project_id=project_id,
            project_ids=project_ids,
        )
        # If results are dicts, convert them. Otherwise, they are already SearchResult objects.
        if not results or isinstance(results[0], dict):
            return dicts_to_search_results(cast(List[Dict[str, Any]], results), source="graph")  # type: ignore[return-value]
        
        # At this point, results must be List[SearchResult]
        return cast(List[SearchResult], results)

    async def _graph_ranking_supported(self) -> bool:
        """Check if graph ranking data is available.

        Uses StorageFacade.has_graph_ranking_data() to check runtime availability
        of ranking signals (not just capability).
        """
        try:
            return await self._storage_facade.has_graph_ranking_data()
        except Exception:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to check for graph ranking capability",
                exc_info=True,
            )
            return False

    async def _fallback_search_without_graph(
        self,
        *,
        search_query_vector: Optional[List[float]],
        search_query_fts: Optional[str],
        limit: int,
        vector_column_name: str,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        if search_query_vector is not None and search_query_fts is not None:
            results = await self.hybrid_search(
                query_vector=search_query_vector,
                query_fts=search_query_fts,
                limit=limit,
                rerank_by_graph=False,
                vector_column_name=vector_column_name,
                project_id=project_id,
                project_ids=project_ids,
            )
            return cast(List[SearchResult], results)
        if search_query_vector is not None:
            return await self.vector_search(
                query_vector=search_query_vector,
                limit=limit,
                vector_column_name=vector_column_name,
                project_id=project_id,
            )
        if search_query_fts is not None:
            return await self.fts_search(
                query_fts=search_query_fts,
                limit=limit,
                project_id=project_id,
            )
        return []

    async def _rerank_by_graph(self, search_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rerank search results by graph pagerank scores.
        
        Delegates to GraphSearchService for the actual reranking logic.
        """
        return await self._graph_search.rerank_by_graph(search_results)

    async def enrich_with_graph_context(
        self,
        search_results: List[Dict[str, Any]],
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Enrich search results with graph context.
        
        Delegates to GraphSearchService for the actual enrichment logic.
        """
        return await self._graph_search.enrich_with_graph_context(
            search_results=search_results,
            project_id=project_id,
        )

    def _enrich_results_with_project_id(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enrich search results with project_id in metadata.
        
        Args:
            results: List of search results from database
        
        Returns:
            Results with project_id added to metadata field
        """
        for result in results:
            if "project_id" in result:
                # Move project_id to metadata if not already there
                if "metadata" not in result:
                    result["metadata"] = {}
                if isinstance(result["metadata"], dict):
                    result["metadata"]["project_id"] = result["project_id"]
        return results

    async def traverse_relationships(
        self,
        entity_id: str,
        relationship_types: Optional[List[str]] = None,
        direction: str = "outgoing",
        max_depth: int = 1,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        include_metadata: bool = True,
    ) -> Dict[str, Any]:
        """Traverse relationships from an entity in the knowledge graph.
        
        Delegates to GraphSearchService for the actual traversal logic.
        """
        return await self._graph_search.traverse_relationships(
            entity_id=entity_id,
            relationship_types=relationship_types,
            direction=direction,
            max_depth=max_depth,
            project_id=project_id,
            include_metadata=include_metadata,
        )

    async def resolve_entity(
        self,
        entity_name: str,
        entity_type: Optional[str] = None,
        context: Optional[str] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        similarity_threshold: float = 0.7,
    ) -> Dict[str, Any]:
        """Resolve an entity by name with disambiguation support.
        
        Delegates to GraphSearchService for the actual resolution logic.
        """
        return await self._graph_search.resolve_entity(
            entity_name=entity_name,
            entity_type=entity_type,
            context=context,
            project_id=project_id,
            similarity_threshold=similarity_threshold,
        )
