import pytest

pytestmark = pytest.mark.unit

import unittest
from datetime import datetime, timezone
import json

from agentic_inquiry.models import DocumentChunk, GraphEntity, GraphRelationship
from agentic_inquiry.models.graph_relationship import (
    RelationshipType,
    get_inverse_relationship,
    INVERSE_RELATIONSHIPS,
    CodeRelationshipMetadata,
    DocumentationRelationshipMetadata,
    TemporalRelationshipMetadata,
    SemanticRelationshipMetadata,
    validate_relationship_metadata,
    parse_relationship_metadata,
)
from agentic_inquiry.config import VECTOR_DIMENSION


class TestDataModels(unittest.TestCase):
    def test_document_chunk_creation(self):
        """Test that a DocumentChunk can be created with valid data."""
        chunk = DocumentChunk(
            id="doc_abc123_0",
            doc_id="doc_abc123",
            file_path="src/services/search.py",
            project_id="proj_123",
            content="class SearchService:...",
            fts_text="class SearchService",
            vector=[0.1] * VECTOR_DIMENSION,
            content_type="CODE",
            language="python",
            element_type="class",
            element_name="SearchService",
            page_number=5,
            line_start=1,
            line_end=20,
            chunk_index=0,
            total_chunks=2,
            indexed_at=datetime.now(timezone.utc),
            source_modified_at=datetime.now(timezone.utc),
            metadata={"module": "services.search"},
            ranking_signals={"importance": 0.75},
        )
        self.assertEqual(chunk.id, "doc_abc123_0")
        self.assertEqual(chunk.language, "python")
        self.assertEqual(chunk.metadata["module"], "services.search")
        self.assertAlmostEqual(chunk.ranking_signals["importance"], 0.75)
        self.assertEqual(chunk.project_id, "proj_123")
        serialised = chunk.to_dict()
        self.assertIsInstance(serialised["indexed_at"], str)
        self.assertIsInstance(serialised["source_modified_at"], str)

    def test_graph_entity_creation(self):
        """Test that a GraphEntity can be created with valid data."""
        entity = GraphEntity(
            id="class::abcdef::src/search.py::SearchService",
            name="SearchService",
            type="class",
            file_path="src/services/search.py",
            doc_id="doc_abc123",
            project_id="proj_123",
            vector=[0.4] * VECTOR_DIMENSION,
            pagerank=0.85,
        )
        self.assertEqual(entity.name, "SearchService")
        self.assertEqual(entity.pagerank, 0.85)
        self.assertEqual(entity.project_id, "proj_123")

    def test_graph_relationship_creation(self):
        """Test that a GraphRelationship can be created with valid data."""
        import json

        relationship = GraphRelationship(
            id="edge_xyz789",
            source_id="class::abcdef::src/search.py::SearchService",
            target_id="class::abcdef::src/storage.py::VectorStore",
            type="calls",
            project_id="proj_123",
            vector=[0.0] * VECTOR_DIMENSION,
            metadata=json.dumps({"line_number": 42}),
        )
        self.assertEqual(relationship.type, "calls")
        self.assertEqual(json.loads(relationship.metadata)["line_number"], 42)
        self.assertEqual(relationship.project_id, "proj_123")


class TestRelationshipOntology(unittest.TestCase):
    """Test the relationship type ontology and inverse mappings."""

    def test_relationship_type_enum_values(self):
        """Test that all relationship types have correct string values."""
        self.assertEqual(RelationshipType.CALLS.value, "calls")
        self.assertEqual(RelationshipType.CALLED_BY.value, "called_by")
        self.assertEqual(RelationshipType.IMPORTS.value, "imports")
        self.assertEqual(RelationshipType.DOCUMENTS.value, "documents")
        self.assertEqual(RelationshipType.TESTS.value, "tests")

    def test_inverse_relationships_completeness(self):
        """Test that all relationship types have inverse mappings."""
        for rel_type in RelationshipType:
            self.assertIn(
                rel_type,
                INVERSE_RELATIONSHIPS,
                f"{rel_type} missing from INVERSE_RELATIONSHIPS",
            )

    def test_inverse_relationships_symmetry(self):
        """Test that inverse relationships are symmetric (A->B implies B->A)."""
        for rel_type, inverse in INVERSE_RELATIONSHIPS.items():
            # The inverse of the inverse should be the original
            inverse_of_inverse = INVERSE_RELATIONSHIPS[inverse]
            self.assertEqual(
                rel_type,
                inverse_of_inverse,
                f"Inverse symmetry broken for {rel_type} <-> {inverse}",
            )

    def test_get_inverse_relationship(self):
        """Test the get_inverse_relationship helper function."""
        self.assertEqual(
            get_inverse_relationship(RelationshipType.CALLS), RelationshipType.CALLED_BY
        )
        self.assertEqual(
            get_inverse_relationship(RelationshipType.IMPORTS),
            RelationshipType.IMPORTED_BY,
        )
        self.assertEqual(
            get_inverse_relationship(RelationshipType.SIMILAR_TO),
            RelationshipType.SIMILAR_TO,  # Symmetric
        )

    def test_symmetric_relationships(self):
        """Test that symmetric relationships are their own inverse."""
        symmetric_types = [RelationshipType.SIMILAR_TO, RelationshipType.UNKNOWN]
        for rel_type in symmetric_types:
            self.assertEqual(
                get_inverse_relationship(rel_type),
                rel_type,
                f"{rel_type} should be symmetric",
            )


