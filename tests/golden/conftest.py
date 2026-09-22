"""Fixtures for Golden Set regression tests.

These tests verify search quality doesn't regress by testing
against a fixed dataset with expected results.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def golden_dataset_path() -> Path:
    """Path to the golden dataset directory."""
    return Path(__file__).parent / "dataset"


@pytest.fixture(scope="session")
def golden_queries_path() -> Path:
    """Path to the golden queries file."""
    return Path(__file__).parent / "queries.json"


@pytest.fixture(scope="session")
def golden_queries(golden_queries_path: Path) -> list[dict[str, Any]]:
    """Load golden queries with expected results."""
    if not golden_queries_path.exists():
        pytest.skip("Golden queries file not found")

    with open(golden_queries_path) as f:
        data = json.load(f)

    return data.get("queries", [])


@pytest_asyncio.fixture
async def golden_indexed_storage(mock_db_manager, mock_temp_config, mock_embedding_registry, golden_dataset_path):
    """Create a storage instance with the golden dataset indexed.

    This fixture indexes the golden dataset and returns a storage
    instance ready for search queries.
    """
    from agent_vault.indexing.pipeline import IndexingPipeline
    from agent_vault.storage.facade import StorageFacade
    from agent_vault.database.adapters.lancedb_adapter import LanceDBAdapter

    # Skip if dataset doesn't exist
    if not golden_dataset_path.exists():
        pytest.skip("Golden dataset not found")

    # Create pipeline and index the dataset
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=mock_temp_config,
        project_id="golden_test",
        registry=mock_embedding_registry
    )

    # Index the golden dataset
    await pipeline.index_directory(str(golden_dataset_path))

    # Create and return storage facade
    adapter = LanceDBAdapter(mock_db_manager)
    facade = StorageFacade(
        config=mock_temp_config,
        project_id="golden_test",
        vector_provider=adapter,
        graph_provider=adapter,
    )

    return facade


@pytest.fixture
def golden_deduplicator():
    """Create a deduplicator that passes through all results."""
    dedup = MagicMock()
    # Pass through results without deduplication for golden tests
    dedup.deduplicate_results.side_effect = lambda results, *args, **kwargs: results
    return dedup


@pytest_asyncio.fixture
async def golden_search_service(golden_indexed_storage, mock_temp_config, golden_deduplicator):
    """Create a HybridSearchService for golden tests."""
    from agent_vault.search.hybrid_search import HybridSearchService

    return HybridSearchService(
        storage=golden_indexed_storage,
        config=mock_temp_config,
        deduplicator=golden_deduplicator,
        project_id="golden_test",
    )
