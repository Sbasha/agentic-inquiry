"""LanceDB filter adapter implementing the shared translator protocol.

LanceDB's ``.where()`` accepts a SQL-style WHERE expression string. The
heavy lifting already lives in :mod:`translator` (AST → SQL) and
:mod:`dict_translator` (dict → SQL); this adapter wraps them so LanceDB
satisfies the same :class:`FilterTranslator` contract as Postgres and
the in-memory provider.

The existing ``LanceDBFilterTranslator`` class in ``translator.py`` is
the AST-walker implementation (historical name); this module exposes
the *protocol-shaped* entry point.
"""

from __future__ import annotations

from typing import Optional

from agent_vault.database.filters.protocol import (
    FilterInput,
    FilterTranslator,
    normalize_to_ast,
)
from agent_vault.database.filters.translator import translate_filter


class LanceDBFilterAdapter(FilterTranslator[str]):
    """Produce a LanceDB ``.where()`` expression from dict or AST input.

    Both dict and AST inputs are routed through :func:`normalize_to_ast`
    before being rendered. This is deliberate: the legacy
    :func:`translate_dict_filters` path interpolated the operator from a
    ``(op, value)`` tuple verbatim into SQL, which meant a crafted
    operator string (e.g. ``("= 1) OR TRUE --", "x")``) could bypass
    validation. Going through the AST forces every operator to come from
    the whitelisted :class:`FilterOperator` enum before it reaches the
    renderer.
    """

    def translate(self, filters: Optional[FilterInput]) -> Optional[str]:
        ast = normalize_to_ast(filters)
        if ast is None:
            return None
        return translate_filter(ast)


__all__ = ["LanceDBFilterAdapter"]
