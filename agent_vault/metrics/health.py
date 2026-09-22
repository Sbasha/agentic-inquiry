"""
Health tracking service for monitoring cognitive performance and stability.
"""

import logging
from datetime import datetime
from typing import Optional

from agent_vault.metrics import get_metrics_tracker, MetricsTracker
from agent_vault.models.health import ComponentHealth, CognitiveHealthState, HealthStatus

logger = logging.getLogger(__name__)


class HealthTracker:
    """Aggregates latency, error, and component-health metrics."""

    def __init__(self, metrics_tracker: Optional[MetricsTracker] = None) -> None:
        """Initialize health tracker."""
        self.metrics = metrics_tracker or get_metrics_tracker()
        self._thresholds = {
            "search.latency_p95_critical": 2.0,  # seconds
            "search.latency_p95_degraded": 1.0,  # seconds
            "memory.retrieval_p95_critical": 1.5,
            "memory.retrieval_p95_degraded": 0.8,
            "error_rate_critical": 0.1,  # 10%
        }

    def get_component_health(self, component_id: str) -> ComponentHealth:
        """
        Evaluate health for a specific component based on metrics.
        """
        issues = []
        status = HealthStatus.OPTIMAL
        
        # Pull raw metrics
        all_metrics = self.metrics.get_all_metrics()
        latency_data = all_metrics["latency"].get(component_id, {})
        counters = all_metrics["counters"]
        
        # Calculate latency health
        p95 = latency_data.get("p95", 0.0)
        
        critical_thresh = self._thresholds.get(f"{component_id}.latency_p95_critical", 2.0)
        degraded_thresh = self._thresholds.get(f"{component_id}.latency_p95_degraded", 1.0)
        
        if p95 >= critical_thresh:
            status = HealthStatus.CRITICAL
            issues.append(f"Latency P95 ({p95:.2f}s) exceeds critical threshold ({critical_thresh}s)")
        elif p95 >= degraded_thresh:
            status = HealthStatus.DEGRADED
            issues.append(f"Latency P95 ({p95:.2f}s) exceeds degraded threshold ({degraded_thresh}s)")
            
        # Error rate check (if tracked)
        # e.g., search.errors / search.total
        total_key = f"{component_id}.total"
        error_key = f"{component_id}.errors"
        
        if total_key in counters and counters[total_key] > 0:
            error_count = counters.get(error_key, 0)
            error_rate = error_count / counters[total_key]
            if error_rate > self._thresholds["error_rate_critical"]:
                status = HealthStatus.CRITICAL
                issues.append(f"Error rate ({error_rate:.1%}) is critical")
        
        return ComponentHealth(
            component_id=component_id,
            status=status,
            latency_p95=p95,
            issues=issues,
            metrics=latency_data
        )

    def get_overall_health(self) -> CognitiveHealthState:
        """
        Aggregate health status across all major cognitive components.
        """
        components_to_track = ["search", "memory", "indexing"]
        component_healths = {}
        worst_status = HealthStatus.OPTIMAL
        insights = []
        
        for cid in components_to_track:
            health = self.get_component_health(cid)
            component_healths[cid] = health
            
            # Aggregate status
            if health.status == HealthStatus.CRITICAL:
                worst_status = HealthStatus.CRITICAL
            elif health.status == HealthStatus.DEGRADED and worst_status != HealthStatus.CRITICAL:
                worst_status = HealthStatus.DEGRADED
                
            if health.issues:
                insights.extend([f"[{cid}] {issue}" for issue in health.issues])

        return CognitiveHealthState(
            overall_status=worst_status,
            components=component_healths,
            insights=insights
        )

    def is_active(self, threshold_seconds: int = 30) -> bool:
        """
        Check if the system has been active (queries/indexing) in the last N seconds.
        """
        all_metrics = self.metrics.get_all_metrics()
        counters = all_metrics["counters"]
        active_indicators = ["search.total", "memory.stored", "memory.retrieved"]
        
        now = datetime.now().timestamp()
        current_activity_count = sum(counters.get(k, 0) for k in active_indicators)
        
        # Initialize if not already done
        if not hasattr(self, "_last_activity_count"):
            self._last_activity_count = current_activity_count
            self._last_activity_time = now if current_activity_count > 0 else 0.0
            return current_activity_count > 0
            
        # Check for NEW activity since last check
        if current_activity_count > self._last_activity_count:
            self._last_activity_count = current_activity_count
            self._last_activity_time = now
            return True
            
        # Check if we are within the quiet period of the LAST detected activity
        if self._last_activity_time == 0.0:
            return False
            
        return (now - self._last_activity_time) < threshold_seconds
