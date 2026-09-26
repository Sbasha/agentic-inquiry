"""Data model representing an edge in the knowledge graph."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import List, Optional, Dict, Any, Union
import json


class RelationshipType(str, Enum):
    """Enumeration of all relationship types in the knowledge graph.

    Each relationship type represents a specific semantic connection between entities.
    Relationships are directional (source -> target) with defined inverse relationships.
    """

    # Code relationships
    CALLS = "calls"  # Function/method calls another function/method
    CALLED_BY = "called_by"  # Inverse of CALLS

    IMPORTS = "imports"  # Module imports another module/symbol
    IMPORTED_BY = "imported_by"  # Inverse of IMPORTS

    INHERITS = "inherits"  # Class inherits from another class
    INHERITED_BY = "inherited_by"  # Inverse of INHERITS

    IMPLEMENTS = "implements"  # Class implements an interface/protocol
    IMPLEMENTED_BY = "implemented_by"  # Inverse of IMPLEMENTS

    DEFINES = "defines"  # Module/class defines a symbol
    DEFINED_IN = "defined_in"  # Inverse of DEFINES

    REFERENCES = "references"  # Code references another symbol
    REFERENCED_BY = "referenced_by"  # Inverse of REFERENCES

    USES = "uses"  # General usage relationship
    USED_BY = "used_by"  # Inverse of USES

    CONTAINS = "contains"  # Container contains items (e.g., module contains classes)
    CONTAINED_IN = "contained_in"  # Inverse of CONTAINS

    OVERRIDES = "overrides"  # Method overrides parent method
    OVERRIDDEN_BY = "overridden_by"  # Inverse of OVERRIDES

    DECORATES = "decorates"  # Decorator decorates a function/class
    DECORATED_BY = "decorated_by"  # Inverse of DECORATES

    # Documentation relationships
    DOCUMENTS = "documents"  # Documentation describes code/concept
    DOCUMENTED_BY = "documented_by"  # Inverse of DOCUMENTS

    EXPLAINS = "explains"  # Documentation explains a concept
    EXPLAINED_BY = "explained_by"  # Inverse of EXPLAINS

    CROSS_REFERENCES = "cross_references"  # Document references another document
    CROSS_REFERENCED_BY = "cross_referenced_by"  # Inverse of CROSS_REFERENCES

    # Conceptual relationships
    RELATES_TO = "relates_to"  # General semantic relationship
    RELATED_BY = "related_by"  # Inverse of RELATES_TO

    SIMILAR_TO = "similar_to"  # Entities are semantically similar
    # Note: SIMILAR_TO is symmetric, so it's its own inverse

    DEPENDS_ON = "depends_on"  # Entity depends on another
    DEPENDENCY_OF = "dependency_of"  # Inverse of DEPENDS_ON

    # Memory relationships
    RECALLS = "recalls"  # Memory recalls/references an entity
    RECALLED_BY = "recalled_by"  # Inverse of RECALLS

    LEARNED_FROM = "learned_from"  # Memory learned from an entity
    TAUGHT = "taught"  # Inverse of LEARNED_FROM

    # Test relationships
    TESTS = "tests"  # Test tests a code entity
    TESTED_BY = "tested_by"  # Inverse of TESTS

    MOCKS = "mocks"  # Test mocks an entity
    MOCKED_BY = "mocked_by"  # Inverse of MOCKS

    # Temporal relationships
    PRECEDES = "precedes"  # Entity comes before another temporally
    FOLLOWS = "follows"  # Inverse of PRECEDES

    REPLACES = "replaces"  # Entity replaces/supersedes another
    REPLACED_BY = "replaced_by"  # Inverse of REPLACES

    # Generic fallback
    UNKNOWN = "unknown"  # Unknown relationship type


# Mapping of relationship types to their inverses
INVERSE_RELATIONSHIPS = {
    RelationshipType.CALLS: RelationshipType.CALLED_BY,
    RelationshipType.CALLED_BY: RelationshipType.CALLS,
    RelationshipType.IMPORTS: RelationshipType.IMPORTED_BY,
    RelationshipType.IMPORTED_BY: RelationshipType.IMPORTS,
    RelationshipType.INHERITS: RelationshipType.INHERITED_BY,
    RelationshipType.INHERITED_BY: RelationshipType.INHERITS,
    RelationshipType.IMPLEMENTS: RelationshipType.IMPLEMENTED_BY,
    RelationshipType.IMPLEMENTED_BY: RelationshipType.IMPLEMENTS,
    RelationshipType.DEFINES: RelationshipType.DEFINED_IN,
    RelationshipType.DEFINED_IN: RelationshipType.DEFINES,
    RelationshipType.REFERENCES: RelationshipType.REFERENCED_BY,
    RelationshipType.REFERENCED_BY: RelationshipType.REFERENCES,
    RelationshipType.USES: RelationshipType.USED_BY,
    RelationshipType.USED_BY: RelationshipType.USES,
    RelationshipType.CONTAINS: RelationshipType.CONTAINED_IN,
    RelationshipType.CONTAINED_IN: RelationshipType.CONTAINS,
    RelationshipType.OVERRIDES: RelationshipType.OVERRIDDEN_BY,
    RelationshipType.OVERRIDDEN_BY: RelationshipType.OVERRIDES,
    RelationshipType.DECORATES: RelationshipType.DECORATED_BY,
    RelationshipType.DECORATED_BY: RelationshipType.DECORATES,
    RelationshipType.DOCUMENTS: RelationshipType.DOCUMENTED_BY,
    RelationshipType.DOCUMENTED_BY: RelationshipType.DOCUMENTS,
    RelationshipType.EXPLAINS: RelationshipType.EXPLAINED_BY,
    RelationshipType.EXPLAINED_BY: RelationshipType.EXPLAINS,
    RelationshipType.CROSS_REFERENCES: RelationshipType.CROSS_REFERENCED_BY,
    RelationshipType.CROSS_REFERENCED_BY: RelationshipType.CROSS_REFERENCES,
    RelationshipType.RELATES_TO: RelationshipType.RELATED_BY,
    RelationshipType.RELATED_BY: RelationshipType.RELATES_TO,
    RelationshipType.SIMILAR_TO: RelationshipType.SIMILAR_TO,  # Symmetric
    RelationshipType.DEPENDS_ON: RelationshipType.DEPENDENCY_OF,
    RelationshipType.DEPENDENCY_OF: RelationshipType.DEPENDS_ON,
    RelationshipType.RECALLS: RelationshipType.RECALLED_BY,
    RelationshipType.RECALLED_BY: RelationshipType.RECALLS,
    RelationshipType.LEARNED_FROM: RelationshipType.TAUGHT,
    RelationshipType.TAUGHT: RelationshipType.LEARNED_FROM,
    RelationshipType.TESTS: RelationshipType.TESTED_BY,
    RelationshipType.TESTED_BY: RelationshipType.TESTS,
    RelationshipType.MOCKS: RelationshipType.MOCKED_BY,
    RelationshipType.MOCKED_BY: RelationshipType.MOCKS,
    RelationshipType.PRECEDES: RelationshipType.FOLLOWS,
    RelationshipType.FOLLOWS: RelationshipType.PRECEDES,
    RelationshipType.REPLACES: RelationshipType.REPLACED_BY,
    RelationshipType.REPLACED_BY: RelationshipType.REPLACES,
    RelationshipType.UNKNOWN: RelationshipType.UNKNOWN,  # Self-inverse
}


def get_inverse_relationship(rel_type: RelationshipType) -> RelationshipType:
    """Get the inverse of a relationship type.

    Args:
        rel_type: The relationship type to invert

    Returns:
        The inverse relationship type

    Example:
        >>> get_inverse_relationship(RelationshipType.CALLS)
        RelationshipType.CALLED_BY
    """
    return INVERSE_RELATIONSHIPS.get(rel_type, RelationshipType.UNKNOWN)


# Type-specific metadata schemas


@dataclass
class CodeRelationshipMetadata:
    """Metadata for code-related relationships (calls, imports, references, etc.)."""

    line_number: Optional[int] = None
    column_number: Optional[int] = None
    file_path: Optional[str] = None
    context: Optional[str] = None  # Surrounding code context
    language: Optional[str] = None
    # Import-specific fields
    resolution_strategy: Optional[str] = None  # How import was resolved
    resolution_confidence: Optional[float] = None  # Confidence score 0-1
    first_pass_confidence: Optional[float] = None  # First pass resolution confidence
    import_path: Optional[str] = None  # Full import path
    import_type: Optional[str] = None  # Type of import (absolute, relative, etc.)
    # Contains-specific fields
    hierarchy_level: Optional[int] = None  # Nesting level in document structure
    # Call-specific fields (from parser)
    call_type: Optional[str] = None  # Type of call (function, method, constructor)
    object: Optional[str] = None  # Object on which the method is called
    line: Optional[int] = (
        None  # Line number of the call (alias for line_number from parser)
    )
    # Defines-specific fields (from parser)
    start_line: Optional[int] = None  # Start line of the defined symbol
    end_line: Optional[int] = None  # End line of the defined symbol

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class DocumentationRelationshipMetadata:
    """Metadata for documentation relationships."""

    section: Optional[str] = None  # Section/heading in documentation
    page_number: Optional[int] = None
    url: Optional[str] = None
    format: Optional[str] = None  # markdown, rst, html, etc.

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class TemporalRelationshipMetadata:
    """Metadata for temporal relationships (precedes, follows, replaces)."""

    timestamp: Optional[str] = None  # ISO format timestamp
    version: Optional[str] = None
    commit_hash: Optional[str] = None
    author: Optional[str] = None
    # Resolution metadata (for graph builder consistency)
    resolution_confidence: Optional[float] = None  # 0.0 to 1.0
    resolution_strategy: Optional[str] = None  # How the relationship was resolved

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class TestRelationshipMetadata:
    """Metadata for test relationships."""

    test_type: Optional[str] = None  # unit, integration, e2e, etc.
    coverage_percentage: Optional[float] = None
    test_framework: Optional[str] = None  # pytest, unittest, etc.

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class SemanticRelationshipMetadata:
    """Metadata for semantic/conceptual relationships."""

    similarity_score: Optional[float] = None  # 0.0 to 1.0
    confidence: Optional[float] = None  # 0.0 to 1.0
    reasoning: Optional[str] = None  # Why this relationship exists

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


# Mapping of relationship types to their metadata schemas
RELATIONSHIP_METADATA_SCHEMAS = {
    # Code relationships use CodeRelationshipMetadata
    RelationshipType.CALLS: CodeRelationshipMetadata,
    RelationshipType.CALLED_BY: CodeRelationshipMetadata,
    RelationshipType.IMPORTS: CodeRelationshipMetadata,
    RelationshipType.IMPORTED_BY: CodeRelationshipMetadata,
    RelationshipType.INHERITS: CodeRelationshipMetadata,
    RelationshipType.INHERITED_BY: CodeRelationshipMetadata,
    RelationshipType.IMPLEMENTS: CodeRelationshipMetadata,
    RelationshipType.IMPLEMENTED_BY: CodeRelationshipMetadata,
    RelationshipType.DEFINES: CodeRelationshipMetadata,
    RelationshipType.DEFINED_IN: CodeRelationshipMetadata,
    RelationshipType.REFERENCES: CodeRelationshipMetadata,
    RelationshipType.REFERENCED_BY: CodeRelationshipMetadata,
    RelationshipType.USES: CodeRelationshipMetadata,
    RelationshipType.USED_BY: CodeRelationshipMetadata,
    RelationshipType.CONTAINS: CodeRelationshipMetadata,
    RelationshipType.CONTAINED_IN: CodeRelationshipMetadata,
    RelationshipType.OVERRIDES: CodeRelationshipMetadata,
    RelationshipType.OVERRIDDEN_BY: CodeRelationshipMetadata,
    RelationshipType.DECORATES: CodeRelationshipMetadata,
    RelationshipType.DECORATED_BY: CodeRelationshipMetadata,
    # Documentation relationships use DocumentationRelationshipMetadata
    RelationshipType.DOCUMENTS: DocumentationRelationshipMetadata,
    RelationshipType.DOCUMENTED_BY: DocumentationRelationshipMetadata,
    RelationshipType.EXPLAINS: DocumentationRelationshipMetadata,
    RelationshipType.EXPLAINED_BY: DocumentationRelationshipMetadata,
    RelationshipType.CROSS_REFERENCES: DocumentationRelationshipMetadata,
    RelationshipType.CROSS_REFERENCED_BY: DocumentationRelationshipMetadata,
    # Semantic relationships use SemanticRelationshipMetadata
    RelationshipType.RELATES_TO: SemanticRelationshipMetadata,
    RelationshipType.RELATED_BY: SemanticRelationshipMetadata,
    RelationshipType.SIMILAR_TO: SemanticRelationshipMetadata,
    RelationshipType.DEPENDS_ON: SemanticRelationshipMetadata,
    RelationshipType.DEPENDENCY_OF: SemanticRelationshipMetadata,
    RelationshipType.RECALLS: SemanticRelationshipMetadata,
    RelationshipType.RECALLED_BY: SemanticRelationshipMetadata,
    RelationshipType.LEARNED_FROM: SemanticRelationshipMetadata,
    RelationshipType.TAUGHT: SemanticRelationshipMetadata,
    # Test relationships use TestRelationshipMetadata
    RelationshipType.TESTS: TestRelationshipMetadata,
    RelationshipType.TESTED_BY: TestRelationshipMetadata,
    RelationshipType.MOCKS: TestRelationshipMetadata,
    RelationshipType.MOCKED_BY: TestRelationshipMetadata,
    # Temporal relationships use TemporalRelationshipMetadata
    RelationshipType.PRECEDES: TemporalRelationshipMetadata,
    RelationshipType.FOLLOWS: TemporalRelationshipMetadata,
    RelationshipType.REPLACES: TemporalRelationshipMetadata,
    RelationshipType.REPLACED_BY: TemporalRelationshipMetadata,
}


def validate_relationship_metadata(
    rel_type: RelationshipType, metadata: Optional[Union[str, Dict[str, Any]]]
) -> Optional[str]:
    """Validate that metadata matches the expected schema for a relationship type.

    Args:
        rel_type: The relationship type
        metadata: The metadata to validate (can be JSON string or dict)

    Returns:
        Validated metadata as JSON string, or None if no metadata

    Raises:
        ValueError: If metadata is invalid for the relationship type
    """
    if metadata is None:
        return None

    # Parse metadata if it's a string
    if isinstance(metadata, str):
        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON metadata: {e}")
    else:
        metadata_dict = metadata

    # Get expected schema for this relationship type
    schema_class = RELATIONSHIP_METADATA_SCHEMAS.get(rel_type)

    if schema_class is None:
        # No specific schema, allow any dict
        return json.dumps(metadata_dict)

    # Validate that all keys in metadata are valid for the schema
    valid_fields = {f.name for f in schema_class.__dataclass_fields__.values()}  # type: ignore
    invalid_fields = set(metadata_dict.keys()) - valid_fields

    if invalid_fields:
        raise ValueError(
            f"Invalid metadata fields for {rel_type.value}: {invalid_fields}. "
            f"Valid fields: {valid_fields}"
        )

    # Create instance to validate types
    try:
        instance = schema_class(**metadata_dict)
        return json.dumps(instance.to_dict())
    except TypeError as e:
        raise ValueError(f"Invalid metadata types for {rel_type.value}: {e}")


def parse_relationship_metadata(
    rel_type: RelationshipType, metadata: Optional[str]
) -> Optional[
    Union[
        CodeRelationshipMetadata,
        DocumentationRelationshipMetadata,
        TemporalRelationshipMetadata,
        TestRelationshipMetadata,
        SemanticRelationshipMetadata,
        Dict[str, Any],
    ]
]:
    """Parse metadata string into appropriate typed metadata object.

    Args:
        rel_type: The relationship type
        metadata: JSON string metadata

    Returns:
        Typed metadata object or dict if no specific schema
    """
    if metadata is None:
        return None

    try:
        metadata_dict = json.loads(metadata)
    except json.JSONDecodeError:
        return None

    schema_class = RELATIONSHIP_METADATA_SCHEMAS.get(rel_type)

    if schema_class is None:
        return metadata_dict

    try:
        return schema_class(**metadata_dict)
    except TypeError:
        return metadata_dict


@dataclass(slots=True)
class GraphRelationship:
    """Represents a directed edge in the knowledge graph."""

    id: str
    source_id: str
    target_id: str
    type: str
    project_id: str
    vector: List[float]
    metadata: Optional[str] = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.id,
                self.source_id,
                self.target_id,
                self.type,
                self.project_id,
            )
        ):
            raise ValueError(
                "GraphRelationship id, source_id, target_id, type and project_id must be non-empty strings"
            )
        if not isinstance(self.vector, list) or not all(
            isinstance(v, (int, float)) for v in self.vector
        ):
            raise ValueError("vector must be a list of numbers")

        # Validate relationship type if it's a known type
        try:
            rel_type = RelationshipType(self.type)
        except ValueError:
            # Unknown relationship type - allow it but don't validate metadata
            rel_type = None

        # Validate metadata if we have a known relationship type
        if rel_type is not None and self.metadata is not None:
            self.metadata = validate_relationship_metadata(rel_type, self.metadata)

    @classmethod
    def get_source_column(cls, vector_column_name: str) -> str:
        """Return the default text column used for embedding generation."""
        return "type"

    def to_dict(self) -> dict:
        """Serialise the dataclass to a plain dictionary."""
        return asdict(self)

    def to_db_dict(self, backend: str = "lancedb") -> dict:
        """Serialise to a dictionary with backend-specific column names.

        Different storage backends use different column names:
        - LanceDB schema uses 'type' for relationship type
        - PostgreSQL schema uses 'relationship_type' for relationship type

        Args:
            backend: Storage backend ("lancedb" or "postgresql")

        Returns:
            Dictionary with column names appropriate for the backend
        """
        data = asdict(self)
        if backend == "postgresql":
            # PostgreSQL uses 'relationship_type' instead of 'type'
            data["relationship_type"] = data.pop("type")
        return data

    @classmethod
    def from_db_dict(cls, data: dict, backend: str = "lancedb") -> "GraphRelationship":
        """Create instance from a database dictionary.

        Handles column name mapping for different backends.

        Args:
            data: Database row as dictionary
            backend: Storage backend ("lancedb" or "postgresql")

        Returns:
            GraphRelationship instance
        """
        data = dict(data)  # Don't modify the input
        if backend == "postgresql" and "relationship_type" in data:
            # PostgreSQL uses 'relationship_type', model uses 'type'
            data["type"] = data.pop("relationship_type")
        return cls(**data)

    def get_typed_metadata(
        self,
    ) -> Optional[
        Union[
            CodeRelationshipMetadata,
            DocumentationRelationshipMetadata,
            TemporalRelationshipMetadata,
            TestRelationshipMetadata,
            SemanticRelationshipMetadata,
            Dict[str, Any],
        ]
    ]:
        """Get metadata as a typed object based on relationship type.

        Returns:
            Typed metadata object or dict if no specific schema, or None if no metadata
        """
        try:
            rel_type = RelationshipType(self.type)
            return parse_relationship_metadata(rel_type, self.metadata)
        except ValueError:
            # Unknown relationship type
            if self.metadata:
                try:
                    return json.loads(self.metadata)
                except json.JSONDecodeError:
                    return None
            return None

    def set_typed_metadata(
        self,
        metadata: Union[
            CodeRelationshipMetadata,
            DocumentationRelationshipMetadata,
            TemporalRelationshipMetadata,
            TestRelationshipMetadata,
            SemanticRelationshipMetadata,
            Dict[str, Any],
        ],
    ) -> None:
        """Set metadata from a typed object.

        Args:
            metadata: Typed metadata object or dict
        """
        if hasattr(metadata, "to_dict"):
            self.metadata = json.dumps(metadata.to_dict())
        else:
            self.metadata = json.dumps(metadata)

    def get_inverse(self) -> RelationshipType:
        """Get the inverse relationship type.

        Returns:
            The inverse relationship type, or UNKNOWN if not a known type
        """
        try:
            rel_type = RelationshipType(self.type)
            return get_inverse_relationship(rel_type)
        except ValueError:
            return RelationshipType.UNKNOWN
