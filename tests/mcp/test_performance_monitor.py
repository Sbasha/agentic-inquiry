"""Tests for MCP performance monitor."""

import pytest

pytestmark = pytest.mark.unit

import time

from agentic_inquiry.mcp.utils.performance import (
    PerformanceMonitor,
    ToolExecutionMetric,
    ToolStatistics,
)


def test_start_and_end_execution():
    """Test starting and ending execution tracking."""
    monitor = PerformanceMonitor()

    # Start execution
    exec_id = monitor.start_execution(
        tool_name="search_knowledge", session_id="session123"
    )

    assert exec_id in monitor.active_metrics

    # End execution
    monitor.end_execution(execution_id=exec_id, status="success", token_usage=100)

    assert exec_id not in monitor.active_metrics
    assert len(monitor.metrics_history) == 1
    assert monitor.metrics_history[0].status == "success"
    assert monitor.metrics_history[0].token_usage == 100


def test_execution_duration_tracking():
    """Test that execution duration is tracked correctly."""
    monitor = PerformanceMonitor()

    exec_id = monitor.start_execution(
        tool_name="search_knowledge", session_id="session123"
    )

    # Simulate some work
    time.sleep(0.1)

    monitor.end_execution(execution_id=exec_id, status="success")

    metric = monitor.metrics_history[0]
    assert metric.duration_ms is not None
    assert metric.duration_ms >= 100  # At least 100ms


def test_tool_statistics_update():
    """Test that tool statistics are updated correctly."""
    monitor = PerformanceMonitor()

    # Execute tool multiple times
    for i in range(5):
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id="session123"
        )
        monitor.end_execution(
            execution_id=exec_id,
            status="success" if i < 4 else "error",
            token_usage=100 + i * 10,
        )

    # Check statistics
    stats = monitor.get_tool_stats("search_knowledge")
    assert stats is not None
    assert stats["total_executions"] == 5
    assert stats["successful_executions"] == 4
    assert stats["failed_executions"] == 1
    assert stats["tokens"]["total"] == 600  # 100+110+120+130+140


def test_cache_hit_tracking():
    """Test cache hit tracking in statistics."""
    monitor = PerformanceMonitor()

    # Execute with cache hits and misses
    for i in range(10):
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id="session123"
        )
        monitor.end_execution(
            execution_id=exec_id,
            status="success",
            cache_hit=(i % 2 == 0),  # Every other is a cache hit
        )

    stats = monitor.get_tool_stats("search_knowledge")
    assert stats["cache"]["hits"] == 5
    assert stats["cache"]["misses"] == 5
    assert stats["cache"]["hit_rate_percent"] == 50.0


def test_get_all_stats():
    """Test getting statistics for all tools."""
    monitor = PerformanceMonitor()

    # Execute different tools
    for tool in ["search_knowledge", "build_context", "understand_entity"]:
        exec_id = monitor.start_execution(tool_name=tool, session_id="session123")
        monitor.end_execution(execution_id=exec_id, status="success")

    all_stats = monitor.get_all_stats()
    assert all_stats["total_executions"] == 3
    assert len(all_stats["tools"]) == 3
    assert "search_knowledge" in all_stats["tools"]
    assert "build_context" in all_stats["tools"]
    assert "understand_entity" in all_stats["tools"]


def test_get_recent_metrics():
    """Test getting recent execution metrics."""
    monitor = PerformanceMonitor()

    # Execute multiple times
    for i in range(10):
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id=f"session{i}"
        )
        monitor.end_execution(execution_id=exec_id, status="success")

    # Get recent metrics
    recent = monitor.get_recent_metrics(limit=5)
    assert len(recent) == 5

    # Should be most recent
    assert recent[-1]["session_id"] == "session9"


def test_get_recent_metrics_filtered():
    """Test getting recent metrics filtered by tool."""
    monitor = PerformanceMonitor()

    # Execute different tools
    for i in range(5):
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id="session123"
        )
        monitor.end_execution(execution_id=exec_id, status="success")

    for i in range(3):
        exec_id = monitor.start_execution(
            tool_name="build_context", session_id="session123"
        )
        monitor.end_execution(execution_id=exec_id, status="success")

    # Get metrics for specific tool
    search_metrics = monitor.get_recent_metrics(tool_name="search_knowledge")
    assert len(search_metrics) == 5
    assert all(m["tool_name"] == "search_knowledge" for m in search_metrics)


def test_get_slow_executions():
    """Test getting slow executions."""
    monitor = PerformanceMonitor()

    # Create some fast and slow executions
    for i in range(5):
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id="session123"
        )

        # Simulate varying execution times
        if i < 3:
            time.sleep(0.001)  # Fast
        else:
            time.sleep(0.1)  # Slow

        monitor.end_execution(execution_id=exec_id, status="success")

    # Get slow executions (>50ms)
    slow = monitor.get_slow_executions(threshold_ms=50)
    assert len(slow) == 2  # Only the slow ones


