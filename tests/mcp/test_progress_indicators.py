"""Tests for progress indicator functionality."""

import pytest

pytestmark = pytest.mark.unit

from datetime import datetime
from agentic_inquiry.mcp.utils.progress import ProgressEvent, ProgressHandler


class TestProgressEvent:
    """Test ProgressEvent dataclass."""
    
    def test_progress_event_creation(self):
        """Test creating a progress event."""
        event = ProgressEvent(
            event_type="progress",
            current=5,
            total=10,
            file="test.py",
            percent=50
        )
        
        assert event.event_type == "progress"
        assert event.current == 5
        assert event.total == 10
        assert event.file == "test.py"
        assert event.percent == 50
        assert isinstance(event.timestamp, datetime)
    
    def test_progress_event_to_dict(self):
        """Test converting progress event to dictionary."""
        event = ProgressEvent(
            event_type="progress",
            current=5,
            total=10,
            file="test.py",
            percent=50
        )
        
        event_dict = event.to_dict()
        
        assert event_dict["event_type"] == "progress"
        assert event_dict["current"] == 5
        assert event_dict["total"] == 10
        assert event_dict["file"] == "test.py"
        assert event_dict["percent"] == 50
        assert "timestamp" in event_dict


class TestProgressHandler:
    """Test ProgressHandler class."""
    
    def test_progress_handler_initialization(self):
        """Test progress handler initialization."""
        handler = ProgressHandler()
        
        assert handler.events == []
        assert handler._start_time is None
        assert handler._last_event_time is None
    
    def test_on_progress(self):
        """Test handling progress events."""
        handler = ProgressHandler()
        
        handler.on_progress(current=5, total=10, file="test.py", percent=50)
        
        assert len(handler.events) == 1
        event = handler.events[0]
        assert event.event_type == "progress"
        assert event.current == 5
        assert event.total == 10
        assert event.file == "test.py"
        assert event.percent == 50
        assert handler._start_time is not None
        assert handler._last_event_time is not None
    
    def test_on_complete(self):
        """Test handling completion events."""
        handler = ProgressHandler()
        
        handler.on_complete(total=10, duration_ms=1000)
        
        assert len(handler.events) == 1
        event = handler.events[0]
        assert event.event_type == "complete"
        assert event.current == 10
        assert event.total == 10
        assert event.percent == 100
        assert "Completed 10 items" in event.message
    
    def test_on_error(self):
        """Test handling error events."""
        handler = ProgressHandler()
        
        handler.on_error(current=5, total=10, percent=50, error="Test error")
        
        assert len(handler.events) == 1
        event = handler.events[0]
        assert event.event_type == "error"
        assert event.current == 5
        assert event.total == 10
        assert event.percent == 50
        assert event.message == "Test error"
    
    def test_get_events(self):
        """Test getting all collected events."""
        handler = ProgressHandler()
        
        handler.on_progress(current=5, total=10, file="test.py", percent=50)
        handler.on_progress(current=10, total=10, file="test2.py", percent=100)
        
        events = handler.get_events()
        
        assert len(events) == 2
        assert events[0].current == 5
        assert events[1].current == 10
    
    def test_format_progress(self):
        """Test formatting progress events as messages."""
        handler = ProgressHandler()
        
        handler.on_progress(current=5, total=10, file="test.py", percent=50)
        handler.on_complete(total=10, duration_ms=1000)
        
        messages = handler.format_progress()
        
        assert len(messages) == 2
        assert "Progress: 5/10 (50%)" in messages[0]
        assert "test.py" in messages[0]
        assert "Operation complete" in messages[1] or "Completed 10 items" in messages[1]
    
    def test_get_summary(self):
        """Test getting progress summary."""
        handler = ProgressHandler()
        
        handler.on_progress(current=5, total=10, file="test.py", percent=50)
        handler.on_progress(current=10, total=10, file="test2.py", percent=100)
        handler.on_complete(total=10, duration_ms=1000)
        
        summary = handler.get_summary()
        
        assert summary["total_events"] == 3
        assert summary["completed"] is True
        assert summary["had_errors"] is False
        assert summary["current"] == 10
        assert summary["total"] == 10
        assert summary["percent"] == 100
        assert "duration_seconds" in summary
    
    def test_get_summary_empty(self):
        """Test getting summary with no events."""
        handler = ProgressHandler()
        
        summary = handler.get_summary()
        
        assert summary["total_events"] == 0
        assert summary["completed"] is False
        assert summary["had_errors"] is False
    
    def test_get_summary_with_errors(self):
        """Test getting summary with error events."""
        handler = ProgressHandler()
        
        handler.on_progress(current=5, total=10, file="test.py", percent=50)
        handler.on_error(current=6, total=10, percent=60, error="Test error")
        
        summary = handler.get_summary()
        
        assert summary["had_errors"] is True
        assert summary["completed"] is False
    
    def test_clear(self):
        """Test clearing collected events."""
        handler = ProgressHandler()
        
        handler.on_progress(current=5, total=10, file="test.py", percent=50)
        handler.on_complete(total=10, duration_ms=1000)
        
        assert len(handler.events) == 2
        
        handler.clear()
        
        assert len(handler.events) == 0
        assert handler._start_time is None
        assert handler._last_event_time is None
    
    def test_multiple_progress_events(self):
        """Test collecting multiple progress events."""
        handler = ProgressHandler()
        
        for i in range(1, 11):
            handler.on_progress(
                current=i,
                total=10,
                file=f"test{i}.py",
                percent=i * 10
            )
        
        assert len(handler.events) == 10
        assert handler.events[0].current == 1
        assert handler.events[9].current == 10
        assert handler.events[9].percent == 100
