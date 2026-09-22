"""Spring dependency-injection recognizer for Java.

Extracts the Spring DI graph: which classes / methods provide
beans, and which classes consume which dependencies. Pairs with
``java_spring.py`` (HTTP routes) — the two recognizers run
independently on ``.java`` files, each emitting its own edge
kinds.

Edge kinds emitted:

- ``spring_di_bean``: a class or method provides a bean.
  - ``source`` = the declaring class (for ``@Service`` et al.) or
    the declaring method (for ``@Bean`` methods inside a
    ``@Configuration`` class).
  - ``target`` = the bean's *type* — the class itself for a
    stereotype-annotated class; the method return type for a
    ``@Bean`` method.
  - ``metadata.stereotype`` = ``Service`` / ``Component`` /
    ``Repository`` / ``Controller`` / ``RestController`` /
    ``Configuration`` / ``Bean``.
  - ``metadata.bean_name`` = the name Spring registers the bean
    under (default: decapitalized class name for class
    stereotypes, method name for ``@Bean`` methods;
    ``@Service("custom")`` or ``@Bean("custom")`` overrides).
  - ``metadata.kind`` = ``class_stereotype`` or ``bean_method``.

- ``spring_di_depends_on``: a class or factory method depends on
  a type that must be resolved from the DI container.
  - ``source_type`` = ``class`` for constructor / field / setter
    injection on a Spring class; ``method`` for parameters of a
    ``@Bean`` factory method.
  - ``source_name`` = the consumer class name or factory method
    name.
  - ``target`` = the dependency's type (raw identifier name;
    generics and outer parametrization are stripped).
  - ``metadata.injection_type`` = ``constructor`` / ``field`` /
    ``setter`` / ``bean_method_param``.
  - ``metadata.parameter_name`` = the parameter or field name
    receiving the injection.
  - ``metadata.qualifier`` = the ``@Qualifier`` argument value,
    if present.

**What it captures.**

- All six class-level Spring stereotypes (``@Service``,
  ``@Component``, ``@Repository``, ``@Controller``,
  ``@RestController``, ``@Configuration``) and derived stereotypes
  recognised via last-segment matching on qualified annotation
  names.
- Constructor injection — every non-primitive parameter of every
  constructor becomes a ``depends_on`` edge. Covers both the
  implicit single-constructor case (modern Spring auto-wires a
  sole constructor) and explicit ``@Autowired`` on one of
  several.
- Field injection — fields annotated ``@Autowired`` or
  ``@Inject`` (JSR-330).
- Setter injection — methods annotated ``@Autowired`` / ``@Inject``
  with one or more non-primitive parameters.
- ``@Bean`` methods inside any Spring-managed class — ``@Configuration``
  uses full CGLIB proxying, ``@Component`` uses "lite mode"; both
  register the beans. ``@Bean`` on a plain POJO with no stereotype
  is silently ignored by Spring and by this recognizer. The method
  return type is the bean type; the method is the provider. Any
  parameters on the factory method become ``depends_on`` edges
  from the method (Spring resolves them from the container before
  calling the factory).

**What it does NOT do.**

- **Generic type parameters** — ``Optional<Foo>``, ``List<Foo>``,
  ``Map<K, V>`` all collapse to their outer type (``Optional``,
  ``List``, ``Map``). The outer type alone isn't usually a DI
  target; handling this well requires tracking the generic
  parameter. Documented edge case; consumers can filter on the
  raw outer type.
- **Primitives** — ``int``, ``long``, ``boolean``, etc. are
  filtered out of ``depends_on`` edges since they can't be
  Spring beans. ``String`` is deliberately NOT filtered because
  ``@Value`` injection of property strings is a legitimate
  pattern.
- **``@Qualifier`` resolution** — the qualifier string is
  captured as metadata but not used to disambiguate beans at
  extraction time.
- **``@Primary`` / ``@Conditional`` / ``@Lazy`` / ``@Profile``** —
  these influence runtime resolution; out of scope.
- **Cross-file bean resolution** — we emit edges with
  ``target_name`` = type identifier; the graph layer is
  responsible for joining those to the bean-providing class or
  method chunk.
- **Nested / inner classes** — only top-level
  ``class_declaration`` nodes are walked.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, FrozenSet, Iterator, List, Optional, Tuple

from agent_vault.parsers.models import (
    ParsedDocument,
    ParserChunk,
    ParserRelationship,
)

from ._tree_sitter_utils import (
    TSNode,
    first_child_of_type,
    identifier_text,
    iter_children_of_type,
    last_name_segment,
    node_text,
)

logger = logging.getLogger(__name__)


# Class-level stereotypes. Matched against the last segment of the
# annotation name, so ``@org.springframework.stereotype.Service``
# resolves the same as ``@Service``.
_CLASS_STEREOTYPES: FrozenSet[str] = frozenset(
    {
        "Service",
        "Component",
        "Repository",
        "Controller",
        "RestController",
        "Configuration",
    }
)

# Annotations that mark a field / setter / constructor as an
# injection point. ``@Inject`` is the JSR-330 form Spring also
# accepts; ``@Autowired`` is the native Spring form.
_INJECTION_ANNOTATIONS: FrozenSet[str] = frozenset({"Autowired", "Inject"})

# Annotation that declares a factory method as a bean provider.
_BEAN_METHOD_ANNOTATION: str = "Bean"

# ``@Qualifier("name")`` disambiguates when multiple beans match a
# type. We capture the argument as metadata; we don't resolve.
_QUALIFIER_ANNOTATION: str = "Qualifier"

# Java primitives — can't be Spring beans, so we filter them out
# of dependency edges. ``String`` is *not* here because ``@Value``
# injection of configuration strings is a real pattern.
_JAVA_PRIMITIVES: FrozenSet[str] = frozenset(
    {
        "int",
        "long",
        "short",
        "byte",
        "float",
        "double",
        "boolean",
        "char",
        "void",
    }
)

# Fast pre-filter markers. A Spring DI file imports from
# ``org.springframework.*`` or references one of the annotation
# names literally. ``springframework`` alone covers the typical
# import case plus qualified usage; the bare annotation markers
# catch files that re-export the decorators from a wrapper
# package (so the ``springframework`` substring never appears).
#
# Keep every stereotype this recognizer supports in the list —
# missing a marker means a wrapper-only file using just that
# stereotype would be skipped without a parse, emitting nothing.
_SPRING_DI_MARKERS: Tuple[bytes, ...] = (
    b"springframework",
    b"@Autowired",
    b"@Inject",
    b"@Service",
    b"@Component",
    b"@Repository",
    b"@Controller",
    b"@RestController",
    b"@Configuration",
    b"@Bean",
    b"@Qualifier",
)


class JavaSpringDIRecognizer:
    """Recognizer that adds Spring DI edges to Java documents."""

    name = "java_spring_di"
    file_extensions: FrozenSet[str] = frozenset({".java"})

    def __init__(self) -> None:
        self._parser = None
        self._parser_load_failed = False
        self._parser_lock = threading.Lock()

    async def enrich(self, parsed: ParsedDocument) -> ParsedDocument:
        try:
            source = Path(parsed.file_path).read_bytes()
        except OSError as exc:
            logger.debug(
                "JavaSpringDIRecognizer: could not read %s: %s",
                parsed.file_path,
                exc,
            )
            return parsed

        if not any(marker in source for marker in _SPRING_DI_MARKERS):
            return parsed

        parser = self._get_parser()
        if parser is None:
            return parsed

        try:
            tree = parser.parse(source)
        except Exception as exc:
            logger.debug(
                "JavaSpringDIRecognizer: parse failed for %s: %s",
                parsed.file_path,
                exc,
            )
            return parsed

        beans, deps = _extract(tree.root_node, source)
        if not beans and not deps:
            return parsed

        _attach(parsed.chunks, beans, deps, parsed.file_path)
        return parsed

    def _get_parser(self):
        if self._parser is not None:
            return self._parser
        if self._parser_load_failed:
            return None
        with self._parser_lock:
            if self._parser is not None:
                return self._parser
            if self._parser_load_failed:
                return None
            try:
                from tree_sitter_language_pack import get_parser

                self._parser = get_parser("java")
            except Exception as exc:
                logger.debug(
                    "JavaSpringDIRecognizer: Java tree-sitter parser unavailable: %s",
                    exc,
                )
                self._parser_load_failed = True
                return None
            return self._parser


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


class _Bean:
    """Provider record — a class or method that produces a bean."""

    __slots__ = (
        "provider_name",
        "provider_kind",
        "provider_line",
        "bean_type",
        "bean_name",
        "stereotype",
    )

    def __init__(
        self,
        provider_name: str,
        provider_kind: str,
        provider_line: int,
        bean_type: str,
        bean_name: str,
        stereotype: str,
    ) -> None:
        self.provider_name = provider_name
        self.provider_kind = provider_kind  # "class_stereotype" | "bean_method"
        self.provider_line = provider_line
        self.bean_type = bean_type
        self.bean_name = bean_name
        self.stereotype = stereotype


class _Dep:
    """Consumer-side dependency record.

    ``consumer_kind`` distinguishes class-scoped deps (constructor /
    field / setter on a Spring class) from method-scoped deps
    (parameters of a ``@Bean`` factory method). The two emit with
    different ``source_type`` values so downstream graph queries
    can tell "class X depends on T" from "bean-factory method M
    depends on T".
    """

    __slots__ = (
        "consumer_name",
        "consumer_line",
        "consumer_kind",
        "dependency_type",
        "injection_type",
        "parameter_name",
        "qualifier",
    )

    def __init__(
        self,
        consumer_name: str,
        consumer_line: int,
        consumer_kind: str,
        dependency_type: str,
        injection_type: str,
        parameter_name: str,
        qualifier: Optional[str],
    ) -> None:
        self.consumer_name = consumer_name
        self.consumer_line = consumer_line
        self.consumer_kind = consumer_kind  # "class" | "method"
        self.dependency_type = dependency_type
        self.injection_type = injection_type
        self.parameter_name = parameter_name
        self.qualifier = qualifier


class _Annotation:
    """Parsed annotation: name + ``arguments`` node (or ``None`` for
    marker form)."""

    __slots__ = ("name", "args_node")

    def __init__(self, name: str, args_node: Optional[TSNode]) -> None:
        self.name = name
        self.args_node = args_node


def _extract(root_node: TSNode, source: bytes) -> Tuple[List[_Bean], List[_Dep]]:
    """Walk top-level class declarations, emit beans and deps."""
    beans: List[_Bean] = []
    deps: List[_Dep] = []

    for class_node in iter_children_of_type(root_node, "class_declaration"):
        class_name = identifier_text(class_node, "name", source)
        if not class_name:
            continue

        class_annotations = _annotations_on(class_node, source)
        stereotype_ann = _find_stereotype(class_annotations)
        is_spring_class = stereotype_ann is not None

        class_line = class_node.start_point[0] + 1

        if is_spring_class:
            bean_name = _annotation_string_arg(stereotype_ann, source) or _decapitalize(
                class_name
            )
            beans.append(
                _Bean(
                    provider_name=class_name,
                    provider_kind="class_stereotype",
                    provider_line=class_line,
                    bean_type=class_name,
                    bean_name=bean_name,
                    stereotype=stereotype_ann.name,
                )
            )

        body = class_node.child_by_field_name("body")
        if body is None:
            continue

        for member in body.children:
            mtype = member.type

            # Constructor injection — any Spring class's constructor
            # parameters are injection points. We emit edges for every
            # constructor to cover both single-ctor (implicit
            # @Autowired) and multi-ctor (explicit @Autowired on one)
            # cases without having to pick which is "the" constructor.
            if mtype == "constructor_declaration" and is_spring_class:
                for dep in _params_as_deps(
                    member,
                    source,
                    class_name,
                    class_line,
                    "class",
                    "constructor",
                ):
                    deps.append(dep)
                continue

            if mtype == "method_declaration":
                method_annotations = _annotations_on(member, source)
                ann_names = {a.name for a in method_annotations}

                # @Bean methods are only registered in Spring's container
                # when the enclosing class is itself Spring-managed
                # (``@Configuration`` or another stereotype — Spring
                # silently ignores ``@Bean`` on plain POJOs). Gating here
                # avoids emitting edges for beans that don't actually
                # exist in the container.
                if is_spring_class and _BEAN_METHOD_ANNOTATION in ann_names:
                    return_type = _method_return_type(member, source)
                    method_name = identifier_text(member, "name", source)
                    if return_type and method_name:
                        bean_ann = next(
                            (
                                a
                                for a in method_annotations
                                if a.name == _BEAN_METHOD_ANNOTATION
                            ),
                            None,
                        )
                        bean_name = (
                            _annotation_string_arg(bean_ann, source) or method_name
                        )
                        method_line = member.start_point[0] + 1
                        beans.append(
                            _Bean(
                                provider_name=method_name,
                                provider_kind="bean_method",
                                provider_line=method_line,
                                # Normalize for consistency with
                                # depends_on edges: strip generics/
                                # arrays and the package qualifier so
                                # downstream matching lands on the
                                # bare class name.
                                bean_type=_clean_type_name(return_type),
                                bean_name=bean_name,
                                stereotype=_BEAN_METHOD_ANNOTATION,
                            )
                        )

                        # @Bean factory parameters are dependencies of
                        # the factory method. Spring resolves them from
                        # the container before calling the factory.
                        # ``consumer`` is the method itself so the edge
                        # points from the factory to its inputs.
                        for dep in _params_as_deps(
                            member,
                            source,
                            method_name,
                            method_line,
                            "method",
                            "bean_method_param",
                        ):
                            deps.append(dep)

                # Setter injection — @Autowired / @Inject on a method
                # with parameters. Note: a method annotated with BOTH
                # @Bean AND @Autowired (an anti-pattern nobody writes
                # intentionally) will emit deps via both the factory
                # branch above and this branch. The two edges have
                # distinct ``injection_type`` values
                # (``bean_method_param`` vs ``setter``) so the dep
                # dedup key keeps them separate — representing both
                # roles is semantically right if the anti-pattern
                # does appear.
                if is_spring_class and (ann_names & _INJECTION_ANNOTATIONS):
                    for dep in _params_as_deps(
                        member,
                        source,
                        class_name,
                        class_line,
                        "class",
                        "setter",
                    ):
                        deps.append(dep)
                continue

            if mtype == "field_declaration" and is_spring_class:
                field_annotations = _annotations_on(member, source)
                ann_names = {a.name for a in field_annotations}
                if not (ann_names & _INJECTION_ANNOTATIONS):
                    continue
                field_type, field_name = _field_type_and_name(member, source)
                if not field_name:
                    # No declarator / malformed field — can't emit a
                    # usable edge without knowing which field the
                    # injection lands on.
                    continue
                normalised = _normalise_type(field_type)
                if normalised is None:
                    continue
                deps.append(
                    _Dep(
                        consumer_name=class_name,
                        consumer_line=class_line,
                        consumer_kind="class",
                        dependency_type=normalised,
                        injection_type="field",
                        parameter_name=field_name,
                        qualifier=_qualifier_value(field_annotations, source),
                    )
                )

    return beans, deps


def _find_stereotype(annotations: List[_Annotation]) -> Optional[_Annotation]:
    for ann in annotations:
        if ann.name in _CLASS_STEREOTYPES:
            return ann
    return None


def _annotations_on(decl_node: TSNode, source: bytes) -> List[_Annotation]:
    """Collect annotations from a declaration's ``modifiers`` block.

    Java puts all modifiers (annotations + visibility + static + final
    + ...) under a single ``modifiers`` child that precedes the
    declaration keyword. Missing modifiers block ⇒ no annotations.
    Qualified names (``@org.springframework.stereotype.Service``) are
    normalised to the final segment so matching is straightforward.
    """
    modifiers = first_child_of_type(decl_node, "modifiers")
    if modifiers is None:
        return []
    annotations: List[_Annotation] = []
    for child in modifiers.children:
        if child.type == "marker_annotation":
            name = last_name_segment(identifier_text(child, "name", source))
            if name:
                annotations.append(_Annotation(name, None))
        elif child.type == "annotation":
            name = last_name_segment(identifier_text(child, "name", source))
            args_node = child.child_by_field_name("arguments")
            if name:
                annotations.append(_Annotation(name, args_node))
    return annotations


def _annotation_string_arg(ann: Optional[_Annotation], source: bytes) -> Optional[str]:
    """Return the first string-literal argument of an annotation.

    Handles both positional (``@Service("name")``) and named
    (``@Service(value="name")``) forms. Returns ``None`` for marker
    annotations or non-string arguments.
    """
    if ann is None or ann.args_node is None:
        return None
    args_text = node_text(ann.args_node, source)
    if args_text.startswith("(") and args_text.endswith(")"):
        args_text = args_text[1:-1]
    for key in ("value", "name"):
        found = _named_string_arg(args_text, key)
        if found is not None:
            return found
    return _first_string_literal(args_text)


def _qualifier_value(annotations: List[_Annotation], source: bytes) -> Optional[str]:
    """Return the ``@Qualifier`` argument value, or ``None``."""
    for ann in annotations:
        if ann.name == _QUALIFIER_ANNOTATION:
            return _annotation_string_arg(ann, source)
    return None


def _named_string_arg(args_text: str, key: str) -> Optional[str]:
    """Find ``key = "..."`` in an argument list, return the inside string.

    Mirrors the Java string-scan approach used in java_spring.py's
    route path extraction — Java tree-sitter doesn't give us structured
    named-argument nodes for annotations, so we scan.
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
        return _parse_string_literal(args_text, j)
    return None


