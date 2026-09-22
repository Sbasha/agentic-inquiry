# Filter AST (Canonical Filter Language)

This document defines the unified filter representation (`Filter` AST), its operators, and translation invariants for all database adapters.

## Goals

- One canonical filter language across the codebase (replaces dict/tuple/SQL-string formats).
- Injection-safe translation into backend-native predicates.
- Explicit semantics for `None`, lists, and compound predicates.

## Non-Goals

- Full SQL expressiveness.
- Backend-specific features (geospatial, regex, custom functions).

## Canonical Data Model

### Operators

The canonical operator set is intentionally small and must be implemented (or rejected explicitly) by every adapter:

- `EQ` / `NE`
- `GT` / `GTE` / `LT` / `LTE`
- `IN` / `NOT_IN`
- `IS_NULL` / `IS_NOT_NULL`
- `AND` / `OR` (compound)

Optional operators (only if supported and documented by adapter):

- `CONTAINS` (string contains)
- `STARTS_WITH`, `ENDS_WITH`

### Type Constraints

Filter operands must be one of:
- `str`, `int`, `float`, `bool`, `None`
- `List[str|int|float|bool]` for `IN`/`NOT_IN`

Complex objects (`dict`, nested lists) are not permitted.

## Semantics

### Equality and NULL

- `EQ(field, None)` is **not permitted**; use `IS_NULL(field)` explicitly.
- `NE(field, None)` is **not permitted**; use `IS_NOT_NULL(field)` explicitly.

Rationale: many backends treat `field = NULL` differently or as invalid.

### IN and Empty Lists

- `IN(field, [])` must evaluate to `FALSE` (returns no rows).
- `NOT_IN(field, [])` must evaluate to `TRUE` (no restriction).

Adapters may implement these as short-circuits at the adapter layer.

### AND/OR Precedence

The AST is explicit; there is no implicit precedence. Translation must preserve parentheses and grouping exactly.

## Field Name Validation (Security)

Adapters must validate field names before translation:
- Allowed: `[A-Za-z_][A-Za-z0-9_]*`
- Disallowed: whitespace, quotes, dots, brackets, operators, SQL keywords embedded via punctuation

This is required even if the backend uses structured query APIs—field name injection is still possible in many systems.

## Translation Invariants

Every adapter’s filter translator must satisfy:

- **Safety**: never concatenate unescaped user values into query strings.
- **Correctness**: preserve AND/OR grouping and operator meaning.
- **Determinism**: produce the same predicate for the same AST.
- **Error clarity**: on unsupported operator/type, raise an exception that includes:
  - operator
  - field name
  - backend name

## Suggested Python Shape

The exact implementation is flexible; the following is the intended structure:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Sequence


class FilterOperator(str, Enum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    AND = "and"
    OR = "or"


@dataclass(frozen=True, slots=True)
class Filter:
    operator: FilterOperator
    field: Optional[str] = None
    value: Optional[Any] = None
    values: Optional[Sequence[Any]] = None
    left: Optional["Filter"] = None
    right: Optional["Filter"] = None
```

## Adapter Author Checklist

To implement filters for a new backend:

- Validate field names.
- Validate operand types.
- Translate each operator.
- Implement empty-list behavior for `IN`/`NOT_IN`.
- Add unit tests covering:
  - quoting/escaping (strings with `'`)
  - compound expressions
  - null checks
  - empty list behavior

