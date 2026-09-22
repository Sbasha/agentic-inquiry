"""Schema registry for storage backend configuration schemas.

This module provides a registry that maps backend types to their JSON schema files.
Schemas are loaded lazily and merged at validation time to allow backends to extend
the base configuration schema without modifying core code.

Design principles:
    - Plugin-like: Backends provide their own schema fragments
    - Lazy loading: Schemas are only loaded when needed
    - Schema composition: Backend schemas are merged with the base schema
    - Backward compatible: Existing configs continue to work

Example:
    >>> from agentic_inquiry.storage.schema_registry import get_merged_storage_schema
    >>> with open("config/config.schema.json") as f:
    ...     base_schema = json.load(f)
    >>> merged = get_merged_storage_schema(base_schema)
    >>> jsonschema.validate(config_data, merged)
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Directory containing backend schema files
SCHEMAS_DIR = Path(__file__).parent / "schemas"

# Registry: backend_type -> schema_file_name
# Maps each backend type to its schema file
SCHEMA_REGISTRY: Dict[str, str] = {
    "lancedb": "lancedb.schema.json",
    "postgresql": "postgresql.schema.json",
    "cloudsql": "cloudsql.schema.json",
    "alloydb": "alloydb.schema.json",
    "sqlite": "sqlite.schema.json",
    "memory": "memory.schema.json",
    "spanner": "spanner.schema.json",
}

# Cache for loaded schemas to avoid repeated file reads
_schema_cache: Dict[str, Dict[str, Any]] = {}


class SchemaRegistryError(Exception):
    """Base exception for schema registry errors."""

    pass


class SchemaNotFoundError(SchemaRegistryError):
    """Raised when a schema file is not found."""

    def __init__(self, backend_type: str, schema_path: Path):
        self.backend_type = backend_type
        self.schema_path = schema_path
        super().__init__(
            f"Schema file not found for backend '{backend_type}': {schema_path}"
        )


class SchemaLoadError(SchemaRegistryError):
    """Raised when a schema file cannot be loaded or parsed."""

    def __init__(self, backend_type: str, cause: Exception):
        self.backend_type = backend_type
        self.cause = cause
        super().__init__(f"Failed to load schema for '{backend_type}': {cause}")


def get_registered_backends() -> Set[str]:
    """Get all backend types with registered schemas.

    Returns:
        Set of backend type names
    """
    return set(SCHEMA_REGISTRY.keys())


def get_backend_schema(backend_type: str) -> Optional[Dict[str, Any]]:
    """Load and return the schema for a backend type.

    Args:
        backend_type: The backend type to get schema for

    Returns:
        The JSON schema dict, or None if not registered

    Raises:
        SchemaNotFoundError: If schema file doesn't exist
        SchemaLoadError: If schema file can't be parsed
    """
    if backend_type not in SCHEMA_REGISTRY:
        logger.debug("No schema registered for backend: %s", backend_type)
        return None

    # Check cache first
    if backend_type in _schema_cache:
        logger.debug("Using cached schema for: %s", backend_type)
        return _schema_cache[backend_type]

    # Load schema file
    schema_file = SCHEMA_REGISTRY[backend_type]
    schema_path = SCHEMAS_DIR / schema_file

    if not schema_path.exists():
        raise SchemaNotFoundError(backend_type, schema_path)

    try:
        with open(schema_path, "r") as f:
            schema = json.load(f)
        logger.debug("Loaded schema for %s from %s", backend_type, schema_path)
    except json.JSONDecodeError as e:
        raise SchemaLoadError(backend_type, e) from e
    except Exception as e:
        raise SchemaLoadError(backend_type, e) from e

    # Cache and return
    _schema_cache[backend_type] = schema
    return schema


def register_backend_schema(backend_type: str, schema_file: str) -> None:
    """Register a custom schema file for a backend type.

    This allows extending the registry with custom backend schemas at runtime.

    Args:
        backend_type: The backend type name
        schema_file: Path to schema file (relative to schemas/ dir or absolute)

    Example:
        >>> register_backend_schema("custom_db", "custom.schema.json")
    """
    SCHEMA_REGISTRY[backend_type] = schema_file

    # Invalidate cache if it exists
    _schema_cache.pop(backend_type, None)

    logger.info("Registered schema for backend '%s': %s", backend_type, schema_file)


def clear_cache() -> None:
    """Clear the schema cache.

    Useful for testing or when reloading schemas.
    """
    _schema_cache.clear()
    logger.debug("Schema cache cleared")


def discover_schemas() -> List[str]:
    """Discover available schema files in the schemas directory.

    Returns:
        List of schema file names found
    """
    if not SCHEMAS_DIR.exists():
        return []

    return [f.name for f in SCHEMAS_DIR.glob("*.schema.json")]


def get_merged_storage_schema(base_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Merge backend schemas into the base configuration schema.

    This function modifies the storage section of the base schema to:
    1. Remove 'additionalProperties: false' from storage
    2. Add a 'backends' property for named backend configurations
    3. Add role assignment properties (vector_backend, graph_backend, etc.)
    4. Expand backend enums to include all registered backends

    Args:
        base_schema: The base configuration schema (will not be modified)

    Returns:
        A new schema with backend schemas merged in
    """
    # Deep copy to avoid modifying the original
    merged = deepcopy(base_schema)

    # Get storage properties section
    storage = merged.get("properties", {}).get("storage", {})
    if not storage:
        logger.warning("No storage section in schema, returning unmodified")
        return merged

    # Remove additionalProperties: false to allow extension
    if "additionalProperties" in storage:
        del storage["additionalProperties"]

    # Build the backends schema with oneOf for different backend types
    backend_schemas = _build_backends_property_schema()

    # Add new properties to storage section
    storage_props = storage.setdefault("properties", {})

    # Add 'backends' property (named backend configurations)
    storage_props["backends"] = {
        "type": "object",
        "description": "Named backend configurations. Each key is a backend name that can be referenced by role assignments.",
        "additionalProperties": backend_schemas,
    }

    # Add role assignment properties
    role_assignments = {
        "vector_backend": "Name of the backend to use for vector storage",
        "graph_backend": "Name of the backend to use for graph storage",
        "events_backend": "Name of the backend to use for event storage",
        "file_tracker_backend_v2": "Name of the backend to use for file tracking",
    }

    for prop_name, description in role_assignments.items():
        storage_props[prop_name] = {
            "type": "string",
            "description": description,
        }

    # Add table_prefix property (common for multi-tenant setups)
    storage_props["table_prefix"] = {
        "type": "string",
        "description": "Prefix for table names (useful for multi-tenant deployments)",
        "pattern": "^[a-zA-Z0-9_]*$",
    }

    # Expand backend enums in legacy fields to include all registered backends
    _expand_backend_enums(storage_props)

    logger.debug("Merged %d backend schemas into storage schema", len(SCHEMA_REGISTRY))
    return merged


