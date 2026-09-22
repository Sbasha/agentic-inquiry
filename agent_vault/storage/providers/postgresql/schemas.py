"""PostgreSQL table schemas and DDL generation.

This module defines the database schemas for all PostgreSQL storage providers.
It generates parameterized DDL that respects table prefixes for multi-tenant deployments.

Table naming convention:
    {prefix}v_*  - Vector storage tables (chunks, embeddings)
    {prefix}g_*  - Graph storage tables (entities, relationships)
    {prefix}e_*  - Event storage tables (audit logs)
    {prefix}f_*  - File tracker tables (hash tracking)

Dependencies:
    - pgvector extension for vector similarity search
    - Standard PostgreSQL 12+ for other tables
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, TYPE_CHECKING

from agent_vault.storage.similarity import (
    DEFAULT_SIMILARITY_METRIC,
    pgvector_operator_class,
)

# Import escape_identifier to prevent SQL injection attacks
try:
    from asyncpg.utils import _quote_ident as escape_identifier
except ImportError:
    # Fallback for testing or if asyncpg not available
    def escape_identifier(ident: str) -> str:
        """Simple identifier escaping fallback."""
        # Escape double quotes by doubling them, then wrap in double quotes
        return '"' + ident.replace('"', '""') + '"'


if TYPE_CHECKING:
    from .index_config import IndexConfig


@dataclass
class TableSchema:
    """Schema definition for a PostgreSQL table.

    Attributes:
        name: Base table name (without prefix)
        role: Storage role (vector, graph, events, file_tracker)
        create_sql: DDL template for CREATE TABLE
        indexes: List of index DDL templates
    """

    name: str
    role: str
    create_sql: str
    indexes: List[str]


# Vector Storage Schemas (pgvector)

CHUNKS_TABLE = TableSchema(
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
    embedding vector({embedding_dim}),
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
        "CREATE INDEX IF NOT EXISTS {index_name}_embedding ON {table_name} USING ivfflat (embedding {vector_op_class}) WITH (lists = 100);",
    ],
)


CHUNKS_FTS_TABLE = TableSchema(
    name="chunks_fts",
    role="vector",
    create_sql="""
