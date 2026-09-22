"""FastAPI recognizer for Python.

Adds ``fastapi_route`` relationships for FastAPI HTTP route
handlers. Decorator-driven registration much like Spring / NestJS,
but with an Express-style receiver model (``app`` vs ``router``)
for mount-prefix composition.

**What it captures.**

- Standard HTTP verb decorators: ``@app.get(...)``, ``@app.post``,
  ``@app.put``, ``@app.delete``, ``@app.patch``, ``@app.options``,
  ``@app.head``. Same verbs on ``@router.<verb>``.
- ``APIRouter(prefix="/x")`` — the router's declared prefix is
  picked up in the prepass and applied to routes on that router.
- ``app.include_router(router, prefix="/mount")`` — the mount
  prefix prepends the router's own prefix so the final path is
  ``"/mount" + "/x" + handler_path`` (matching FastAPI's runtime
  resolution).
- Both sync and ``async def`` handlers — tree-sitter parses them
  identically (``async`` is a modifier on ``function_definition``).
- Qualified decorator receivers (``@my_module.app.get(...)``) —
  the receiver resolves to the last segment of the attribute
  chain.

**What it does NOT do.**

- ``@app.api_route("/x", methods=["GET", "POST"])`` — the generic
  form with explicit verb list. Rare in practice (most code uses
  the specific decorators). Would need extra kwarg parsing.
- ``@app.websocket("/ws")`` — WebSocket routes are a distinct
  edge kind; would deserve its own relationship type.
- Cross-file router mounting. A router defined in one file and
  mounted in another won't have its mount prefix applied during
  per-file analysis.
- Non-literal paths — ``@app.get(USERS_PATH)`` with a constant
  reference. We capture only string literals.
- Nested router composition — ``app.include_router(outer)`` where
  ``outer`` itself includes other routers. We apply one mount
  level per router.

**Implementation.**

Subclass of :class:`HTTPRouteRecognizer`. The base owns pre-filter,
parser loading, chunk matching, and dedup. This file contributes
Python AST extraction: a two-pass walk (router prefix table,
mount table) followed by decorator extraction.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterator, List, Optional, Tuple

from ._http_route import HTTPRouteRecognizer, _Route, join_paths
from ._tree_sitter_utils import (
    TSNode,
    last_name_segment,
    node_text,
)


_VERB_METHODS: Dict[str, str] = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
    "patch": "PATCH",
    "options": "OPTIONS",
    "head": "HEAD",
}


class PythonFastAPIRecognizer(HTTPRouteRecognizer):
    """Recognizer that adds FastAPI HTTP route edges to Python files."""

    name = "python_fastapi"
    file_extensions: FrozenSet[str] = frozenset({".py"})

    _relationship_type = "fastapi_route"
    _framework_name = "fastapi"
    _tree_sitter_language = "python"

    # Pre-filter markers:
    # - ``fastapi`` catches the canonical ``from fastapi import`` line.
    # - ``FastAPI`` catches the app constructor even under a wrapper
    #   package that doesn't carry the ``fastapi`` string literally.
    # - ``APIRouter`` catches router-only files (a ``routers/users.py``
    #   that declares endpoints but doesn't instantiate ``FastAPI``).
    _pre_filter_markers = (
        b"fastapi",
        b"FastAPI",
        b"APIRouter",
    )

    # Same handler registered on ``app`` vs a distinct ``router``
    # should stay as separate edges — matches Express's receiver
    # dedup semantics.
    _extra_dedup_metadata_keys = ("receiver",)

    def _extract_routes(self, root_node: TSNode, source: bytes) -> List[_Route]:
        # Pass 1: find routers declared with ``APIRouter(prefix="/x")``.
        # We key the table by receiver identifier so the subsequent
        # route-walking pass can look up a router's prefix without a
        # separate scope resolver.
        router_prefixes: Dict[str, str] = {}
        for assignment in _walk_type(root_node, "assignment"):
            var_name = _assignment_target_name(assignment, source)
            call_node = _assignment_call_rhs(assignment)
            if not var_name or call_node is None:
                continue
            callee = _call_callee_name(call_node, source)
            if last_name_segment(callee) != "APIRouter":
                continue
            prefix = _call_kwarg_string(call_node, "prefix", source)
            if prefix:
                # Normalise via ``join_paths`` so a prefix written
                # without a leading slash (``prefix="api/v1"``) or
                # with a trailing one (``prefix="/api/v1/"``) ends
                # up in the consistent ``"/api/v1"`` form. Keeps
                # the ``metadata["mount_prefix"]`` that lands on
                # relationships stable across input styles.
                router_prefixes[var_name] = join_paths(prefix, "")

        # Pass 2: combine router prefixes with any ``app.include_router``
        # mount prefixes. FastAPI runtime resolution is
        # ``mount_prefix + router_prefix`` — we follow the same, using
        # ``join_paths`` so a stray trailing slash in either half
        # doesn't leak a ``//`` into the metadata.
        mount_prefixes: Dict[str, str] = dict(router_prefixes)
        for call in _walk_type(root_node, "call"):
            _, method = _call_receiver_method(call, source)
            if method != "include_router":
                continue
            args = call.child_by_field_name("arguments")
            if args is None:
                continue
            router_ref = _first_identifier_arg(args, source)
            if router_ref is None:
                continue
            mount_prefix = _call_kwarg_string(call, "prefix", source) or ""
            if not mount_prefix:
                # No additional mount; any APIRouter(prefix=...) is
                # already in ``mount_prefixes`` via the copy above.
                continue
            existing = router_prefixes.get(router_ref, "")
            # ``join_paths`` on both sides (with an empty second
            # half when there's no existing router prefix)
            # normalises leading/trailing slashes consistently.
            mount_prefixes[router_ref] = join_paths(mount_prefix, existing)

        # Pass 3: walk decorated function definitions for the
        # actual route emission.
        routes: List[_Route] = []
        for dec_def in _walk_type(root_node, "decorated_definition"):
            func = _function_definition_of(dec_def)
            if func is None:
                continue
            func_name = _function_name(func, source)
            if not func_name:
                continue
            func_line = func.start_point[0] + 1

            for decorator in _iter_decorators(dec_def):
                receiver, method = _decorator_receiver_method(decorator, source)
                if method is None or method not in _VERB_METHODS:
                    continue
                path = _decorator_first_string(decorator, source)
                if path is None:
                    continue
                mount = mount_prefixes.get(receiver or "", "")
                routes.append(
                    _Route(
                        source_name=func_name,
                        source_line=func_line,
                        http_method=_VERB_METHODS[method],
                        path=join_paths(mount, path),
                        metadata={
                            "receiver": receiver or "",
                            "mount_prefix": mount,
                        },
                    )
                )
                # One verb decorator per function is the norm;
                # if multiple verb decorators are stacked (rare,
                # but legal) we let the loop continue and emit
                # one route per verb.

        return routes


# ---------------------------------------------------------------------------
# Python AST helpers
# ---------------------------------------------------------------------------


def _walk_type(node: TSNode, type_name: str) -> Iterator[TSNode]:
    """Yield every descendant of ``node`` with the given ``type``.

    Recursive so router assignments nested inside ``if
    TYPE_CHECKING`` blocks, route decorators inside
    ``setup_routes()`` functions, and so on are all found. Small
    per-file cost.
    """
    if node.type == type_name:
        yield node
    for child in node.children:
        yield from _walk_type(child, type_name)


def _assignment_target_name(assignment: TSNode, source: bytes) -> Optional[str]:
    """Return the LHS identifier of ``x = ...`` assignments.

    Tree-sitter Python uses the ``left`` field for the assignment
    target. Only single-name targets are useful here; tuple /
    pattern assignments aren't how routers are declared in
    practice.
    """
    left = assignment.child_by_field_name("left")
    if left is None or left.type != "identifier":
        return None
    return node_text(left, source)


def _assignment_call_rhs(assignment: TSNode) -> Optional[TSNode]:
    """Return the ``call`` on the RHS of an assignment, or ``None``
    when the RHS isn't a call expression."""
    right = assignment.child_by_field_name("right")
    if right is None or right.type != "call":
        return None
    return right


