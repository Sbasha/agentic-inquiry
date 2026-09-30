"""What each chunk embeds and full-text indexes (docs/specs/retrieval-core AC6)."""

from __future__ import annotations

from types import SimpleNamespace

from agentic_inquiry.indexing.document_processor import DocumentProcessor


def chunk(content: str, content_type: str, scope: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        fts_text="",
        symbols=[],
        content_type=content_type,
        metadata={"scope": scope} if scope else {},
    )


def test_code_chunk_carries_path_scope_and_split_identifiers() -> None:
    processor = DocumentProcessor(project_hash="h", project_id="p")
    embed, fts = processor.index_texts(
        chunk("def parseHeader(self):\n    pass", "CODE", "class FitsReader"),
        "io/fits.py",
    )
    assert embed == "io/fits.py\nclass FitsReader\ndef parseHeader(self):\n    pass"
    assert fts == f"{embed}\nparse header"


def test_text_chunk_has_path_header_and_no_identifier_split() -> None:
    processor = DocumentProcessor(project_hash="h", project_id="p")
    embed, fts = processor.index_texts(
        chunk("Install with pipInstall.", "TEXT"), "docs/setup.md"
    )
    assert embed == fts == "docs/setup.md\nInstall with pipInstall."


def test_empty_chunk_is_not_indexed() -> None:
    processor = DocumentProcessor(project_hash="h", project_id="p")
    assert processor.index_texts(chunk("  \n", "TEXT"), "a.txt") is None
