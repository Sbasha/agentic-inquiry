"""Tests for logical schema definitions.

Tests cover:
- Base schema types (FieldType, SchemaField, LogicalSchema)
- Core schemas (document_chunks, graph_entities, graph_relationships)
- Memory schemas (episodic, semantic)
- Schema validation and registry functions
"""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.database.schemas import (
    ALL_SCHEMAS,
    CORE_SCHEMAS,
    DOCUMENT_CHUNKS_SCHEMA,
    GRAPH_ENTITIES_SCHEMA,
    GRAPH_RELATIONSHIPS_SCHEMA,
    MEMORY_EPISODIC_SCHEMA,
    MEMORY_SCHEMAS,
    MEMORY_SEMANTIC_SCHEMA,
    FieldType,
    LogicalSchema,
    SchemaField,
    get_core_schema,
    get_memory_schema,
    get_schema,
)


# =============================================================================
# FieldType Tests
# =============================================================================


class TestFieldType:
    """Tests for FieldType enum."""

    def test_all_field_types_exist(self) -> None:
        """Verify all expected field types exist."""
        expected = {
            "string",
            "int",
            "float",
            "bool",
            "datetime",
            "json",
            "vector",
            "string_list",
            "float_list",
        }
        actual = {ft.value for ft in FieldType}
        assert actual == expected

    def test_field_types_are_strings(self) -> None:
        """Field types should be string enums."""
        for ft in FieldType:
            assert isinstance(ft.value, str)


# =============================================================================
# SchemaField Tests
# =============================================================================


class TestSchemaField:
    """Tests for SchemaField dataclass."""

    def test_basic_creation(self) -> None:
        """Create a basic field."""
        field = SchemaField(
            name="test_field",
            field_type=FieldType.STRING,
            required=True,
        )
        assert field.name == "test_field"
        assert field.field_type == FieldType.STRING
        assert field.required is True
        assert field.default is None

    def test_optional_field_with_default(self) -> None:
        """Create optional field with default value."""
        field = SchemaField(
            name="count",
            field_type=FieldType.INT,
            required=False,
            default=0,
        )
        assert field.required is False
        assert field.default == 0

    def test_field_with_sentinel(self) -> None:
        """Create field with sentinel value."""
        field = SchemaField(
            name="line_number",
            field_type=FieldType.INT,
            required=False,
            default=-1,
            sentinel=-1,
        )
        assert field.sentinel == -1

    def test_vector_field_with_dimensions(self) -> None:
        """Create vector field with dimensions."""
        field = SchemaField(
            name="embedding",
            field_type=FieldType.VECTOR,
            required=True,
            dimensions=384,
        )
        assert field.dimensions == 384

    def test_fts_source_field(self) -> None:
        """Create FTS source field."""
        field = SchemaField(
            name="content",
            field_type=FieldType.STRING,
            required=True,
            fts_source=True,
        )
        assert field.fts_source is True

    def test_empty_name_raises(self) -> None:
        """Empty field name should raise."""
        with pytest.raises(ValueError, match="cannot be empty"):
            SchemaField(name="", field_type=FieldType.STRING)

    def test_invalid_name_raises(self) -> None:
        """Invalid field name should raise."""
        with pytest.raises(ValueError, match="valid snake_case"):
            SchemaField(name="123invalid", field_type=FieldType.STRING)

    def test_valid_snake_case_names(self) -> None:
        """Valid snake_case names should work."""
        valid_names = ["id", "file_path", "_private", "test123", "a_b_c"]
        for name in valid_names:
            field = SchemaField(name=name, field_type=FieldType.STRING)
            assert field.name == name

    def test_frozen_immutable(self) -> None:
        """SchemaField should be frozen/immutable."""
        field = SchemaField(name="test", field_type=FieldType.STRING)
        with pytest.raises(AttributeError):
            field.name = "changed"  # type: ignore


# =============================================================================
# LogicalSchema Tests
# =============================================================================


