"""Response models for MCP tools."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Async Indexing Responses
class AsyncIndexingResponse(BaseModel):
    """Response for asynchronous add_knowledge operations."""

    status: str = Field(..., description="Operation status: started, completed, failed")
    operation_id: str = Field(
        ..., description="Unique operation identifier for tracking"
    )
    message: str = Field(..., description="Human-readable status message")
    monitor_instructions: str = Field(
        ..., description="Instructions on how to monitor progress"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status,
            "operation_id": self.operation_id,
            "message": self.message,
            "monitor_instructions": self.monitor_instructions,
        }


# Session Management Responses
class SessionInfoResponse(BaseModel):
    """Response with session information."""

    session_id: str = Field(..., description="Session identifier")
    project_id: str = Field(..., description="Project identifier")
    created_at: str = Field(..., description="Session creation time (ISO 8601)")
    state: str = Field(
        default="active",
        description="Session lifecycle state: active, expired, archived",
    )
    status: str = Field(..., description="Index status: empty, partial, ready")
    statistics: Dict[str, Any] = Field(..., description="Project statistics")
    log_file: str = Field(..., description="Path to session log file")
    guidance: str = Field(..., description="Next steps guidance")
    next_steps: List[str] = Field(
        default_factory=list, description="Suggested next actions"
    )


class GetSessionResponse(BaseModel):
    """Response with detailed session information."""

    session_id: str = Field(..., description="Session identifier")
    project_id: str = Field(..., description="Project identifier")
    created_at: str = Field(..., description="Session creation time (ISO 8601)")
    last_active: str = Field(..., description="Last activity time (ISO 8601)")
    description: Optional[str] = Field(None, description="Session description")
    is_expired: bool = Field(..., description="Whether session is expired")
    age_hours: float = Field(..., description="Session age in hours")
    inactive_hours: float = Field(..., description="Hours since last activity")
    statistics: Dict[str, Any] = Field(..., description="Project statistics")
    state: str = Field(
        ..., description="Session lifecycle state: active, expired, archived"
    )
    log_file: str = Field(..., description="Path to session log file")
    history: Optional[List[Dict[str, Any]]] = Field(
        None, description="Tool call history"
    )
    history_count: int = Field(..., description="Number of history entries")


class ListSessionsResponse(BaseModel):
    """Response with list of sessions."""

    sessions: List[Dict[str, Any]] = Field(..., description="List of sessions")
    total_count: int = Field(..., description="Total number of sessions")
    filters: Dict[str, Any] = Field(..., description="Applied filters")


class ResumeSessionResponse(BaseModel):
    """Response when resuming a session."""

    session_id: str = Field(..., description="Session identifier")
    project_id: str = Field(..., description="Project identifier")
    last_active: str = Field(..., description="Updated last activity time (ISO 8601)")
    created_at: str = Field(..., description="Session creation time (ISO 8601)")
    status: str = Field(..., description="Session status")
    state: Dict[str, Any] = Field(
        ..., description="Restored context state for multi-turn refinement"
    )
    statistics: Dict[str, Any] = Field(..., description="Current project statistics")
    guidance: str = Field(..., description="Next steps guidance")
    next_steps: List[str] = Field(
        default_factory=list, description="Suggested next actions"
    )
    history_count: int = Field(..., description="Number of history entries")
    log_file: str = Field(..., description="Path to session log file")


# Knowledge Management Responses
class SearchResult(BaseModel):
    """Individual search result."""

    id: str = Field(..., description="Result identifier")
    type: str = Field(..., description="Result type (code, doc, etc.)")
    title: str = Field(..., description="Result title")
    summary: str = Field(..., description="Result summary")
    relevance_score: float = Field(
        ..., ge=0.0, le=1.0, description="Relevance score (0.0-1.0)"
    )
    location: str = Field(..., description="Source file path")
    snippet: str = Field(..., description="Content snippet")
    content: Optional[str] = Field(None, description="Full content (if requested)")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class SearchKnowledgeResponse(BaseModel):
    """Response from knowledge search."""

    results: List[SearchResult] = Field(..., description="Search results")
    total_results: int = Field(..., description="Total number of results")
    search_time_ms: int = Field(
        ..., description="Search execution time in milliseconds"
    )
    search_strategy: str = Field(
        ..., description="Search strategy used (hybrid, vector, fts)"
    )
    suggestions: List[str] = Field(
        default_factory=list, description="Query suggestions"
    )
    facets: Optional[Dict[str, Any]] = Field(None, description="Result facets")


class AddKnowledgeResponse(BaseModel):
    """Response from adding knowledge."""

    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="Job status: completed, failed")
    items_processed: int = Field(
        ..., description="Number of items successfully processed"
    )
    items_failed: int = Field(..., description="Number of items that failed")
    errors: List[str] = Field(default_factory=list, description="Error messages")
    next_steps: List[str] = Field(
        default_factory=list, description="Suggested next actions"
    )


# Context Building Responses
class ContextResponse(BaseModel):
    """Response with built context."""

    context: str = Field(..., description="Built context text")
    token_count: int = Field(..., description="Actual token count")
    sources: List[Dict[str, Any]] = Field(..., description="Source chunks used")
    entities_included: List[str] = Field(
        ..., description="Entities included in context"
    )
    truncated: bool = Field(..., description="Whether context was truncated")


# Entity Understanding Responses
class EntityInfo(BaseModel):
    """Entity information used in entity tool."""

    id: str = Field(..., description="Entity identifier")
    name: str = Field(..., description="Entity name")
    type: str = Field(..., description="Entity type")
    location: str = Field(..., description="Entity location (file path)")
    definition: Optional[str] = Field(None, description="Entity definition")
    documentation: Optional[str] = Field(None, description="Entity documentation")
    signature: Optional[str] = Field(None, description="Entity signature")
    language: str = Field(..., description="Programming language")


class EntityDetail(BaseModel):
    """Detailed entity information."""

    name: str = Field(..., description="Entity name")
    type: str = Field(..., description="Entity type")
    qualified_name: str = Field(..., description="Fully qualified name")
    file_path: str = Field(..., description="Source file path")
    line_start: Optional[int] = Field(None, description="Starting line number")
    line_end: Optional[int] = Field(None, description="Ending line number")
    definition: Optional[str] = Field(None, description="Entity definition")
    docstring: Optional[str] = Field(None, description="Entity documentation")


class UnderstandEntityResponse(BaseModel):
    """Response with entity understanding."""

    entity: EntityDetail = Field(..., description="Entity details")
    usage: Optional[List[Dict[str, Any]]] = Field(None, description="Usage examples")
    dependencies: Optional[List[Dict[str, Any]]] = Field(
        None, description="Dependencies"
    )
    related_entities: List[str] = Field(
        default_factory=list, description="Related entities"
    )


# Impact Analysis Responses
class ImpactAnalysisResponse(BaseModel):
    """Response with impact analysis."""

    target: Dict[str, Any] = Field(..., description="Target entity information")
    impact: Dict[str, Any] = Field(..., description="Impact analysis details")
    areas_to_review: List[str] = Field(
        default_factory=list, description="Areas requiring review"
    )
    test_coverage: Dict[str, Any] = Field(
        default_factory=dict, description="Test coverage information"
    )
    risk_assessment: str = Field(
        ..., description="Risk level: low, medium, high, or critical"
    )
    recommendations: List[str] = Field(
        default_factory=list, description="Recommendations"
    )


# Memory Management Responses
class Memory(BaseModel):
    """Individual memory."""

    id: str = Field(..., description="Memory identifier")
    summary: str = Field(..., description="Memory summary")
    content: str = Field(..., description="Memory content")
    created: str = Field(..., description="Creation time (ISO 8601)")
    tags: List[str] = Field(default_factory=list, description="Memory tags")
    importance: str = Field(..., description="Importance level: low, medium, high")
    relevance_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Relevance score (0.0-1.0)"
    )
    related_count: int = Field(default=0, description="Number of related entities")


class MemoryInfoResponse(BaseModel):
    """Response with memory information."""

    memory_id: str = Field(..., description="Memory identifier")
    tier: str = Field(..., description="Memory tier")
    created_at: str = Field(..., description="Creation time (ISO 8601)")
    success: bool = Field(..., description="Whether operation succeeded")


class SaveMemoryResponse(BaseModel):
    """Response from saving a memory."""

    memory_id: str = Field(..., description="Memory identifier")
    created: str = Field(..., description="Creation time (ISO 8601)")
    confirmation: str = Field(..., description="Confirmation message")


class RecallMemoriesResponse(BaseModel):
    """Response with recalled memories."""

    memories: List[Memory] = Field(..., description="Recalled memories")
    total_found: int = Field(..., description="Total number of memories found")
    suggestions: List[str] = Field(
        default_factory=list, description="Search suggestions"
    )


# Events Responses
class EventInfo(BaseModel):
    """Individual event information."""

    event_id: str = Field(..., description="Event identifier")
    event_type: str = Field(..., description="Event type")
    timestamp: str = Field(..., description="Event timestamp (ISO 8601)")
    status: str = Field(..., description="Event status")
    source: str = Field(..., description="Event source")
    message: str = Field(..., description="Human-readable event message")
    details: Dict[str, Any] = Field(
        default_factory=dict, description="Event details/metadata"
    )
    duration_ms: Optional[float] = Field(
        None, description="Event duration in milliseconds"
    )


class GetEventsResponse(BaseModel):
    """Response with events."""

    events: List[Dict[str, Any]] = Field(..., description="List of events")
    total_events: int = Field(..., description="Total number of events")
    summary: Dict[str, Any] = Field(
        default_factory=dict, description="Event summary statistics"
    )
    time_range: Dict[str, Any] = Field(
        default_factory=dict, description="Time range of events"
    )


# Project Info Responses
class ProjectInfoResponse(BaseModel):
    """Response with project information."""

    project_id: str = Field(..., description="Project identifier")
    statistics: Dict[str, Any] = Field(..., description="Project statistics")
    index_health: str = Field(..., description="Index health status")
    last_indexed: Optional[str] = Field(
        None, description="Last indexing time (ISO 8601)"
    )


# Pattern Finding Responses
class PatternMatch(BaseModel):
    """Individual pattern match."""

    pattern_type: str = Field(..., description="Type of pattern")
    location: str = Field(..., description="Location of match")
    code_snippet: str = Field(..., description="Code snippet")
    confidence: float = Field(..., description="Confidence score (0.0-1.0)")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class FindPatternsResponse(BaseModel):
    """Response with found patterns."""

    patterns: List[PatternMatch] = Field(..., description="Found patterns")
    total_count: int = Field(..., description="Total number of patterns")
    pattern_type: str = Field(..., description="Searched pattern type")


# Recent Activity Responses
class ActivityItem(BaseModel):
    """Individual activity item."""

    activity_id: str = Field(..., description="Activity identifier")
    activity_type: str = Field(..., description="Activity type")
    timestamp: str = Field(..., description="Activity timestamp (ISO 8601)")
    session_id: Optional[str] = Field(None, description="Associated session ID")
    project_id: Optional[str] = Field(None, description="Associated project ID")
    description: str = Field(..., description="Activity description")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class RecentActivityResponse(BaseModel):
    """Response with recent activity."""

    activities: List[ActivityItem] = Field(..., description="List of activities")
    total_count: int = Field(..., description="Total number of activities")
    has_more: bool = Field(..., description="Whether more activities are available")


class ResponseMeta(BaseModel):
    """Timing and latency metadata for MCP tool responses.

    Provides performance instrumentation for debugging and monitoring.
    All timing values are in milliseconds.
    """

    execution_time_ms: float = Field(
        ..., description="Total execution time in milliseconds"
    )
    result_count: int = Field(..., description="Number of results returned")
    embedding_time_ms: Optional[float] = Field(
        None, description="Time spent generating embeddings"
    )
    query_time_ms: Optional[float] = Field(
        None, description="Time spent executing queries"
    )
    entity_resolution_time_ms: Optional[float] = Field(
        None, description="Time spent resolving entities"
    )
    graph_traversal_time_ms: Optional[float] = Field(
        None, description="Time spent traversing graph"
    )
    context_build_time_ms: Optional[float] = Field(
        None, description="Time spent building context"
    )
    memory_recall_time_ms: Optional[float] = Field(
        None, description="Time spent recalling memories"
    )


__all__ = [
    "ResponseMeta",
    "AsyncIndexingResponse",
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
]
