"""Filter AST builder helpers for common patterns.

These helpers assist gradual migration from dict-based filters to Filter AST.
See Phase 4.5.1 in DATABASE-ABSTRACTION-TASKS.md.

Available helpers:
- from_dict: Convert legacy dict filters to Filter AST
- project_scoped: Common project filter pattern
- by_id: Single ID lookup pattern
- by_type: Entity type filter pattern
- combine_filters: Combine optional filters with AND
- id_in_list: ID list membership pattern
- file_path: File path filter
- source_id, target_id: Relationship endpoint filters

Example usage:
    >>> from agent_vault.database.filter_helpers import from_dict, project_scoped
    >>> # Convert legacy dict
    >>> filter_ast = from_dict({"status": "active", "type": ["code", "doc"]})
    >>> # Create project-scoped filter
    >>> filter_ast = project_scoped("proj_001", eq("status", "indexed"))
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from agent_vault.database.filters import (
    Filter,
    FilterOperator,
    and_,
    eq,
    is_in,
)


def from_dict(filters: dict[str, Any]) -> Optional[Filter]:
    """Convert legacy dict-based filters to Filter AST.

    Handles common patterns:
    - {"field": "value"} → eq("field", "value")
    - {"field": ["val1", "val2"]} → is_in("field", ["val1", "val2"])
    - {"field1": "val1", "field2": "val2"} → and_(eq(...), eq(...))

    Args:
        filters: Dictionary of field-value pairs

    Returns:
        Filter AST, or None if filters is empty

    Raises:
        ValueError: If a value is None (use is_null filter explicitly)
        TypeError: If a value is a nested dict (not supported)

    Example:
        >>> from_dict({"status": "active"})
        Filter(operator=FilterOperator.EQ, field="status", value="active")
        >>> from_dict({})
        None
    """
    if not filters:
        return None

    filter_list: list[Filter] = []

    for field, value in filters.items():
        filter_list.append(_convert_field_value(field, value))

    if len(filter_list) == 1:
        return filter_list[0]

    return and_(*filter_list)


def _convert_field_value(field: str, value: Any) -> Filter:
    """Convert a single field-value pair to a Filter.

    Args:
        field: Field name
        value: Field value (scalar or list/tuple/set)

    Returns:
        Filter for this field-value pair

    Raises:
        ValueError: If value is None
        TypeError: If value is a nested dict
    """
    if value is None:
        raise ValueError(
            f"Cannot use None value in dict filter for field '{field}'. "
            f"Use is_null('{field}') filter explicitly instead."
        )

    if isinstance(value, dict):
        raise TypeError(
            f"Nested dict values not supported for field '{field}'. "
            f"Use explicit Filter construction for complex queries."
        )

    if isinstance(value, (list, tuple, set)):
        return _values_to_filter(field, list(value))

    # Scalar value
    return eq(field, value)


def _values_to_filter(field: str, values: list[Any]) -> Filter:
    """Convert a list of values to IN or EQ filter.

    Optimizes single-item lists to EQ instead of IN.
    This is a shared helper used by both from_dict and id_in_list.

    Args:
        field: Field name
        values: List of values

    Returns:
        Filter for this field-values pair
    """
    if len(values) == 1:
        # Optimize single-item list to EQ
        return eq(field, values[0])

    return is_in(field, values)


def project_scoped(
    project_id: str, additional: Optional[Filter] = None
) -> Filter:
    """Create a project-scoped filter.

    Common pattern for filtering by project_id, optionally combined
    with additional filters.

    Args:
        project_id: Project ID to filter by
        additional: Optional additional filter to combine with AND

    Returns:
        Filter for project_id, optionally combined with additional

    Example:
        >>> project_scoped("proj_001")
        Filter(operator=FilterOperator.EQ, field="project_id", value="proj_001")
        >>> project_scoped("proj_001", eq("status", "active"))
        Filter(operator=FilterOperator.AND, left=..., right=...)
    """
    project_filter = eq("project_id", project_id)

    if additional is None:
        return project_filter

    return Filter(
        operator=FilterOperator.AND,
        left=project_filter,
        right=additional,
    )


def by_id(field: str, id_value: str) -> Filter:
    """Create a filter for a single ID lookup.

    Common pattern for entity_id, doc_id, etc.

    Args:
        field: ID field name (e.g., "entity_id", "doc_id")
        id_value: The ID value to match

    Returns:
        EQ filter for the ID field

    Example:
        >>> by_id("entity_id", "ent_001")
        Filter(operator=FilterOperator.EQ, field="entity_id", value="ent_001")
    """
    return eq(field, id_value)


def by_type(type_value: str, field: str = "type") -> Filter:
    """Create a filter for entity type.

    Args:
        type_value: Type value to filter by. Supports plain type names
                   like "function", "class", "method". Also handles
                   legacy "code_*" prefixed types for backward compatibility.
        field: Field name (default: "type")

    Returns:
        EQ filter for the type field

    Example:
        >>> by_type("function")
        Filter(operator=FilterOperator.EQ, field="type", value="function")
        >>> by_type("class", field="entity_type")
        Filter(operator=FilterOperator.EQ, field="entity_type", value="class")
    """
    from agent_vault.models.graph_entity import EntityType
    normalized_type = EntityType.normalize(type_value)
    return eq(field, normalized_type)


def combine_filters(*filters: Optional[Filter]) -> Optional[Filter]:
    """Combine multiple optional filters with AND.

    Filters that are None are ignored. Useful when building filters
    from optional parameters.

    Args:
        *filters: Filters to combine (None values are ignored)

    Returns:
        Combined filter, or None if all filters are None

    Example:
        >>> combine_filters(
        ...     eq("project_id", "proj_001"),
        ...     eq("status", "active") if status else None,
        ...     is_in("type", types) if types else None,
        ... )
    """
    non_none: list[Filter] = [f for f in filters if f is not None]

    if not non_none:
        return None

    if len(non_none) == 1:
        return non_none[0]

    return and_(*non_none)


def id_in_list(field: str, ids: Sequence[str]) -> Filter:
    """Create a filter for ID list membership.

    Optimizes single-item lists to EQ instead of IN.

    Args:
        field: ID field name
        ids: List of IDs to match

    Returns:
        EQ filter for single ID, IN filter for multiple IDs

    Example:
        >>> id_in_list("doc_id", ["doc1"])
        Filter(operator=FilterOperator.EQ, field="doc_id", value="doc1")
        >>> id_in_list("doc_id", ["doc1", "doc2"])
        Filter(operator=FilterOperator.IN, field="doc_id", values=["doc1", "doc2"])
    """
    return _values_to_filter(field, list(ids))


def file_path(path: str) -> Filter:
    """Create a file path filter.

    Args:
        path: File path to filter by

    Returns:
        EQ filter for file_path field

    Example:
        >>> file_path("/src/main.py")
        Filter(operator=FilterOperator.EQ, field="file_path", value="/src/main.py")
    """
    return eq("file_path", path)


def source_id(entity_id: str) -> Filter:
    """Create a source_id filter for relationship queries.

    Args:
        entity_id: Source entity ID

    Returns:
        EQ filter for source_id field

    Example:
        >>> source_id("ent_001")
        Filter(operator=FilterOperator.EQ, field="source_id", value="ent_001")
    """
    return eq("source_id", entity_id)


def target_id(entity_id: str) -> Filter:
    """Create a target_id filter for relationship queries.

    Args:
        entity_id: Target entity ID

    Returns:
        EQ filter for target_id field

    Example:
        >>> target_id("ent_002")
        Filter(operator=FilterOperator.EQ, field="target_id", value="ent_002")
    """
    return eq("target_id", entity_id)
