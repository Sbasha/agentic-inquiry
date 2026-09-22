"""In-memory predicate-based filter adapter.

The in-memory storage provider matches rows in Python rather than delegating
to a database engine, so its translator output is a ``Callable`` that takes
a row-dict and returns whether it matches. This replaces the ad-hoc
``_matches_filters`` logic previously embedded in
:mod:`agentic_inquiry.storage.providers.memory` and gives the in-memory
provider the same operator coverage as Postgres/LanceDB.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Callable, Dict, Optional, Pattern

from agentic_inquiry.database.filters.ast import Filter, FilterOperator
from agentic_inquiry.database.filters.protocol import (
    FilterInput,
    FilterTranslator,
    normalize_to_ast,
)

logger = logging.getLogger(__name__)


Predicate = Callable[[Dict[str, Any]], bool]


class MemoryFilterAdapter(FilterTranslator[Predicate]):
    """Compile filters into a Python predicate over row dicts.

    Supports nested field access via dot notation (``metadata.type``) the
    same way the AST validator allows it — looks up ``row["metadata"]
    ["type"]``. Missing fields evaluate to ``None`` for comparison purposes.
    """

    def translate(self, filters: Optional[FilterInput]) -> Optional[Predicate]:
        ast = normalize_to_ast(filters)
        if ast is None:
            return None
        return _compile(ast)


def _compile(node: Filter) -> Predicate:
    op = node.operator

    if op == FilterOperator.AND:
        assert node.left is not None and node.right is not None
        left = _compile(node.left)
        right = _compile(node.right)
        return lambda row: left(row) and right(row)

    if op == FilterOperator.OR:
        assert node.left is not None and node.right is not None
        left = _compile(node.left)
        right = _compile(node.right)
        return lambda row: left(row) or right(row)

    assert node.field is not None
    field_path = node.field.split(".")

    def get_field(row: Dict[str, Any]) -> Any:
        value: Any = row
        for segment in field_path:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get(segment)
            else:
                value = getattr(value, segment, None)
        return value

    if op == FilterOperator.IS_NULL:
        return lambda row: get_field(row) is None
    if op == FilterOperator.IS_NOT_NULL:
        return lambda row: get_field(row) is not None

    if op == FilterOperator.IN:
        values = set(node.values or [])
        if not values:
            return lambda row: False
        return lambda row: get_field(row) in values
    if op == FilterOperator.NOT_IN:
        values = set(node.values or [])
        if not values:
            return lambda row: True
        return lambda row: get_field(row) not in values

    target = node.value
    if op == FilterOperator.EQ:
        return lambda row: get_field(row) == target
    if op == FilterOperator.NE:
        return lambda row: get_field(row) != target
    if op == FilterOperator.GT:
        return lambda row: _lt(target, get_field(row))
    if op == FilterOperator.GTE:
        return lambda row: _le(target, get_field(row))
    if op == FilterOperator.LT:
        return lambda row: _lt(get_field(row), target)
    if op == FilterOperator.LTE:
        return lambda row: _le(get_field(row), target)

    if op in (FilterOperator.LIKE, FilterOperator.ILIKE):
        assert isinstance(target, str)  # AST validates pattern type
        regex = _like_to_regex(target, case_insensitive=(op == FilterOperator.ILIKE))
        return lambda row: _match_regex(regex, get_field(row))

    raise ValueError(f"Unsupported operator for memory predicate: {op}")


def _match_regex(regex: Pattern[str], value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return regex.fullmatch(value) is not None


@lru_cache(maxsize=256)
def _like_to_regex(pattern: str, *, case_insensitive: bool) -> Pattern[str]:
    """Translate a SQL LIKE pattern to a Python regex.

    - ``%`` → ``.*`` (zero or more of any character).
    - ``_`` → ``.`` (single character).
    - Every other char is regex-escaped. ``\\%`` and ``\\_`` literal escapes
      are recognized (standard SQL LIKE escape).
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern) and pattern[i + 1] in ("%", "_"):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
        i += 1
    flags = re.DOTALL | (re.IGNORECASE if case_insensitive else 0)
    return re.compile("".join(out), flags)


def _lt(a: Any, b: Any) -> bool:
    """Safe strict-less-than that returns False for incomparable values.

    Incomparable cross-type operands are almost always a schema mismatch
    (e.g. comparing a string to an int because the field changed type).
    Returning ``False`` keeps the query running, but emit a debug log so
    the mismatch is diagnosable without turning filter evaluation into an
    exception.
    """
    if a is None or b is None:
        return False
    try:
        return a < b  # type: ignore[operator]
    except TypeError:
        logger.debug(
            "Incomparable operand types in filter predicate: %s vs %s",
            type(a).__name__,
            type(b).__name__,
        )
        return False


def _le(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    try:
        return a <= b  # type: ignore[operator]
    except TypeError:
        logger.debug(
            "Incomparable operand types in filter predicate: %s vs %s",
            type(a).__name__,
            type(b).__name__,
        )
        return False


__all__ = ["MemoryFilterAdapter", "Predicate"]
