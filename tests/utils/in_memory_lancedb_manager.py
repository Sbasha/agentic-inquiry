"""In-memory LanceDB manager used to isolate tests from the real backend."""
from __future__ import annotations

import asyncio
import logging
import math
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional

from agentic_inquiry.database.lancedb_manager import (
    FORBIDDEN_FIELD_ALIASES,
    REQUIRED_FIELDS,
)

logger = logging.getLogger(__name__)


class _MockVectorProvider:
    """Mock vector provider for InMemoryLanceDBManager.

    Provides the nested structure expected by SessionManager:
    db_manager.vector_provider._db_manager
    """
    def __init__(self, db_manager: "InMemoryLanceDBManager"):
        self._db_manager = db_manager


class InMemoryLanceDBManager:
    """A lightweight drop-in replacement for :class:`LanceDBManager`."""

    def __init__(self, uri: str, project_id: Optional[str] = None):
        self.uri = uri
        self._project_id = project_id
        self.db: Optional[InMemoryLanceDBManager] = None
        self._tables: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        # Provide vector_provider for StorageFacade compatibility
        self.vector_provider = _MockVectorProvider(self)


    def _validate_record(
        self, 
        table_name: str, 
        record: Dict[str, Any],
        strict: bool = True
    ) -> None:
        """Validate a record against schema requirements before write.
        
        Args:
            table_name: Name of the target table
            record: Dictionary to validate
            strict: If True, raise error on forbidden fields; if False, log warning
            
        Raises:
            ValueError: If record contains forbidden field aliases or missing required fields
        """
        # Check for forbidden field aliases (common mistakes)
        for forbidden, correct in FORBIDDEN_FIELD_ALIASES.items():
            if forbidden in record:
                msg = (
                    f"Field '{forbidden}' is not allowed in {table_name}. "
                    f"Use '{correct}' instead. This is a schema consistency error."
                )
                if strict:
                    raise ValueError(msg)
                else:
                    logger.warning(msg)
        
        # Check for required fields
        if table_name in REQUIRED_FIELDS:
            required = REQUIRED_FIELDS[table_name]
            missing = [f for f in required if f not in record]
            if missing:
                raise ValueError(
                    f"Missing required fields for {table_name}: {missing}. "
                    f"Required fields are: {required}"
                )

    async def connect(self) -> "InMemoryLanceDBManager":
        if self.db is None:
            self.db = self
        return self

    async def create_tables_and_indexes(self) -> None:
        self._tables = {
            "document_chunks": [],
            "graph_entities": [],
            "graph_relationships": [],
        }
        self.db = self

    async def add_document_chunks(
        self,
        chunks: List[Any],
        project_id: str = "current",
        ensure_commit: bool = True,
    ) -> None:
        await self._add_rows("document_chunks", chunks)
        # Note: ensure_commit parameter is accepted for compatibility but has no effect in memory

    async def add_graph_entities(
        self,
        entities: List[Any],
        project_id: str = "current",
        ensure_commit: bool = True,
    ) -> None:
        await self._add_rows("graph_entities", entities)
        # Note: ensure_commit parameter is accepted for compatibility but has no effect in memory

    async def add_graph_relationships(
        self,
        relationships: List[Any],
        project_id: str = "current",
        ensure_commit: bool = True,
    ) -> None:
        await self._add_rows("graph_relationships", relationships)

    async def graph_ranking_available(self) -> bool:
        rows = await self.advanced_filter("graph_entities", limit=5)
        return any(
            row.get("has_ranking_signals") or row.get("pagerank") is not None
            for row in rows
        )

    async def delete_document_chunks(self, ids: List[str]) -> None:
        await self._delete_rows("document_chunks", ids)

    async def delete_graph_entities(self, ids: List[str]) -> None:
        await self._delete_rows("graph_entities", ids)

    async def delete_graph_relationships(self, ids: List[str]) -> None:
        await self._delete_rows("graph_relationships", ids)

    async def vector_search(
        self,
        table_name: str,
        query_vector: List[float],
        vector_column_name: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = "current",
    ) -> List[Dict[str, Any]]:
        # Add project_id filter if specified
        filters = self._add_project_filter(filters, project_id)
        rows = await self._get_rows(table_name, filters)
        if not query_vector:
            return rows[:limit]

        def cosine_similarity(row: Dict[str, Any]) -> float:
            candidate = row.get(vector_column_name) or []
            if not candidate:
                return -1.0
            dot = sum(a * b for a, b in zip(query_vector, candidate))
            norm_q = math.sqrt(sum(a * a for a in query_vector))
            norm_c = math.sqrt(sum(a * a for a in candidate))
            if norm_q == 0 or norm_c == 0:
                return 0.0
            return dot / (norm_q * norm_c)

        scored = [(cosine_similarity(row), row) for row in rows]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in scored[:limit]]

    async def fts_search(
        self,
        table_name: str,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = "current",
    ) -> List[Dict[str, Any]]:
        # Add project_id filter if specified
        filters = self._add_project_filter(filters, project_id)
        rows = await self._get_rows(table_name, filters)
        if not query:
            return rows[:limit]

        needle = query.lower()

        def text_score(row: Dict[str, Any]) -> int:
            haystacks = [
                row.get("fts_text", ""),
                row.get("content", ""),
                row.get("element_name", ""),
            ]
            combined = " ".join(filter(None, haystacks)).lower()
            return combined.count(needle)

        scored = []
        for row in rows:
            score = text_score(row)
            if score > 0 or not needle:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in scored[:limit]]

    async def advanced_filter(
        self,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        project_id: Optional[str] = "current",
    ) -> List[Dict[str, Any]]:
        # Add project_id filter if specified
        filters = self._add_project_filter(filters, project_id)
        rows = await self._get_rows(table_name, filters)
        if limit is not None:
            rows = rows[:limit]
        return rows

    async def query_raw(
        self,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = "current",
    ) -> List[Dict[str, Any]]:
        """Query table returning raw dicts (like advanced_filter but matches LanceDBManager API)."""
        return await self.advanced_filter(
            table_name=table_name,
            filters=filters,
            limit=limit,
            project_id=project_id,
        )

    async def query_entities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = "current",
    ) -> List[Dict[str, Any]]:
        """Query graph entities with filters."""
        return await self.advanced_filter(
            table_name="graph_entities",
            filters=filters,
            limit=limit,
            project_id=project_id,
        )

    async def query_relationships(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = "current",
    ) -> List[Dict[str, Any]]:
        """Query graph relationships with filters."""
        return await self.advanced_filter(
            table_name="graph_relationships",
            filters=filters,
            limit=limit,
            project_id=project_id,
        )

    async def upsert(
        self,
        table_name: str,
        data: List[Dict[str, Any]],
        key_field: str = "id",
    ) -> None:
        """Insert or update records in a table."""
        if not data:
            return
        
        # Separate records into updates and inserts
        to_insert = []
        to_delete_ids = []
        
        for record in data:
            key_value = record.get(key_field)
            if not key_value:
                # No key value, treat as insert
                to_insert.append(record)
                continue
            
            # Check if record exists
            existing = await self.advanced_filter(
                table_name=table_name,
                filters={key_field: key_value},
                limit=1,
                project_id=None,
            )
            
            if existing:
                # Record exists - mark for deletion and re-insert
                # Use the 'id' field for deletion (standard primary key)
                if existing[0].get("id"):
                    to_delete_ids.append(existing[0]["id"])
                to_insert.append(record)
            else:
                # Record doesn't exist, insert it
                to_insert.append(record)
        
        # Delete existing records
        if to_delete_ids:
            await self._delete_rows(table_name=table_name, ids=to_delete_ids)
        
        # Insert all records (both new and updated)
        if to_insert:
            await self._add_rows(table_name=table_name, items=to_insert)
    
    async def query_across_projects(
        self,
        table_name: str,
        project_ids: List[str],
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Query across multiple projects."""
        if not project_ids:
            return []
        
        # Build filter with project_ids using IN clause
        project_filter = {"project_id": ("IN", project_ids)}
        
        if filters is None:
            filters = project_filter
        else:
            filters = {**filters, **project_filter}
        
        rows = await self._get_rows(table_name, filters)
        if limit is not None:
            rows = rows[:limit]
        return rows
    
    def _add_project_filter(
        self,
        filters: Optional[Dict[str, Any]],
        project_id: Optional[str] = "current",
    ) -> Optional[Dict[str, Any]]:
        """Add project_id filter to existing filters."""
        # If project_id is None, search all projects (no filter)
        if project_id is None:
            return filters
        
        # If project_id is "current", use the configured project_id
        if project_id == "current":
            if self._project_id is None:
                # No project_id configured, don't filter
                return filters
            project_id = self._project_id
        
        # Add project_id filter
        project_filter = {"project_id": project_id}
        
        if filters is None:
            return project_filter
        
        # Merge with existing filters
        return {**filters, **project_filter}

    async def _add_rows(self, table_name: str, items: Iterable[Any]) -> None:
        async with self._lock:
            table = self._tables.setdefault(table_name, [])
            for item in items:
                if hasattr(item, "to_dict"):
                    record = item.to_dict()
                elif hasattr(item, "model_dump"):
                    record = item.model_dump()
                else:
                    record = deepcopy(item)
                
                # Validate record against schema requirements before adding
                self._validate_record(table_name, record)
                table.append(record)

    async def _delete_rows(self, table_name: str, ids: List[str]) -> None:
        async with self._lock:
            table = self._tables.get(table_name, [])
            id_set = set(ids)
            self._tables[table_name] = [row for row in table if row.get("id") not in id_set]

    async def add_rows(self, table_name: str, items: List[Dict[str, Any]]) -> None:
        """Public API for adding rows - delegates to _add_rows."""
        await self._add_rows(table_name, items)

    async def delete_by_ids(self, table_name: str, ids: List[str]) -> None:
        """Public API for deleting rows by ID - delegates to _delete_rows."""
        await self._delete_rows(table_name, ids)

    async def _get_rows(self, table_name: str, filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        async with self._lock:
            rows = [deepcopy(row) for row in self._tables.get(table_name, [])]
        if not filters:
            return rows
        return [row for row in rows if self._matches_filters(row, filters)]

    def _matches_filters(self, row: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        for key, value in filters.items():
            upper_key = key.upper()
            if upper_key == "OR":
                return any(self._matches_filters(row, option) for option in value)
            if upper_key == "NOT":
                return not self._matches_filters(row, value)

            if isinstance(value, tuple) and len(value) == 2:
                operator, expected = value
                operator_upper = operator.upper()
                actual = row.get(key)
                if operator_upper == "IN":
                    if actual not in expected:
                        return False
                elif operator_upper == "!=":
                    if actual == expected:
                        return False
                elif operator_upper in {">", ">=", "<", "<="}:
                    if actual is None:
                        return False
                    comparison = {
                        ">": actual > expected,
                        ">=": actual >= expected,
                        "<": actual < expected,
                        "<=": actual <= expected,
                    }[operator_upper]
                    if not comparison:
                        return False
                else:
                    if actual != expected:
                        return False
            else:
                if row.get(key) != value:
                    return False
        return True