def test_get_error_summary():
    """Test getting error summary."""
    monitor = PerformanceMonitor()

    # Execute with some errors
    for i in range(10):
        exec_id = monitor.start_execution(
            tool_name="search_knowledge" if i < 5 else "build_context",
            session_id="session123",
        )

        if i % 3 == 0:
            monitor.end_execution(
                execution_id=exec_id, status="error", error_message="Connection timeout"
            )
        else:
            monitor.end_execution(execution_id=exec_id, status="success")

    error_summary = monitor.get_error_summary()
    assert error_summary["total_errors"] > 0
    assert "search_knowledge" in error_summary["errors_by_tool"]
    assert len(error_summary["top_error_messages"]) > 0


def test_percentile_calculation():
    """Test percentile calculation for tool statistics."""
    monitor = PerformanceMonitor()

    # Create executions with known durations
    durations = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

    for duration in durations:
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id="session123"
        )

        # Manually set duration for testing
        metric = monitor.active_metrics[exec_id]
        metric.start_time = time.time() - (duration / 1000)

        monitor.end_execution(execution_id=exec_id, status="success")

    stats = monitor.get_tool_stats("search_knowledge")
    assert stats["duration_ms"]["p95"] is not None
    assert stats["duration_ms"]["p99"] is not None
    assert stats["duration_ms"]["p95"] >= stats["duration_ms"]["avg"]


def test_history_limit():
    """Test that history is limited to max_history."""
    monitor = PerformanceMonitor(max_history=10)

    # Execute more than max_history times
    for i in range(20):
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id="session123"
        )
        monitor.end_execution(execution_id=exec_id, status="success")

    # History should be limited
    assert len(monitor.metrics_history) == 10


def test_reset():
    """Test resetting monitor."""
    monitor = PerformanceMonitor()

    # Execute some tools
    for i in range(5):
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id="session123"
        )
        monitor.end_execution(execution_id=exec_id, status="success")

    # Reset
    monitor.reset()

    # Everything should be cleared
    assert len(monitor.metrics_history) == 0
    assert len(monitor.active_metrics) == 0
    assert len(monitor.tool_stats) == 0


def test_export_metrics():
    """Test exporting all metrics."""
    monitor = PerformanceMonitor()

    # Execute some tools
    exec_id = monitor.start_execution(
        tool_name="search_knowledge", session_id="session123"
    )
    monitor.end_execution(execution_id=exec_id, status="success", token_usage=100)

    # Export metrics
    export = monitor.export_metrics()

    assert "timestamp" in export
    assert "uptime_seconds" in export
    assert "statistics" in export
    assert "recent_metrics" in export
    assert "slow_executions" in export
    assert "error_summary" in export


def test_tool_statistics_to_dict():
    """Test converting tool statistics to dictionary."""
    stats = ToolStatistics(tool_name="search_knowledge")

    # Create a mock metric
    metric = ToolExecutionMetric(
        tool_name="search_knowledge", session_id="session123", start_time=time.time()
    )
    metric.complete(status="success")
    metric.token_usage = 100
    metric.cache_hit = True

    # Update statistics
    stats.update(metric)

    # Convert to dict
    stats_dict = stats.to_dict()

    assert stats_dict["tool_name"] == "search_knowledge"
    assert stats_dict["total_executions"] == 1
    assert stats_dict["successful_executions"] == 1
    assert stats_dict["tokens"]["total"] == 100
    assert stats_dict["cache"]["hits"] == 1


def test_success_rate_calculation():
    """Test success rate calculation."""
    monitor = PerformanceMonitor()

    # Execute with mix of success and failure
    for i in range(10):
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id="session123"
        )
        monitor.end_execution(
            execution_id=exec_id, status="success" if i < 8 else "error"
        )

    stats = monitor.get_tool_stats("search_knowledge")
    assert stats["success_rate_percent"] == 80.0


def test_avg_tokens_per_execution():
    """Test average tokens per execution calculation."""
    monitor = PerformanceMonitor()

    # Execute with varying token usage
    token_usages = [100, 200, 300, 400, 500]
    for tokens in token_usages:
        exec_id = monitor.start_execution(
            tool_name="search_knowledge", session_id="session123"
        )
        monitor.end_execution(
            execution_id=exec_id, status="success", token_usage=tokens
        )

    stats = monitor.get_tool_stats("search_knowledge")
    assert stats["tokens"]["avg_per_execution"] == 300.0  # (100+200+300+400+500)/5