class TestRelationshipMetadataValidation(unittest.TestCase):
    """Test relationship metadata schemas and validation."""

    def test_code_relationship_metadata(self):
        """Test CodeRelationshipMetadata creation and serialization."""
        metadata = CodeRelationshipMetadata(
            line_number=42,
            column_number=10,
            file_path="src/main.py",
            context="def foo():",
            language="python",
        )

        metadata_dict = metadata.to_dict()
        self.assertEqual(metadata_dict["line_number"], 42)
        self.assertEqual(metadata_dict["file_path"], "src/main.py")
        self.assertEqual(metadata_dict["language"], "python")

    def test_code_relationship_metadata_excludes_none(self):
        """Test that None values are excluded from to_dict()."""
        metadata = CodeRelationshipMetadata(line_number=42, file_path="src/main.py")

        metadata_dict = metadata.to_dict()
        self.assertIn("line_number", metadata_dict)
        self.assertIn("file_path", metadata_dict)
        self.assertNotIn("column_number", metadata_dict)
        self.assertNotIn("context", metadata_dict)

    def test_documentation_relationship_metadata(self):
        """Test DocumentationRelationshipMetadata."""
        metadata = DocumentationRelationshipMetadata(
            section="API Reference", page_number=5, format="markdown"
        )

        metadata_dict = metadata.to_dict()
        self.assertEqual(metadata_dict["section"], "API Reference")
        self.assertEqual(metadata_dict["page_number"], 5)

    def test_temporal_relationship_metadata(self):
        """Test TemporalRelationshipMetadata."""
        metadata = TemporalRelationshipMetadata(
            timestamp="2024-01-01T00:00:00Z", version="1.0.0", commit_hash="abc123"
        )

        metadata_dict = metadata.to_dict()
        self.assertEqual(metadata_dict["version"], "1.0.0")
        self.assertEqual(metadata_dict["commit_hash"], "abc123")

    def test_test_relationship_metadata(self):
        """Test TestRelationshipMetadata."""
        from agentic_inquiry.models.graph_relationship import (
            TestRelationshipMetadata as TestMeta,
        )

        metadata = TestMeta(
            test_type="unit", coverage_percentage=85.5, test_framework="pytest"
        )

        metadata_dict = metadata.to_dict()
        self.assertEqual(metadata_dict["test_type"], "unit")
        self.assertAlmostEqual(metadata_dict["coverage_percentage"], 85.5)

    def test_semantic_relationship_metadata(self):
        """Test SemanticRelationshipMetadata."""
        metadata = SemanticRelationshipMetadata(
            similarity_score=0.85,
            confidence=0.9,
            reasoning="Both functions handle authentication",
        )

        metadata_dict = metadata.to_dict()
        self.assertAlmostEqual(metadata_dict["similarity_score"], 0.85)
        self.assertAlmostEqual(metadata_dict["confidence"], 0.9)


class TestMetadataValidation(unittest.TestCase):
    """Test metadata validation functions."""

    def test_validate_code_relationship_metadata(self):
        """Test validation of code relationship metadata."""
        metadata = {"line_number": 42, "file_path": "src/main.py", "language": "python"}

        validated = validate_relationship_metadata(RelationshipType.CALLS, metadata)

        self.assertIsNotNone(validated)
        parsed = json.loads(validated)
        self.assertEqual(parsed["line_number"], 42)
        self.assertEqual(parsed["file_path"], "src/main.py")

    def test_validate_metadata_with_json_string(self):
        """Test validation with JSON string input."""
        metadata_str = json.dumps({"line_number": 42, "file_path": "src/main.py"})

        validated = validate_relationship_metadata(RelationshipType.CALLS, metadata_str)

        self.assertIsNotNone(validated)
        parsed = json.loads(validated)
        self.assertEqual(parsed["line_number"], 42)

    def test_validate_metadata_invalid_fields(self):
        """Test that invalid fields are rejected."""
        metadata = {"line_number": 42, "invalid_field": "should fail"}

        with self.assertRaises(ValueError) as context:
            validate_relationship_metadata(RelationshipType.CALLS, metadata)

        self.assertIn("Invalid metadata fields", str(context.exception))

    def test_validate_metadata_none(self):
        """Test that None metadata is allowed."""
        validated = validate_relationship_metadata(RelationshipType.CALLS, None)
        self.assertIsNone(validated)

    def test_parse_relationship_metadata(self):
        """Test parsing metadata into typed objects."""
        metadata_str = json.dumps({"line_number": 42, "file_path": "src/main.py"})

        parsed = parse_relationship_metadata(RelationshipType.CALLS, metadata_str)

        self.assertIsInstance(parsed, CodeRelationshipMetadata)
        self.assertEqual(parsed.line_number, 42)
        self.assertEqual(parsed.file_path, "src/main.py")

    def test_parse_metadata_unknown_type(self):
        """Test parsing metadata for unknown relationship type."""
        metadata_str = json.dumps({"custom": "value"})

        parsed = parse_relationship_metadata(RelationshipType.UNKNOWN, metadata_str)

        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["custom"], "value")


