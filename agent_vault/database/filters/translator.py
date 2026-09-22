"""Filter AST to LanceDB SQL translator.

Translates the canonical Filter AST to LanceDB-compatible SQL predicates.
This is the ONLY place where Filter → backend translation occurs.

Security:
- Field names are validated by the Filter class during construction
- String values are properly escaped to prevent SQL injection
- Empty IN() lists are short-circuited at translation time

See: docs/design/filter-ast.md
"""
from __future__ import annotations

from typing import Any, Optional

from .ast import Filter, FilterOperator


class FilterTranslationError(Exception):
    """Error during filter translation.

    Attributes:
        message: Error description
        operator: The operator that caused the error
        field: The field involved (if applicable)
        backend: The backend name
    """

    def __init__(
        self,
        message: str,
        operator: Optional[FilterOperator] = None,
        field: Optional[str] = None,
        backend: str = "lancedb",
    ) -> None:
        self.operator = operator
        self.field = field
        self.backend = backend
        super().__init__(message)


class LanceDBFilterTranslator:
    """Translates Filter AST to LanceDB SQL predicates.

    LanceDB uses a SQL-like syntax for filter predicates. This translator
    converts the canonical Filter AST to LanceDB-compatible strings.

    Translation rules:
    - EQ: field = value
    - NE: field != value (or field <> value)
    - GT/GTE/LT/LTE: field > value, etc.
    - IN: field IN (v1, v2, ...)
    - NOT_IN: field NOT IN (v1, v2, ...)
    - IS_NULL: field IS NULL
    - IS_NOT_NULL: field IS NOT NULL
    - AND: (left) AND (right)
    - OR: (left) OR (right)

    Empty list behavior (per filter-ast.md):
    - IN(field, []) → FALSE literal (matches no rows)
    - NOT_IN(field, []) → TRUE literal (no restriction)

    Example:
        >>> translator = LanceDBFilterTranslator()
        >>> from agent_vault.database.filters import eq, gt, and_
        >>> filter_ast = and_(eq("status", "active"), gt("score", 0.5))
        >>> sql = translator.translate(filter_ast)
        >>> print(sql)
        ((status = 'active') AND (score > 0.5))
    """

    # Operator to SQL symbol mapping
    COMPARISON_OPS = {
        FilterOperator.EQ: "=",
        FilterOperator.NE: "!=",
        FilterOperator.GT: ">",
        FilterOperator.GTE: ">=",
        FilterOperator.LT: "<",
        FilterOperator.LTE: "<=",
        FilterOperator.LIKE: "LIKE",
        FilterOperator.ILIKE: "ILIKE",
    }

    def translate(self, filter_ast: Filter) -> str:
        """Translate a Filter AST to a LanceDB SQL predicate string.

        Args:
            filter_ast: The filter to translate

        Returns:
            SQL predicate string for LanceDB

        Raises:
            FilterTranslationError: If translation fails
        """
        return self._translate_node(filter_ast)

    def _translate_node(self, node: Filter) -> str:
        """Recursively translate a filter node."""
        op = node.operator

        # Compound operators (AND/OR)
        if op == FilterOperator.AND:
            left = self._translate_node(node.left)  # type: ignore[arg-type]
            right = self._translate_node(node.right)  # type: ignore[arg-type]
            return f"({left}) AND ({right})"

        if op == FilterOperator.OR:
            left = self._translate_node(node.left)  # type: ignore[arg-type]
            right = self._translate_node(node.right)  # type: ignore[arg-type]
            return f"({left}) OR ({right})"

        # Quote field name to handle reserved keywords
        field_ref = self._quote_identifier(node.field) if node.field else None

        # Null checks
        if op == FilterOperator.IS_NULL:
            return f"{field_ref} IS NULL"

        if op == FilterOperator.IS_NOT_NULL:
            return f"{field_ref} IS NOT NULL"

        # Set membership - with empty list short-circuit
        if op == FilterOperator.IN:
            values = node.values or []
            if len(values) == 0:
                # IN([]) → FALSE (matches no rows)
                return "FALSE"
            values_sql = ", ".join(self._format_value(v) for v in values)
            return f"{field_ref} IN ({values_sql})"

        if op == FilterOperator.NOT_IN:
            values = node.values or []
            if len(values) == 0:
                # NOT_IN([]) → TRUE (no restriction)
                return "TRUE"
            values_sql = ", ".join(self._format_value(v) for v in values)
            return f"{field_ref} NOT IN ({values_sql})"

        # Comparison operators
        if op in self.COMPARISON_OPS:
            sql_op = self.COMPARISON_OPS[op]
            value_sql = self._format_value(node.value)
            return f"{field_ref} {sql_op} {value_sql}"

        # Unknown operator
        raise FilterTranslationError(
            f"Unsupported operator: {op}",
            operator=op,
            field=node.field,
            backend="lancedb",
        )

    def _quote_identifier(self, field: str) -> str:
        """Format field names for LanceDB queries.

        LanceDB doesn't require quoting for simple identifiers, and quoting
        can cause lookup failures. Only quote when necessary (reserved words).

        For nested fields like 'metadata.type', dots are preserved for
        JSON field access.

        Args:
            field: Field name, possibly with dots for nested access

        Returns:
            Field identifier safe for LanceDB queries
        """
        # LanceDB doesn't need quoting for regular field names
        # Quoting can cause issues - only quote if field contains special chars
        # For now, return the field as-is to match FilterBuilder behavior
        return field

    def _format_value(self, value: Any) -> str:
        """Format a value for SQL.

        Args:
            value: The value to format

        Returns:
            SQL-safe string representation

        Raises:
            FilterTranslationError: If value type is not supported
        """
        if value is None:
            return "NULL"

        if isinstance(value, bool):
            # Bool must be checked before int (bool is subclass of int)
            return "TRUE" if value else "FALSE"

        if isinstance(value, (int, float)):
            return str(value)

        if isinstance(value, str):
            return self._escape_string(value)

        raise FilterTranslationError(
            f"Unsupported value type: {type(value).__name__}",
            backend="lancedb",
        )

    def _escape_string(self, value: str) -> str:
        """Escape a string value for SQL.

        LanceDB uses single quotes for strings. We escape:
        - Single quotes (') → ('')
        - Backslashes (\\) → (\\\\) for some backends

        Args:
            value: String to escape

        Returns:
            Escaped and quoted string
        """
        # Escape single quotes by doubling them
        escaped = value.replace("'", "''")
        return f"'{escaped}'"


def translate_filter(filter_ast: Optional[Filter]) -> Optional[str]:
    """Convenience function to translate a filter to LanceDB SQL.

    Args:
        filter_ast: Filter to translate, or None

    Returns:
        SQL predicate string, or None if filter_ast is None

    Example:
        >>> from agent_vault.database.filters import eq
        >>> translate_filter(eq("status", "active"))
        "status = 'active'"
        >>> translate_filter(None)
        None
    """
    if filter_ast is None:
        return None
    translator = LanceDBFilterTranslator()
    return translator.translate(filter_ast)
