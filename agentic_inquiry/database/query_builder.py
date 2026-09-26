"""Query builder for LanceDB operations.

This module provides the LanceDBQueryBuilder class for constructing
safe, validated database queries.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Union

from agentic_inquiry.constants import CURRENT_PROJECT_ID
from agentic_inquiry.database.filters import Filter, translate_filter, translate_dict_filters
from agentic_inquiry.search.query_sanitizer import QuerySanitizer

_fts_sanitizer = QuerySanitizer()

logger = logging.getLogger(__name__)


def _is_stale_table_error(error: Exception) -> bool:
    """Check if an error indicates a stale table reference.

    LanceDB raises errors when cached table references point to
    deleted or moved data files. This function detects such errors.

    Args:
        error: Exception to check

    Returns:
        True if error indicates stale table data
    """
    error_str = str(error).lower()
    # LanceDB file not found errors
    if "not found" in error_str and ".lance" in error_str:
        return True
    # LanceDB IO errors on missing files
    if "lancedb" in error_str and "io" in error_str:
        return True
    if "lance error" in error_str:
        return True
    return False


class LanceDBQueryBuilder:
    """Builds safe LanceDB queries with proper filtering and validation.

    This class handles query construction for vector search, full-text search,
    hybrid search, and graph queries. It ensures proper filter construction
    and project isolation.

    This class extracts query-building logic from LanceDBManager to improve
    maintainability and adhere to Single Responsibility Principle.
    """

    def __init__(
        self,
        get_table_fn: Callable[[str], Any],
        run_sync_fn: Callable[[Callable], Any],
        project_id: Optional[str] = None,
        invalidate_cache_fn: Optional[Callable[[str], Any]] = None,
    ):
        """Initialize query builder.

        Args:
            get_table_fn: Function to get table by name (async)
            run_sync_fn: Function to run sync operations in async context
            project_id: Optional project ID for filtering
            invalidate_cache_fn: Optional async function to invalidate table cache
        """
        self._get_table = get_table_fn
        self._run_sync = run_sync_fn
        self._project_id = project_id
        self._invalidate_cache = invalidate_cache_fn

    async def _search_with_stale_retry(
        self,
        table_name: str,
        table: Any,
        run: Callable[[Any], List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Run ``run(table)``, retrying once on a re-opened table if it is stale.

        A cached table handle goes stale when another process drops and
        re-creates the table. ``run`` receives the table rather than closing
        over it, so the retry cannot touch the stale handle.
        """
        try:
            return await self._run_sync(lambda: run(table))
        except Exception as e:
            if not (_is_stale_table_error(e) and self._invalidate_cache):
                raise
            logger.warning(
                "Stale table detected for '%s', invalidating cache and retrying: %s",
                table_name,
                str(e)[:100],
            )
            await self._invalidate_cache(table_name)
            fresh_table = await self._get_table(table_name)
            if fresh_table is None:
                return []
            return await self._run_sync(lambda: run(fresh_table))

    async def vector_search(
        self,
        table_name: str,
        query_vector: List[float],
        vector_column_name: str,
        limit: int,
        filters: Optional[Union[Dict[str, Any], Filter]] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Perform vector similarity search.

        Args:
            table_name: Name of the table to search
            query_vector: Query vector for similarity search
            vector_column_name: Name of the vector column
            limit: Maximum number of results
            filters: Optional additional filters
            project_id: Project ID to filter by. Use CURRENT_PROJECT_ID for configured project,
                       specific ID for single project, or None for all projects.

        Returns:
            List of matching records
        """
        table = await self._get_table(table_name)
        if table is None:
            return []

        # Add project_id filter if specified
        filters = self._add_project_filter(filters, project_id)
        filter_expression = self._filters_to_expression(filters)

        def _run_search(table: Any) -> List[Dict[str, Any]]:
            query = table.search(query_vector, vector_column_name=vector_column_name)
            if filter_expression:
                query = query.where(filter_expression)
            # Use refine_factor for accurate distance calculations if available
            if hasattr(query, 'refine_factor'):
                query = query.refine_factor(10)
            return query.limit(limit).to_list()

        return await self._search_with_stale_retry(table_name, table, _run_search)

    async def fts_search(
        self,
        table_name: str,
        query: str,
        limit: int,
        filters: Optional[Union[Dict[str, Any], Filter]] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Perform full-text search.

        Args:
            table_name: Name of the table to search
            query: Search query string
            limit: Maximum number of results
            filters: Optional additional filters
            project_id: Project ID to filter by. Use CURRENT_PROJECT_ID for configured project,
                       specific ID for single project, or None for all projects.

        Returns:
            List of matching records
        """
        table = await self._get_table(table_name)
        if table is None:
            return []

        # Add project_id filter if specified
        filters = self._add_project_filter(filters, project_id)
        filter_expression = self._filters_to_expression(filters)
        safe_query = _fts_sanitizer.sanitize(query)

        def _run_search(table: Any) -> List[Dict[str, Any]]:
            query_builder = table.search(safe_query, query_type="fts")
            if filter_expression:
                query_builder = query_builder.where(filter_expression)
            return query_builder.limit(limit).to_list()

        return await self._search_with_stale_retry(table_name, table, _run_search)

    async def hybrid_search(
        self,
        table_name: str,
        query: str,
        query_vector: List[float],
        vector_column_name: str,
        limit: int,
        filters: Optional[Union[Dict[str, Any], Filter]] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        reranker: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Perform hybrid search combining vector and FTS.

        Args:
            table_name: Name of the table to search
            query: Search query string
            query_vector: Query vector for similarity search
            vector_column_name: Name of the vector column
            limit: Maximum number of results
            filters: Optional additional filters (dict or Filter AST)
            project_id: Project ID to filter by
            reranker: Optional reranker for result fusion

        Returns:
            List of matching records
        """
        table = await self._get_table(table_name)
        if table is None:
            return []

        # Add project_id filter if specified
        filters = self._add_project_filter(filters, project_id)
        filter_expression = self._filters_to_expression(filters)

        def _run_search(table: Any) -> List[Dict[str, Any]]:
            # For hybrid search with explicit vector and text, we use query_type="hybrid"
            # without a query string, then set text() and vector() explicitly
            query_builder = table.search(query_type="hybrid")
            query_builder = query_builder.text(query).vector(query_vector)

            if filter_expression:
                query_builder = query_builder.where(filter_expression)

            if reranker:
                query_builder = query_builder.rerank(reranker=reranker)

            return query_builder.limit(limit).to_list()

        return await self._search_with_stale_retry(table_name, table, _run_search)

    async def advanced_filter(
        self,
        table_name: str,
        filters: Optional[Union[Dict[str, Any], Filter]] = None,
        limit: int = 100,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Query with advanced filtering.

        Args:
            table_name: Name of the table to query
            filters: Filter conditions (dict or Filter AST)
            limit: Maximum number of results
            project_id: Project ID to filter by

        Returns:
            List of matching records
        """
        table = await self._get_table(table_name)
        if table is None:
            return []

        # Add project_id filter if specified (only for dict filters)
        combined_filters = self._add_project_filter(filters, project_id)
        filter_expression = self._filters_to_expression(combined_filters)

        def _run_query(table: Any) -> List[Dict[str, Any]]:
            query = table.search()
            if filter_expression:
                query = query.where(filter_expression)
            return query.limit(limit).to_list()

        return await self._search_with_stale_retry(table_name, table, _run_query)

    async def query_entities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Query graph entities.
        
        Args:
            filters: Optional filter conditions
            limit: Maximum number of results
            project_id: Project ID to filter by
            
        Returns:
            List of matching graph entities
        """
        return await self.advanced_filter(
            table_name="graph_entities",
            filters=filters,
            limit=limit,
            project_id=project_id,
        )

    async def query_relationships(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Query graph relationships.
        
        Args:
            filters: Optional filter conditions
            limit: Maximum number of results
            project_id: Project ID to filter by
            
        Returns:
            List of matching graph relationships
        """
        return await self.advanced_filter(
            table_name="graph_relationships",
            filters=filters,
            limit=limit,
            project_id=project_id,
        )

    async def query_across_projects(
        self,
        table_name: str,
        filters: Dict[str, Any],
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query across all projects without project filtering.
        
        Args:
            table_name: Name of the table to query
            filters: Filter conditions
            limit: Maximum number of results
            
        Returns:
            List of matching records
        """
        return await self.advanced_filter(
            table_name=table_name,
            filters=filters,
            limit=limit,
            project_id=None,  # No project filtering
        )

    async def vector_search_across_projects(
        self,
        table_name: str,
        query_vector: List[float],
        vector_column_name: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform vector search across all projects.
        
        Args:
            table_name: Name of the table to search
            query_vector: Query embedding vector
            vector_column_name: Name of the vector column
            limit: Maximum number of results
            filters: Optional filters to apply
            
        Returns:
            List of matching records
        """
        return await self.vector_search(
            table_name=table_name,
            query_vector=query_vector,
            vector_column_name=vector_column_name,
            limit=limit,
            filters=filters,
            project_id=None,  # No project filtering
        )

    async def fts_search_across_projects(
        self,
        table_name: str,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform FTS search across all projects.
        
        Args:
            table_name: Name of the table to search
            query: Search query string
            limit: Maximum number of results
            filters: Optional filters to apply
            
        Returns:
            List of matching records
        """
        return await self.fts_search(
            table_name=table_name,
            query=query,
            limit=limit,
            filters=filters,
            project_id=None,  # No project filtering
        )

    def _add_project_filter(
        self,
        filters: Optional[Union[Dict[str, Any], Filter]],
        project_id: Optional[str],
    ) -> Optional[Union[Dict[str, Any], Filter]]:
        """Add project filter to existing filters.

        Args:
            filters: Existing filters (dict or Filter AST)
            project_id: Project ID to filter by. Use CURRENT_PROJECT_ID for configured project,
                       specific ID for single project, or None for all projects.

        Returns:
            Updated filters with project filter added
        """
        from agentic_inquiry.database.filters import eq, and_

        # Handle CURRENT_PROJECT_ID
        if project_id == CURRENT_PROJECT_ID:
            project_id = self._project_id

        # No filtering if project_id is None
        if project_id is None:
            return filters

        # Handle Filter AST
        if isinstance(filters, Filter):
            project_filter = eq("project_id", project_id)
            return and_(project_filter, filters)

        # Handle dict filters (legacy path)
        if filters is None:
            filters = {}
        else:
            filters = filters.copy()  # Don't modify original

        filters["project_id"] = project_id
        return filters

    def _filters_to_expression(
        self, filters: Optional[Union[Dict[str, Any], Filter]]
    ) -> str:
        """Convert filter dict or Filter AST to SQL expression.

        Delegates to agentic_inquiry.database.filters for consolidated filter translation.

        Args:
            filters: Dictionary of field: value pairs OR Filter AST

        Returns:
            SQL filter expression string
        """
        if filters is None:
            return ""

        # Handle Filter AST directly
        if isinstance(filters, Filter):
            result = translate_filter(filters)
            return result if result else ""

        # Handle dict filters using consolidated translator
        result = translate_dict_filters(filters)
        return result if result else ""
