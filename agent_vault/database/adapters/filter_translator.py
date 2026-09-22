"""Filter AST to LanceDB SQL translator.

DEPRECATED: This module has moved to agent_vault.database.filters.translator.
This file is a backward compatibility shim - import from the new location:

    from agent_vault.database.filters import (
        LanceDBFilterTranslator,
        FilterTranslationError,
        translate_filter,
    )

This shim will be removed in a future release.
"""

import warnings

# Re-export all public symbols from new location
from agent_vault.database.filters.translator import (
    FilterTranslationError,
    LanceDBFilterTranslator,
    translate_filter,
)

__all__ = [
    "FilterTranslationError",
    "LanceDBFilterTranslator",
    "translate_filter",
]

# Issue deprecation warning on import
warnings.warn(
    "agent_vault.database.adapters.filter_translator is deprecated. "
    "Import from agent_vault.database.filters instead: "
    "from agent_vault.database.filters import translate_filter, LanceDBFilterTranslator",
    DeprecationWarning,
    stacklevel=2,
)
