"""Tests for Session model changes - Task 1."""

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from agent_vault.mcp.models.session import Session, SessionState

pytestmark = pytest.mark.unit


class TestSessionToDbRecord:
    """Tests for to_db_record method."""
    
    def test_to_db_record_includes_ttl_hours(self):
        """Test to_db_record includes ttl_hours field."""
        session = Session(
            session_id="test_id",
            project_id="test_project",
            ttl_hours=72
        )
        
        record = session.to_db_record()
        
        assert "ttl_hours" in record
        assert record["ttl_hours"] == 72
    
    def test_to_db_record_includes_all_fields(self):
        """Test to_db_record includes all required fields."""
        session = Session(
            session_id="test_id",
            project_id="test_project",
            description="Test session",
            ttl_hours=48
        )
        
        record = session.to_db_record()
        
        # Verify all required fields are present
        required_fields = [
            "id", "session_id", "project_id", "state", "status",
            "created_at", "last_active", "description", "log_file",
            "context_state_json", "is_expired", "history_json", "events_json", "ttl_hours"
        ]

        for field in required_fields:
            assert field in record, f"Missing field: {field}"
    
    def test_to_db_record_is_expired_uses_property(self):
        """Test to_db_record uses is_expired property value."""
        # New session should have is_expired = False
        new_session = Session(
            session_id="test_id",
            project_id="test_project",
            ttl_hours=48
        )
        
        record = new_session.to_db_record()
        assert record["is_expired"] is False
        
        # Old session should have is_expired = True
        old_time = datetime.now() - timedelta(hours=50)
        old_session = Session(
            session_id="test_id2",
            project_id="test_project",
            created_at=old_time,
            ttl_hours=48
        )
        
        record = old_session.to_db_record()
        assert record["is_expired"] is True


class TestSessionFromDbRecord:
    """Tests for from_db_record method."""
    
    def test_from_db_record_handles_ttl_hours(self):
        """Test from_db_record extracts ttl_hours from record."""
        db_record = {
            "session_id": "test_id",
            "project_id": "test_project",
            "state": "active",
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "description": None,
            "log_file": None,
            "context_state": {},
            "is_expired": False,
            "history": [],
            "ttl_hours": 72
        }
        
        session = Session.from_db_record(db_record)
        
        assert session.ttl_hours == 72
    
    def test_from_db_record_defaults_missing_ttl_hours(self):
        """Test from_db_record uses default of 48 for missing ttl_hours."""
        db_record = {
            "session_id": "test_id",
            "project_id": "test_project",
            "state": "active",
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "description": None,
            "log_file": None,
            "context_state": {},
            "is_expired": False,
            "history": []
            # ttl_hours is missing
        }
        
        session = Session.from_db_record(db_record)
        
        assert session.ttl_hours == 48
    
    def test_from_db_record_reconstructs_correctly(self):
        """Test from_db_record reconstructs all fields correctly."""
        now = datetime.now()
        db_record = {
            "id": "test_id",
            "session_id": "test_id",
            "project_id": "test_project",
            "state": "active",
            "created_at": now.isoformat(),
            "last_active": now.isoformat(),
            "description": "Test session",
            "log_file": "/path/to/log.log",
            "context_state": {"key": "value"},
            "is_expired": False,
            "history": [{"tool": "test", "params": {}}],
            "ttl_hours": 96
        }
        
        session = Session.from_db_record(db_record)
        
        assert session.session_id == "test_id"
        assert session.project_id == "test_project"
        assert session.state == SessionState.ACTIVE
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_active, datetime)
        assert session.description == "Test session"
        assert isinstance(session.log_file, Path)
        assert session.context_state == {"key": "value"}
        assert len(session.history) == 1
        assert session.ttl_hours == 96


