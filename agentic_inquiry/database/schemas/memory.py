"""Memory table schemas for Agentic Inquiry.

This module defines the canonical schemas for memory tables:
- memory_episodic_medium: Episodic/working memory (Tier 2)
- memory_semantic_high: Semantic/long-term memory (Tier 3)

See: docs/design/logical-schema-reference.md
"""

from __future__ import annotations

from .base import FieldType, LogicalSchema, SchemaField

# =============================================================================
# Common Memory Fields
# =============================================================================

# These fields are shared between episodic and semantic memory
_COMMON_MEMORY_FIELDS = (
    # Identity
    SchemaField(
        name="id",
        field_type=FieldType.STRING,
        required=True,
        description="Unique identifier for the memory item",
    ),
    # Context
    SchemaField(
        name="agent_id",
        field_type=FieldType.STRING,
        required=False,
        description="Agent that created/owns this memory",
    ),
    SchemaField(
        name="session_id",
        field_type=FieldType.STRING,
        required=False,
        description="Session context",
    ),
    SchemaField(
        name="conversation_id",
        field_type=FieldType.STRING,
        required=False,
        description="Conversation context",
    ),
    SchemaField(
        name="task_id",
        field_type=FieldType.STRING,
        required=False,
        description="Task context",
    ),
    SchemaField(
        name="project_id",
        field_type=FieldType.STRING,
        required=False,
        description="Project scope identifier",
    ),
    # Content
    SchemaField(
        name="content",
        field_type=FieldType.STRING,
        required=False,
        description="Full memory content",
    ),
    SchemaField(
        name="summary",
        field_type=FieldType.STRING,
        required=False,
        description="Summarized version of the content",
    ),
    # Scoring
    SchemaField(
        name="importance",
        field_type=FieldType.FLOAT,
        required=False,
        description="Importance score (0.0 to 1.0)",
    ),
    SchemaField(
        name="tier",
        field_type=FieldType.STRING,
        required=False,
        description="Memory tier (working, episodic, semantic)",
    ),
    # Provenance
    SchemaField(
        name="creator_agent_id",
        field_type=FieldType.STRING,
        required=False,
        description="Agent that originally created this memory",
    ),
    SchemaField(
        name="modifier_agent_id",
        field_type=FieldType.STRING,
        required=False,
        description="Last agent to modify this memory",
    ),
    SchemaField(
        name="content_source",
        field_type=FieldType.STRING,
        required=False,
        description="Source of the content (user, system, inference)",
    ),
    # Timestamps
    SchemaField(
        name="created_at",
        field_type=FieldType.DATETIME,
        required=False,
        description="When the memory was created (ISO 8601)",
    ),
    SchemaField(
        name="accessed_at",
        field_type=FieldType.DATETIME,
        required=False,
        description="When the memory was last accessed (ISO 8601)",
    ),
    SchemaField(
        name="modified_at",
        field_type=FieldType.DATETIME,
        required=False,
        description="When the memory was last modified (ISO 8601)",
    ),
    SchemaField(
        name="access_count",
        field_type=FieldType.INT,
        required=False,
        default=0,
        description="Number of times the memory has been accessed",
    ),
    # Vectors
    SchemaField(
        name="vector",
        field_type=FieldType.VECTOR,
        required=False,
        description="Content embedding vector",
    ),
    SchemaField(
        name="summary_vector",
        field_type=FieldType.VECTOR,
        required=False,
        description="Summary embedding vector",
    ),
    # Event info
    SchemaField(
        name="event_type",
        field_type=FieldType.STRING,
        required=False,
        description="Type of event that created this memory",
    ),
    # Emotional signals
    SchemaField(
        name="emotional_valence",
        field_type=FieldType.FLOAT,
        required=False,
        description="Emotional valence (-1.0 negative to 1.0 positive)",
    ),
    SchemaField(
        name="emotional_arousal",
        field_type=FieldType.FLOAT,
        required=False,
        description="Emotional arousal (0.0 calm to 1.0 intense)",
    ),
    # Semantic triplet
    SchemaField(
        name="subject",
        field_type=FieldType.STRING,
        required=False,
        description="Subject of semantic triplet",
    ),
    SchemaField(
        name="relationship",
        field_type=FieldType.STRING,
        required=False,
        description="Relationship in semantic triplet",
    ),
    SchemaField(
        name="object",
        field_type=FieldType.STRING,
        required=False,
        description="Object of semantic triplet",
    ),
    SchemaField(
        name="confidence",
        field_type=FieldType.FLOAT,
        required=False,
        description="Confidence in the memory (0.0 to 1.0)",
    ),
    # Metadata
    SchemaField(
        name="metadata",
        field_type=FieldType.JSON,
        required=False,
        description="Additional metadata",
    ),
)

# =============================================================================
# Episodic Memory Schema (Tier 2 - Medium Term)
# =============================================================================

MEMORY_EPISODIC_SCHEMA = LogicalSchema(
    name="memory_episodic_medium",
    description="Episodic/working memory for medium-term retention",
    primary_key=("id",),
    fts_columns=("content", "summary"),
    vector_columns=("vector", "summary_vector"),
    fields=_COMMON_MEMORY_FIELDS,
)

# =============================================================================
# Semantic Memory Schema (Tier 3 - Long Term)
# =============================================================================

MEMORY_SEMANTIC_SCHEMA = LogicalSchema(
    name="memory_semantic_high",
    description="Semantic/long-term memory for permanent knowledge",
    primary_key=("id",),
    fts_columns=("content", "summary"),
    vector_columns=("vector", "summary_vector"),
    fields=_COMMON_MEMORY_FIELDS,
)

# =============================================================================
# Schema Registry
# =============================================================================

MEMORY_SCHEMAS = {
    "memory_episodic_medium": MEMORY_EPISODIC_SCHEMA,
    "memory_semantic_high": MEMORY_SEMANTIC_SCHEMA,
}


def get_memory_schema(name: str) -> LogicalSchema:
    """Get a memory schema by name.

    Args:
        name: Schema name

    Returns:
        LogicalSchema instance

    Raises:
        KeyError: If schema not found
    """
    if name not in MEMORY_SCHEMAS:
        raise KeyError(
            f"Unknown memory schema: {name}. Available: {list(MEMORY_SCHEMAS.keys())}"
        )
    return MEMORY_SCHEMAS[name]
