"""Unit tests for CloudSQLConnectionManager with mocked Google libraries.

These tests verify the CloudSQLConnectionManager behavior without requiring actual
GCP credentials or Cloud SQL instances by mocking google.auth and Connector.

Run with: pytest tests/storage/providers/cloudsql/test_connection.py -v
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Skip all tests if CloudSQL connector is not installed
try:
    import google.cloud.sql.connector  # noqa: F401
    HAS_CLOUDSQL = True
except ImportError:
    HAS_CLOUDSQL = False

if not HAS_CLOUDSQL:
    pytest.skip(
        "Skipping CloudSQL tests: google-cloud-sql-connector not installed",
        allow_module_level=True,
    )

from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.cloudsql.connection import CloudSQLConnectionManager
from agent_vault.storage.providers.cloudsql.errors import CloudSQLError, CloudSQLErrorCode


# Mark all tests in this module as unit tests
pytestmark = [pytest.mark.unit]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def valid_config():
    """Create a valid Cloud SQL configuration."""
    return BackendConfig(
        type="cloudsql",
        project="test-project",
        region="us-central1",
        instance="test-instance",
        database="test_db",  # Use underscore, not hyphen (per GCP naming rules)
        user="test-user",
        pool_size=10,
        max_overflow=5,
        table_prefix="agv_test_",
    )


@pytest.fixture
def mock_credentials():
    """Create mock google.auth credentials."""
    creds = MagicMock()
    creds.__class__.__name__ = "UserCredentials"
    return creds


@pytest.fixture
def mock_asyncpg_pool():
    """Create a mock asyncpg pool with all required methods."""
    pool = AsyncMock()
    pool.get_size = Mock(return_value=5)
    pool.get_idle_size = Mock(return_value=3)
    
    # Mock connection
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_conn.execute = AsyncMock(return_value="OK")
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.executemany = AsyncMock()
    
    # Mock transaction context manager
    mock_transaction = AsyncMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = Mock(return_value=mock_transaction)
    
    # Mock pool.acquire() context manager
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = Mock(return_value=mock_acquire)
    
    pool.close = AsyncMock()
    
    return pool


@pytest.fixture
def mock_connector():
    """Create a mock Cloud SQL Connector."""
    connector = MagicMock()
    connector.connect_async = AsyncMock()
    connector.close_async = AsyncMock()
    return connector


# =============================================================================
# Initialization Tests
# =============================================================================


class TestInitialization:
    """Test CloudSQLConnectionManager initialization."""

    async def test_init_logs_auth_source(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector, caplog
    ):
        """Test that initialize logs the authentication source at INFO level (AC-11)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        # Verify auth source was logged at INFO level (FR-5.9a, AC-11)
        assert any(
            "Cloud SQL auth source:" in record.message and record.levelname == "INFO"
            for record in caplog.records
        )
        assert manager._auth_source == "user_adc"

    async def test_init_fails_fast_on_auth_error(self, valid_config):
        """Test that initialize raises CloudSQLError on auth failure (AC-24)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default") as mock_auth:
            import google.auth.exceptions
            mock_auth.side_effect = google.auth.exceptions.DefaultCredentialsError("ADC not configured")
            
            with pytest.raises(CloudSQLError) as exc_info:
                await manager.initialize()
            
            # Verify correct error code (AC-24)
            assert exc_info.value.code == CloudSQLErrorCode.AUTH_FAILED
            assert "AUTH_001" in str(exc_info.value)
            assert exc_info.value.error_id  # Has error ID (AC-12)

    async def test_init_fails_fast_on_connection_error(
        self, valid_config, mock_credentials, mock_connector
    ):
        """Test that initialize raises CloudSQLError on connection failure (AC-27)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                # Mock pool creation to fail
                with patch("asyncpg.create_pool") as mock_create_pool:
                    mock_create_pool.side_effect = Exception("Connection refused")
                    
                    with pytest.raises(CloudSQLError) as exc_info:
                        await manager.initialize()
                    
                    # Verify correct error code (AC-27)
                    assert exc_info.value.code == CloudSQLErrorCode.STARTUP_FAILED
                    assert exc_info.value.error_id  # Has error ID (AC-12)

    async def test_pool_recycling_lifetime(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that pool is configured with max_inactive_connection_lifetime=3300 (AC-5b)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool) as mock_create_pool:
                    await manager.initialize()
                    
                    # Verify pool was created with correct recycling parameter (FR-6.2a, AC-5b)
                    mock_create_pool.assert_called_once()
                    call_kwargs = mock_create_pool.call_args.kwargs
                    assert call_kwargs["max_inactive_connection_lifetime"] == 3300

    async def test_select_1_has_timeout(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that SELECT 1 validation uses asyncio.wait_for with 5 second timeout (AC-18)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        # Track if wait_for was called
        original_wait_for = asyncio.wait_for
        wait_for_calls = []
        
        async def mock_wait_for(coro, timeout=None):
            wait_for_calls.append(timeout)
            return await original_wait_for(coro, timeout=timeout)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    with patch("asyncio.wait_for", side_effect=mock_wait_for):
                        await manager.initialize()
        
        # Verify SELECT 1 was called with 5 second timeout (FR-3.5, AC-18)
        assert 5.0 in wait_for_calls

    async def test_init_total_timeout(self, valid_config, mock_credentials, mock_connector):
        """Test that initialization has a 30 second total timeout (AC-28)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        # Mock a slow connection that exceeds the timeout
        async def slow_create_pool(*args, **kwargs):
            await asyncio.sleep(35)  # Exceed 30 second timeout
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", side_effect=slow_create_pool):
                    start = time.time()
                    with pytest.raises(CloudSQLError) as exc_info:
                        await manager.initialize()
                    elapsed = time.time() - start
                    
                    # Should timeout around 30 seconds, not 35
                    assert elapsed < 32  # Allow 2 second buffer
                    assert exc_info.value.code == CloudSQLErrorCode.STARTUP_FAILED
                    assert "timeout" in str(exc_info.value).lower()


# =============================================================================
# Connection Acquisition Tests
# =============================================================================


class TestConnectionAcquisition:
    """Test connection acquisition and error handling."""

    async def test_acquire_raises_if_not_initialized(self, valid_config):
        """Test that acquire raises CloudSQLError if not initialized (AC-27)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        # Don't initialize - should raise
        with pytest.raises(CloudSQLError) as exc_info:
            async with manager.acquire():
                pass
        
        assert exc_info.value.code == CloudSQLErrorCode.STARTUP_FAILED

    async def test_acquire_timeout_configurable(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that acquire timeout parameter is respected (AC-26)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        # Mock pool.acquire to hang indefinitely
        async def hanging_acquire():
            await asyncio.sleep(100)
        
        mock_acquire_ctx = AsyncMock()
        mock_acquire_ctx.__aenter__ = AsyncMock(side_effect=hanging_acquire)
        mock_acquire_ctx.__aexit__ = AsyncMock()
        manager._pool.acquire = Mock(return_value=mock_acquire_ctx)
        
        # Test with custom timeout
        start = time.time()
        with pytest.raises(CloudSQLError) as exc_info:
            async with manager.acquire(timeout=0.5):
                pass
        elapsed = time.time() - start
        
        # Should timeout around 0.5 seconds
        assert elapsed < 1.0
        assert exc_info.value.code == CloudSQLErrorCode.CONNECTION_FAILED
        assert "timeout" in str(exc_info.value).lower()


# =============================================================================
# Query Method Tests
# =============================================================================


class TestQueryMethods:
    """Test query execution methods with error wrapping."""

    @pytest.fixture
    async def initialized_manager(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Create an initialized manager for query tests."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        return manager

    async def test_query_errors_wrapped(self, initialized_manager):
        """Test that query errors are wrapped in CloudSQLError (FR-6.5, AC-13)."""
        # Mock connection to raise an error
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("Database error"))
        
        mock_acquire_ctx = AsyncMock()
        mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_ctx.__aexit__ = AsyncMock()
        initialized_manager._pool.acquire = Mock(return_value=mock_acquire_ctx)
        
        with pytest.raises(CloudSQLError) as exc_info:
            await initialized_manager.execute("SELECT 1")
        
        # Verify error is wrapped correctly
        assert exc_info.value.code == CloudSQLErrorCode.QUERY_FAILED
        assert exc_info.value.error_id  # Has error ID
        # Verify internal details not exposed (AC-13)
        assert "Database error" not in str(exc_info.value)  # Original error not in user message

    async def test_execute_increments_query_count(self, initialized_manager):
        """Test that execute increments query count."""
        initial_count = initialized_manager._query_count
        await initialized_manager.execute("SELECT 1")
        assert initialized_manager._query_count == initial_count + 1

    async def test_fetch_increments_query_count(self, initialized_manager):
        """Test that fetch increments query count."""
        initial_count = initialized_manager._query_count
        await initialized_manager.fetch("SELECT 1")
        assert initialized_manager._query_count == initial_count + 1

    async def test_fetchrow_increments_query_count(self, initialized_manager):
        """Test that fetchrow increments query count."""
        initial_count = initialized_manager._query_count
        await initialized_manager.fetchrow("SELECT 1")
        assert initialized_manager._query_count == initial_count + 1

    async def test_fetchval_increments_query_count(self, initialized_manager):
        """Test that fetchval increments query count."""
        initial_count = initialized_manager._query_count
        await initialized_manager.fetchval("SELECT 1")
        assert initialized_manager._query_count == initial_count + 1

    async def test_executemany_increments_query_count_by_batch_size(self, initialized_manager):
        """Test that executemany increments query count by number of parameter sets."""
        initial_count = initialized_manager._query_count
        await initialized_manager.executemany("INSERT INTO test VALUES ($1)", [(1,), (2,), (3,)])
        assert initialized_manager._query_count == initial_count + 3


# =============================================================================
# Health Check Tests
# =============================================================================


class TestHealthCheck:
    """Test health check functionality."""

    async def test_health_check_returns_consistent_shape_success(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that health_check returns consistent shape on success (AC-15)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        health = await manager.health_check()
        
        # Verify consistent shape (FR-6.8a, AC-15)
        assert "healthy" in health
        assert health["healthy"] is True
        assert "auth_source" in health
        assert "query_count" in health
        assert "error_count" in health
        assert "last_error_time" in health
        assert "consecutive_errors" in health
        assert "pool_size_current" in health
        assert "pool_connections_idle" in health
        assert "pool_connections_active" in health
        assert "uptime_seconds" in health
        assert "total_connections" in health

    async def test_health_check_returns_consistent_shape_failure(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that health_check returns consistent shape on failure (AC-15)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        # Mock fetchval to raise an error
        manager.fetchval = AsyncMock(side_effect=Exception("Connection lost"))
        
        health = await manager.health_check()
        
        # Verify consistent shape even on failure (FR-6.8a)
        assert "healthy" in health
        assert health["healthy"] is False
        assert "auth_source" in health
        assert "query_count" in health
        assert "error_count" in health
        assert "last_error_time" in health
        assert "consecutive_errors" in health
        assert "pool_size_current" in health
        assert "pool_connections_idle" in health
        assert "pool_connections_active" in health
        assert "uptime_seconds" in health
        assert "total_connections" in health

    async def test_health_check_when_not_initialized(self, valid_config):
        """Test that health_check returns consistent shape when not initialized."""
        manager = CloudSQLConnectionManager(valid_config)
        
        health = await manager.health_check()
        
        # Should return consistent shape with healthy=False
        assert health["healthy"] is False
        assert "auth_source" in health
        assert "query_count" in health
        assert health["pool_size_current"] == 0


# =============================================================================
# Duck-Typing Interface Tests
# =============================================================================


class TestDuckTypingInterface:
    """Test that CloudSQLConnectionManager implements required interface."""

    async def test_get_table_name_matches_postgres_signature(self, valid_config):
        """Test that get_table_name has correct signature matching PostgresConnectionManager (AC-22)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        # Test signature: get_table_name(base_name: str, role: str) -> str
        # Note: role parameter is required (not optional with default empty string)
        result = manager.get_table_name("chunks", "vector")
        assert result == "agv_test_v_chunks"
        
        result = manager.get_table_name("entities", "graph")
        assert result == "agv_test_g_entities"
        
        result = manager.get_table_name("events", "events")
        assert result == "agv_test_e_events"
        
        result = manager.get_table_name("file_hashes", "file_tracker")
        assert result == "agv_test_f_file_hashes"

    def test_all_required_methods_exist(self, valid_config):
        """Test that all required methods exist for duck-typing (AC-22)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        # Verify all required methods exist (AC-1, FR-1.4)
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
            assert hasattr(manager, method_name), f"Missing required method: {method_name}"
            method = getattr(manager, method_name)
            assert callable(method), f"{method_name} is not callable"


# =============================================================================
# Additional Tests
# =============================================================================


class TestAdditionalBehavior:
    """Test additional CloudSQLConnectionManager behavior."""

    async def test_transaction_context_manager(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that transaction() works as a context manager."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        async with manager.transaction() as conn:
            assert conn is not None

    async def test_close_is_idempotent(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that close() can be called multiple times safely."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        # Close multiple times - should not raise
        await manager.close()
        await manager.close()
        await manager.close()
        
        assert not manager.is_initialized

    async def test_context_manager_protocol(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that CloudSQLConnectionManager works as async context manager."""
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    async with CloudSQLConnectionManager(valid_config) as manager:
                        assert manager.is_initialized
                    
                    # Should be closed after exiting context
                    assert not manager.is_initialized

    def test_repr_does_not_expose_sensitive_data(self, valid_config):
        """Test that __repr__ doesn't expose credentials (AC-13)."""
        manager = CloudSQLConnectionManager(valid_config)
        
        repr_str = repr(manager)
        
        # Should not expose user credentials
        assert "test-user" not in repr_str
        # Should include instance info
        assert "test-instance" in repr_str
        assert "test-project" in repr_str

    async def test_check_extension_returns_bool(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that check_extension returns boolean."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        # Mock fetchval to return True
        manager.fetchval = AsyncMock(return_value=True)
        
        result = await manager.check_extension("vector")
        assert result is True
        
        manager.fetchval = AsyncMock(return_value=False)
        result = await manager.check_extension("nonexistent")
        assert result is False

    async def test_ensure_extension_creates_if_missing(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that ensure_extension creates extension if missing."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        # Mock extension doesn't exist, then does after creation
        check_results = [False, True]
        manager.check_extension = AsyncMock(side_effect=check_results)
        manager.execute = AsyncMock()
        
        await manager.ensure_extension("vector")
        
        # Should have called execute to create extension
        manager.execute.assert_called_once()

    async def test_consecutive_errors_resets_on_success(
        self, valid_config, mock_credentials, mock_asyncpg_pool, mock_connector
    ):
        """Test that consecutive_errors counter resets on successful query."""
        manager = CloudSQLConnectionManager(valid_config)
        
        with patch("google.auth.default", return_value=(mock_credentials, "test-project")):
            with patch("google.cloud.sql.connector.Connector", return_value=mock_connector):
                with patch("asyncpg.create_pool", return_value=mock_asyncpg_pool):
                    await manager.initialize()
        
        # Simulate error
        mock_conn_error = AsyncMock()
        mock_conn_error.execute = AsyncMock(side_effect=Exception("Error"))
        mock_acquire_error = AsyncMock()
        mock_acquire_error.__aenter__ = AsyncMock(return_value=mock_conn_error)
        mock_acquire_error.__aexit__ = AsyncMock()
        manager._pool.acquire = Mock(return_value=mock_acquire_error)
        
        try:
            await manager.execute("SELECT 1")
        except CloudSQLError:
            pass
        
        assert manager._consecutive_errors == 1
        
        # Now simulate success - restore working connection
        mock_conn_success = AsyncMock()
        mock_conn_success.execute = AsyncMock(return_value="OK")
        mock_acquire_success = AsyncMock()
        mock_acquire_success.__aenter__ = AsyncMock(return_value=mock_conn_success)
        mock_acquire_success.__aexit__ = AsyncMock()
        manager._pool.acquire = Mock(return_value=mock_acquire_success)
        
        await manager.execute("SELECT 1")
        
        # Consecutive errors should reset
        assert manager._consecutive_errors == 0
