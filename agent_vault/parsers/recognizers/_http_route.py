"""Shared base class for HTTP route recognizers.

All framework-specific HTTP route recognizers (Spring, NestJS,
Express, FastAPI, ...) follow the same shape:

1. Pre-filter source bytes for framework markers — skip the parse
   entirely when the file obviously isn't this framework.
2. Parse with tree-sitter (language + grammar vary by recognizer).
3. Walk the AST to extract route records — the ONLY step that's
   genuinely framework-specific.
4. Attach route relationships to the chunk that carries the
   handler.

This module owns 1, 2, and 4 plus the ``_Route`` struct and
idempotence semantics. Subclasses implement step 3 plus a handful
of class attributes.

**Subclass contract.** A concrete recognizer must set:

- ``name``: unique registry identifier (e.g. ``"java_spring"``)
- ``file_extensions``: frozenset of extensions to dispatch on
- ``_relationship_type``: relationship string emitted onto chunks
  (e.g. ``"spring_route"``)
- ``_framework_name``: goes into ``metadata["framework"]``
  (e.g. ``"spring"``)
- ``_tree_sitter_language``: language key for
  ``tree_sitter_language_pack.get_parser`` (e.g. ``"java"``)
- ``_pre_filter_markers``: tuple of byte-strings; if none appear in
  the source, the parse is skipped

and implement:

- ``_extract_routes(root_node, source) -> list[_Route]``

May optionally override:

- ``_extra_dedup_metadata_keys``: extra metadata keys to include
  in the idempotence equivalence (e.g. ``("receiver",)`` for
  Express so ``app.get('/x', h)`` and ``router.get('/x', h)`` stay
  distinct).

**Attachment strategy (shared).** A route's ``source_name``
identifies the handler; ``source_line`` gives a hint for
disambiguation. Attachment tries, in order:

1. Primary: ``(source_name, source_line)`` exact match in
   ``by_name_line``.
2. Secondary: ``by_name`` if exactly one candidate chunk
   advertises the name (refuse to guess when ambiguous).
3. Range: the narrowest chunk whose line range contains
   ``source_line`` — catches anonymous handlers attached to a
   surrounding setup function.
4. Last resort: the ``code_full`` whole-file fallback chunk, if
   the base parser emitted one.

``code_full`` is kept out of the name indices entirely so it
doesn't introduce ambiguity against per-entity chunks, but
becomes the last-resort target so routes aren't silently dropped
when the base parser only produced the whole-file sentinel.

**Why a base class rather than composition.** Every recognizer
pays the cost of lazy parser loading, the tiered match, and
idempotence dedup — and every tweak to that machinery has to be
repeated across every recognizer file. With four concrete
recognizers already and more planned, the duplication is the
shape the abstraction should take. Composition with protocol
hooks would be more flexible but also harder to follow —
inheritance matches the "every subclass is a fully functioning
recognizer that replaces at most ``_extract_routes``" story.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, cast

from agent_vault.parsers.models import (
    ParsedDocument,
    ParserChunk,
    ParserRelationship,
)

logger = logging.getLogger(__name__)


@dataclass
class _Route:
    """Extracted route data, language-agnostic.

    ``source_name`` is the handler identifier (or ``<anonymous>@L42``
    for inline handlers). ``source_line`` is a line hint used for
    disambiguation — Spring/NestJS use the method's start line,
    Express uses the registration call-site line.

    ``metadata`` is framework-specific extras that get merged into
    the emitted relationship's metadata (controller class, receiver
    name, mount prefix, ...). The core edge semantics live on
    ``source_name``, ``http_method``, and ``path``.
    """

    source_name: str
    source_line: int
    http_method: str
    path: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class HTTPRouteRecognizer:
    """Base for framework recognizers that emit HTTP route edges."""

    # ------------------------------------------------------------------
    # Subclass-provided class attributes (MUST be set).
    # ------------------------------------------------------------------
    name: str = ""
    file_extensions: FrozenSet[str] = frozenset()

    _relationship_type: str = ""
    _framework_name: str = ""
    _tree_sitter_language: str = ""
    _pre_filter_markers: Tuple[bytes, ...] = ()

    # ------------------------------------------------------------------
    # Subclass-optional class attributes.
    # ------------------------------------------------------------------
    # Extra metadata keys to include in the idempotence equivalence
    # check. ``http_method`` and ``path`` are always checked; this
    # attribute lets subclasses preserve distinct edges that share
    # those but differ on a framework-specific dimension (e.g.
    # Express's ``receiver`` — same handler on ``app`` vs ``router``).
    _extra_dedup_metadata_keys: Tuple[str, ...] = ()

    def __init__(self) -> None:
        # Lazy tree-sitter parser cache. Two-state (parser OR
        # ``_parser_load_failed``) so a failed load isn't retried
        # on every subsequent enrich call. ``_parser_lock`` guards
        # the one-time load transition; the steady-state fast path
        # reads both state fields without locking.
        self._parser: Any = None
        self._parser_load_failed: bool = False
        self._parser_lock = threading.Lock()

    async def enrich(self, parsed: ParsedDocument) -> ParsedDocument:
        """Entry point — pre-filter, parse, extract, attach."""
        try:
            source = Path(parsed.file_path).read_bytes()
        except OSError as exc:
            logger.debug(
                "%s: could not read %s: %s",
                type(self).__name__,
                parsed.file_path,
                exc,
            )
            return parsed

        if not any(marker in source for marker in self._pre_filter_markers):
            return parsed

        parser = self._get_parser()
        if parser is None:
            return parsed

        try:
            tree = parser.parse(source)
        except Exception as exc:
            logger.debug(
                "%s: parse failed for %s: %s",
                type(self).__name__,
                parsed.file_path,
                exc,
            )
            return parsed

        routes = self._extract_routes(tree.root_node, source)
        if not routes:
            return parsed

        self._attach_routes(parsed.chunks, routes, parsed.file_path)
        return parsed

    def _get_parser(self) -> Any:
        """Lazy load the tree-sitter parser, double-checked under lock."""
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

                # ``get_parser`` is typed with a ``Literal[...]`` of
                # supported languages. The class attribute is a
                # plain ``str`` (because subclasses set it
                # individually), which mypy can't narrow back to
                # the Literal. Cast to ``Any`` rather than couple
                # the base class to the third-party Literal alias
                # (which would be a versioning hazard if the pack
                # adds/removes languages).
                self._parser = get_parser(cast(Any, self._tree_sitter_language))
            except Exception as exc:
                logger.debug(
                    "%s: tree-sitter parser %r unavailable: %s",
                    type(self).__name__,
                    self._tree_sitter_language,
                    exc,
                )
                self._parser_load_failed = True
                return None
            return self._parser

    def _extract_routes(self, root_node: Any, source: bytes) -> List[_Route]:
        """Walk the AST, return extracted routes.

        Subclasses MUST override. The base raises so a misconfigured
        subclass fails loudly instead of silently producing zero
        edges.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _extract_routes"
        )

    # ------------------------------------------------------------------
    # Chunk attachment (shared).
    # ------------------------------------------------------------------

    def _attach_routes(
        self,
        chunks: List[ParserChunk],
        routes: List[_Route],
        file_path: str,
    ) -> None:
        """Attach ``ParserRelationship`` edges to matching chunks.

        See the module docstring for the tiered matching strategy
        and rationale for each tier.
        """
        by_name_line: Dict[Tuple[str, int], ParserChunk] = {}
        by_name: Dict[str, List[ParserChunk]] = {}
        ranged: List[Tuple[int, int, ParserChunk]] = []
        code_full_fallback: Optional[ParserChunk] = None

        def _add(name: str, chunk: ParserChunk) -> None:
            """Append chunk under ``name`` unless this exact object
            is already there. A per-method chunk that lists its own
            method both via ``element_name`` and ``symbol_metadata``
            would otherwise register twice and inflate the
            ambiguity check."""
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
                "module",
            ):
                _add(chunk.element_name, chunk)
                if chunk.line_start is not None:
                    by_name_line[(chunk.element_name, chunk.line_start)] = chunk

            for sym_name, sym_meta in (chunk.symbol_metadata or {}).items():
                if not sym_name:
                    continue
                if sym_meta.get("type") not in ("method", "function"):
                    continue
                if chunk.element_name == sym_name:
                    continue
                _add(sym_name, chunk)
                start_line = sym_meta.get("start_line")
                if isinstance(start_line, int):
                    by_name_line.setdefault((sym_name, start_line), chunk)

            if (
                chunk.line_start is not None
                and chunk.line_end is not None
                and chunk.line_start > 0
            ):
                ranged.append((chunk.line_start, chunk.line_end, chunk))

        for route in routes:
            chunk = self._locate_chunk(
                route,
                by_name_line,
                by_name,
                ranged,
                code_full_fallback,
            )
            if chunk is None:
                continue

            relationship = ParserRelationship(
                source_type=_resolve_source_type(chunk, route.source_name),
                source_name=route.source_name,
                target_type="http_route",
                target_name=f"{route.http_method} {route.path}",
                type=self._relationship_type,
                target_path=file_path,
                metadata={
                    "http_method": route.http_method,
                    "path": route.path,
                    "framework": self._framework_name,
                    **route.metadata,
                },
            )

            if not self._has_equivalent(chunk.relationships, relationship):
                chunk.relationships.append(relationship)

    def _locate_chunk(
        self,
        route: _Route,
        by_name_line: Dict[Tuple[str, int], ParserChunk],
        by_name: Dict[str, List[ParserChunk]],
        ranged: List[Tuple[int, int, ParserChunk]],
        code_full_fallback: Optional[ParserChunk],
    ) -> Optional[ParserChunk]:
        """Tiered match:

        1. ``(name, line)`` primary.
        2. name-only secondary (unambiguous).
        3. **Ambiguous name:** disambiguate *among the name
           candidates* by line — the narrowest candidate whose
           range covers ``source_line`` wins. If none contain the
           line, refuse (``None``).
        4. No name candidates at all: full range match for
           anonymous handlers whose ``source_name`` doesn't
           appear in any chunk (e.g. ``<anonymous>@L42``).
        5. ``code_full`` last resort.

        Tier 3 vs 4 matter for recognizers where ``source_line``
        semantics differ. Spring/NestJS use the handler's own line,
        so ambiguous same-name handlers disambiguate cleanly by
        their own line. Express uses the call-site line, which
        isn't inside any handler chunk — so ambiguous named
        handlers in Express refuse rather than mis-attach to the
        setup chunk that happens to contain the call. Anonymous
        handlers in Express deliberately skip Tier 3 (no name
        candidates) and land on the setup chunk via Tier 4.
        """
        # Tier 1: primary exact match.
        chunk = by_name_line.get((route.source_name, route.source_line))
        if chunk is not None:
            return chunk

        # Tier 2: name-only, only when unambiguous.
        candidates = by_name.get(route.source_name, [])
        if len(candidates) == 1:
            return candidates[0]

        # Tier 3: ambiguous name — disambiguate among candidates by
        # line, or refuse.
        if len(candidates) > 1:
            chunk = _narrowest_range_among(candidates, route.source_line)
            if chunk is not None:
                return chunk
            # No candidate's range contains source_line. Rather
            # than misattributing to a chunk that merely happens
            # to span the registration site, drop the edge.
            return None

        # Tier 4: no name match at all — full range fallback for
        # anonymous handlers.
        chunk = _narrowest_range_match(ranged, route.source_line)
        if chunk is not None:
            return chunk

        # Tier 5: last-resort code_full.
        return code_full_fallback

    def _has_equivalent(
        self,
        existing: List[ParserRelationship],
        candidate: ParserRelationship,
    ) -> bool:
        """Idempotence equivalence check.

        Key is ``(type, source_name, http_method, path)`` plus any
        extra metadata keys the subclass declared via
        ``_extra_dedup_metadata_keys``. Two relationships that
        match on all keys are considered the same edge; a re-run
        of ``enrich`` won't create a duplicate.
        """
        keys: Tuple[str, ...] = (
            "http_method",
            "path",
        ) + self._extra_dedup_metadata_keys
        want = {key: candidate.metadata.get(key) for key in keys}
        for rel in existing:
            if rel.type != candidate.type:
                continue
            if rel.source_name != candidate.source_name:
                continue
            if all(rel.metadata.get(key) == value for key, value in want.items()):
                return True
        return False