class TestLogicalSchema:
    """Tests for LogicalSchema dataclass."""

    def test_basic_creation(self) -> None:
        """Create a basic schema."""
        schema = LogicalSchema(
            name="test_table",
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING),
                SchemaField(name="name", field_type=FieldType.STRING),
            ),
        )
        assert schema.name == "test_table"
        assert len(schema.fields) == 2

    def test_schema_with_fts_and_vector(self) -> None:
        """Create schema with FTS and vector columns."""
        schema = LogicalSchema(
            name="searchable",
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING),
                SchemaField(name="content", field_type=FieldType.STRING),
                SchemaField(name="vector", field_type=FieldType.VECTOR),
            ),
            fts_columns=("content",),
            vector_columns=("vector",),
        )
        assert schema.fts_columns == ("content",)
        assert schema.vector_columns == ("vector",)

    def test_empty_name_raises(self) -> None:
        """Empty schema name should raise."""
        with pytest.raises(ValueError, match="cannot be empty"):
            LogicalSchema(
                name="",
                fields=(SchemaField(name="id", field_type=FieldType.STRING),),
            )

    def test_invalid_primary_key_raises(self) -> None:
        """Primary key referencing non-existent field should raise."""
        with pytest.raises(ValueError, match="Primary key field"):
            LogicalSchema(
                name="test",
                fields=(SchemaField(name="id", field_type=FieldType.STRING),),
                primary_key=("nonexistent",),
            )

    def test_invalid_fts_column_raises(self) -> None:
        """FTS column referencing non-existent field should raise."""
        with pytest.raises(ValueError, match="FTS column"):
            LogicalSchema(
                name="test",
                fields=(SchemaField(name="id", field_type=FieldType.STRING),),
                fts_columns=("content",),
            )

    def test_invalid_vector_column_raises(self) -> None:
        """Vector column referencing non-existent field should raise."""
        with pytest.raises(ValueError, match="Vector column"):
            LogicalSchema(
                name="test",
                fields=(SchemaField(name="id", field_type=FieldType.STRING),),
                vector_columns=("vector",),
            )

    def test_vector_column_wrong_type_raises(self) -> None:
        """Vector column with non-vector type should raise."""
        with pytest.raises(ValueError, match="must have VECTOR type"):
            LogicalSchema(
                name="test",
                fields=(
                    SchemaField(name="id", field_type=FieldType.STRING),
                    SchemaField(name="vector", field_type=FieldType.STRING),
                ),
                vector_columns=("vector",),
            )

    def test_duplicate_field_names_raises(self) -> None:
        """Duplicate field names should raise."""
        with pytest.raises(ValueError, match="Duplicate"):
            LogicalSchema(
                name="test",
                fields=(
                    SchemaField(name="id", field_type=FieldType.STRING),
                    SchemaField(name="id", field_type=FieldType.STRING),
                ),
            )

    def test_get_field(self) -> None:
        """Test get_field method."""
        schema = LogicalSchema(
            name="test",
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING),
                SchemaField(name="name", field_type=FieldType.STRING),
            ),
        )
        field = schema.get_field("name")
        assert field is not None
        assert field.name == "name"
        assert schema.get_field("nonexistent") is None

    def test_get_required_fields(self) -> None:
        """Test get_required_fields method."""
        schema = LogicalSchema(
            name="test",
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING, required=True),
                SchemaField(name="opt", field_type=FieldType.STRING, required=False),
            ),
        )
        required = schema.get_required_fields()
        assert len(required) == 1
        assert required[0].name == "id"

    def test_get_optional_fields(self) -> None:
        """Test get_optional_fields method."""
        schema = LogicalSchema(
            name="test",
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING, required=True),
                SchemaField(name="opt", field_type=FieldType.STRING, required=False),
            ),
        )
        optional = schema.get_optional_fields()
        assert len(optional) == 1
        assert optional[0].name == "opt"

    def test_get_field_names(self) -> None:
        """Test get_field_names method."""
        schema = LogicalSchema(
            name="test",
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING),
                SchemaField(name="name", field_type=FieldType.STRING),
            ),
        )
        names = schema.get_field_names()
        assert names == frozenset({"id", "name"})

    def test_validate_row_valid(self) -> None:
        """Test validate_row with valid data."""
        schema = LogicalSchema(
            name="test",
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING, required=True),
                SchemaField(name="opt", field_type=FieldType.STRING, required=False),
            ),
        )
        errors = schema.validate_row({"id": "123", "opt": "value"})
        assert errors == []

    def test_validate_row_missing_required(self) -> None:
        """Test validate_row with missing required field."""
        schema = LogicalSchema(
            name="test",
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING, required=True),
            ),
        )
        errors = schema.validate_row({})
        assert len(errors) == 1
        assert "Missing required field" in errors[0]

    def test_validate_row_unknown_field(self) -> None:
        """Test validate_row with unknown field."""
        schema = LogicalSchema(
            name="test",
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING, required=True),
            ),
        )
        errors = schema.validate_row({"id": "123", "unknown": "value"})
        assert len(errors) == 1
        assert "Unknown field" in errors[0]

    def test_to_dict(self) -> None:
        """Test to_dict method."""
        schema = LogicalSchema(
            name="test",
            description="Test schema",
            fields=(
                SchemaField(
                    name="id",
                    field_type=FieldType.STRING,
                    required=True,
                    description="Primary key",
                ),
            ),
        )
        d = schema.to_dict()
        assert d["name"] == "test"
        assert d["description"] == "Test schema"
        assert len(d["fields"]) == 1
        assert d["fields"][0]["name"] == "id"
        assert d["fields"][0]["field_type"] == "string"


