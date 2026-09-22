"""Salesforce Apex recognizer.

Adds framework edges the generic Apex grammar cannot mean: which
sObject a trigger watches, which objects a SOQL query names, and
which methods are exposed as Aura/REST entry points.

Edge kinds:

- ``salesforce_observes``: trigger → sObject. ``metadata.events`` is a
  comma-separated event list (``before insert,after update``).
- ``salesforce_queries``: method → sObject from a SOQL ``FROM`` clause.
- ``salesforce_route``: method exposed via ``@HttpGet`` / ``@HttpPost``
  / ``@HttpPut`` / ``@HttpPatch`` / ``@HttpDelete``, class-level
  ``@RestResource(urlMapping=...)``, or ``@AuraEnabled``.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from agentic_inquiry.parsers.models import (
    ParsedDocument,
    ParserChunk,
    ParserRelationship,
)
from agentic_inquiry.parsers.recognizers._tree_sitter_utils import (
    TSNode,
    first_child_of_type,
    identifier_text,
    iter_children_of_type,
    last_name_segment,
    node_text,
)

logger = logging.getLogger(__name__)

_HTTP_ANNOTATIONS: Dict[str, str] = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpPatch": "PATCH",
    "HttpDelete": "DELETE",
}

_PRE_FILTER_MARKERS: Tuple[bytes, ...] = (
    b"@AuraEnabled",
    b"@RestResource",
    b"@HttpGet",
    b"@HttpPost",
    b"@HttpPut",
    b"@HttpPatch",
    b"@HttpDelete",
)

# DX / Prettier often wraps SOQL as `[ \n SELECT ... ]` or `[Select ...]`.
_SOQL_MARKER = re.compile(rb"\[\s*select\b", re.IGNORECASE)
_TRIGGER_MARKER = re.compile(rb"trigger\s", re.IGNORECASE)


def _has_apex_markers(source: bytes) -> bool:
    if any(marker in source for marker in _PRE_FILTER_MARKERS):
        return True
    if _TRIGGER_MARKER.search(source):
        return True
    return _SOQL_MARKER.search(source) is not None


def _walk(node: TSNode) -> List[TSNode]:
    """Collect this node and every descendant (named and anonymous)."""
    found = [node]
    for child in node.children:
        found.extend(_walk(child))
    return found


def _annotation_name(annotation: TSNode, source: bytes) -> str:
    ident = first_child_of_type(annotation, "identifier")
    if ident is None:
        return ""
    return last_name_segment(node_text(ident, source))


def _annotation_string_arg(annotation: TSNode, key: str, source: bytes) -> str:
    """Return the string literal for ``key=...`` on an annotation, or ``""``."""
    args = first_child_of_type(annotation, "annotation_argument_list")
    if args is None:
        return ""
    for kv in iter_children_of_type(args, "annotation_key_value"):
        name = first_child_of_type(kv, "identifier")
        if name is None or node_text(name, source) != key:
            continue
        literal = first_child_of_type(kv, "string_literal")
        if literal is None:
            return ""
        raw = node_text(literal, source)
        return raw.strip("'\"")
    return ""


def _modifiers_annotations(decl: TSNode, source: bytes) -> List[Tuple[str, TSNode]]:
    modifiers = first_child_of_type(decl, "modifiers")
    if modifiers is None:
        return []
    out: List[Tuple[str, TSNode]] = []
    for ann in iter_children_of_type(modifiers, "annotation"):
        name = _annotation_name(ann, source)
        if name:
            out.append((name, ann))
    return out


def _containing_method_name(node: TSNode, source: bytes) -> str:
    current = node
    while current is not None:
        if current.type == "method_declaration":
            return identifier_text(current, "name", source)
        current = current.parent
    return ""


def _soql_from_objects(root: TSNode, source: bytes) -> List[Tuple[str, str]]:
    """Return ``(method_name, sobject)`` pairs from SOQL ``FROM`` clauses."""
    pairs: List[Tuple[str, str]] = []
    for node in _walk(root):
        if node.type != "from_clause":
            continue
        method = _containing_method_name(node, source)
        if not method:
            continue
        for storage in _walk(node):
            if storage.type != "storage_identifier":
                continue
            ident = first_child_of_type(storage, "identifier")
            if ident is None:
                continue
            sobject = node_text(ident, source)
            if sobject:
                pairs.append((method, sobject))
    return pairs


def _extract_edges(root: TSNode, source: bytes) -> List[ParserRelationship]:
    edges: List[ParserRelationship] = []

    for trigger in (n for n in _walk(root) if n.type == "trigger_declaration"):
        name = identifier_text(trigger, "name", source)
        sobject = identifier_text(trigger, "object", source)
        if not name or not sobject:
            continue
        events: List[str] = []
        for ev in iter_children_of_type(trigger, "trigger_event"):
            text = node_text(ev, source).strip()
            if text:
                events.append(text)
        edges.append(
            ParserRelationship(
                source_type="class",
                source_name=name,
                target_type="class",
                target_name=sobject,
                type="salesforce_observes",
                metadata={"events": ",".join(events)},
            )
        )

    for method, sobject in _soql_from_objects(root, source):
        edges.append(
            ParserRelationship(
                source_type="method",
                source_name=method,
                target_type="class",
                target_name=sobject,
                type="salesforce_queries",
                metadata={},
            )
        )

    for cls in (n for n in _walk(root) if n.type == "class_declaration"):
        class_path = ""
        for ann_name, ann in _modifiers_annotations(cls, source):
            if ann_name == "RestResource":
                class_path = _annotation_string_arg(ann, "urlMapping", source)
        for method in (n for n in _walk(cls) if n.type == "method_declaration"):
            method_name = identifier_text(method, "name", source)
            if not method_name:
                continue
            for ann_name, ann in _modifiers_annotations(method, source):
                if ann_name == "AuraEnabled":
                    edges.append(
                        ParserRelationship(
                            source_type="method",
                            source_name=method_name,
                            target_type="method",
                            target_name=method_name,
                            type="salesforce_route",
                            metadata={"aura_enabled": True},
                        )
                    )
                http_method = _HTTP_ANNOTATIONS.get(ann_name)
                if http_method:
                    edges.append(
                        ParserRelationship(
                            source_type="method",
                            source_name=method_name,
                            target_type="method",
                            target_name=method_name,
                            type="salesforce_route",
                            metadata={
                                "http_method": http_method,
                                "path": class_path,
                            },
                        )
                    )

    return edges


def _rel_key(rel: ParserRelationship) -> Tuple[Any, ...]:
    meta = rel.metadata or {}
    return (
        rel.type,
        rel.source_name,
        rel.target_name,
        meta.get("events"),
        meta.get("http_method"),
        meta.get("path"),
        meta.get("aura_enabled"),
    )


def _attach(chunks: List[ParserChunk], edges: List[ParserRelationship]) -> None:
    if not chunks:
        return
    for edge in edges:
        target: Optional[ParserChunk] = None
        for chunk in chunks:
            if chunk.element_name == edge.source_name:
                target = chunk
                break
        if target is None:
            for chunk in chunks:
                if edge.source_name in (chunk.symbols or []):
                    target = chunk
                    break
        if target is None:
            target = chunks[0]
        existing = {_rel_key(rel) for rel in target.relationships}
        if _rel_key(edge) not in existing:
            target.relationships.append(edge)


class ApexSalesforceRecognizer:
    """Recognizer that adds Salesforce Apex framework edges."""

    name = "apex_salesforce"
    file_extensions: FrozenSet[str] = frozenset({".cls", ".trigger", ".apex"})

    def __init__(self) -> None:
        self._parser: Any = None
        self._parser_load_failed = False
        self._parser_lock = threading.Lock()

    async def enrich(self, parsed: ParsedDocument) -> ParsedDocument:
        try:
            source = Path(parsed.file_path).read_bytes()
        except OSError as exc:
            logger.debug(
                "ApexSalesforceRecognizer: could not read %s: %s",
                parsed.file_path,
                exc,
            )
            return parsed

        if not _has_apex_markers(source):
            return parsed

        parser = self._get_parser()
        if parser is None:
            return parsed

        try:
            tree = parser.parse(source)
        except Exception as exc:
            logger.debug(
                "ApexSalesforceRecognizer: parse failed for %s: %s",
                parsed.file_path,
                exc,
            )
            return parsed

        edges = _extract_edges(tree.root_node, source)
        if not edges:
            return parsed
        _attach(parsed.chunks, edges)
        return parsed

    def _get_parser(self) -> Any:
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

                self._parser = get_parser("apex")
            except Exception as exc:
                logger.debug(
                    "ApexSalesforceRecognizer: Apex parser unavailable: %s",
                    exc,
                )
                self._parser_load_failed = True
                return None
            return self._parser
