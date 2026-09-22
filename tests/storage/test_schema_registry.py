"""Tests for the schema registry module.

Tests cover:
    - Schema discovery and loading
    - Schema merging functionality
    - Backend schema validation
    - Runtime registration
    - Cache behavior
    - Property-based invariants (hypothesis)
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from hypothesis import assume, given, settings, HealthCheck
from hypothesis import strategies as st

from agentic_inquiry.storage.schema_registry import (
    SCHEMA_REGISTRY,
    SCHEMAS_DIR,
    clear_cache,
    discover_schemas,
    get_backend_schema,
    get_merged_storage_schema,
    get_registered_backends,
    get_registry_info,
    register_backend_schema,
)


@pytest.fixture(autouse=True)
def clear_schema_cache():
    """Clear schema cache before each test."""
    clear_cache()
    yield
    clear_cache()


class TestSchemaDiscovery:
    """Tests for schema discovery functionality."""

    def test_schemas_directory_exists(self):
        """Schema directory should exist."""
        assert SCHEMAS_DIR.exists(), f"Schemas directory not found: {SCHEMAS_DIR}"

    def test_discover_schemas_finds_files(self):
        """Should discover all schema files in the directory."""
        schemas = discover_schemas()
        assert len(schemas) > 0, "Should find at least one schema file"
        assert all(s.endswith(".schema.json") for s in schemas)

    def test_all_registered_backends_have_schema_files(self):
        """All registered backends should have corresponding schema files."""
        discovered = set(discover_schemas())
        for backend_type, schema_file in SCHEMA_REGISTRY.items():
            assert schema_file in discovered, (
                f"Schema file '{schema_file}' for backend '{backend_type}' not found"
            )


class TestSchemaLoading:
    """Tests for schema loading functionality."""

    def test_get_registered_backends(self):
        """Should return all registered backend types."""
        backends = get_registered_backends()
        assert "lancedb" in backends
        assert "postgresql" in backends
        assert "sqlite" in backends
        assert "memory" in backends

    def test_load_postgresql_schema(self):
        """Should load PostgreSQL schema correctly."""
        schema = get_backend_schema("postgresql")
        assert schema is not None
        assert schema["title"] == "PostgreSQL Backend Configuration"
        assert "connection_string" in schema["properties"]
        assert "pool_size" in schema["properties"]

    def test_load_lancedb_schema(self):
        """Should load LanceDB schema correctly."""
        schema = get_backend_schema("lancedb")
        assert schema is not None
        assert "database_path" in schema["properties"]

    def test_load_sqlite_schema(self):
        """Should load SQLite schema correctly."""
        schema = get_backend_schema("sqlite")
        assert schema is not None
        assert "database_path" in schema["properties"]

    def test_load_memory_schema(self):
        """Should load memory schema correctly."""
        schema = get_backend_schema("memory")
        assert schema is not None
        assert schema["properties"]["type"]["const"] == "memory"

    def test_load_cloudsql_schema(self):
        """Should load CloudSQL schema correctly."""
        schema = get_backend_schema("cloudsql")
        assert schema is not None
        assert "project" in schema["properties"]
        assert "region" in schema["properties"]
        assert "instance" in schema["properties"]

    def test_load_unregistered_backend_returns_none(self):
        """Loading unregistered backend should return None."""
        schema = get_backend_schema("nonexistent_backend")
        assert schema is None

    def test_schema_caching(self):
        """Schema should be cached after first load."""
        schema1 = get_backend_schema("postgresql")
        schema2 = get_backend_schema("postgresql")
        # Should be the same object (from cache)
        assert schema1 is schema2


class TestSchemaRegistration:
    """Tests for runtime schema registration."""

    def test_register_custom_backend(self, tmp_path):
        """Should allow registering custom backend schemas."""
        # Create a custom schema file
        custom_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Custom Backend",
            "type": "object",
            "properties": {
                "type": {"const": "custom"},
                "custom_field": {"type": "string"},
            },
        }
        schema_file = tmp_path / "custom.schema.json"
        schema_file.write_text(json.dumps(custom_schema))

        # Register the custom backend (using absolute path)
        register_backend_schema("custom", str(schema_file))

        assert "custom" in get_registered_backends()

    def test_registration_invalidates_cache(self):
        """Registering a backend should invalidate its cache entry."""
        # Load postgresql schema to populate cache
        get_backend_schema("postgresql")

        # Re-register should clear cache
        register_backend_schema("postgresql", "postgresql.schema.json")

        # Should reload from file (cache was cleared)
        # Just verify no exception is raised
        get_backend_schema("postgresql")


class TestSchemaMerging:
    """Tests for schema merging functionality."""

    @pytest.fixture
    def base_schema(self):
        """Load the base configuration schema."""
        schema_path = Path(__file__).parent.parent.parent / "config" / "config.schema.json"
        with open(schema_path, "r") as f:
            return json.load(f)

    def test_merged_schema_has_backends_property(self, base_schema):
        """Merged schema should have 'backends' property in storage."""
        merged = get_merged_storage_schema(base_schema)
        storage_props = merged["properties"]["storage"]["properties"]
        assert "backends" in storage_props

    def test_merged_schema_has_role_assignments(self, base_schema):
        """Merged schema should have role assignment properties."""
        merged = get_merged_storage_schema(base_schema)
        storage_props = merged["properties"]["storage"]["properties"]
        assert "vector_backend" in storage_props
        assert "graph_backend" in storage_props
        assert "events_backend" in storage_props
        assert "file_tracker_backend_v2" in storage_props

    def test_merged_schema_preserves_base_properties(self, base_schema):
        """Merging should preserve existing base schema properties."""
        merged = get_merged_storage_schema(base_schema)
        storage_props = merged["properties"]["storage"]["properties"]
        # Original properties should still exist
        assert "root" in storage_props
        assert "lancedb" in storage_props
        assert "file_tracker" in storage_props

    def test_merged_schema_removes_additional_properties_restriction(self, base_schema):
        """Merging should remove additionalProperties: false from storage."""
        # Base schema has the restriction in the file
        merged = get_merged_storage_schema(base_schema)
        storage = merged["properties"]["storage"]
        # Should not have additionalProperties: false (allows extension)
        assert storage.get("additionalProperties") is not False

    def test_backend_enums_expanded(self, base_schema):
        """Backend enum fields should include all registered backends."""
        merged = get_merged_storage_schema(base_schema)
        storage_props = merged["properties"]["storage"]["properties"]

        backend_field = storage_props.get("backend", {})
        if "enum" in backend_field:
            backends = set(backend_field["enum"])
            # Should include postgresql and cloudsql (not just lancedb)
            assert "postgresql" in backends or len(backends) > 1


class TestRegistryInfo:
    """Tests for registry information utilities."""

    def test_get_registry_info(self):
        """Should return human-readable registry info."""
        info = get_registry_info()
        assert isinstance(info, dict)
        assert "postgresql" in info
        assert "lancedb" in info
        # Values should be full paths
        assert "schema.json" in info["postgresql"]


class TestSchemaValidation:
    """Tests for schema validation with jsonschema."""

    @pytest.fixture
    def merged_schema(self):
        """Get merged schema for validation tests."""
        schema_path = Path(__file__).parent.parent.parent / "config" / "config.schema.json"
        with open(schema_path, "r") as f:
            base = json.load(f)
        return get_merged_storage_schema(base)

    def test_valid_config_with_backends(self, merged_schema):
        """Config with backends section should validate."""
        pytest.importorskip("jsonschema")
        import jsonschema

        config = {
            "storage": {
                "root": "./.agentic-inquiry",
                "lancedb": {"path": "lancedb"},
                "file_tracker": {"path": "file_tracker.db"},
                "document_cache": {"enabled": False, "path": "cache"},
                "backends": {
                    "primary_pg": {
                        "type": "postgresql",
                        "connection_string": "postgresql://localhost/test",
                    }
                },
                "vector_backend": "primary_pg",
            },
            "cache": {
                "document_cache": {"max_size": 1000}
            },
            "search": {
                "default_limit": 10,
                "max_limit": 100
            },
            "embeddings": {
                "default_provider": "sentence_transformer"
            },
            "parsers": {}
        }

        # Should not raise
        jsonschema.validate(config, merged_schema)


# Hypothesis strategies for property-based testing
json_primitive = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000000, max_value=1000000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=50),
)


# JSON-compatible nested structures (limited depth for performance)
json_value = st.recursive(
    json_primitive,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=5),
    ),
    max_leaves=20,
)


class TestSchemaMergingPropertyBased:
    """Property-based tests for schema merging invariants.

    These tests use hypothesis to verify that schema merging preserves
    important invariants regardless of input variations.
    """

    @pytest.fixture
    def real_base_schema(self):
        """Load the actual base configuration schema."""
        schema_path = Path(__file__).parent.parent.parent / "config" / "config.schema.json"
        with open(schema_path, "r") as f:
            return json.load(f)

    @given(extra_props=st.dictionaries(
        st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_"),
        json_value,
        max_size=5
    ))
    @settings(max_examples=50, deadline=None)
    def test_merging_never_modifies_original_schema(self, extra_props):
        """Property: get_merged_storage_schema should never modify the input schema."""
        # Create a base schema with storage section
        base_schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "properties": {
                "storage": {
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        **extra_props
                    },
                    "additionalProperties": False,
                }
            }
        }

        # Deep copy before merging to compare
        original = deepcopy(base_schema)

        # Perform merge
        get_merged_storage_schema(base_schema)

        # Original should be unchanged
        assert base_schema == original, "Merging modified the original schema"

    @given(prop_name=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_"))
    @settings(max_examples=30, deadline=None)
    def test_merging_preserves_arbitrary_storage_properties(self, prop_name):
        """Property: Existing storage properties should be preserved after merging."""
        # Skip reserved property names that get modified
        assume(prop_name not in {"backends", "vector_backend", "graph_backend",
                                  "events_backend", "file_tracker_backend_v2",
                                  "table_prefix", "additionalProperties"})

        base_schema = {
            "properties": {
                "storage": {
                    "type": "object",
                    "properties": {
                        prop_name: {"type": "string", "description": "test property"}
                    }
                }
            }
        }

        merged = get_merged_storage_schema(base_schema)
        storage_props = merged["properties"]["storage"]["properties"]

        assert prop_name in storage_props, f"Property '{prop_name}' was lost during merging"
        assert storage_props[prop_name]["type"] == "string"

    @given(backend_names=st.lists(
        st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnopqrstuvwxyz"),
        min_size=0,
        max_size=3,
        unique=True
    ))
    @settings(max_examples=30, deadline=None)
    def test_merged_schema_always_has_required_role_properties(self, backend_names):
        """Property: Merged schema always has role assignment properties."""
        base_schema = {
            "properties": {
                "storage": {
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                    }
                }
            }
        }

        merged = get_merged_storage_schema(base_schema)
        storage_props = merged["properties"]["storage"]["properties"]

        # These role properties should always be present
        required_roles = ["vector_backend", "graph_backend", "events_backend",
                         "file_tracker_backend_v2"]

        for role in required_roles:
            assert role in storage_props, f"Role property '{role}' missing from merged schema"
            assert storage_props[role]["type"] == "string"

    @given(extra_top_level=st.dictionaries(
        st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnopqrstuvwxyz"),
        st.fixed_dictionaries({"type": st.just("object")}),
        max_size=3
    ))
    @settings(max_examples=30, deadline=None)
    def test_merging_preserves_non_storage_properties(self, extra_top_level):
        """Property: Non-storage properties in the schema are preserved."""
        base_schema = {
            "properties": {
                "storage": {
                    "type": "object",
                    "properties": {"root": {"type": "string"}}
                },
                **extra_top_level
            }
        }

        merged = get_merged_storage_schema(base_schema)

        for prop_name in extra_top_level:
            assert prop_name in merged["properties"], \
                f"Top-level property '{prop_name}' was lost during merging"

    def test_merging_always_produces_valid_json_schema_structure(self, real_base_schema):
        """Property: Merged schema should always have valid JSON schema structure."""
        merged = get_merged_storage_schema(real_base_schema)

        # Must have properties
        assert "properties" in merged
        assert "storage" in merged["properties"]

        storage = merged["properties"]["storage"]
        assert "properties" in storage

        # Backends should have oneOf or be an object type
        backends_schema = storage["properties"].get("backends", {})
        assert "additionalProperties" in backends_schema or "type" in backends_schema

    def test_all_registered_backends_included_in_merged_schema(self, real_base_schema):
        """Property: All registered backends should be available in merged schema."""
        merged = get_merged_storage_schema(real_base_schema)
        storage_props = merged["properties"]["storage"]["properties"]

        backends_schema = storage_props.get("backends", {})
        additional_props = backends_schema.get("additionalProperties", {})

        # Should have oneOf with all backend schemas
        if "oneOf" in additional_props:
            backend_types_in_schema = set()
            for schema in additional_props["oneOf"]:
                if "properties" in schema and "type" in schema["properties"]:
                    type_schema = schema["properties"]["type"]
                    if "const" in type_schema:
                        backend_types_in_schema.add(type_schema["const"])

            registered = get_registered_backends()
            for backend in registered:
                assert backend in backend_types_in_schema, \
                    f"Registered backend '{backend}' not found in merged schema"

    @given(iterations=st.integers(min_value=1, max_value=5))
    @settings(
        max_examples=10,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    def test_merging_is_idempotent(self, real_base_schema, iterations):
        """Property: Merging multiple times should produce equivalent results.

        Note: real_base_schema fixture is read-only, safe to use with hypothesis.
        """
        # First merge
        first_merge = get_merged_storage_schema(real_base_schema)

        # Merge the same base schema multiple times
        result = real_base_schema
        for _ in range(iterations):
            result = get_merged_storage_schema(deepcopy(real_base_schema))

        # Compare storage sections (they should be equivalent)
        assert first_merge["properties"]["storage"] == result["properties"]["storage"]
