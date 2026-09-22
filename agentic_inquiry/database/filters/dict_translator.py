"""Dict-based filter to SQL translator.

This module provides the canonical implementation for translating dict-based
filters to SQL expressions. All dict→SQL translation should use this module.

Supports:
- Simple field: value equality
- Operators via tuple: (operator, value)
- Nested OR: {"OR": [{...}, {...}]}
- Nested NOT: {"NOT": {...}}
- IN clause: ("IN", [values])
- NULL handling: value=None → IS NULL

Example:
    >>> translate_dict_filters({"status": "active", "type": "code"})
    "status = 'active' AND type = 'code'"

    >>> translate_dict_filters({"score": (">", 0.5)})
    "score > 0.5"

    >>> translate_dict_filters({"OR": [{"status": "active"}, {"status": "pending"}]})
    "(status = 'active' OR status = 'pending')"
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from agentic_inquiry.database.filters.ast import validate_field_name

logger = logging.getLogger(__name__)


def translate_dict_filters(filters: Optional[Dict[str, Any]]) -> Optional[str]:
    """Translate a dict-based filter to a SQL expression string.

    This is the single source of truth for dict→SQL translation.

    Args:
        filters: Dictionary of field: value pairs, or None

    Returns:
        SQL expression string, or None if filters is None/empty

    Examples:
        # Simple equality
        >>> translate_dict_filters({"status": "active"})
        "status = 'active'"

        # Multiple fields (AND)
        >>> translate_dict_filters({"status": "active", "type": "code"})
        "status = 'active' AND type = 'code'"

        # Operators via tuple
        >>> translate_dict_filters({"score": (">", 0.5)})
        "score > 0.5"

        # IN operator
        >>> translate_dict_filters({"type": ("IN", ["code", "doc"])})
        "type IN ('code', 'doc')"

        # OR logic
        >>> translate_dict_filters({"OR": [{"a": 1}, {"b": 2}]})
        "(a = 1 OR b = 2)"

        # NOT logic
        >>> translate_dict_filters({"NOT": {"deleted": True}})
        "(NOT (deleted = true))"

        # NULL handling
        >>> translate_dict_filters({"deleted_at": None})
        "deleted_at IS NULL"
    """
    if not filters:
        return None

    translator = DictFilterTranslator()
    return translator.translate(filters)


class DictFilterTranslator:
    """Translates dict-based filters to SQL expressions.

    This class consolidates the filter translation logic that was previously
    duplicated across LanceDBManager._filters_to_expression() and
    FilterBuilder.

    The translator handles:
    - Simple field=value equality
    - Operators via tuple: (operator, value)
    - Nested OR: {"OR": [{...}, {...}]}
    - Nested NOT: {"NOT": {...}}
    - IN clauses
    - NULL handling
    """

    def translate(self, filters: Dict[str, Any]) -> Optional[str]:
        """Translate filter dict to SQL expression.

        Args:
            filters: Dictionary of field: value pairs

        Returns:
            SQL expression string, or None if empty
        """
        if not filters:
            return None

        expressions: List[str] = []
        for key, value in filters.items():
            upper_key = key.upper()

            # Handle OR operator
            if upper_key == "OR":
                sub_expressions = [
                    expr
                    for expr in (self.translate(option) for option in value)
                    if expr
                ]
                if sub_expressions:
                    expressions.append(f"({' OR '.join(sub_expressions)})")
                continue

            # Handle NOT operator
            if upper_key == "NOT":
                nested = self.translate(value)
                if nested:
                    expressions.append(f"(NOT ({nested}))")
                continue

            # Handle regular field conditions
            clause = self._translate_condition(key, value)
            if clause:
                expressions.append(clause)

        if not expressions:
            return None
        return " AND ".join(expressions)

    def _translate_condition(self, column: str, value: Any) -> Optional[str]:
        """Translate a single field condition.

        Args:
            column: Field/column name
            value: Value or (operator, value) tuple

        Returns:
            SQL expression for this condition

        Raises:
            ValueError: If column name contains invalid characters (SQL injection prevention)
        """
        # Validate column name to prevent SQL injection (SEC-006)
        validate_field_name(column)

        # Handle operator tuple: (operator, operand)
        if isinstance(value, tuple) and len(value) == 2:
            operator, operand = value
            operator_upper = str(operator).upper()

            # IN operator
            if operator_upper == "IN":
                if not operand:
                    return "FALSE"
                values = [self._format_value(item) for item in operand]
                return f"{column} IN ({', '.join(values)})"

            # NOT IN operator
            if operator_upper == "NOT IN":
                if not operand:
                    return "TRUE"
                values = [self._format_value(item) for item in operand]
                return f"{column} NOT IN ({', '.join(values)})"

            # NULL comparison with operators
            if operand is None:
                if operator_upper in {"=", "IS", "=="}:
                    return f"{column} IS NULL"
                if operator_upper in {"!=", "<>", "IS NOT"}:
                    return f"{column} IS NOT NULL"

            # Standard comparison operators
            return f"{column} {operator} {self._format_value(operand)}"

        # Handle list value (implicit IN)
        if isinstance(value, list):
            if not value:
                return None
            formatted = [self._format_value(v) for v in value]
            return f"{column} IN ({', '.join(formatted)})"

        # Handle NULL
        if value is None:
            return f"{column} IS NULL"

        # Simple equality
        return f"{column} = {self._format_value(value)}"

    def _format_value(self, value: Any) -> str:
        """Format a value for SQL.

        Args:
            value: Value to format

        Returns:
            SQL-safe string representation
        """
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        if isinstance(value, bool):
            # Use lowercase true/false to match FilterBuilder behavior
            return "true" if value else "false"
        if value is None:
            return "NULL"
        return str(value)


def format_in_clause(column: str, values: Sequence[str]) -> Optional[str]:
    """Format an IN clause for a list of values.

    Args:
        column: Column name
        values: Values for the IN clause

    Returns:
        IN clause string, or None if values is empty
    """
    if not values:
        return None
    translator = DictFilterTranslator()
    formatted = ", ".join(translator._format_value(v) for v in values)
    return f"{column} IN ({formatted})"
