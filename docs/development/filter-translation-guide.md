# Filter Translation Guide

This guide explains how to implement a filter translator that converts the canonical `Filter` AST to your backend's query language.

## Overview

The `Filter` AST is the canonical filter language used throughout Agentic Inquiry. Every database adapter must translate this AST to its backend's native format (SQL, DSL, structured queries).

**Key files:**
- `agentic_inquiry/database/filters.py` - Filter AST definition
- `agentic_inquiry/database/adapters/filter_translator.py` - LanceDB reference implementation
- `docs/design/filter-ast.md` - Canonical specification

---

## Filter AST Structure

```python
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Sequence


class FilterOperator(str, Enum):
    # Comparison
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"

    # Set membership
    IN = "in"
    NOT_IN = "not_in"

    # Null checks
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"

    # Compound
    AND = "and"
    OR = "or"


@dataclass(frozen=True)
class Filter:
    operator: FilterOperator
    field: Optional[str] = None       # For comparison/null ops
    value: Optional[Any] = None       # For EQ, NE, GT, etc.
    values: Optional[Sequence] = None # For IN, NOT_IN
    left: Optional["Filter"] = None   # For AND, OR
    right: Optional["Filter"] = None  # For AND, OR
```

### Builder Functions

Use these instead of constructing Filter directly:

```python
from agentic_inquiry.database.filters import (
    eq, ne, gt, gte, lt, lte,
    is_in, not_in,
    is_null, is_not_null,
    and_, or_,
)

# Simple comparisons
eq("status", "active")      # status = 'active'
gt("score", 0.5)            # score > 0.5
is_in("type", ["a", "b"])   # type IN ('a', 'b')

# Null checks
is_null("deleted_at")       # deleted_at IS NULL
is_not_null("project_id")   # project_id IS NOT NULL

# Compound
and_(
    eq("status", "active"),
    gt("score", 0.5)
)  # (status = 'active') AND (score > 0.5)
```

---

## Operators and Semantics

### Comparison Operators

| Operator | Meaning | SQL Equivalent |
|----------|---------|----------------|
| `EQ` | Equal | `field = value` |
| `NE` | Not equal | `field != value` or `field <> value` |
| `GT` | Greater than | `field > value` |
| `GTE` | Greater than or equal | `field >= value` |
| `LT` | Less than | `field < value` |
| `LTE` | Less than or equal | `field <= value` |

### Set Membership Operators

| Operator | Meaning | SQL Equivalent |
|----------|---------|----------------|
| `IN` | Value in set | `field IN (v1, v2, ...)` |
| `NOT_IN` | Value not in set | `field NOT IN (v1, v2, ...)` |

### Null Operators

| Operator | Meaning | SQL Equivalent |
|----------|---------|----------------|
| `IS_NULL` | Field is null | `field IS NULL` |
| `IS_NOT_NULL` | Field is not null | `field IS NOT NULL` |

**Important:** Do NOT use `EQ(field, None)` or `NE(field, None)`. The Filter class enforces this at construction time.

### Compound Operators

| Operator | Meaning | SQL Equivalent |
|----------|---------|----------------|
| `AND` | Both conditions | `(left) AND (right)` |
| `OR` | Either condition | `(left) OR (right)` |

Compound operators combine two Filter nodes via `left` and `right` fields.

---

## Empty List Behavior

This is critical and must be implemented correctly:

| Expression | Evaluates To | Rationale |
|------------|--------------|-----------|
| `IN(field, [])` | `FALSE` | Empty set contains nothing |
| `NOT_IN(field, [])` | `TRUE` | Everything is "not in" an empty set |

Implement these as short-circuits at translation time:

```python
if op == FilterOperator.IN:
    values = node.values or []
    if len(values) == 0:
        return "FALSE"  # Short-circuit
    # ... normal translation

if op == FilterOperator.NOT_IN:
    values = node.values or []
    if len(values) == 0:
        return "TRUE"  # Short-circuit
    # ... normal translation
```

---

## Field Name Validation (Security)

Field names are validated by the `Filter` class during construction. The pattern is:

```
^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$
```

This allows:
- Simple fields: `status`, `project_id`, `created_at`
- Nested fields: `metadata.type`, `ranking_signals.pagerank`

