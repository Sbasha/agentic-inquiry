"""Pydantic models for event payload validation.

This module provides typed Pydantic models for common event payloads to improve
type safety and validation. All models are optional and backwards-compatible with
existing metadata-based event emission.

Example:
    >>> from agentic_inquiry.events.payloads import IndexingStartedPayload
    >>> payload = IndexingStartedPayload(path="/path/to/file", content_type="code")
    >>> await event_system.emit_typed(
    ...     EventTypes.Indexing.STARTED,
    ...     source="pipeline",
    ...     payload=payload
    ... )
"""

from typing import Any, Dict, Literal, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


class BaseEventPayload(BaseModel):
    """Base class for all event payloads.

    Provides common configuration and validation for event payloads.
    """
    model_config = ConfigDict(
        # Allow extra fields for backwards compatibility
        extra="allow",
        # Validate assignment to catch errors early
        validate_assignment=True,
        # Use snake_case for JSON serialization
        populate_by_name=True,
    )

    def to_metadata(self) -> Dict[str, Any]:
        """Convert payload to metadata dict for event emission.

        Returns:
            Dictionary suitable for event metadata
        """
        return self.model_dump(exclude_none=True, by_alias=True)


# ============================================================================
# Indexing Event Payloads
# ============================================================================

class IndexingStartedPayload(BaseEventPayload):
    """Payload for indexing.started event.

    Attributes:
        path: Path to file or directory being indexed
        content_type: Type of content (code, file, directory, etc.)
        file_count: Optional number of files to be indexed
    """
    path: str = Field(..., description="Path to file or directory being indexed")
    content_type: str = Field(..., description="Type of content being indexed")
    file_count: Optional[int] = Field(None, description="Number of files to be indexed")


class IndexingProgressPayload(BaseEventPayload):
    """Payload for indexing.progress event.

    Attributes:
        files_processed: Number of files processed so far
        files_discovered: Total number of files discovered
        chunks_created: Number of chunks created so far
        entities_created: Number of entities created so far
        relationships_created: Number of relationships created so far
    """
    files_processed: Optional[int] = Field(None, description="Number of files processed")
    files_discovered: Optional[int] = Field(None, description="Total files discovered")
    chunks_created: Optional[int] = Field(None, description="Number of chunks created")
    entities_created: Optional[int] = Field(None, description="Number of entities created")
    relationships_created: Optional[int] = Field(None, description="Number of relationships created")


class IndexingCompletedPayload(BaseEventPayload):
    """Payload for indexing.completed event.

    Attributes:
        files_processed: Number of files processed
        chunks_created: Number of chunks created
        entities_created: Number of entities created
        relationships_created: Number of relationships created
        duration_seconds: Optional duration of indexing operation
        success: Whether indexing completed successfully
    """
    files_processed: int = Field(..., description="Number of files processed")
    chunks_created: int = Field(..., description="Number of chunks created")
    entities_created: int = Field(..., description="Number of entities created")
    relationships_created: int = Field(..., description="Number of relationships created")
    duration_seconds: Optional[float] = Field(None, description="Duration of operation")
    success: bool = Field(True, description="Whether operation succeeded")


class IndexingStoredPayload(BaseEventPayload):
    """Payload for indexing.stored event.

    Emitted when chunks have been written to storage but may not yet be
    searchable (e.g. AlloyDB server-side embeddings are still generating).

    Attributes:
        files_processed: Number of files processed
        chunks_created: Number of chunks created
        entities_created: Number of entities created
        relationships_created: Number of relationships created
        duration_seconds: Optional duration of storage operation
        embedding_strategy: Whether embeddings are local or server_side
    """
    files_processed: int = Field(..., description="Number of files processed")
    chunks_created: int = Field(..., description="Number of chunks created")
    entities_created: int = Field(..., description="Number of entities created")
    relationships_created: int = Field(..., description="Number of relationships created")
    duration_seconds: Optional[float] = Field(None, description="Duration of storage operation")
    embedding_strategy: Optional[str] = Field(None, description="Embedding strategy (local or server_side)")


