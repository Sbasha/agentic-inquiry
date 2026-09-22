"""Tests for database protocol definitions.

Tests cover:
- Protocol structural typing (runtime checkable)
- Capability detection helpers
- Protocol compliance verification
"""
import pytest

pytestmark = pytest.mark.unit
from typing import Any, Dict, List, Optional, Sequence

from agent_vault.database.protocols import (
    BatchCapability,
    FTSCapability,
    GraphRankingCapability,
    HybridSearchCapability,
    TransactionCapability,
    VectorSearchCapability,
    VectorStorageProtocol,
    has_batch,
    has_fts,
    has_graph_ranking,
    has_hybrid_search,
    has_transactions,
    has_vector_search,
)
from agent_vault.database.filters import Filter
from agent_vault.database.query_spec import QuerySpec
from agent_vault.database.results import SearchResult


# =============================================================================
# Mock Implementations for Testing
# =============================================================================


class MinimalAdapter:
    """Adapter implementing only VectorStorageProtocol."""

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def add(
        self,
        table: str,
        records: Sequence[Dict[str, Any]],
    ) -> None:
        pass

    async def delete(
        self,
        table: str,
        ids: Sequence[str],
    ) -> int:
        return len(ids)

    async def get_by_ids(
        self,
        table: str,
        ids: Sequence[str],
    ) -> List[Dict[str, Any]]:
        return []

    async def upsert(
        self,
        table: str,
        records: Sequence[Dict[str, Any]],
        key_field: str = "id",
    ) -> None:
        pass

    async def execute(
        self,
        spec: QuerySpec,
    ) -> List[SearchResult]:
        return []

    async def table_exists(self, table: str) -> bool:
        return True

    async def count(
        self,
        table: str,
        filters: Optional[Filter] = None,
    ) -> int:
        return 0


