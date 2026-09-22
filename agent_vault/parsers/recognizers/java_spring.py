"""Spring Framework recognizer for Java.

Adds ``spring_route`` relationships to method chunks produced by the
base Java parser. The base parser has no concept of Spring — it sees a
``@GetMapping("/users/{id}")`` as an annotation node and drops it.
Static analysis tools can't follow Spring's runtime route registration
without knowing the convention, so for onboarding / impact analysis
these dynamic edges go missing. This recognizer fills that gap for
the common Spring MVC / Spring WebFlux annotation-driven style.

**What it captures.**

Class-level stereotypes that mark the enclosing class as a route
container:

- ``@RestController``
- ``@Controller``

Class-level mapping annotations that contribute a base path when
combined with one of the stereotypes above (they do **not** by
themselves mark the class as Spring — a class with only
``@RequestMapping`` and no stereotype is ignored):

- ``@RequestMapping("/base")`` — prepended to every handler's path.

Method-level HTTP mapping annotations that mark a method as a route
handler:

- ``@RequestMapping(method=..., path=...)`` (generic form)
- ``@GetMapping``, ``@PostMapping``, ``@PutMapping``,
  ``@DeleteMapping``, ``@PatchMapping`` (HTTP-specific shortcuts)

Qualified annotation names (``@org.springframework...GetMapping``)
resolve the same as their bare form — we match on the final
``.``-separated segment.

**What it does NOT do.**

- Constants / ``@Value`` substitution in annotation paths: we take
  the literal string.
- Multi-path mappings (``@GetMapping({"/a", "/b"})``): we take the
  first literal.
- Spring XML config / ``@Bean``-based route registration.
- ``consumes`` / ``produces`` / ``headers``.
- Nested inner classes and ``record`` declarations.
- ``@RequestMapping``'s ``method=`` argument is located by scanning
  the argument text for ``RequestMethod.``. A string literal
  elsewhere in the annotation (e.g. a ``headers = "RequestMethod.GET"``
  that happens to include the token) could be mis-attributed.
  Vanishingly unlikely in real code.

**Implementation.**

Subclass of :class:`HTTPRouteRecognizer` — the base owns pre-filter,
parser loading, chunk matching, and dedup. This file only contributes
Spring-specific AST extraction (``_extract_routes``) and the class
attributes that name the framework.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Optional, Tuple

from ._http_route import HTTPRouteRecognizer, _Route, join_paths
from ._tree_sitter_utils import (
    first_child_of_type,
    identifier_text,
    iter_children_of_type,
    last_name_segment,
    node_text,
)


# HTTP-method-specific mapping annotation → HTTP verb it denotes.
# ``@RequestMapping`` is handled separately because the method is an
# argument (``method = RequestMethod.GET``) rather than encoded in the
# annotation name.
_METHOD_MAPPINGS: Dict[str, str] = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}

# Class-level stereotypes that mark the class as a route container.
# ``@Controller`` is included because server-rendered MVC controllers
# still count — a ``@Controller`` with ``@GetMapping`` methods does
# route HTTP requests, it just returns a view name instead of a body.
_ROUTE_CONTAINER_STEREOTYPES: FrozenSet[str] = frozenset(
    {
        "RestController",
        "Controller",
    }
)


class JavaSpringRecognizer(HTTPRouteRecognizer):
    """Recognizer that adds Spring HTTP route edges to Java documents."""

    name = "java_spring"
    file_extensions: FrozenSet[str] = frozenset({".java"})

    _relationship_type = "spring_route"
    _framework_name = "spring"
    _tree_sitter_language = "java"

    # Cheap pre-filter: every Spring file imports from
    # ``org.springframework`` and controllers reference the stereotype
    # annotations by name. Catches wildcard imports, specific imports,
    # and fully-qualified annotation references without tokenising.
    _pre_filter_markers = (
        b"springframework",
        b"RestController",
        b"RequestMapping",
    )

    def _extract_routes(self, root_node, source: bytes) -> List[_Route]:
        """Walk top-level class declarations, emit routes per handler.

        Non-Spring classes are skipped entirely — a plain POJO in the
        same package shouldn't incur any cost beyond the AST walk.
        """
        routes: List[_Route] = []

        for class_node in iter_children_of_type(root_node, "class_declaration"):
            annotations = _annotations_on(class_node, source)
            if not any(ann.name in _ROUTE_CONTAINER_STEREOTYPES for ann in annotations):
                continue

            base_path = ""
            class_name = identifier_text(class_node, "name", source)
            for ann in annotations:
                if ann.name == "RequestMapping":
                    base_path = _annotation_path(ann.args_text) or ""
                    break

            body = class_node.child_by_field_name("body")
            if body is None:
                continue

            for method_node in iter_children_of_type(body, "method_declaration"):
                method_annotations = _annotations_on(method_node, source)
                http_method, method_path = _resolve_handler_mapping(method_annotations)
                if http_method is None:
                    continue

                method_name = identifier_text(method_node, "name", source)
                if not method_name:
                    continue

                routes.append(
                    _Route(
                        source_name=method_name,
                        # tree-sitter rows are 0-indexed; ParserChunk
                        # line_start is 1-indexed.
                        source_line=method_node.start_point[0] + 1,
                        http_method=http_method,
                        path=join_paths(base_path, method_path),
                        metadata={"controller_class": class_name},
                    )
                )

        return routes


# ---------------------------------------------------------------------------
# Java-Spring-specific annotation parsing
# ---------------------------------------------------------------------------


class _Annotation:
    """Parsed annotation: name + raw argument list text (minus parens)."""

    __slots__ = ("name", "args_text")

    def __init__(self, name: str, args_text: str) -> None:
        self.name = name
        self.args_text = args_text


def _annotations_on(decl_node, source: bytes) -> List[_Annotation]:
    """Collect annotations from a declaration's ``modifiers`` block.

    Java's tree-sitter grammar models annotations as children of a
    ``modifiers`` node that precedes the declaration keyword. Missing
    modifiers ⇒ no annotations. Qualified names resolve to their
    final segment.
    """
    modifiers = first_child_of_type(decl_node, "modifiers")
    if modifiers is None:
        return []

    annotations: List[_Annotation] = []
    for child in modifiers.children:
        if child.type == "marker_annotation":
            name = last_name_segment(identifier_text(child, "name", source))
            if name:
                annotations.append(_Annotation(name, ""))
        elif child.type == "annotation":
            name = last_name_segment(identifier_text(child, "name", source))
            args_node = child.child_by_field_name("arguments")
            args_text = node_text(args_node, source) if args_node else ""
            if args_text.startswith("(") and args_text.endswith(")"):
                args_text = args_text[1:-1]
            if name:
                annotations.append(_Annotation(name, args_text))
    return annotations


def _resolve_handler_mapping(
    annotations: List[_Annotation],
) -> Tuple[Optional[str], str]:
    """Return ``(http_method, path)`` for the first mapping annotation,
    or ``(None, "")`` if none present.

    HTTP-specific shortcuts resolve first (more common and
    informative). ``@RequestMapping`` falls back to reading the
    ``method`` argument; absent → ``"ANY"``.
    """
    for ann in annotations:
        verb = _METHOD_MAPPINGS.get(ann.name)
        if verb is not None:
            return verb, _annotation_path(ann.args_text) or ""

    for ann in annotations:
        if ann.name == "RequestMapping":
            verb = _request_mapping_verb(ann.args_text) or "ANY"
            return verb, _annotation_path(ann.args_text) or ""

    return None, ""


def _request_mapping_verb(args_text: str) -> Optional[str]:
    """Pull the HTTP verb out of a ``@RequestMapping`` argument list.

    Recognises ``method = RequestMethod.GET`` and
    ``method = {RequestMethod.GET, RequestMethod.POST}`` (first wins).
    """
    marker = "RequestMethod."
    idx = args_text.find(marker)
    if idx < 0:
        return None
    rest = args_text[idx + len(marker) :]
    verb_chars: List[str] = []
    for ch in rest:
        if ch.isalpha() or ch == "_":
            verb_chars.append(ch)
        else:
            break
    verb = "".join(verb_chars)
    return verb or None


def _annotation_path(args_text: str) -> Optional[str]:
    """Pull the route path out of annotation args.

    Precedence matches Spring's docs: ``value = "..."`` → ``path =
    "..."`` → first positional string literal. Arrays
    (``value = {"/a", "/b"}``) resolve to the first element.
    """
    for key in ("value", "path"):
        path = _named_string_arg(args_text, key)
        if path is not None:
            return path
    return _first_string_literal(args_text)


def _named_string_arg(args_text: str, key: str) -> Optional[str]:
    """Find ``key = "..."`` in annotation args, return the inside string.

    Tolerates whitespace around ``=`` and an opening ``{`` for array
    forms. Java tree-sitter doesn't give structured named-arg nodes
    for annotations, hence the scan.
    """
    i = 0
    key_len = len(key)
    n = len(args_text)
    while i < n:
        idx = args_text.find(key, i)
        if idx < 0:
            return None
        before_ok = idx == 0 or not (
            args_text[idx - 1].isalnum() or args_text[idx - 1] == "_"
        )
        after_pos = idx + key_len
        after_ok = after_pos < n and not (
            args_text[after_pos].isalnum() or args_text[after_pos] == "_"
        )
        if not (before_ok and after_ok):
            i = idx + 1
            continue

        j = after_pos
        while j < n and args_text[j].isspace():
            j += 1
        if j >= n or args_text[j] != "=":
            i = idx + 1
            continue
        j += 1
        while j < n and args_text[j].isspace():
            j += 1
        if j < n and args_text[j] == "{":
            j += 1
            while j < n and args_text[j].isspace():
                j += 1

        return _parse_string_literal(args_text, j)
    return None


def _parse_string_literal(args_text: str, start: int) -> Optional[str]:
    """Parse a double-quoted Java string starting at ``args_text[start]``."""
    n = len(args_text)
    if start >= n or args_text[start] != '"':
        return None
    j = start + 1
    while j < n:
        if args_text[j] == "\\" and j + 1 < n:
            j += 2
            continue
        if args_text[j] == '"':
            return args_text[start + 1 : j]
        j += 1
    return None


def _first_string_literal(args_text: str) -> Optional[str]:
    i = 0
    n = len(args_text)
    while i < n:
        if args_text[i] == '"':
            return _parse_string_literal(args_text, i)
        i += 1
    return None
