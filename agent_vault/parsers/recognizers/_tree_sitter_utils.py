"""Language-agnostic tree-sitter traversal helpers.

Shared between recognizers that re-parse their target file to access
details the base ``unified_code`` query drops (annotations, decorators,
DSL-specific syntax). Hoisted out of the first recognizer so that the
second one — FastAPI, Django, C# ASP.NET, whatever comes next —
doesn't copy-paste four tiny functions.

The helpers are intentionally thin: they wrap patterns that tree-sitter
itself already supports, just with names that read better than the raw
bindings (``child_by_field_name``, index into ``.children``, byte-slice
decoding). If you find yourself writing anything more elaborate, push
it into the recognizer that needs it — this module stays small on
purpose.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

# Tree-sitter's Python bindings don't ship a public ``Node`` type
# usable as a runtime annotation (the class is a C extension type,
# and ``tree_sitter.Node`` has varied between binding releases), so
# ``Any`` is the honest choice. The attributes we actually touch —
# ``.children``, ``.type``, ``.start_byte``, ``.end_byte``,
# ``.child_by_field_name`` — are the tree-sitter binding's stable
# surface.
TSNode = Any


def iter_children_of_type(node: TSNode, type_name: str) -> Iterator[TSNode]:
    """Yield direct children of ``node`` whose ``type`` field matches.

    Tree-sitter Python bindings expose ``node.children`` as a list, so
    a generator is fine — no large intermediate list.
    """
    for child in node.children:
        if child.type == type_name:
            yield child


def first_child_of_type(node: TSNode, type_name: str) -> Optional[TSNode]:
    """Return the first direct child whose ``type`` matches, or ``None``.

    Used for lookups where at most one match is expected (e.g. the
    ``modifiers`` block preceding a declaration).
    """
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def node_text(node: TSNode, source: bytes) -> str:
    """Decode the source bytes spanned by ``node``.

    Falls back to replacement characters on malformed UTF-8 rather
    than raising — a recognizer must never crash on a file the base
    parser accepted.
    """
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def identifier_text(node: TSNode, field_name: str, source: bytes) -> str:
    """Return the decoded text of a named field whose value is an identifier.

    Returns ``""`` when the field is absent — callers treat the empty
    string as "no name" and skip the node. Keeps call sites free of
    ``None``-checks.
    """
    target = node.child_by_field_name(field_name)
    if target is None:
        return ""
    return node_text(target, source)


def last_name_segment(qualified: str) -> str:
    """Return the final ``.``-separated segment of a qualified name.

    Useful for matching annotation / decorator names that may be
    written either bare (``@RestController``) or fully qualified
    (``@org.springframework.web.bind.annotation.RestController``).
    ``RestController`` is returned in both cases.
    """
    if not qualified:
        return qualified
    return qualified.rsplit(".", 1)[-1]


__all__ = [
    "TSNode",
    "iter_children_of_type",
    "first_child_of_type",
    "node_text",
    "identifier_text",
    "last_name_segment",
]
