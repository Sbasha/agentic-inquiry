"""NestJS recognizer for TypeScript.

Adds ``nestjs_route`` relationships to handler methods on
``@Controller``-decorated classes. The base TypeScript parser has no
concept of NestJS — it sees ``@Get(':id')`` as a generic decorator
and drops the routing semantics. This recognizer fills that gap for
the standard NestJS HTTP controller pattern.

**What it captures.**

- Class stereotype: ``@Controller()`` / ``@Controller('path')`` /
  ``@Controller({ path: 'items', version: '1' })``. Only the
  ``path`` key is read from the options object.
- Method-level verb decorators: ``@Get``, ``@Post``, ``@Put``,
  ``@Delete``, ``@Patch``, ``@Options``, ``@Head``. ``@All``
  emits ``"ANY"``.
- Qualified decorator names (``@common.Controller``, ``@nestjs.Get``)
  resolve via the shared ``last_name_segment`` helper.

**What it does NOT do.**

- Global prefix via ``app.setGlobalPrefix('api')`` — cross-file,
  bootstrap.
- WebSocket gateways / microservice message patterns — distinct
  edge kinds deserving separate recognizers.
- Versioning via ``@Controller({ version: '1' })`` — path only.
- Multi-path arrays (``@Get(['/a', '/b'])``) — first string wins.
- Nested / inner controllers — only top-level class declarations
  are walked.

**Implementation.**

Subclass of :class:`HTTPRouteRecognizer` — the base owns pre-filter,
parser loading, chunk matching, and dedup. This file contributes
only TypeScript/NestJS-specific AST extraction plus the decorator-
walker helpers (class decorators can sit inside ``export_statement``
or directly on ``class_declaration`` depending on export status and
parser version).
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Iterator, List, Optional, Tuple

from ._http_route import HTTPRouteRecognizer, _Route, join_paths
from ._tree_sitter_utils import (
    TSNode,
    iter_children_of_type,
    last_name_segment,
    node_text,
)


_VERB_DECORATORS: Dict[str, str] = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Delete": "DELETE",
    "Patch": "PATCH",
    "Options": "OPTIONS",
    "Head": "HEAD",
    "All": "ANY",
}

_CONTROLLER_STEREOTYPE: str = "Controller"


class TypeScriptNestJSRecognizer(HTTPRouteRecognizer):
    """Recognizer that adds NestJS HTTP route edges to TypeScript documents."""

    name = "typescript_nestjs"
    # Intentionally ``.ts`` only — NestJS controllers aren't written
    # in ``.tsx`` (React/JSX territory).
    file_extensions: FrozenSet[str] = frozenset({".ts"})

    _relationship_type = "nestjs_route"
    _framework_name = "nestjs"
    _tree_sitter_language = "typescript"

    # Fast pre-filter markers:
    #
    # - ``@nestjs/`` catches any file importing from an ``@nestjs/*``
    #   package (wildcard, named, or aliased imports).
    # - ``@Controller`` catches bare-decorator usage even when the
    #   import comes from a re-export wrapper.
    # - ``.Controller`` catches qualified-decorator usage
    #   (``@common.Controller('x')``) from a wrapper package.
    #
    # The tighter ``@Controller`` (with the ``@``) avoids false
    # positives on every TypeScript file with a ``*Controller``
    # class name.
    _pre_filter_markers = (
        b"@nestjs/",
        b"@Controller",
        b".Controller",
    )

    def _extract_routes(self, root_node: TSNode, source: bytes) -> List[_Route]:
        routes: List[_Route] = []

        for class_node, class_decorators in _top_level_classes_with_decorators(
            root_node
        ):
            stereotype_ann, base_path = _class_controller_info(class_decorators, source)
            if stereotype_ann is None:
                continue

            class_name = _class_name(class_node, source)
            body = class_node.child_by_field_name("body")
            if body is None:
                continue

            for method_node, method_decorators in _methods_with_decorators(body):
                http_method, method_path = _resolve_handler(method_decorators, source)
                if http_method is None:
                    continue

                method_name = _method_name(method_node, source)
                if not method_name:
                    continue

                routes.append(
                    _Route(
                        source_name=method_name,
                        source_line=method_node.start_point[0] + 1,
                        http_method=http_method,
                        path=join_paths(base_path, method_path),
                        metadata={"controller_class": class_name},
                    )
                )

        return routes


# ---------------------------------------------------------------------------
# TypeScript decorator walking
# ---------------------------------------------------------------------------


def _top_level_classes_with_decorators(
    root_node: TSNode,
) -> Iterator[Tuple[TSNode, List[TSNode]]]:
    """Yield ``(class_declaration_node, [decorator_nodes])`` pairs.

    TypeScript's tree-sitter grammar places class decorators in two
    different locations depending on whether the class is exported:

    - **Non-exported** (``@Controller('x') class Foo {}``): the
      decorator is a *child* of the ``class_declaration`` itself,
      appearing before the ``class`` keyword.
    - **Exported** (``@Controller('x') export class Foo {}``): the
      decorator is a child of the enclosing ``export_statement``,
      a sibling of the inner ``class_declaration``. Some parser
      versions nest decorators inside the class_declaration even
      when exported — we union both locations to be safe.
    """
    for child in root_node.children:
        if child.type == "class_declaration":
            decorators = [c for c in child.children if c.type == "decorator"]
            yield child, decorators
            continue

        if child.type == "export_statement":
            inner_decorators: List[TSNode] = []
            inner_class: Optional[TSNode] = None
            for sub in child.children:
                if sub.type == "decorator":
                    inner_decorators.append(sub)
                elif sub.type == "class_declaration":
                    inner_class = sub
                    inner_decorators.extend(
                        c for c in sub.children if c.type == "decorator"
                    )
            if inner_class is not None:
                yield inner_class, inner_decorators


def _methods_with_decorators(
    class_body: TSNode,
) -> Iterator[Tuple[TSNode, List[TSNode]]]:
    """Yield ``(method_definition_node, [decorator_nodes])`` pairs.

    Decorators accumulate across consecutive ``decorator`` siblings
    and are consumed on the next declaration. Only
    ``method_definition`` nodes yield; field definitions still reset
    the accumulator so their decorators don't leak onto a following
    method.
    """
    accumulated: List[TSNode] = []

    for child in class_body.children:
        ctype = child.type
        if ctype == "decorator":
            accumulated.append(child)
            continue
        if ctype in ("comment", "{", "}", ",", ";"):
            continue
        if ctype == "method_definition":
            yield child, accumulated
        accumulated = []


def _class_controller_info(
    class_decorators: List[TSNode],
    source: bytes,
) -> Tuple[Optional[TSNode], str]:
    """Return ``(@Controller decorator, base_path)`` or ``(None, "")``."""
    for decorator in class_decorators:
        name = _decorator_name(decorator, source)
        if last_name_segment(name) != _CONTROLLER_STEREOTYPE:
            continue
        path = _decorator_path_arg(decorator, source) or ""
        return decorator, path
    return None, ""


def _resolve_handler(
    method_decorators: List[TSNode],
    source: bytes,
) -> Tuple[Optional[str], str]:
    """Return ``(http_verb, path)`` for the first verb decorator, or
    ``(None, "")``."""
    for decorator in method_decorators:
        name = last_name_segment(_decorator_name(decorator, source))
        verb = _VERB_DECORATORS.get(name)
        if verb is None:
            continue
        return verb, _decorator_path_arg(decorator, source) or ""
    return None, ""


def _decorator_name(decorator: TSNode, source: bytes) -> str:
    """Extract the (possibly qualified) name of a decorator.

    Handles ``@Name(...)`` (call form) and the rare bare ``@Name``.
    Qualified access (``@common.Controller(...)``) returns the full
    dotted text; caller normalises via ``last_name_segment``.
    """
    for child in decorator.children:
        if child.type == "call_expression":
            fn = child.child_by_field_name("function")
            if fn is not None:
                return node_text(fn, source)
        elif child.type in ("identifier", "member_expression"):
            return node_text(child, source)
    return ""


def _decorator_path_arg(decorator: TSNode, source: bytes) -> Optional[str]:
    """Pull the path out of a decorator's argument list.

    Scans arguments in source order and returns the first path it
    can recognise: a string/template literal, an options object
    with a ``path`` entry, or the first string in an array arg.
    """
    call = None
    for child in decorator.children:
        if child.type == "call_expression":
            call = child
            break
    if call is None:
        return None

    args = call.child_by_field_name("arguments")
    if args is None:
        return None

    for arg in args.children:
        literal = _literal_string_value(arg, source)
        if literal is not None:
            return literal
        if arg.type == "object":
            path = _object_path_property(arg, source)
            if path is not None:
                return path
        if arg.type == "array":
            for elem in arg.children:
                literal = _literal_string_value(elem, source)
                if literal is not None:
                    return literal
    return None


def _object_path_property(obj_node: TSNode, source: bytes) -> Optional[str]:
    """Extract the ``path`` property's string value from an object literal.

    Accepts ``property_identifier`` keys (``{ path: 'items' }``) and
    ``string`` keys (``{ 'path': 'items' }`` / ``{ "path": 'items' }``).
    Uses the ``pair`` node's ``key`` and ``value`` field accessors
    so value-string can't be mistaken for key-string.
    """
    for pair in iter_children_of_type(obj_node, "pair"):
        key_node = pair.child_by_field_name("key")
        value_node = pair.child_by_field_name("value")
        if key_node is None or value_node is None:
            continue

        key: Optional[str] = None
        if key_node.type == "property_identifier":
            key = node_text(key_node, source)
        elif key_node.type == "string":
            key = _string_fragment_text(key_node, source)

        if key != "path":
            continue
        return _literal_string_value(value_node, source)
    return None


def _literal_string_value(node: TSNode, source: bytes) -> Optional[str]:
    """Return the inside of a ``string`` or simple ``template_string``.

    Interpolated templates (`` `a${x}b` ``) return ``None`` —
    emitting a truncated path from the first fragment alone would be
    silently wrong; dropping the path preserves the handler without
    a misleading edge.
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
    """Return the inside of a string/template literal via raw source span.

    Escape sequences split a string literal into multiple
    ``string_fragment`` + ``escape_sequence`` children. Iterating
    only ``string_fragment`` would truncate after the first; taking
    the raw byte span minus the surrounding quote tokens preserves
    the source form verbatim.
    """
    raw = node_text(node, source)
    if len(raw) < 2:
        return ""
    return raw[1:-1]


def _class_name(class_node: TSNode, source: bytes) -> str:
    name_node = class_node.child_by_field_name("name")
    if name_node is None:
        return ""
    return node_text(name_node, source)


def _method_name(method_node: TSNode, source: bytes) -> str:
    name_node = method_node.child_by_field_name("name")
    if name_node is None or name_node.type != "property_identifier":
        return ""
    return node_text(name_node, source)
