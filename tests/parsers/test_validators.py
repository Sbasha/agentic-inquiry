import pytest

pytestmark = pytest.mark.unit

from agent_vault.exceptions import ParsingError
from agent_vault.parsers import (
    ParserChunk,
    ParsedDocument,
    assert_valid_chunks,
    assert_valid_parsed_document,
    validate_chunks_have_text,
    validate_parsed_document,
)


def test_validate_chunks_have_text_flags_empty_chunks():
    chunks = [
        ParserChunk(content="ok"),
        ParserChunk(content=None),
    ]

    issues = validate_chunks_have_text(chunks)
    assert len(issues) == 1
    assert issues[0].index == 1


def test_validate_parsed_document_enriches_context():
    doc = ParsedDocument(
        doc_id="doc-1",
        file_path="file.py",
        chunks=[ParserChunk(content=None)],
    )

    issues = validate_parsed_document(doc)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.doc_id == "doc-1"
    assert issue.file_path == "file.py"


def test_assert_valid_chunks_raises_on_error():
    chunks = [ParserChunk(content=None)]

    with pytest.raises(ParsingError):
        assert_valid_chunks(chunks)


def test_assert_valid_parsed_document_raises_on_error():
    doc = ParsedDocument(doc_id="doc", file_path="file.py", chunks=[ParserChunk(content=None)])

    with pytest.raises(ParsingError):
        assert_valid_parsed_document(doc)
