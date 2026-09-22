"""Database helpers and transactional utilities.

The database module provides:
- LanceDBManager: Main facade for database operations
- ConnectionManager: Handles connection lifecycle
- TableManager: Handles table operations and caching
- Transaction: Transactional wrapper for database operations

Design reference: DES-S3-001 in .sessions/deep-architecture-review/009-design.md
"""

from .adapters.lancedb_adapter import LanceDBAdapter
from .connection import ConnectionManager
from .filters import FilterBuilder
from .lancedb_manager import LanceDBManager, SyncLanceDBManager
from .lancedb_schemas import (
    FORBIDDEN_FIELD_ALIASES,
    REQUIRED_FIELDS,
    TABLE_CONFIGS,
    get_document_chunks_schema,
    get_graph_entities_schema,
    get_graph_relationships_schema,
    get_memory_episodic_schema,
)
from .protocols import IndexingDatabaseProtocol, has_indexing_support
from .tables import TableManager
from .transaction import Transaction

__all__ = [
    # Adapters
    "LanceDBAdapter",
    # Connection management
    "ConnectionManager",
    # Filters
    "FilterBuilder",
    # LanceDB schemas
    "FORBIDDEN_FIELD_ALIASES",
    "REQUIRED_FIELDS",
    "TABLE_CONFIGS",
    "get_document_chunks_schema",
    "get_graph_entities_schema",
    "get_graph_relationships_schema",
    "get_memory_episodic_schema",
    # Managers
    "LanceDBManager",
    "SyncLanceDBManager",
    # Protocols
    "IndexingDatabaseProtocol",
    "has_indexing_support",
    # Table management
    "TableManager",
    # Transaction
    "Transaction",
]