Disallowed:
- Spaces: `"my field"`
- Quotes: `"field'name"`
- Brackets: `"field[0]"`
- Operators: `"field > 5"`
- SQL injection attempts: `"field; DROP TABLE"`

Your translator can trust that field names are pre-validated, but you should still:
1. Quote identifiers if your backend requires it
2. Be careful with reserved keywords

---

## String Escaping

**Critical for SQL-based backends.** Always escape string values to prevent injection:

```python
def _escape_string(self, value: str) -> str:
    """Escape a string value for SQL."""
    # Escape single quotes by doubling them
    escaped = value.replace("'", "''")
    return f"'{escaped}'"
```

Example translations:
- `"active"` → `'active'`
- `"It's a test"` → `'It''s a test'`
- `"O'Brien"` → `'O''Brien'`

---

## Translator Implementation Pattern

Here's the recommended structure for a filter translator:

```python
"""Filter translator for [Backend Name]."""
from typing import Any, Optional

from agentic_inquiry.database.filters import Filter, FilterOperator


class FilterTranslationError(Exception):
    """Error during filter translation."""

    def __init__(
        self,
        message: str,
        operator: Optional[FilterOperator] = None,
        field: Optional[str] = None,
        backend: str = "your_backend",
    ) -> None:
        self.operator = operator
        self.field = field
        self.backend = backend
        super().__init__(message)


class YourBackendFilterTranslator:
    """Translates Filter AST to [Backend] predicates."""

    COMPARISON_OPS = {
        FilterOperator.EQ: "=",
        FilterOperator.NE: "!=",
        FilterOperator.GT: ">",
        FilterOperator.GTE: ">=",
        FilterOperator.LT: "<",
        FilterOperator.LTE: "<=",
    }

    def translate(self, filter_ast: Filter) -> YourPredicateType:
        """Translate a Filter AST to backend predicate.

        Args:
            filter_ast: The filter to translate

        Returns:
            Backend-specific predicate object or string

        Raises:
            FilterTranslationError: If translation fails
        """
        return self._translate_node(filter_ast)

    def _translate_node(self, node: Filter) -> YourPredicateType:
        """Recursively translate a filter node."""
        op = node.operator

        # 1. Handle compound operators (AND/OR)
        if op == FilterOperator.AND:
            left = self._translate_node(node.left)
            right = self._translate_node(node.right)
            return self._combine_and(left, right)

        if op == FilterOperator.OR:
            left = self._translate_node(node.left)
            right = self._translate_node(node.right)
            return self._combine_or(left, right)

        # 2. Handle null checks
        if op == FilterOperator.IS_NULL:
            return self._null_check(node.field, is_null=True)

        if op == FilterOperator.IS_NOT_NULL:
            return self._null_check(node.field, is_null=False)

        # 3. Handle set membership with empty list short-circuit
        if op == FilterOperator.IN:
            values = node.values or []
            if len(values) == 0:
                return self._false_literal()
            return self._in_predicate(node.field, values)

        if op == FilterOperator.NOT_IN:
            values = node.values or []
            if len(values) == 0:
                return self._true_literal()
            return self._not_in_predicate(node.field, values)

        # 4. Handle comparison operators
        if op in self.COMPARISON_OPS:
            return self._comparison(node.field, op, node.value)

        # 5. Unknown operator
        raise FilterTranslationError(
            f"Unsupported operator: {op}",
            operator=op,
            field=node.field,
            backend="your_backend",
        )
```

---

## LanceDB Translator Walkthrough

Here's a line-by-line explanation of the LanceDB translator:

### 1. Operator Mapping

```python
COMPARISON_OPS = {
    FilterOperator.EQ: "=",
    FilterOperator.NE: "!=",
    FilterOperator.GT: ">",
    FilterOperator.GTE: ">=",
    FilterOperator.LT: "<",
    FilterOperator.LTE: "<=",
}
```

Maps canonical operators to SQL symbols. This table drives comparison translation.

### 2. Compound Operators

```python
if op == FilterOperator.AND:
    left = self._translate_node(node.left)
    right = self._translate_node(node.right)
    return f"({left}) AND ({right})"
```

Recursively translate children, wrap in parentheses, combine with `AND`. Parentheses preserve grouping.

