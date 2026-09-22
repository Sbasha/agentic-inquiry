"""Tests for metrics tracking functionality."""

import pytest

import asyncio
from agentic_inquiry.metrics import (
    LatencyMetrics,
    MetricsTracker,
    get_metrics_tracker,
    reset_metrics,
)


class TestLatencyMetrics:
    """Test LatencyMetrics class."""
    
    def test_initialization(self):
        """Test LatencyMetrics initialization."""
        metrics = LatencyMetrics("test_operation")
        assert metrics.operation_name == "test_operation"
        assert metrics.count == 0
        assert metrics.total_time == 0.0
        assert metrics.min_time == float('inf')
        assert metrics.max_time == 0.0
        assert len(metrics.recent_times) == 0
    
    def test_record_single_measurement(self):
        """Test recording a single measurement."""
        metrics = LatencyMetrics("test_operation")
        metrics.record(0.5)
        
        assert metrics.count == 1
        assert metrics.total_time == 0.5
        assert metrics.min_time == 0.5
        assert metrics.max_time == 0.5
        assert metrics.avg_time == 0.5
        assert len(metrics.recent_times) == 1
    
    def test_record_multiple_measurements(self):
        """Test recording multiple measurements."""
        metrics = LatencyMetrics("test_operation")
        measurements = [0.1, 0.2, 0.3, 0.4, 0.5]
        
        for measurement in measurements:
            metrics.record(measurement)
        
        assert metrics.count == 5
        assert metrics.total_time == 1.5
        assert metrics.min_time == 0.1
        assert metrics.max_time == 0.5
        assert metrics.avg_time == 0.3
        assert len(metrics.recent_times) == 5
    
    def test_percentile_calculations(self):
        """Test percentile calculations."""
        metrics = LatencyMetrics("test_operation")
        
        # Add 100 measurements from 0.01 to 1.00
        for i in range(1, 101):
            metrics.record(i / 100.0)
        
        # Check percentiles
        assert 0.49 <= metrics.p50 <= 0.51  # Median around 0.5
        assert 0.94 <= metrics.p95 <= 0.96  # 95th percentile around 0.95
        assert 0.98 <= metrics.p99 <= 1.00  # 99th percentile around 0.99
    
    def test_recent_times_limit(self):
        """Test that recent_times is limited to max_recent."""
        metrics = LatencyMetrics("test_operation", max_recent=10)
        
        # Add 20 measurements
        for i in range(20):
            metrics.record(i / 10.0)
        
        # Should only keep last 10
        assert len(metrics.recent_times) == 10
        assert metrics.count == 20  # But count should be 20
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        metrics = LatencyMetrics("test_operation")
        metrics.record(0.1)
        metrics.record(0.2)
        metrics.record(0.3)
        
        result = metrics.to_dict()
        
        assert result["count"] == 3
        assert abs(result["total_time"] - 0.6) < 0.001  # Allow for floating point precision
        assert abs(result["avg_time"] - 0.2) < 0.001
        assert result["min_time"] == 0.1
        assert result["max_time"] == 0.3
        assert "p50" in result
        assert "p95" in result
        assert "p99" in result


