"""Salesforce LWC recognizer.

Finds ``@salesforce/apex/Class.method`` imports in Lightning Web
Component JavaScript and emits ``salesforce_invokes`` edges so impact
analysis can walk from the LWC file to the Apex method.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import FrozenSet

from agent_vault.parsers.models import (
    ParsedDocument,
    ParserChunk,
    ParserRelationship,
)

logger = logging.getLogger(__name__)

# import getFoo from '@salesforce/apex/AccountApi.find'
_APEX_IMPORT = re.compile(r"@salesforce/apex/([A-Za-z][\w]*(?:\.[A-Za-z][\w]*)+)")


def _rel_key(rel: ParserRelationship) -> tuple[str, str, str]:
    return (rel.type, rel.source_name, rel.target_name)


class LwcSalesforceRecognizer:
    """Recognizer that adds LWC-to-Apex invoke edges."""

    name = "lwc_salesforce"
    file_extensions: FrozenSet[str] = frozenset({".js"})

    async def enrich(self, parsed: ParsedDocument) -> ParsedDocument:
        try:
            source = Path(parsed.file_path).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError as exc:
            logger.debug(
                "LwcSalesforceRecognizer: could not read %s: %s",
                parsed.file_path,
                exc,
            )
            return parsed

        if "@salesforce/apex/" not in source:
            return parsed

        targets = _APEX_IMPORT.findall(source)
        if not targets:
            return parsed

        source_name = Path(parsed.file_path).stem
        if not parsed.chunks:
            return parsed

        # Prefer a chunk that already names this module; otherwise the first.
        target_chunk: ParserChunk = parsed.chunks[0]
        for chunk in parsed.chunks:
            if chunk.element_name == source_name or source_name in (
                chunk.symbols or []
            ):
                target_chunk = chunk
                break

        existing = {_rel_key(rel) for rel in target_chunk.relationships}
        for apex_ref in targets:
            edge = ParserRelationship(
                source_type="module",
                source_name=source_name,
                target_type="method",
                target_name=apex_ref,
                type="salesforce_invokes",
                metadata={},
            )
            key = _rel_key(edge)
            if key not in existing:
                target_chunk.relationships.append(edge)
                existing.add(key)

        return parsed
