"""Express recognizer for TypeScript.

Adds ``express_route`` relationships for Express HTTP route
registrations. Unlike Spring / NestJS, Express declares routes by
**call expressions** rather than decorators:

.. code-block:: typescript

    app.get('/users/:id', getUserHandler);
    app.post('/users', (req, res) => { ... });
    router.delete('/:id', middleware, removeUser);
    app.use('/api/v1', router);  // mount point

The base TypeScript parser emits the call expressions as generic
function calls; the routing semantics live only in conventions
(``<verb>(path, ...handlers)`` where the verb matches HTTP). This
recognizer makes those semantics explicit.

**What it captures.**

``<receiver>.<verb>(path, ...handlers)`` for all eight Express
verbs (``get``, ``post``, ``put``, ``delete``, ``patch``,
``options``, ``head``, ``all``). ``all`` emits ``"ANY"``. The
receiver name (``app`` vs ``router`` vs any other variable) lands
in ``metadata["receiver"]``.

Same-file router mounting — ``app.use('/prefix', routerVar)`` —
is resolved by a prepass that builds a ``{router_var_name:
prefix}`` table. First mount wins when a router is mounted
multiple times.

**What it does NOT do.**

- Cross-file router mounting (per-file recognizer).
- Method chains (``app.route('/x').get(handler)``) — would need
  callee-type inference.
- Dynamic verb registration (``app[method](...)``).
- ``.js`` files (TypeScript grammar only).

**Handler attribution.**

Named handler (``identifier`` or ``member_expression``): route
attaches to the chunk whose ``element_name`` / ``symbol_metadata``
matches the handler name. Anonymous handler (arrow function):
``source_name`` becomes ``<anonymous>@L{line}`` so multiple inline
handlers in a file stay distinct downstream, and the range-fallback
tier attaches the edge to the enclosing function / module chunk.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterator, List, Optional, Tuple

from ._http_route import HTTPRouteRecognizer, _Route, join_paths
from ._tree_sitter_utils import (
    TSNode,
    last_name_segment,
    node_text,
)


# HTTP-verb methods Express recognises. ``use`` is handled separately
# as a mount point, not a route.
_VERB_METHODS: Dict[str, str] = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
    "patch": "PATCH",
    "options": "OPTIONS",
    "head": "HEAD",
    "all": "ANY",
}


# Sentinel prefix used in the ``source_name`` slot when a route's
# handler is an inline lambda / function expression (no stable name
# to reference). Routes tag the exact call-site line onto the prefix
# (``<anonymous>@L42``) so downstream graph builders that derive
# ``source_id`` from ``(type, file_path, source_name)`` don't collapse
# multiple inline handlers in the same file onto a single node.
_ANONYMOUS_HANDLER = "<anonymous>"


def _anonymous_handler_name(line: int) -> str:
    """Format the anonymous-handler source_name for a given call line.

    Callers that need "is this anonymous?" use
    ``name.startswith(_ANONYMOUS_HANDLER)`` — the ``<`` character
    can't start a TypeScript identifier, so the prefix never
    collides with a real named handler.
    """
    return f"{_ANONYMOUS_HANDLER}@L{line}"


class TypeScriptExpressRecognizer(HTTPRouteRecognizer):
    """Recognizer that adds Express HTTP route edges to TypeScript
    documents.
    """

    name = "typescript_express"
    file_extensions: FrozenSet[str] = frozenset({".ts"})

    _relationship_type = "express_route"
    _framework_name = "express"
    _tree_sitter_language = "typescript"

    # Pre-filter markers. An Express project imports the library by
    # its package name exactly once, typically via ``from 'express'``
    # or ``require('express')``. Matching the quoted form rules out
    # false positives from variable names or free-text mentions.
    _pre_filter_markers = (
        b"'express'",
        b'"express"',
    )

    # Same handler on different receivers (``app.get('/x', h)`` vs
    # ``router.get('/x', h)``) must stay as two distinct edges —
    # the ``receiver`` metadata disambiguates.
    _extra_dedup_metadata_keys = ("receiver",)

    def _extract_routes(self, root_node: TSNode, source: bytes) -> List[_Route]:
        """Two-pass walk: mount table prepass, then route emission."""
        mount_prefixes: Dict[str, str] = {}
        for call in _walk_call_expressions(root_node):
            receiver, method = _call_receiver_method(call, source)
            if method != "use":
                continue
            args = call.child_by_field_name("arguments")
            if args is None:
                continue
            prefix = _first_string_arg(args, source)
            router_ref = _last_identifier_arg(args, source)
            if prefix is not None and router_ref is not None:
                mount_prefixes.setdefault(router_ref, prefix)

        routes: List[_Route] = []
        for call in _walk_call_expressions(root_node):
            receiver, method = _call_receiver_method(call, source)
            if method is None or method not in _VERB_METHODS:
                continue
            args = call.child_by_field_name("arguments")
            if args is None:
                continue
            path = _first_string_arg(args, source)
            if path is None:
                # No string path — not a registration we can resolve.
                continue
            handler = _extract_handler(args, source)
            call_line = call.start_point[0] + 1
            if handler == _ANONYMOUS_HANDLER:
                # Tag anonymous handlers with their call-site line
                # so multiple inline handlers stay distinct downstream.
                handler = _anonymous_handler_name(call_line)
            mount = mount_prefixes.get(receiver or "", "")
            routes.append(
                _Route(
                    source_name=handler,
                    source_line=call_line,
                    http_method=_VERB_METHODS[method],
                    path=join_paths(mount, path),
                    metadata={
                        "receiver": receiver or "",
                        "mount_prefix": mount,
                    },
                )
            )

        return routes


# ---------------------------------------------------------------------------
# Call-expression walking helpers
# ---------------------------------------------------------------------------


def _walk_call_expressions(node: TSNode) -> Iterator[TSNode]:
    """Yield every ``call_expression`` descendant of ``node``.

    Recursive so routes declared inside ``setupRoutes()`` functions,
    ``if`` blocks, or module-level IIFEs are all found.
    """
    if node.type == "call_expression":
        yield node
    for child in node.children:
        yield from _walk_call_expressions(child)


def _call_receiver_method(
    call: TSNode, source: bytes
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(receiver_name, method_name)`` for ``receiver.method(...)``.

    ``(None, None)`` when the callee isn't a simple member expression.
    Receiver is the bare identifier — for qualified forms
    (``express.Router.get``), take the last segment of the object
    expression (``Router``).
    """
    fn = call.child_by_field_name("function")
    if fn is None or fn.type != "member_expression":
        return None, None
    obj = fn.child_by_field_name("object")
    prop = fn.child_by_field_name("property")
    if prop is None or prop.type != "property_identifier":
        return None, None
    method_name = node_text(prop, source)

    if obj is None:
        return None, method_name
    if obj.type == "identifier":
        return node_text(obj, source), method_name
    if obj.type == "member_expression":
        obj_prop = obj.child_by_field_name("property")
        if obj_prop is not None and obj_prop.type == "property_identifier":
            return node_text(obj_prop, source), method_name
        return last_name_segment(node_text(obj, source)), method_name
    # Other shapes (call chains like ``app.route('/x').get(...)``)
    # aren't first-class receivers for mount purposes.
    return None, method_name


