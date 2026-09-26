"""Database query optimization utilities for MCP."""

import time
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class QueryProfile:
    """Profile information for a database query."""

    query_type: str
    table_name: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[int] = None
    rows_returned: int = 0
    filters: Dict[str, Any] = field(default_factory=dict)
    limit: Optional[int] = None
    status: str = "running"  # running, success, error
    error_message: Optional[str] = None

    def complete(
        self,
        rows_returned: int = 0,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> None:
        """Mark query as complete.

        Args:
            rows_returned: Number of rows returned
            status: Query status (success or error)
            error_message: Optional error message
        """
        self.end_time = time.time()
        self.duration_ms = int((self.end_time - self.start_time) * 1000)
        self.rows_returned = rows_returned
        self.status = status
        self.error_message = error_message


@dataclass
class QueryStatistics:
    """Aggregated statistics for a query type."""

    query_type: str
    table_name: str
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    total_duration_ms: int = 0
    avg_duration_ms: float = 0.0
    min_duration_ms: Optional[int] = None
    max_duration_ms: Optional[int] = None
    total_rows: int = 0
    avg_rows: float = 0.0

    def update(self, profile: QueryProfile) -> None:
        """Update statistics with a new query profile.

        Args:
            profile: Query profile to add
        """
        if profile.duration_ms is None:
            return

        self.total_queries += 1

        if profile.status == "success":
            self.successful_queries += 1
        else:
            self.failed_queries += 1

        self.total_duration_ms += profile.duration_ms
        self.avg_duration_ms = self.total_duration_ms / self.total_queries

        if self.min_duration_ms is None or profile.duration_ms < self.min_duration_ms:
            self.min_duration_ms = profile.duration_ms

        if self.max_duration_ms is None or profile.duration_ms > self.max_duration_ms:
            self.max_duration_ms = profile.duration_ms

        self.total_rows += profile.rows_returned
        self.avg_rows = self.total_rows / self.total_queries

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "query_type": self.query_type,
            "table_name": self.table_name,
            "total_queries": self.total_queries,
            "successful_queries": self.successful_queries,
            "failed_queries": self.failed_queries,
            "success_rate_percent": (
                self.successful_queries / self.total_queries * 100
                if self.total_queries > 0
                else 0.0
            ),
            "duration_ms": {
                "total": self.total_duration_ms,
                "avg": round(self.avg_duration_ms, 2),
                "min": self.min_duration_ms,
                "max": self.max_duration_ms,
            },
            "rows": {
                "total": self.total_rows,
                "avg": round(self.avg_rows, 2),
            },
        }


