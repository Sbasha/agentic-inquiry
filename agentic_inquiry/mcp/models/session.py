"""Session-related models for MCP server."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SessionState(str, Enum):
    """Session lifecycle states."""
    
    ACTIVE = "active"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class ProjectStatistics(BaseModel):
    """Statistics about an indexed project."""
    
    total_chunks: int = Field(..., description="Total number of indexed chunks")
    total_memories: int = Field(..., description="Total number of stored memories")
    total_files: int = Field(..., description="Total number of indexed files")
    last_indexed: Optional[datetime] = Field(None, description="Last indexing timestamp")
    index_health: str = Field(..., description="Index health status: healthy, stale, or empty")
    languages: Dict[str, int] = Field(default_factory=dict, description="File count by language")
    top_directories: List[Dict[str, Any]] = Field(default_factory=list, description="Most active directories")
    indexed_file_count: int = Field(default=0, description="Count of indexed files")
    entity_counts: Dict[str, int] = Field(default_factory=dict, description="Entity counts by type")
    
    model_config = {"frozen": False}
    
    def is_empty(self) -> bool:
        """Check if project has no indexed content."""
        return self.total_chunks == 0 and self.total_files == 0
    
    def is_stale(self, days: int = 30) -> bool:
        """Check if index is stale (not updated in specified days)."""
        if not self.last_indexed:
            # Only stale if truly empty - not just missing timestamp
            return self.total_chunks == 0
        age_days = (datetime.now() - self.last_indexed).days
        return age_days > days
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(mode='json')


class Session(BaseModel):
    """Agent work session."""
    
    session_id: str = Field(..., description="Unique session identifier")
    project_id: str = Field(..., description="Project this session belongs to")
    created_at: datetime = Field(default_factory=datetime.now, description="Session creation time")
    last_active: datetime = Field(default_factory=datetime.now, description="Last activity timestamp")
    description: Optional[str] = Field(None, description="Session description")
    log_file: Optional[Path] = Field(None, description="Path to session log file")
    state: SessionState = Field(default=SessionState.ACTIVE, description="Current session state")
    status: str = Field(default="active", description="Session status (active, expired, closed)")
    context_state: Dict[str, Any] = Field(default_factory=dict, description="Multi-turn refinement state")
    history: List[Dict[str, Any]] = Field(default_factory=list, description="Tool call history")
    events: List[Dict[str, Any]] = Field(default_factory=list, description="Session events for async operations")
    ttl_hours: int = Field(default=48, description="Time-to-live in hours")
    
    model_config = {"frozen": False, "arbitrary_types_allowed": True}
    
    @property
    def is_expired(self) -> bool:
        """Check if session has expired based on TTL or state."""
        # Check if explicitly marked as expired
        if self.state == SessionState.EXPIRED:
            return True
        # Check if TTL has been exceeded
        return (datetime.now() - self.created_at).total_seconds() / 3600 > self.ttl_hours
    
    @property
    def activity_log(self) -> List[str]:
        """Get formatted activity log from history.
        
        Returns:
            List of formatted activity strings
        """
        log = []
        for entry in self.history[-10:]:  # Last 10 entries
            tool = entry.get("tool", "unknown")
            timestamp = entry.get("timestamp", "")
            log.append(f"{timestamp}: {tool}")
        return log
    
    def update_activity(self) -> None:
        """Update last_active timestamp."""
        self.last_active = datetime.now()
    
    def mark_expired(self) -> None:
        """Mark session as expired."""
        self.state = SessionState.EXPIRED
        self.status = "expired"
    
    def get_age_hours(self) -> float:
        """Get session age in hours."""
        return (datetime.now() - self.created_at).total_seconds() / 3600
    
    def get_inactive_hours(self) -> float:
        """Get hours since last activity."""
        return (datetime.now() - self.last_active).total_seconds() / 3600
    
    def add_to_history(self, tool_name: str, params: Dict[str, Any]) -> None:
        """Add tool call to history.
        
        Args:
            tool_name: Name of the tool called
            params: Parameters passed to the tool
        """
        self.history.append({
            "tool": tool_name,
            "params": params,
            "timestamp": datetime.now().isoformat()
        })
        self.update_activity()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return self.model_dump(mode='json')
    
    def to_db_record(self) -> Dict[str, Any]:
        """Convert session to database record format.

        Returns dictionary matching mcp_sessions table schema with:
        - DateTime objects converted to ISO 8601 strings
        - SessionState enum converted to string value
        - Path objects converted to strings
        - Nested structures (context_state, history, events) serialized to JSON
        - All required fields for database storage

        Returns:
            Dictionary matching mcp_sessions schema
        """
        import json

        return {
            "id": self.session_id,  # Primary key for database
            "session_id": self.session_id,
            "project_id": self.project_id,
            "state": self.state.value if isinstance(self.state, SessionState) else self.state,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
            "description": self.description,
            "log_file": str(self.log_file) if self.log_file else None,
            "context_state_json": json.dumps(self.context_state) if self.context_state else "{}",
            "is_expired": self.is_expired,
            "history_json": json.dumps(self.history) if self.history else "[]",
            "events_json": json.dumps(self.events) if self.events else "[]",
            "ttl_hours": self.ttl_hours
        }
    
    @classmethod
    def from_db_record(cls, record: Dict[str, Any]) -> "Session":
        """Reconstruct Session from database record.

        Handles conversion of:
        - ISO 8601 strings to datetime objects
        - String state values to SessionState enum
        - String paths to Path objects
        - JSON strings to Python objects (context_state, history, events)

        Args:
            record: Database record dictionary

        Returns:
            Reconstructed Session object
        """
        import json

        # Create a copy to avoid modifying the original
        data = record.copy()

        # Convert ISO 8601 strings to datetime objects
        if isinstance(data.get('created_at'), str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if isinstance(data.get('last_active'), str):
            data['last_active'] = datetime.fromisoformat(data['last_active'])

        # Convert string state to SessionState enum
        if isinstance(data.get('state'), str):
            data['state'] = SessionState(data['state'])

        # Convert string path to Path object
        if data.get('log_file') and isinstance(data['log_file'], str):
            data['log_file'] = Path(data['log_file'])

        # Deserialize JSON strings to Python objects
        if 'context_state_json' in data:
            json_str = data.pop('context_state_json')
            data['context_state'] = json.loads(json_str) if json_str else {}
        if 'history_json' in data:
            json_str = data.pop('history_json')
            data['history'] = json.loads(json_str) if json_str else []
        if 'events_json' in data:
            json_str = data.pop('events_json')
            data['events'] = json.loads(json_str) if json_str else []

        # Handle missing ttl_hours with default of 48
        if 'ttl_hours' not in data:
            data['ttl_hours'] = 48

        # Handle missing status with default of 'active'
        if 'status' not in data:
            data['status'] = 'active'

        # Remove 'id' field if present (it's just a duplicate of session_id)
        data.pop('id', None)

        return cls(**data)


__all__ = [
    "Session",
    "SessionState",
    "ProjectStatistics",
]
