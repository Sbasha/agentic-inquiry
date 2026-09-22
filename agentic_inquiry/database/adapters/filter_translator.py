"""Filter AST to LanceDB SQL translator.

DEPRECATED: This module has moved to agentic_inquiry.database.filters.translator.
This file is a backward compatibility shim - import from the new location:

    from agentic_inquiry.database.filters import (
        LanceDBFilterTranslator,
        FilterTranslationError,
        translate_filter,
    )

This shim will be removed in a future release.
"""

import warnings

# Re-export all public symbols from new location
from agentic_inquiry.database.filters.translator import (
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
    "agentic_inquiry.database.adapters.filter_translator is deprecated. "
    "Import from agentic_inquiry.database.filters instead: "
    "from agentic_inquiry.database.filters import translate_filter, LanceDBFilterTranslator",
    DeprecationWarning,
    stacklevel=2,
)