def _parse_string_literal(args_text: str, start: int) -> Optional[str]:
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


def _params_as_deps(
    method_or_ctor_node: TSNode,
    source: bytes,
    consumer_name: str,
    consumer_line: int,
    consumer_kind: str,
    injection_type: str,
) -> Iterator[_Dep]:
    """Yield a ``_Dep`` per non-primitive parameter.

    ``consumer_name`` / ``consumer_line`` is the enclosing entity
    the deps attribute to — typically the Spring class (for
    constructor / setter injection) or the ``@Bean`` factory method
    itself. ``consumer_kind`` tags the edge's ``source_type``.
    """
    params_node = method_or_ctor_node.child_by_field_name("parameters")
    if params_node is None:
        return

    for param in params_node.children:
        if param.type != "formal_parameter":
            continue
        param_type, param_name = _param_type_and_name(param, source)
        normalised = _normalise_type(param_type)
        if normalised is None:
            continue
        qualifier = _qualifier_value(_annotations_on(param, source), source)
        yield _Dep(
            consumer_name=consumer_name,
            consumer_line=consumer_line,
            consumer_kind=consumer_kind,
            dependency_type=normalised,
            injection_type=injection_type,
            parameter_name=param_name,
            qualifier=qualifier,
        )


def _param_type_and_name(param: TSNode, source: bytes) -> Tuple[str, str]:
    """Extract ``(type_text, name)`` from a ``formal_parameter``.

    Java tree-sitter exposes ``type`` and ``name`` as field accessors
    on ``formal_parameter`` — ``type`` is a type node (identifier,
    generic_type, array_type, etc.) and ``name`` is the parameter
    identifier. Returns empty strings when either field is missing.
    """
    type_node = param.child_by_field_name("type")
    name_node = param.child_by_field_name("name")
    type_text = node_text(type_node, source) if type_node is not None else ""
    name_text = node_text(name_node, source) if name_node is not None else ""
    return type_text, name_text


