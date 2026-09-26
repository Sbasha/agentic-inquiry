"""
Models for system-wide cognitive health tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List


class HealthStatus(Enum):
    """Overall health status of a cognitive component."""

    OPTIMAL = "optimal"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health metrics for a specific cognitive component."""

    component_id: str
    status: HealthStatus
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Key performance indicators
    latency_p95: float = 0.0
    error_rate: float = 0.0
    throughput: float = 0.0

    # Component-specific metrics
    metrics: Dict[str, Any] = field(default_factory=dict)

    # Reasons for current status
    issues: List[str] = field(default_factory=list)


@dataclass
class CognitiveHealthState:
    """Aggregate health state of the entire 'brain'."""

    overall_status: HealthStatus
    components: Dict[str, ComponentHealth] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Global insights (e.g., "Memory entropy is high")
    insights: List[str] = field(default_factory=list)