# =============================================================================
# Document Chunks Schema Tests
# =============================================================================


class TestDocumentChunksSchema:
    """Tests for DOCUMENT_CHUNKS_SCHEMA."""

    def test_schema_name(self) -> None:
        """Verify schema name."""
        assert DOCUMENT_CHUNKS_SCHEMA.name == "document_chunks"

    def test_required_fields(self) -> None:
        """Verify required fields exist."""
        required = {
            "id",
            "doc_id",
            "file_path",
            "project_id",
            "content",
            "fts_text",
            "vector",
            "content_type",
        }
        actual = {f.name for f in DOCUMENT_CHUNKS_SCHEMA.get_required_fields()}
        assert required == actual

    def test_fts_column(self) -> None:
        """Verify FTS column is fts_text."""
        assert DOCUMENT_CHUNKS_SCHEMA.fts_columns == ("fts_text",)

    def test_vector_column(self) -> None:
        """Verify vector column."""
        assert DOCUMENT_CHUNKS_SCHEMA.vector_columns == ("vector",)

    def test_sentinel_values(self) -> None:
        """Verify sentinel values for integer fields."""
        for field_name in ("page_number", "line_start", "line_end"):
            field = DOCUMENT_CHUNKS_SCHEMA.get_field(field_name)
            assert field is not None
            assert field.sentinel == -1


# =============================================================================
# Graph Entities Schema Tests
# =============================================================================


class TestGraphEntitiesSchema:
    """Tests for GRAPH_ENTITIES_SCHEMA."""

    def test_schema_name(self) -> None:
        """Verify schema name."""
        assert GRAPH_ENTITIES_SCHEMA.name == "graph_entities"

    def test_required_fields(self) -> None:
        """Verify required fields exist."""
        required = {
            "id",
            "name",
            "type",
            "file_path",
            "doc_id",
            "project_id",
            "vector",
            "has_ranking_signals",
        }
        actual = {f.name for f in GRAPH_ENTITIES_SCHEMA.get_required_fields()}
        assert required == actual

    def test_pagerank_field_name(self) -> None:
        """Verify pagerank field is named correctly (not page_rank)."""
        field = GRAPH_ENTITIES_SCHEMA.get_field("pagerank")
        assert field is not None
        assert field.field_type == FieldType.FLOAT

        # Ensure page_rank doesn't exist
        assert GRAPH_ENTITIES_SCHEMA.get_field("page_rank") is None


# =============================================================================
# Graph Relationships Schema Tests
# =============================================================================


class TestGraphRelationshipsSchema:
    """Tests for GRAPH_RELATIONSHIPS_SCHEMA."""

    def test_schema_name(self) -> None:
        """Verify schema name."""
        assert GRAPH_RELATIONSHIPS_SCHEMA.name == "graph_relationships"

    def test_required_fields(self) -> None:
        """Verify required fields exist."""
        required = {"id", "source_id", "target_id", "type", "project_id", "vector"}
        actual = {f.name for f in GRAPH_RELATIONSHIPS_SCHEMA.get_required_fields()}
        assert required == actual

    def test_source_target_field_names(self) -> None:
        """Verify source_id/target_id field names (not source_entity_id)."""
        assert GRAPH_RELATIONSHIPS_SCHEMA.get_field("source_id") is not None
        assert GRAPH_RELATIONSHIPS_SCHEMA.get_field("target_id") is not None
        assert GRAPH_RELATIONSHIPS_SCHEMA.get_field("source_entity_id") is None


# =============================================================================
# Memory Schema Tests
# =============================================================================


