"""MCP-specific Pydantic models for sessions, responses, and errors.

Note: Request models are no longer needed as tools use function parameters directly.
FastMCP generates schemas from function type hints automatically.
"""

from agentic_inquiry.mcp.models.session import (
    Session,
    SessionState,
    ProjectStatistics,
)
from agentic_inquiry.mcp.models.responses import (
    SessionInfoResponse,
    GetSessionResponse,
    ListSessionsResponse,
    ResumeSessionResponse,
    SearchResult,
    SearchKnowledgeResponse,
    AddKnowledgeResponse,
    ContextResponse,
    EntityInfo,
    EntityDetail,
    UnderstandEntityResponse,
    ImpactAnalysisResponse,
    Memory,
    MemoryInfoResponse,
    SaveMemoryResponse,
    RecallMemoriesResponse,
    EventInfo,
    GetEventsResponse,
    ProjectInfoResponse,
    PatternMatch,
    FindPatternsResponse,
    ActivityItem,
    RecentActivityResponse,
)
from agentic_inquiry.mcp.models.errors import (
    MCPError,
    SessionNotFoundError,
    EntityNotFoundError,
    ValidationError,
)

__all__ = [
    # Session models
    "Session",
    "SessionState",
    "ProjectStatistics",
    # Response models
    "SessionInfoResponse",
    "GetSessionResponse",
    "ListSessionsResponse",
    "ResumeSessionResponse",
    "SearchResult",
    "SearchKnowledgeResponse",
    "AddKnowledgeResponse",
    "ContextResponse",
    "EntityInfo",
    "EntityDetail",
    "UnderstandEntityResponse",
    "ImpactAnalysisResponse",
    "Memory",
    "MemoryInfoResponse",
    "SaveMemoryResponse",
    "RecallMemoriesResponse",
    "EventInfo",
    "GetEventsResponse",
    "ProjectInfoResponse",
    "PatternMatch",
    "FindPatternsResponse",
    "ActivityItem",
    "RecentActivityResponse",
    # Error models
    "MCPError",
    "SessionNotFoundError",
    "EntityNotFoundError",
    "ValidationError",
]