class QueryOptimizer:
    """Optimize and profile database queries.

    Features:
    - Query profiling and timing
    - Query statistics tracking
    - Slow query detection
    - Index recommendations
    """

    def __init__(self, slow_query_threshold_ms: int = 1000):
        """Initialize query optimizer.

        Args:
            slow_query_threshold_ms: Threshold for slow query detection
        """
        self.slow_query_threshold_ms = slow_query_threshold_ms
        self.query_profiles: List[QueryProfile] = []
        self.query_stats: Dict[str, QueryStatistics] = {}
        self.active_queries: Dict[str, QueryProfile] = {}

    def start_query(
        self,
        query_type: str,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> str:
        """Start profiling a query.

        Args:
            query_type: Type of query (search, filter, insert, etc.)
            table_name: Name of the table
            filters: Optional filters applied
            limit: Optional result limit

        Returns:
            Query ID for tracking
        """
        query_id = f"{query_type}:{table_name}:{time.time()}"

        profile = QueryProfile(
            query_type=query_type,
            table_name=table_name,
            start_time=time.time(),
            filters=filters or {},
            limit=limit,
        )

        self.active_queries[query_id] = profile
        return query_id

    def end_query(
        self,
        query_id: str,
        rows_returned: int = 0,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> None:
        """End profiling a query.

        Args:
            query_id: Query ID from start_query
            rows_returned: Number of rows returned
            status: Query status (success or error)
            error_message: Optional error message
        """
        if query_id not in self.active_queries:
            return

        profile = self.active_queries.pop(query_id)
        profile.complete(
            rows_returned=rows_returned, status=status, error_message=error_message
        )

        # Add to history
        self.query_profiles.append(profile)

        # Update statistics
        stats_key = f"{profile.query_type}:{profile.table_name}"
        if stats_key not in self.query_stats:
            self.query_stats[stats_key] = QueryStatistics(
                query_type=profile.query_type, table_name=profile.table_name
            )

        self.query_stats[stats_key].update(profile)

    # NOTE: batch_insert and batch_get_by_ids methods were removed as dead code.
    # They called non-existent db_manager.insert() method and used incorrect
    # filter format. If batch operations are needed, use:
    # - db_manager.add_rows() for batch inserts
    # - db_manager.advanced_filter() with proper filter format for batch retrieval

    def get_slow_queries(
        self,
        threshold_ms: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get slow queries above threshold.

        Args:
            threshold_ms: Duration threshold (uses default if not provided)
            limit: Maximum number of results

        Returns:
            List of slow query profiles
        """
        threshold = threshold_ms or self.slow_query_threshold_ms

        slow_queries = [
            p
            for p in self.query_profiles
            if p.duration_ms and p.duration_ms > threshold
        ]

        # Sort by duration (slowest first)
        slow_queries.sort(key=lambda p: p.duration_ms or 0, reverse=True)

        return [
            {
                "query_type": p.query_type,
                "table_name": p.table_name,
                "duration_ms": p.duration_ms,
                "rows_returned": p.rows_returned,
                "filters": p.filters,
                "limit": p.limit,
                "timestamp": p.start_time,
            }
            for p in slow_queries[:limit]
        ]

    def get_query_stats(
        self,
        query_type: Optional[str] = None,
        table_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get query statistics.

        Args:
            query_type: Optional query type filter
            table_name: Optional table name filter

        Returns:
            Dictionary with query statistics
        """
        filtered_stats = {}

        for key, stats in self.query_stats.items():
            if query_type and stats.query_type != query_type:
                continue
            if table_name and stats.table_name != table_name:
                continue

            filtered_stats[key] = stats.to_dict()

        return {
            "statistics": filtered_stats,
            "total_queries": sum(s.total_queries for s in self.query_stats.values()),
        }

    def get_index_recommendations(self) -> List[Dict[str, Any]]:
        """Get index recommendations based on query patterns.

        Returns:
            List of index recommendations
        """
        recommendations = []

        # Analyze query patterns
        for key, stats in self.query_stats.items():
            # Recommend index if many queries on this table
            if stats.total_queries > 100 and stats.avg_duration_ms > 100:
                recommendations.append(
                    {
                        "table": stats.table_name,
                        "reason": f"High query volume ({stats.total_queries} queries) with slow avg time ({stats.avg_duration_ms:.0f}ms)",
                        "priority": "high" if stats.avg_duration_ms > 500 else "medium",
                        "suggested_action": "Consider adding indices on frequently filtered columns",
                    }
                )

        # Check for slow queries with common filters
        slow_queries = self.get_slow_queries(limit=100)
        filter_usage: dict[str, int] = {}

        for query in slow_queries:
            table = query["table_name"]
            for filter_key in query.get("filters", {}).keys():
                key = f"{table}.{filter_key}"
                filter_usage[key] = filter_usage.get(key, 0) + 1

        # Recommend indices for frequently used filters
        for key, count in filter_usage.items():
            if count > 10:
                table, column = key.split(".", 1)
                recommendations.append(
                    {
                        "table": table,
                        "column": column,
                        "reason": f"Column '{column}' used in {count} slow queries",
                        "priority": "high" if count > 50 else "medium",
                        "suggested_action": f"Add index on {table}.{column}",
                    }
                )

        return recommendations

    def reset(self) -> None:
        """Reset all query profiles and statistics."""
        self.query_profiles.clear()
        self.query_stats.clear()
        self.active_queries.clear()

    def export_stats(self) -> Dict[str, Any]:
        """Export all statistics for monitoring.

        Returns:
            Complete statistics export
        """
        return {
            "timestamp": datetime.now().isoformat(),
            "query_statistics": self.get_query_stats(),
            "slow_queries": self.get_slow_queries(limit=20),
            "index_recommendations": self.get_index_recommendations(),
            "active_queries": len(self.active_queries),
        }


def profile_query(
    optimizer: QueryOptimizer, query_type: str, table_name: str
) -> Callable:
    """Decorator to profile database queries.

    Args:
        optimizer: QueryOptimizer instance
        query_type: Type of query
        table_name: Name of the table

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Start profiling
            query_id = optimizer.start_query(
                query_type=query_type,
                table_name=table_name,
                filters=kwargs.get("filters"),
                limit=kwargs.get("limit"),
            )

            try:
                # Execute query
                result = await func(*args, **kwargs)

                # End profiling
                rows_returned = len(result) if isinstance(result, list) else 0
                optimizer.end_query(
                    query_id=query_id, rows_returned=rows_returned, status="success"
                )

                return result

            except Exception as e:
                # End profiling with error
                optimizer.end_query(
                    query_id=query_id, status="error", error_message=str(e)
                )
                raise

        return wrapper

    return decorator
