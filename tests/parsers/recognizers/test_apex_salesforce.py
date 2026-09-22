"""Tests for :class:`ApexSalesforceRecognizer`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from agentic_inquiry.parsers.recognizers.apex_salesforce import ApexSalesforceRecognizer

pytestmark = pytest.mark.unit

_TRIGGER = """\
trigger AccountTrigger on Account (before insert, after update) {
    AccountApi.find();
}
"""

_API = """\
@RestResource(urlMapping='/accounts/*')
global with sharing class AccountApi {
    @HttpGet
    global static Account getOne() {
        return [SELECT Id FROM Account LIMIT 1];
    }

    @AuraEnabled(cacheable=true)
    public static List<Account> find() {
        return [SELECT Id FROM Account WHERE Name = :n];
    }
}
"""

_PLAIN = """\
public class PlainHelper {
    public static Integer add(Integer a, Integer b) {
        return a + b;
    }
}
"""


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source)
    return path


def _doc(path: Path, names: list[tuple[str, str]]) -> ParsedDocument:
    chunks = [
        ParserChunk(
            content=name,
            element_type=elem_type,
            element_name=name,
            symbols=[name],
            relationships=[],
        )
        for elem_type, name in names
    ]
    return ParsedDocument(
        doc_id=str(path), file_path=str(path), chunks=chunks, metadata={}
    )


def _rels(doc: ParsedDocument, rel_type: str) -> list[ParserRelationship]:
    found: list[ParserRelationship] = []
    for chunk in doc.chunks:
        for rel in chunk.relationships:
            if rel.type == rel_type:
                found.append(rel)
    return found


@pytest.fixture
def recognizer() -> ApexSalesforceRecognizer:
    return ApexSalesforceRecognizer()


@pytest.mark.asyncio
async def test_trigger_observes_account(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    path = _write(tmp_path, "AccountTrigger.trigger", _TRIGGER)
    doc = _doc(path, [("class", "AccountTrigger")])
    enriched = await recognizer.enrich(doc)
    rels = _rels(enriched, "salesforce_observes")
    assert len(rels) == 1
    assert rels[0].target_name == "Account"
    assert rels[0].metadata["events"] == "before insert,after update"


@pytest.mark.asyncio
async def test_trigger_keyword_is_case_insensitive(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    source = """\
Trigger AccountTrigger on Account (before insert) {
    AccountApi.find();
}
"""
    path = _write(tmp_path, "AccountTrigger.trigger", source)
    doc = _doc(path, [("class", "AccountTrigger")])
    enriched = await recognizer.enrich(doc)
    rels = _rels(enriched, "salesforce_observes")
    assert len(rels) == 1
    assert rels[0].target_name == "Account"


@pytest.mark.asyncio
async def test_multiline_soql_queries_account(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    source = """\
public class AccountApi {
    public static List<Account> find() {
        return [
            SELECT Id FROM Account
        ];
    }
}
"""
    path = _write(tmp_path, "AccountApi.cls", source)
    doc = _doc(path, [("class", "AccountApi"), ("method", "find")])
    enriched = await recognizer.enrich(doc)
    targets = {
        (rel.source_name, rel.target_name)
        for rel in _rels(enriched, "salesforce_queries")
    }
    assert ("find", "Account") in targets


@pytest.mark.asyncio
async def test_soql_queries_account(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    path = _write(tmp_path, "AccountApi.cls", _API)
    doc = _doc(
        path, [("class", "AccountApi"), ("method", "getOne"), ("method", "find")]
    )
    enriched = await recognizer.enrich(doc)
    targets = {
        (rel.source_name, rel.target_name)
        for rel in _rels(enriched, "salesforce_queries")
    }
    assert ("getOne", "Account") in targets
    assert ("find", "Account") in targets


@pytest.mark.asyncio
async def test_rest_and_aura_routes(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    path = _write(tmp_path, "AccountApi.cls", _API)
    doc = _doc(
        path, [("class", "AccountApi"), ("method", "getOne"), ("method", "find")]
    )
    enriched = await recognizer.enrich(doc)
    routes = _rels(enriched, "salesforce_route")
    by_source = {rel.source_name: rel for rel in routes}
    assert by_source["getOne"].metadata["http_method"] == "GET"
    assert by_source["getOne"].metadata["path"] == "/accounts/*"
    assert by_source["find"].metadata["aura_enabled"] is True


@pytest.mark.asyncio
async def test_plain_apex_has_no_salesforce_edges(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    path = _write(tmp_path, "PlainHelper.cls", _PLAIN)
    doc = _doc(path, [("class", "PlainHelper"), ("method", "add")])
    enriched = await recognizer.enrich(doc)
    all_types = {rel.type for chunk in enriched.chunks for rel in chunk.relationships}
    assert not any(t.startswith("salesforce_") for t in all_types)


@pytest.mark.asyncio
async def test_java_file_is_not_claimed(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    path = _write(tmp_path, "Foo.java", "class Foo { void bar() {} }")
    doc = _doc(path, [("class", "Foo")])
    # Dispatch would skip .java; enrich still no-ops without Apex markers.
    enriched = await recognizer.enrich(doc)
    assert _rels(enriched, "salesforce_observes") == []
    assert _rels(enriched, "salesforce_queries") == []
    assert _rels(enriched, "salesforce_route") == []


@pytest.mark.asyncio
async def test_enrich_twice_is_idempotent(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    path = _write(tmp_path, "AccountTrigger.trigger", _TRIGGER)
    doc = _doc(path, [("class", "AccountTrigger")])
    once = await recognizer.enrich(doc)
    twice = await recognizer.enrich(once)
    assert len(_rels(twice, "salesforce_observes")) == 1


@pytest.mark.asyncio
async def test_missing_file_returns_document(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    path = tmp_path / "missing.trigger"
    doc = _doc(path, [("class", "Missing")])
    result = await recognizer.enrich(doc)
    assert result is doc


@pytest.mark.asyncio
async def test_malformed_source_does_not_raise(
    recognizer: ApexSalesforceRecognizer, tmp_path: Path
) -> None:
    path = _write(tmp_path, "Broken.trigger", "trigger { SELECT FROM @HttpGet")
    doc = _doc(path, [("class", "Broken")])
    result = await recognizer.enrich(doc)
    assert result is doc or result.file_path == str(path)