def _narrowest_range_match(
    ranged: List[Tuple[int, int, ParserChunk]],
    line: int,
) -> Optional[ParserChunk]:
    """Return the chunk with the smallest line range containing ``line``.

    ``ranged`` entries are ``(line_start, line_end, chunk)``.
    Narrower wins so a route inside ``setupRoutes()`` attaches to
    that function's chunk rather than the enclosing module chunk
    (both may contain the call site line).
    """
    best_chunk: Optional[ParserChunk] = None
    best_span: Optional[int] = None
    for start, end, candidate in ranged:
        if start <= line <= end:
            span = end - start
            if best_span is None or span < best_span:
                best_span = span
                best_chunk = candidate
    return best_chunk


def _resolve_source_type(chunk: ParserChunk, source_name: str) -> str:
    """Pick the relationship's ``source_type`` to match the entity
    type ``unified_code`` will use for the same symbol.

    Downstream graph builders construct entity IDs from
    ``(source_type, file_path, source_name)``. If the recognizer
    emits an edge keyed on ``method::...`` but the base parser
    registered the symbol as ``function::...`` (Python
    top-level def, TypeScript module-level function), the join
    fails and the edge dangles.

    Resolution order:

    1. ``chunk.symbol_metadata[source_name]["type"]`` — the most
       specific signal; matches what ``unified_code`` records for
       the symbol.
    2. ``chunk.element_type`` when ``chunk.element_name`` is the
       handler — covers per-method/per-function chunks where the
       handler IS the chunk's primary symbol.
    3. ``chunk.element_type`` when the chunk is a function/method
       enclosing the route registration (typical for anonymous
       Express handlers attached to a ``setupRoutes()`` chunk).
    4. ``"method"`` default — Spring/NestJS class handlers and
       any pathological case where no other signal is available.
    """
    sym_meta = (chunk.symbol_metadata or {}).get(source_name)
    if isinstance(sym_meta, dict):
        sym_type = sym_meta.get("type")
        if sym_type in ("method", "function"):
            return sym_type
    if chunk.element_name == source_name and chunk.element_type in (
        "method",
        "function",
    ):
        return chunk.element_type
    if chunk.element_type in ("method", "function"):
        return chunk.element_type
    return "method"


