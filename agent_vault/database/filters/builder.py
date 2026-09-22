"""Safe filter expression builder for LanceDB queries.

This module provides FilterBuilder for constructing safe, validated filter
expressions that prevent SQL injection vulnerabilities.
"""

import logging
from typing import Any, List, Union

logger = logging.getLogger(__name__)


class FilterBuilder:
    """Builds safe filter expressions for LanceDB queries.
    
    This class provides a fluent interface for constructing filter expressions
    with proper escaping and validation to prevent injection attacks.
    
    Example:
        >>> builder = FilterBuilder()
        >>> builder.add_doc_id_filter(["doc1", "doc2"])
        >>> builder.add_project_filter("my_project")
        >>> filter_expr = builder.build()
        >>> # Result: "doc_id IN ('doc1', 'doc2') AND project_id = 'my_project'"
    """

    def __init__(self) -> None:
        """Initialize an empty filter builder."""
        self._conditions: List[str] = []

    def add_doc_id_filter(self, doc_ids: Union[str, List[str]]) -> "FilterBuilder":
        """Add document ID filter with proper escaping.
        
        Args:
            doc_ids: Single document ID or list of document IDs
            
        Returns:
            Self for method chaining
            
        Raises:
            ValueError: If doc_ids is empty or contains invalid values
        """
        if not doc_ids:
            raise ValueError("doc_ids cannot be empty")
        
        # Normalize to list
        if isinstance(doc_ids, str):
            doc_ids = [doc_ids]
        
        # Validate all doc_ids are strings
        if not all(isinstance(doc_id, str) for doc_id in doc_ids):
            raise ValueError("All doc_ids must be strings")
        
        # Build filter expression
        if len(doc_ids) == 1:
            escaped = self._escape_string(doc_ids[0])
            self._conditions.append(f"doc_id = '{escaped}'")
        else:
            escaped_ids = [self._escape_string(doc_id) for doc_id in doc_ids]
            in_clause = ", ".join(f"'{eid}'" for eid in escaped_ids)
            self._conditions.append(f"doc_id IN ({in_clause})")
        
        return self

    def add_project_filter(self, project_id: str) -> "FilterBuilder":
        """Add project filter with validation.
        
        Args:
            project_id: Project ID to filter by
            
        Returns:
            Self for method chaining
            
        Raises:
            ValueError: If project_id is empty or not a string
        """
        if not isinstance(project_id, str):
            raise ValueError("project_id must be a string")
        
        if not project_id:
            raise ValueError("project_id cannot be empty")
        
        escaped = self._escape_string(project_id)
        self._conditions.append(f"project_id = '{escaped}'")
        
        return self

    def add_field_filter(
        self,
        field: str,
        value: Union[str, int, float, bool, None, List[Any]],
    ) -> "FilterBuilder":
        """Add a generic field filter with proper type handling.
        
        Args:
            field: Field name to filter on
            value: Value or list of values to filter by
            
        Returns:
            Self for method chaining
            
        Raises:
            ValueError: If field is empty or value type is unsupported
        """
        if not field:
            raise ValueError("field cannot be empty")
        
        # Validate field name (alphanumeric and underscore only)
        if not all(c.isalnum() or c == '_' for c in field):
            raise ValueError(f"Invalid field name: {field}")
        
        expr = self._build_field_expression(field, value)
        if expr:
            self._conditions.append(expr)
        
        return self

    def add_custom_condition(self, condition: str) -> "FilterBuilder":
        """Add a custom condition (use with caution).
        
        This method allows adding pre-built conditions. Use only when
        the condition is constructed from trusted sources.
        
        Args:
            condition: Pre-built condition string
            
        Returns:
            Self for method chaining
            
        Raises:
            ValueError: If condition is empty
        """
        if not condition:
            raise ValueError("condition cannot be empty")
        
        self._conditions.append(condition)
        return self

    def build(self) -> str:
        """Build final filter expression.
        
        Returns:
            Complete filter expression string, or empty string if no conditions
        """
        if not self._conditions:
            return ""
        
        return " AND ".join(self._conditions)

    def reset(self) -> "FilterBuilder":
        """Reset the builder to empty state.
        
        Returns:
            Self for method chaining
        """
        self._conditions.clear()
        return self

    def _escape_string(self, value: str) -> str:
        """Escape string value for SQL.
        
        Args:
            value: String to escape
            
        Returns:
            Escaped string safe for SQL
        """
        # Escape single quotes by doubling them (SQL standard)
        return value.replace("'", "''")

    def _build_field_expression(self, field: str, value: Any) -> str:
        """Build filter expression for a field.
        
        Args:
            field: Field name
            value: Field value or list of values
            
        Returns:
            Filter expression string
        """
        if value is None:
            return f"{field} IS NULL"
        
        if isinstance(value, list):
            if not value:
                return ""
            return self._build_in_expression(field, value)
        
        if isinstance(value, bool):
            return f"{field} = {str(value).lower()}"
        
        if isinstance(value, (int, float)):
            return f"{field} = {value}"
        
        if isinstance(value, str):
            escaped = self._escape_string(value)
            return f"{field} = '{escaped}'"
        
        logger.warning("Unsupported filter value type: %s", type(value))
        return ""

    def _build_in_expression(self, field: str, values: List[Any]) -> str:
        """Build IN expression for a list of values.
        
        Args:
            field: Field name
            values: List of values
            
        Returns:
            IN expression string
        """
        formatted = [self._format_value(v) for v in values]
        in_clause = ", ".join(formatted)
        return f"{field} IN ({in_clause})"

    def _format_value(self, value: Any) -> str:
        """Format a single value for SQL.
        
        Args:
            value: Value to format
            
        Returns:
            Formatted value string
        """
        if isinstance(value, str):
            escaped = self._escape_string(value)
            return f"'{escaped}'"
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)