class IndexingReadyPayload(BaseEventPayload):
    """Payload for indexing.ready event.

    Emitted when the index is fully searchable. For local-embedding backends
    this fires simultaneously with indexing.stored. For server-side embedding
    backends (AlloyDB) this fires after embedding generation completes.

    Attributes:
        files_processed: Number of files processed
        chunks_created: Number of chunks created
        entities_created: Number of entities created
        relationships_created: Number of relationships created
        duration_seconds: Optional total duration including embedding generation
        embedding_duration_seconds: Optional duration of embedding generation only
    """
    files_processed: int = Field(..., description="Number of files processed")
    chunks_created: int = Field(..., description="Number of chunks created")
    entities_created: int = Field(..., description="Number of entities created")
    relationships_created: int = Field(..., description="Number of relationships created")
    duration_seconds: Optional[float] = Field(None, description="Total duration including embeddings")
    embedding_duration_seconds: Optional[float] = Field(None, description="Duration of embedding generation")


class IndexingFailedPayload(BaseEventPayload):
    """Payload for indexing.failed event.

    Attributes:
        error: Error message describing the failure
        error_type: Optional type of error (e.g., "ValidationError")
        path: Optional path where error occurred
        files_processed: Optional number of files processed before failure
    """
    error: str = Field(..., description="Error message")
    error_type: Optional[str] = Field(None, description="Type of error")
    path: Optional[str] = Field(None, description="Path where error occurred")
    files_processed: Optional[int] = Field(None, description="Files processed before failure")


class IndexingFileIndexedPayload(BaseEventPayload):
    """Payload for indexing.file.indexed event.

    Attributes:
        file_path: Path to the indexed file
        chunks_created: Number of chunks created from this file
        entities_created: Number of entities created from this file
        duration_ms: Optional duration in milliseconds
    """
    file_path: str = Field(..., description="Path to indexed file")
    chunks_created: int = Field(..., description="Number of chunks created")
    entities_created: int = Field(..., description="Number of entities created")
    duration_ms: Optional[float] = Field(None, description="Duration in milliseconds")


class IndexingFileSkippedPayload(BaseEventPayload):
    """Payload for indexing.file.skipped event.

    Attributes:
        file_path: Path to the skipped file
        reason: Reason for skipping (e.g., "unchanged", "ignored", "unsupported")
    """
    file_path: str = Field(..., description="Path to skipped file")
    reason: str = Field(..., description="Reason for skipping")


class IndexingFileFailedPayload(BaseEventPayload):
    """Payload for indexing.file.failed event.

    Attributes:
        file_path: Path to the failed file
        error: Error message describing the failure
        error_type: Optional type of error
    """
    file_path: str = Field(..., description="Path to failed file")
    error: str = Field(..., description="Error message")
    error_type: Optional[str] = Field(None, description="Type of error")


# ============================================================================
# Search Event Payloads
# ============================================================================

class SearchQueryStartedPayload(BaseEventPayload):
    """Payload for search.query.started event.

    Attributes:
        search_type: Type of search (vector, fts, hybrid, graph)
        query_text: Optional text query
        limit: Maximum number of results
    """
    search_type: Literal["vector", "fts", "hybrid", "graph"] = Field(
        ..., description="Type of search"
    )
    query_text: Optional[str] = Field(None, description="Text query")
    limit: Optional[int] = Field(None, description="Maximum results")


class SearchQueryCompletedPayload(BaseEventPayload):
    """Payload for search.query.completed event.

    Attributes:
        search_type: Type of search performed
        result_count: Number of results returned
        duration_ms: Duration in milliseconds
    """
    search_type: str = Field(..., description="Type of search")
    result_count: int = Field(..., description="Number of results")
    duration_ms: Optional[float] = Field(None, description="Duration in milliseconds")


class SearchQueryFailedPayload(BaseEventPayload):
    """Payload for search.query.failed event.

    Attributes:
        search_type: Type of search that failed
        error: Error message
        error_type: Optional type of error
    """
    search_type: str = Field(..., description="Type of search")
    error: str = Field(..., description="Error message")
    error_type: Optional[str] = Field(None, description="Type of error")


class SearchResultsReturnedPayload(BaseEventPayload):
    """Payload for search.results.returned event.

    Attributes:
        result_count: Number of results returned
        search_type: Type of search performed
    """
    result_count: int = Field(..., description="Number of results")
    search_type: str = Field(..., description="Type of search")


# ============================================================================
# Memory Event Payloads
# ============================================================================

