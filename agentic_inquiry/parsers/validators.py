"""Utilities for validating parser output prior to ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from agentic_inquiry.exceptions import ParsingError
from .models import ParsedDocument, ParserChunk


@dataclass(slots=True)
class ChunkValidationIssue:
    """Represents an issue discovered while validating parser chunks."""

    index: int
    message: str
    chunk: ParserChunk
    doc_id: Optional[str] = None
    file_path: Optional[str] = None


def _has_text_payload(chunk: ParserChunk) -> bool:
    """Return ``True`` when a chunk provides at least one textual payload."""

    candidates = (chunk.content, chunk.fts_text)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return True
    return False


def validate_chunks_have_text(
    chunks: Iterable[ParserChunk],
) -> List[ChunkValidationIssue]:
    """Validate that each chunk exposes textual content for embedding."""

    issues: List[ChunkValidationIssue] = []
    for index, chunk in enumerate(chunks):
        if _has_text_payload(chunk):
            continue
        issues.append(
            ChunkValidationIssue(
                index=index,
                message="Chunk is missing content or fts_text",
                chunk=chunk,
            )
        )
    return issues


def validate_parsed_document(
    parsed_document: ParsedDocument,
) -> List[ChunkValidationIssue]:
    """Run all validation checks against a :class:`ParsedDocument`."""

    issues = validate_chunks_have_text(parsed_document.chunks)
    for issue in issues:
        issue.doc_id = parsed_document.doc_id
        issue.file_path = parsed_document.file_path
    return issues


def assert_valid_chunks(chunks: Iterable[ParserChunk]) -> None:
    """Raise a :class:`ParsingError` when chunks fail validation."""

    issues = validate_chunks_have_text(chunks)
    if not issues:
        return
    details = ", ".join(f"index={issue.index}" for issue in issues)
    raise ParsingError(f"Invalid parser chunks detected ({details})")


def assert_valid_parsed_document(parsed_document: ParsedDocument) -> None:
    """Validate a :class:`ParsedDocument` and raise on failure."""

    issues = validate_parsed_document(parsed_document)
    if not issues:
        return
    context = f"doc_id={parsed_document.doc_id}, file_path={parsed_document.file_path}"
    details = ", ".join(f"chunk_index={issue.index}" for issue in issues)
    raise ParsingError(f"Invalid parsed document ({context}; {details})")
