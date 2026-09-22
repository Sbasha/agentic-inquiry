"""Safe filter expression builder for LanceDB queries.

DEPRECATED: This module has moved to agentic_inquiry.database.filters.builder.
This file is a backward compatibility shim - import from the new location:

    from agentic_inquiry.database.filters import FilterBuilder

This shim will be removed in a future release.
"""

import warnings

# Re-export FilterBuilder from new location
from agentic_inquiry.database.filters.builder import FilterBuilder

__all__ = ["FilterBuilder"]

# Issue deprecation warning on import
warnings.warn(
    "agentic_inquiry.database.filter_builder is deprecated. "
    "Import from agentic_inquiry.database.filters instead: "
    "from agentic_inquiry.database.filters import FilterBuilder",
    DeprecationWarning,
    stacklevel=2,
)