class FullFeaturedAdapter(MinimalAdapter):
    """Adapter implementing all capabilities."""

    async def vector_search(
        self,
        table: str,
        vector: List[float],
        limit: int = 10,
        filters: Optional[Filter] = None,
        vector_column: str = "vector",
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        return []

    async def fts_search(
        self,
        table: str,
        query: str,
        limit: int = 10,
        filters: Optional[Filter] = None,
        fts_columns: Optional[List[str]] = None,
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        return []

    async def hybrid_search(
        self,
        table: str,
        vector: List[float],
        query: str,
        limit: int = 10,
        filters: Optional[Filter] = None,
        vector_column: str = "vector",
        fts_columns: Optional[List[str]] = None,
        vector_weight: float = 0.7,
        fts_weight: float = 0.3,
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        return []

    async def has_graph_ranking(self, table: str) -> bool:
        return True

    async def apply_graph_boost(
        self,
        results: List[SearchResult],
        table: str,
        boost_factor: float = 0.1,
    ) -> List[SearchResult]:
        return results

    async def add_batch(
        self,
        table: str,
        records: Sequence[Dict[str, Any]],
        batch_size: int = 1000,
    ) -> int:
        return len(records)

    async def delete_batch(
        self,
        table: str,
        filters: Filter,
        batch_size: int = 1000,
    ) -> int:
        return 0

    async def begin_transaction(self) -> Any:
        return "txn_123"

    async def commit_transaction(self, transaction: Any) -> None:
        pass

    async def rollback_transaction(self, transaction: Any) -> None:
        pass


class VectorOnlyAdapter(MinimalAdapter):
    """Adapter with only vector search capability."""

    async def vector_search(
        self,
        table: str,
        vector: List[float],
        limit: int = 10,
        filters: Optional[Filter] = None,
        vector_column: str = "vector",
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        return []


class FTSOnlyAdapter(MinimalAdapter):
    """Adapter with only FTS capability."""

    async def fts_search(
        self,
        table: str,
        query: str,
        limit: int = 10,
        filters: Optional[Filter] = None,
        fts_columns: Optional[List[str]] = None,
        project_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        return []


# =============================================================================
# VectorStorageProtocol Tests
# =============================================================================


class TestVectorStorageProtocol:
    """Tests for VectorStorageProtocol."""

    def test_minimal_adapter_is_instance(self) -> None:
        """MinimalAdapter should satisfy VectorStorageProtocol."""
        adapter = MinimalAdapter()
        assert isinstance(adapter, VectorStorageProtocol)

    def test_full_adapter_is_instance(self) -> None:
        """FullFeaturedAdapter should satisfy VectorStorageProtocol."""
        adapter = FullFeaturedAdapter()
        assert isinstance(adapter, VectorStorageProtocol)

    def test_object_is_not_instance(self) -> None:
        """Plain object should not satisfy VectorStorageProtocol."""
        assert not isinstance(object(), VectorStorageProtocol)

    def test_dict_is_not_instance(self) -> None:
        """Dict should not satisfy VectorStorageProtocol."""
        assert not isinstance({}, VectorStorageProtocol)

    def test_incomplete_class_is_not_instance(self) -> None:
        """Class missing methods should not satisfy protocol."""

        class IncompleteAdapter:
            async def initialize(self) -> None:
                pass
            # Missing other required methods

        assert not isinstance(IncompleteAdapter(), VectorStorageProtocol)


# =============================================================================
# VectorSearchCapability Tests
# =============================================================================


class TestVectorSearchCapability:
    """Tests for VectorSearchCapability."""

    def test_full_adapter_has_capability(self) -> None:
        """FullFeaturedAdapter should have vector search."""
        adapter = FullFeaturedAdapter()
        assert isinstance(adapter, VectorSearchCapability)

    def test_vector_only_adapter_has_capability(self) -> None:
        """VectorOnlyAdapter should have vector search."""
        adapter = VectorOnlyAdapter()
        assert isinstance(adapter, VectorSearchCapability)

    def test_minimal_adapter_lacks_capability(self) -> None:
        """MinimalAdapter should NOT have vector search."""
        adapter = MinimalAdapter()
        assert not isinstance(adapter, VectorSearchCapability)

    def test_fts_only_adapter_lacks_capability(self) -> None:
        """FTSOnlyAdapter should NOT have vector search."""
        adapter = FTSOnlyAdapter()
        assert not isinstance(adapter, VectorSearchCapability)


# =============================================================================
# FTSCapability Tests
# =============================================================================


class TestFTSCapability:
    """Tests for FTSCapability."""

    def test_full_adapter_has_capability(self) -> None:
        """FullFeaturedAdapter should have FTS."""
        adapter = FullFeaturedAdapter()
        assert isinstance(adapter, FTSCapability)

    def test_fts_only_adapter_has_capability(self) -> None:
        """FTSOnlyAdapter should have FTS."""
        adapter = FTSOnlyAdapter()
        assert isinstance(adapter, FTSCapability)

    def test_minimal_adapter_lacks_capability(self) -> None:
        """MinimalAdapter should NOT have FTS."""
        adapter = MinimalAdapter()
        assert not isinstance(adapter, FTSCapability)

    def test_vector_only_adapter_lacks_capability(self) -> None:
        """VectorOnlyAdapter should NOT have FTS."""
        adapter = VectorOnlyAdapter()
        assert not isinstance(adapter, FTSCapability)


# =============================================================================
# HybridSearchCapability Tests
# =============================================================================


class TestHybridSearchCapability:
    """Tests for HybridSearchCapability."""

    def test_full_adapter_has_capability(self) -> None:
        """FullFeaturedAdapter should have hybrid search."""
        adapter = FullFeaturedAdapter()
        assert isinstance(adapter, HybridSearchCapability)

    def test_minimal_adapter_lacks_capability(self) -> None:
        """MinimalAdapter should NOT have hybrid search."""
        adapter = MinimalAdapter()
        assert not isinstance(adapter, HybridSearchCapability)

    def test_vector_only_adapter_lacks_capability(self) -> None:
        """VectorOnlyAdapter should NOT have hybrid search."""
        adapter = VectorOnlyAdapter()
        assert not isinstance(adapter, HybridSearchCapability)


# =============================================================================
# GraphRankingCapability Tests
# =============================================================================


class TestGraphRankingCapability:
    """Tests for GraphRankingCapability."""

    def test_full_adapter_has_capability(self) -> None:
        """FullFeaturedAdapter should have graph ranking."""
        adapter = FullFeaturedAdapter()
        assert isinstance(adapter, GraphRankingCapability)

    def test_minimal_adapter_lacks_capability(self) -> None:
        """MinimalAdapter should NOT have graph ranking."""
        adapter = MinimalAdapter()
        assert not isinstance(adapter, GraphRankingCapability)


# =============================================================================
# BatchCapability Tests
# =============================================================================


class TestBatchCapability:
    """Tests for BatchCapability."""

    def test_full_adapter_has_capability(self) -> None:
        """FullFeaturedAdapter should have batch operations."""
        adapter = FullFeaturedAdapter()
        assert isinstance(adapter, BatchCapability)

    def test_minimal_adapter_lacks_capability(self) -> None:
        """MinimalAdapter should NOT have batch operations."""
        adapter = MinimalAdapter()
        assert not isinstance(adapter, BatchCapability)


# =============================================================================
# TransactionCapability Tests
# =============================================================================


class TestTransactionCapability:
    """Tests for TransactionCapability."""

    def test_full_adapter_has_capability(self) -> None:
        """FullFeaturedAdapter should have transactions."""
        adapter = FullFeaturedAdapter()
        assert isinstance(adapter, TransactionCapability)

    def test_minimal_adapter_lacks_capability(self) -> None:
        """MinimalAdapter should NOT have transactions."""
        adapter = MinimalAdapter()
        assert not isinstance(adapter, TransactionCapability)


# =============================================================================
# Capability Helper Function Tests
# =============================================================================


class TestCapabilityHelpers:
    """Tests for capability detection helper functions."""

    def test_has_vector_search_true(self) -> None:
        """has_vector_search should return True for capable adapters."""
        assert has_vector_search(FullFeaturedAdapter()) is True
        assert has_vector_search(VectorOnlyAdapter()) is True

    def test_has_vector_search_false(self) -> None:
        """has_vector_search should return False for incapable adapters."""
        assert has_vector_search(MinimalAdapter()) is False
        assert has_vector_search(FTSOnlyAdapter()) is False

    def test_has_fts_true(self) -> None:
        """has_fts should return True for capable adapters."""
        assert has_fts(FullFeaturedAdapter()) is True
        assert has_fts(FTSOnlyAdapter()) is True

    def test_has_fts_false(self) -> None:
        """has_fts should return False for incapable adapters."""
        assert has_fts(MinimalAdapter()) is False
        assert has_fts(VectorOnlyAdapter()) is False

    def test_has_hybrid_search_true(self) -> None:
        """has_hybrid_search should return True for capable adapters."""
        assert has_hybrid_search(FullFeaturedAdapter()) is True

    def test_has_hybrid_search_false(self) -> None:
        """has_hybrid_search should return False for incapable adapters."""
        assert has_hybrid_search(MinimalAdapter()) is False
        assert has_hybrid_search(VectorOnlyAdapter()) is False
        assert has_hybrid_search(FTSOnlyAdapter()) is False

    def test_has_graph_ranking_true(self) -> None:
        """has_graph_ranking should return True for capable adapters."""
        assert has_graph_ranking(FullFeaturedAdapter()) is True

    def test_has_graph_ranking_false(self) -> None:
        """has_graph_ranking should return False for incapable adapters."""
        assert has_graph_ranking(MinimalAdapter()) is False

    def test_has_batch_true(self) -> None:
        """has_batch should return True for capable adapters."""
        assert has_batch(FullFeaturedAdapter()) is True

    def test_has_batch_false(self) -> None:
        """has_batch should return False for incapable adapters."""
        assert has_batch(MinimalAdapter()) is False

    def test_has_transactions_true(self) -> None:
        """has_transactions should return True for capable adapters."""
        assert has_transactions(FullFeaturedAdapter()) is True

    def test_has_transactions_false(self) -> None:
        """has_transactions should return False for incapable adapters."""
        assert has_transactions(MinimalAdapter()) is False


# =============================================================================
# Capability Composition Tests
# =============================================================================


class TestCapabilityComposition:
    """Tests for various capability combinations."""

    def test_vector_and_fts_without_hybrid(self) -> None:
        """Adapter can have vector + FTS without native hybrid."""

        class VectorAndFTSAdapter(MinimalAdapter):
            async def vector_search(
                self, table: str, vector: List[float], **kwargs: Any
            ) -> List[SearchResult]:
                return []

            async def fts_search(
                self, table: str, query: str, **kwargs: Any
            ) -> List[SearchResult]:
                return []

        adapter = VectorAndFTSAdapter()
        assert has_vector_search(adapter) is True
        assert has_fts(adapter) is True
        assert has_hybrid_search(adapter) is False  # App layer handles merging

    def test_all_search_capabilities(self) -> None:
        """Adapter can have all search capabilities."""
        adapter = FullFeaturedAdapter()
        assert has_vector_search(adapter) is True
        assert has_fts(adapter) is True
        assert has_hybrid_search(adapter) is True
        assert has_graph_ranking(adapter) is True

    def test_protocol_inheritance_check(self) -> None:
        """Capability protocols don't inherit from VectorStorageProtocol."""
        # This ensures adapters must explicitly implement the core protocol
        adapter = FullFeaturedAdapter()
        assert isinstance(adapter, VectorStorageProtocol)
        # Capabilities are separate concerns
        assert isinstance(adapter, VectorSearchCapability)
        assert isinstance(adapter, FTSCapability)


# =============================================================================
# Async Method Signature Tests
# =============================================================================


class TestAsyncMethodSignatures:
    """Tests that protocol methods are async."""

    @pytest.mark.asyncio
    async def test_minimal_adapter_async_methods(self) -> None:
        """MinimalAdapter methods should be async."""
        adapter = MinimalAdapter()

        # All core methods should be awaitable
        await adapter.initialize()
        await adapter.close()
        await adapter.add("test", [])
        await adapter.delete("test", [])
        await adapter.get_by_ids("test", [])
        await adapter.upsert("test", [])
        await adapter.execute(QuerySpec(table="test"))
        await adapter.table_exists("test")
        await adapter.count("test")

    @pytest.mark.asyncio
    async def test_full_adapter_async_methods(self) -> None:
        """FullFeaturedAdapter methods should be async."""
        adapter = FullFeaturedAdapter()

        # Search capabilities
        await adapter.vector_search("test", [0.1] * 384)
        await adapter.fts_search("test", "query")
        await adapter.hybrid_search("test", [0.1] * 384, "query")

        # Graph ranking
        await adapter.has_graph_ranking("test")
        await adapter.apply_graph_boost([], "test")

        # Batch operations
        await adapter.add_batch("test", [])
        from agent_vault.database.filters import eq
        await adapter.delete_batch("test", eq("id", "1"))

        # Transactions
        txn = await adapter.begin_transaction()
        await adapter.commit_transaction(txn)
        await adapter.rollback_transaction(txn)
