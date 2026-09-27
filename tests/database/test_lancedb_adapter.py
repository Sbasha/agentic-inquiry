"""Tests for LanceDB adapter.

Tests cover:
- Adapter lifecycle (initialize, close)
- CRUD operations (add, delete, get_by_ids, upsert)
- Vector search
- FTS search
- Hybrid search
- Graph ranking capabilities
- Query execution via execute()
- Result conversion and score normalization
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
from agentic_inquiry.database.filters import and_, eq, gt, is_in
from agentic_inquiry.database.query_spec import QuerySpec
from agentic_inquiry.database.results import SearchResult


@pytest.fixture
def mock_manager() -> MagicMock:
    """Create a mock LanceDBManager."""
    manager = MagicMock()
    manager.connect = AsyncMock()
    manager.create_tables_and_indexes = AsyncMock()
    manager.close = AsyncMock()
    manager.list_tables = AsyncMock(return_value=["document_chunks", "graph_entities"])
    manager.count_records = AsyncMock(return_value=100)
    manager.add_rows = AsyncMock()
    manager.delete_by_ids = AsyncMock()
    manager.upsert = AsyncMock()
    manager.advanced_filter = AsyncMock(return_value=[])
    manager.vector_search = AsyncMock(return_value=[])
    manager.fts_search = AsyncMock(return_value=[])
    manager.hybrid_search = AsyncMock(return_value=[])
    manager.graph_ranking_available = AsyncMock(return_value=True)
    manager.query_across_projects = AsyncMock(return_value=[])
    return manager


@pytest.fixture
def adapter(mock_manager: MagicMock) -> LanceDBAdapter:
    """Create adapter with mock manager."""
    return LanceDBAdapter(mock_manager)


class TestAdapterLifecycle:
    """Tests for adapter initialization and cleanup."""

    @pytest.mark.asyncio
    async def test_initialize(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Initialize connects and creates tables."""
        await adapter.initialize()

        mock_manager.connect.assert_called_once()
        mock_manager.create_tables_and_indexes.assert_called_once()
        assert adapter._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_idempotent(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Multiple initialize calls only run once."""
        await adapter.initialize()
        await adapter.initialize()
        await adapter.initialize()

        # Should only be called once
        assert mock_manager.connect.call_count == 1
        assert mock_manager.create_tables_and_indexes.call_count == 1

    @pytest.mark.asyncio
    async def test_close(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Close releases resources."""
        await adapter.initialize()
        await adapter.close()

        mock_manager.close.assert_called_once()
        assert adapter._initialized is False


class TestCRUDOperations:
    """Tests for add, delete, get_by_ids, upsert."""

    @pytest.mark.asyncio
    async def test_add_records(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Add forwards to manager."""
        records = [{"id": "1", "content": "test"}]
        await adapter.add("document_chunks", records)

        mock_manager.add_rows.assert_called_once_with("document_chunks", records)

    @pytest.mark.asyncio
    async def test_add_empty_list(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Add with empty list does nothing."""
        await adapter.add("document_chunks", [])

        mock_manager.add_rows.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_by_ids(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Delete forwards to manager and returns actual deleted count."""
        ids = ["id1", "id2"]
        # Mock advanced_filter to return 2 matching records (simulating they exist)
        mock_manager.advanced_filter.return_value = [{"id": "id1"}, {"id": "id2"}]

        result = await adapter.delete("document_chunks", ids)

        mock_manager.delete_by_ids.assert_called_once_with("document_chunks", ids)
        assert result == 2  # Actual count of existing records

    @pytest.mark.asyncio
    async def test_delete_empty_list(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Delete with empty list returns 0."""
        result = await adapter.delete("document_chunks", [])

        mock_manager.delete_by_ids.assert_not_called()
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_by_ids(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Get by IDs uses IN filter."""
        mock_manager.advanced_filter.return_value = [{"id": "1", "content": "test"}]

        result = await adapter.get_by_ids("document_chunks", ["1", "2"])

        mock_manager.advanced_filter.assert_called_once()
        call_args = mock_manager.advanced_filter.call_args
        assert call_args[0][0] == "document_chunks"
        assert "_sql" in call_args[1]["filters"]
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_by_ids_empty(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Get with empty list returns empty."""
        result = await adapter.get_by_ids("document_chunks", [])

        mock_manager.advanced_filter.assert_not_called()
        assert result == []

    @pytest.mark.asyncio
    async def test_upsert(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Upsert forwards to manager."""
        records = [{"id": "1", "content": "updated"}]
        await adapter.upsert("document_chunks", records)

        mock_manager.upsert.assert_called_once_with(
            "document_chunks", records, key_field="id"
        )

    @pytest.mark.asyncio
    async def test_upsert_empty(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Upsert with empty list does nothing."""
        await adapter.upsert("document_chunks", [])

        mock_manager.upsert.assert_not_called()


class TestVectorSearch:
    """Tests for vector similarity search."""

    @pytest.mark.asyncio
    async def test_vector_search_basic(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Basic vector search."""
        mock_manager.vector_search.return_value = [
            {"id": "1", "content": "test", "_distance": 0.5}
        ]

        vector = [0.1] * 384
        results = await adapter.vector_search("document_chunks", vector, limit=10)

        mock_manager.vector_search.assert_called_once()
        call_kwargs = mock_manager.vector_search.call_args[1]
        assert call_kwargs["table_name"] == "document_chunks"
        assert call_kwargs["query_vector"] == vector
        assert call_kwargs["limit"] == 10

        assert len(results) == 1
        assert results[0].id == "1"
        assert results[0].source == "vector"

    @pytest.mark.asyncio
    async def test_vector_search_with_filters(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Vector search with filter."""
        mock_manager.vector_search.return_value = []

        vector = [0.1] * 384
        filter_ast = eq("status", "active")
        await adapter.vector_search(
            "document_chunks", vector, limit=5, filters=filter_ast
        )

        call_kwargs = mock_manager.vector_search.call_args[1]
        assert "_sql" in call_kwargs["filters"]
        assert "active" in call_kwargs["filters"]["_sql"]

    @pytest.mark.asyncio
    async def test_vector_search_with_project_id(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Vector search with project scope."""
        mock_manager.vector_search.return_value = []

        vector = [0.1] * 384
        await adapter.vector_search("document_chunks", vector, project_ids=["proj_001"])

        call_kwargs = mock_manager.vector_search.call_args[1]
        assert call_kwargs["project_id"] == "proj_001"


class TestFTSSearch:
    """Tests for full-text search."""

    @pytest.mark.asyncio
    async def test_fts_search_basic(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Basic FTS search."""
        mock_manager.fts_search.return_value = [
            {"id": "1", "content": "authentication", "_score": 0.9}
        ]

        results = await adapter.fts_search(
            "document_chunks", "authentication", limit=10
        )

        mock_manager.fts_search.assert_called_once()
        call_kwargs = mock_manager.fts_search.call_args[1]
        assert call_kwargs["table_name"] == "document_chunks"
        assert call_kwargs["query"] == "authentication"

        assert len(results) == 1
        assert results[0].id == "1"
        assert results[0].score == 0.9
        assert results[0].source == "fts"

    @pytest.mark.asyncio
    async def test_fts_search_with_filters(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """FTS search with filter."""
        mock_manager.fts_search.return_value = []

        filter_ast = gt("score", 0.5)
        await adapter.fts_search("document_chunks", "test query", filters=filter_ast)

        call_kwargs = mock_manager.fts_search.call_args[1]
        assert "_sql" in call_kwargs["filters"]


class TestHybridSearch:
    """Tests for hybrid search."""

    @pytest.mark.asyncio
    async def test_hybrid_search_basic(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Basic hybrid search."""
        mock_manager.hybrid_search.return_value = [
            {"id": "1", "content": "test", "_score": 0.85}
        ]

        vector = [0.1] * 384
        results = await adapter.hybrid_search(
            "document_chunks", vector, "test query", limit=10
        )

        mock_manager.hybrid_search.assert_called_once()
        call_kwargs = mock_manager.hybrid_search.call_args[1]
        assert call_kwargs["table_name"] == "document_chunks"
        assert call_kwargs["query_vector"] == vector
        assert call_kwargs["query"] == "test query"

        assert len(results) == 1
        assert results[0].source == "hybrid"

    @pytest.mark.asyncio
    async def test_hybrid_search_with_weights(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Hybrid search accepts weights (not passed to manager yet)."""
        mock_manager.hybrid_search.return_value = []

        vector = [0.1] * 384
        await adapter.hybrid_search(
            "document_chunks",
            vector,
            "query",
            vector_weight=0.8,
            fts_weight=0.2,
        )

        # Verify call was made (weights documented as not passed through currently)
        mock_manager.hybrid_search.assert_called_once()


class TestGraphRanking:
    """Tests for graph ranking capabilities."""

    @pytest.mark.asyncio
    async def test_has_graph_ranking(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Check graph ranking availability."""
        mock_manager.graph_ranking_available.return_value = True

        result = await adapter.has_graph_ranking("document_chunks")

        mock_manager.graph_ranking_available.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_has_graph_ranking_table_ignored(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Table parameter is ignored (LanceDBManager always checks graph_entities)."""
        await adapter.has_graph_ranking("any_table")
        await adapter.has_graph_ranking("another_table")

        # Both calls go to manager without table param
        assert mock_manager.graph_ranking_available.call_count == 2

    @pytest.mark.asyncio
    async def test_apply_graph_boost(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Apply PageRank-based boost to results."""
        # Setup: mock pagerank query
        mock_manager.advanced_filter.return_value = [
            {"id": "1", "pagerank": 0.8},
            {"id": "2", "pagerank": 0.2},
        ]

        # Create input results
        results = [
            SearchResult(id="1", data={}, score=0.5, source="vector"),
            SearchResult(id="2", data={}, score=0.7, source="vector"),
        ]

        boosted = await adapter.apply_graph_boost(
            results, "document_chunks", boost_factor=0.5
        )

        assert len(boosted) == 2
        # Result with higher pagerank (0.8) should be boosted more
        # id="1": (1-0.5)*0.5 + 0.5*0.8 = 0.25 + 0.4 = 0.65
        # id="2": (1-0.5)*0.7 + 0.5*0.2 = 0.35 + 0.1 = 0.45
        assert boosted[0].id == "1"  # Higher combined score
        assert boosted[1].id == "2"
        assert boosted[0].source == "graph_boosted"

    @pytest.mark.asyncio
    async def test_apply_graph_boost_empty_results(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Graph boost with empty results returns empty."""
        result = await adapter.apply_graph_boost([], "document_chunks")

        assert result == []
        mock_manager.advanced_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_graph_boost_zero_factor(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Graph boost with factor=0 returns unchanged results."""
        results = [SearchResult(id="1", data={}, score=0.5, source="vector")]

        boosted = await adapter.apply_graph_boost(
            results, "document_chunks", boost_factor=0.0
        )

        assert boosted == results
        mock_manager.advanced_filter.assert_not_called()


class TestQueryExecution:
    """Tests for execute() method with QuerySpec."""

    @pytest.mark.asyncio
    async def test_execute_vector_only(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Execute routes to vector search when only vector specified."""
        mock_manager.vector_search.return_value = [{"id": "1", "_distance": 0.3}]

        spec = QuerySpec(
            table="document_chunks",
            vector=[0.1] * 384,
            limit=10,
        )
        results = await adapter.execute(spec)

        mock_manager.vector_search.assert_called_once()
        mock_manager.fts_search.assert_not_called()
        mock_manager.hybrid_search.assert_not_called()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_execute_fts_only(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Execute routes to FTS when only fts_query specified."""
        mock_manager.fts_search.return_value = [{"id": "1", "_score": 0.9}]

        spec = QuerySpec(
            table="document_chunks",
            fts_query="search terms",
            limit=10,
        )
        results = await adapter.execute(spec)

        mock_manager.fts_search.assert_called_once()
        mock_manager.vector_search.assert_not_called()
        mock_manager.hybrid_search.assert_not_called()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_execute_hybrid(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Execute routes to hybrid when both vector and fts_query specified."""
        mock_manager.hybrid_search.return_value = [{"id": "1", "_score": 0.85}]

        spec = QuerySpec(
            table="document_chunks",
            vector=[0.1] * 384,
            fts_query="search terms",
            limit=10,
        )
        results = await adapter.execute(spec)

        mock_manager.hybrid_search.assert_called_once()
        mock_manager.vector_search.assert_not_called()
        mock_manager.fts_search.assert_not_called()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_execute_filter_only(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Execute routes to filter query when no vector/fts."""
        mock_manager.advanced_filter.return_value = [{"id": "1", "status": "active"}]

        spec = QuerySpec(
            table="document_chunks",
            filters=eq("status", "active"),
            limit=10,
        )
        results = await adapter.execute(spec)

        mock_manager.advanced_filter.assert_called_once()
        assert len(results) == 1
        assert results[0].source == "filter"
        assert results[0].score == 1.0  # Default for filter-only


class TestTableOperations:
    """Tests for table_exists and count."""

    @pytest.mark.asyncio
    async def test_table_exists_true(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Table exists returns True for existing table."""
        result = await adapter.table_exists("document_chunks")

        mock_manager.list_tables.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_table_exists_false(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Table exists returns False for missing table."""
        result = await adapter.table_exists("nonexistent_table")

        assert result is False

    @pytest.mark.asyncio
    async def test_count_without_filters(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Count without filters."""
        result = await adapter.count("document_chunks")

        mock_manager.count_records.assert_called_once_with(
            "document_chunks", filters=None
        )
        assert result == 100

    @pytest.mark.asyncio
    async def test_count_with_filters(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Count with filters."""
        filter_ast = eq("status", "active")
        await adapter.count("document_chunks", filters=filter_ast)

        call_kwargs = mock_manager.count_records.call_args[1]
        assert "_sql" in call_kwargs["filters"]


class TestScoreNormalization:
    """Tests for score normalization in result conversion."""

    @pytest.mark.asyncio
    async def test_distance_to_score(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Distance is converted to normalized score."""
        mock_manager.vector_search.return_value = [
            {"id": "1", "_distance": 0.0},  # Perfect match → ~1.0
            {"id": "2", "_distance": 1.0},  # Some distance → 0.5
            {"id": "3", "_distance": 9.0},  # Far → 0.1
        ]

        results = await adapter.vector_search("document_chunks", [0.1] * 384)

        # Using 1/(1+distance) normalization
        assert results[0].score == pytest.approx(1.0, abs=0.01)
        assert results[1].score == pytest.approx(0.5, abs=0.01)
        assert results[2].score == pytest.approx(0.1, abs=0.01)

    @pytest.mark.asyncio
    async def test_score_passthrough(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Pre-computed scores are passed through."""
        mock_manager.fts_search.return_value = [
            {"id": "1", "_score": 0.95},
            {"id": "2", "_score": 0.3},
        ]

        results = await adapter.fts_search("document_chunks", "query")

        assert results[0].score == 0.95
        assert results[1].score == 0.3

    @pytest.mark.asyncio
    async def test_score_clamping(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Scores are clamped to 0.0-1.0 range."""
        mock_manager.fts_search.return_value = [
            {"id": "1", "_score": 1.5},  # Above max
            {"id": "2", "_score": -0.1},  # Below min
        ]

        results = await adapter.fts_search("document_chunks", "query")

        assert results[0].score == 1.0  # Clamped
        assert results[1].score == 0.0  # Clamped


class TestProjectIdResolution:
    """Tests for project_ids handling."""

    @pytest.mark.asyncio
    async def test_single_project_id(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Single project ID is passed through."""
        mock_manager.vector_search.return_value = []

        await adapter.vector_search(
            "document_chunks", [0.1] * 384, project_ids=["proj_001"]
        )

        call_kwargs = mock_manager.vector_search.call_args[1]
        assert call_kwargs["project_id"] == "proj_001"

    @pytest.mark.asyncio
    async def test_empty_project_ids(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Empty project_ids list means all projects."""
        mock_manager.vector_search.return_value = []

        await adapter.vector_search("document_chunks", [0.1] * 384, project_ids=[])

        call_kwargs = mock_manager.vector_search.call_args[1]
        assert call_kwargs["project_id"] is None

    @pytest.mark.asyncio
    async def test_none_project_ids(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """None project_ids means all projects."""
        mock_manager.vector_search.return_value = []

        await adapter.vector_search("document_chunks", [0.1] * 384, project_ids=None)

        call_kwargs = mock_manager.vector_search.call_args[1]
        assert call_kwargs["project_id"] is None

    @pytest.mark.asyncio
    async def test_multiple_project_ids_uses_first(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Multiple project_ids uses IN clause filter instead of single project_id."""
        mock_manager.vector_search.return_value = []

        # With multiple project_ids, should use IN clause filter
        await adapter.vector_search(
            "document_chunks", [0.1] * 384, project_ids=["proj_001", "proj_002"]
        )

        call_kwargs = mock_manager.vector_search.call_args[1]
        # project_id should be None when using IN clause
        assert call_kwargs["project_id"] is None
        # filters should contain IN clause for project_id
        assert call_kwargs["filters"] is not None
        assert call_kwargs["filters"]["project_id"] == ("IN", ["proj_001", "proj_002"])


class TestFilterTranslation:
    """Tests for filter AST translation integration."""

    @pytest.mark.asyncio
    async def test_simple_filter(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Simple EQ filter is translated."""
        mock_manager.vector_search.return_value = []

        filter_ast = eq("status", "active")
        await adapter.vector_search("document_chunks", [0.1] * 384, filters=filter_ast)

        call_kwargs = mock_manager.vector_search.call_args[1]
        sql = call_kwargs["filters"]["_sql"]
        # Field names are not quoted (per Phase 4.5.2 fix - quoting caused empty results)
        assert "status = 'active'" in sql

    @pytest.mark.asyncio
    async def test_compound_filter(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Compound AND filter is translated."""
        mock_manager.vector_search.return_value = []

        filter_ast = and_(eq("status", "active"), gt("score", 0.5))
        await adapter.vector_search("document_chunks", [0.1] * 384, filters=filter_ast)

        call_kwargs = mock_manager.vector_search.call_args[1]
        sql = call_kwargs["filters"]["_sql"]
        assert "AND" in sql
        assert "status" in sql
        assert "score" in sql

    @pytest.mark.asyncio
    async def test_in_filter(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """IN filter is translated."""
        mock_manager.vector_search.return_value = []

        filter_ast = is_in("type", ["code", "doc"])
        await adapter.vector_search("document_chunks", [0.1] * 384, filters=filter_ast)

        call_kwargs = mock_manager.vector_search.call_args[1]
        sql = call_kwargs["filters"]["_sql"]
        assert "IN" in sql
        assert "code" in sql
        assert "doc" in sql


class TestQueryAcrossProjects:
    """Tests for query_across_projects method."""

    @pytest.mark.asyncio
    async def test_query_across_projects_basic(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Query across projects calls manager correctly."""
        mock_manager.query_across_projects.return_value = [
            {"id": "1", "name": "entity1"},
            {"id": "2", "name": "entity2"},
        ]

        result = await adapter.query_across_projects(
            table_name="graph_entities",
            project_ids=["proj1", "proj2"],
            filters={"status": "active"},
            limit=50,
        )

        mock_manager.query_across_projects.assert_called_once_with(
            table_name="graph_entities",
            filters={"status": "active"},
            limit=50,
            project_ids=["proj1", "proj2"],
        )
        assert len(result) == 2
        assert result[0]["id"] == "1"

    @pytest.mark.asyncio
    async def test_query_across_projects_no_filters(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Query across projects with no filters."""
        await adapter.query_across_projects(
            table_name="graph_entities",
            project_ids=["proj1"],
        )

        mock_manager.query_across_projects.assert_called_once_with(
            table_name="graph_entities",
            filters={},
            limit=100,
            project_ids=["proj1"],
        )

    @pytest.mark.asyncio
    async def test_list_tables(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """List tables delegates to manager."""
        result = await adapter.list_tables()

        mock_manager.list_tables.assert_called_once()
        assert "document_chunks" in result
        assert "graph_entities" in result


class TestConfigBasedWeights:
    """Tests for config-based hybrid search weights in execute()."""

    @pytest.mark.asyncio
    async def test_execute_uses_config_weights(self, mock_manager: MagicMock) -> None:
        """Execute uses weights from config when available."""
        # Create mock config with custom weights
        mock_config = MagicMock()
        mock_config.search.hybrid_search.vector_weight = 0.8
        mock_config.search.hybrid_search.fts_weight = 0.2

        adapter = LanceDBAdapter(mock_manager, config=mock_config)
        mock_manager.hybrid_search.return_value = [{"id": "1", "_score": 0.9}]

        spec = QuerySpec(
            table="document_chunks",
            vector=[0.1] * 384,
            fts_query="test query",
            limit=10,
        )

        await adapter.execute(spec)

        # Verify hybrid_search was called
        # Note: weights are passed to adapter.hybrid_search, not directly to manager
        # The manager hybrid_search doesn't receive weights directly
        mock_manager.hybrid_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_uses_default_weights_without_config(
        self, adapter: LanceDBAdapter, mock_manager: MagicMock
    ) -> None:
        """Execute uses default weights (0.7/0.3) when no config."""
        mock_manager.hybrid_search.return_value = [{"id": "1", "_score": 0.9}]

        spec = QuerySpec(
            table="document_chunks",
            vector=[0.1] * 384,
            fts_query="test query",
            limit=10,
        )

        await adapter.execute(spec)

        # Verify hybrid_search was called
        mock_manager.hybrid_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_from_config_passes_config(self, mock_manager: MagicMock) -> None:
        """from_config passes config to constructor."""
        mock_config = MagicMock()
        mock_config.search.hybrid_search.vector_weight = 0.6
        mock_config.search.hybrid_search.fts_weight = 0.4

        # Create adapter via from_config (need to mock LanceDBManager.from_config)
        from unittest.mock import patch

        with patch(
            "agentic_inquiry.database.adapters.lancedb_adapter.LanceDBManager.from_config",
            return_value=mock_manager,
        ):
            adapter = await LanceDBAdapter.from_config(mock_config)

        # Verify config is stored
        assert adapter._config is mock_config
