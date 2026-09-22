"""Database adapters package.

This package contains adapter implementations for different backends.

Filter translation utilities have moved to agentic_inquiry.database.filters.
For backward compatibility, they are re-exported from here.
"""
# Re-export filter utilities from new location for backward compatibility
from agentic_inquiry.database.filters import (
    FilterTranslationError,
    LanceDBFilterTranslator,
    translate_filter,
)
from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter

__all__ = [
    "FilterTranslationError",
    "LanceDBAdapter",
    "LanceDBFilterTranslator",
    "translate_filter",
]