class TestGraphRelationshipWithOntology(unittest.TestCase):
    """Test GraphRelationship integration with relationship ontology."""

    def test_create_relationship_with_valid_type(self):
        """Test creating a relationship with a valid relationship type."""
        relationship = GraphRelationship(
            id="edge_1",
            source_id="entity_a",
            target_id="entity_b",
            type=RelationshipType.CALLS.value,
            project_id="proj_1",
            vector=[0.1] * VECTOR_DIMENSION,
            metadata=json.dumps({"line_number": 42}),
        )

        self.assertEqual(relationship.type, "calls")
        self.assertIsNotNone(relationship.metadata)

    def test_create_relationship_validates_metadata(self):
        """Test that relationship creation validates metadata."""
        # Valid metadata should work
        relationship = GraphRelationship(
            id="edge_1",
            source_id="entity_a",
            target_id="entity_b",
            type=RelationshipType.CALLS.value,
            project_id="proj_1",
            vector=[0.1] * VECTOR_DIMENSION,
            metadata=json.dumps({"line_number": 42, "file_path": "main.py"}),
        )

        self.assertIsNotNone(relationship.metadata)

    def test_create_relationship_rejects_invalid_metadata(self):
        """Test that invalid metadata is rejected for known relationship types."""
        # This should raise ValueError because "invalid_field" is not valid for CALLS
        with self.assertRaises(ValueError) as context:
            GraphRelationship(
                id="edge_1",
                source_id="entity_a",
                target_id="entity_b",
                type=RelationshipType.CALLS.value,
                project_id="proj_1",
                vector=[0.1] * VECTOR_DIMENSION,
                metadata=json.dumps({"invalid_field": "bad"}),
            )

        self.assertIn("Invalid metadata fields", str(context.exception))

    def test_get_typed_metadata(self):
        """Test getting typed metadata from relationship."""
        relationship = GraphRelationship(
            id="edge_1",
            source_id="entity_a",
            target_id="entity_b",
            type=RelationshipType.CALLS.value,
            project_id="proj_1",
            vector=[0.1] * VECTOR_DIMENSION,
            metadata=json.dumps({"line_number": 42, "file_path": "main.py"}),
        )

        typed_metadata = relationship.get_typed_metadata()
        self.assertIsInstance(typed_metadata, CodeRelationshipMetadata)
        self.assertEqual(typed_metadata.line_number, 42)
        self.assertEqual(typed_metadata.file_path, "main.py")

    def test_set_typed_metadata(self):
        """Test setting typed metadata on relationship."""
        relationship = GraphRelationship(
            id="edge_1",
            source_id="entity_a",
            target_id="entity_b",
            type=RelationshipType.CALLS.value,
            project_id="proj_1",
            vector=[0.1] * VECTOR_DIMENSION,
        )

        metadata = CodeRelationshipMetadata(
            line_number=100, file_path="test.py", language="python"
        )

        relationship.set_typed_metadata(metadata)

        self.assertIsNotNone(relationship.metadata)
        parsed = json.loads(relationship.metadata)
        self.assertEqual(parsed["line_number"], 100)
        self.assertEqual(parsed["file_path"], "test.py")

    def test_get_inverse(self):
        """Test getting inverse relationship type."""
        relationship = GraphRelationship(
            id="edge_1",
            source_id="entity_a",
            target_id="entity_b",
            type=RelationshipType.CALLS.value,
            project_id="proj_1",
            vector=[0.1] * VECTOR_DIMENSION,
        )

        inverse = relationship.get_inverse()
        self.assertEqual(inverse, RelationshipType.CALLED_BY)

    def test_relationship_with_unknown_type(self):
        """Test that unknown relationship types are allowed."""
        relationship = GraphRelationship(
            id="edge_1",
            source_id="entity_a",
            target_id="entity_b",
            type="custom_relationship",
            project_id="proj_1",
            vector=[0.1] * VECTOR_DIMENSION,
            metadata=json.dumps({"custom": "data"}),
        )

        self.assertEqual(relationship.type, "custom_relationship")
        self.assertEqual(relationship.get_inverse(), RelationshipType.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