def _call_callee_name(call: TSNode, source: bytes) -> str:
    """Return the callee identifier (handles qualified attributes).

    ``FastAPI()`` → ``"FastAPI"``. ``fastapi.FastAPI()`` →
    ``"fastapi.FastAPI"`` (caller applies ``last_name_segment``).
    """
    fn = call.child_by_field_name("function")
    if fn is None:
        return ""
    return node_text(fn, source)


def _call_receiver_method(
    call: TSNode, source: bytes
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(receiver_name, method_name)`` for ``receiver.method(...)``.

    Python tree-sitter exposes ``attribute`` nodes with ``object``
    and ``attribute`` fields. ``app.include_router(...)``:
    receiver = ``"app"``, method = ``"include_router"``. Chained
    attributes like ``app.router.include_router`` yield receiver =
    the last object segment (``"router"``) — matching the shape of
    the Express recognizer's receiver resolution.
    """
    fn = call.child_by_field_name("function")
    if fn is None or fn.type != "attribute":
        return None, None
    obj = fn.child_by_field_name("object")
    attr = fn.child_by_field_name("attribute")
    if attr is None or attr.type != "identifier":
        return None, None
    method_name = node_text(attr, source)

    if obj is None:
        return None, method_name
    if obj.type == "identifier":
        return node_text(obj, source), method_name
    if obj.type == "attribute":
        # Nested attribute — take the last segment as the effective
        # receiver. Matches Express's behavior for qualified forms.
        return last_name_segment(node_text(obj, source)), method_name
    return None, method_name


def _call_kwarg_string(call: TSNode, key: str, source: bytes) -> Optional[str]:
    """Return the string-literal value of ``key=...`` kwarg, or
    ``None`` if absent or non-literal.

    ``keyword_argument`` nodes have ``identifier``-``=``-value
    children. Returns ``None`` unless the value is a ``string`` we
    can resolve at parse time.
    """
    args = call.child_by_field_name("arguments")
    if args is None:
        return None
    for arg in args.children:
        if arg.type != "keyword_argument":
            continue
        name_node = arg.child_by_field_name("name")
        value_node = arg.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        if node_text(name_node, source) != key:
            continue
        return _string_content(value_node, source)
    return None


def _first_identifier_arg(args: TSNode, source: bytes) -> Optional[str]:
    """Return the first positional-identifier argument's text.

    ``app.include_router(router)`` → ``"router"``. Skips leading
    ``(`` and non-identifier argument shapes.
    """
    for child in args.children:
        if child.type == "identifier":
            return node_text(child, source)
        if child.type == "attribute":
            # ``module.router`` — take the final attribute segment.
            return last_name_segment(node_text(child, source))
    return None


def _function_definition_of(dec_def: TSNode) -> Optional[TSNode]:
    """Return the ``function_definition`` child of a decorated block.

    Tree-sitter Python places it as the last child (after the
    decorators). Iterate to find it — faster than relying on
    position in case the grammar adds metadata children later.
    """
    for child in dec_def.children:
        if child.type == "function_definition":
            return child
    return None


def _function_name(func: TSNode, source: bytes) -> str:
    """Return the function identifier text."""
    name_node = func.child_by_field_name("name")
    if name_node is None or name_node.type != "identifier":
        return ""
    return node_text(name_node, source)


def _iter_decorators(dec_def: TSNode) -> Iterator[TSNode]:
    """Yield every ``decorator`` child of a ``decorated_definition``."""
    for child in dec_def.children:
        if child.type == "decorator":
            yield child


def _decorator_receiver_method(
    decorator: TSNode, source: bytes
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(receiver_name, method_name)`` for ``@receiver.method(...)``.

    The decorator's child is a ``call`` whose callee is an
    ``attribute`` node (same shape as a statement-level call).
    Delegates to :func:`_call_receiver_method`.
    """
    for child in decorator.children:
        if child.type == "call":
            return _call_receiver_method(child, source)
    return None, None


def _decorator_first_string(decorator: TSNode, source: bytes) -> Optional[str]:
    """Return the decorator call's path argument, positional or kwarg.

    FastAPI's verb decorators accept both forms:

    - Positional: ``@app.get("/users")``
    - Keyword: ``@app.get(path="/users", include_in_schema=False)``

    We prefer the ``path=`` kwarg when present — Python disallows
    mixing positional and ``path=`` simultaneously, so there's no
    ambiguity. Falls back to the first positional string literal.
    """
    for child in decorator.children:
        if child.type != "call":
            continue

        kw_path = _call_kwarg_string(child, "path", source)
        if kw_path is not None:
            return kw_path

        args = child.child_by_field_name("arguments")
        if args is None:
            continue
        for arg in args.children:
            if arg.type == "string":
                return _string_content(arg, source)
        return None
    return None


def _string_content(string_node: TSNode, source: bytes) -> Optional[str]:
    """Return the content of a Python ``string`` node (without quotes).

    Python strings in tree-sitter have ``string_start``,
    ``string_content``, ``string_end`` children. f-strings with
    interpolations (``f"/{x}/y"``) have ``interpolation`` children
    too — we return ``None`` for those since a truncated fragment
    would be a silently-wrong edge. Concatenation across multiple
    ``string_content`` pieces (after escapes) is handled by joining.
    """
    if string_node.type != "string":
        return None
    fragments: List[str] = []
    for child in string_node.children:
        if child.type == "string_content":
            fragments.append(node_text(child, source))
        elif child.type == "interpolation":
            # f-string interpolation — runtime-computed path.
            return None
    return "".join(fragments)
