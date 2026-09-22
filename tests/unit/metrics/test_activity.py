from datetime import datetime, timedelta
from agentic_inquiry.metrics import MetricsTracker
from agentic_inquiry.metrics.health import HealthTracker
import agentic_inquiry.metrics.health as health_module

def test_health_tracker_activity_detection(monkeypatch):
    metrics = MetricsTracker()
    tracker = HealthTracker(metrics_tracker=metrics)
    
    class FixedDateTime(datetime):
        current = datetime(2024, 1, 1, 0, 0, 0)

        @classmethod
        def now(cls):
            return cls.current

    monkeypatch.setattr(health_module, "datetime", FixedDateTime)

    # Initial state: inactive
    assert tracker.is_active() is False
    
    # Record some activity
    metrics.increment("search.total")
    
    # Should now be active
    assert tracker.is_active() is True
    
    # Wait for threshold (simulated)
    FixedDateTime.current = FixedDateTime.current + timedelta(seconds=40)
    assert tracker.is_active(threshold_seconds=30) is False

def test_health_tracker_activity_threshold(monkeypatch):
    metrics = MetricsTracker()
    tracker = HealthTracker(metrics_tracker=metrics)

    class FixedDateTime(datetime):
        current = datetime(2024, 1, 1, 0, 0, 0)

        @classmethod
        def now(cls):
            return cls.current

    monkeypatch.setattr(health_module, "datetime", FixedDateTime)

    metrics.increment("search.total")
    tracker.is_active()  # updates last_activity_time to now
    
    FixedDateTime.current = FixedDateTime.current + timedelta(seconds=5)
    assert tracker.is_active(threshold_seconds=10) is True
    
    # Advance beyond threshold
    FixedDateTime.current = FixedDateTime.current + timedelta(seconds=11)
    assert tracker.is_active(threshold_seconds=10) is False
