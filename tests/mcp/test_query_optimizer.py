"""Tests for database query optimizer."""

import pytest

pytestmark = pytest.mark.unit

import time

from agent_vault.mcp.utils.query_optimizer import (
    QueryOptimizer,
    QueryProfile,
    QueryStatistics,
)


def test_start_and_end_query():
    """Test starting and ending query profiling."""
    optimizer = QueryOptimizer()
    
    # Start query
    query_id = optimizer.start_query(
        query_type="search",
        table_name="document_chunks",
        filters={"project_id": "test"},
        limit=20
    )
    
    assert query_id in optimizer.active_queries
    
    # End query
    optimizer.end_query(
        query_id=query_id,
        rows_returned=15,
        status="success"
    )
    
    assert query_id not in optimizer.active_queries
    assert len(optimizer.query_profiles) == 1
    assert optimizer.query_profiles[0].rows_returned == 15


def test_query_duration_tracking():
    """Test that query duration is tracked correctly."""
    optimizer = QueryOptimizer()
    
    query_id = optimizer.start_query(
        query_type="search",
        table_name="document_chunks"
    )
    
    # Ensure at least 100ms passes for measurable duration
    min_duration = 0.1
    start = time.time()
    while (time.time() - start) < min_duration:
        time.sleep(0.01)

    optimizer.end_query(query_id=query_id, rows_returned=10)

    profile = optimizer.query_profiles[0]
    assert profile.duration_ms is not None
    assert profile.duration_ms >= 100  # At least 100ms


def test_query_statistics_update():
    """Test that query statistics are updated correctly."""
    optimizer = QueryOptimizer()
    
    # Execute multiple queries
    for i in range(5):
        query_id = optimizer.start_query(
            query_type="search",
            table_name="document_chunks"
        )
        optimizer.end_query(
            query_id=query_id,
            rows_returned=10 + i,
            status="success" if i < 4 else "error"
        )
    
    # Check statistics
    stats = optimizer.get_query_stats(
        query_type="search",
        table_name="document_chunks"
    )
    
    assert stats["total_queries"] == 5
    stats_detail = list(stats["statistics"].values())[0]
    assert stats_detail["successful_queries"] == 4
    assert stats_detail["failed_queries"] == 1


# NOTE: test_batch_insert and test_batch_get_by_ids were removed along with
# the dead code methods they tested (batch_insert, batch_get_by_ids)


def test_get_slow_queries():
    """Test getting slow queries."""
    optimizer = QueryOptimizer(slow_query_threshold_ms=100)
    
    # Create some fast and slow queries
    for i in range(5):
        query_id = optimizer.start_query(
            query_type="search",
            table_name="document_chunks"
        )
        
        # Simulate varying execution times with condition-based waits
        if i < 3:
            # Fast query - minimal wait
            time.sleep(0.01)
        else:
            # Slow query - ensure we exceed 100ms threshold
            slow_start = time.time()
            while (time.time() - slow_start) < 0.15:
                time.sleep(0.01)
        
        optimizer.end_query(query_id=query_id, rows_returned=10)
    
    # Get slow queries
    slow = optimizer.get_slow_queries()
    assert len(slow) == 2  # Only the slow ones


def test_get_query_stats_filtered():
    """Test getting filtered query statistics."""
    optimizer = QueryOptimizer()
    
    # Execute queries on different tables
    for table in ["document_chunks", "graph_entities"]:
        for i in range(3):
            query_id = optimizer.start_query(
                query_type="search",
                table_name=table
            )
            optimizer.end_query(query_id=query_id, rows_returned=10)
    
    # Get stats for specific table
    stats = optimizer.get_query_stats(table_name="document_chunks")
    assert len(stats["statistics"]) == 1
    assert "search:document_chunks" in stats["statistics"]


def test_index_recommendations():
    """Test index recommendations based on query patterns."""
    optimizer = QueryOptimizer(slow_query_threshold_ms=50)
    
    # Create many slow queries with common filters
    for i in range(150):
        query_id = optimizer.start_query(
            query_type="search",
            table_name="document_chunks",
            filters={"project_id": "test", "type": "code"}
        )
        
        # Ensure query exceeds 50ms threshold
        slow_start = time.time()
        while (time.time() - slow_start) < 0.06:
            time.sleep(0.01)
        
        optimizer.end_query(query_id=query_id, rows_returned=10)
    
    # Get recommendations
    recommendations = optimizer.get_index_recommendations()
    assert len(recommendations) > 0
    
    # Should recommend index on frequently used filters
    filter_recommendations = [
        r for r in recommendations 
        if "column" in r and r["table"] == "document_chunks"
    ]
    assert len(filter_recommendations) > 0


def test_query_profile_complete():
    """Test completing a query profile."""
    profile = QueryProfile(
        query_type="search",
        table_name="document_chunks",
        start_time=time.time()
    )
    
    # Ensure at least 100ms passes for measurable duration
    min_duration = 0.1
    start = time.time()
    while (time.time() - start) < min_duration:
        time.sleep(0.01)

    profile.complete(rows_returned=10, status="success")

    assert profile.end_time is not None
    assert profile.duration_ms is not None
    assert profile.duration_ms >= 100
    assert profile.rows_returned == 10
    assert profile.status == "success"


