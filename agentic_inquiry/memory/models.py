"""
Data models for the Memory System.

Defines core data structures including MemoryItem, MemoryContext,
and result types for memory operations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import numpy as np
import pyarrow as pa


class MemoryTier(Enum):
    """Memory tier classification."""

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class MemoryStatus(Enum):
    """Status of a memory item."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    NEGATED = "negated"


class Priority(Enum):
    """Priority levels for memory importance."""

    LOW = 0.3
    MEDIUM = 0.6
    HIGH = 0.9
    CRITICAL = 1.0


class ConsolidationStrategy(Enum):
    """Strategy for memory consolidation."""

    IMPORTANCE_BASED = "importance_based"
    FREQUENCY_BASED = "frequency_based"
    RECENCY_BASED = "recency_based"
    ADAPTIVE = "adaptive"


class RecallStrategy(Enum):
    """Strategy for memory retrieval."""

    RELEVANCE = "relevance"
    RECENCY = "recency"
    IMPORTANCE = "importance"
    ADAPTIVE = "adaptive"


@dataclass
class MemoryContext:
    """
    Context information for memory operations.

    Provides agent, session, and conversation scoping for memory isolation.
    """

    agent_id: str
    session_id: str
    conversation_id: str
    task_id: str | None = None
    project_id: str | None = None
    priority: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def context_key(self) -> str:
        """
        Generate unique context key.

        Returns:
            String key in format "agent_id:session_id:conversation_id[:project_id]"
        """
        parts = [self.agent_id, self.session_id, self.conversation_id]
        if self.project_id:
            parts.append(self.project_id)
        return ":".join(parts)

    def with_task(self, task_id: str) -> "MemoryContext":
        """
        Create new context with task_id.

        Args:
            task_id: Task identifier

        Returns:
            New MemoryContext with task_id set
        """
        return MemoryContext(
            agent_id=self.agent_id,
            session_id=self.session_id,
            conversation_id=self.conversation_id,
            task_id=task_id,
            project_id=self.project_id,
            priority=self.priority,
            metadata=self.metadata.copy(),
            created_at=self.created_at,
        )

    def with_project(self, project_id: str) -> "MemoryContext":
        """
        Create new context with project_id.

        Args:
            project_id: Project identifier

        Returns:
            New MemoryContext with project_id set
        """
        return MemoryContext(
            agent_id=self.agent_id,
            session_id=self.session_id,
            conversation_id=self.conversation_id,
            task_id=self.task_id,
            project_id=project_id,
            priority=self.priority,
            metadata=self.metadata.copy(),
            created_at=self.created_at,
        )

    def with_conversation(self, conversation_id: str) -> "MemoryContext":
        """
        Create new context with conversation_id.

        Args:
            conversation_id: Conversation identifier

        Returns:
            New MemoryContext with conversation_id set
        """
        return MemoryContext(
            agent_id=self.agent_id,
            session_id=self.session_id,
            conversation_id=conversation_id,
            task_id=self.task_id,
            project_id=self.project_id,
            priority=self.priority,
            metadata=self.metadata.copy(),
            created_at=self.created_at,
        )


