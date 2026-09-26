"""Core table schemas for Agentic Inquiry.

This module defines the canonical schemas for the primary tables:
- document_chunks: Indexed document content
- graph_entities: Knowledge graph nodes
- graph_relationships: Knowledge graph edges

See: docs/design/logical-schema-reference.md
"""

from __future__ import annotations

from .base import FieldType, LogicalSchema, SchemaField

# =============================================================================
# Document Chunks Schema
# =============================================================================

DOCUMENT_CHUNKS_SCHEMA = LogicalSchema(
    name="document_chunks",
    description="Atomic units of searchable content from parsed documents",
    primary_key=("id",),
    fts_columns=("fts_text",),
    vector_columns=("vector",),
    fields=(
        # Identity and ownership
        SchemaField(
            name="id",
            field_type=FieldType.STRING,
            required=True,
            description="Unique identifier for the chunk",
        ),
        SchemaField(
            name="doc_id",
            field_type=FieldType.STRING,
            required=True,
            description="Parent document identifier",
        ),
        SchemaField(
            name="file_path",
            field_type=FieldType.STRING,
            required=True,
            description="Source file path",
        ),
        SchemaField(
            name="project_id",
            field_type=FieldType.STRING,
            required=True,
            description="Project scope identifier",
        ),
        # Content
        SchemaField(
            name="content",
            field_type=FieldType.STRING,
            required=True,
            description="Raw content of the chunk",
        ),
        SchemaField(
            name="fts_text",
            field_type=FieldType.STRING,
            required=True,
            fts_source=True,
            description="Text prepared for full-text search indexing",
        ),
        SchemaField(
            name="vector",
            field_type=FieldType.VECTOR,
            required=True,
            description="Embedding vector (dimensions from config)",
        ),
        # Type and language
        SchemaField(
            name="content_type",
            field_type=FieldType.STRING,
            required=True,
            description="Content type: CODE, PROSE, TABLE, HEADING, etc.",
        ),
        SchemaField(
            name="language",
            field_type=FieldType.STRING,
            required=False,
            default="",
            sentinel="",
            description="Programming language or document language",
        ),
        # Location
        SchemaField(
            name="page_number",
            field_type=FieldType.INT,
            required=False,
            default=-1,
            sentinel=-1,
            description="Page number for paginated documents",
        ),
        SchemaField(
            name="line_start",
            field_type=FieldType.INT,
            required=False,
            default=-1,
            sentinel=-1,
            description="Starting line number in source file",
        ),
        SchemaField(
            name="line_end",
            field_type=FieldType.INT,
            required=False,
            default=-1,
            sentinel=-1,
            description="Ending line number in source file",
        ),
        # Chunking info
        SchemaField(
            name="chunk_index",
            field_type=FieldType.INT,
            required=False,
            default=0,
            description="Index of this chunk within the document",
        ),
        SchemaField(
            name="total_chunks",
            field_type=FieldType.INT,
            required=False,
            default=1,
            description="Total number of chunks in the document",
        ),
        # Structure
        SchemaField(
            name="element_type",
            field_type=FieldType.STRING,
            required=False,
            default="",
            sentinel="",
            description="Structural element type (function, class, section, etc.)",
        ),
        SchemaField(
            name="element_name",
            field_type=FieldType.STRING,
            required=False,
            default="",
            sentinel="",
            description="Name of the structural element",
        ),
        SchemaField(
            name="parent_id",
            field_type=FieldType.STRING,
            required=False,
            default="",
            sentinel="",
            description="Parent chunk ID for hierarchical documents",
        ),
        SchemaField(
            name="child_ids",
            field_type=FieldType.STRING_LIST,
            required=False,
            description="Child chunk IDs for hierarchical documents",
        ),
        SchemaField(
            name="symbols",
            field_type=FieldType.STRING_LIST,
            required=False,
            description="Symbols extracted from this chunk",
        ),
        # Timestamps
        SchemaField(
            name="indexed_at",
            field_type=FieldType.DATETIME,
            required=False,
            description="When the chunk was indexed (ISO 8601)",
        ),
        SchemaField(
            name="source_modified_at",
            field_type=FieldType.DATETIME,
            required=False,
            description="Source file modification time (ISO 8601)",
        ),
        # Metadata
        SchemaField(
            name="metadata",
            field_type=FieldType.JSON,
            required=False,
            description="Additional metadata (flat dict, no nested structures)",
        ),
        SchemaField(
            name="ranking_signals",
            field_type=FieldType.JSON,
            required=False,
            description="Signals for search ranking (pagerank, etc.)",
        ),
    ),
)

# =============================================================================
# Graph Entities Schema
# =============================================================================

