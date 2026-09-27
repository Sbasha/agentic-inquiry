"""Canonical filter AST for database queries.

This module defines the unified filter language used across all backends.
All filter construction MUST use these types - no dict/tuple/SQL string formats.

See: docs/design/filter-ast.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional, Sequence, Union


class FilterOperator(str, Enum):
    """Operators for filter expressions.

    Core operators (MUST be supported by all backends):
        - Comparison: EQ, NE, GT, GTE, LT, LTE
        - String pattern: LIKE, ILIKE (SQL wildcard semantics: ``%`` = any
          run of chars, ``_`` = single char). ILIKE is case-insensitive.
          Required because MCP entity resolution uses ``ILIKE`` against
          entity names and the graph provider already supports it.
        - Set membership: IN, NOT_IN
        - Null checks: IS_NULL, IS_NOT_NULL
        - Logical: AND, OR

    Note: Use IS_NULL/IS_NOT_NULL for null checks, NOT EQ/NE with None.
    """

    # Comparison operators
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"

    # Pattern-match operators (SQL LIKE / ILIKE semantics)
    LIKE = "like"
    ILIKE = "ilike"

    # Set membership
    IN = "in"
    NOT_IN = "not_in"

    # Null checks
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"

    # Logical operators (compound filters)
    AND = "and"
    OR = "or"


# Valid types for filter values
FilterValue = Union[str, int, float, bool, None]
FilterValueList = List[Union[str, int, float, bool]]

# Field name validation pattern
# Allows nested field access with dots (e.g., metadata.type, headers.content_type)
# Each segment must start with letter/underscore, contain only letters/numbers/underscores
FIELD_NAME_SEGMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_field_name(field: str) -> None:
    """Validate that a field name is safe for use in queries.

    Field names must:
    - Start with a letter or underscore
    - Contain only letters, numbers, underscores, and dots (for nested access)
    - Each dot-separated segment must be valid on its own
    - Not be empty, not start/end with dot, no consecutive dots

    Examples of valid field names:
    - "status", "file_path", "_private"
    - "metadata.type", "headers.content_type" (nested JSON access)

    This prevents SQL injection and ensures compatibility across backends.

    Args:
        field: Field name to validate

    Raises:
        ValueError: If field name is invalid
    """
    if not field:
        raise ValueError("Field name cannot be empty")

    # Check for invalid dot patterns
    if field.startswith(".") or field.endswith(".") or ".." in field:
        raise ValueError(
            f"Invalid field name '{field}'. Field names cannot start/end with "
            f"dots or contain consecutive dots."
        )

    # Validate each segment
    segments = field.split(".")
    for segment in segments:
        if not segment:
            raise ValueError(f"Invalid field name '{field}'. Empty segment found.")
        if not FIELD_NAME_SEGMENT_PATTERN.match(segment):
            raise ValueError(
                f"Invalid field name '{field}'. Each segment must match pattern "
                f"[A-Za-z_][A-Za-z0-9_]* (letters, numbers, underscores only, "
                f"starting with letter or underscore)"
            )


def validate_filter_value(value: Any) -> None:
    """Validate that a value is a valid filter value type.

    Valid types: str, int, float, bool, None

    Args:
        value: Value to validate

    Raises:
        TypeError: If value is not a valid filter value type
    """
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise TypeError(
            f"Filter value must be str, int, float, bool, or None. "
            f"Got {type(value).__name__}: {value!r}"
        )


def validate_filter_value_list(values: Sequence[Any]) -> None:
    """Validate that all values in a list are valid filter value types.

    Args:
        values: Sequence of values to validate

    Raises:
        TypeError: If any value is not a valid filter value type
    """
    for i, value in enumerate(values):
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError(
                f"Filter value list item {i} must be str, int, float, or bool. "
                f"Got {type(value).__name__}: {value!r}"
            )


@dataclass(frozen=True, slots=True)
class Filter:
    """A single filter condition or compound filter.

    For simple conditions:
        Filter(operator=FilterOperator.EQ, field="status", value="active")

    For set membership:
        Filter(operator=FilterOperator.IN, field="type", values=["a", "b", "c"])

    For null checks:
        Filter(operator=FilterOperator.IS_NULL, field="deleted_at")

    For compound filters:
        Filter(
            operator=FilterOperator.AND,
            left=Filter(operator=FilterOperator.EQ, field="status", value="active"),
            right=Filter(operator=FilterOperator.GT, field="score", value=0.5)
        )

    Attributes:
        operator: The filter operator
        field: Field name for simple conditions (None for AND/OR)
        value: Single value for comparison operators
        values: List of values for IN/NOT_IN operators
        left: Left operand for AND/OR
        right: Right operand for AND/OR

    Semantics:
        - EQ(field, None) is FORBIDDEN - use IS_NULL(field)
        - NE(field, None) is FORBIDDEN - use IS_NOT_NULL(field)
        - IN(field, []) → FALSE (matches no rows)
        - NOT_IN(field, []) → TRUE (no restriction)
    """

    operator: FilterOperator
    field: Optional[str] = None
    value: Optional[FilterValue] = None
    values: Optional[Sequence[FilterValue]] = None
    left: Optional[Filter] = None
    right: Optional[Filter] = None

    def __post_init__(self) -> None:
        """Validate filter structure."""
        self._validate()

    def _validate(self) -> None:
        """Validate filter based on operator type."""
        op = self.operator

        # Compound operators (AND/OR)
        if op in (FilterOperator.AND, FilterOperator.OR):
            if self.left is None or self.right is None:
                raise ValueError(
                    f"{op.value.upper()} filter requires both 'left' and 'right' operands"
                )
            if self.field is not None:
                raise ValueError(f"{op.value.upper()} filter must not have 'field' set")
            return

        # All other operators require a field
        if self.field is None:
            raise ValueError(f"{op.value.upper()} filter requires 'field'")
        validate_field_name(self.field)

        # Null check operators
        if op in (FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL):
            if self.value is not None or self.values is not None:
                raise ValueError(
                    f"{op.value.upper()} filter must not have 'value' or 'values'"
                )
            return

        # Set membership operators
        if op in (FilterOperator.IN, FilterOperator.NOT_IN):
            if self.values is None:
                raise ValueError(f"{op.value.upper()} filter requires 'values' list")
            validate_filter_value_list(self.values)
            return

        # Comparison operators
        if op in (
            FilterOperator.EQ,
            FilterOperator.NE,
            FilterOperator.GT,
            FilterOperator.GTE,
            FilterOperator.LT,
            FilterOperator.LTE,
        ):
            # Forbid EQ/NE with None - use IS_NULL/IS_NOT_NULL
            if self.value is None and op in (FilterOperator.EQ, FilterOperator.NE):
                null_op = "IS_NULL" if op == FilterOperator.EQ else "IS_NOT_NULL"
                raise ValueError(
                    f"Cannot use {op.value.upper()} with None. Use {null_op} instead."
                )
            validate_filter_value(self.value)
            return

        # String pattern operators (LIKE / ILIKE) — pattern must be a string.
        if op in (FilterOperator.LIKE, FilterOperator.ILIKE):
            if not isinstance(self.value, str):
                raise ValueError(
                    f"{op.value.upper()} filter requires a string pattern; "
                    f"got {type(self.value).__name__}"
                )
            return

    def is_compound(self) -> bool:
        """Check if this is a compound filter (AND/OR)."""
        return self.operator in (FilterOperator.AND, FilterOperator.OR)


# Convenience constructors for common filter patterns
def eq(field: str, value: FilterValue) -> Filter:
    """Create an equality filter: field == value."""
    return Filter(operator=FilterOperator.EQ, field=field, value=value)


def ne(field: str, value: FilterValue) -> Filter:
    """Create a not-equal filter: field != value."""
    return Filter(operator=FilterOperator.NE, field=field, value=value)


def gt(field: str, value: FilterValue) -> Filter:
    """Create a greater-than filter: field > value."""
    return Filter(operator=FilterOperator.GT, field=field, value=value)


def gte(field: str, value: FilterValue) -> Filter:
    """Create a greater-than-or-equal filter: field >= value."""
    return Filter(operator=FilterOperator.GTE, field=field, value=value)


def lt(field: str, value: FilterValue) -> Filter:
    """Create a less-than filter: field < value."""
    return Filter(operator=FilterOperator.LT, field=field, value=value)


def lte(field: str, value: FilterValue) -> Filter:
    """Create a less-than-or-equal filter: field <= value."""
    return Filter(operator=FilterOperator.LTE, field=field, value=value)


def like(field: str, pattern: str) -> Filter:
    """Create a LIKE filter: ``field LIKE pattern`` (SQL wildcard semantics)."""
    return Filter(operator=FilterOperator.LIKE, field=field, value=pattern)


def ilike(field: str, pattern: str) -> Filter:
    """Create an ILIKE filter: ``field ILIKE pattern`` (case-insensitive)."""
    return Filter(operator=FilterOperator.ILIKE, field=field, value=pattern)


def is_in(field: str, values: Sequence[FilterValue]) -> Filter:
    """Create an IN filter: field IN (values)."""
    return Filter(operator=FilterOperator.IN, field=field, values=values)


def not_in(field: str, values: Sequence[FilterValue]) -> Filter:
    """Create a NOT IN filter: field NOT IN (values)."""
    return Filter(operator=FilterOperator.NOT_IN, field=field, values=values)


def is_null(field: str) -> Filter:
    """Create an IS NULL filter: field IS NULL."""
    return Filter(operator=FilterOperator.IS_NULL, field=field)


def is_not_null(field: str) -> Filter:
    """Create an IS NOT NULL filter: field IS NOT NULL."""
    return Filter(operator=FilterOperator.IS_NOT_NULL, field=field)


def and_(*filters: Filter) -> Filter:
    """Create an AND filter combining multiple filters.

    Args:
        *filters: Two or more filters to combine with AND

    Returns:
        Combined AND filter

    Example:
        >>> combined = and_(
        ...     eq("status", "active"),
        ...     gt("score", 0.5),
        ...     is_not_null("name")
        ... )
    """
    if len(filters) < 2:
        raise ValueError("and_() requires at least 2 filters")

    result = filters[0]
    for f in filters[1:]:
        result = Filter(operator=FilterOperator.AND, left=result, right=f)
    return result


def or_(*filters: Filter) -> Filter:
    """Create an OR filter combining multiple filters.

    Args:
        *filters: Two or more filters to combine with OR

    Returns:
        Combined OR filter

    Example:
        >>> combined = or_(
        ...     eq("type", "code"),
        ...     eq("type", "doc")
        ... )
    """
    if len(filters) < 2:
        raise ValueError("or_() requires at least 2 filters")

    result = filters[0]
    for f in filters[1:]:
        result = Filter(operator=FilterOperator.OR, left=result, right=f)
    return result
