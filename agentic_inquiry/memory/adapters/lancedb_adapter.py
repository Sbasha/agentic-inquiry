"""LanceDB adapter for memory storage.

This module provides a MemoryStorageProtocol-compliant adapter that uses
LanceDB for persistence. It encapsulates all LanceDB-specific operations
and row conversion logic.

Design reference: DES-S2-002 in .sessions/deep-architecture-review/009-design.md
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import numpy as np
import pyarrow as pa

from agentic_inquiry.memory.models import MemoryContext, MemoryItem, MemoryTier, MemoryStatus
from agentic_inquiry.memory.protocols import UPDATABLE_FIELDS


class _MetadataJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles common non-serializable types.

    Handles: UUID, datetime, date, Pydantic models, numpy types.
    """

    def default(self, obj: Any) -> Any:
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        # Handle Pydantic models
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        return super().default(obj)

if TYPE_CHECKING:
    from agentic_inquiry.database.lancedb_manager import LanceDBManager

logger = logging.getLogger(__name__)

# Optional columns hold these instead of NULL, as _memory_item_to_row writes.
_EMPTY_WHEN_NONE: Dict[str, Any] = {
    "content_source": "",
    "event_type": "",
    "subject": "",
    "relationship": "",
    "object": "",
    "superseded_by": "",
    "emotional_valence": 0.0,
    "emotional_arousal": 0.0,
    "confidence": 0.0,
}


def _column_value(field: str, value: Any) -> Any:
    """Convert a MemoryItem field value to the value store() writes for it.

    Raises:
        ValueError: If the value would leave a row that cannot be read back
    """
    if value is None:
        if field not in _EMPTY_WHEN_NONE:
            raise ValueError(f"Memory field {field} cannot be None")
        return _EMPTY_WHEN_NONE[field]
    if field == "tier":
        return MemoryTier(value).value
    if field == "status":
        return MemoryStatus(value).value
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"Memory field {field} must be finite, got {value}")
    return value


