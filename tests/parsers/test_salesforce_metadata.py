"""Tests for the Salesforce metadata allowlist parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_vault.config import Config, ParsersConfig
from agent_vault.parsers.chain import ParserChain
from agent_vault.parsers.executor import available_parsers
from agent_vault.parsers.implementations.salesforce_metadata import (
    SalesforceMetadataParser,
)
from agent_vault.parsers.models import ParserRelationship

pytestmark = pytest.mark.unit

_FLOW = """\
<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>Update_Account</fullName>
    <actionCalls>
        <actionName>AccountService</actionName>
        <actionType>apex</actionType>
    </actionCalls>
    <recordLookups>
        <object>Account</object>
    </recordLookups>
</Flow>
"""

_FIELD = """\
<?xml version="1.0" encoding="UTF-8"?>
<CustomField>
    <fullName>Status__c</fullName>
    <type>Text</type>
</CustomField>
"""

_LAYOUT = """\
<?xml version="1.0" encoding="UTF-8"?>
<Layout>
    <layoutSections>
        <layoutColumns>
            <layoutItems>
                <field>Name</field>
            </layoutItems>
        </layoutColumns>
    </layoutSections>
</Layout>
"""

_FLEXIPAGE = """\
<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage>
    <sobjectType>Account</sobjectType>
</FlexiPage>
"""

_OBJECT = """\
<?xml version="1.0" encoding="UTF-8"?>
<CustomObject>
    <label>Account</label>
</CustomObject>
"""


def _rels(result, rel_type: str) -> list[ParserRelationship]:
    return [
        rel
        for chunk in result.chunks
        for rel in chunk.relationships
        if rel.type == rel_type
    ]


@pytest.fixture
def parser() -> SalesforceMetadataParser:
    return SalesforceMetadataParser()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Account.object-meta.xml", True),
        ("Status__c.field-meta.xml", True),
        ("Update_Account.flow-meta.xml", True),
        ("Account_Record_Page.flexipage-meta.xml", True),
        ("Account-Account Layout.layout-meta.xml", True),
        ("pom.xml", False),
        ("Account.cls-meta.xml", False),
    ],
)
async def test_can_parse_suffixes(
    parser: SalesforceMetadataParser, name: str, expected: bool
) -> None:
    assert await parser.can_parse(name) is expected


@pytest.mark.asyncio
async def test_field_edge(parser: SalesforceMetadataParser, tmp_path: Path) -> None:
    path = tmp_path / "objects" / "Account" / "fields" / "Status__c.field-meta.xml"
    path.parent.mkdir(parents=True)
    path.write_text(_FIELD)
    result = await parser.parse(str(path))
    rels = _rels(result, "salesforce_field")
    assert len(rels) == 1
    assert rels[0].source_name == "Account"
    assert rels[0].target_name == "Status__c"


@pytest.mark.asyncio
async def test_flow_edges(parser: SalesforceMetadataParser, tmp_path: Path) -> None:
    path = tmp_path / "Update_Account.flow-meta.xml"
    path.write_text(_FLOW)
    result = await parser.parse(str(path))
    touches = {rel.target_name for rel in _rels(result, "salesforce_touches")}
    invokes = {rel.target_name for rel in _rels(result, "salesforce_invokes")}
    assert "Account" in touches
    assert "AccountService" in invokes


@pytest.mark.asyncio
async def test_layout_touches_object(
    parser: SalesforceMetadataParser, tmp_path: Path
) -> None:
    path = tmp_path / "Account-Account Layout.layout-meta.xml"
    path.write_text(_LAYOUT)
    result = await parser.parse(str(path))
    targets = {rel.target_name for rel in _rels(result, "salesforce_touches")}
    assert "Account" in targets
    assert "Name" in targets


@pytest.mark.asyncio
async def test_flexipage_touches_object(
    parser: SalesforceMetadataParser, tmp_path: Path
) -> None:
    path = tmp_path / "Account_Record_Page.flexipage-meta.xml"
    path.write_text(_FLEXIPAGE)
    result = await parser.parse(str(path))
    targets = {rel.target_name for rel in _rels(result, "salesforce_touches")}
    assert "Account" in targets


@pytest.mark.asyncio
async def test_object_chunk(parser: SalesforceMetadataParser, tmp_path: Path) -> None:
    path = tmp_path / "Account.object-meta.xml"
    path.write_text(_OBJECT)
    result = await parser.parse(str(path))
    names = [chunk.element_name for chunk in result.chunks]
    assert "Account" in names


def test_config_default_priority() -> None:
    cfg = ParsersConfig()
    assert cfg.salesforce_metadata.enabled is True
    assert cfg.salesforce_metadata.priority == 75


def test_parser_is_registered() -> None:
    assert "salesforce_metadata" in available_parsers()


@pytest.mark.asyncio
async def test_malformed_xml_does_not_raise(
    parser: SalesforceMetadataParser, tmp_path: Path
) -> None:
    path = tmp_path / "Broken.flow-meta.xml"
    path.write_text("<Flow><unclosed")
    result = await parser.parse(str(path))
    assert result.metadata.get("parser") == "salesforce_metadata"
    assert result.chunks


@pytest.mark.asyncio
async def test_flow_namespaced_apex_invokes(
    parser: SalesforceMetadataParser, tmp_path: Path
) -> None:
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Flow>
    <fullName>Update_Account</fullName>
    <actionCalls>
        <actionName>ns.AccountService</actionName>
        <actionType>apex</actionType>
    </actionCalls>
</Flow>
"""
    path = tmp_path / "Update_Account.flow-meta.xml"
    path.write_text(xml)
    result = await parser.parse(str(path))
    invokes = {rel.target_name for rel in _rels(result, "salesforce_invokes")}
    assert "ns.AccountService" in invokes


