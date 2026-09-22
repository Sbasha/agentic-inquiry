"""Database schemas for MCP tables.

This module defines the schemas for MCP-specific tables:
- mcp_sessions: Session tracking and state management
- mcp_events: Event logging for debugging and monitoring
"""

from typing import Dict, Any, List


# MCP Sessions Table Schema
MCP_SESSIONS_SCHEMA: Dict[str, Any] = {
    "session_id": "str",           # UUID - Primary key
    "project_id": "str",           # Project identifier
    "created_at": "timestamp",     # Session creation time
    "last_active": "timestamp",    # Last activity timestamp
    "description": "str",          # Optional session description
    "state": "str",                # SessionState enum value
    "status": "str",               # Session status (active, expired, closed)
    "log_file": "str",             # Path to session log file
    "context_state_json": "str",   # Serialized context state dict
    "history_json": "str",         # Serialized tool call history
    "events_json": "str",          # Serialized session events
    "is_expired": "bool",          # Whether session has expired
    "ttl_hours": "int",            # Time-to-live in hours
}

# MCP Events Table Schema
MCP_EVENTS_SCHEMA: Dict[str, Any] = {
    "event_id": "str",             # UUID - Primary key
    "session_id": "str",           # Associated session ID
    "event_type": "str",           # Event type (tool.executed, indexing.started, etc.)
    "timestamp": "timestamp",      # Event timestamp
    "status": "str",               # Event status (success, error, etc.)
    "message": "str",              # Event message
    "details_json": "str",         # Serialized event details
    "duration_ms": "int",          # Operation duration in milliseconds
}

# Indices for performance
MCP_SESSIONS_INDICES: List[str] = [
    "project_id",      # For filtering sessions by project
    "last_active",     # For finding expired sessions
    "is_expired",      # For filtering active/expired sessions
]

MCP_EVENTS_INDICES: List[str] = [
    "session_id",      # For filtering events by session
    "timestamp",       # For time-range queries
    "event_type",      # For filtering by event type
]


def get_mcp_table_schemas() -> Dict[str, Dict[str, Any]]:
    """Get all MCP table schemas.
    
    Returns:
        Dictionary mapping table names to their schemas
    """
    return {
        "mcp_sessions": MCP_SESSIONS_SCHEMA,
        "mcp_events": MCP_EVENTS_SCHEMA,
    }


def get_mcp_table_indices() -> Dict[str, List[str]]:
    """Get all MCP table indices.
    
    Returns:
        Dictionary mapping table names to their index fields
    """
    return {
        "mcp_sessions": MCP_SESSIONS_INDICES,
        "mcp_events": MCP_EVENTS_INDICES,
    }


__all__ = [
    "MCP_SESSIONS_SCHEMA",
    "MCP_EVENTS_SCHEMA",
    "MCP_SESSIONS_INDICES",
    "MCP_EVENTS_INDICES",
    "get_mcp_table_schemas",
    "get_mcp_table_indices",
]
