"""Canonical query specification for database operations.

This module defines the unified query format used across all backends.
QuerySpec captures the application's intent without backend-specific details.

See: docs/design/query-semantics.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from agentic_inquiry.database.filters import Filter
from agentic_inquiry.mcp.utils.validation import (
    validate_column_name,
    validate_column_names,
    validate_table_name,
    ColumnNameValidationError,
)


@dataclass
class QuerySpec:
    """Specification for a database query.

    QuerySpec captures the application's query intent in a backend-agnostic way.
    Adapters translate QuerySpec to backend-specific query formats.

    Attributes:
        table: Logical table name (required). Must match schema definitions.
        filters: Optional unified Filter AST for row filtering.
        limit: Maximum number of results to return (default: 100).
        offset: Number of results to skip for pagination (default: 0).
        vector: Optional query vector for similarity search.
        vector_column: Column containing vectors (default: "vector").
        fts_query: Optional full-text search query string.
        fts_columns: Columns to search for FTS (default: empty = use table default).
        project_ids: Optional list of project IDs to scope the query.
        order_by: Optional column name for sorting results.
        order_desc: Sort in descending order (default: True).
        select_columns: Optional list of columns to return (None = all columns).

    Invariants:
        - `table` must be a valid logical table name
        - `offset` applies to post-filtered, post-sorted results
        - If `select_columns` is set, it MUST include "id" for result identity
        - `order_by` must reference a valid column in the table

    Project Scoping:
        - If `project_ids` is None: query spans all projects (cross-project)
        - If `project_ids` is set: results filtered to those projects
        - If `project_ids` is empty list []: returns no results (no valid scope)
        - Combined with `filters` via AND

    Capability-Based Degradation:
        - If backend can't support hybrid search: adapter MUST reject, not silently degrade
        - App layer handles separate vector + FTS + merge if needed
        - Offset emulation permitted if backend lacks it (with performance note)

    Example:
        >>> spec = QuerySpec(
        ...     table="document_chunks",
        ...     filters=eq("content_type", "CODE"),
        ...     limit=20,
        ...     vector=[0.1, 0.2, ...],  # 384 dimensions
        ...     project_ids=["project_123"],
        ...     order_by="indexed_at",
        ...     order_desc=True
        ... )
    """

    # Required
    table: str

    # Filtering
    filters: Optional[Filter] = None

    # Pagination (stable: offset applies to post-filtered results)
    limit: int = 100
    offset: int = 0

    # Vector search (optional)
    vector: Optional[List[float]] = None
    vector_column: str = "vector"

    # FTS search (optional)
    fts_query: Optional[str] = None
    fts_columns: List[str] = field(default_factory=list)

    # Multi-project scope (optional)
    project_ids: Optional[List[str]] = None

    # Sorting
    order_by: Optional[str] = None
    order_desc: bool = True

    # Column selection
    select_columns: Optional[List[str]] = None

    def __post_init__(self) -> None:
        """Validate query spec."""
        self._validate()

    def _validate(self) -> None:
        """Validate query spec constraints.

        SEC-006: Validates column and table names to prevent SQL injection.
        """
        # Table is required
        if not self.table:
            raise ValueError("QuerySpec requires 'table' to be set")

        # SEC-006: Validate table name (allow_unknown=True for dynamic tables)
        try:
            validate_table_name(self.table, allow_unknown=True)
        except ColumnNameValidationError as e:
            raise ValueError(f"QuerySpec 'table': {e}")

        # SEC-006: Validate vector_column
        try:
            validate_column_name(self.vector_column, field_name="vector_column")
        except ColumnNameValidationError as e:
            raise ValueError(f"QuerySpec 'vector_column': {e}")

        # SEC-006: Validate order_by if set
        if self.order_by is not None:
            try:
                validate_column_name(self.order_by, field_name="order_by")
            except ColumnNameValidationError as e:
                raise ValueError(f"QuerySpec 'order_by': {e}")

        # SEC-006: Validate fts_columns
        if self.fts_columns:
            try:
                validate_column_names(
                    self.fts_columns,
                    field_name="fts_columns",
                    allow_nested=False  # FTS columns are simple column names
                )
            except ColumnNameValidationError as e:
                raise ValueError(f"QuerySpec 'fts_columns': {e}")

        # SEC-006: Validate select_columns
        if self.select_columns is not None:
            try:
                validate_column_names(
                    self.select_columns,
                    field_name="select_columns",
                    allow_nested=True  # Allow nested access like metadata.type
                )
            except ColumnNameValidationError as e:
                raise ValueError(f"QuerySpec 'select_columns': {e}")

        # Limit must be positive
        if self.limit <= 0:
            raise ValueError(f"QuerySpec 'limit' must be positive, got {self.limit}")

        # Offset must be non-negative
        if self.offset < 0:
            raise ValueError(
                f"QuerySpec 'offset' must be non-negative, got {self.offset}"
            )

        # If select_columns is set, it must include 'id' for result identity
        if self.select_columns is not None and "id" not in self.select_columns:
            raise ValueError(
                "QuerySpec 'select_columns' must include 'id' for result identity"
            )

    def is_vector_search(self) -> bool:
        """Check if this is a vector search query."""
        return self.vector is not None

    def is_fts_search(self) -> bool:
        """Check if this is a full-text search query."""
        return self.fts_query is not None

    def is_hybrid_search(self) -> bool:
        """Check if this is a hybrid (vector + FTS) search query."""
        return self.is_vector_search() and self.is_fts_search()

    def is_filter_only(self) -> bool:
        """Check if this is a filter-only query (no search ranking)."""
        return not self.is_vector_search() and not self.is_fts_search()

    def is_cross_project(self) -> bool:
        """Check if this query spans multiple projects."""
        return self.project_ids is not None and len(self.project_ids) > 1

    def with_filters(self, filters: Optional[Filter]) -> QuerySpec:
        """Create a new QuerySpec with updated filters.

        Args:
            filters: New filter to apply

        Returns:
            New QuerySpec with updated filters
        """
        return QuerySpec(
            table=self.table,
            filters=filters,
            limit=self.limit,
            offset=self.offset,
            vector=self.vector,
            vector_column=self.vector_column,
            fts_query=self.fts_query,
            fts_columns=self.fts_columns,
            project_ids=self.project_ids,
            order_by=self.order_by,
            order_desc=self.order_desc,
            select_columns=self.select_columns,
        )

    def with_pagination(self, limit: int, offset: int = 0) -> QuerySpec:
        """Create a new QuerySpec with updated pagination.

        Args:
            limit: Maximum results to return
            offset: Results to skip

        Returns:
            New QuerySpec with updated pagination
        """
        return QuerySpec(
            table=self.table,
            filters=self.filters,
            limit=limit,
            offset=offset,
            vector=self.vector,
            vector_column=self.vector_column,
            fts_query=self.fts_query,
            fts_columns=self.fts_columns,
            project_ids=self.project_ids,
            order_by=self.order_by,
            order_desc=self.order_desc,
            select_columns=self.select_columns,
        )

    def with_project_scope(self, project_ids: Optional[List[str]]) -> QuerySpec:
        """Create a new QuerySpec with updated project scope.

        Args:
            project_ids: List of project IDs to scope to, or None for cross-project

        Returns:
            New QuerySpec with updated project scope
        """
        return QuerySpec(
            table=self.table,
            filters=self.filters,
            limit=self.limit,
            offset=self.offset,
            vector=self.vector,
            vector_column=self.vector_column,
            fts_query=self.fts_query,
            fts_columns=self.fts_columns,
            project_ids=project_ids,
            order_by=self.order_by,
            order_desc=self.order_desc,
            select_columns=self.select_columns,
        )


# ============================================================================
# QuerySpec Builders
# ============================================================================
# These factory functions make it easy to construct QuerySpec objects for
# common search patterns.


def vector_query(
    vector: List[float],
    table: str = "document_chunks",
    limit: int = 10,
    project_id: Optional[str] = None,
    filters: Optional[Filter] = None,
    vector_column: str = "vector",
) -> QuerySpec:
    """Build a QuerySpec for vector similarity search.

    Args:
        vector: Query embedding vector
        table: Table to search (default: document_chunks)
        limit: Maximum results to return
        project_id: Optional project ID to scope the search
        filters: Optional additional filters
        vector_column: Column containing vectors (default: vector)

    Returns:
        QuerySpec configured for vector search

    Example:
        >>> spec = vector_query(
        ...     vector=[0.1] * 384,
        ...     table="document_chunks",
        ...     limit=20,
        ...     project_id="my_project"
        ... )
        >>> results = await search_service.execute(spec)
    """
    return QuerySpec(
        table=table,
        vector=vector,
        vector_column=vector_column,
        limit=limit,
        filters=filters,
        project_ids=[project_id] if project_id else None,
    )


def fts_query(
    query: str,
    table: str = "document_chunks",
    limit: int = 10,
    project_id: Optional[str] = None,
    filters: Optional[Filter] = None,
    fts_columns: Optional[List[str]] = None,
) -> QuerySpec:
    """Build a QuerySpec for full-text search.

    Args:
        query: Full-text search query string
        table: Table to search (default: document_chunks)
        limit: Maximum results to return
        project_id: Optional project ID to scope the search
        filters: Optional additional filters
        fts_columns: Columns to search (default: table default)

    Returns:
        QuerySpec configured for FTS search

    Example:
        >>> spec = fts_query(
        ...     query="authentication error",
        ...     table="document_chunks",
        ...     limit=20,
        ...     project_id="my_project"
        ... )
        >>> results = await search_service.execute(spec)
    """
    return QuerySpec(
        table=table,
        fts_query=query,
        fts_columns=fts_columns or [],
        limit=limit,
        filters=filters,
        project_ids=[project_id] if project_id else None,
    )


def hybrid_query(
    vector: List[float],
    fts: str,
    table: str = "document_chunks",
    limit: int = 10,
    project_id: Optional[str] = None,
    project_ids: Optional[List[str]] = None,
    filters: Optional[Filter] = None,
    vector_column: str = "vector",
    fts_columns: Optional[List[str]] = None,
) -> QuerySpec:
    """Build a QuerySpec for hybrid (vector + FTS) search.

    Hybrid search combines vector similarity with keyword matching for
    better relevance. Supports multi-project search via project_ids.

    Note: If both project_id and project_ids are provided, project_ids
    takes precedence.

    Args:
        vector: Query embedding vector
        fts: Full-text search query string
        table: Table to search (default: document_chunks)
        limit: Maximum results to return
        project_id: Single project ID (use project_ids for multiple)
        project_ids: List of project IDs for multi-project search (takes precedence)
        filters: Optional additional filters
        vector_column: Column containing vectors (default: vector)
        fts_columns: Columns to search for FTS (default: table default)

    Returns:
        QuerySpec configured for hybrid search

    Example:
        >>> spec = hybrid_query(
        ...     vector=[0.1] * 384,
        ...     fts="authentication error",
        ...     limit=20,
        ...     project_ids=["project_a", "project_b"]
        ... )
        >>> results = await search_service.execute(spec)
    """
    # Resolve project scope
    resolved_project_ids: Optional[List[str]] = None
    if project_ids is not None:
        resolved_project_ids = project_ids
    elif project_id is not None:
        resolved_project_ids = [project_id]

    return QuerySpec(
        table=table,
        vector=vector,
        vector_column=vector_column,
        fts_query=fts,
        fts_columns=fts_columns or [],
        limit=limit,
        filters=filters,
        project_ids=resolved_project_ids,
    )


def filter_query(
    table: str,
    filters: Optional[Filter] = None,
    limit: int = 100,
    offset: int = 0,
    project_id: Optional[str] = None,
    order_by: Optional[str] = None,
    order_desc: bool = True,
) -> QuerySpec:
    """Build a QuerySpec for filter-only queries.

    Filter queries retrieve records based on field matching without
    any semantic ranking.

    Args:
        table: Table to query
        filters: Filter expressions (Filter AST)
        limit: Maximum results to return
        offset: Number of results to skip
        project_id: Optional project ID to scope the query
        order_by: Optional column to sort by
        order_desc: Sort descending (default: True)

    Returns:
        QuerySpec configured for filter-only query

    Example:
        >>> from agentic_inquiry.database.filter_ast import eq, and_
        >>> spec = filter_query(
        ...     table="graph_entities",
        ...     filters=and_(eq("type", "class"), eq("name", "Config")),
        ...     limit=10,
        ...     project_id="my_project"
        ... )
        >>> results = await search_service.execute(spec)
    """
    return QuerySpec(
        table=table,
        filters=filters,
        limit=limit,
        offset=offset,
        project_ids=[project_id] if project_id else None,
        order_by=order_by,
        order_desc=order_desc,
    )