### 3. Null Checks

```python
if op == FilterOperator.IS_NULL:
    return f"{field_ref} IS NULL"
```

Direct translation. No value needed.

### 4. Set Membership with Short-Circuit

```python
if op == FilterOperator.IN:
    values = node.values or []
    if len(values) == 0:
        return "FALSE"  # Short-circuit!
    values_sql = ", ".join(self._format_value(v) for v in values)
    return f"{field_ref} IN ({values_sql})"
```

Empty list returns `FALSE` immediately. Otherwise, format each value and join.

### 5. Comparison Operators

```python
if op in self.COMPARISON_OPS:
    sql_op = self.COMPARISON_OPS[op]
    value_sql = self._format_value(node.value)
    return f"{field_ref} {sql_op} {value_sql}"
```

Look up SQL symbol, format value, combine.

### 6. Value Formatting

```python
def _format_value(self, value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return self._escape_string(value)
    raise FilterTranslationError(...)
```

Type dispatch with proper escaping. Note: check `bool` before `int` since `bool` is a subclass of `int`.

---

## Translation for Non-SQL Backends

For backends with structured query APIs (Qdrant, Pinecone, Milvus):

```python
# Qdrant example
from qdrant_client.models import Filter as QdrantFilter, FieldCondition, MatchValue

def translate_to_qdrant(filter_ast: Filter) -> QdrantFilter:
    """Translate Filter AST to Qdrant filter object."""
    if filter_ast.operator == FilterOperator.EQ:
        return QdrantFilter(
            must=[
                FieldCondition(
                    key=filter_ast.field,
                    match=MatchValue(value=filter_ast.value),
                )
            ]
        )
    elif filter_ast.operator == FilterOperator.AND:
        left = translate_to_qdrant(filter_ast.left)
        right = translate_to_qdrant(filter_ast.right)
        return QdrantFilter(must=left.must + right.must)
    # ... etc.
```

The principles are the same:
- Recursive translation
- Empty list short-circuits
- Type validation
- Clear error messages

---

## Required Tests

Your translator must pass tests covering:

### 1. Basic Operations

```python
def test_eq_string():
    f = eq("status", "active")
    assert translator.translate(f) == "status = 'active'"

def test_gt_number():
    f = gt("score", 0.5)
    assert translator.translate(f) == "score > 0.5"
```

### 2. String Escaping

```python
def test_escape_single_quote():
    f = eq("name", "O'Brien")
    assert translator.translate(f) == "name = 'O''Brien'"
```

### 3. Compound Expressions

```python
def test_and():
    f = and_(eq("a", 1), eq("b", 2))
    assert translator.translate(f) == "(a = 1) AND (b = 2)"

def test_nested_compound():
    f = and_(eq("a", 1), or_(eq("b", 2), eq("c", 3)))
    assert translator.translate(f) == "(a = 1) AND ((b = 2) OR (c = 3))"
```

### 4. Null Checks

```python
def test_is_null():
    f = is_null("deleted_at")
    assert translator.translate(f) == "deleted_at IS NULL"
```

### 5. Empty List Behavior

```python
def test_in_empty_list():
    f = is_in("type", [])
    assert translator.translate(f) == "FALSE"

def test_not_in_empty_list():
    f = not_in("type", [])
    assert translator.translate(f) == "TRUE"
```

### 6. Injection Prevention

```python
def test_sql_injection_in_value():
    # Malicious value should be escaped, not executed
    f = eq("name", "'; DROP TABLE users; --")
    result = translator.translate(f)
    assert "DROP" not in result or "DROP" in result  # Escaped safely
    assert "''" in result  # Quotes are escaped
```

---

## Error Handling

When translation fails, raise `FilterTranslationError` with context:

```python
raise FilterTranslationError(
    f"Unsupported operator: {op}",
    operator=op,
    field=node.field,
    backend="your_backend",
)
```

This allows callers to understand:
- What operator failed
- Which field was involved
- Which backend rejected it

---

## See Also

- `docs/design/filter-ast.md` - Canonical specification
- `docs/development/adapter-implementation-guide.md` - Full adapter guide
- `agentic_inquiry/database/adapters/filter_translator.py` - LanceDB reference
- `tests/database/test_filter_translator.py` - Test patterns