def _field_type_and_name(field: TSNode, source: bytes) -> Tuple[str, str]:
    """Extract ``(type_text, name)`` from a ``field_declaration``.

    Java tree-sitter puts the type as a field-named child of
    ``field_declaration`` (``type`` field) and the name inside a
    ``variable_declarator`` sibling. For multi-declarator fields
    (``int a, b;``) we take the first declarator's name — rare in
    Spring injection contexts where each field carries its own
    annotation.
    """
    type_node = field.child_by_field_name("type")
    type_text = node_text(type_node, source) if type_node is not None else ""

    declarator = first_child_of_type(field, "variable_declarator")
    name_text = identifier_text(declarator, "name", source) if declarator else ""
    return type_text, name_text


def _method_return_type(method_node: TSNode, source: bytes) -> str:
    """Return the method's declared return type, or ``""`` for void."""
    type_node = method_node.child_by_field_name("type")
    if type_node is None:
        return ""
    # ``void_type`` is a distinct node kind — ``@Bean`` can't return
    # void, so filter it out here.
    if type_node.type == "void_type":
        return ""
    return node_text(type_node, source)


def _strip_generics(type_text: str) -> str:
    """Strip generic parameters from a type name.

    ``Optional<Foo>`` → ``Optional``. ``Map<K, V>`` → ``Map``.
    Arrays (``Foo[]``) also get their suffix dropped so the raw type
    is what ends up as the dependency target. Graph consumers see
    the outer type; the parametrization is lost (documented
    non-goal for the MVP).
    """
    idx = type_text.find("<")
    if idx >= 0:
        type_text = type_text[:idx]
    # Strip array suffix.
    while type_text.endswith("[]"):
        type_text = type_text[:-2]
    return type_text.strip()


