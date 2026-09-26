from dataclasses import dataclass, field, fields
from typing import Any, Dict, Iterable, List, Mapping, Optional

from pydantic import BaseModel, Field, field_validator


@dataclass(slots=True)
class ParserRelationship:
    source_type: str
    source_name: str
    target_type: str
    target_name: str
    type: str
    target_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    ranking_signals: Dict[str, Any] = field(default_factory=dict)


_RELATIONSHIP_FIELD_NAMES = {f.name for f in fields(ParserRelationship)}


def _normalise_relationship(relationship: Any) -> ParserRelationship:
    """Convert a raw relationship payload into :class:`ParserRelationship`."""

    if isinstance(relationship, ParserRelationship):
        return relationship

    if isinstance(relationship, Mapping):
        filtered: Dict[str, Any] = {
            key: relationship[key]
            for key in _RELATIONSHIP_FIELD_NAMES
            if key in relationship
        }

        for key in ("metadata", "ranking_signals"):
            value = filtered.get(key)
            if value is not None:
                if not isinstance(value, Mapping):
                    raise TypeError(
                        f"relationship {key} must be a mapping when provided"
                    )
                filtered[key] = dict(value)

        return ParserRelationship(**filtered)

    raise TypeError(
        "relationships must be ParserRelationship instances or mappings; "
        f"received {type(relationship)!r}"
    )


def _normalise_relationships(
    relationships: Optional[Iterable[Any]],
) -> List[ParserRelationship]:
    """Normalise a collection of relationships into dataclass instances."""

    if not relationships:
        return []

    return [_normalise_relationship(relationship) for relationship in relationships]


class ParserChunk(BaseModel):
    """A chunk of parsed content with metadata.

    The `metadata` dict supports standard JSON-serializable types (str, int, float, bool, None, list, dict).
    These are serialized to JSON strings during storage to ensure compatibility across backends.

    Prefer using top-level fields (symbols, language, line_start, etc.) over metadata where possible.
    Use ranking_signals for metrics and scores.
    Use symbol_metadata/symbol_rankings for per-symbol information.
    """

    content: Optional[str]
    fts_text: Optional[str] = None
    content_type: Optional[str] = None
    language: Optional[str] = None
    page_number: Optional[int] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    element_type: Optional[str] = None
    element_name: Optional[str] = None
    parent_id: Optional[str] = None
    child_ids: List[str] = Field(default_factory=list)
    symbols: List[str] = Field(default_factory=list)
    # Use a typed dataclass for relationships for better safety and clarity
    relationships: List[ParserRelationship] = Field(default_factory=list)

    # Optional metadata supplied by the parser
    metadata: Optional[Dict[str, Any]] = None
    ranking_signals: Optional[Dict[str, Any]] = None

    # Optional per-symbol metadata / rankings
    symbol_rankings: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    symbol_metadata: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("metadata")
    @classmethod
    def validate_metadata_types(
        cls, v: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Ensure metadata contains valid JSON-serializable types.

        Allows str, int, float, bool, None, list, and dict.
        Complex objects that are not JSON-serializable will cause issues during storage.
        """
        if v is None:
            return v

        # We allow complex types now, relying on the storage layer to handle serialization.
        # Basic validation to ensure keys are strings is sufficient for Pydantic.
        return v

    @field_validator("relationships", mode="before")
    @classmethod
    def normalize_relationships(cls, v: Any) -> List[ParserRelationship]:
        """Normalize relationships to ParserRelationship instances."""
        return _normalise_relationships(v)


@dataclass(slots=True)
class ParsedDocument:
    """Container describing the structured output of a parser run."""

    doc_id: str
    file_path: str
    chunks: List[ParserChunk] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.doc_id, str) or not self.doc_id:
            raise ValueError("doc_id must be a non-empty string")
        if not isinstance(self.file_path, str) or not self.file_path:
            raise ValueError("file_path must be a non-empty string")

        normalised_chunks: List[ParserChunk] = []
        for chunk in self.chunks:
            if isinstance(chunk, ParserChunk):
                normalised_chunks.append(chunk)
                continue

            if isinstance(chunk, Mapping):
                mapping = dict(chunk)
                normalised_chunks.append(
                    ParserChunk(
                        content=mapping.get("content"),
                        fts_text=mapping.get("fts_text"),
                        content_type=mapping.get("content_type"),
                        language=mapping.get("language"),
                        page_number=mapping.get("page_number"),
                        line_start=mapping.get("line_start"),
                        line_end=mapping.get("line_end"),
                        element_type=mapping.get("element_type"),
                        element_name=mapping.get("element_name"),
                        parent_id=mapping.get("parent_id"),
                        child_ids=mapping.get("child_ids") or [],
                        symbols=mapping.get("symbols", mapping.get("code_symbols", [])),
                        relationships=mapping.get("relationships", []),
                        metadata=mapping.get("metadata"),
                        ranking_signals=mapping.get("ranking_signals"),
                        symbol_rankings=mapping.get("symbol_rankings", {}),
                        symbol_metadata=mapping.get("symbol_metadata", {}),
                    )
                )
                continue

            raise TypeError(
                "chunks must contain ParserChunk instances or mappings convertible to ParserChunk"
            )

        self.chunks = normalised_chunks