class TestMetricsTracker:
    """Test MetricsTracker class."""
    
    def test_initialization(self):
        """Test MetricsTracker initialization."""
        tracker = MetricsTracker()
        assert len(tracker._latency_metrics) == 0
        assert len(tracker._counters) == 0

    def test_increment_counter(self):
        """Test incrementing counters."""
        tracker = MetricsTracker()

        # Default increment by 1
        tracker.increment("counter1")
        assert tracker.get("counter1") == 1

        # Increment again
        tracker.increment("counter1")
        assert tracker.get("counter1") == 2

        # Increment by custom amount
        tracker.increment("counter2", 5)
        assert tracker.get("counter2") == 5

        # Get non-existent counter returns default
        assert tracker.get("nonexistent") == 0
        assert tracker.get("nonexistent", 42) == 42
    
    def test_get_latency_metrics(self):
        """Test getting latency metrics."""
        tracker = MetricsTracker()
        
        metrics1 = tracker.get_latency_metrics("operation1")
        assert metrics1.operation_name == "operation1"
        
        # Getting same operation should return same instance
        metrics2 = tracker.get_latency_metrics("operation1")
        assert metrics1 is metrics2
        
        # Different operation should return different instance
        metrics3 = tracker.get_latency_metrics("operation2")
        assert metrics3 is not metrics1
    
    def test_track_latency_context_manager(self):
        """Test track_latency context manager."""
        tracker = MetricsTracker()
        
        with tracker.track_latency("test_operation"):
            # Simulate some work
            import time
            time.sleep(0.01)
        
        metrics = tracker.get_latency_metrics("test_operation")
        assert metrics.count == 1
        assert metrics.total_time > 0.01
    
    def test_track_latency_with_exception(self):
        """Test that metrics are recorded even if exception occurs."""
        tracker = MetricsTracker()
        
        try:
            with tracker.track_latency("test_operation"):
                raise ValueError("Test error")
        except ValueError:
            pass
        
        metrics = tracker.get_latency_metrics("test_operation")
        assert metrics.count == 1
        assert metrics.total_time > 0
    
    def test_get_all_metrics(self):
        """Test getting all metrics."""
        tracker = MetricsTracker()

        with tracker.track_latency("operation1"):
            pass

        with tracker.track_latency("operation2"):
            pass

        # Add counter metrics
        tracker.increment("counter1")
        tracker.increment("counter2", 5)

        all_metrics = tracker.get_all_metrics()

        # Check structure
        assert "latency" in all_metrics
        assert "counters" in all_metrics

        # Check latency metrics
        assert "operation1" in all_metrics["latency"]
        assert "operation2" in all_metrics["latency"]
        assert all_metrics["latency"]["operation1"]["count"] == 1
        assert all_metrics["latency"]["operation2"]["count"] == 1

        # Check counter metrics
        assert "counter1" in all_metrics["counters"]
        assert "counter2" in all_metrics["counters"]
        assert all_metrics["counters"]["counter1"] == 1
        assert all_metrics["counters"]["counter2"] == 5
    
    def test_reset(self):
        """Test resetting metrics."""
        tracker = MetricsTracker()

        with tracker.track_latency("test_operation"):
            pass
        tracker.increment("counter1")

        assert len(tracker._latency_metrics) == 1
        assert len(tracker._counters) == 1

        tracker.reset()
        assert len(tracker._latency_metrics) == 0
        assert len(tracker._counters) == 0
    
    def test_get_summary(self):
        """Test getting metrics summary."""
        tracker = MetricsTracker()

        with tracker.track_latency("operation1"):
            pass

        with tracker.track_latency("operation2"):
            pass

        tracker.increment("counter1")
        tracker.increment("counter2", 3)

        summary = tracker.get_summary()
        assert "latency_metrics" in summary
        assert "counters" in summary
        assert "total_operations" in summary
        assert "total_counter_events" in summary
        assert summary["total_operations"] == 2
        assert summary["total_counter_events"] == 4  # 1 + 3


class TestGlobalMetricsTracker:
    """Test global metrics tracker functions."""
    
    def test_get_metrics_tracker(self):
        """Test getting global metrics tracker."""
        tracker1 = get_metrics_tracker()
        tracker2 = get_metrics_tracker()
        
        # Should return same instance
        assert tracker1 is tracker2
    
    def test_reset_metrics(self):
        """Test resetting global metrics."""
        tracker = get_metrics_tracker()
        
        with tracker.track_latency("test_operation"):
            pass
        
        assert len(tracker._latency_metrics) == 1
        
        reset_metrics()
        
        # After reset, get_metrics_tracker() should return a new instance with no metrics
        new_tracker = get_metrics_tracker()
        assert len(new_tracker._latency_metrics) == 0


@pytest.mark.asyncio
class TestMetricsIntegration:
    """Integration tests for metrics tracking."""
    
    async def test_concurrent_tracking(self):
        """Test metrics tracking with concurrent operations."""
        tracker = MetricsTracker()
        
        async def async_operation(name: str, duration: float):
            with tracker.track_latency(name):
                await asyncio.sleep(duration)
        
        # Run multiple operations concurrently
        await asyncio.gather(
            async_operation("op1", 0.01),
            async_operation("op1", 0.01),
            async_operation("op2", 0.01),
        )
        
        metrics1 = tracker.get_latency_metrics("op1")
        metrics2 = tracker.get_latency_metrics("op2")
        
        assert metrics1.count == 2
        assert metrics2.count == 1
    
    async def test_nested_tracking(self):
        """Test nested operation tracking."""
        tracker = MetricsTracker()
        
        with tracker.track_latency("outer"):
            await asyncio.sleep(0.01)
            with tracker.track_latency("inner"):
                await asyncio.sleep(0.01)
        
        outer_metrics = tracker.get_latency_metrics("outer")
        inner_metrics = tracker.get_latency_metrics("inner")
        
        assert outer_metrics.count == 1
        assert inner_metrics.count == 1
        # Outer should take longer than inner
        assert outer_metrics.total_time > inner_metrics.total_time
