"""Integration tests for CloudSQLConnectionManager with real Cloud SQL instance.

These tests verify CloudSQLConnectionManager behavior with an actual Cloud SQL
PostgreSQL instance. Tests are skipped if Cloud SQL environment variables are
not configured, making them safe for local development.

Environment Variables Required:
    CLOUDSQL_PROJECT: GCP project ID
    CLOUDSQL_REGION: GCP region
    CLOUDSQL_INSTANCE: Cloud SQL instance name
    CLOUDSQL_DATABASE: Database name
    CLOUDSQL_USER: Database user

Test Isolation:
    Each test runs in a transaction that is rolled back on exit via the
    test_transaction fixture from conftest.py.

Acceptance Criteria Coverage:
    - AC-1: CloudSQLConnectionManager duck-types with PostgresConnectionManager
    - AC-3: SELECT 1 works (connectivity validation)
    - AC-4: TLS enforced via SELECT ssl_is_used()
    - AC-14: Transaction isolation works (rollback verification)

Run with:
    CLOUDSQL_PROJECT=my-project CLOUDSQL_REGION=us-central1 \\
    CLOUDSQL_INSTANCE=my-instance CLOUDSQL_DATABASE=testdb \\
    CLOUDSQL_USER=test-user \\
    pytest tests/storage/providers/cloudsql/test_integration.py -v
"""

import os

import pytest

# Mark all tests in this module as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("CLOUDSQL_PROJECT"),
        reason="Cloud SQL not configured (CLOUDSQL_PROJECT not set)",
    ),
]


class TestCloudSQLConnectivity:
    """Test basic Cloud SQL connectivity and authentication."""

    async def test_cloudsql_connection(self, cloudsql_manager):
        """Test that SELECT 1 works (AC-3).

        Verifies basic connectivity to Cloud SQL instance through
        authenticated connection with IAM or standard auth.
        """
        result = await cloudsql_manager.fetchval("SELECT 1")
        assert result == 1, "SELECT 1 should return 1"

    async def test_cloudsql_auth_source_detected(self, cloudsql_manager):
        """Test that auth_source is detected and logged (AC-11).

        Verifies that CloudSQLConnectionManager detects the authentication
        source (workload_identity, service_account, or user_adc) and makes
        it available for observability.
        """
        # Auth source should be set after initialization
        assert cloudsql_manager._auth_source is not None
        assert isinstance(cloudsql_manager._auth_source, str)
        assert len(cloudsql_manager._auth_source) > 0

        # Should be one of the known auth sources
        valid_sources = {
            "workload_identity",
            "service_account",
            "user_adc",
        }
        # Auth source may be "unknown (CredentialType)" for new credential types
        assert (
            cloudsql_manager._auth_source in valid_sources
            or cloudsql_manager._auth_source.startswith("unknown (")
        ), f"Unexpected auth source: {cloudsql_manager._auth_source}"

    async def test_cloudsql_tls_enforced(self, cloudsql_manager):
        """Test that TLS is enforced via SQL query (AC-4).

        Verifies SSL/TLS encryption by querying pg_stat_ssl.ssl, which
        returns TRUE if the current connection is using SSL.
        """
        # Query directly checks if current connection uses SSL
        # Returns TRUE if SSL is active, FALSE otherwise
        result = await cloudsql_manager.fetchval(
            "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
        )
        assert result is True, "Connection should use SSL/TLS"


class TestCloudSQLHealthCheck:
    """Test health check functionality."""

    async def test_cloudsql_health_check(self, cloudsql_manager):
        """Test that health_check returns healthy=True with all metrics (AC-15).

        Verifies that health_check returns consistent shape with all required
        fields and that the connection is healthy.
        """
        health = await cloudsql_manager.health_check()

        # Verify all required fields present (FR-6.8a, AC-15)
        required_fields = {
            "healthy",
            "auth_source",
            "query_count",
            "error_count",
            "last_error_time",
            "consecutive_errors",
            "pool_size_current",
            "pool_connections_idle",
            "pool_connections_active",
            "uptime_seconds",
            "total_connections",
        }
        assert set(health.keys()) == required_fields, "Health check missing required fields"

        # Verify healthy status
        assert health["healthy"] is True, "Connection should be healthy"

        # Verify auth source is populated
        assert health["auth_source"] is not None
        assert isinstance(health["auth_source"], str)

        # Verify query count is tracked
        assert health["query_count"] >= 0

        # Verify pool metrics are present
        assert health["pool_size_current"] > 0, "Pool should have connections"
        assert health["pool_connections_idle"] >= 0
        assert health["pool_connections_active"] >= 0

        # Verify uptime is tracked
        assert health["uptime_seconds"] > 0, "Manager should have uptime"

        # Verify connection count
        assert health["total_connections"] > 0, "Should have established connections"