GRAPH_ENTITIES_SCHEMA = LogicalSchema(
    name="graph_entities",
    description="Nodes in the knowledge graph",
    primary_key=("id",),
    fts_columns=("name",),
    vector_columns=("vector",),
    fields=(
        # Identity
        SchemaField(
            name="id",
            field_type=FieldType.STRING,
            required=True,
            description="Unique identifier for the entity",
        ),
        SchemaField(
            name="name",
            field_type=FieldType.STRING,
            required=True,
            description="Human-readable entity name",
        ),
        SchemaField(
            name="type",
            field_type=FieldType.STRING,
            required=True,
            description="Entity type (function, class, method, doc_section, etc.)",
        ),
        SchemaField(
            name="domain",
            field_type=FieldType.STRING,
            required=False,
            default="code",
            description="Entity domain (code, ontology, taxonomy, documentation)",
        ),
        # Location
        SchemaField(
            name="file_path",
            field_type=FieldType.STRING,
            required=True,
            description="Source file path",
        ),
        SchemaField(
            name="doc_id",
            field_type=FieldType.STRING,
            required=True,
            description="Parent document identifier",
        ),
        SchemaField(
            name="project_id",
            field_type=FieldType.STRING,
            required=True,
            description="Project scope identifier",
        ),
        # Vector
        SchemaField(
            name="vector",
            field_type=FieldType.VECTOR,
            required=True,
            description="Embedding vector (dimensions from config)",
        ),
        # Line numbers
        SchemaField(
            name="line_start",
            field_type=FieldType.INT,
            required=False,
            default=-1,
            sentinel=-1,
            description="Starting line number",
        ),
        SchemaField(
            name="line_end",
            field_type=FieldType.INT,
            required=False,
            default=-1,
            sentinel=-1,
            description="Ending line number",
        ),
        # Ranking signals (note: pagerank not page_rank)
        SchemaField(
            name="pagerank",
            field_type=FieldType.FLOAT,
            required=False,
            description="PageRank score for importance",
        ),
        SchemaField(
            name="betweenness",
            field_type=FieldType.FLOAT,
            required=False,
            description="Betweenness centrality score",
        ),
        SchemaField(
            name="community_id",
            field_type=FieldType.STRING,
            required=False,
            description="Community/cluster identifier",
        ),
        SchemaField(
            name="has_ranking_signals",
            field_type=FieldType.BOOL,
            required=True,
            default=False,
            description="Whether ranking signals have been computed",
        ),
    ),
)

# =============================================================================
# Graph Relationships Schema
# =============================================================================

GRAPH_RELATIONSHIPS_SCHEMA = LogicalSchema(
    name="graph_relationships",
    description="Directed edges in the knowledge graph",
    primary_key=("id",),
    fts_columns=(),
    vector_columns=("vector",),
    fields=(
        # Identity
        SchemaField(
            name="id",
            field_type=FieldType.STRING,
            required=True,
            description="Unique identifier for the relationship",
        ),
        # Edge endpoints (note: source_id/target_id, not source_entity_id)
        SchemaField(
            name="source_id",
            field_type=FieldType.STRING,
            required=True,
            description="Source entity ID",
        ),
        SchemaField(
            name="target_id",
            field_type=FieldType.STRING,
            required=True,
            description="Target entity ID",
        ),
        # Type and scope
        SchemaField(
            name="type",
            field_type=FieldType.STRING,
            required=True,
            description="Relationship type (calls, imports, inherits, etc.)",
        ),
        SchemaField(
            name="project_id",
            field_type=FieldType.STRING,
            required=True,
            description="Project scope identifier",
        ),
        # Vector
        SchemaField(
            name="vector",
            field_type=FieldType.VECTOR,
            required=True,
            description="Embedding vector (dimensions from config)",
        ),
        # Metadata
        SchemaField(
            name="metadata",
            field_type=FieldType.JSON,
            required=False,
            description="Type-specific relationship metadata",
        ),
    ),
)

# =============================================================================
# Schema Registry
# =============================================================================

CORE_SCHEMAS = {
    "document_chunks": DOCUMENT_CHUNKS_SCHEMA,
    "graph_entities": GRAPH_ENTITIES_SCHEMA,
    "graph_relationships": GRAPH_RELATIONSHIPS_SCHEMA,
}


def get_core_schema(name: str) -> LogicalSchema:
    """Get a core schema by name.

    Args:
        name: Schema name

    Returns:
        LogicalSchema instance

    Raises:
        KeyError: If schema not found
    """
    if name not in CORE_SCHEMAS:
        raise KeyError(
            f"Unknown core schema: {name}. Available: {list(CORE_SCHEMAS.keys())}"
        )
    return CORE_SCHEMAS[name]