class TestMemorySchemas:
    """Tests for memory schemas."""

    def test_episodic_schema_name(self) -> None:
        """Verify episodic schema name."""
        assert MEMORY_EPISODIC_SCHEMA.name == "memory_episodic_medium"

    def test_semantic_schema_name(self) -> None:
        """Verify semantic schema name."""
        assert MEMORY_SEMANTIC_SCHEMA.name == "memory_semantic_high"

    def test_common_fields(self) -> None:
        """Both schemas should have common memory fields."""
        common_fields = {
            "id",
            "agent_id",
            "session_id",
            "conversation_id",
            "task_id",
            "project_id",
            "content",
            "summary",
            "importance",
            "tier",
            "creator_agent_id",
            "modifier_agent_id",
            "content_source",
            "created_at",
            "accessed_at",
            "modified_at",
            "access_count",
            "vector",
            "summary_vector",
            "event_type",
            "emotional_valence",
            "emotional_arousal",
            "subject",
            "relationship",
            "object",
            "confidence",
            "metadata",
        }
        for schema in (MEMORY_EPISODIC_SCHEMA, MEMORY_SEMANTIC_SCHEMA):
            actual = schema.get_field_names()
            assert common_fields.issubset(actual), f"Missing fields in {schema.name}"

    def test_fts_columns(self) -> None:
        """Both schemas should have FTS on content and summary."""
        for schema in (MEMORY_EPISODIC_SCHEMA, MEMORY_SEMANTIC_SCHEMA):
            assert "content" in schema.fts_columns
            assert "summary" in schema.fts_columns

    def test_vector_columns(self) -> None:
        """Both schemas should have vector and summary_vector."""
        for schema in (MEMORY_EPISODIC_SCHEMA, MEMORY_SEMANTIC_SCHEMA):
            assert "vector" in schema.vector_columns
            assert "summary_vector" in schema.vector_columns


# =============================================================================
# Schema Registry Tests
# =============================================================================


class TestSchemaRegistry:
    """Tests for schema registry functions."""

    def test_core_schemas_dict(self) -> None:
        """Test CORE_SCHEMAS dictionary."""
        assert "document_chunks" in CORE_SCHEMAS
        assert "graph_entities" in CORE_SCHEMAS
        assert "graph_relationships" in CORE_SCHEMAS
        assert len(CORE_SCHEMAS) == 3

    def test_memory_schemas_dict(self) -> None:
        """Test MEMORY_SCHEMAS dictionary."""
        assert "memory_episodic_medium" in MEMORY_SCHEMAS
        assert "memory_semantic_high" in MEMORY_SCHEMAS
        assert len(MEMORY_SCHEMAS) == 2

    def test_all_schemas_dict(self) -> None:
        """Test ALL_SCHEMAS dictionary."""
        assert len(ALL_SCHEMAS) == 5
        assert "document_chunks" in ALL_SCHEMAS
        assert "memory_episodic_medium" in ALL_SCHEMAS

    def test_get_core_schema(self) -> None:
        """Test get_core_schema function."""
        schema = get_core_schema("document_chunks")
        assert schema is DOCUMENT_CHUNKS_SCHEMA

    def test_get_core_schema_not_found(self) -> None:
        """Test get_core_schema with unknown name."""
        with pytest.raises(KeyError, match="Unknown core schema"):
            get_core_schema("nonexistent")

    def test_get_memory_schema(self) -> None:
        """Test get_memory_schema function."""
        schema = get_memory_schema("memory_episodic_medium")
        assert schema is MEMORY_EPISODIC_SCHEMA

    def test_get_memory_schema_not_found(self) -> None:
        """Test get_memory_schema with unknown name."""
        with pytest.raises(KeyError, match="Unknown memory schema"):
            get_memory_schema("nonexistent")

    def test_get_schema_core(self) -> None:
        """Test get_schema with core schema."""
        schema = get_schema("document_chunks")
        assert schema is DOCUMENT_CHUNKS_SCHEMA

    def test_get_schema_memory(self) -> None:
        """Test get_schema with memory schema."""
        schema = get_schema("memory_semantic_high")
        assert schema is MEMORY_SEMANTIC_SCHEMA

    def test_get_schema_not_found(self) -> None:
        """Test get_schema with unknown name."""
        with pytest.raises(KeyError, match="Unknown schema"):
            get_schema("nonexistent")
