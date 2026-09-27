"""Tests for SchemaProcessor with logical schema support.

These tests verify:
- SchemaProcessor uses DOCUMENT_CHUNKS_SCHEMA by default
- Custom schemas can be passed to SchemaProcessor
- Schema-driven validation, transformation, and sanitization work correctly
"""

import pytest

pytestmark = pytest.mark.unit
from datetime import datetime
from unittest.mock import MagicMock

from agentic_inquiry.database.schemas import (
    DOCUMENT_CHUNKS_SCHEMA,
    FieldType,
    LogicalSchema,
    SchemaField,
)
from agentic_inquiry.indexing.schema_processor import SchemaProcessor, ValidationError
from agentic_inquiry.parsers.models import ParserChunk, ParsedDocument


class TestSchemaProcessorInitialization:
    """Tests for SchemaProcessor initialization with schema parameter."""

    def test_default_schema_is_document_chunks(self):
        """Verify SchemaProcessor uses DOCUMENT_CHUNKS_SCHEMA by default."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        assert processor.schema == DOCUMENT_CHUNKS_SCHEMA
        assert processor.schema.name == "document_chunks"

    def test_custom_schema_accepted(self):
        """Verify custom LogicalSchema can be passed to SchemaProcessor."""
        mock_db = MagicMock()

        # Create a minimal custom schema
        custom_schema = LogicalSchema(
            name="custom_test_schema",
            primary_key=("id",),
            fts_columns=(),
            vector_columns=(),
            fields=(
                SchemaField(name="id", field_type=FieldType.STRING, required=True),
                SchemaField(name="content", field_type=FieldType.STRING, required=True),
            ),
        )

        processor = SchemaProcessor(mock_db, schema=custom_schema)

        assert processor.schema == custom_schema
        assert processor.schema.name == "custom_test_schema"

    def test_field_mappings_built_from_schema(self):
        """Verify field mappings are built from the logical schema."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        # Check that field mappings contain all schema fields
        assert len(processor._field_mappings) == len(DOCUMENT_CHUNKS_SCHEMA.fields)

        # Verify some specific fields are present
        assert "id" in processor._field_mappings
        assert "content" in processor._field_mappings
        assert "vector" in processor._field_mappings
        assert "project_id" in processor._field_mappings

    def test_validation_rules_built_from_schema(self):
        """Verify validation rules are built from the logical schema."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        # Check that validation rules contain all schema fields
        assert len(processor._validation_rules) == len(DOCUMENT_CHUNKS_SCHEMA.fields)

        # Verify structure of a validation rule
        id_rule = processor._validation_rules.get("id")
        assert id_rule is not None
        assert "required" in id_rule
        assert "field_type" in id_rule
        assert "sentinel" in id_rule
        assert "default" in id_rule


class TestSchemaProcessorHelpers:
    """Tests for SchemaProcessor helper methods."""

    def test_get_required_field_names(self):
        """Verify _get_required_field_names returns correct fields."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        required = processor._get_required_field_names()

        # Check it returns a FrozenSet
        assert isinstance(required, frozenset)

        # Check required fields are present
        assert "id" in required
        assert "doc_id" in required
        assert "content" in required
        assert "vector" in required
        assert "project_id" in required

    def test_get_optional_field_names(self):
        """Verify _get_optional_field_names returns correct fields."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        optional = processor._get_optional_field_names()

        # Check it returns a FrozenSet
        assert isinstance(optional, frozenset)

        # Optional fields should include things like page_number, line_start
        # (these have sentinel values in the schema)
        assert len(optional) > 0

    def test_get_type_default_string(self):
        """Verify default for STRING type is empty string."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        assert processor._get_type_default(FieldType.STRING) == ""

    def test_get_type_default_int(self):
        """Verify default for INT type is -1."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        assert processor._get_type_default(FieldType.INT) == -1

    def test_get_type_default_vector(self):
        """Verify default for VECTOR type is empty list."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        assert processor._get_type_default(FieldType.VECTOR) == []

    def test_get_type_default_datetime(self):
        """Verify default for DATETIME type is ISO format string."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        default = processor._get_type_default(FieldType.DATETIME)

        # Should be a valid ISO datetime string
        assert isinstance(default, str)
        # Should be parseable as datetime
        datetime.fromisoformat(default)


class TestChunkValidation:
    """Tests for chunk validation using schema rules."""

    def test_valid_chunk_passes_validation(self):
        """Verify a valid chunk passes validation."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        chunk = ParserChunk(
            content="Test content",
            metadata={"key": "value"},
        )

        # Should not raise
        processor._validate_chunk(chunk)

    def test_empty_content_fails_validation(self):
        """Verify chunk with no content or fts_text fails validation."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        chunk = ParserChunk(
            content="",
            fts_text="",
        )

        with pytest.raises(ValidationError, match="content or fts_text"):
            processor._validate_chunk(chunk)

    def test_complex_metadata_accepted_by_pydantic(self):
        """Verify ParserChunk accepts complex metadata types.

        ParserChunk now allows lists and dicts in metadata, relying on JSON serialization
        at the storage layer. This test verifies lists are accepted.
        """
        # List in metadata should NOT fail
        chunk = ParserChunk(
            content="Test content",
            metadata={"list_field": [1, 2, 3]},
        )
        assert chunk.metadata["list_field"] == [1, 2, 3]

    def test_dict_metadata_accepted_by_pydantic(self):
        """Verify ParserChunk accepts nested dict metadata.

        ParserChunk now allows lists and dicts in metadata, relying on JSON serialization
        at the storage layer. This test verifies nested dicts are accepted.
        """
        # Dict in metadata should NOT fail
        chunk = ParserChunk(
            content="Test content",
            metadata={"nested": {"key": "value"}},
        )
        assert chunk.metadata["nested"]["key"] == "value"

    def test_invalid_line_range_fails_validation(self):
        """Verify chunk with line_start > line_end fails validation."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        chunk = ParserChunk(
            content="Test content",
            line_start=100,
            line_end=50,
        )

        with pytest.raises(ValidationError, match="Invalid line range"):
            processor._validate_chunk(chunk)


