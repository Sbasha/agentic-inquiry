"""LanceDB-specific schema configuration and PyArrow schemas.

This module provides:
- Table configuration (vector columns, FTS columns)
- Required field definitions per table
- Forbidden field aliases for validation
- PyArrow schema generation functions for LanceDB tables

These definitions are LanceDB-specific and used by LanceDBManager for
table creation and validation. Generic logical schemas are defined
separately in the `schemas/` package.

Design reference: S2-004 in .sessions/deep-architecture-review/010-tasks.md
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

# =============================================================================
# LanceDB Table Configuration
# =============================================================================

TABLE_CONFIGS: Dict[str, Dict[str, Sequence[str]]] = {
    "document_chunks": {
        "vector_columns": ("vector",),
        "fts_columns": ("fts_text",),
    },
    "graph_entities": {
        "vector_columns": ("vector",),
        "fts_columns": ("name",),
    },
    "graph_relationships": {
        "vector_columns": ("vector",),
        "fts_columns": ("type",),
    },
}

# Required fields per table - used for validation at write time
# These are the canonical field names as defined in the PyArrow schemas
REQUIRED_FIELDS: Dict[str, tuple[str, ...]] = {
    "document_chunks": ("id", "doc_id", "file_path", "project_id", "content", "content_type"),
    "graph_entities": ("id", "name", "type", "file_path", "project_id"),
    "graph_relationships": ("id", "source_id", "target_id", "type", "project_id"),
}

# Field name aliases that should NOT be used (they mask the correct schema field)
# These are common mistakes that the validation should catch
FORBIDDEN_FIELD_ALIASES: Dict[str, str] = {
    "entity_id": "id",  # Use 'id' instead
    "chunk_id": "id",   # Use 'id' instead
    "relationship_type": "type",  # Use 'type' instead
    "entity_type": "type",  # Use 'type' for entities, NOT 'entity_type'
}


# =============================================================================
# PyArrow Schema Functions
# =============================================================================

try:
    import pyarrow as pa
except ImportError:
    pa = None  # type: ignore[assignment]


def get_document_chunks_schema(vector_dims: int = 128) -> Optional[Any]:
    """Get the PyArrow schema for document_chunks table.

    Args:
        vector_dims: Dimensionality of the vector embeddings

    Returns:
        PyArrow schema or None if pyarrow is not available
    """
    if pa is None:
        return None

    return pa.schema([
        pa.field("id", pa.string(), nullable=False),
        pa.field("doc_id", pa.string(), nullable=False),
        pa.field("file_path", pa.string(), nullable=False),
        pa.field("project_id", pa.string(), nullable=False),
        pa.field("content", pa.string(), nullable=False),
        pa.field("fts_text", pa.string(), nullable=False),
        pa.field("vector", pa.list_(pa.float32(), vector_dims), nullable=False),
        pa.field("content_type", pa.string(), nullable=False),
        pa.field("language", pa.string(), nullable=False),
        pa.field("page_number", pa.int32(), nullable=False),
        pa.field("line_start", pa.int32(), nullable=False),
        pa.field("line_end", pa.int32(), nullable=False),
        pa.field("chunk_index", pa.int32(), nullable=False),
        pa.field("total_chunks", pa.int32(), nullable=False),
        pa.field("element_type", pa.string(), nullable=False),
        pa.field("element_name", pa.string(), nullable=False),
        pa.field("parent_id", pa.string(), nullable=False),
        pa.field("child_ids", pa.list_(pa.string()), nullable=False),
        pa.field("symbols", pa.list_(pa.string()), nullable=False),
        pa.field("indexed_at", pa.string(), nullable=False),  # ISO format datetime
        pa.field("source_modified_at", pa.string(), nullable=False),  # ISO format datetime
        pa.field("metadata", pa.struct([
            pa.field("data", pa.string()),
            pa.field("symbol_metadata", pa.string()),
            pa.field("symbol_rankings", pa.string()),
        ]), nullable=False),
        pa.field("ranking_signals", pa.struct([
            pa.field("data", pa.string()),
        ]), nullable=False),
    ])


def get_graph_entities_schema(vector_dims: int = 128) -> Optional[Any]:
    """Get the PyArrow schema for graph_entities table.

    Args:
        vector_dims: Dimensionality of the vector embeddings

    Returns:
        PyArrow schema or None if pyarrow is not available
    """
    if pa is None:
        return None

    return pa.schema([
        pa.field("id", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("type", pa.string(), nullable=False),
        pa.field("domain", pa.string(), nullable=False),  # Entity domain (code, ontology, taxonomy, documentation)
        pa.field("file_path", pa.string(), nullable=False),
        pa.field("doc_id", pa.string(), nullable=False),
        pa.field("project_id", pa.string(), nullable=False),
        pa.field("vector", pa.list_(pa.float32(), vector_dims), nullable=False),
        pa.field("line_start", pa.int32(), nullable=False),
        pa.field("line_end", pa.int32(), nullable=False),
        pa.field("pagerank", pa.float32(), nullable=True),
        pa.field("betweenness", pa.float32(), nullable=True),
        pa.field("community_id", pa.string(), nullable=True),
        pa.field("has_ranking_signals", pa.bool_(), nullable=False),
    ])


def get_graph_relationships_schema(vector_dims: int = 128) -> Optional[Any]:
    """Get the PyArrow schema for graph_relationships table.

    Args:
        vector_dims: Dimensionality of the vector embeddings

    Returns:
        PyArrow schema or None if pyarrow is not available
    """
    if pa is None:
        return None

    return pa.schema([
        pa.field("id", pa.string(), nullable=False),
        pa.field("source_id", pa.string(), nullable=False),
        pa.field("target_id", pa.string(), nullable=False),
        pa.field("type", pa.string(), nullable=False),
        pa.field("project_id", pa.string(), nullable=False),
        pa.field("vector", pa.list_(pa.float32(), vector_dims), nullable=False),
        pa.field("metadata", pa.string(), nullable=True),
    ])


def get_memory_episodic_schema(
    content_vector_dims: int = 384,
    summary_vector_dims: int = 128,
) -> Optional[Any]:
    """Get the PyArrow schema for memory_episodic_medium table.

    Args:
        content_vector_dims: Dimensionality of content embeddings (MEDIUM = 384)
        summary_vector_dims: Dimensionality of summary embeddings (LOW = 128)

    Returns:
        PyArrow schema or None if pyarrow is not available
    """
    if pa is None:
        return None

    return pa.schema([
        pa.field("id", pa.string(), nullable=False),
        pa.field("agent_id", pa.string(), nullable=False),
        pa.field("session_id", pa.string(), nullable=False),
        pa.field("conversation_id", pa.string(), nullable=False),
        pa.field("task_id", pa.string(), nullable=True),
        pa.field("project_id", pa.string(), nullable=True),
        pa.field("content", pa.string(), nullable=False),
        pa.field("summary", pa.string(), nullable=False),
        pa.field("importance", pa.float64(), nullable=False),
        pa.field("tier", pa.string(), nullable=False),
        pa.field("creator_agent_id", pa.string(), nullable=False),
        pa.field("modifier_agent_id", pa.string(), nullable=False),
        pa.field("content_source", pa.string(), nullable=True),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("accessed_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("modified_at", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("access_count", pa.int64(), nullable=False),
        pa.field("vector", pa.list_(pa.float32(), content_vector_dims), nullable=False),
        pa.field("summary_vector", pa.list_(pa.float32(), summary_vector_dims), nullable=False),
        pa.field("event_type", pa.string(), nullable=True),
        pa.field("emotional_valence", pa.float64(), nullable=True),
        pa.field("emotional_arousal", pa.float64(), nullable=True),
        pa.field("subject", pa.string(), nullable=True),
        pa.field("relationship", pa.string(), nullable=True),
        pa.field("object", pa.string(), nullable=True),
        pa.field("confidence", pa.float64(), nullable=True),
        pa.field("metadata", pa.string(), nullable=True),
    ])
