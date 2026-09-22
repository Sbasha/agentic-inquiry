"""Tests for :class:`LwcSalesforceRecognizer`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_vault.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from agent_vault.parsers.recognizers.lwc_salesforce import LwcSalesforceRecognizer

pytestmark = pytest.mark.unit


def _doc(path: Path) -> ParsedDocument:
    return ParsedDocument(
        doc_id=str(path),
        file_path=str(path),
        chunks=[
            ParserChunk(
                content="module",
                element_type="module",
                element_name=path.stem,
                symbols=[path.stem],
                relationships=[],
            )
        ],
        metadata={},
    )


def _invokes(doc: ParsedDocument) -> list[ParserRelationship]:
    return [
        rel
        for chunk in doc.chunks
        for rel in chunk.relationships
        if rel.type == "salesforce_invokes"
    ]


@pytest.fixture
def recognizer() -> LwcSalesforceRecognizer:
    return LwcSalesforceRecognizer()


@pytest.mark.asyncio
async def test_apex_import_invokes(
    recognizer: LwcSalesforceRecognizer, tmp_path: Path
) -> None:
    path = tmp_path / "accountCard.js"
    path.write_text("import find from '@salesforce/apex/AccountApi.find';\n")
    enriched = await recognizer.enrich(_doc(path))
    rels = _invokes(enriched)
    assert len(rels) == 1
    assert rels[0].target_name == "AccountApi.find"
    assert rels[0].source_name == "accountCard"


@pytest.mark.asyncio
async def test_plain_js_has_no_edges(
    recognizer: LwcSalesforceRecognizer, tmp_path: Path
) -> None:
    path = tmp_path / "util.js"
    path.write_text("export function add(a, b) { return a + b; }\n")
    enriched = await recognizer.enrich(_doc(path))
    assert _invokes(enriched) == []


@pytest.mark.asyncio
async def test_missing_file_returns_document(
    recognizer: LwcSalesforceRecognizer, tmp_path: Path
) -> None:
    path = tmp_path / "missing.js"
    result = await recognizer.enrich(_doc(path))
    assert result.file_path == str(path)
    assert _invokes(result) == []


@pytest.mark.asyncio
async def test_enrich_twice_is_idempotent(
    recognizer: LwcSalesforceRecognizer, tmp_path: Path
) -> None:
    path = tmp_path / "accountCard.js"
    path.write_text("import find from '@salesforce/apex/AccountApi.find';\n")
    once = await recognizer.enrich(_doc(path))
    twice = await recognizer.enrich(once)
    assert len(_invokes(twice)) == 1