@dataclass
class MemoryItem:
    """
    A single unit of stored memory.

    Supports episodic (event-based) and semantic (fact-based) memory types
    with embeddings for similarity search.
    """

    # Core fields
    id: str
    content: str
    summary: str
    context: MemoryContext
    importance: float
    tier: MemoryTier

    # Attribution fields
    creator_agent_id: str
    modifier_agent_id: str
    content_source: str | None = None

    # Temporal fields
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    accessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    modified_at: datetime | None = None
    access_count: int = 0

    # Embedding fields
    embedding: np.ndarray | None = None
    summary_embedding: np.ndarray | None = None

    # Episodic-specific fields
    event_type: str | None = None
    emotional_valence: float | None = None
    emotional_arousal: float | None = None

    # Semantic-specific fields
    subject: str | None = None
    relationship: str | None = None
    object: str | None = None
    confidence: float | None = None

    # Status fields (for negative truths/updates)
    status: MemoryStatus = MemoryStatus.ACTIVE
    superseded_by: str | None = None

    # Additional metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate field values after initialization."""
        # Validate importance score
        if not 0.0 <= self.importance <= 1.0:
            raise ValueError(
                f"importance must be between 0.0 and 1.0, got {self.importance}"
            )

        # Validate confidence score if present
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )

        # Validate emotional valence if present
        if (
            self.emotional_valence is not None
            and not -1.0 <= self.emotional_valence <= 1.0
        ):
            raise ValueError(
                f"emotional_valence must be between -1.0 and 1.0, got {self.emotional_valence}"
            )

        # Validate emotional arousal if present
        if (
            self.emotional_arousal is not None
            and not 0.0 <= self.emotional_arousal <= 1.0
        ):
            raise ValueError(
                f"emotional_arousal must be between 0.0 and 1.0, got {self.emotional_arousal}"
            )

    def access(self) -> None:
        """Update access statistics."""
        self.accessed_at = datetime.now(timezone.utc)
        self.access_count += 1

    def decay(self, decay_factor: float = 0.95) -> None:
        """
        Apply decay to importance score.

        Args:
            decay_factor: Multiplier for importance (default: 0.95)
        """
        self.importance = max(0.0, self.importance * decay_factor)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization
        """
        return {
            "id": self.id,
            "content": self.content,
            "summary": self.summary,
            "context": {
                "agent_id": self.context.agent_id,
                "session_id": self.context.session_id,
                "conversation_id": self.context.conversation_id,
                "task_id": self.context.task_id,
                "project_id": self.context.project_id,
                "priority": self.context.priority,
                "metadata": self.context.metadata,
                "created_at": self.context.created_at.isoformat(),
            },
            "importance": self.importance,
            "tier": self.tier.value,
            "creator_agent_id": self.creator_agent_id,
            "modifier_agent_id": self.modifier_agent_id,
            "content_source": self.content_source,
            "created_at": self.created_at.isoformat(),
            "accessed_at": self.accessed_at.isoformat(),
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "access_count": self.access_count,
            "embedding": self.embedding.tolist()
            if self.embedding is not None
            else None,
            "summary_embedding": (
                self.summary_embedding.tolist()
                if self.summary_embedding is not None
                else None
            ),
            "event_type": self.event_type,
            "emotional_valence": self.emotional_valence,
            "emotional_arousal": self.emotional_arousal,
            "subject": self.subject,
            "relationship": self.relationship,
            "object": self.object,
            "confidence": self.confidence,
            "status": self.status.value,
            "superseded_by": self.superseded_by,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        """
        Deserialize from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            MemoryItem instance
        """
        # Reconstruct context
        context_data = data["context"]
        context = MemoryContext(
            agent_id=context_data["agent_id"],
            session_id=context_data["session_id"],
            conversation_id=context_data["conversation_id"],
            task_id=context_data.get("task_id"),
            project_id=context_data.get("project_id"),
            priority=context_data.get("priority", 0.5),
            metadata=context_data.get("metadata", {}),
            created_at=datetime.fromisoformat(context_data["created_at"]),
        )

        # Convert embeddings
        embedding = np.array(data["embedding"]) if data.get("embedding") else None
        summary_embedding = (
            np.array(data["summary_embedding"])
            if data.get("summary_embedding")
            else None
        )

        # Parse timestamps
        created_at = datetime.fromisoformat(data["created_at"])
        accessed_at = datetime.fromisoformat(data["accessed_at"])
        modified_at = (
            datetime.fromisoformat(data["modified_at"])
            if data.get("modified_at")
            else None
        )

        return cls(
            id=data["id"],
            content=data["content"],
            summary=data["summary"],
            context=context,
            importance=data["importance"],
            tier=MemoryTier(data["tier"]),
            creator_agent_id=data["creator_agent_id"],
            modifier_agent_id=data["modifier_agent_id"],
            content_source=data.get("content_source"),
            created_at=created_at,
            accessed_at=accessed_at,
            modified_at=modified_at,
            access_count=data.get("access_count", 0),
            embedding=embedding,
            summary_embedding=summary_embedding,
            event_type=data.get("event_type"),
            emotional_valence=data.get("emotional_valence"),
            emotional_arousal=data.get("emotional_arousal"),
            subject=data.get("subject"),
            relationship=data.get("relationship"),
            object=data.get("object"),
            confidence=data.get("confidence"),
            status=MemoryStatus(data.get("status", "active")),
            superseded_by=data.get("superseded_by"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def get_pyarrow_schema(
        cls, embedding_dims: int, summary_embedding_dims: int
    ) -> pa.Schema:
        """
        Get PyArrow schema for LanceDB storage.

        Args:
            embedding_dims: Dimensions for content embedding
            summary_embedding_dims: Dimensions for summary embedding

        Returns:
            PyArrow schema for LanceDB table
        """
        return pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("agent_id", pa.string()),
                pa.field("session_id", pa.string()),
                pa.field("conversation_id", pa.string()),
                pa.field("task_id", pa.string()),
                pa.field("project_id", pa.string()),
                pa.field("content", pa.string()),
                pa.field("summary", pa.string()),
                pa.field("importance", pa.float64()),
                pa.field("tier", pa.string()),
                pa.field("creator_agent_id", pa.string()),
                pa.field("modifier_agent_id", pa.string()),
                pa.field("content_source", pa.string()),
                pa.field("created_at", pa.timestamp("us", tz="UTC")),
                pa.field("accessed_at", pa.timestamp("us", tz="UTC")),
                pa.field("modified_at", pa.timestamp("us", tz="UTC")),
                pa.field("access_count", pa.int64()),
                pa.field("embedding", pa.list_(pa.float32(), embedding_dims)),
                pa.field(
                    "summary_embedding", pa.list_(pa.float32(), summary_embedding_dims)
                ),
                pa.field("event_type", pa.string()),
                pa.field("emotional_valence", pa.float64()),
                pa.field("emotional_arousal", pa.float64()),
                pa.field("subject", pa.string()),
                pa.field("relationship", pa.string()),
                pa.field("object", pa.string()),
                pa.field("confidence", pa.float64()),
                pa.field("status", pa.string()),
                pa.field("superseded_by", pa.string()),
                pa.field("metadata", pa.string()),  # JSON-encoded
            ]
        )


@dataclass
class RetrievalResult:
    """
    Result from memory retrieval operation.

    Contains the retrieved memory item along with relevance scoring
    and metadata about the retrieval.
    """

    item: MemoryItem
    relevance_score: float
    retrieval_tier: MemoryTier
    retrieval_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    type: str | None = (
        None  # Indicates why result was returned (e.g., "exact_match", "similar_to")
    )

    @property
    def confidence(self) -> float:
        """
        Combined confidence score.

        Returns:
            Average of relevance_score and item importance
        """
        return (self.relevance_score + self.item.importance) / 2.0

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization
        """
        return {
            "item": self.item.to_dict(),
            "relevance_score": self.relevance_score,
            "retrieval_tier": self.retrieval_tier.value,
            "retrieval_time": self.retrieval_time.isoformat(),
            "type": self.type,
            "confidence": self.confidence,
        }