class TestSessionStatusField:
    """Tests for Session status field - Task 8.1."""
    
    def test_session_has_status_field(self):
        """Test Session model has status field."""
        session = Session(
            session_id="test_id",
            project_id="test_project"
        )
        
        assert hasattr(session, 'status')
        assert isinstance(session.status, str)
    
    def test_status_defaults_to_active(self):
        """Test status field defaults to 'active'."""
        session = Session(
            session_id="test_id",
            project_id="test_project"
        )
        
        assert session.status == "active"
    
    def test_status_can_be_set(self):
        """Test status can be set to different values."""
        # Test active
        session_active = Session(
            session_id="test_id",
            project_id="test_project",
            status="active"
        )
        assert session_active.status == "active"
        
        # Test expired
        session_expired = Session(
            session_id="test_id2",
            project_id="test_project",
            status="expired"
        )
        assert session_expired.status == "expired"
        
        # Test closed
        session_closed = Session(
            session_id="test_id3",
            project_id="test_project",
            status="closed"
        )
        assert session_closed.status == "closed"
    
    def test_mark_expired_updates_status(self):
        """Test mark_expired() updates both state and status."""
        session = Session(
            session_id="test_id",
            project_id="test_project",
            status="active"
        )
        
        # Mark as expired
        session.mark_expired()
        
        # Verify both state and status are updated
        assert session.state == SessionState.EXPIRED
        assert session.status == "expired"
    
    def test_to_db_record_includes_status(self):
        """Test to_db_record includes status field."""
        session = Session(
            session_id="test_id",
            project_id="test_project",
            status="active"
        )
        
        record = session.to_db_record()
        
        assert "status" in record
        assert record["status"] == "active"
    
    def test_from_db_record_extracts_status(self):
        """Test from_db_record extracts status from record."""
        db_record = {
            "session_id": "test_id",
            "project_id": "test_project",
            "state": "active",
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "description": None,
            "log_file": None,
            "context_state": {},
            "is_expired": False,
            "history": [],
            "ttl_hours": 48
        }
        
        session = Session.from_db_record(db_record)
        
        assert session.status == "active"
    
    def test_from_db_record_defaults_missing_status(self):
        """Test from_db_record uses default 'active' if status is missing."""
        # Record without status field
        db_record = {
            "session_id": "test_id",
            "project_id": "test_project",
            "state": "expired",
            # status field is missing
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "description": None,
            "log_file": None,
            "context_state": {},
            "is_expired": True,
            "history": [],
            "ttl_hours": 48
        }
        
        session = Session.from_db_record(db_record)
        
        # Status should default to 'active'
        assert session.status == "active"
    
    def test_activity_log_property_exists(self):
        """Test Session has activity_log property."""
        session = Session(
            session_id="test_id",
            project_id="test_project"
        )
        
        assert hasattr(session, 'activity_log')
        assert isinstance(session.activity_log, list)
    
    def test_activity_log_formats_history(self):
        """Test activity_log returns formatted history entries."""
        session = Session(
            session_id="test_id",
            project_id="test_project"
        )
        
        # Add some history
        session.add_to_history("search_knowledge", {"query": "test"})
        session.add_to_history("build_context", {"query": "test2"})
        
        activity_log = session.activity_log
        
        # Should have 2 entries
        assert len(activity_log) == 2
        
        # Each entry should be a formatted string
        for entry in activity_log:
            assert isinstance(entry, str)
            assert ":" in entry  # Should have timestamp:tool format


class TestSessionRoundTrip:
    """Tests for round-trip persistence."""
    
    def test_round_trip_with_ttl_hours(self):
        """Test round-trip: to_db_record -> from_db_record preserves ttl_hours."""
        original = Session(
            session_id="test_id",
            project_id="test_project",
            description="Round trip test",
            ttl_hours=120
        )
        
        # Convert to DB record and back
        db_record = original.to_db_record()
        reconstructed = Session.from_db_record(db_record)
        
        # Verify ttl_hours is preserved
        assert reconstructed.ttl_hours == original.ttl_hours
        assert reconstructed.ttl_hours == 120
    
    def test_round_trip_preserves_all_fields(self):
        """Test round-trip preserves all fields including ttl_hours."""
        original = Session(
            session_id="test_id",
            project_id="test_project",
            description="Complete test",
            ttl_hours=72
        )
        
        # Add some history
        original.add_to_history("test_tool", {"param": "value"})
        
        # Convert to DB record and back
        db_record = original.to_db_record()
        reconstructed = Session.from_db_record(db_record)
        
        # Verify all fields match
        assert reconstructed.session_id == original.session_id
        assert reconstructed.project_id == original.project_id
        assert reconstructed.state == original.state
        assert reconstructed.description == original.description
        assert reconstructed.ttl_hours == original.ttl_hours
        assert len(reconstructed.history) == len(original.history)
        assert reconstructed.context_state == original.context_state
    
    def test_round_trip_preserves_status(self):
        """Test round-trip preserves status field."""
        original = Session(
            session_id="test_id",
            project_id="test_project",
            status="expired"
        )
        
        # Convert to DB record and back
        db_record = original.to_db_record()
        reconstructed = Session.from_db_record(db_record)
        
        # Verify status is preserved
        assert reconstructed.status == original.status
        assert reconstructed.status == "expired"