class MemoryStoredPayload(BaseEventPayload):
    """Payload for memory.stored event.

    Attributes:
        memory_id: Unique identifier for the stored memory
        tier: Memory tier (working, episodic, semantic)
        agent_id: Agent identifier
        session_id: Optional session identifier
        importance: Importance score (0.0-1.0)
        content_length: Length of stored content
    """
    memory_id: str = Field(..., description="Memory identifier")
    tier: Literal["working", "episodic", "semantic"] = Field(
        ..., description="Memory tier"
    )
    agent_id: str = Field(..., description="Agent identifier")
    session_id: Optional[str] = Field(None, description="Session identifier")
    importance: float = Field(..., ge=0.0, le=1.0, description="Importance score")
    content_length: int = Field(..., ge=0, description="Content length")


class MemoryRetrievedPayload(BaseEventPayload):
    """Payload for memory.retrieved event.

    Attributes:
        query: Query text used for retrieval
        result_count: Number of memories retrieved
        strategy: Retrieval strategy used
        agent_id: Agent identifier
        session_id: Optional session identifier
    """
    query: str = Field(..., description="Query text")
    result_count: int = Field(..., ge=0, description="Number of results")
    strategy: str = Field(..., description="Retrieval strategy")
    agent_id: str = Field(..., description="Agent identifier")
    session_id: Optional[str] = Field(None, description="Session identifier")


class MemoryConsolidatedPayload(BaseEventPayload):
    """Payload for memory.consolidated event.

    Attributes:
        items_promoted: Number of items promoted to higher tier
        concepts_extracted: Number of concepts extracted
        agent_id: Agent identifier
        session_id: Optional session identifier
        duration_seconds: Optional duration of consolidation
    """
    items_promoted: int = Field(..., ge=0, description="Items promoted")
    concepts_extracted: int = Field(..., ge=0, description="Concepts extracted")
    agent_id: str = Field(..., description="Agent identifier")
    session_id: Optional[str] = Field(None, description="Session identifier")
    duration_seconds: Optional[float] = Field(None, description="Duration in seconds")


# ============================================================================
# Watching Event Payloads
# ============================================================================

class WatchingStartedPayload(BaseEventPayload):
    """Payload for watching.started event.

    Attributes:
        path: Path being watched
        recursive: Whether watching recursively
        ignore_patterns: Optional list of ignore patterns
    """
    path: str = Field(..., description="Path being watched")
    recursive: bool = Field(..., description="Recursive watching")
    ignore_patterns: Optional[list[str]] = Field(None, description="Ignore patterns")


class WatchingStoppedPayload(BaseEventPayload):
    """Payload for watching.stopped event.

    Attributes:
        path: Path that was being watched
        events_processed: Optional number of events processed
    """
    path: str = Field(..., description="Path that was watched")
    events_processed: Optional[int] = Field(None, description="Events processed")


class WatchingFileChangedPayload(BaseEventPayload):
    """Payload for watching.file.changed/created/deleted events.

    Attributes:
        file_path: Path to the changed file
        event_type: Type of change (created, modified, deleted)
        change_hash: Optional hash of file content
    """
    file_path: str = Field(..., description="Path to changed file")
    event_type: Literal["created", "modified", "deleted"] = Field(
        ..., description="Type of change"
    )
    change_hash: Optional[str] = Field(None, description="Content hash")


# ============================================================================
# Parsing Event Payloads
# ============================================================================

class ParsingStartedPayload(BaseEventPayload):
    """Payload for parsing.started event.

    Attributes:
        file_path: Path to file being parsed
        parser_type: Optional type of parser being used
    """
    file_path: str = Field(..., description="Path to file")
    parser_type: Optional[str] = Field(None, description="Parser type")


class ParsingCompletedPayload(BaseEventPayload):
    """Payload for parsing.completed event.

    Attributes:
        file_path: Path to parsed file
        chunks_created: Number of chunks created
        parser_type: Type of parser used
        duration_ms: Optional duration in milliseconds
    """
    file_path: str = Field(..., description="Path to file")
    chunks_created: int = Field(..., description="Number of chunks")
    parser_type: str = Field(..., description="Parser type")
    duration_ms: Optional[float] = Field(None, description="Duration in milliseconds")