def _narrowest_range_among(
    candidates: List[ParserChunk],
    line: int,
) -> Optional[ParserChunk]:
    """Ambiguity disambiguation: among chunks that already share a
    name, return the narrowest whose range contains ``line``.

    Distinct from :func:`_narrowest_range_match` in that the
    search space is the pre-filtered name candidates, not every
    chunk in the file. This is what lets ambiguous-name matches
    resolve by proximity without leaking to unrelated chunks.
    """
    best_chunk: Optional[ParserChunk] = None
    best_span: Optional[int] = None
    for chunk in candidates:
        start = chunk.line_start
        end = chunk.line_end
        if start is None or end is None or start <= 0:
            continue
        if start <= line <= end:
            span = end - start
            if best_span is None or span < best_span:
                best_span = span
                best_chunk = chunk
    return best_chunk


# ---------------------------------------------------------------------------
# Small string helper shared by path-composing recognizers.
# ---------------------------------------------------------------------------


def join_paths(base: str, sub: str) -> str:
    """Combine a class/router base path with a handler-level path.

    Normalises slash boundaries so ``/api`` + ``/users`` and
    ``/api/`` + ``users`` both produce ``/api/users``. Class-level
    ``"/"`` combined with handler ``"/x"`` collapses to ``/x``
    (not ``//x``). If both halves are empty the handler binds to
    the container's root and we return ``/`` (not ``""``) so every
    emitted path is well-formed.
    """
    left = base.rstrip("/")
    if left and not left.startswith("/"):
        left = "/" + left
    right = sub.lstrip("/")

    if not left and not right:
        return "/"
    if not left:
        return "/" + right
    if not right:
        return left
    return f"{left}/{right}"


__all__ = [
    "HTTPRouteRecognizer",
    "_Route",
    "join_paths",
]
