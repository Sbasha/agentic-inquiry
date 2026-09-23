"""Agentic Inquiry package.

Importing this package is side-effect free. Subpackages resolve lazily so a
short-lived ``ai`` process does not load the storage stack until a command
actually needs it.
"""

from __future__ import annotations

import importlib
from types import ModuleType

__all__ = [
    "database",
    "embeddings",
    "exceptions",
    "indexing",
    "models",
    "parsers",
    "search",
]


def __getattr__(name: str) -> ModuleType:
    """Import ``agentic_inquiry.<name>`` on first access.

    Unknown names raise ``AttributeError``. A subpackage that exists but fails
    while importing still raises that import error.
    """
    if name.startswith("_"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name = f"{__name__}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
        raise
    globals()[name] = module
    return module