class TestSanitizeMetadata:
    """Tests for schema-driven metadata sanitization."""

    def test_sanitize_adds_missing_fields(self):
        """Verify sanitization adds missing fields with schema defaults."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        # Minimal record
        record = {"id": "test_id"}

        sanitized = processor._sanitize_metadata(record)

        # Should have added fields from schema
        assert "content" in sanitized
        assert "project_id" in sanitized
        assert "vector" in sanitized

    def test_sanitize_uses_sentinel_values(self):
        """Verify sanitization uses sentinel values from schema."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        # Record missing page_number (which has sentinel -1)
        record = {"id": "test_id", "content": "test"}

        sanitized = processor._sanitize_metadata(record)

        # page_number should be -1 (sentinel value from schema)
        assert sanitized.get("page_number") == -1
        assert sanitized.get("line_start") == -1
        assert sanitized.get("line_end") == -1

    def test_sanitize_preserves_existing_values(self):
        """Verify sanitization preserves existing record values."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        record = {
            "id": "test_123",
            "content": "Existing content",
            "page_number": 42,
        }

        sanitized = processor._sanitize_metadata(record)

        # Existing values should be preserved
        assert sanitized["id"] == "test_123"
        assert sanitized["content"] == "Existing content"
        assert sanitized["page_number"] == 42

    def test_sanitize_fixes_invalid_struct_fields(self):
        """Verify sanitization fixes non-dict metadata and ranking_signals."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        record = {
            "id": "test_id",
            "metadata": "not_a_dict",
            "ranking_signals": "also_not_a_dict",
        }

        sanitized = processor._sanitize_metadata(record)

        # Should be converted to proper dict structure
        assert isinstance(sanitized["metadata"], dict)
        assert "data" in sanitized["metadata"]
        assert isinstance(sanitized["ranking_signals"], dict)
        assert "data" in sanitized["ranking_signals"]


class TestTransformChunk:
    """Tests for chunk transformation using schema definitions."""

    def test_transform_creates_valid_record(self):
        """Verify transformation creates a valid database record."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        chunk = ParserChunk(
            content="Test content for embedding",
            language="python",
            symbols=["test_func"],
            page_number=1,
            line_start=10,
            line_end=20,
        )

        parsed_doc = ParsedDocument(
            doc_id="doc_123",
            file_path="/path/to/file.py",
            chunks=[chunk],
        )

        vector = [0.1] * 384  # Sample embedding vector

        record = processor._transform_chunk(
            chunk=chunk,
            parsed_document=parsed_doc,
            chunk_index=0,
            total_chunks=1,
            vector=vector,
            project_id="test_project",
        )

        # Check required fields - ID now includes project_id prefix
        assert record["id"] == "test_project::doc_123_0"
        assert record["doc_id"] == "doc_123"
        assert record["file_path"] == "/path/to/file.py"
        assert record["project_id"] == "test_project"
        assert record["content"] == "Test content for embedding"
        assert record["language"] == "python"
        assert record["vector"] == vector
        assert record["page_number"] == 1
        assert record["line_start"] == 10
        assert record["line_end"] == 20
        assert record["symbols"] == ["test_func"]

    def test_transform_handles_missing_optional_fields(self):
        """Verify transformation handles missing optional fields gracefully."""
        mock_db = MagicMock()
        processor = SchemaProcessor(mock_db)

        chunk = ParserChunk(
            content="Minimal content",
        )

        parsed_doc = ParsedDocument(
            doc_id="doc_456",
            file_path="/path/to/file.txt",
            chunks=[chunk],
        )

        vector = [0.1] * 384

        record = processor._transform_chunk(
            chunk=chunk,
            parsed_document=parsed_doc,
            chunk_index=0,
            total_chunks=1,
            vector=vector,
            project_id="test_project",
        )

        # Optional fields should have sentinel/default values
        assert record["page_number"] == -1
        assert record["line_start"] == -1
        assert record["line_end"] == -1
        assert record["symbols"] == []
        assert record["parent_id"] == ""
        assert record["child_ids"] == []
