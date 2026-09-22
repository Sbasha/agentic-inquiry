"""Data model representing a node in the project knowledge graph."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import List, Optional


class EntityType(str, Enum):
    """Enumeration of all entity types in the knowledge graph.
    
    Entity types categorize nodes in the knowledge graph, enabling
    type-specific filtering and disambiguation during entity resolution.
    """
    
    # Code entities (plain structural types - domain is separate "code" field)
    CODE_FUNCTION = "function"  # Standalone function (not in a class)
    CODE_METHOD = "method"  # Method within a class
    CODE_CLASS = "class"  # Class definition
    CODE_MODULE = "module"  # Module or file
    CODE_VARIABLE = "variable"  # Variable or constant
    CODE_INTERFACE = "interface"  # Interface or protocol
    CODE_ENUM = "enum"  # Enumeration
    CODE_STRUCT = "struct"  # Struct or data class
    CODE_NAMESPACE = "namespace"  # Namespace or package
    CODE_DECORATOR = "decorator"  # Decorator
    CODE_PROPERTY = "property"  # Property or attribute
    CODE_PARAMETER = "parameter"  # Function parameter
    CODE_TYPE = "type"  # Type alias or type definition
    
    # Documentation entities
    DOC_SECTION = "doc_section"  # Documentation section
    DOC_PAGE = "doc_page"  # Documentation page
    DOC_API_REF = "doc_api_ref"  # API reference entry
    DOC_GUIDE = "doc_guide"  # Tutorial or guide
    DOC_EXAMPLE = "doc_example"  # Code example in documentation
    DOC_FAQ = "doc_faq"  # FAQ entry
    DOC_CHANGELOG = "doc_changelog"  # Changelog entry
    
    # Conceptual entities
    CONCEPT = "concept"  # Abstract concept or idea
    PATTERN = "pattern"  # Design pattern or code pattern
    ARCHITECTURE = "architecture"  # Architectural component
    REQUIREMENT = "requirement"  # Requirement or specification
    DECISION = "decision"  # Design decision or ADR
    
    # Memory entities
    MEMORY_OBSERVATION = "memory_observation"  # Agent observation
    MEMORY_INSIGHT = "memory_insight"  # Agent insight or learning
    MEMORY_TASK = "memory_task"  # Task or work item
    MEMORY_NOTE = "memory_note"  # General note or annotation
    
    # Test entities
    TEST_CASE = "test_case"  # Test case
    TEST_SUITE = "test_suite"  # Test suite
    TEST_FIXTURE = "test_fixture"  # Test fixture
    TEST_MOCK = "test_mock"  # Mock or stub
    
    # Configuration entities
    CONFIG_SETTING = "config_setting"  # Configuration setting
    CONFIG_FILE = "config_file"  # Configuration file
    CONFIG_SCHEMA = "config_schema"  # Configuration schema
    
    # Data entities
    DATA_MODEL = "data_model"  # Data model or schema
    DATA_FIELD = "data_field"  # Field in a data model
    DATA_QUERY = "data_query"  # Database query
    
    # External entities (unresolved symbols from stdlib, libraries, builtins)
    EXTERNAL_FUNCTION = "external_function"  # External function or method
    EXTERNAL_CLASS = "external_class"  # External class, interface, struct, type
    EXTERNAL_MODULE = "external_module"  # External module, package, namespace
    EXTERNAL_VALUE = "external_value"  # External variable, constant, value
    EXTERNAL_SYMBOL = "external_symbol"  # External symbol (type unknown)

    # Generic fallback
    UNKNOWN = "unknown"  # Unknown entity type

    @classmethod
    def normalize(cls, type_name: str) -> str:
        """Normalize a type name to a canonical EntityType value.

        Args:
            type_name: Type name (e.g., "function", "class", "method", "code_function")

        Returns:
            Normalized EntityType value (e.g., "function", "class", "method")

        Note:
            For backward compatibility, also handles legacy "code_*" prefixed types
            by stripping the prefix.
        """
        type_lower = type_name.lower()

        # Handle legacy "code_*" prefixed types for backward compatibility
        if type_lower.startswith("code_"):
            type_lower = type_lower[5:]  # Strip "code_" prefix

        # Mapping of aliases/shorthands to canonical EntityType values
        alias_map = {
            "constant": cls.CODE_VARIABLE.value,  # Constants are variables
            "field": cls.CODE_PROPERTY.value,  # Fields are properties
            # Documentation shorthands
            "section": cls.DOC_SECTION.value,
            "page": cls.DOC_PAGE.value,
            "api": cls.DOC_API_REF.value,
            "guide": cls.DOC_GUIDE.value,
            "example": cls.DOC_EXAMPLE.value,
            "faq": cls.DOC_FAQ.value,
            "changelog": cls.DOC_CHANGELOG.value,
        }

        # Return alias mapping if found, otherwise return the type as-is
        return alias_map.get(type_lower, type_lower)


@dataclass(slots=True)
class GraphEntity:
    """Represents a node in the knowledge graph.

    The `type` field represents the structural shape (e.g., "class", "function", "method").
    The `domain` field represents the context/source (e.g., "code", "ontology", "taxonomy").
    This separation enables future flexibility for non-code entities while maintaining
    clean type semantics for filtering and grouping.
    """

    id: str
    name: str
    type: str  # Structural: "class", "function", "method", "variable", etc.
    file_path: str
    doc_id: str
    project_id: str
    vector: List[float]
    domain: str = "code"  # Context: "code", "ontology", "taxonomy", "documentation"
    line_start: int = -1
    line_end: int = -1
    pagerank: Optional[float] = None
    betweenness: Optional[float] = None
    community_id: Optional[str] = None
    has_ranking_signals: bool = False
    # Distance from vector search (not persisted, used for result ranking)
    _distance: Optional[float] = None

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.id, self.name, self.type, self.file_path, self.doc_id, self.project_id)):
            raise ValueError("GraphEntity id, name, type, file_path, doc_id and project_id must be non-empty strings")
        if not isinstance(self.vector, list) or not all(isinstance(v, (int, float)) for v in self.vector):
            raise ValueError("vector must be a list of numbers")
        if not isinstance(self.has_ranking_signals, bool):
            raise ValueError("has_ranking_signals must be a boolean")

    @classmethod
    def get_source_column(cls, vector_column_name: str) -> str:
        """Return the default text column used for embedding generation."""
        return "name"

    def to_dict(self) -> dict:
        """Serialise the dataclass to a plain dictionary.

        Note: Excludes _distance field as it's a runtime-only value
        not meant for persistence.
        """
        result = asdict(self)
        # Remove runtime-only fields that shouldn't be persisted
        result.pop('_distance', None)
        return result
