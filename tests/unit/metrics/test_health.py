from agent_vault.metrics import MetricsTracker
from agent_vault.metrics.health import HealthTracker
from agent_vault.models.health import HealthStatus

def test_health_tracker_latency_degradation():
    metrics = MetricsTracker()
    tracker = HealthTracker(metrics_tracker=metrics)
    
    # Simulate degraded search latency (1.2s > 1.0s threshold)
    latency_metrics = metrics.get_latency_metrics("search")
    for _ in range(10):
        latency_metrics.record(1.2)
        
    health = tracker.get_component_health("search")
    assert health.status == HealthStatus.DEGRADED
    assert any("Latency P95" in issue for issue in health.issues)

def test_health_tracker_critical_latency():
    metrics = MetricsTracker()
    tracker = HealthTracker(metrics_tracker=metrics)
    
    # Simulate critical search latency (2.5s > 2.0s threshold)
    latency_metrics = metrics.get_latency_metrics("search")
    for _ in range(10):
        latency_metrics.record(2.5)
        
    health = tracker.get_component_health("search")
    assert health.status == HealthStatus.CRITICAL

def test_overall_health_aggregation():
    metrics = MetricsTracker()
    tracker = HealthTracker(metrics_tracker=metrics)
    
    # Search is degraded
    latency_search = metrics.get_latency_metrics("search")
    latency_search.record(1.1)
    
    # Indexing is critical
    latency_indexing = metrics.get_latency_metrics("indexing")
    latency_indexing.record(10.0) # assuming 2.0 is default critical if not specified
    
    overall = tracker.get_overall_health()
    assert overall.overall_status == HealthStatus.CRITICAL
    assert "search" in overall.components
    assert "indexing" in overall.components
    assert len(overall.insights) >= 2