def _clean_type_name(type_text: str) -> str:
    """Strip generics / arrays AND the package qualifier, return the
    bare type name.

    Graph layers match symbols by their unqualified class names, so a
    declaration like ``public UserService(com.example.UserRepo repo)``
    has to resolve to ``"UserRepo"`` — emitting the dotted path would
    leave the edge pointing at a non-existent external entity. Strip
    the generics first (so ``com.example.List<Foo>`` collapses in a
    single pass), then take the final ``.``-separated segment.
    """
    stripped = _strip_generics(type_text)
    return last_name_segment(stripped) if stripped else ""


def _normalise_type(type_text: str) -> Optional[str]:
    """Return the cleaned dependency type, or ``None`` for anything
    not a valid DI target.

    Wraps :func:`_clean_type_name` with a primitive filter — the
    type must not be empty after cleaning and must not be a Java
    primitive. Catches two traps:

    1. ``int[]``: raw text doesn't match ``_JAVA_PRIMITIVES``,
       strip-to-``int`` does. Order matters.
    2. ``com.example.Foo``: qualified names must reduce to their
       tail before matching, otherwise the edge targets a dotted
       path the graph layer can't resolve.
    """
    cleaned = _clean_type_name(type_text)
    if not cleaned or cleaned in _JAVA_PRIMITIVES:
        return None
    return cleaned