CREATE TABLE IF NOT EXISTS {table_name} (
    chunk_id TEXT PRIMARY KEY REFERENCES {chunks_table}(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    tsvector_content tsvector NOT NULL
);
""",
    indexes=[
        "CREATE INDEX IF NOT EXISTS {index_name}_project ON {table_name}(project_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_content ON {table_name} USING GIN(tsvector_content);",
    ],
)


CHUNK_EMBEDDINGS_TABLE = TableSchema(
    name="chunk_embeddings",
    role="vector",
    create_sql="""
CREATE TABLE IF NOT EXISTS {table_name} (
    chunk_id TEXT PRIMARY KEY REFERENCES {chunks_table}(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector({embedding_dim})
);
""",
    indexes=[
        "CREATE INDEX IF NOT EXISTS {index_name}_project ON {table_name}(project_id);",
    ],
)


# Graph Storage Schemas

ENTITIES_TABLE = TableSchema(
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
    embedding vector({embedding_dim}),
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
        "CREATE INDEX IF NOT EXISTS {index_name}_project_name ON {table_name}(project_id, name);",
        "CREATE INDEX IF NOT EXISTS {index_name}_embedding ON {table_name} USING ivfflat (embedding {vector_op_class}) WITH (lists = 100);",
    ],
)


ENTITY_EMBEDDINGS_TABLE = TableSchema(
    name="entity_embeddings",
    role="graph",
    create_sql="""
CREATE TABLE IF NOT EXISTS {table_name} (
    entity_id TEXT PRIMARY KEY REFERENCES {entities_table}(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector({embedding_dim})
);
""",
    indexes=[
        "CREATE INDEX IF NOT EXISTS {index_name}_project ON {table_name}(project_id);",
    ],
)


RELATIONSHIPS_TABLE = TableSchema(
    name="relationships",
    role="graph",
    create_sql="""
CREATE TABLE IF NOT EXISTS {table_name} (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    weight FLOAT DEFAULT 1.0,
    metadata JSONB DEFAULT '{{}}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, source_id, target_id, relationship_type)
);
""",
    indexes=[
        "CREATE INDEX IF NOT EXISTS {index_name}_project ON {table_name}(project_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_file ON {table_name}(file_path);",
        "CREATE INDEX IF NOT EXISTS {index_name}_source ON {table_name}(source_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_target ON {table_name}(target_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_type ON {table_name}(relationship_type);",
        "CREATE INDEX IF NOT EXISTS {index_name}_project_source ON {table_name}(project_id, source_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_project_target ON {table_name}(project_id, target_id);",
    ],
)


# Event Storage Schemas

EVENTS_TABLE = TableSchema(
    name="events",
    role="events",
    create_sql="""
CREATE TABLE IF NOT EXISTS {table_name} (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT DEFAULT 'info',
    message TEXT,
    details JSONB DEFAULT '{{}}',
    file_path TEXT,
    entity_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
""",
    indexes=[
        "CREATE INDEX IF NOT EXISTS {index_name}_project ON {table_name}(project_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_operation ON {table_name}(operation_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_type ON {table_name}(event_type);",
        "CREATE INDEX IF NOT EXISTS {index_name}_severity ON {table_name}(severity);",
        "CREATE INDEX IF NOT EXISTS {index_name}_created ON {table_name}(created_at);",
        "CREATE INDEX IF NOT EXISTS {index_name}_file ON {table_name}(file_path) WHERE file_path IS NOT NULL;",
    ],
)


OPERATIONS_TABLE = TableSchema(
    name="operations",
    role="events",
    create_sql="""
CREATE TABLE IF NOT EXISTS {table_name} (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB DEFAULT '{{}}'
);
""",
    indexes=[
        "CREATE INDEX IF NOT EXISTS {index_name}_project ON {table_name}(project_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_type ON {table_name}(operation_type);",
        "CREATE INDEX IF NOT EXISTS {index_name}_status ON {table_name}(status);",
        "CREATE INDEX IF NOT EXISTS {index_name}_started ON {table_name}(started_at);",
    ],
)


# File Tracker Schemas

FILE_HASHES_TABLE = TableSchema(
    name="file_hashes",
    role="file_tracker",
    create_sql="""
CREATE TABLE IF NOT EXISTS {table_name} (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size BIGINT,
    modified_at TIMESTAMPTZ,
    indexed_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{{}}',
    UNIQUE(project_id, file_path)
);
""",
    indexes=[
        "CREATE INDEX IF NOT EXISTS {index_name}_project ON {table_name}(project_id);",
        "CREATE INDEX IF NOT EXISTS {index_name}_file ON {table_name}(file_path);",
        "CREATE INDEX IF NOT EXISTS {index_name}_hash ON {table_name}(content_hash);",
        "CREATE INDEX IF NOT EXISTS {index_name}_indexed ON {table_name}(indexed_at);",
    ],
)


# Schema registry
ALL_SCHEMAS: Dict[str, List[TableSchema]] = {
    "vector": [CHUNKS_TABLE, CHUNKS_FTS_TABLE, CHUNK_EMBEDDINGS_TABLE],
    "graph": [ENTITIES_TABLE, ENTITY_EMBEDDINGS_TABLE, RELATIONSHIPS_TABLE],
    "events": [EVENTS_TABLE, OPERATIONS_TABLE],
    "file_tracker": [FILE_HASHES_TABLE],
}


class SchemaGenerator:
    """Generates DDL statements for PostgreSQL tables.

    This class takes a table prefix and embedding dimension and generates
    the appropriate DDL for creating tables and indexes.

    Example:
        >>> generator = SchemaGenerator(prefix="myapp_", embedding_dim=384)
        >>> ddl = generator.get_create_statements("vector")
        >>> for stmt in ddl:
        ...     await conn.execute(stmt)
    """

    def __init__(
        self,
        prefix: str = "agv_",
        embedding_dim: int = 384,
        similarity_metric: str = DEFAULT_SIMILARITY_METRIC,
    ) -> None:
        """Initialize schema generator.

        Args:
            prefix: Table name prefix (default: "agv_")
            embedding_dim: Vector embedding dimension (default: 384)
            similarity_metric: Canonical similarity metric name (default: "cosine").
                Translated to the appropriate pgvector operator class at DDL time.
        """
        self.prefix = prefix
        self.embedding_dim = embedding_dim
        self.similarity_metric = similarity_metric
        # Resolve once so invalid metric values fail during __init__, not later
        # when generating indexes.
        self._vector_op_class = pgvector_operator_class(similarity_metric)

    def generate_vector_index(
        self,
        table_name: str,
        column_name: str = "embedding",
        index_config: Optional["IndexConfig"] = None,
        row_count: Optional[int] = None,
    ) -> str:
        """Generate CREATE INDEX statement based on configuration.

        This method implements FR-1.1, FR-1.3 by supporting HNSW, ivfflat, and no index.
        All identifiers are escaped using asyncpg's escape_identifier() to prevent
        SQL injection attacks from user-supplied names (AC-1).

        Args:
            table_name: Name of the table (will be escaped)
            column_name: Name of the vector column (will be escaped, default: "embedding")
            index_config: Index configuration with type and parameters
            row_count: Current row count for dynamic lists calculation (ivfflat only)

        Returns:
            CREATE INDEX SQL statement, or empty string if index_type is NONE

        Raises:
            ConfigurationError: If index configuration is invalid

        Example:
            >>> generator = SchemaGenerator(prefix="test_")
            >>> from .index_config import IndexConfig, IndexType, HNSWParams
            >>> config = IndexConfig(index_type=IndexType.HNSW)
            >>> sql = generator.generate_vector_index(
            ...     "test_v_chunks", "embedding", config
            ... )
            >>> # Returns: CREATE INDEX IF NOT EXISTS "idx_test_v_chunks_embedding" ...
        """
        # Import here to avoid circular dependency
        from .index_config import IndexType, IndexConfigStrategy

        # Use default HNSW config if not provided (FR-1.3: HNSW as default)
        if index_config is None:
            from .index_config import IndexConfig

            index_config = IndexConfig()

        # Escape all identifiers to prevent SQL injection
        safe_table = escape_identifier(table_name)
        safe_column = escape_identifier(column_name)
        index_name = f"{table_name}_{column_name}_idx"
        safe_index = escape_identifier(index_name)

        # Handle no index case
        if index_config.index_type == IndexType.NONE:
            return ""  # No index to create

        # Generate HNSW index (AC-1: HNSW index selection)
        if index_config.index_type == IndexType.HNSW:
            params = index_config.hnsw_params
            if params is None:
                from .index_config import HNSWParams

                params = HNSWParams()

            return (
                f"CREATE INDEX IF NOT EXISTS {safe_index} ON {safe_table} "
                f"USING hnsw ({safe_column} {self._vector_op_class}) "
                f"{params.to_sql_options()}"
            )

        # Generate ivfflat index (AC-2: ivfflat lists calculation)
        if index_config.index_type == IndexType.IVFFLAT:
            lists = IndexConfigStrategy.resolve_ivfflat_lists(index_config, row_count)
            return (
                f"CREATE INDEX IF NOT EXISTS {safe_index} ON {safe_table} "
                f"USING ivfflat ({safe_column} {self._vector_op_class}) "
                f"WITH (lists = {lists})"
            )

        # Unknown index type
        from .index_config import ConfigurationError

        raise ConfigurationError(f"Unknown index type: {index_config.index_type}")

    def add_column_if_not_exists(
        self,
        table_name: str,
        column_name: str,
        column_type: str,
        nullable: bool = True,
        default: Optional[str] = None,
    ) -> str:
        """Generate ALTER TABLE statement for adding a column if it doesn't exist.

        This method implements FR-3.3 for additive schema changes without breaking
        existing deployments. Only nullable columns are supported to ensure backward
        compatibility.

        All identifiers are escaped using asyncpg's escape_identifier() to prevent
        SQL injection attacks from user-supplied names.

        Args:
            table_name: Name of the table (will be escaped)
            column_name: Name of the column to add (will be escaped)
            column_type: PostgreSQL column type (e.g., "TEXT", "INTEGER", "JSONB")
            nullable: Whether column should be nullable (default: True, required for additive changes)
            default: Optional default value expression (as string)

        Returns:
            ALTER TABLE SQL statement

        Raises:
            ConfigurationError: If attempting to add non-nullable column

        Example:
            >>> generator = SchemaGenerator(prefix="test_")
            >>> sql = generator.add_column_if_not_exists(
            ...     "test_v_chunks", "new_field", "TEXT", nullable=True
            ... )
            >>> # Returns: ALTER TABLE "test_v_chunks" ADD COLUMN IF NOT EXISTS ...
        """
        from .index_config import ConfigurationError

        # Only support nullable columns for additive changes
        if not nullable:
            raise ConfigurationError(
                "Additive schema changes only support nullable columns. "
                "Non-nullable columns require explicit migration."
            )

        # Escape identifiers to prevent SQL injection
        safe_table = escape_identifier(table_name)
        safe_column = escape_identifier(column_name)

        # Build ALTER TABLE statement
        sql = (
            f"ALTER TABLE {safe_table} "
            f"ADD COLUMN IF NOT EXISTS {safe_column} {column_type}"
        )

        if default is not None:
            sql += f" DEFAULT {default}"

        return sql

    def _get_role_prefix(self, role: str) -> str:
        """Get role-specific table prefix."""
        role_prefixes = {
            "vector": "v_",
            "graph": "g_",
            "events": "e_",
            "file_tracker": "f_",
        }
        return role_prefixes.get(role, "")

    def get_table_name(self, schema: TableSchema) -> str:
        """Get full table name with prefix."""
        role_prefix = self._get_role_prefix(schema.role)
        return f"{self.prefix}{role_prefix}{schema.name}"

    def get_index_name(self, schema: TableSchema) -> str:
        """Get base index name for a schema."""
        role_prefix = self._get_role_prefix(schema.role)
        return f"idx_{self.prefix}{role_prefix}{schema.name}"

    def generate_create_table(self, schema: TableSchema) -> str:
        """Generate CREATE TABLE statement.

        Args:
            schema: Table schema definition

        Returns:
            DDL statement for creating the table
        """
        table_name = self.get_table_name(schema)

        # Build template context
        context = {
            "table_name": table_name,
            "embedding_dim": self.embedding_dim,
        }

        # Handle FTS and embeddings table references to parent tables
        if schema.name in ("chunks_fts", "chunk_embeddings"):
            context["chunks_table"] = self.get_table_name(CHUNKS_TABLE)
        if schema.name == "entity_embeddings":
            context["entities_table"] = self.get_table_name(ENTITIES_TABLE)

        return schema.create_sql.format(**context).strip()

    def generate_indexes(self, schema: TableSchema) -> List[str]:
        """Generate CREATE INDEX statements.

        Args:
            schema: Table schema definition

        Returns:
            List of DDL statements for creating indexes
        """
        table_name = self.get_table_name(schema)
        index_name = self.get_index_name(schema)

        context = {
            "table_name": table_name,
            "index_name": index_name,
            "vector_op_class": self._vector_op_class,
        }

        return [idx.format(**context).strip() for idx in schema.indexes]

    def get_create_statements(self, role: str) -> List[str]:
        """Get all CREATE statements for a role.

        Args:
            role: Storage role (vector, graph, events, file_tracker)

        Returns:
            List of DDL statements (tables and indexes)
        """
        schemas = ALL_SCHEMAS.get(role, [])
        statements = []

        for schema in schemas:
            statements.append(self.generate_create_table(schema))
            statements.extend(self.generate_indexes(schema))

        return statements

    def get_all_create_statements(self) -> Dict[str, List[str]]:
        """Get CREATE statements for all roles.

        Returns:
            Dict mapping role to list of DDL statements
        """
        return {role: self.get_create_statements(role) for role in ALL_SCHEMAS}

    def get_drop_statements(self, role: str) -> List[str]:
        """Get DROP TABLE statements for a role.

        Args:
            role: Storage role

        Returns:
            List of DROP TABLE statements
        """
        schemas = ALL_SCHEMAS.get(role, [])
        statements = []

        # Drop in reverse order to handle foreign keys
        for schema in reversed(schemas):
            table_name = self.get_table_name(schema)
            statements.append(f"DROP TABLE IF EXISTS {table_name} CASCADE;")

        return statements

    def get_extension_statements(self) -> List[str]:
        """Get statements to create required extensions.

        Returns:
            List of CREATE EXTENSION statements
        """
        return [
            "CREATE EXTENSION IF NOT EXISTS vector;",
        ]


# Convenience functions


def get_vector_schemas(
    prefix: str = "agv_",
    embedding_dim: int = 384,
    similarity_metric: str = DEFAULT_SIMILARITY_METRIC,
) -> List[str]:
    """Get DDL for vector storage tables."""
    gen = SchemaGenerator(prefix, embedding_dim, similarity_metric)
    return gen.get_create_statements("vector")


def get_graph_schemas(
    prefix: str = "agv_",
    embedding_dim: int = 384,
    similarity_metric: str = DEFAULT_SIMILARITY_METRIC,
) -> List[str]:
    """Get DDL for graph storage tables."""
    gen = SchemaGenerator(prefix, embedding_dim, similarity_metric)
    return gen.get_create_statements("graph")


def get_events_schemas(prefix: str = "agv_") -> List[str]:
    """Get DDL for event storage tables."""
    gen = SchemaGenerator(prefix)
    return gen.get_create_statements("events")


def get_file_tracker_schemas(prefix: str = "agv_") -> List[str]:
    """Get DDL for file tracker tables."""
    gen = SchemaGenerator(prefix)
    return gen.get_create_statements("file_tracker")
