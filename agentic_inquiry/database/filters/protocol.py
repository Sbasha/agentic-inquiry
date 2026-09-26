"""Backend-agnostic filter translator protocol.

This is the contract every storage backend implements so the upstream dict
shape (what the facade and MCP tools pass today) and the canonical
:class:`Filter` AST both translate to whatever form the backend's query
layer natively consumes — a WHERE-expression string for LanceDB, a
parameterized ``(sql, params, next_index)`` bundle for Postgres, a Python
predicate for the in-memory provider, an Elasticsearch bool-DSL dict for
a future OpenSearch backend.

The goal is to keep filter semantics identical across backends (the core
operator set is enforced by the AST) while giving each backend the output
shape it prefers — so a filter that works against LanceDB works
identically against Postgres/OpenSearch/Memory with the same dict input.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Optional, Sequence, TypeVar, Union

from agentic_inquiry.database.filters.ast import (
    Filter,
    FilterOperator,
    and_,
    eq,
    gt,
    gte,
    ilike,
    is_in,
    is_not_null,
    is_null,
    like,
    lt,
    lte,
    ne,
    not_in,
    or_,
    validate_field_name,
)


FilterInput = Union[Filter, Dict[str, Any]]
TResult = TypeVar("TResult")


class FilterTranslator(Generic[TResult], ABC):
    """Translate canonical filter input to a backend-native form.

    Contract for implementations:

    - ``translate(None)`` MUST return ``None``.
    - Empty-dict input MUST return ``None`` (no-op; callers short-circuit).
    - Field names MUST be validated via
      :func:`agentic_inquiry.database.filters.ast.validate_field_name` before
      being interpolated into any backend syntax — this is the
      injection-prevention boundary for dict-form inputs.
    - All core operators from
      :class:`agentic_inquiry.database.filters.ast.FilterOperator` MUST be
      supported for both dict and AST inputs:
      ``EQ, NE, GT, GTE, LT, LTE, LIKE, ILIKE, IN, NOT_IN, IS_NULL, IS_NOT_NULL, AND, OR``.
    - ``IN(field, [])`` resolves to FALSE (matches no rows);
      ``NOT_IN(field, [])`` resolves to TRUE (no restriction) — mirrors the
      AST's own validation semantics.

    The output type is backend-specific. Common shapes:

    - :class:`~.lancedb_adapter.LanceDBFilterAdapter` → ``str``
      (a LanceDB ``.where()`` expression).
    - :class:`~.postgres_adapter.PostgresFilterAdapter` → a
      :class:`~.postgres_adapter.PostgresFilter` dataclass carrying the
      SQL fragment, positional params, and the next available placeholder.
    - :class:`~.memory_adapter.MemoryFilterAdapter` → a
      ``Callable[[Dict[str, Any]], bool]`` predicate.
    """

    @abstractmethod
    def translate(self, filters: Optional[FilterInput]) -> Optional[TResult]:
        """Translate ``filters`` to this backend's native representation.

        Returns ``None`` for no-op inputs (``None``, empty dict) so callers
        can easily skip emitting a WHERE clause.
        """


def normalize_to_ast(filters: Optional[FilterInput]) -> Optional[Filter]:
    """Coerce an upstream filter input to a :class:`Filter` AST or ``None``.

    Accepts:

    - ``None`` or empty dict → ``None``.
    - An already-built :class:`Filter` → returned unchanged.
    - A dict in the legacy shape (see :func:`translate_dict_filters`):
      ``{"field": value}``, ``{"field": (op, value)}``, ``{"field": [list]}``,
      ``{"OR": [...]}``, ``{"NOT": {...}}``, ``{"field": None}``. All
      field-name validation is deferred to the AST constructor.

    Centralizing the dict→AST step lets every backend translator share the
    same normalization and reuse the AST's validation instead of
    reimplementing operator dispatch per backend.
    """
    if filters is None:
        return None
    if isinstance(filters, Filter):
        return filters
    if not filters:
        return None

    parts: List[Filter] = []
    for key, value in filters.items():
        upper_key = key.upper()

        if upper_key == "OR":
            sub_asts: List[Filter] = []
            for option in value:
                translated = normalize_to_ast(option)
                if translated is not None:
                    sub_asts.append(translated)
            if sub_asts:
                parts.append(sub_asts[0] if len(sub_asts) == 1 else or_(*sub_asts))
            continue

        if upper_key == "NOT":
            negated = _negate_dict(value)
            if negated is not None:
                parts.append(negated)
            continue

        parts.append(_field_to_ast(key, value))

    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return and_(*parts)


def _field_to_ast(field: str, value: Any) -> Filter:
    """Build a :class:`Filter` AST node for a single ``{field: value}`` entry.

    Covers the tuple-operator, implicit-IN, and IS_NULL cases that the
    legacy dict format supports.
    """
    validate_field_name(field)

    # Tuple shape: (operator, operand)
    if isinstance(value, tuple) and len(value) == 2:
        op_raw, operand = value
        op_upper = str(op_raw).upper().strip()

        if op_upper == "IN":
            operand_list = _as_list(operand)
            return is_in(field, operand_list)

        if op_upper in ("NOT IN", "NOTIN"):
            operand_list = _as_list(operand)
            return not_in(field, operand_list)

        if operand is None:
            if op_upper in ("=", "==", "IS", "EQ"):
                return is_null(field)
            if op_upper in ("!=", "<>", "IS NOT", "NE"):
                return is_not_null(field)
            raise ValueError(
                f"NULL operand only valid with equality operators; got {op_raw!r}"
            )

        if op_upper in ("=", "==", "EQ"):
            return eq(field, operand)
        if op_upper in ("!=", "<>", "NE"):
            return ne(field, operand)
        if op_upper in (">", "GT"):
            return gt(field, operand)
        if op_upper in (">=", "GTE"):
            return gte(field, operand)
        if op_upper in ("<", "LT"):
            return lt(field, operand)
        if op_upper in ("<=", "LTE"):
            return lte(field, operand)
        if op_upper == "LIKE":
            return like(field, str(operand))
        if op_upper == "ILIKE":
            return ilike(field, str(operand))

        raise ValueError(
            f"Unsupported operator {op_raw!r} for field {field!r}. "
            f"Expected one of: =, !=, >, >=, <, <=, LIKE, ILIKE, IN, NOT IN, IS, IS NOT."
        )

    # Implicit IN: {"field": [v1, v2, ...]}
    if isinstance(value, list):
        return is_in(field, value)

    # Bare None → IS NULL
    if value is None:
        return is_null(field)

    return eq(field, value)


def _negate_dict(value: Any) -> Optional[Filter]:
    """Translate ``{"NOT": <inner>}`` legacy shape into an AST.

    The canonical AST has no standalone NOT node, but negation distributes
    cleanly over the supported operators (``EQ ↔ NE``, ``IN ↔ NOT_IN``,
    ``IS_NULL ↔ IS_NOT_NULL``, and ``AND/OR`` swap under De Morgan). For the
    small set of legacy ``{"NOT": ...}`` uses this is enough; compound-NOT
    over arbitrary trees is intentionally out of scope.
    """
    inner = normalize_to_ast(value)
    if inner is None:
        return None
    return _negate_ast(inner)


def _negate_ast(node: Filter) -> Filter:
    op = node.operator

    # De Morgan cases — compound nodes have no field.
    if op == FilterOperator.AND:
        assert node.left is not None and node.right is not None
        return or_(_negate_ast(node.left), _negate_ast(node.right))
    if op == FilterOperator.OR:
        assert node.left is not None and node.right is not None
        return and_(_negate_ast(node.left), _negate_ast(node.right))

    # Non-compound operators: AST validation guarantees ``field`` is set and
    # (for EQ/NE/comparisons) ``value`` is non-None. Narrow with asserts so
    # the builders below get strict types without ``# type: ignore``.
    assert node.field is not None, f"{op} filter without field"
    field = node.field

    if op in (FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL):
        return is_not_null(field) if op == FilterOperator.IS_NULL else is_null(field)

    if op == FilterOperator.IN:
        return not_in(field, list(node.values or []))
    if op == FilterOperator.NOT_IN:
        return is_in(field, list(node.values or []))

    assert node.value is not None, f"{op} filter without value"
    value = node.value

    if op == FilterOperator.EQ:
        return ne(field, value)
    if op == FilterOperator.NE:
        return eq(field, value)
    if op == FilterOperator.GT:
        return lte(field, value)
    if op == FilterOperator.GTE:
        return lt(field, value)
    if op == FilterOperator.LT:
        return gte(field, value)
    if op == FilterOperator.LTE:
        return gt(field, value)

    raise ValueError(f"Cannot negate filter with operator {op}")


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    # Be lenient: a scalar in IN position becomes a single-element list.
    return [value]


__all__ = [
    "FilterInput",
    "FilterTranslator",
    "normalize_to_ast",
]
