"""Metrics tracking for Agentic Inquiry components.

This module provides centralized metrics tracking for:
- Resolution rates (RelationshipResolver)
- Cache hit rates (DocumentCache)
- Query latencies (SearchService, LanceDBManager)
"""

import time
from contextlib import contextmanager
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class LatencyMetrics:
    """Track latency statistics for operations."""

    operation_name: str
    count: int = 0
    total_time: float = 0.0
    min_time: float = float("inf")
    max_time: float = 0.0
    recent_times: List[float] = field(default_factory=list)
    max_recent: int = 100  # Keep last 100 measurements

    def record(self, duration: float) -> None:
        """Record a new latency measurement."""
        self.count += 1
        self.total_time += duration
        self.min_time = min(self.min_time, duration)
        self.max_time = max(self.max_time, duration)

        # Keep recent times for percentile calculations
        self.recent_times.append(duration)
        if len(self.recent_times) > self.max_recent:
            self.recent_times.pop(0)

    @property
    def avg_time(self) -> float:
        """Calculate average latency."""
        if self.count == 0:
            return 0.0
        return self.total_time / self.count

    @property
    def p50(self) -> float:
        """Calculate 50th percentile (median) latency."""
        if not self.recent_times:
            return 0.0
        sorted_times = sorted(self.recent_times)
        idx = len(sorted_times) // 2
        return sorted_times[idx]

    @property
    def p95(self) -> float:
        """Calculate 95th percentile latency."""
        if not self.recent_times:
            return 0.0
        sorted_times = sorted(self.recent_times)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[min(idx, len(sorted_times) - 1)]

    @property
    def p99(self) -> float:
        """Calculate 99th percentile latency."""
        if not self.recent_times:
            return 0.0
        sorted_times = sorted(self.recent_times)
        idx = int(len(sorted_times) * 0.99)
        return sorted_times[min(idx, len(sorted_times) - 1)]

    def to_dict(self) -> Dict[str, float]:
        """Convert metrics to dictionary."""
        return {
            "count": self.count,
            "total_time": self.total_time,
            "avg_time": self.avg_time,
            "min_time": self.min_time if self.min_time != float("inf") else 0.0,
            "max_time": self.max_time,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
        }


class MetricsTracker:
    """Centralized metrics tracking for all components."""

    def __init__(self) -> None:
        """Initialize metrics tracker."""
        self._latency_metrics: Dict[str, LatencyMetrics] = {}
        self._counters: Dict[str, int] = {}

    def increment(self, counter_name: str, amount: int = 1) -> None:
        """Increment a counter metric.

        Args:
            counter_name: Name of the counter (e.g., "search.fallback.triggered").
            amount: Amount to increment by (default 1).
        """
        self._counters[counter_name] = self._counters.get(counter_name, 0) + amount

    def get(self, counter_name: str, default: int = 0) -> int:
        """Get the current value of a counter.

        Args:
            counter_name: Name of the counter.
            default: Default value if counter doesn't exist.

        Returns:
            Current counter value.
        """
        return self._counters.get(counter_name, default)

    def get_latency_metrics(self, operation_name: str) -> LatencyMetrics:
        """Get or create latency metrics for an operation."""
        if operation_name not in self._latency_metrics:
            self._latency_metrics[operation_name] = LatencyMetrics(operation_name)
        return self._latency_metrics[operation_name]

    @contextmanager
    def track_latency(self, operation_name: str) -> Generator[None, None, None]:
        """Context manager to track operation latency.

        Usage:
            with metrics_tracker.track_latency("vector_search"):
                # perform operation
                results = await db.vector_search(...)
        """
        start_time = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start_time
            metrics = self.get_latency_metrics(operation_name)
            metrics.record(duration)

            # Log slow operations (> 1 second)
            if duration > 1.0:
                logger.warning(
                    f"Slow operation detected: {operation_name} took {duration:.3f}s",
                    extra={"operation": operation_name, "duration": duration},
                )

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all tracked metrics.

        Returns:
            Dictionary with 'latency' and 'counters' sections.
        """
        return {
            "latency": {
                name: metrics.to_dict()
                for name, metrics in self._latency_metrics.items()
            },
            "counters": dict(self._counters),
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self._latency_metrics.clear()
        self._counters.clear()

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics."""
        summary = {
            "latency_metrics": self.get_all_metrics()["latency"],
            "counters": self.get_all_metrics()["counters"],
            "total_operations": sum(m.count for m in self._latency_metrics.values()),
            "total_counter_events": sum(self._counters.values()),
        }
        return summary

    def get_performance_recommendations(self) -> List[Dict[str, str]]:
        """Analyze metrics and provide performance recommendations.

        Detects degraded performance (>2x baseline) and provides actionable
        recommendations for optimization.

        Returns:
            List of recommendations with operation, issue, and suggestion
        """
        recommendations = []

        # Define baseline expectations (in seconds)
        baselines = {
            "search.vector_search": 0.5,
            "search.fts_search": 0.3,
            "indexing.sync": 5.0,
            "hybrid_search": 1.0,
        }

        for operation_name, metrics in self._latency_metrics.items():
            if metrics.count == 0:
                continue

            # Check if operation has a known baseline
            baseline = baselines.get(operation_name)
            if baseline is None:
                # No baseline defined, skip
                continue

            # Check if p95 latency is >2x baseline (degraded performance)
            if metrics.p95 > baseline * 2:
                recommendation = {
                    "operation": operation_name,
                    "issue": f"P95 latency ({metrics.p95:.3f}s) is {metrics.p95 / baseline:.1f}x baseline ({baseline}s)",
                    "suggestion": self._get_recommendation_for_operation(
                        operation_name, metrics
                    ),
                }
                recommendations.append(recommendation)

        return recommendations

    def _get_recommendation_for_operation(
        self, operation_name: str, metrics: LatencyMetrics
    ) -> str:
        """Get specific recommendation for an operation based on metrics."""
        if "search" in operation_name:
            if metrics.p95 > 2.0:
                return "Consider reducing search limit or enabling result caching"
            elif metrics.p95 > 1.0:
                return "Consider optimizing query filters or reducing result limit"
            else:
                return "Consider enabling query result caching"

        elif "indexing" in operation_name:
            if metrics.p95 > 10.0:
                return "Consider reducing concurrent file processing or indexing in smaller batches"
            else:
                return (
                    "Consider increasing processing_semaphore_limit for faster indexing"
                )

        else:
            return "Consider profiling this operation to identify bottlenecks"


# Global metrics tracker instance
_global_metrics_tracker: Optional[MetricsTracker] = None


def get_metrics_tracker() -> MetricsTracker:
    """Get the global metrics tracker instance."""
    global _global_metrics_tracker
    if _global_metrics_tracker is None:
        _global_metrics_tracker = MetricsTracker()
    return _global_metrics_tracker


def reset_metrics() -> None:
    """Reset all global metrics by forcing recreation of the tracker."""
    global _global_metrics_tracker
    _global_metrics_tracker = None


__all__ = [
    "LatencyMetrics",
    "MetricsTracker",
    "get_metrics_tracker",
    "reset_metrics",
]
