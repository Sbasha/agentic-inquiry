"""Utilities for flexible attribute access on entities.

This module provides helper functions for safely accessing attributes
from objects that may be dicts or dataclasses, enabling code to work
seamlessly with both PostgreSQL (dataclass) and LanceDB (dict) backends.
"""

from typing import Any


def get_attr(obj: Any, attr: str, default: Any = "") -> Any:
    """Safely get attribute from entity (dict or dataclass).

    Handles both dict-style access and dataclass attribute access,
    allowing code to work with both PostgreSQL (dataclass) and
    LanceDB (dict) backends.

    Args:
        obj: Entity object (dict or dataclass)
        attr: Attribute name to access
        default: Default value if not found

    Returns:
        The attribute value or default

    Example:
        >>> entity = {"name": "foo", "type": "function"}
        >>> get_attr(entity, "name")
        'foo'

        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class Entity:
        ...     name: str
        ...     type: str
        >>> entity = Entity(name="bar", type="class")
        >>> get_attr(entity, "name")
        'bar'
    """
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)