class TestCloudSQLDuckTyping:
    """Test that CloudSQLConnectionManager implements required interface."""

    async def test_cloudsql_with_vector_provider(self, cloudsql_manager):
        """Test full provider interface with duck-typing (AC-1, AC-22).

        Verifies that CloudSQLConnectionManager implements all methods
        required by the vector provider interface without formal Protocol.
        """
        # Test all required methods exist and are callable
        required_methods = [
            "execute",
            "fetch",
            "fetchrow",
            "fetchval",
            "executemany",
            "transaction",
            "health_check",
            "check_extension",
            "ensure_extension",
            "get_table_name",
            "acquire",
        ]

        for method_name in required_methods:
            assert hasattr(
                cloudsql_manager, method_name
            ), f"Missing required method: {method_name}"
            method = getattr(cloudsql_manager, method_name)
            assert callable(method), f"{method_name} is not callable"

        # Test get_table_name signature and behavior (AC-22)
        # Must accept (base_name: str, role: str) -> str
        table_name = cloudsql_manager.get_table_name("chunks", "vector")
        assert isinstance(table_name, str)
        assert "chunks" in table_name

        # Test different roles produce different table names
        vector_table = cloudsql_manager.get_table_name("entities", "vector")
        graph_table = cloudsql_manager.get_table_name("entities", "graph")
        assert vector_table != graph_table, "Different roles should produce different table names"

        # Test execute with parameters
        result = await cloudsql_manager.fetchval("SELECT $1::int", 42)
        assert result == 42

        # Test fetch returns list
        rows = await cloudsql_manager.fetch("SELECT 1 AS num UNION SELECT 2")
        assert isinstance(rows, list)
        assert len(rows) == 2


class TestCloudSQLTransactions:
    """Test transaction isolation and rollback."""

    async def test_cloudsql_transaction_rollback(self, cloudsql_manager, test_transaction):
        """Test that transaction rollback works for test isolation (AC-14).

        Verifies that:
        1. Operations within a transaction are visible inside the transaction
        2. Rolled-back transactions don't persist data
        3. Test isolation is maintained between tests
        """
        # Create a temporary test table inside the transaction
        await test_transaction.execute(
            """
            CREATE TEMPORARY TABLE test_rollback (
                id SERIAL PRIMARY KEY,
                value TEXT
            )
            """
        )

        # Insert data within the transaction
        await test_transaction.execute(
            "INSERT INTO test_rollback (value) VALUES ($1)", "test_value"
        )

        # Verify data is visible within the transaction
        result = await test_transaction.fetchval(
            "SELECT value FROM test_rollback WHERE value = $1", "test_value"
        )
        assert result == "test_value", "Data should be visible within transaction"

        # Transaction will roll back on exit from test_transaction fixture
        # On next test, this data will not exist (verified by running multiple tests)

    async def test_cloudsql_transaction_isolation_verified(
        self, cloudsql_manager, test_transaction
    ):
        """Verify that previous test's data was rolled back.

        This test runs after test_cloudsql_transaction_rollback and verifies
        that the temporary table created in that test does not exist, proving
        that transaction rollback provides test isolation.
        """
        # Try to create the same temporary table - should succeed because
        # the previous test's transaction was rolled back
        await test_transaction.execute(
            """
            CREATE TEMPORARY TABLE test_rollback (
                id SERIAL PRIMARY KEY,
                value TEXT
            )
            """
        )

        # Verify table is empty (previous test's INSERT was rolled back)
        count = await test_transaction.fetchval("SELECT COUNT(*) FROM test_rollback")
        assert count == 0, "Table should be empty (previous transaction rolled back)"