@pytest.mark.asyncio
async def test_field_object_uses_fields_parent(
    parser: SalesforceMetadataParser, tmp_path: Path
) -> None:
    path = (
        tmp_path
        / "objects"
        / "my-app"
        / "force-app"
        / "main"
        / "default"
        / "objects"
        / "Account"
        / "fields"
        / "Status__c.field-meta.xml"
    )
    path.parent.mkdir(parents=True)
    path.write_text(_FIELD)
    result = await parser.parse(str(path))
    rels = _rels(result, "salesforce_field")
    assert len(rels) == 1
    assert rels[0].source_name == "Account"


@pytest.mark.asyncio
async def test_flow_without_apex_type_does_not_invoke(
    parser: SalesforceMetadataParser, tmp_path: Path
) -> None:
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Flow>
    <fullName>Update_Account</fullName>
    <actionCalls>
        <actionName>Update_Account</actionName>
        <actionType>flow</actionType>
    </actionCalls>
    <recordLookups>
        <object>Account</object>
    </recordLookups>
</Flow>
"""
    path = tmp_path / "Update_Account.flow-meta.xml"
    path.write_text(xml)
    result = await parser.parse(str(path))
    assert _rels(result, "salesforce_invokes") == []
    assert {rel.target_name for rel in _rels(result, "salesforce_touches")} == {
        "Account"
    }


@pytest.mark.asyncio
async def test_chain_claims_field_meta(tmp_path: Path) -> None:
    path = tmp_path / "objects" / "Account" / "fields" / "Status__c.field-meta.xml"
    path.parent.mkdir(parents=True)
    path.write_text(_FIELD)
    chain = ParserChain(config=Config())
    result = await chain.parse(str(path))
    assert result.metadata.get("parser") == "salesforce_metadata"
    rels = _rels(result, "salesforce_field")
    assert len(rels) == 1
    assert rels[0].source_name == "Account"
    assert rels[0].target_name == "Status__c"


@pytest.mark.asyncio
async def test_oversized_file_is_skipped(
    parser: SalesforceMetadataParser, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "Account.object-meta.xml"
    path.write_text(_OBJECT)
    monkeypatch.setattr(
        "agent_vault.parsers.implementations.salesforce_metadata._MAX_FILE_SIZE",
        1,
    )
    result = await parser.parse(str(path))
    assert result.chunks == []
    assert result.metadata.get("skipped") is True
    assert result.metadata.get("reason") == "file_too_large"
