"""Fixtures for stress and concurrency tests.

These tests verify behavior under load and concurrent access.
They help identify race conditions and resource contention issues.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def stress_config() -> dict[str, Any]:
    """Configuration for stress tests."""
    return {
        "concurrent_operations": 50,
        "batch_size": 100,
        "timeout_seconds": 30,
        "max_memory_mb": 512,
    }


@pytest.fixture
def concurrent_semaphore(stress_config) -> asyncio.Semaphore:
    """Semaphore to control concurrency level."""
    return asyncio.Semaphore(stress_config["concurrent_operations"])


@pytest_asyncio.fixture
async def stress_test_storage(mock_db_manager, mock_temp_config):
    """Create a storage instance for stress testing.

    This fixture creates an isolated storage instance that can
    handle concurrent operations without affecting other tests.
    """
    from agentic_inquiry.storage.facade import StorageFacade
    from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter

    adapter = LanceDBAdapter(mock_db_manager)
    facade = StorageFacade(
        config=mock_temp_config,
        project_id="stress_test",
        vector_provider=adapter,
        graph_provider=adapter,
    )

    return facade
