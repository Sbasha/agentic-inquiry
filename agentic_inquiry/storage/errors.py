"""Shared storage error types used across backends.

Centralizing these classes lets LanceDB, PostgreSQL, and future backends
(OpenSearch, Neptune) raise the same exception shape for cross-cutting
concerns like dimension/schema mismatches — callers (CLI, migration tooling,
integration tests) only need to catch one type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class SchemaMismatchError(Exception):
    """Raised when configured schema doesn't match existing persisted schema.

    Most commonly used for embedding-dimension mismatches detected at backend
    initialization, where the configured ``embedding_dim`` differs from the
    dimension baked into an already-created vector column/index.
    """


@dataclass
class DimensionMismatch:
    """Details of an embedding-dimension mismatch.

    Attributes:
        backend: Backend identifier (e.g. ``"postgresql"``, ``"lancedb"``).
        table_name: Name of the persisted table/index with the mismatch.
        configured: Dimension from the current ``BackendConfig`` / ``Config``.
        actual: Dimension read from the persisted schema.
        column: Vector column whose dim was inspected.
        remediation: Optional backend-specific remediation hint appended to
            the rendered error. Keeps the shared message generic while still
            letting callers surface actionable, backend-specific guidance
            (e.g. an exact CLI command).
    """

    backend: str
    table_name: str
    configured: int
    actual: int
    column: str = "embedding"
    remediation: Optional[str] = None

    def __str__(self) -> str:
        lines = [
            "Embedding dimension mismatch detected.",
            f"  Backend: {self.backend}",
            f"  Table: {self.table_name}",
            f"  Column: {self.column}",
            f"  Configured: {self.configured} dimensions",
            f"  Actual: {self.actual} dimensions",
            "",
            "Embedding dimensions are fixed at table creation and cannot be",
            "changed in place. The table must be dropped and re-indexed.",
        ]
        if self.remediation:
            lines += ["", self.remediation]
        return "\n".join(lines)


__all__ = ["SchemaMismatchError", "DimensionMismatch"]
