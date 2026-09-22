"""Correlation ID management for request tracing.

This module provides correlation ID support for tracing requests through
the system. Correlation IDs can be:
- Provided by the user
- Auto-generated using UUID
- Propagated through component boundaries
- Included in all log messages
"""

import uuid
import logging
from contextvars import ContextVar
from typing import Optional
from contextlib import contextmanager
from collections.abc import Generator

# Context variable for storing correlation ID
_correlation_id: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)

logger = logging.getLogger(__name__)


def generate_correlation_id() -> str:
    """Generate a new correlation ID.
    
    Returns:
        A new UUID-based correlation ID
    """
    return str(uuid.uuid4())


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID from context.
    
    Returns:
        Current correlation ID or None if not set
    """
    return _correlation_id.get()


def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """Set the correlation ID for the current context.
    
    Args:
        correlation_id: Correlation ID to set. If None, generates a new one.
    
    Returns:
        The correlation ID that was set
    """
    if correlation_id is None:
        correlation_id = generate_correlation_id()
    
    _correlation_id.set(correlation_id)
    return correlation_id


def clear_correlation_id() -> None:
    """Clear the correlation ID from the current context."""
    _correlation_id.set(None)


@contextmanager
def correlation_context(correlation_id: Optional[str] = None) -> Generator[str, None, None]:
    """Context manager for correlation ID scope.
    
    Sets a correlation ID for the duration of the context and clears it
    when exiting. If no correlation ID is provided, generates a new one.
    
    Args:
        correlation_id: Optional correlation ID. If None, generates a new one.
    
    Yields:
        The correlation ID being used
    
    Example:
        with correlation_context() as corr_id:
            logger.info("Processing request", extra={"correlation_id": corr_id})
            # All operations in this context share the same correlation ID
    """
    # Save previous correlation ID
    previous_id = get_correlation_id()
    
    # Set new correlation ID
    current_id = set_correlation_id(correlation_id)
    
    try:
        yield current_id
    finally:
        # Restore previous correlation ID
        if previous_id is not None:
            _correlation_id.set(previous_id)
        else:
            clear_correlation_id()


class CorrelationIdFilter(logging.Filter):
    """Logging filter that adds correlation ID to log records.
    
    This filter automatically adds the current correlation ID to all log
    records, making it easy to trace requests through the system.
    
    Usage:
        import logging
        from agent_vault.correlation import CorrelationIdFilter
        
        # Add to root logger
        logging.getLogger().addFilter(CorrelationIdFilter())
        
        # Or add to specific logger
        logger = logging.getLogger(__name__)
        logger.addFilter(CorrelationIdFilter())
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation ID to log record.
        
        Args:
            record: Log record to modify
        
        Returns:
            Always True (don't filter out any records)
        """
        correlation_id = get_correlation_id()
        record.correlation_id = correlation_id if correlation_id else "-"
        return True


def configure_correlation_logging(
    logger_name: Optional[str] = None,
    format_string: Optional[str] = None
) -> None:
    """Configure logging to include correlation IDs.
    
    This is a convenience function that:
    1. Adds CorrelationIdFilter to the specified logger
    2. Optionally updates the log format to include correlation_id
    
    Args:
        logger_name: Name of logger to configure. If None, configures root logger.
        format_string: Optional log format string. If provided, updates the handler format.
                      Should include %(correlation_id)s to show correlation IDs.
    
    Example:
        # Configure root logger with correlation IDs
        configure_correlation_logging(
            format_string="%(asctime)s [%(correlation_id)s] %(levelname)s %(name)s: %(message)s"
        )
    """
    # Get logger
    target_logger = logging.getLogger(logger_name)
    
    # Add correlation ID filter
    target_logger.addFilter(CorrelationIdFilter())
    
    # Update format if provided
    if format_string:
        formatter = logging.Formatter(format_string)
        # Update all handlers
        if target_logger.handlers:
            for handler in target_logger.handlers:
                handler.setFormatter(formatter)
        else:
            # If no handlers yet, create a basic one
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            target_logger.addHandler(handler)
            target_logger.setLevel(logging.INFO)


__all__ = [
    "generate_correlation_id",
    "get_correlation_id",
    "set_correlation_id",
    "clear_correlation_id",
    "correlation_context",
    "CorrelationIdFilter",
    "configure_correlation_logging",
]
