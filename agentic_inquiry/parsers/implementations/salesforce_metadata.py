"""Suffix-gated parser for a short Salesforce metadata allowlist.

Claims only source-format files whose names end in one of five
suffixes. Other XML (POMs, ``*.cls-meta.xml``, MDAPI ``.object``
blobs) stays on DocumentParser.

Extraction is intentionally small: enough for ``/ai:impact Account``
to see fields, Flows, FlexiPages, and layouts that bind an sObject.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import aiofiles

from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship

logger = logging.getLogger(__name__)

_SUFFIXES: Tuple[str, ...] = (
    ".object-meta.xml",
    ".field-meta.xml",
    ".flow-meta.xml",
    ".flexipage-meta.xml",
    ".layout-meta.xml",
)

_APEX_CLASS = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_]*\.)?[A-Z][A-Za-z0-9_]*$")
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB, same cap as unified_code


def _stem_before_suffix(filename: str, suffix: str) -> str:
    """Strip ``suffix`` from ``filename`` without regard to letter case."""
    if filename.lower().endswith(suffix):
        return filename[: -len(suffix)]
    return Path(filename).stem


def _local_tag(tag: str) -> str:
    """Strip an XML namespace brace so ``{ns}object`` becomes ``object``."""
    return tag.rsplit("}", 1)[-1]


def _iter_local(root: ET.Element, name: str) -> Iterable[ET.Element]:
    for el in root.iter():
        if _local_tag(el.tag) == name:
            yield el


def _text(el: ET.Element) -> str:
    return (el.text or "").strip()


def _rel(
    source_type: str,
    source_name: str,
    target_type: str,
    target_name: str,
    rel_type: str,
) -> ParserRelationship:
    return ParserRelationship(
        source_type=source_type,
        source_name=source_name,
        target_type=target_type,
        target_name=target_name,
        type=rel_type,
        metadata={},
    )


def _chunk(
    path: Path,
    name: str,
    element_type: str,
    content: str,
    relationships: Sequence[ParserRelationship],
) -> ParserChunk:
    return ParserChunk(
        content=content,
        fts_text=f"{name} {content}",
        content_type="CODE",
        language="xml",
        element_type=element_type,
        element_name=name,
        symbols=[name],
        relationships=list(relationships),
        metadata={},
        line_start=1,
        line_end=content.count("\n") + 1,
    )


def _object_from_field_path(path: Path) -> str:
    """``…/<Object>/fields/Status__c.field-meta.xml`` → ``<Object>``.

    Uses the directory immediately above ``fields`` so a path that also
    contains an earlier ``objects`` segment (a project folder, a DX
    package name) still resolves to the sObject.
    """
    parts = path.parts
    if "fields" in parts:
        idx = len(parts) - 1 - parts[::-1].index("fields")
        if idx > 0:
            return parts[idx - 1]
    return ""


def _object_from_layout_name(stem: str) -> str:
    """``Account-Account Layout`` → ``Account``."""
    if "-" in stem:
        return stem.split("-", 1)[0]
    return stem


def _extract(path: Path, text: str) -> List[ParserChunk]:
    name = path.name.lower()
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        logger.warning("Salesforce metadata XML parse failed for %s: %s", path, exc)
        return [
            _chunk(path, path.stem, "file", text, ()),
        ]

    if name.endswith(".object-meta.xml"):
        object_name = _stem_before_suffix(path.name, ".object-meta.xml")
        return [_chunk(path, object_name, "object", text, ())]

    if name.endswith(".field-meta.xml"):
        field_name = ""
        for el in _iter_local(root, "fullName"):
            field_name = _text(el)
            break
        if not field_name:
            field_name = _stem_before_suffix(path.name, ".field-meta.xml")
        object_name = _object_from_field_path(path)
        rels: List[ParserRelationship] = []
        if object_name:
            rels.append(
                _rel("class", object_name, "property", field_name, "salesforce_field")
            )
        return [_chunk(path, field_name, "property", text, rels)]

    if name.endswith(".flow-meta.xml"):
        flow_name = _stem_before_suffix(path.name, ".flow-meta.xml")
        for el in _iter_local(root, "fullName"):
            if _text(el):
                flow_name = _text(el)
                break
        objects = {_text(el) for el in _iter_local(root, "object") if _text(el)}
        apex_actions: List[str] = []
        for container in list(_iter_local(root, "actionCalls")) + list(
            _iter_local(root, "actionCall")
        ):
            action_type = ""
            action_name = ""
            for child in container.iter():
                local = _local_tag(child.tag)
                if local == "actionType":
                    action_type = _text(child)
                elif local == "actionName":
                    action_name = _text(child)
            if action_type.lower() == "apex" and _APEX_CLASS.match(action_name):
                apex_actions.append(action_name)
        rels = [
            _rel("function", flow_name, "class", obj, "salesforce_touches")
            for obj in sorted(objects)
        ]
        rels.extend(
            _rel("function", flow_name, "class", action, "salesforce_invokes")
            for action in apex_actions
        )
        return [_chunk(path, flow_name, "function", text, rels)]

    if name.endswith(".flexipage-meta.xml"):
        page_name = _stem_before_suffix(path.name, ".flexipage-meta.xml")
        objects = {_text(el) for el in _iter_local(root, "sobjectType") if _text(el)}
        rels = [
            _rel("function", page_name, "class", obj, "salesforce_touches")
            for obj in sorted(objects)
        ]
        return [_chunk(path, page_name, "function", text, rels)]

    if name.endswith(".layout-meta.xml"):
        layout_stem = _stem_before_suffix(path.name, ".layout-meta.xml")
        object_name = _object_from_layout_name(layout_stem)
        fields = {_text(el) for el in _iter_local(root, "field") if _text(el)}
        layout_rels: List[ParserRelationship] = []
        if object_name:
            layout_rels.append(
                _rel(
                    "function", layout_stem, "class", object_name, "salesforce_touches"
                )
            )
            for field_name in sorted(fields):
                layout_rels.append(
                    _rel(
                        "function",
                        layout_stem,
                        "property",
                        field_name,
                        "salesforce_touches",
                    )
                )
        return [_chunk(path, layout_stem, "function", text, layout_rels)]

    return [_chunk(path, path.stem, "file", text, ())]


class SalesforceMetadataParser:
    """Parser for the five Salesforce metadata suffixes in the spec allowlist."""

    async def can_parse(self, path: str) -> bool:
        name = Path(path).name.lower()
        return any(name.endswith(suffix) for suffix in _SUFFIXES)

    async def parse(self, path: str, **kwargs: object) -> ParsedDocument:
        file_path = Path(path)
        try:
            size = file_path.stat().st_size
        except OSError:
            raise
        if size > _MAX_FILE_SIZE:
            logger.warning(
                "Skipping %s: size %s exceeds %s", file_path, size, _MAX_FILE_SIZE
            )
            return ParsedDocument(
                doc_id=str(file_path),
                file_path=str(file_path),
                chunks=[],
                metadata={
                    "language": "xml",
                    "parser": "salesforce_metadata",
                    "skipped": True,
                    "reason": "file_too_large",
                },
            )
        async with aiofiles.open(
            file_path, encoding="utf-8", errors="replace"
        ) as handle:
            text = await handle.read()
        loop = asyncio.get_running_loop()
        chunks = await loop.run_in_executor(None, _extract, file_path, text)
        return ParsedDocument(
            doc_id=str(file_path),
            file_path=str(file_path),
            chunks=chunks,
            metadata={"language": "xml", "parser": "salesforce_metadata"},
        )
