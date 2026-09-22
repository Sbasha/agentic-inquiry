"""Apex extraction depth: classes, triggers, calls, inheritance, SOQL text.

See docs/specs/salesforce-apex-parsing/spec.md.
"""

from __future__ import annotations

from typing import List

import pytest

from agentic_inquiry.parsers.implementations.unified_code import UnifiedCodeParser
from agentic_inquiry.parsers.models import ParserRelationship

pytestmark = pytest.mark.integration

_ACCOUNT_SERVICE_CLS = """\
public with sharing class AccountService extends BaseService implements Schedulable {
    public enum Status { Open, Closed }

    public AccountService() {}

    public String Name { get; set; }
    public Integer count;

    public class Metrics {
        public Decimal baseline;
    }

    public static List<Account> find() {
        return [SELECT Id FROM Account WHERE Name = :name];
    }

    public void ping() {
        find();
        Math.abs(1);
    }
}
"""

_ACCOUNT_TRIGGER = """\
trigger AccountTrigger on Account (before insert, after update) {
    AccountService.find();
}
"""


@pytest.fixture
def parser() -> UnifiedCodeParser:
    return UnifiedCodeParser()


def _all_symbols(result) -> List[str]:
    names: List[str] = []
    for chunk in result.chunks:
        names.extend(chunk.symbols or [])
        if chunk.element_name:
            names.append(chunk.element_name)
    return names


def _rels(result, rel_type: str) -> List[ParserRelationship]:
    found: List[ParserRelationship] = []
    for chunk in result.chunks:
        for rel in chunk.relationships:
            if rel.type == rel_type:
                found.append(rel)
    return found


@pytest.mark.asyncio
async def test_cls_extracts_class_members(parser: UnifiedCodeParser, tmp_path) -> None:
    path = tmp_path / "AccountService.cls"
    path.write_text(_ACCOUNT_SERVICE_CLS)
    result = await parser.parse(str(path))
    symbols = _all_symbols(result)

    for name in (
        "AccountService",
        "Metrics",
        "find",
        "ping",
        "Name",
        "count",
        "Status",
    ):
        assert name in symbols, symbols

    joined = "\n".join(chunk.content for chunk in result.chunks)
    assert "public AccountService()" in joined


@pytest.mark.asyncio
async def test_trigger_extracts_trigger_name(
    parser: UnifiedCodeParser, tmp_path
) -> None:
    path = tmp_path / "AccountTrigger.trigger"
    path.write_text(_ACCOUNT_TRIGGER)
    result = await parser.parse(str(path))
    symbols = _all_symbols(result)
    assert "AccountTrigger" in symbols, symbols


@pytest.mark.asyncio
async def test_apex_inherits_superclass_and_interfaces(
    parser: UnifiedCodeParser, tmp_path
) -> None:
    path = tmp_path / "AccountService.cls"
    path.write_text(_ACCOUNT_SERVICE_CLS)
    result = await parser.parse(str(path))
    targets = [rel.target_name for rel in _rels(result, "inherits")]
    assert "BaseService" in targets, targets
    assert "Schedulable" in targets, targets


@pytest.mark.asyncio
async def test_apex_calls_attributed_to_method(
    parser: UnifiedCodeParser, tmp_path
) -> None:
    path = tmp_path / "AccountService.cls"
    path.write_text(_ACCOUNT_SERVICE_CLS)
    result = await parser.parse(str(path))
    calls = _rels(result, "calls")
    by_target = {rel.target_name: rel for rel in calls}
    assert "find" in by_target, [rel.target_name for rel in calls]
    assert "abs" in by_target, [rel.target_name for rel in calls]
    assert by_target["find"].source_name == "ping"
    assert by_target["abs"].source_name == "ping"


@pytest.mark.asyncio
async def test_soql_text_stays_in_method_chunk(
    parser: UnifiedCodeParser, tmp_path
) -> None:
    path = tmp_path / "AccountService.cls"
    path.write_text(_ACCOUNT_SERVICE_CLS)
    result = await parser.parse(str(path))
    find_chunks = [
        chunk
        for chunk in result.chunks
        if "find" in (chunk.symbols or []) or chunk.element_name == "find"
    ]
    assert find_chunks, [chunk.element_name for chunk in result.chunks]
    joined = "\n".join(chunk.content for chunk in find_chunks)
    assert "[SELECT Id FROM Account WHERE Name = :name]" in joined


@pytest.mark.asyncio
async def test_apex_enum_extracted(parser: UnifiedCodeParser, tmp_path) -> None:
    path = tmp_path / "AccountService.cls"
    path.write_text(_ACCOUNT_SERVICE_CLS)
    result = await parser.parse(str(path))
    assert "Status" in _all_symbols(result)


@pytest.mark.asyncio
async def test_apex_interface_extracted(parser: UnifiedCodeParser, tmp_path) -> None:
    path = tmp_path / "TokenProvider.cls"
    path.write_text("public interface TokenProvider {\n    String getToken();\n}\n")
    result = await parser.parse(str(path))
    assert "TokenProvider" in _all_symbols(result)


@pytest.mark.asyncio
async def test_trigger_calls_attributed_to_trigger(
    parser: UnifiedCodeParser, tmp_path
) -> None:
    path = tmp_path / "AccountTrigger.trigger"
    path.write_text(_ACCOUNT_TRIGGER)
    result = await parser.parse(str(path))
    calls = _rels(result, "calls")
    by_target = {rel.target_name: rel for rel in calls}
    assert "find" in by_target, [rel.target_name for rel in calls]
    assert by_target["find"].source_name == "AccountTrigger"
