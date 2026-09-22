"""Chain-level Salesforce recognizer coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_vault.config import Config
from agent_vault.parsers.chain import ParserChain
from agent_vault.parsers.models import ParserRelationship

pytestmark = pytest.mark.integration

_TRIGGER = """\
trigger AccountTrigger on Account (before insert, after update) {
    AccountApi.find();
}
"""

_CLS = """\
public with sharing class AccountApi {
    public static List<Account> find() {
        return [SELECT Id FROM Account];
    }
}
"""


def _rels(doc, rel_type: str) -> list[ParserRelationship]:
    return [
        rel
        for chunk in doc.chunks
        for rel in chunk.relationships
        if rel.type == rel_type
    ]


@pytest.fixture
def chain() -> ParserChain:
    return ParserChain(parser_names=["unified_code"], config=Config())


@pytest.mark.asyncio
async def test_chain_trigger_observes(chain: ParserChain, tmp_path: Path) -> None:
    path = tmp_path / "AccountTrigger.trigger"
    path.write_text(_TRIGGER)
    doc = await chain.parse(str(path))
    rels = _rels(doc, "salesforce_observes")
    assert rels
    assert rels[0].target_name == "Account"


@pytest.mark.asyncio
async def test_chain_cls_queries(chain: ParserChain, tmp_path: Path) -> None:
    path = tmp_path / "AccountApi.cls"
    path.write_text(_CLS)
    doc = await chain.parse(str(path))
    targets = {rel.target_name for rel in _rels(doc, "salesforce_queries")}
    assert "Account" in targets


@pytest.mark.asyncio
async def test_chain_lwc_invokes(chain: ParserChain, tmp_path: Path) -> None:
    path = tmp_path / "accountCard.js"
    path.write_text("import find from '@salesforce/apex/AccountApi.find';\n")
    doc = await chain.parse(str(path))
    rels = _rels(doc, "salesforce_invokes")
    assert rels
    assert rels[0].target_name == "AccountApi.find"
