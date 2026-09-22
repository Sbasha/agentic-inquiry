"""Postgres-dialect filter translator emitting parameterized SQL.

Unlike LanceDB's string-form ``.where()`` clauses, asyncpg needs
positional placeholders (``$1``, ``$2``, …) so the query planner can
reuse plans and values are bound safely out-of-band. This adapter walks
the canonical :class:`Filter` AST and emits a fragment + param list +
next-available-index bundle that Postgres callers splice into their own
query.

Field names are validated via ``validate_field_name`` before they reach
SQL — the old ``_build_filter_clause`` in ``postgresql/vector.py`` did
not, which was an injection hole for anyone building dict filters from
user input. This adapter closes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from agent_vault.database.filters.ast import (
    Filter,
    FilterOperator,
    validate_field_name,
)
from agent_vault.database.filters.protocol import (
    FilterInput,
    FilterTranslator,
    normalize_to_ast,
)


@dataclass(frozen=True)
class PostgresFilter:
    """The parameterized-SQL translation result for a Postgres backend.

    Attributes:
        where_sql: A SQL fragment prefixed with ``AND`` so it can be
            appended to an existing ``WHERE ...`` clause directly. The
            caller is expected to have a leading condition (e.g.
            ``project_id = $1``) and just concatenate. Never empty — if
            the filter is a no-op, :meth:`PostgresFilterAdapter.translate`
            returns ``None`` instead of constructing this value.
        params: Positional parameter values already ordered to match the
            placeholders in ``where_sql``, starting from ``start_index``.
        next_index: The first placeholder number NOT used by this filter.
            Callers splice their own subsequent params (e.g. ``LIMIT``)
            starting from this index to avoid collision.
    """

    where_sql: str
    params: List[Any]
    next_index: int


class PostgresFilterAdapter(FilterTranslator[PostgresFilter]):
    """Translate dict or AST filters to parameterized Postgres SQL.

    Supports the full canonical operator set (EQ, NE, GT, GTE, LT, LTE, IN,
    NOT_IN, IS_NULL, IS_NOT_NULL, AND, OR). Empty-list ``IN`` resolves to
    ``FALSE`` and empty-list ``NOT_IN`` to ``TRUE``, matching the AST
    semantics and the legacy dict translator.

    The ``table_alias`` constructor arg prefixes every field reference with
    ``{alias}.``. Needed for multi-table JOINs (e.g. the server-side
    vector-search path joins chunks with a separate embeddings table).

    Use :meth:`translate` for single-filter cases and :meth:`bind` when
    splicing into a query that already consumes placeholders.
    """

    def __init__(
        self,
        *,
        table_alias: str = "",
        field_map: Optional[Mapping[str, str]] = None,
    ) -> None:
        """Configure the translator.

        Args:
            table_alias: Prefix every field reference with ``{alias}.`` —
                needed for multi-table JOINs.
            field_map: Optional model-field → column-name rename map. The
                graph provider uses this for ``{"type": "entity_type"}`` /
                ``{"type": "relationship_type"}`` so callers can pass the
                model-level field name while the adapter emits the real
                column in SQL.
        """
        self._prefix = f"{table_alias}." if table_alias else ""
        self._field_map: Dict[str, str] = dict(field_map or {})

    def translate(self, filters: Optional[FilterInput]) -> Optional[PostgresFilter]:
        return self.bind(filters, start_index=1)

    def bind(
        self,
        filters: Optional[FilterInput],
        *,
        start_index: int = 1,
    ) -> Optional[PostgresFilter]:
        """Translate with an explicit starting placeholder index.

        Example::

            # caller has $1 = project_id, $2 = limit already
            result = adapter.bind(filters, start_index=3)
            if result:
                query = f"SELECT ... WHERE project_id = $1 {result.where_sql} LIMIT $2"
                params = [project_id, limit, *result.params]
        """
        ast = normalize_to_ast(filters)
        if ast is None:
            return None

        state = _BindState(start_index=start_index, prefix=self._prefix)
        expr = self._walk(ast, state)
        if not expr:
            return None
        return PostgresFilter(
            where_sql=f"AND {expr}",
            params=state.params,
            next_index=state.start_index + len(state.params),
        )

    def _walk(self, node: Filter, state: "_BindState") -> str:
        op = node.operator

        if op == FilterOperator.AND:
            assert node.left is not None and node.right is not None
            left = self._walk(node.left, state)
            right = self._walk(node.right, state)
            return f"({left} AND {right})"
        if op == FilterOperator.OR:
            assert node.left is not None and node.right is not None
            left = self._walk(node.left, state)
            right = self._walk(node.right, state)
            return f"({left} OR {right})"

        assert node.field is not None  # non-compound ops always carry a field
        validate_field_name(node.field)
        # Dotted field names (``metadata.type``) are valid in the canonical
        # AST (LanceDB/memory can use them for JSON access), but Postgres
        # needs explicit JSON operators (``metadata->>'type'``) — rejecting
        # them here is safer than emitting broken SQL. Apply JSON translation
        # in a follow-up if we need that.
        if "." in node.field:
            raise ValueError(
                f"Dotted field names are not supported by the Postgres filter "
                f"adapter: {node.field!r}. Use explicit JSON operators in a "
                f"custom WHERE clause if you need JSONB access."
            )
        mapped = self._field_map.get(node.field, node.field)
        column = f"{state.prefix}{mapped}"

        if op == FilterOperator.IS_NULL:
            return f"{column} IS NULL"
        if op == FilterOperator.IS_NOT_NULL:
            return f"{column} IS NOT NULL"

        if op == FilterOperator.IN:
            values = list(node.values or [])
            if not values:
                return "FALSE"
            placeholders = [state.bind_param(v) for v in values]
            return f"{column} IN ({', '.join(placeholders)})"
        if op == FilterOperator.NOT_IN:
            values = list(node.values or [])
            if not values:
                return "TRUE"
            placeholders = [state.bind_param(v) for v in values]
            return f"{column} NOT IN ({', '.join(placeholders)})"

        # Comparison operators
        sql_op = _COMPARISON_SQL[op]
        placeholder = state.bind_param(node.value)
        return f"{column} {sql_op} {placeholder}"


_COMPARISON_SQL = {
    FilterOperator.EQ: "=",
    FilterOperator.NE: "!=",
    FilterOperator.GT: ">",
    FilterOperator.GTE: ">=",
    FilterOperator.LT: "<",
    FilterOperator.LTE: "<=",
    FilterOperator.LIKE: "LIKE",
    FilterOperator.ILIKE: "ILIKE",
}


@dataclass
class _BindState:
    start_index: int
    prefix: str
    params: List[Any] = field(default_factory=list)

    def bind_param(self, value: Any) -> str:
        """Reserve the next placeholder and append the value to params."""
        self.params.append(value)
        return f"${self.start_index + len(self.params) - 1}"


__all__ = [
    "PostgresFilter",
    "PostgresFilterAdapter",
]
