"""Canonical logical schema definitions.

This package defines the logical schemas for all database tables.
Schemas specify canonical field names and types that adapters must support.

See: docs/design/logical-schema-reference.md

Usage:
    from agent_vault.database.schemas import (
        DOCUMENT_CHUNKS_SCHEMA,
        GRAPH_ENTITIES_SCHEMA,
        GRAPH_RELATIONSHIPS_SCHEMA,
        MEMORY_EPISODIC_SCHEMA,
        MEMORY_SEMANTIC_SCHEMA,
        get_schema,
    )

    # Get all field names for a schema
    fields = DOCUMENT_CHUNKS_SCHEMA.get_field_names()

    # Validate a row
    errors = DOCUMENT_CHUNKS_SCHEMA.validate_row(row_data)

    # Get a schema by name
    schema = get_schema("document_chunks")
"""
from __future__ import annotations

from typing import Dict

from .base import FieldType, LogicalSchema, SchemaField
from .core import (
    CORE_SCHEMAS,
    DOCUMENT_CHUNKS_SCHEMA,
    GRAPH_ENTITIES_SCHEMA,
    GRAPH_RELATIONSHIPS_SCHEMA,
    get_core_schema,
)
from .memory import (
    MEMORY_EPISODIC_SCHEMA,
    MEMORY_SCHEMAS,
    MEMORY_SEMANTIC_SCHEMA,
    get_memory_schema,
)

__all__ = [
    # Base types
    "FieldType",
    "SchemaField",
    "LogicalSchema",
    # Core schemas
    "DOCUMENT_CHUNKS_SCHEMA",
    "GRAPH_ENTITIES_SCHEMA",
    "GRAPH_RELATIONSHIPS_SCHEMA",
    "CORE_SCHEMAS",
    "get_core_schema",
    # Memory schemas
    "MEMORY_EPISODIC_SCHEMA",
    "MEMORY_SEMANTIC_SCHEMA",
    "MEMORY_SCHEMAS",
    "get_memory_schema",
    # Combined
    "ALL_SCHEMAS",
    "get_schema",
]

# Combined schema registry
ALL_SCHEMAS: Dict[str, LogicalSchema] = {
    **CORE_SCHEMAS,
    **MEMORY_SCHEMAS,
}


def get_schema(name: str) -> LogicalSchema:
    """Get any schema by name.

    Args:
        name: Schema name

    Returns:
        LogicalSchema instance

    Raises:
        KeyError: If schema not found
    """
    if name not in ALL_SCHEMAS:
        raise KeyError(
            f"Unknown schema: {name}. "
            f"Available: {list(ALL_SCHEMAS.keys())}"
        )
    return ALL_SCHEMAS[name]
