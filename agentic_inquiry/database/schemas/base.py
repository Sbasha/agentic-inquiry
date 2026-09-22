"""Base schema definitions for canonical logical schemas.

This module defines the building blocks for logical schema specifications.
Schemas define the canonical field names and types that all adapters must support.

See: docs/design/logical-schema-reference.md
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


class FieldType(str, Enum):
    """Canonical field types for schema definitions.

    These types are abstract and map to backend-specific types at the adapter layer.
    """

    # Primitive types
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"

    # Complex types
    DATETIME = "datetime"  # ISO 8601 string at storage boundary
    JSON = "json"  # Dict/struct depending on backend
    VECTOR = "vector"  # List[float] with fixed dimensions

    # List types
    STRING_LIST = "string_list"  # List[str]
    FLOAT_LIST = "float_list"  # List[float] (non-vector)


@dataclass(frozen=True, slots=True)
class SchemaField:
    """Definition of a single field in a logical schema.

    Attributes:
        name: Canonical field name (snake_case)
        field_type: The type of this field
        required: Whether this field must be present
        default: Default value for optional fields (None means no default)
        description: Human-readable description for documentation
        sentinel: Sentinel value indicating "not set" (e.g., -1 for integers)
        dimensions: For VECTOR type, the expected dimensions (None = use config)
        fts_source: If True, this field is a source for full-text search indexing
    """

    name: str
    field_type: FieldType
    required: bool = True
    default: Any = None
    description: str = ""
    sentinel: Any = None
    dimensions: Optional[int] = None
    fts_source: bool = False

    def __post_init__(self) -> None:
        """Validate field definition."""
        if not self.name:
            raise ValueError("Field name cannot be empty")
        # Field names must be valid identifiers (snake_case)
        if not self.name.replace("_", "").isalnum() or self.name[0].isdigit():
            raise ValueError(
                f"Field name '{self.name}' must be a valid snake_case identifier"
            )


@dataclass(frozen=True)
class LogicalSchema:
    """Definition of a logical table schema.

    LogicalSchema defines the canonical structure that all adapters must support.
    Adapters map physical storage to these logical field names.

    Attributes:
        name: Logical table name
        fields: Tuple of field definitions (frozen for immutability)
        description: Human-readable description
        primary_key: Field name(s) that uniquely identify a row
        fts_columns: Fields to include in full-text search index
        vector_columns: Fields containing vectors for similarity search
    """

    name: str
    fields: Tuple[SchemaField, ...]
    description: str = ""
    primary_key: Tuple[str, ...] = ("id",)
    fts_columns: Tuple[str, ...] = ()
    vector_columns: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate schema definition."""
        if not self.name:
            raise ValueError("Schema name cannot be empty")

        # Validate all fields exist
        field_names = {f.name for f in self.fields}

        # Primary key fields must exist
        for pk in self.primary_key:
            if pk not in field_names:
                raise ValueError(
                    f"Primary key field '{pk}' not found in schema '{self.name}'"
                )

        # FTS columns must exist
        for fts_col in self.fts_columns:
            if fts_col not in field_names:
                raise ValueError(
                    f"FTS column '{fts_col}' not found in schema '{self.name}'"
                )

        # Vector columns must exist and be of VECTOR type
        for vec_col in self.vector_columns:
            if vec_col not in field_names:
                raise ValueError(
                    f"Vector column '{vec_col}' not found in schema '{self.name}'"
                )
            vec_field = self.get_field(vec_col)
            if vec_field and vec_field.field_type != FieldType.VECTOR:
                raise ValueError(
                    f"Vector column '{vec_col}' must have VECTOR type, "
                    f"got {vec_field.field_type}"
                )

        # Check for duplicate field names
        if len(field_names) != len(self.fields):
            raise ValueError(f"Duplicate field names in schema '{self.name}'")

    def get_field(self, name: str) -> Optional[SchemaField]:
        """Get a field by name.

        Args:
            name: Field name to look up

        Returns:
            SchemaField if found, None otherwise
        """
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def get_required_fields(self) -> List[SchemaField]:
        """Get all required fields.

        Returns:
            List of required SchemaField instances
        """
        return [f for f in self.fields if f.required]

    def get_optional_fields(self) -> List[SchemaField]:
        """Get all optional fields.

        Returns:
            List of optional SchemaField instances
        """
        return [f for f in self.fields if not f.required]

    def get_field_names(self) -> FrozenSet[str]:
        """Get all field names as a frozen set.

        Returns:
            FrozenSet of field names
        """
        return frozenset(f.name for f in self.fields)

    def validate_row(self, row: Dict[str, Any]) -> List[str]:
        """Validate a row against this schema.

        Args:
            row: Dictionary representing a row of data

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check required fields
        for f in self.fields:
            if f.required and f.name not in row:
                errors.append(f"Missing required field: {f.name}")

        # Check for unknown fields
        known_fields = self.get_field_names()
        for key in row:
            if key not in known_fields:
                errors.append(f"Unknown field: {key}")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert schema to dictionary for serialization.

        Returns:
            Dictionary representation of the schema
        """
        return {
            "name": self.name,
            "description": self.description,
            "primary_key": list(self.primary_key),
            "fts_columns": list(self.fts_columns),
            "vector_columns": list(self.vector_columns),
            "fields": [
                {
                    "name": f.name,
                    "field_type": f.field_type.value,
                    "required": f.required,
                    "default": f.default,
                    "description": f.description,
                    "sentinel": f.sentinel,
                    "dimensions": f.dimensions,
                    "fts_source": f.fts_source,
                }
                for f in self.fields
            ],
        }
