"""Performance monitoring for MCP tools."""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ToolExecutionMetric:
    """Metrics for a single tool execution."""

    tool_name: str
    session_id: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[int] = None
    status: str = "running"  # running, success, error
    error_message: Optional[str] = None
    token_usage: Optional[int] = None
    cache_hit: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def complete(
        self, status: str = "success", error_message: Optional[str] = None
    ) -> None:
        """Mark execution as complete.

        Args:
            status: Execution status (success or error)
            error_message: Optional error message
        """
        self.end_time = time.time()
        self.duration_ms = int((self.end_time - self.start_time) * 1000)
        self.status = status
        self.error_message = error_message


@dataclass
class ToolStatistics:
    """Aggregated statistics for a tool."""

    tool_name: str
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    total_duration_ms: int = 0
    min_duration_ms: Optional[int] = None
    max_duration_ms: Optional[int] = None
    avg_duration_ms: float = 0.0
    p95_duration_ms: Optional[int] = None
    p99_duration_ms: Optional[int] = None
    total_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def update(self, metric: ToolExecutionMetric) -> None:
        """Update statistics with a new metric.

        Args:
            metric: Tool execution metric
        """
        if metric.duration_ms is None:
            return

        self.total_executions += 1

        if metric.status == "success":
            self.successful_executions += 1
        else:
            self.failed_executions += 1

        self.total_duration_ms += metric.duration_ms

        if self.min_duration_ms is None or metric.duration_ms < self.min_duration_ms:
            self.min_duration_ms = metric.duration_ms

        if self.max_duration_ms is None or metric.duration_ms > self.max_duration_ms:
            self.max_duration_ms = metric.duration_ms

        self.avg_duration_ms = self.total_duration_ms / self.total_executions

        if metric.token_usage:
            self.total_tokens += metric.token_usage

        if metric.cache_hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        cache_total = self.cache_hits + self.cache_misses
        cache_hit_rate = (
            (self.cache_hits / cache_total * 100) if cache_total > 0 else 0.0
        )

        return {
            "tool_name": self.tool_name,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "success_rate_percent": (
                self.successful_executions / self.total_executions * 100
                if self.total_executions > 0
                else 0.0
            ),
            "duration_ms": {
                "total": self.total_duration_ms,
                "min": self.min_duration_ms,
                "max": self.max_duration_ms,
                "avg": round(self.avg_duration_ms, 2),
                "p95": self.p95_duration_ms,
                "p99": self.p99_duration_ms,
            },
            "tokens": {
                "total": self.total_tokens,
                "avg_per_execution": (
                    round(self.total_tokens / self.total_executions, 2)
                    if self.total_executions > 0
                    else 0.0
                ),
            },
            "cache": {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "hit_rate_percent": round(cache_hit_rate, 2),
            },
        }


