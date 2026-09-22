"""AlloyDB-specific table schemas with GENERATED ALWAYS AS embedding columns.

AlloyDB's built-in `embedding()` function generates vectors server-side via
Vertex AI's text-embedding-005 model (768 dimensions). This eliminates the
need for local embedding generation entirely.

Key differences from PostgreSQL schemas:
    - embedding columns use GENERATED ALWAYS AS (embedding('text-embedding-005', ...)) STORED
    - Default dimension is 768 (text-embedding-005 output)
    - Uses HNSW indexes (AlloyDB-optimized) instead of IVFFlat
    - Requires google_ml_integration extension alongside vector
"""

from __future__ import annotations

from typing import Dict, List

from agent_vault.storage.providers.postgresql.schemas import (
    SchemaGenerator,
    TableSchema,
    ALL_SCHEMAS as PG_ALL_SCHEMAS,
    CHUNKS_FTS_TABLE,
    EVENTS_TABLE,
    OPERATIONS_TABLE,
    FILE_HASHES_TABLE,
    RELATIONSHIPS_TABLE,
)
from agent_vault.storage.similarity import DEFAULT_SIMILARITY_METRIC


# AlloyDB Chunks table with server-side embedding generation
ALLOYDB_CHUNKS_TABLE = TableSchema(
    name="chunks",
    role="vector",
    create_sql="""
CREATE TABLE IF NOT EXISTS {table_name} (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT,
    language TEXT,
    start_line INTEGER,
    end_line INTEGER,
    embedding vector({embedding_dim}) GENERATED ALWAYS AS (embedding('text-embedding-005', content)) STORED,
    metadata JSONB DEFAULT '{{}}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, file_path, chunk_index)
);
""",
    indexes=[
        "CREATE INDEX IF NOT EXISTS {index_name}_project ON {table_name}(project_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_file ON {table_name}(file_path);",
        "CREATE INDEX IF NOT EXISTS {index_name}_content_type ON {table_name}(content_type);",
        "CREATE INDEX IF NOT EXISTS {index_name}_embedding ON {table_name} USING hnsw (embedding {vector_op_class});",
    ],
)


# AlloyDB Entities table with server-side embedding generation
ALLOYDB_ENTITIES_TABLE = TableSchema(
    name="entities",
    role="graph",
    create_sql="""
CREATE TABLE IF NOT EXISTS {table_name} (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    embedding vector({embedding_dim}) GENERATED ALWAYS AS (embedding('text-embedding-005', qualified_name)) STORED,
    metadata JSONB DEFAULT '{{}}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, qualified_name)
);
""",
    indexes=[
        "CREATE INDEX IF NOT EXISTS {index_name}_project ON {table_name}(project_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_file ON {table_name}(file_path);",
        "CREATE INDEX IF NOT EXISTS {index_name}_name ON {table_name}(name);",
        "CREATE INDEX IF NOT EXISTS {index_name}_qname ON {table_name}(qualified_name);",
        "CREATE INDEX IF NOT EXISTS {index_name}_type ON {table_name}(entity_type);",
        "CREATE INDEX IF NOT EXISTS {index_name}_embedding ON {table_name} USING hnsw (embedding {vector_op_class});",
    ],
)


# AlloyDB schema registry - reuse non-embedding tables from PostgreSQL
ALLOYDB_ALL_SCHEMAS: Dict[str, List[TableSchema]] = {
    "vector": [ALLOYDB_CHUNKS_TABLE, CHUNKS_FTS_TABLE],
    "graph": [ALLOYDB_ENTITIES_TABLE, RELATIONSHIPS_TABLE],
    "events": [EVENTS_TABLE, OPERATIONS_TABLE],
    "file_tracker": [FILE_HASHES_TABLE],
}


class AlloyDBSchemaGenerator(SchemaGenerator):
    """Generates DDL for AlloyDB with GENERATED ALWAYS AS embedding columns.

    Uses text-embedding-005 (768 dims) via Vertex AI and HNSW indexes.

    Example:
        >>> generator = AlloyDBSchemaGenerator(prefix="agv_")
        >>> ddl = generator.get_create_statements("vector")
        >>> for stmt in ddl:
        ...     await conn.execute(stmt)
    """

    def __init__(
        self,
        prefix: str = "agv_",
        embedding_dim: int = 768,
        similarity_metric: str = DEFAULT_SIMILARITY_METRIC,
    ) -> None:
        """Initialize AlloyDB schema generator.

        Args:
            prefix: Table name prefix (default: "agv_")
            embedding_dim: Vector dimension (default: 768 for text-embedding-005)
            similarity_metric: Canonical similarity metric name (default: "cosine").
        """
        super().__init__(
            prefix=prefix,
            embedding_dim=embedding_dim,
            similarity_metric=similarity_metric,
        )

    def get_create_statements(self, role: str) -> List[str]:
        """Get all CREATE statements for a role using AlloyDB schemas."""
        schemas = ALLOYDB_ALL_SCHEMAS.get(role, [])
        statements = []

        for schema in schemas:
            statements.append(self.generate_create_table(schema))
            statements.extend(self.generate_indexes(schema))

        return statements

    def get_all_create_statements(self) -> Dict[str, List[str]]:
        """Get CREATE statements for all roles."""
        return {role: self.get_create_statements(role) for role in ALLOYDB_ALL_SCHEMAS}

    def get_drop_statements(self, role: str) -> List[str]:
        """Get DROP TABLE statements for a role."""
        schemas = ALLOYDB_ALL_SCHEMAS.get(role, [])
        statements = []
        for schema in reversed(schemas):
            table_name = self.get_table_name(schema)
            statements.append(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
        return statements

    def get_extension_statements(self) -> List[str]:
        """Get statements to create required extensions."""
        return [
            "CREATE EXTENSION IF NOT EXISTS vector;",
            "CREATE EXTENSION IF NOT EXISTS google_ml_integration;",
        ]