def _decapitalize(class_name: str) -> str:
    """Spring's default bean-name rule: first letter lowercased unless
    the first two letters are both uppercase (``URL`` stays ``URL``).

    This matches ``java.beans.Introspector.decapitalize`` which Spring
    uses internally. Matters because a consumer searching by bean
    name (via ``@Qualifier`` or ``@Resource("name")``) uses the
    decapitalized form.
    """
    if not class_name:
        return class_name
    if len(class_name) > 1 and class_name[0].isupper() and class_name[1].isupper():
        return class_name
    return class_name[0].lower() + class_name[1:]


# ---------------------------------------------------------------------------
# Chunk attachment
# ---------------------------------------------------------------------------


def _attach(
    chunks: List[ParserChunk],
    beans: List[_Bean],
    deps: List[_Dep],
    file_path: str,
) -> None:
    """Attach ``spring_di_bean`` and ``spring_di_depends_on`` edges to
    the chunk that carries the provider or consumer symbol.

    Matching mirrors the route recognizers' tiered strategy:

    1. Primary: ``(name, line_start)`` lookup via ``element_name``
       or ``symbol_metadata``.
    2. Secondary: name only, if exactly one chunk advertises the
       name (refuse to guess when multiple candidates).
    3. Last-resort fallback: the ``code_full`` whole-file chunk
       (if the base parser produced one). Kept out of the name
       indices so it doesn't introduce ambiguity, but used here
       so routes aren't silently dropped when the only chunk is
       the whole-file sentinel.

    Identity-based dedup at insertion so a per-method chunk listed
    both via ``element_name`` and its own ``symbol_metadata``
    doesn't inflate the candidate pool.

    Idempotence keys differ between the two edge types:

    - Beans: ``(type, source_name, target_name, stereotype, kind)``
      — distinct stereotypes on the same provider (shouldn't
      happen in practice) stay distinct.
    - Deps: ``(type, source_name, target_name, injection_type,
      parameter_name)`` — the same consumer depending on the same
      target via different injection points (e.g. constructor
      AND field, an anti-pattern but seen) stays distinct, and
      two distinct params of the same method injecting the same
      type stay distinct too.
    """
    by_name_line: Dict[Tuple[str, int], ParserChunk] = {}
    by_name: Dict[str, List[ParserChunk]] = {}
    code_full_fallback: Optional[ParserChunk] = None

    def _add(name: str, chunk: ParserChunk) -> None:
        bucket = by_name.setdefault(name, [])
        for existing in bucket:
            if existing is chunk:
                return
        bucket.append(chunk)

    for chunk in chunks:
        if chunk.element_type == "code_full":
            if code_full_fallback is None:
                code_full_fallback = chunk
            continue

        if chunk.element_name and chunk.element_type in (
            "class",
            "method",
            "function",
        ):
            _add(chunk.element_name, chunk)
            if chunk.line_start is not None:
                by_name_line[(chunk.element_name, chunk.line_start)] = chunk

        for sym_name, sym_meta in (chunk.symbol_metadata or {}).items():
            if not sym_name:
                continue
            if sym_meta.get("type") not in ("class", "method", "function"):
                continue
            if chunk.element_name == sym_name:
                continue
            _add(sym_name, chunk)
            start_line = sym_meta.get("start_line")
            if isinstance(start_line, int):
                by_name_line.setdefault((sym_name, start_line), chunk)

    def _locate(name: str, line: int) -> Optional[ParserChunk]:
        chunk = by_name_line.get((name, line))
        if chunk is not None:
            return chunk
        candidates = by_name.get(name, [])
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            # Ambiguous name (e.g. two classes with the same name in
            # one file, or overloaded ``@Bean`` methods). Refuse to
            # guess — dropping the edge is strictly better than
            # misattributing it to the whole-file chunk where it
            # could collide with unrelated symbols.
            return None
        # No candidates at all — the base parser didn't carry the
        # name in any per-entity chunk. Fall back to ``code_full``
        # if available so the edge isn't silently lost.
        return code_full_fallback

    for bean in beans:
        chunk = _locate(bean.provider_name, bean.provider_line)
        if chunk is None:
            continue
        relationship = ParserRelationship(
            source_type="class"
            if bean.provider_kind == "class_stereotype"
            else "method",
            source_name=bean.provider_name,
            target_type="class",
            target_name=bean.bean_type,
            type="spring_di_bean",
            target_path=file_path,
            metadata={
                "stereotype": bean.stereotype,
                "bean_name": bean.bean_name,
                "kind": bean.provider_kind,
                "framework": "spring",
            },
        )
        if not _has_equivalent_bean(chunk.relationships, relationship):
            chunk.relationships.append(relationship)

    for dep in deps:
        chunk = _locate(dep.consumer_name, dep.consumer_line)
        if chunk is None:
            continue
        relationship = ParserRelationship(
            source_type=dep.consumer_kind,
            source_name=dep.consumer_name,
            target_type="class",
            target_name=dep.dependency_type,
            type="spring_di_depends_on",
            target_path=file_path,
            metadata={
                "injection_type": dep.injection_type,
                "parameter_name": dep.parameter_name,
                "qualifier": dep.qualifier,
                "framework": "spring",
            },
        )
        if not _has_equivalent_dep(chunk.relationships, relationship):
            chunk.relationships.append(relationship)