class LanceDBMemoryAdapter:
    """LanceDB implementation of MemoryStorageProtocol.

    This adapter wraps a LanceDBManager instance and provides high-level
    memory operations that work with MemoryItem objects directly.

    The adapter handles:
    - Schema creation and management
    - Row conversion between MemoryItem and LanceDB format
    - Vector search with filter translation
    - CRUD operations

    Example:
        adapter = LanceDBMemoryAdapter(
            manager=db_manager,
            table_name="memory_episodic",
            embedding_dims=384,
        )
        await adapter.initialize()
        await adapter.store(memory_item, embedding_vector)
    """

    def __init__(
        self,
        manager: "LanceDBManager",
        table_name: str,
        embedding_dims: int = 384,
        summary_embedding_dims: Optional[int] = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            manager: LanceDBManager instance for database operations
            table_name: Name of the table to use for this memory tier
            embedding_dims: Dimensions for content embedding vector
            summary_embedding_dims: Dimensions for summary embedding (defaults to embedding_dims)
        """
        self._manager = manager
        self._table_name = table_name
        self._embedding_dims = embedding_dims
        self._summary_embedding_dims = summary_embedding_dims or embedding_dims
        self._initialized = False

    @property
    def table_name(self) -> str:
        """Get the table name for this adapter."""
        return self._table_name

    async def initialize(self) -> None:
        """Initialize the storage and ensure tables exist.

        This method is idempotent - calling it multiple times
        has the same effect as calling it once.

        Raises:
            RuntimeError: If initialization fails
        """
        if self._initialized:
            return

        try:
            await self._manager.connect()
            existing = await self._manager.get_table(self._table_name)
            if existing is None:
                await self._manager.create_table_from_schema(
                    self._table_name, self.get_schema()
                )
            self._initialized = True
            logger.info(
                "LanceDBMemoryAdapter initialized: table=%s, dims=%d",
                self._table_name,
                self._embedding_dims,
            )
        except Exception as e:
            logger.error("Failed to initialize LanceDBMemoryAdapter: %s", e)
            raise RuntimeError(f"Memory adapter initialization failed: {e}") from e

    async def store(
        self,
        item: MemoryItem,
        vector: List[float],
    ) -> str:
        """Store memory item with embedding vector.

        Args:
            item: Memory item to store (must have valid id)
            vector: Embedding vector for similarity search

        Returns:
            ID of the stored item

        Raises:
            ValueError: If item is invalid
            RuntimeError: If storage fails
        """
        if not self._initialized:
            await self.initialize()

        try:
            row = self._memory_item_to_row(item, vector)
            await self._manager.add_rows(self._table_name, [row])
            logger.debug("Stored memory item: id=%s, table=%s", item.id, self._table_name)
            return item.id
        except Exception as e:
            logger.error("Failed to store memory item %s: %s", item.id, e)
            raise RuntimeError(f"Failed to store memory item: {e}") from e

    async def retrieve(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """Retrieve memories by vector similarity.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results to return
            filters: Optional field-based filters

        Returns:
            List of memory items sorted by similarity (highest first)

        Raises:
            RuntimeError: If retrieval fails
        """
        if not self._initialized:
            await self.initialize()

        try:
            results = await self._manager.vector_search(
                table_name=self._table_name,
                query_vector=query_vector,
                vector_column_name="vector",
                limit=limit,
                filters=filters,
                project_id=None,  # Memory tables don't use project isolation
            )

            return [self._row_to_memory_item(row) for row in results]
        except Exception as e:
            # Handle table not found gracefully (returns empty results)
            if "table" in str(e).lower() and "not found" in str(e).lower():
                logger.debug(
                    "Memory table %s not found, returning empty results",
                    self._table_name,
                )
                return []
            logger.error("Failed to retrieve memories: %s", e)
            raise RuntimeError(f"Failed to retrieve memories: {e}") from e

    async def retrieve_with_scores(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[MemoryItem, float]]:
        """Retrieve memories by vector similarity with similarity scores.

        This method implements MemoryScoredRetrievalCapability, returning
        both the MemoryItem and its similarity score for use in
        RetrievalResult population.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results to return
            filters: Optional field-based filters

        Returns:
            List of (MemoryItem, similarity_score) tuples sorted by similarity.
            Similarity scores are in range [0, 1] where 1 is most similar.

        Raises:
            RuntimeError: If retrieval fails
        """
        if not self._initialized:
            await self.initialize()

        try:
            results = await self._manager.vector_search(
                table_name=self._table_name,
                query_vector=query_vector,
                vector_column_name="vector",
                limit=limit,
                filters=filters,
                project_id=None,  # Memory tables don't use project isolation
            )

            scored_results: List[Tuple[MemoryItem, float]] = []
            for row in results:
                item = self._row_to_memory_item(row)
                # LanceDB returns _distance (L2 distance), convert to similarity
                distance = row.get("_distance", 0.0)
                similarity = 1.0 / (1.0 + distance)
                scored_results.append((item, similarity))

            return scored_results
        except Exception as e:
            # Handle table not found gracefully (returns empty results)
            if "table" in str(e).lower() and "not found" in str(e).lower():
                logger.debug(
                    "Memory table %s not found, returning empty results",
                    self._table_name,
                )
                return []
            logger.error("Failed to retrieve memories with scores: %s", e)
            raise RuntimeError(f"Failed to retrieve memories: {e}") from e

    async def get_by_id(
        self,
        item_id: str,
    ) -> Optional[MemoryItem]:
        """Retrieve a single memory item by ID.

        Args:
            item_id: ID of the item to retrieve

        Returns:
            Memory item if found, None otherwise

        Raises:
            RuntimeError: If retrieval fails
        """
        if not self._initialized:
            await self.initialize()

        try:
            results = await self._manager.advanced_filter(
                table_name=self._table_name,
                filters={"id": item_id},
                limit=1,
                project_id=None,  # Memory tables don't use project isolation
            )
            if results:
                return self._row_to_memory_item(results[0])
            return None
        except Exception as e:
            # Handle table not found gracefully (returns None)
            if "table" in str(e).lower() and "not found" in str(e).lower():
                logger.debug(
                    "Memory table %s not found, returning None",
                    self._table_name,
                )
                return None
            logger.error("Failed to get memory item %s: %s", item_id, e)
            raise RuntimeError(f"Failed to get memory item: {e}") from e

    async def update(
        self,
        item_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Set fields of a stored memory item in place.

        Writes only the named columns, in one commit, without deleting or
        re-inserting the row. A concurrent writer that changes other fields
        of the same item (for example access statistics) keeps its change.

        Args:
            item_id: ID of the item to update
            updates: MemoryItem field name to new value, for fields in
                ``UPDATABLE_FIELDS``

        Returns:
            True if item was updated, False if not found

        Raises:
            ValueError: If updates name a field outside ``UPDATABLE_FIELDS``,
                or a value the column cannot hold
            RuntimeError: If update fails
        """
        invalid = sorted(set(updates) - UPDATABLE_FIELDS)
        if invalid:
            raise ValueError(
                f"Cannot update memory fields in place: {', '.join(invalid)}"
            )
        values = {
            field: _column_value(field, value) for field, value in updates.items()
        }

        if not self._initialized:
            await self.initialize()

        try:
            rows_updated = await self._manager.update_by_ids(
                self._table_name, [item_id], values
            )
        except Exception as e:
            logger.error("Failed to update memory item %s: %s", item_id, e)
            raise RuntimeError(f"Failed to update memory item: {e}") from e

        logger.debug("Updated memory item: id=%s, fields=%s", item_id, sorted(values))
        return rows_updated > 0

    async def delete(
        self,
        item_id: str,
    ) -> bool:
        """Delete memory item.

        Args:
            item_id: ID of the item to delete

        Returns:
            True if deletion was attempted (LanceDB doesn't report actual deletions)

        Raises:
            RuntimeError: If deletion fails
        """
        if not self._initialized:
            await self.initialize()

        try:
            # Check if item exists first
            existing = await self.get_by_id(item_id)
            if not existing:
                return False

            await self._manager.delete_by_ids(self._table_name, [item_id])
            logger.debug("Deleted memory item: id=%s", item_id)
            return True
        except Exception as e:
            logger.error("Failed to delete memory item %s: %s", item_id, e)
            raise RuntimeError(f"Failed to delete memory item: {e}") from e

    async def count(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count memory items matching filters.

        Args:
            filters: Optional field-based filters

        Returns:
            Number of matching items

        Raises:
            RuntimeError: If count fails
        """
        if not self._initialized:
            await self.initialize()

        try:
            return await self._manager.count_records(
                table_name=self._table_name,
                filters=filters,
            )
        except Exception as e:
            # Handle table not found gracefully (returns 0)
            if "table" in str(e).lower() and "not found" in str(e).lower():
                logger.debug(
                    "Memory table %s not found, returning count 0",
                    self._table_name,
                )
                return 0
            logger.error("Failed to count memory items: %s", e)
            raise RuntimeError(f"Failed to count memory items: {e}") from e

    # =========================================================================
    # Bulk Operations (MemoryBulkCapability)
    # =========================================================================

    async def store_batch(
        self,
        items: List[MemoryItem],
        vectors: List[List[float]],
    ) -> int:
        """Store multiple memory items in a batch.

        Args:
            items: Memory items to store
            vectors: Corresponding embedding vectors (same order as items)

        Returns:
            Number of items stored

        Raises:
            ValueError: If items and vectors lengths don't match
            RuntimeError: If storage fails
        """
        if len(items) != len(vectors):
            raise ValueError(
                f"Items and vectors length mismatch: {len(items)} vs {len(vectors)}"
            )

        if not self._initialized:
            await self.initialize()

        try:
            rows = [
                self._memory_item_to_row(item, vector)
                for item, vector in zip(items, vectors)
            ]
            await self._manager.add_rows(self._table_name, rows)
            logger.debug("Stored %d memory items in batch", len(items))
            return len(items)
        except Exception as e:
            logger.error("Failed to store batch of %d items: %s", len(items), e)
            raise RuntimeError(f"Failed to store batch: {e}") from e

    async def delete_batch(
        self,
        item_ids: List[str],
    ) -> int:
        """Delete multiple memory items.

        Args:
            item_ids: IDs of items to delete

        Returns:
            Number of items requested for deletion (LanceDB doesn't report actual)

        Raises:
            RuntimeError: If deletion fails
        """
        if not self._initialized:
            await self.initialize()

        if not item_ids:
            return 0

        try:
            await self._manager.delete_by_ids(self._table_name, item_ids)
            logger.debug("Deleted %d memory items in batch", len(item_ids))
            return len(item_ids)
        except Exception as e:
            logger.error("Failed to delete batch of %d items: %s", len(item_ids), e)
            raise RuntimeError(f"Failed to delete batch: {e}") from e

    # =========================================================================
    # Query Operations (MemoryQueryCapability)
    # =========================================================================

    async def query(
        self,
        filters: Dict[str, Any],
        limit: Optional[int] = None,
        offset: int = 0,
        order_by: Optional[str] = None,
        order_desc: bool = False,
    ) -> List[MemoryItem]:
        """Query memory items with advanced filtering.

        Args:
            filters: Field-based filter conditions
            limit: Maximum results to return (None = all)
            offset: Number of results to skip
            order_by: Field name to sort by
            order_desc: Sort descending if True

        Returns:
            List of matching memory items

        Raises:
            RuntimeError: If query fails
        """
        if not self._initialized:
            await self.initialize()

        try:
            results = await self._manager.advanced_filter(
                table_name=self._table_name,
                filters=filters,
                limit=limit,
                project_id=None,  # Memory tables don't use project isolation
            )

            items = [self._row_to_memory_item(row) for row in results]

            # Apply offset
            if offset > 0:
                items = items[offset:]

            # Apply ordering if specified
            if order_by:
                items.sort(
                    key=lambda x: getattr(x, order_by, 0),
                    reverse=order_desc,
                )

            return items
        except Exception as e:
            # Handle table not found gracefully (returns empty list)
            if "table" in str(e).lower() and "not found" in str(e).lower():
                logger.debug(
                    "Memory table %s not found, returning empty results",
                    self._table_name,
                )
                return []
            logger.error("Failed to query memory items: %s", e)
            raise RuntimeError(f"Failed to query memory items: {e}") from e

    # =========================================================================
    # Schema and Conversion Helpers
    # =========================================================================

    def get_schema(self) -> pa.Schema:
        """Get the PyArrow schema for this memory table.

        Returns:
            PyArrow schema for LanceDB table creation
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
                pa.field("vector", pa.list_(pa.float32(), self._embedding_dims)),
                pa.field(
                    "summary_vector",
                    pa.list_(pa.float32(), self._summary_embedding_dims),
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

    def _memory_item_to_row(
        self, item: MemoryItem, vector: List[float]
    ) -> Dict[str, Any]:
        """Convert MemoryItem to LanceDB row format.

        Args:
            item: MemoryItem to convert
            vector: Embedding vector for the item

        Returns:
            Dictionary suitable for LanceDB insertion
        """
        return {
            "id": item.id,
            "agent_id": item.context.agent_id,
            "session_id": item.context.session_id,
            "conversation_id": item.context.conversation_id,
            "task_id": item.context.task_id or "",
            "project_id": item.context.project_id or "",
            "content": item.content,
            "summary": item.summary,
            "importance": item.importance,
            "tier": item.tier.value,
            "creator_agent_id": item.creator_agent_id,
            "modifier_agent_id": item.modifier_agent_id,
            "content_source": item.content_source or "",
            "created_at": item.created_at,
            "accessed_at": item.accessed_at,
            "modified_at": item.modified_at or datetime.now(timezone.utc),
            "access_count": item.access_count,
            "vector": vector,
            "summary_vector": (
                item.summary_embedding.tolist()
                if item.summary_embedding is not None
                else [0.0] * self._summary_embedding_dims
            ),
            "event_type": item.event_type or "",
            "emotional_valence": item.emotional_valence or 0.0,
            "emotional_arousal": item.emotional_arousal or 0.0,
            "subject": item.subject or "",
            "relationship": item.relationship or "",
            "object": item.object or "",
            "confidence": item.confidence or 0.0,
            "status": item.status.value,
            "superseded_by": item.superseded_by or "",
            "metadata": json.dumps(item.metadata, cls=_MetadataJSONEncoder),
        }

    def _row_to_memory_item(self, row: Dict[str, Any]) -> MemoryItem:
        """Convert LanceDB row to MemoryItem.

        Args:
            row: Dictionary from LanceDB query

        Returns:
            MemoryItem instance
        """
        # Reconstruct context
        context = MemoryContext(
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            conversation_id=row["conversation_id"],
            task_id=row.get("task_id") or None,
            project_id=row.get("project_id") or None,
            priority=0.5,  # Default priority
            metadata={},
            created_at=row["created_at"],
        )

        # Parse metadata
        metadata = {}
        if row.get("metadata"):
            try:
                metadata = json.loads(row["metadata"])
            except json.JSONDecodeError:
                logger.warning("Failed to parse metadata for item %s", row["id"])

        # Convert embeddings
        embedding = np.array(row["vector"]) if row.get("vector") else None
        summary_embedding = (
            np.array(row["summary_vector"]) if row.get("summary_vector") else None
        )

        return MemoryItem(
            id=row["id"],
            content=row["content"],
            summary=row["summary"],
            context=context,
            importance=row["importance"],
            tier=MemoryTier(row["tier"]),
            creator_agent_id=row["creator_agent_id"],
            modifier_agent_id=row["modifier_agent_id"],
            content_source=row.get("content_source") or None,
            created_at=row["created_at"],
            accessed_at=row["accessed_at"],
            modified_at=row.get("modified_at"),
            access_count=row.get("access_count", 0),
            embedding=embedding,
            summary_embedding=summary_embedding,
            event_type=row.get("event_type") or None,
            emotional_valence=row.get("emotional_valence"),
            emotional_arousal=row.get("emotional_arousal"),
            subject=row.get("subject") or None,
            relationship=row.get("relationship") or None,
            object=row.get("object") or None,
            confidence=row.get("confidence"),
            status=MemoryStatus(row.get("status", "active")),
            superseded_by=row.get("superseded_by") or None,
            metadata=metadata,
        )