def _build_backends_property_schema() -> Dict[str, Any]:
    """Build the schema for individual backend configurations.

    Uses oneOf to allow different backend types with type discriminator.

    Returns:
        JSON schema for a single backend configuration
    """
    backend_schemas = []

    for backend_type in get_registered_backends():
        try:
            schema = get_backend_schema(backend_type)
            if schema:
                # Ensure type discriminator is present
                if "properties" not in schema:
                    schema["properties"] = {}
                if "type" not in schema["properties"]:
                    schema["properties"]["type"] = {
                        "const": backend_type,
                        "description": f"Backend type identifier ({backend_type})",
                    }
                backend_schemas.append(schema)
        except SchemaRegistryError as e:
            # Log but don't fail - missing schemas are optional
            logger.warning("Could not load schema for %s: %s", backend_type, e)

    if not backend_schemas:
        # Fallback: allow any object if no schemas loaded
        return {"type": "object", "additionalProperties": True}

    return {"oneOf": backend_schemas}


def _expand_backend_enums(storage_props: Dict[str, Any]) -> None:
    """Expand backend enum fields to include all registered backends.

    Modifies storage properties in place to allow any registered backend type.
    """
    # Fields that should accept any backend type
    backend_enum_fields = ["backend", "event_store_backend", "file_tracker_backend"]

    # Get all registered backend types.  Include "" (empty string) as a valid
    # value so that unconfigured deployments (before `ai setup` is run) pass
    # schema validation.  The StorageFacade guard catches the empty value at
    # runtime and raises a user-friendly ConfigurationError.
    all_backends = [""] + sorted(get_registered_backends())

    for field_name in backend_enum_fields:
        if field_name in storage_props:
            field_schema = storage_props[field_name]
            # Replace enum with all backend types if it exists
            if "enum" in field_schema:
                field_schema["enum"] = all_backends
                logger.debug(
                    "Expanded enum for %s to: %s", field_name, all_backends
                )


def get_registry_info() -> Dict[str, str]:
    """Get human-readable registry information.

    Returns:
        Dict mapping backend types to schema file paths
    """
    return {
        backend_type: str(SCHEMAS_DIR / schema_file)
        for backend_type, schema_file in SCHEMA_REGISTRY.items()
    }