def _first_string_arg(args_node: TSNode, source: bytes) -> Optional[str]:
    """Return the first string-literal argument's text, without quotes."""
    for arg in args_node.children:
        literal = _literal_string_value(arg, source)
        if literal is not None:
            return literal
    return None


def _last_identifier_arg(args_node: TSNode, source: bytes) -> Optional[str]:
    """Return the last identifier-like arg's text.

    Used for the router-mount prepass: ``app.use('/prefix',
    someRouter)`` — we want ``someRouter`` regardless of middleware
    before it. For ``module.exports.router``, take the last segment.
    """
    last: Optional[str] = None
    for arg in args_node.children:
        if arg.type == "identifier":
            last = node_text(arg, source)
        elif arg.type == "member_expression":
            last = last_name_segment(node_text(arg, source))
    return last


def _extract_handler(args_node: TSNode, source: bytes) -> str:
    """Return the route handler identifier or ``<anonymous>``.

    Iterates arguments and keeps the last handler-looking arg — an
    ``identifier``, ``member_expression``, or function expression.
    Path strings and non-handler types are ignored. Async arrow
    functions parse as ``arrow_function`` too.
    """
    last_handler = _ANONYMOUS_HANDLER
    for arg in args_node.children:
        if arg.type == "identifier":
            last_handler = node_text(arg, source)
        elif arg.type == "member_expression":
            last_handler = last_name_segment(node_text(arg, source))
        elif arg.type in ("arrow_function", "function_expression"):
            last_handler = _ANONYMOUS_HANDLER
    return last_handler


def _literal_string_value(node: TSNode, source: bytes) -> Optional[str]:
    """Return the inside of a ``string`` / simple ``template_string``.

    Interpolated templates return ``None`` — emitting a truncated
    fragment would be silently wrong.
    """
    if node.type == "string":
        return _string_fragment_text(node, source)
    if node.type == "template_string":
        for child in node.children:
            if child.type == "template_substitution":
                return None
        return _string_fragment_text(node, source)
    return None


def _string_fragment_text(node: TSNode, source: bytes) -> str:
    """Return a string/template literal's inner text via raw source span.

    Escape sequences split the literal across multiple
    ``string_fragment`` + ``escape_sequence`` children; taking the
    raw span minus the surrounding quote tokens preserves the source
    form verbatim.
    """
    raw = node_text(node, source)
    if len(raw) < 2:
        return ""
    return raw[1:-1]
