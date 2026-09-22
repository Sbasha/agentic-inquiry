"""PostgreSQL memory storage adapter.

This adapter provides persistent memory storage using PostgreSQL
with pgvector for similarity search.
"""

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agent_vault.memory.protocols import MemoryStorageProtocol, MemoryScoredRetrievalCapability

from agent_vault.memory.models import MemoryItem, MemoryContext, MemoryTier

if TYPE_CHECKING:
    from agent_vault.storage.providers.postgresql.connection import PostgresConnectionManager

logger = logging.getLogger(__name__)


class PostgresMemoryAdapter(MemoryStorageProtocol, MemoryScoredRetrievalCapability):
    """PostgreSQL implementation of memory storage.

    Uses pgvector for vector similarity search and stores
    all memory data in PostgreSQL tables.

    Implements MemoryScoredRetrievalCapability to return similarity scores
    alongside retrieved memories for proper semantic ranking.

    Attributes:
        _conn: PostgresConnectionManager for database access
        _table_name: Name of the memory table
        _embedding_dims: Dimension of embedding vectors
    """

    # Whitelist of valid column names to prevent SQL injection
    # Only these columns can be used in filters and updates
    ALLOWED_COLUMNS: frozenset[str] = frozenset({
        "id", "content", "summary", "tier", "importance", "access_count",
        "created_at", "accessed_at", "modified_at",
        "agent_id", "session_id", "conversation_id", "task_id", "project_id",
        "creator_agent_id", "modifier_agent_id", "content_source", "metadata",
    })

    def __init__(
        self,
        connection_manager: "PostgresConnectionManager",
        table_name: str,
        embedding_dims: int = 384,
        table_prefix: str = "",
        embedding_model: Optional[str] = None,
    ):
        """Initialize PostgreSQL memory adapter.

        Args:
            connection_manager: PostgresConnectionManager instance
            table_name: Base name for memory table
            embedding_dims: Dimension of embedding vectors
            table_prefix: Optional prefix for table names
            embedding_model: Server-side embedding model name (e.g., 'text-embedding-005').
                When set, retrieve operations use SQL-based embedding() instead of
                requiring pre-computed query vectors. Used by AlloyDB/RDS backends.
        """
        self._conn = connection_manager
        self._base_table_name = table_name
        self._table_name = f"{table_prefix}{table_name}" if table_prefix else table_name
        self._embedding_dims = embedding_dims
        self._embedding_model = embedding_model
        self._initialized = False
        logger.info(
            "PostgresMemoryAdapter created for table '%s' with %d dimensions%s",
            self._table_name,
            self._embedding_dims,
            f" (server-side: {embedding_model})" if embedding_model else "",
        )

    def _validate_column_name(self, column: str) -> str:
        """Validate column name against whitelist to prevent SQL injection.

        Args:
            column: Column name to validate

        Returns:
            The validated column name

        Raises:
            ValueError: If column name is not in the allowed whitelist
        """
        if column not in self.ALLOWED_COLUMNS:
            raise ValueError(
                f"Invalid column name '{column}'. "
                f"Allowed columns: {', '.join(sorted(self.ALLOWED_COLUMNS))}"
            )
        return column

    async def initialize(self) -> None:
        """Initialize storage and ensure table exists."""
        if self._initialized:
            return

        # Create table with vector column
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {self._table_name} (
            id VARCHAR(255) PRIMARY KEY,
            content TEXT NOT NULL,
            summary TEXT,
            tier VARCHAR(50) NOT NULL,
            importance REAL NOT NULL,
            access_count INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            accessed_at TIMESTAMPTZ DEFAULT NOW(),
            modified_at TIMESTAMPTZ,
            embedding vector({self._embedding_dims}),

            -- Context fields
            agent_id VARCHAR(255),
            session_id VARCHAR(255),
            conversation_id VARCHAR(255),
            task_id VARCHAR(255),
            project_id VARCHAR(255),

            -- Attribution fields
            creator_agent_id VARCHAR(255),
            modifier_agent_id VARCHAR(255),
            content_source VARCHAR(255),

            -- Optional fields as JSON
            metadata JSONB DEFAULT '{{}}'::jsonb
        );
        """

        # Create index for vector similarity search
        create_index_sql = f"""
        CREATE INDEX IF NOT EXISTS {self._table_name}_embedding_idx
        ON {self._table_name}
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
        """

        try:
            await self._conn.execute(create_table_sql)
            # Try to create vector index (may fail if table is empty)
            try:
                await self._conn.execute(create_index_sql)
            except Exception as e:
                logger.debug("Could not create vector index (table may be empty): %s", e)

            self._initialized = True
            logger.debug("PostgresMemoryAdapter initialized for table '%s'", self._table_name)
        except Exception as e:
            logger.error("Failed to initialize PostgresMemoryAdapter: %s", e)
            raise

    async def store(
        self,
        item: MemoryItem,
        vector: List[float],
    ) -> str:
        """Store memory item with embedding vector.

        When embedding_model is configured (server-side backends like AlloyDB/RDS),
        generates the embedding server-side using embedding('model', content) instead
        of the provided local vector, ensuring dimension consistency.

        Args:
            item: Memory item to store
            vector: Embedding vector (used for local embedding backends;
                    ignored when embedding_model is set)

        Returns:
            ID of stored item

        Raises:
            ValueError: If vector is empty/wrong dimensions (local embedding only)
        """
        # Serialize metadata to JSON
        metadata_json = json.dumps(item.metadata) if item.metadata else "{}"

        # For server-side embedding: use embedding() SQL function instead of local vector
        if self._embedding_model:
            insert_sql = f"""
            INSERT INTO {self._table_name} (
                id, content, summary, tier, importance, access_count,
                created_at, accessed_at, modified_at, embedding,
                agent_id, session_id, conversation_id, task_id, project_id,
                creator_agent_id, modifier_agent_id, content_source, metadata
            ) VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, embedding('{self._embedding_model}', $2)::vector,
                $10, $11, $12, $13, $14,
                $15, $16, $17, $18::jsonb
            )
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content,
                summary = EXCLUDED.summary,
                importance = EXCLUDED.importance,
                access_count = EXCLUDED.access_count,
                accessed_at = EXCLUDED.accessed_at,
                modified_at = NOW(),
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata
            """

            await self._conn.execute(
                insert_sql,
                item.id,
                item.content,
                item.summary,
                item.tier.value if isinstance(item.tier, MemoryTier) else str(item.tier),
                item.importance,
                item.access_count,
                item.created_at,
                item.accessed_at,
                item.modified_at,
                item.context.agent_id if item.context else None,
                item.context.session_id if item.context else None,
                item.context.conversation_id if item.context else None,
                item.context.task_id if item.context else None,
                item.context.project_id if item.context else None,
                item.creator_agent_id,
                item.modifier_agent_id,
                item.content_source,
                metadata_json,
            )
            return item.id

        # Local embedding path: validate and store the provided vector
        if not vector or len(vector) == 0:
            raise ValueError(
                "Cannot store memory with empty vector. "
                "This may indicate an embedding generation issue."
            )

        if len(vector) != self._embedding_dims:
            raise ValueError(
                f"Vector dimension mismatch: expected {self._embedding_dims}, "
                f"got {len(vector)}. Cannot store memory with mismatched dimensions."
            )

        # Convert vector to PostgreSQL format
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"

        insert_sql = f"""
        INSERT INTO {self._table_name} (
            id, content, summary, tier, importance, access_count,
            created_at, accessed_at, modified_at, embedding,
            agent_id, session_id, conversation_id, task_id, project_id,
            creator_agent_id, modifier_agent_id, content_source, metadata
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10::vector,
            $11, $12, $13, $14, $15,
            $16, $17, $18, $19::jsonb
        )
        ON CONFLICT (id) DO UPDATE SET
            content = EXCLUDED.content,
            summary = EXCLUDED.summary,
            importance = EXCLUDED.importance,
            access_count = EXCLUDED.access_count,
            accessed_at = EXCLUDED.accessed_at,
            modified_at = NOW(),
            embedding = EXCLUDED.embedding,
            metadata = EXCLUDED.metadata
        """

        await self._conn.execute(
            insert_sql,
            item.id,
            item.content,
            item.summary,
            item.tier.value if isinstance(item.tier, MemoryTier) else str(item.tier),
            item.importance,
            item.access_count,
            item.created_at,
            item.accessed_at,
            item.modified_at,
            vector_str,
            item.context.agent_id if item.context else None,
            item.context.session_id if item.context else None,
            item.context.conversation_id if item.context else None,
            item.context.task_id if item.context else None,
            item.context.project_id if item.context else None,
            item.creator_agent_id,
            item.modifier_agent_id,
            item.content_source,
            metadata_json,
        )

        return item.id

    async def retrieve(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """Retrieve memories by vector similarity.

        Args:
            query_vector: Query embedding vector
            limit: Maximum results
            filters: Optional filters

        Returns:
            List of similar memory items
        """
        # Validate query vector - pgvector requires at least 1 dimension
        if not query_vector or len(query_vector) == 0:
            logger.warning(
                "Empty query vector provided to retrieve() - returning empty results. "
                "This may indicate an embedding generation issue."
            )
            return []

        if len(query_vector) != self._embedding_dims:
            logger.error(
                "Vector dimension mismatch in retrieve(): expected %d, got %d. "
                "Returning empty results to prevent pgvector error.",
                self._embedding_dims,
                len(query_vector),
            )
            return []

        vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

        # Build WHERE clause from filters
        where_clauses = []
        params = [vector_str, limit]
        param_idx = 3

        if filters:
            for key, value in filters.items():
                validated_col = self._validate_column_name(key)
                where_clauses.append(f"{validated_col} = ${param_idx}")
                params.append(value)
                param_idx += 1

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query_sql = f"""
        SELECT id, content, summary, tier, importance, access_count,
               created_at, accessed_at, modified_at,
               agent_id, session_id, conversation_id, task_id, project_id,
               creator_agent_id, modifier_agent_id, content_source, metadata,
               1 - (embedding <=> $1::vector) as similarity
        FROM {self._table_name}
        {where_sql}
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """

        rows = await self._conn.fetch(query_sql, *params)

        items = []
        for row in rows:
            item = self._row_to_memory_item(row)
            if item:
                items.append(item)

        return items

    @property
    def supports_server_side_embedding(self) -> bool:
        """Whether this adapter can embed queries server-side (no local vector needed)."""
        return self._embedding_model is not None

    async def retrieve_by_text(
        self,
        query_text: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """Retrieve memories using server-side embedding of query text.

        Uses the database's embedding() function to embed the query server-side,
        avoiding the need for a local embedding model with matching dimensions.
        Only available when embedding_model is configured (AlloyDB, RDS).

        Args:
            query_text: Raw query string to embed server-side
            limit: Maximum results
            filters: Optional filters

        Returns:
            List of similar memory items
        """
        if not self._embedding_model:
            raise RuntimeError(
                "retrieve_by_text requires embedding_model to be configured. "
                "Use retrieve() with a pre-computed vector instead."
            )

        where_clauses = []
        params: list[Any] = [query_text, limit]
        param_idx = 3

        if filters:
            for key, value in filters.items():
                validated_col = self._validate_column_name(key)
                where_clauses.append(f"{validated_col} = ${param_idx}")
                params.append(value)
                param_idx += 1

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query_sql = f"""
        SELECT id, content, summary, tier, importance, access_count,
               created_at, accessed_at, modified_at,
               agent_id, session_id, conversation_id, task_id, project_id,
               creator_agent_id, modifier_agent_id, content_source, metadata,
               1 - (embedding <=> embedding('{self._embedding_model}', $1)::vector) as similarity
        FROM {self._table_name}
        {where_sql}
        ORDER BY embedding <=> embedding('{self._embedding_model}', $1)::vector
        LIMIT $2
        """

        rows = await self._conn.fetch(query_sql, *params)

        items = []
        for row in rows:
            item = self._row_to_memory_item(row)
            if item:
                items.append(item)

        return items

    async def retrieve_with_scores_by_text(
        self,
        query_text: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[MemoryItem, float]]:
        """Retrieve memories with similarity scores using server-side query embedding.

        Like retrieve_with_scores but uses the database's embedding() function
        for the query, matching the server-side embeddings stored in the table.

        Args:
            query_text: Raw query string to embed server-side
            limit: Maximum results
            filters: Optional filters

        Returns:
            List of (MemoryItem, similarity_score) tuples
        """
        if not self._embedding_model:
            raise RuntimeError(
                "retrieve_with_scores_by_text requires embedding_model to be configured."
            )

        where_clauses = []
        params: list[Any] = [query_text, limit]
        param_idx = 3

        if filters:
            for key, value in filters.items():
                validated_col = self._validate_column_name(key)
                where_clauses.append(f"{validated_col} = ${param_idx}")
                params.append(value)
                param_idx += 1

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query_sql = f"""
        SELECT id, content, summary, tier, importance, access_count,
               created_at, accessed_at, modified_at,
               agent_id, session_id, conversation_id, task_id, project_id,
               creator_agent_id, modifier_agent_id, content_source, metadata,
               1 - (embedding <=> embedding('{self._embedding_model}', $1)::vector) as similarity
        FROM {self._table_name}
        {where_sql}
        ORDER BY embedding <=> embedding('{self._embedding_model}', $1)::vector
        LIMIT $2
        """

        rows = await self._conn.fetch(query_sql, *params)

        results = []
        for row in rows:
            item = self._row_to_memory_item(row)
            if item:
                similarity = float(row.get("similarity", 0.0) if hasattr(row, "get") else getattr(row, "similarity", 0.0))
                results.append((item, similarity))

        return results

    async def retrieve_with_scores(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[MemoryItem, float]]:
        """Retrieve memories by vector similarity with similarity scores.

        This method implements MemoryScoredRetrievalCapability, returning
        both the MemoryItem and its similarity score for proper semantic
        ranking in the memory retrieval engine.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results to return
            filters: Optional field-based filters

        Returns:
            List of (MemoryItem, similarity_score) tuples sorted by similarity.
            Similarity scores are in range [0, 1] where 1 is most similar.

        Raises:
            ValueError: If query vector dimensions don't match
            RuntimeError: If retrieval fails
        """
        # Validate query vector - pgvector requires at least 1 dimension
        if not query_vector or len(query_vector) == 0:
            logger.warning(
                "Empty query vector provided to retrieve_with_scores() - returning empty results. "
                "This may indicate an embedding generation issue."
            )
            return []

        if len(query_vector) != self._embedding_dims:
            logger.error(
                "Vector dimension mismatch in retrieve_with_scores(): expected %d, got %d. "
                "Returning empty results to prevent pgvector error.",
                self._embedding_dims,
                len(query_vector),
            )
            return []

        vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

        # Build WHERE clause from filters
        where_clauses = []
        params = [vector_str, limit]
        param_idx = 3

        if filters:
            for key, value in filters.items():
                validated_col = self._validate_column_name(key)
                where_clauses.append(f"{validated_col} = ${param_idx}")
                params.append(value)
                param_idx += 1

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query_sql = f"""
        SELECT id, content, summary, tier, importance, access_count,
               created_at, accessed_at, modified_at,
               agent_id, session_id, conversation_id, task_id, project_id,
               creator_agent_id, modifier_agent_id, content_source, metadata,
               1 - (embedding <=> $1::vector) as similarity
        FROM {self._table_name}
        {where_sql}
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """

        rows = await self._conn.fetch(query_sql, *params)

        scored_results: List[Tuple[MemoryItem, float]] = []
        for row in rows:
            item = self._row_to_memory_item(row)
            if item:
                # Extract similarity score from the row
                similarity = float(row.get("similarity", 0.0))
                scored_results.append((item, similarity))

        return scored_results

    async def get_by_id(
        self,
        item_id: str,
    ) -> Optional[MemoryItem]:
        """Get memory item by ID.

        Args:
            item_id: Item ID

        Returns:
            Memory item or None
        """
        query_sql = f"""
        SELECT id, content, summary, tier, importance, access_count,
               created_at, accessed_at, modified_at,
               agent_id, session_id, conversation_id, task_id, project_id,
               creator_agent_id, modifier_agent_id, content_source, metadata
        FROM {self._table_name}
        WHERE id = $1
        """

        row = await self._conn.fetchrow(query_sql, item_id)
        if row:
            return self._row_to_memory_item(row)
        return None

    async def update(
        self,
        item_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Update memory item fields.

        Args:
            item_id: Item ID
            updates: Field updates

        Returns:
            True if updated
        """
        if not updates:
            return False

        # Build SET clause
        set_clauses = []
        params = []
        param_idx = 1

        for key, value in updates.items():
            validated_col = self._validate_column_name(key)
            set_clauses.append(f"{validated_col} = ${param_idx}")
            params.append(value)
            param_idx += 1

        params.append(item_id)
        set_sql = ", ".join(set_clauses)

        update_sql = f"""
        UPDATE {self._table_name}
        SET {set_sql}, modified_at = NOW()
        WHERE id = ${param_idx}
        """

        result = await self._conn.execute(update_sql, *params)
        return "UPDATE 1" in str(result) or result == "UPDATE 1"

    async def delete(
        self,
        item_id: str,
    ) -> bool:
        """Delete memory item.

        Args:
            item_id: Item ID

        Returns:
            True if deleted
        """
        delete_sql = f"""
        DELETE FROM {self._table_name}
        WHERE id = $1
        """

        result = await self._conn.execute(delete_sql, item_id)
        return "DELETE 1" in str(result) or result == "DELETE 1"

    async def count(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count memory items.

        Args:
            filters: Optional filters

        Returns:
            Count of matching items
        """
        where_clauses = []
        params = []
        param_idx = 1

        if filters:
            for key, value in filters.items():
                validated_col = self._validate_column_name(key)
                where_clauses.append(f"{validated_col} = ${param_idx}")
                params.append(value)
                param_idx += 1

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        count_sql = f"""
        SELECT COUNT(*) FROM {self._table_name}
        {where_sql}
        """

        result = await self._conn.fetchval(count_sql, *params)
        return result or 0

    def _row_to_memory_item(self, row: dict) -> Optional[MemoryItem]:
        """Convert database row to MemoryItem.

        Args:
            row: Database row dict

        Returns:
            MemoryItem or None if conversion fails
        """
        try:
            # Parse metadata
            metadata = {}
            if row.get("metadata"):
                if isinstance(row["metadata"], str):
                    metadata = json.loads(row["metadata"])
                else:
                    metadata = dict(row["metadata"])

            # Create context
            context = MemoryContext(
                agent_id=row.get("agent_id") or "unknown",
                session_id=row.get("session_id") or "unknown",
                conversation_id=row.get("conversation_id") or "unknown",
                task_id=row.get("task_id"),
                project_id=row.get("project_id"),
            )

            # Parse tier
            tier_value = row.get("tier", "episodic")
            tier = MemoryTier(tier_value) if tier_value else MemoryTier.EPISODIC

            return MemoryItem(
                id=row["id"],
                content=row["content"],
                summary=row.get("summary") or "",
                context=context,
                importance=row.get("importance", 0.5),
                tier=tier,
                creator_agent_id=row.get("creator_agent_id") or "unknown",
                modifier_agent_id=row.get("modifier_agent_id") or "unknown",
                content_source=row.get("content_source"),
                created_at=row.get("created_at") or datetime.now(timezone.utc),
                accessed_at=row.get("accessed_at") or datetime.now(timezone.utc),
                modified_at=row.get("modified_at"),
                access_count=row.get("access_count", 0),
                metadata=metadata,
            )
        except Exception as e:
            logger.error("Failed to convert row to MemoryItem: %s", e)
            return None
