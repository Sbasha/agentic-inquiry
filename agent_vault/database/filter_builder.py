"""Safe filter expression builder for LanceDB queries.

DEPRECATED: This module has moved to agent_vault.database.filters.builder.
This file is a backward compatibility shim - import from the new location:

    from agent_vault.database.filters import FilterBuilder

This shim will be removed in a future release.
"""

import warnings

# Re-export FilterBuilder from new location
from agent_vault.database.filters.builder import FilterBuilder

__all__ = ["FilterBuilder"]

# Issue deprecation warning on import
warnings.warn(
    "agent_vault.database.filter_builder is deprecated. "
    "Import from agent_vault.database.filters instead: "
    "from agent_vault.database.filters import FilterBuilder",
    DeprecationWarning,
    stacklevel=2,
)
