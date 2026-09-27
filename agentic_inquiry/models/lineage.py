"""Data models for lineage tracing and impact analysis.

This module provides models for tracking data flow through the codebase,
from UI components through backend services to database columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Confidence(str, Enum):
    """Confidence level for lineage relationships.

    Higher confidence indicates stronger evidence for the relationship.
    """

    HIGH = "high"  # Direct annotation or explicit mapping
    MEDIUM = "medium"  # Naming convention match
    LOW = "low"  # Single weak indicator
    INFERRED = "inferred"  # Guessed from context


# Explicit ranking for confidence comparison (Codex fix: avoid min() on Enum)
CONFIDENCE_RANK: dict[Confidence, int] = {
    Confidence.INFERRED: 1,
    Confidence.LOW: 2,
    Confidence.MEDIUM: 3,
    Confidence.HIGH: 4,
}


class ArchitecturalLayer(str, Enum):
    """Architectural layer classification for entities.

    Used to identify where an entity sits in the application stack.
    """

    UI = "ui"  # JSP, Vue, React components, HTML templates
    CONTROLLER = "controller"  # REST controllers, request handlers
    SERVICE = "service"  # Business logic layer
    REPOSITORY = "repository"  # Data access layer
    ENTITY = "entity"  # ORM entities, domain models
    DATABASE = "database"  # Tables, columns, schemas
    UNKNOWN = "unknown"  # Could not determine layer


# Layer inference patterns
LAYER_PATTERNS: dict[ArchitecturalLayer, list[str]] = {
    ArchitecturalLayer.UI: [
        "component",
        "view",
        "template",
        "page",
        "form",
        ".tsx",
        ".jsx",
        ".vue",
        ".html",
        ".jsp",
    ],
    ArchitecturalLayer.CONTROLLER: [
        "controller",
        "handler",
        "endpoint",
        "resource",
        "router",
        "@Controller",
        "@RestController",
        "@RequestMapping",
    ],
    ArchitecturalLayer.SERVICE: [
        "service",
        "manager",
        "facade",
        "orchestrator",
        "@Service",
        "@Component",
    ],
    ArchitecturalLayer.REPOSITORY: [
        "repository",
        "dao",
        "mapper",
        "store",
        "@Repository",
        "Repository",
    ],
    ArchitecturalLayer.ENTITY: [
        "entity",
        "model",
        "domain",
        "@Entity",
        "Base",
        "__tablename__",
    ],
    ArchitecturalLayer.DATABASE: [
        "table",
        "column",
        "schema",
        "migration",
        ".sql",
    ],
}


@dataclass
class LineageStep:
    """A single step in a lineage path.

    Represents one entity in the chain from source to sink.
    """

    entity_id: str
    entity_name: str
    entity_type: str
    layer: ArchitecturalLayer
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    relationship_type: Optional[str] = None  # How connected to previous step
    confidence: Confidence = Confidence.MEDIUM

    def __post_init__(self) -> None:
        if not self.entity_id or not self.entity_name:
            raise ValueError("entity_id and entity_name are required")
        if not isinstance(self.layer, ArchitecturalLayer):
            self.layer = ArchitecturalLayer(self.layer)
        if not isinstance(self.confidence, Confidence):
            self.confidence = Confidence(self.confidence)


@dataclass
class LineagePath:
    """Complete path from source to sink.

    Represents a full data flow path through the application layers.
    """

    path_id: str
    source_id: str
    sink_id: str
    steps: List[LineageStep] = field(default_factory=list)
    is_complete: bool = False
    gaps: List[str] = field(default_factory=list)  # Missing connections

    @property
    def min_confidence(self) -> Confidence:
        """Get minimum confidence across all steps.

        Uses explicit ranking to avoid Enum comparison issues.
        """
        if not self.steps:
            return Confidence.LOW

        min_step = min(self.steps, key=lambda s: CONFIDENCE_RANK.get(s.confidence, 0))
        return min_step.confidence

    @property
    def depth(self) -> int:
        """Number of hops in the path."""
        return len(self.steps)

    def has_layer(self, layer: ArchitecturalLayer) -> bool:
        """Check if path passes through a specific layer."""
        return any(s.layer == layer for s in self.steps)


@dataclass
class ImpactAnalysis:
    """Result of impact analysis for an entity.

    Shows what would be affected by changing the target entity.
    """

    entity_id: str
    entity_name: str
    affected_entities: List[str] = field(default_factory=list)
    affected_files: List[str] = field(default_factory=list)
    affected_count: int = 0
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    paths: List[LineagePath] = field(default_factory=list)
    is_pii: bool = False

    def __post_init__(self) -> None:
        self.affected_count = len(self.affected_entities)


# Lineage-specific relationship types to add to RelationshipType enum
LINEAGE_RELATIONSHIP_TYPES = {
    "binds_to",  # UI element → data field
    "maps_to",  # Entity field → DB column
    "returns_view",  # Controller → view template
    "uses_model",  # Controller → model attribute
    "receives_prop",  # Component receives prop from parent
    "emits",  # Component emits event
    "injects",  # Dependency injection
}


# PII field detection patterns
PII_PATTERNS = [
    "email",
    "phone",
    "ssn",
    "address",
    "name",
    "password",
    "credit_card",
    "dob",
    "birth",
    "social_security",
    "passport",
    "license",
]


def is_pii_field(name: str) -> bool:
    """Check if entity name suggests PII data.

    Args:
        name: Entity or field name to check

    Returns:
        True if name matches PII patterns
    """
    name_lower = name.lower()
    return any(pattern in name_lower for pattern in PII_PATTERNS)


def infer_layer(
    entity_name: str, entity_type: str, file_path: Optional[str]
) -> ArchitecturalLayer:
    """Infer architectural layer from entity metadata.

    Args:
        entity_name: Name of the entity
        entity_type: Type (class, function, etc.)
        file_path: Path to the file containing the entity

    Returns:
        Best guess for architectural layer
    """
    # Combine all text for pattern matching
    search_text = f"{entity_name} {entity_type} {file_path or ''}".lower()

    # Check each layer's patterns
    for layer, patterns in LAYER_PATTERNS.items():
        for pattern in patterns:
            if pattern.lower() in search_text:
                return layer

    return ArchitecturalLayer.UNKNOWN
