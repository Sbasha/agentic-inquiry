"""Data model representing an indexed document chunk."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional


_ALLOWED_CONTENT_TYPES = {
    "CODE",
    "PROSE",
    "TABLE",
    "HEADING",
    "LIST_ITEM",
    "IMAGE_CAPTION",
    "TITLE",
    "OTHER",
}

# Fields added for branch-scoped indexing that must be stripped before LanceDB schema validation.
BRANCH_INDEXING_FIELDS: frozenset[str] = frozenset(
    {"branch", "is_active", "expired_at"}
)


@dataclass(slots=True)
class DocumentChunk:
    """Represents the atomic unit of searchable content."""

    id: str
    doc_id: str
    file_path: str
    project_id: str

    content: str
    fts_text: str
    vector: List[float]

    content_type: Literal[
        "CODE",
        "PROSE",
        "TABLE",
        "HEADING",
        "LIST_ITEM",
        "IMAGE_CAPTION",
        "TITLE",
        "OTHER",
    ] = "PROSE"
    language: str = ""  # Empty string as sentinel instead of None

    page_number: int = -1  # -1 as sentinel instead of None
    line_start: int = -1  # -1 as sentinel instead of None
    line_end: int = -1  # -1 as sentinel instead of None
    chunk_index: int = 0
    total_chunks: int = 1
    element_type: str = ""  # Empty string as sentinel instead of None
    element_name: str = ""  # Empty string as sentinel instead of None

    parent_id: str = ""  # Empty string as sentinel instead of None
    child_ids: List[str] = field(default_factory=list)

    # Symbols extracted from this chunk (functions, classes, headings, entities, etc.)
    symbols: List[str] = field(default_factory=list)

    indexed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_modified_at: datetime = datetime.fromtimestamp(
        0, tz=timezone.utc
    )  # Epoch as sentinel

    # Branch indexing (WS4)
    branch: str = "main"
    is_active: bool = True
    expired_at: Optional[datetime] = None

    metadata: Dict[str, Any] = field(default_factory=dict)
    ranking_signals: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr_name in ("id", "doc_id", "file_path", "project_id"):
            value = getattr(self, attr_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{attr_name} must be a non-empty string")

        if not isinstance(self.content, str):
            raise ValueError("content must be a string")
        if not isinstance(self.fts_text, str):
            raise ValueError("fts_text must be a string")

        if not isinstance(self.vector, list) or not all(
            isinstance(v, (int, float)) for v in self.vector
        ):
            raise ValueError("vector must be a list of numbers")

        if self.content_type not in _ALLOWED_CONTENT_TYPES:
            allowed = ", ".join(sorted(_ALLOWED_CONTENT_TYPES))
            raise ValueError(f"content_type must be one of {allowed}")

        for attr_name in ("page_number", "line_start", "line_end"):
            value = getattr(self, attr_name)
            if not isinstance(value, int):
                raise ValueError(f"{attr_name} must be an integer")
            # Allow -1 as sentinel value for "not applicable"

        if not isinstance(self.chunk_index, int) or self.chunk_index < 0:
            raise ValueError("chunk_index must be a non-negative integer")
        if not isinstance(self.total_chunks, int) or self.total_chunks < 1:
            raise ValueError("total_chunks must be a positive integer")

        if self.child_ids is None:
            self.child_ids = []
        elif not isinstance(self.child_ids, list) or not all(
            isinstance(child, str) for child in self.child_ids
        ):
            raise ValueError("child_ids must be a list of strings")

        if self.symbols is None:
            self.symbols = []
        elif not isinstance(self.symbols, list) or not all(
            isinstance(sym, str) for sym in self.symbols
        ):
            raise ValueError("symbols must be a list of strings")

        for attr_name in ("indexed_at", "source_modified_at"):
            value = getattr(self, attr_name)
            if not isinstance(value, datetime):
                raise ValueError(f"{attr_name} must be a datetime")
            # Epoch (1970-01-01) is used as sentinel for "unknown" source_modified_at

        for attr_name in ("metadata", "ranking_signals"):
            if not isinstance(getattr(self, attr_name), dict):
                raise ValueError(f"{attr_name} must be a dictionary")

    @classmethod
    def get_source_column(cls, vector_column_name: str) -> str:
        """Return the default text column used for embedding generation."""
        return "fts_text"

    def to_dict(self) -> dict:
        """Serialise the dataclass to a plain dictionary."""
        data = asdict(self)
        for key in ("indexed_at", "source_modified_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data