@dataclass
class ConsolidationResult:
    """
    Result from memory consolidation operation.

    Tracks statistics about memory promotion and demotion between tiers.
    """

    items_promoted: int
    items_demoted: int
    concepts_extracted: int
    relationships_created: int
    duration_ms: float
    context: MemoryContext


@dataclass
class AgentProfile:
    """
    Profile for an agent's memory preferences and patterns.

    Used by ContextManager for personalization and learning.
    """

    agent_id: str
    query_patterns: dict[str, int] = field(default_factory=dict)
    successful_strategies: dict[str, int] = field(default_factory=dict)
    preference_weights: dict[str, float] = field(
        default_factory=lambda: {"temporal": 0.5, "semantic": 0.5}
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def update_query_pattern(self, pattern: str) -> None:
        """
        Record a query pattern.

        Args:
            pattern: Query pattern identifier
        """
        self.query_patterns[pattern] = self.query_patterns.get(pattern, 0) + 1
        self.updated_at = datetime.now(timezone.utc)

    def update_successful_strategy(self, strategy: str) -> None:
        """
        Record a successful retrieval strategy.

        Args:
            strategy: Strategy identifier
        """
        self.successful_strategies[strategy] = (
            self.successful_strategies.get(strategy, 0) + 1
        )
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "agent_id": self.agent_id,
            "query_patterns": self.query_patterns,
            "successful_strategies": self.successful_strategies,
            "preference_weights": self.preference_weights,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentProfile":
        """
        Deserialize from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            AgentProfile instance
        """
        return cls(
            agent_id=data["agent_id"],
            query_patterns=data.get("query_patterns", {}),
            successful_strategies=data.get("successful_strategies", {}),
            preference_weights=data.get(
                "preference_weights", {"temporal": 0.5, "semantic": 0.5}
            ),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=data.get("metadata", {}),
        )