class PerformanceMonitor:
    """Monitor and track MCP tool performance.

    Tracks:
    - Tool execution times
    - Token usage
    - Cache performance
    - Error rates
    - Success rates
    """

    def __init__(self, max_history: int = 1000):
        """Initialize performance monitor.

        Args:
            max_history: Maximum number of metrics to keep in history
        """
        self.max_history = max_history
        self.metrics_history: List[ToolExecutionMetric] = []
        self.active_metrics: Dict[str, ToolExecutionMetric] = {}
        self.tool_stats: Dict[str, ToolStatistics] = {}
        self.start_time = datetime.now()

    def start_execution(
        self,
        tool_name: str,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start tracking a tool execution.

        Args:
            tool_name: Name of the tool
            session_id: Session ID
            metadata: Optional metadata

        Returns:
            Execution ID for tracking
        """
        execution_id = f"{tool_name}:{session_id}:{time.time()}"

        metric = ToolExecutionMetric(
            tool_name=tool_name,
            session_id=session_id,
            start_time=time.time(),
            metadata=metadata or {},
        )

        self.active_metrics[execution_id] = metric
        return execution_id

    def end_execution(
        self,
        execution_id: str,
        status: str = "success",
        error_message: Optional[str] = None,
        token_usage: Optional[int] = None,
        cache_hit: bool = False,
    ) -> None:
        """End tracking a tool execution.

        Args:
            execution_id: Execution ID from start_execution
            status: Execution status (success or error)
            error_message: Optional error message
            token_usage: Optional token usage count
            cache_hit: Whether result was from cache
        """
        if execution_id not in self.active_metrics:
            return

        metric = self.active_metrics.pop(execution_id)
        metric.complete(status=status, error_message=error_message)
        metric.token_usage = token_usage
        metric.cache_hit = cache_hit

        # Add to history
        self.metrics_history.append(metric)

        # Trim history if needed
        if len(self.metrics_history) > self.max_history:
            self.metrics_history = self.metrics_history[-self.max_history :]

        # Update tool statistics
        if metric.tool_name not in self.tool_stats:
            self.tool_stats[metric.tool_name] = ToolStatistics(
                tool_name=metric.tool_name
            )

        self.tool_stats[metric.tool_name].update(metric)

        # Calculate percentiles for this tool
        self._update_percentiles(metric.tool_name)

    def _update_percentiles(self, tool_name: str) -> None:
        """Update percentile calculations for a tool.

        Args:
            tool_name: Name of the tool
        """
        # Get all durations for this tool
        durations = [
            m.duration_ms
            for m in self.metrics_history
            if m.tool_name == tool_name and m.duration_ms is not None
        ]

        if not durations:
            return

        durations.sort()

        # Calculate p95
        p95_index = int(len(durations) * 0.95)
        if p95_index < len(durations):
            self.tool_stats[tool_name].p95_duration_ms = durations[p95_index]

        # Calculate p99
        p99_index = int(len(durations) * 0.99)
        if p99_index < len(durations):
            self.tool_stats[tool_name].p99_duration_ms = durations[p99_index]

    def get_tool_stats(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool statistics dictionary or None if not found
        """
        if tool_name not in self.tool_stats:
            return None

        return self.tool_stats[tool_name].to_dict()

    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all tools.

        Returns:
            Dictionary with all tool statistics
        """
        uptime_seconds = (datetime.now() - self.start_time).total_seconds()

        return {
            "uptime_seconds": int(uptime_seconds),
            "total_executions": sum(
                stats.total_executions for stats in self.tool_stats.values()
            ),
            "active_executions": len(self.active_metrics),
            "tools": {
                tool_name: stats.to_dict()
                for tool_name, stats in self.tool_stats.items()
            },
        }

    def get_recent_metrics(
        self,
        tool_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get recent execution metrics.

        Args:
            tool_name: Optional tool name filter
            limit: Maximum number of metrics to return

        Returns:
            List of metric dictionaries
        """
        metrics = self.metrics_history

        if tool_name:
            metrics = [m for m in metrics if m.tool_name == tool_name]

        # Get most recent
        metrics = metrics[-limit:]

        return [
            {
                "tool_name": m.tool_name,
                "session_id": m.session_id,
                "duration_ms": m.duration_ms,
                "status": m.status,
                "error_message": m.error_message,
                "token_usage": m.token_usage,
                "cache_hit": m.cache_hit,
                "timestamp": m.start_time,
            }
            for m in metrics
        ]

    def get_slow_executions(
        self,
        threshold_ms: int = 2000,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get slow executions above threshold.

        Args:
            threshold_ms: Duration threshold in milliseconds
            limit: Maximum number of results

        Returns:
            List of slow execution metrics
        """
        slow_metrics = [
            m
            for m in self.metrics_history
            if m.duration_ms and m.duration_ms > threshold_ms
        ]

        # Sort by duration (slowest first)
        slow_metrics.sort(key=lambda m: m.duration_ms or 0, reverse=True)

        return [
            {
                "tool_name": m.tool_name,
                "session_id": m.session_id,
                "duration_ms": m.duration_ms,
                "status": m.status,
                "timestamp": m.start_time,
                "metadata": m.metadata,
            }
            for m in slow_metrics[:limit]
        ]

    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of errors.

        Returns:
            Error summary dictionary
        """
        error_metrics = [m for m in self.metrics_history if m.status == "error"]

        # Group by tool
        errors_by_tool: Dict[str, List[ToolExecutionMetric]] = defaultdict(list)
        for metric in error_metrics:
            errors_by_tool[metric.tool_name].append(metric)

        # Group by error message
        errors_by_message: Dict[str, int] = defaultdict(int)
        for metric in error_metrics:
            if metric.error_message:
                errors_by_message[metric.error_message] += 1

        return {
            "total_errors": len(error_metrics),
            "errors_by_tool": {
                tool: len(metrics) for tool, metrics in errors_by_tool.items()
            },
            "top_error_messages": sorted(
                [
                    {"message": msg, "count": count}
                    for msg, count in errors_by_message.items()
                ],
                key=lambda x: x["count"],  # type: ignore
                reverse=True,
            )[:10],
        }

    def reset(self) -> None:
        """Reset all metrics and statistics."""
        self.metrics_history.clear()
        self.active_metrics.clear()
        self.tool_stats.clear()
        self.start_time = datetime.now()

    def export_metrics(self) -> Dict[str, Any]:
        """Export all metrics for external monitoring.

        Returns:
            Complete metrics export
        """
        return {
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": int((datetime.now() - self.start_time).total_seconds()),
            "statistics": self.get_all_stats(),
            "recent_metrics": self.get_recent_metrics(limit=100),
            "slow_executions": self.get_slow_executions(),
            "error_summary": self.get_error_summary(),
        }