class ParsingFailedPayload(BaseEventPayload):
    """Payload for parsing.failed event.

    Attributes:
        file_path: Path to failed file
        error: Error message
        error_type: Optional type of error
        parser_type: Optional type of parser that failed
    """
    file_path: str = Field(..., description="Path to file")
    error: str = Field(..., description="Error message")
    error_type: Optional[str] = Field(None, description="Error type")
    parser_type: Optional[str] = Field(None, description="Parser type")


class ParserSelectedPayload(BaseEventPayload):
    """Payload for parsing.parser.selected event.

    Attributes:
        file_path: Path to file
        parser_type: Type of parser selected
        parser_priority: Parser priority value
    """
    file_path: str = Field(..., description="Path to file")
    parser_type: str = Field(..., description="Parser type")
    parser_priority: int = Field(..., description="Parser priority")


# ============================================================================
# Project Lifecycle Event Payloads
# ============================================================================

class ProjectInitializedPayload(BaseEventPayload):
    """Payload for project.initialized event.

    Attributes:
        project_id: Project identifier
        root_path: Optional root path of project
    """
    project_id: str = Field(..., description="Project identifier")
    root_path: Optional[str] = Field(None, description="Project root path")


class ProjectLoadedPayload(BaseEventPayload):
    """Payload for project.loaded event.

    Attributes:
        project_id: Project identifier
        chunk_count: Optional number of chunks loaded
        entity_count: Optional number of entities loaded
    """
    project_id: str = Field(..., description="Project identifier")
    chunk_count: Optional[int] = Field(None, description="Number of chunks")
    entity_count: Optional[int] = Field(None, description="Number of entities")


class ProjectClosedPayload(BaseEventPayload):
    """Payload for project.closed event.

    Attributes:
        project_id: Project identifier
        reason: Optional reason for closing
    """
    project_id: str = Field(..., description="Project identifier")
    reason: Optional[str] = Field(None, description="Reason for closing")


# ============================================================================
# System Event Payloads
# ============================================================================

class SystemStartedPayload(BaseEventPayload):
    """Payload for system.started event.

    Attributes:
        component: Component that started
        version: Optional version string
    """
    component: str = Field(..., description="Component name")
    version: Optional[str] = Field(None, description="Version string")


class SystemStoppedPayload(BaseEventPayload):
    """Payload for system.stopped event.

    Attributes:
        component: Component that stopped
        reason: Optional reason for stopping
    """
    component: str = Field(..., description="Component name")
    reason: Optional[str] = Field(None, description="Reason for stopping")


class SystemErrorPayload(BaseEventPayload):
    """Payload for system.error event.

    Attributes:
        component: Component where error occurred
        error: Error message
        error_type: Optional type of error
        severity: Error severity (low, medium, high, critical)
    """
    component: str = Field(..., description="Component name")
    error: str = Field(..., description="Error message")
    error_type: Optional[str] = Field(None, description="Error type")
    severity: Literal["low", "medium", "high", "critical"] = Field(
        "medium", description="Error severity"
    )


# ============================================================================
# Type Union for All Payloads
# ============================================================================

EventPayload = Union[
    # Indexing
    IndexingStartedPayload,
    IndexingProgressPayload,
    IndexingCompletedPayload,
    IndexingStoredPayload,
    IndexingReadyPayload,
    IndexingFailedPayload,
    IndexingFileIndexedPayload,
    IndexingFileSkippedPayload,
    IndexingFileFailedPayload,
    # Search
    SearchQueryStartedPayload,
    SearchQueryCompletedPayload,
    SearchQueryFailedPayload,
    SearchResultsReturnedPayload,
    # Memory
    MemoryStoredPayload,
    MemoryRetrievedPayload,
    MemoryConsolidatedPayload,
    # Watching
    WatchingStartedPayload,
    WatchingStoppedPayload,
    WatchingFileChangedPayload,
    # Parsing
    ParsingStartedPayload,
    ParsingCompletedPayload,
    ParsingFailedPayload,
    ParserSelectedPayload,
    # Project
    ProjectInitializedPayload,
    ProjectLoadedPayload,
    ProjectClosedPayload,
    # System
    SystemStartedPayload,
    SystemStoppedPayload,
    SystemErrorPayload,
]
