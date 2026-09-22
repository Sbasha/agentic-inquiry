"""Tests for correlation ID functionality."""

import pytest

pytestmark = pytest.mark.unit

import asyncio
import logging
from agentic_inquiry.correlation import (
    generate_correlation_id,
    get_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    correlation_context,
    CorrelationIdFilter,
    configure_correlation_logging,
)


class TestCorrelationIdGeneration:
    """Test correlation ID generation."""
    
    def test_generate_correlation_id(self):
        """Test generating correlation IDs."""
        corr_id1 = generate_correlation_id()
        corr_id2 = generate_correlation_id()
        
        # Should be strings
        assert isinstance(corr_id1, str)
        assert isinstance(corr_id2, str)
        
        # Should be unique
        assert corr_id1 != corr_id2
        
        # Should be valid UUIDs (36 characters with hyphens)
        assert len(corr_id1) == 36
        assert corr_id1.count('-') == 4


class TestCorrelationIdContext:
    """Test correlation ID context management."""
    
    def test_get_correlation_id_default(self):
        """Test getting correlation ID when none is set."""
        clear_correlation_id()
        assert get_correlation_id() is None
    
    def test_set_and_get_correlation_id(self):
        """Test setting and getting correlation ID."""
        test_id = "test-correlation-id"
        set_correlation_id(test_id)
        
        assert get_correlation_id() == test_id
        
        # Clean up
        clear_correlation_id()
    
    def test_set_correlation_id_auto_generate(self):
        """Test auto-generating correlation ID when None is provided."""
        corr_id = set_correlation_id(None)
        
        assert corr_id is not None
        assert isinstance(corr_id, str)
        assert get_correlation_id() == corr_id
        
        # Clean up
        clear_correlation_id()
    
    def test_clear_correlation_id(self):
        """Test clearing correlation ID."""
        set_correlation_id("test-id")
        assert get_correlation_id() is not None
        
        clear_correlation_id()
        assert get_correlation_id() is None
    
    def test_correlation_context_with_id(self):
        """Test correlation context with provided ID."""
        test_id = "test-context-id"
        
        with correlation_context(test_id) as corr_id:
            assert corr_id == test_id
            assert get_correlation_id() == test_id
        
        # Should be cleared after context
        assert get_correlation_id() is None
    
    def test_correlation_context_auto_generate(self):
        """Test correlation context with auto-generated ID."""
        with correlation_context() as corr_id:
            assert corr_id is not None
            assert isinstance(corr_id, str)
            assert get_correlation_id() == corr_id
        
        # Should be cleared after context
        assert get_correlation_id() is None
    
    def test_correlation_context_nested(self):
        """Test nested correlation contexts."""
        outer_id = "outer-id"
        inner_id = "inner-id"
        
        with correlation_context(outer_id):
            assert get_correlation_id() == outer_id
            
            with correlation_context(inner_id):
                assert get_correlation_id() == inner_id
            
            # Should restore outer ID
            assert get_correlation_id() == outer_id
        
        # Should be cleared after both contexts
        assert get_correlation_id() is None
    
    def test_correlation_context_exception(self):
        """Test that correlation context cleans up on exception."""
        test_id = "exception-test-id"
        
        try:
            with correlation_context(test_id):
                assert get_correlation_id() == test_id
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Should be cleared even after exception
        assert get_correlation_id() is None
    
    def test_correlation_context_restores_previous(self):
        """Test that correlation context restores previous ID."""
        first_id = "first-id"
        second_id = "second-id"
        
        set_correlation_id(first_id)
        assert get_correlation_id() == first_id
        
        with correlation_context(second_id):
            assert get_correlation_id() == second_id
        
        # Should restore first ID, not clear it
        assert get_correlation_id() == first_id
        
        # Clean up
        clear_correlation_id()


