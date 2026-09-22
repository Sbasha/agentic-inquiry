"""Fixtures for Cloud SQL integration tests.

This module provides pytest fixtures for testing CloudSQLConnectionManager
with real Cloud SQL instances. Tests are skipped if Cloud SQL environment
variables are not configured.

Required Environment Variables:
    CLOUDSQL_PROJECT: GCP project ID
    CLOUDSQL_REGION: GCP region (e.g., us-central1)
    CLOUDSQL_INSTANCE: Cloud SQL instance name
    CLOUDSQL_DATABASE: Database name
    CLOUDSQL_USER: Database user (IAM or standard)

Authentication:
    Tests use Application Default Credentials (ADC) only.
    DO NOT set GOOGLE_APPLICATION_CREDENTIALS - use Workload Identity Federation.

    Local dev: gcloud auth application-default login
    GKE/Cloud Run: Workload Identity (automatic)
    CI: Workload Identity Federation

Test Isolation:
    Each test runs in a transaction that is rolled back on exit,
    ensuring no persistent state between tests.
"""

import os

import pytest
import pytest_asyncio

from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.cloudsql.connection import CloudSQLConnectionManager


# Skip all tests in this module if Cloud SQL is not configured
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("CLOUDSQL_PROJECT"),
        reason="Cloud SQL not configured (CLOUDSQL_PROJECT not set)",
    ),
]


@pytest_asyncio.fixture
async def cloudsql_manager():
    """Create and initialize CloudSQLConnectionManager.

    Creates a manager from environment variables and ensures it's initialized
    before yielding. Closes cleanly on teardown.

    Yields:
        CloudSQLConnectionManager: Initialized connection manager
    """
    config = BackendConfig(
        type="cloudsql",
        project=os.environ["CLOUDSQL_PROJECT"],
        region=os.environ["CLOUDSQL_REGION"],
        instance=os.environ["CLOUDSQL_INSTANCE"],
        database=os.environ["CLOUDSQL_DATABASE"],
        user=os.environ["CLOUDSQL_USER"],
    )

    manager = CloudSQLConnectionManager.from_config(config)
    await manager.initialize()

    yield manager

    await manager.close()


@pytest_asyncio.fixture
async def test_transaction(cloudsql_manager):
    """Wrap each test in a transaction for isolation.

    All operations within the test run in a transaction that is rolled back
    on exit, ensuring no persistent state between tests. This allows tests
    to safely insert, update, or delete data without affecting other tests.

    Usage:
        async def test_something(test_transaction):
            await test_transaction.execute("INSERT INTO test VALUES (1)")
            # Transaction automatically rolls back on exit

    Args:
        cloudsql_manager: The initialized connection manager

    Yields:
        asyncpg.Connection: Connection with active transaction
    """
    async with cloudsql_manager.transaction() as txn:
        yield txn
        # Transaction automatically rolls back on exit (no explicit rollback needed)