def _has_equivalent_bean(
    existing: List[ParserRelationship],
    candidate: ParserRelationship,
) -> bool:
    """Bean dedup key: ``(type, source_name, target_name, stereotype,
    kind)``. Two beans provided by the same provider with the same
    target and stereotype are the same bean; different stereotypes
    on the same provider shouldn't happen in practice but would be
    distinct if they did."""
    want_target = candidate.target_name
    want_stereotype = candidate.metadata.get("stereotype")
    want_kind = candidate.metadata.get("kind")
    for rel in existing:
        if rel.type != candidate.type:
            continue
        if rel.source_name != candidate.source_name:
            continue
        if rel.target_name != want_target:
            continue
        if (
            rel.metadata.get("stereotype") == want_stereotype
            and rel.metadata.get("kind") == want_kind
        ):
            return True
    return False


def _has_equivalent_dep(
    existing: List[ParserRelationship],
    candidate: ParserRelationship,
) -> bool:
    """Dep dedup key: ``(type, source_name, target_name, injection_type,
    parameter_name)``. Two dependencies on the same type via the same
    injection point and parameter are the same dependency; the same
    consumer depending on the same type via *different* injection
    points (e.g. constructor AND field, which would be an anti-pattern
    but happens) stays distinct."""
    want_target = candidate.target_name
    want_injection = candidate.metadata.get("injection_type")
    want_param = candidate.metadata.get("parameter_name")
    for rel in existing:
        if rel.type != candidate.type:
            continue
        if rel.source_name != candidate.source_name:
            continue
        if rel.target_name != want_target:
            continue
        if (
            rel.metadata.get("injection_type") == want_injection
            and rel.metadata.get("parameter_name") == want_param
        ):
            return True
    return False