class TestCorrelationIdFilter:
    """Test correlation ID logging filter."""
    
    def test_filter_adds_correlation_id(self, caplog):
        """Test that filter adds correlation ID to log records."""
        logger = logging.getLogger("test_correlation_filter")
        logger.addFilter(CorrelationIdFilter())
        logger.setLevel(logging.INFO)
        
        test_id = "test-log-id"
        set_correlation_id(test_id)
        
        with caplog.at_level(logging.INFO, logger="test_correlation_filter"):
            logger.info("Test message")
        
        # Check that correlation_id was added to record
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert hasattr(record, 'correlation_id')
        assert record.correlation_id == test_id
        
        # Clean up
        clear_correlation_id()
    
    def test_filter_adds_dash_when_no_id(self, caplog):
        """Test that filter adds '-' when no correlation ID is set."""
        logger = logging.getLogger("test_correlation_filter_no_id")
        logger.addFilter(CorrelationIdFilter())
        logger.setLevel(logging.INFO)
        
        clear_correlation_id()
        
        with caplog.at_level(logging.INFO, logger="test_correlation_filter_no_id"):
            logger.info("Test message")
        
        # Check that correlation_id is '-'
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert hasattr(record, 'correlation_id')
        assert record.correlation_id == "-"
    
    def test_filter_does_not_filter_records(self):
        """Test that filter doesn't filter out any records."""
        filter_instance = CorrelationIdFilter()
        
        # Create a mock log record
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        
        # Filter should always return True
        assert filter_instance.filter(record) is True


class TestConfigureCorrelationLogging:
    """Test correlation logging configuration."""
    
    def test_configure_correlation_logging_root(self):
        """Test configuring correlation logging on root logger."""
        # Configure root logger
        configure_correlation_logging()
        
        # Check that filter was added
        root_logger = logging.getLogger()
        filters = [f for f in root_logger.filters if isinstance(f, CorrelationIdFilter)]
        assert len(filters) > 0
        
        # Clean up
        for f in filters:
            root_logger.removeFilter(f)
    
    def test_configure_correlation_logging_named(self):
        """Test configuring correlation logging on named logger."""
        logger_name = "test_correlation_config"
        configure_correlation_logging(logger_name=logger_name)
        
        # Check that filter was added
        logger = logging.getLogger(logger_name)
        filters = [f for f in logger.filters if isinstance(f, CorrelationIdFilter)]
        assert len(filters) > 0
        
        # Clean up
        for f in filters:
            logger.removeFilter(f)


@pytest.mark.asyncio
class TestCorrelationIdAsync:
    """Test correlation ID with async operations."""
    
    async def test_correlation_id_in_async_context(self):
        """Test that correlation ID works in async context."""
        test_id = "async-test-id"
        
        async def async_operation():
            return get_correlation_id()
        
        with correlation_context(test_id):
            result = await async_operation()
            assert result == test_id
    
    async def test_correlation_id_across_tasks(self):
        """Test that correlation ID is isolated across tasks."""
        async def task_with_id(task_id: str):
            with correlation_context(task_id):
                await asyncio.sleep(0.01)
                return get_correlation_id()
        
        # Run multiple tasks concurrently
        results = await asyncio.gather(
            task_with_id("task-1"),
            task_with_id("task-2"),
            task_with_id("task-3"),
        )
        
        # Each task should have its own correlation ID
        assert results == ["task-1", "task-2", "task-3"]
    
    async def test_correlation_id_propagation(self):
        """Test that correlation ID propagates through async calls."""
        test_id = "propagation-test"
        
        async def inner_function():
            return get_correlation_id()
        
        async def middle_function():
            return await inner_function()
        
        async def outer_function():
            return await middle_function()
        
        with correlation_context(test_id):
            result = await outer_function()
            assert result == test_id


class TestCorrelationIdIntegration:
    """Integration tests for correlation ID."""
    
    def test_end_to_end_logging(self, caplog):
        """Test end-to-end correlation ID in logging."""
        # Set up logger with correlation filter
        logger = logging.getLogger("test_e2e")
        logger.addFilter(CorrelationIdFilter())
        logger.setLevel(logging.INFO)
        
        test_id = "e2e-test-id"
        
        with caplog.at_level(logging.INFO, logger="test_e2e"):
            with correlation_context(test_id):
                logger.info("Operation started")
                logger.info("Operation in progress")
                logger.info("Operation completed")
        
        # All log records should have the same correlation ID
        assert len(caplog.records) == 3
        for record in caplog.records:
            assert record.correlation_id == test_id
    
    def test_multiple_requests_isolated(self, caplog):
        """Test that multiple requests have isolated correlation IDs."""
        logger = logging.getLogger("test_isolation")
        logger.addFilter(CorrelationIdFilter())
        logger.setLevel(logging.INFO)
        
        with caplog.at_level(logging.INFO, logger="test_isolation"):
            # First request
            with correlation_context("request-1"):
                logger.info("Request 1 message")
            
            # Second request
            with correlation_context("request-2"):
                logger.info("Request 2 message")
        
        # Check that each request has its own correlation ID
        assert len(caplog.records) == 2
        assert caplog.records[0].correlation_id == "request-1"
        assert caplog.records[1].correlation_id == "request-2"