def test_query_statistics_to_dict():
    """Test converting query statistics to dictionary."""
    stats = QueryStatistics(
        query_type="search",
        table_name="document_chunks"
    )
    
    # Create mock profiles
    for i in range(5):
        profile = QueryProfile(
            query_type="search",
            table_name="document_chunks",
            start_time=time.time()
        )
        profile.complete(rows_returned=10 + i, status="success")
        stats.update(profile)
    
    # Convert to dict
    stats_dict = stats.to_dict()
    
    assert stats_dict["query_type"] == "search"
    assert stats_dict["table_name"] == "document_chunks"
    assert stats_dict["total_queries"] == 5
    assert stats_dict["successful_queries"] == 5
    assert stats_dict["rows"]["total"] == 60  # 10+11+12+13+14


def test_reset():
    """Test resetting optimizer."""
    optimizer = QueryOptimizer()
    
    # Execute some queries
    for i in range(5):
        query_id = optimizer.start_query(
            query_type="search",
            table_name="document_chunks"
        )
        optimizer.end_query(query_id=query_id, rows_returned=10)
    
    # Reset
    optimizer.reset()
    
    # Everything should be cleared
    assert len(optimizer.query_profiles) == 0
    assert len(optimizer.query_stats) == 0
    assert len(optimizer.active_queries) == 0


def test_export_stats():
    """Test exporting statistics."""
    optimizer = QueryOptimizer()
    
    # Execute some queries
    query_id = optimizer.start_query(
        query_type="search",
        table_name="document_chunks"
    )
    optimizer.end_query(query_id=query_id, rows_returned=10)
    
    # Export stats
    export = optimizer.export_stats()
    
    assert "timestamp" in export
    assert "query_statistics" in export
    assert "slow_queries" in export
    assert "index_recommendations" in export
    assert "active_queries" in export


def test_success_rate_calculation():
    """Test success rate calculation."""
    optimizer = QueryOptimizer()
    
    # Execute with mix of success and failure
    for i in range(10):
        query_id = optimizer.start_query(
            query_type="search",
            table_name="document_chunks"
        )
        optimizer.end_query(
            query_id=query_id,
            rows_returned=10,
            status="success" if i < 8 else "error"
        )
    
    stats = optimizer.get_query_stats()
    stats_detail = list(stats["statistics"].values())[0]
    assert stats_detail["success_rate_percent"] == 80.0


def test_avg_rows_calculation():
    """Test average rows calculation."""
    optimizer = QueryOptimizer()
    
    # Execute with varying row counts
    row_counts = [10, 20, 30, 40, 50]
    for rows in row_counts:
        query_id = optimizer.start_query(
            query_type="search",
            table_name="document_chunks"
        )
        optimizer.end_query(query_id=query_id, rows_returned=rows)
    
    stats = optimizer.get_query_stats()
    stats_detail = list(stats["statistics"].values())[0]
    assert stats_detail["rows"]["avg"] == 30.0  # (10+20+30+40+50)/5


def test_min_max_duration():
    """Test min and max duration tracking."""
    optimizer = QueryOptimizer()
    
    # Execute with varying durations using condition-based waits
    durations = [0.01, 0.05, 0.1, 0.02, 0.03]
    for duration in durations:
        query_id = optimizer.start_query(
            query_type="search",
            table_name="document_chunks"
        )
        # Ensure minimum duration passes
        start = time.time()
        while (time.time() - start) < duration:
            time.sleep(0.005)
        optimizer.end_query(query_id=query_id, rows_returned=10)
    
    stats = optimizer.get_query_stats()
    stats_detail = list(stats["statistics"].values())[0]
    
    assert stats_detail["duration_ms"]["min"] is not None
    assert stats_detail["duration_ms"]["max"] is not None
    assert stats_detail["duration_ms"]["min"] < stats_detail["duration_ms"]["max"]


def test_slow_query_threshold():
    """Test custom slow query threshold."""
    optimizer = QueryOptimizer(slow_query_threshold_ms=50)
    
    # Create queries with different durations using condition-based waits
    for duration in [0.01, 0.06, 0.1]:
        query_id = optimizer.start_query(
            query_type="search",
            table_name="document_chunks"
        )
        # Ensure minimum duration passes
        start = time.time()
        while (time.time() - start) < duration:
            time.sleep(0.005)
        optimizer.end_query(query_id=query_id, rows_returned=10)
    
    # Get slow queries with default threshold (50ms)
    slow = optimizer.get_slow_queries()
    assert len(slow) == 2  # 60ms and 100ms queries
    
    # Get slow queries with custom threshold (80ms)
    slow_custom = optimizer.get_slow_queries(threshold_ms=80)
    assert len(slow_custom) == 1  # Only 100ms query
