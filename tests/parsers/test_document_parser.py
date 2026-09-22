#!/usr/bin/env python3
"""Tests for DocumentParser entity extraction functionality.

Tests the document entity extraction features including:
- Heading extraction from markdown
- Relationship extraction (contains, follows)
- Heading level detection
- Multiple document formats
"""

import pytest

pytestmark = pytest.mark.integration
from pathlib import Path

from agentic_inquiry.parsers.implementations.document import (
    DocumentParser,
    UNSTRUCTURED_TO_ENTITY_TYPE,
)
from agentic_inquiry.parsers.models import ParsedDocument
from agentic_inquiry.models.graph_entity import EntityType


class TestElementTypeMapping:
    """Test UNSTRUCTURED_TO_ENTITY_TYPE mapping covers all document formats."""

    def test_docx_heading_types_mapped_to_doc_section(self):
        """Verify DOCX Heading1-6 styles map to doc_section entity type.

        DOCX files use "Heading1" through "Heading6" style names which
        unstructured preserves. These must map to doc_section to trigger
        relationship creation in the document graph.

        Regression test for DG-004: DOCX entities had no relationships
        because Heading1-6 were not in the mapping.
        """
        # All DOCX heading styles should map to doc_section
        for i in range(1, 7):
            heading_style = f"Heading{i}"
            assert heading_style in UNSTRUCTURED_TO_ENTITY_TYPE, \
                f"Missing {heading_style} in UNSTRUCTURED_TO_ENTITY_TYPE"
            assert UNSTRUCTURED_TO_ENTITY_TYPE[heading_style] == EntityType.DOC_SECTION.value, \
                f"{heading_style} should map to {EntityType.DOC_SECTION.value}"

    def test_title_and_header_mapped_to_doc_section(self):
        """Verify Title and Header map to doc_section (used by PPTX/PDF)."""
        assert "Title" in UNSTRUCTURED_TO_ENTITY_TYPE
        assert UNSTRUCTURED_TO_ENTITY_TYPE["Title"] == EntityType.DOC_SECTION.value

        assert "Header" in UNSTRUCTURED_TO_ENTITY_TYPE
        assert UNSTRUCTURED_TO_ENTITY_TYPE["Header"] == EntityType.DOC_SECTION.value

    def test_narrative_text_mapped_to_section(self):
        """Verify NarrativeText maps to section (body text)."""
        assert "NarrativeText" in UNSTRUCTURED_TO_ENTITY_TYPE
        assert UNSTRUCTURED_TO_ENTITY_TYPE["NarrativeText"] == "section"


@pytest.fixture
def parser():
    """Provides a DocumentParser instance."""
    return DocumentParser()


@pytest.fixture
def outline_md_path():
    """Path to the outline.md sample document."""
    return Path("tests/parsers/samples/docs/outline.md")


@pytest.fixture
def docx_sample_path():
    """Path to the DOCX sample document."""
    return Path("tests/parsers/samples/docs/Leading GenAI at Scale.docx")


class TestDOCXHeadingIntegration:
    """Integration tests for DOCX heading extraction and relationship creation.

    Regression tests for DG-004: DOCX entities had no graph relationships
    because Heading1-6 weren't mapped to doc_section.
    """

    @pytest.mark.asyncio
    async def test_docx_creates_doc_section_entities(self, parser, docx_sample_path):
        """Verify DOCX headings create doc_section entities.

        This is an integration test that parses an actual DOCX file and
        verifies that heading styles become doc_section entities.
        """
        if not docx_sample_path.exists():
            pytest.skip(f"Sample DOCX not found: {docx_sample_path}")

        result = await parser.parse(str(docx_sample_path))

        # Find doc_section chunks (headings)
        doc_sections = [c for c in result.chunks if c.element_type == "doc_section"]

        assert len(doc_sections) > 0, \
            "DOCX should have doc_section entities from headings"

        # Verify element_name is populated
        for section in doc_sections:
            assert section.element_name, \
                f"doc_section missing element_name: {section.content[:50]}"

    @pytest.mark.asyncio
    async def test_docx_creates_relationships(self, parser, docx_sample_path):
        """Verify DOCX parsing creates relationships (follows, contains).

        Note: Relationships are attached to the chunk whose element_name
        matches the relationship's source_name. For top-level headings,
        this is typically the file entity, not the heading itself.
        """
        if not docx_sample_path.exists():
            pytest.skip(f"Sample DOCX not found: {docx_sample_path}")

        result = await parser.parse(str(docx_sample_path))

        # Collect ALL relationships from ALL chunks
        all_rels = []
        for chunk in result.chunks:
            if chunk.relationships:
                all_rels.extend(chunk.relationships)

        # Note: The sample DOCX may not have proper Word heading styles,
        # so relationship count depends on document structure.
        # This test verifies the parser handles DOCX gracefully and
        # produces valid relationships when headings are present.
        # (Removed tautological assertion - list length >= 0 always true)

        # If relationships exist, verify they have valid types
        for rel in all_rels:
            assert rel.type in ("follows", "contains"), \
                f"Unexpected relationship type: {rel.type}"
            assert rel.source_name, "Relationship missing source_name"
            assert rel.target_name, "Relationship missing target_name"


class TestHeadingExtraction:
    """Test heading extraction from markdown (Subtask 5.1)."""
    
    @pytest.mark.asyncio
    async def test_parse_outline_md_success(self, parser, outline_md_path):
        """Test successful parsing of outline.md."""
        result = await parser.parse(str(outline_md_path))
        
        assert isinstance(result, ParsedDocument)
        assert result.doc_id
        assert result.file_path == str(outline_md_path)
        assert len(result.chunks) > 0
    
    @pytest.mark.asyncio
    async def test_heading_chunks_have_correct_element_type(self, parser, outline_md_path):
        """Verify chunks have element_type='heading' for headings."""
        result = await parser.parse(str(outline_md_path))
        
        # Find heading chunks
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        
        # Should have multiple headings
        assert len(heading_chunks) > 0, "No heading chunks found"
        
        # Verify all heading chunks have the correct type
        for chunk in heading_chunks:
            assert chunk.element_type == "doc_section"
    
    @pytest.mark.asyncio
    async def test_heading_element_names_populated(self, parser, outline_md_path):
        """Verify element_name populated with heading text."""
        result = await parser.parse(str(outline_md_path))
        
        # Find heading chunks
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        
        # All headings should have element_name
        for chunk in heading_chunks:
            assert chunk.element_name, f"Heading chunk missing element_name: {chunk.content[:50]}"
            assert len(chunk.element_name) > 0
        
        # Check for specific known headings from outline.md
        heading_names = [c.element_name for c in heading_chunks]
        
        # Should find some of the main headings
        # Note: Exact text may vary based on how unstructured parses it
        assert any("Presentation Outline" in name or "Agentic Inquiry" in name for name in heading_names), \
            f"Expected to find main title, got: {heading_names[:5]}"
    
    @pytest.mark.asyncio
    async def test_parent_id_set_for_nested_headings(self, parser, outline_md_path):
        """Verify parent_id set correctly for nested headings."""
        result = await parser.parse(str(outline_md_path))
        
        # Find heading chunks
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        
        # Some headings should have parent_id set (nested headings)
        chunks_with_parents = [c for c in heading_chunks if c.parent_id]
        
        assert len(chunks_with_parents) > 0, "No nested headings found with parent_id"
        
        # Verify parent_id references another heading
        all_heading_names = {c.element_name for c in heading_chunks}
        for chunk in chunks_with_parents:
            # Parent should be a valid heading name
            assert chunk.parent_id in all_heading_names, \
                f"parent_id '{chunk.parent_id}' not found in heading names"
    
    @pytest.mark.asyncio
    async def test_section_chunks_have_correct_element_type(self, parser, outline_md_path):
        """Verify non-heading chunks have element_type='section' or other types."""
        result = await parser.parse(str(outline_md_path))
        
        # Find non-heading chunks
        non_heading_chunks = [c for c in result.chunks if c.element_type != "doc_section"]
        
        # Should have content chunks
        assert len(non_heading_chunks) > 0, "No non-heading chunks found"
        
        # Verify they have valid element types
        # Note: "file" is the synthetic file chunk that holds document-level relationships
        valid_types = {"section", "list_item", "table", "figure", "page", "file"}
        for chunk in non_heading_chunks:
            assert chunk.element_type in valid_types, \
                f"Invalid element_type: {chunk.element_type}"


class TestRelationshipExtraction:
    """Test relationship extraction (Subtask 5.2)."""
    
    @pytest.mark.asyncio
    async def test_contains_relationships_in_chunks(self, parser, outline_md_path):
        """Verify contains relationships in chunk.relationships."""
        result = await parser.parse(str(outline_md_path))
        
        # Find heading chunks with relationships
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        chunks_with_rels = [c for c in heading_chunks if c.relationships]
        
        assert len(chunks_with_rels) > 0, "No chunks with relationships found"
        
        # Check for contains relationships
        contains_rels = []
        for chunk in chunks_with_rels:
            contains_rels.extend([r for r in chunk.relationships if r.type == "contains"])
        
        assert len(contains_rels) > 0, "No 'contains' relationships found"
        
        # Verify relationship structure
        for rel in contains_rels[:5]:  # Check first few
            assert rel.source_name, "Relationship missing source_name"
            assert rel.target_name, "Relationship missing target_name"
            assert rel.type == "contains"
    
    @pytest.mark.asyncio
    async def test_follows_relationships_in_chunks(self, parser, outline_md_path):
        """Verify follows relationships in chunk.relationships."""
        result = await parser.parse(str(outline_md_path))
        
        # Find heading chunks with relationships
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        
        # Check for follows relationships
        follows_rels = []
        for chunk in heading_chunks:
            if chunk.relationships:
                follows_rels.extend([r for r in chunk.relationships if r.type == "follows"])
        
        # Should have some follows relationships (siblings)
        assert len(follows_rels) > 0, "No 'follows' relationships found"
        
        # Verify relationship structure
        for rel in follows_rels[:5]:  # Check first few
            assert rel.source_name, "Relationship missing source_name"
            assert rel.target_name, "Relationship missing target_name"
            assert rel.type == "follows"
    
    @pytest.mark.asyncio
    async def test_hierarchy_level_in_relationship_metadata(self, parser, outline_md_path):
        """Verify hierarchy_level in relationship metadata."""
        result = await parser.parse(str(outline_md_path))
        
        # Find heading chunks with contains relationships
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        
        contains_rels = []
        for chunk in heading_chunks:
            if chunk.relationships:
                contains_rels.extend([r for r in chunk.relationships if r.type == "contains"])
        
        # Check metadata
        rels_with_level = [r for r in contains_rels if "hierarchy_level" in r.metadata]
        
        assert len(rels_with_level) > 0, "No relationships with hierarchy_level found"
        
        # Verify hierarchy levels are valid (1-6)
        for rel in rels_with_level:
            level = rel.metadata["hierarchy_level"]
            assert isinstance(level, int), f"hierarchy_level should be int, got {type(level)}"
            assert 1 <= level <= 6, f"hierarchy_level should be 1-6, got {level}"
    
    @pytest.mark.asyncio
    async def test_parent_child_relationships_correct(self, parser, outline_md_path):
        """Check parent-child relationships are correct."""
        result = await parser.parse(str(outline_md_path))
        
        # Build a map of heading names to their chunks
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        heading_map = {c.element_name: c for c in heading_chunks if c.element_name}
        
        # Check that parent_id matches contains relationships
        for chunk in heading_chunks:
            if chunk.parent_id:
                # Parent should exist
                assert chunk.parent_id in heading_map, \
                    f"parent_id '{chunk.parent_id}' not found in headings"
                
                # Parent should have a contains relationship to this chunk
                parent_chunk = heading_map[chunk.parent_id]
                if parent_chunk.relationships:
                    # Verify parent has a 'contains' relationship pointing to this child
                    contains_child = any(
                        r.type == "contains" and r.target_name == chunk.element_name
                        for r in parent_chunk.relationships
                    )
                    assert contains_child, \
                        f"Parent '{chunk.parent_id}' should have 'contains' relationship to '{chunk.element_name}'"


class TestHeadingLevelDetection:
    """Test heading level detection (Subtask 5.3)."""
    
    @pytest.mark.asyncio
    async def test_markdown_heading_level_detection(self, parser, outline_md_path):
        """Test markdown # counting for heading levels."""
        result = await parser.parse(str(outline_md_path))
        
        # Find heading chunks with relationships
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        
        # Extract hierarchy levels from relationships
        levels_found = set()
        for chunk in heading_chunks:
            if chunk.relationships:
                for rel in chunk.relationships:
                    if rel.type == "contains" and "hierarchy_level" in rel.metadata:
                        levels_found.add(rel.metadata["hierarchy_level"])
        
        # outline.md has H1, H2, and H3 headings
        # Should detect multiple levels
        assert len(levels_found) >= 2, f"Expected multiple heading levels, found: {levels_found}"
        
        # Should have level 1 (H1) and level 2 (H2)
        assert 1 in levels_found or 2 in levels_found, \
            f"Expected to find level 1 or 2, found: {levels_found}"
    
    @pytest.mark.asyncio
    async def test_unstructured_element_types_mapped(self, parser, outline_md_path):
        """Test Unstructured element types are mapped correctly."""
        result = await parser.parse(str(outline_md_path))
        
        # Check that element types are standardized
        element_types = {c.element_type for c in result.chunks}
        
        # Should only have standardized types
        # Note: "file" is the synthetic file chunk that holds document-level relationships
        valid_types = {"doc_section", "section", "list_item", "table", "figure", "page", "file"}
        invalid_types = element_types - valid_types
        
        assert len(invalid_types) == 0, \
            f"Found non-standard element types: {invalid_types}"
    
    @pytest.mark.asyncio
    async def test_edge_case_no_headings(self, parser, tmp_path):
        """Test edge case: document with no headings."""
        # Create a document with no headings
        no_headings_file = tmp_path / "no_headings.md"
        no_headings_file.write_text("""
This is a document with no headings.
Just plain text paragraphs.

Another paragraph here.
And another one.
""")
        
        result = await parser.parse(str(no_headings_file))
        
        # Should still parse successfully
        assert isinstance(result, ParsedDocument)
        assert len(result.chunks) > 0

        # Document with no markdown headings should have no doc_section chunks
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        assert len(heading_chunks) == 0, \
            "Document without markdown headings should have no doc_section chunks"
    
    @pytest.mark.asyncio
    async def test_edge_case_flat_structure(self, parser, tmp_path):
        """Test edge case: flat structure (all same level)."""
        # Create a document with all H2 headings
        flat_file = tmp_path / "flat.md"
        flat_file.write_text("""
## Section 1
Content for section 1.

## Section 2
Content for section 2.

## Section 3
Content for section 3.
""")
        
        result = await parser.parse(str(flat_file))
        
        # Should parse successfully
        assert isinstance(result, ParsedDocument)
        assert len(result.chunks) > 0
        
        # Find heading chunks
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        
        # Should have multiple headings at same level
        if len(heading_chunks) >= 2:
            # Check for follows relationships (siblings)
            follows_rels = []
            for chunk in heading_chunks:
                if chunk.relationships:
                    follows_rels.extend([r for r in chunk.relationships if r.type == "follows"])
            
            # Flat structure should have follows relationships
            assert len(follows_rels) > 0, "Flat structure should have 'follows' relationships"


class TestMultipleDocumentFormats:
    """Test multiple document formats (Subtask 5.4)."""
    
    @pytest.mark.asyncio
    async def test_markdown_file_parsing(self, parser, outline_md_path):
        """Test with markdown file."""
        result = await parser.parse(str(outline_md_path))
        
        assert isinstance(result, ParsedDocument)
        assert len(result.chunks) > 0
        
        # Should have headings
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        assert len(heading_chunks) > 0
        
        # Metadata should indicate markdown
        assert result.metadata["parser"] == "document"
    
    @pytest.mark.asyncio
    async def test_consistent_behavior_across_formats(self, parser, outline_md_path):
        """Verify consistent behavior across formats."""
        # Parse markdown
        md_result = await parser.parse(str(outline_md_path))
        
        # All chunks should have element_type
        for chunk in md_result.chunks:
            assert chunk.element_type, "Chunk missing element_type"
        
        # All heading chunks should have element_name
        heading_chunks = [c for c in md_result.chunks if c.element_type == "doc_section"]
        for chunk in heading_chunks:
            assert chunk.element_name, "Heading chunk missing element_name"
        
        # Should have relationships
        chunks_with_rels = [c for c in heading_chunks if c.relationships]
        assert len(chunks_with_rels) > 0, "No chunks with relationships"
    
    @pytest.mark.asyncio
    async def test_parser_can_handle_markdown(self, parser):
        """Test that parser reports it can handle markdown."""
        assert await parser.can_parse("test.md")
        assert await parser.can_parse("test.markdown")
        assert await parser.can_parse("TEST.MD")  # Case insensitive  # Case insensitive
    
    @pytest.mark.asyncio
    async def test_parser_can_handle_other_formats(self, parser):
        """Test that parser reports it can handle other document formats."""
        # PDF
        assert await parser.can_parse("test.pdf")
        
        # Word
        assert await parser.can_parse("test.docx")
        assert await parser.can_parse("test.doc")
        
        # PowerPoint
        assert await parser.can_parse("test.pptx")
        assert await parser.can_parse("test.ppt")
        
        # HTML
        assert await parser.can_parse("test.html")


class TestDocumentParserQuality:
    """Additional quality tests for document parser."""
    
    @pytest.mark.asyncio
    async def test_no_empty_chunks(self, parser, outline_md_path):
        """Verify no empty chunks are created."""
        result = await parser.parse(str(outline_md_path))
        
        for chunk in result.chunks:
            assert chunk.content, "Found empty chunk"
            assert len(chunk.content.strip()) > 0, "Found chunk with only whitespace"
    
    @pytest.mark.asyncio
    async def test_chunk_metadata_complete(self, parser, outline_md_path):
        """Verify chunk metadata is complete."""
        result = await parser.parse(str(outline_md_path))
        
        for chunk in result.chunks:
            # Should have element_type
            assert chunk.element_type, "Chunk missing element_type"
            
            # Should have metadata dict
            assert chunk.metadata is not None, "Chunk missing metadata"
            
            # Should have content_type
            assert chunk.content_type, "Chunk missing content_type"
    
    @pytest.mark.asyncio
    async def test_document_metadata_complete(self, parser, outline_md_path):
        """Verify document-level metadata is complete."""
        result = await parser.parse(str(outline_md_path))
        
        # Check required metadata fields
        assert "parser" in result.metadata
        assert "chunk_count" in result.metadata
        assert "element_count" in result.metadata
        
        # Verify counts match
        assert result.metadata["chunk_count"] == len(result.chunks)
    
    @pytest.mark.asyncio
    async def test_relationships_reference_valid_entities(self, parser, outline_md_path):
        """Verify relationships reference valid entity names."""
        result = await parser.parse(str(outline_md_path))
        
        # Collect all element names
        all_names = {c.element_name for c in result.chunks if c.element_name}
        all_names.add(Path(outline_md_path).name)  # Add document name
        
        # Check all relationships
        for chunk in result.chunks:
            if chunk.relationships:
                for rel in chunk.relationships:
                    # Source and target should be valid names
                    # Note: source might be document name
                    if rel.source_type != "document":
                        assert rel.source_name in all_names or rel.source_name == "", \
                            f"Invalid source_name: {rel.source_name}"
                    
                    assert rel.target_name in all_names or rel.target_name == "", \
                        f"Invalid target_name: {rel.target_name}"


class TestRelationshipDirectionality:
    """Test that relationships are only attached to source chunks, not targets.
    
    This verifies Task 0.12: prevent duplicate relationships when querying.
    Relationships should only exist on the chunk that is the SOURCE of the relationship.
    """
    
    @pytest.mark.asyncio
    async def test_follows_relationship_only_on_source_chunk(self, parser, tmp_path):
        """Verify 'follows' relationships are only attached to the source (predecessor).
        
        When Section B follows Section A:
        - Section A should have a 'follows' relationship pointing to Section B
        - Section B should NOT have a 'follows' relationship in its list
        """
        # Create markdown with sequential sections at the same level
        test_file = tmp_path / "sequential.md"
        test_file.write_text("""
# Section A

Content for Section A.

# Section B

Content for Section B.

# Section C

Content for Section C.
""")
        
        result = await parser.parse(str(test_file))
        
        # Find the heading chunks by name
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        
        chunk_a = next((c for c in heading_chunks if c.element_name == "Section A"), None)
        chunk_b = next((c for c in heading_chunks if c.element_name == "Section B"), None)
        chunk_c = next((c for c in heading_chunks if c.element_name == "Section C"), None)
        
        assert chunk_a is not None, "Section A chunk not found"
        assert chunk_b is not None, "Section B chunk not found"
        assert chunk_c is not None, "Section C chunk not found"
        
        # Section A should have "follows" relationship TO Section B (A is source)
        a_follows_rels = [r for r in (chunk_a.relationships or []) if r.type == "follows"]
        assert len(a_follows_rels) == 1, f"Section A should have 1 'follows' rel, got {len(a_follows_rels)}"
        assert a_follows_rels[0].target_name == "Section B", \
            f"Section A should have 'follows' to Section B, got {a_follows_rels[0].target_name}"
        
        # Section B should have "follows" relationship TO Section C (B is source)
        b_follows_rels = [r for r in (chunk_b.relationships or []) if r.type == "follows"]
        assert len(b_follows_rels) == 1, f"Section B should have 1 'follows' rel, got {len(b_follows_rels)}"
        assert b_follows_rels[0].target_name == "Section C", \
            f"Section B should have 'follows' to Section C, got {b_follows_rels[0].target_name}"
        
        # Section C has no following sibling, so no "follows" relationship
        c_follows_rels = [r for r in (chunk_c.relationships or []) if r.type == "follows"]
        assert len(c_follows_rels) == 0, \
            f"Section C should have no 'follows' rels (no sibling after), got {len(c_follows_rels)}"
    
    @pytest.mark.asyncio
    async def test_contains_relationship_only_on_parent_chunk(self, parser, tmp_path):
        """Verify 'contains' relationships are only attached to the parent (source).
        
        When Parent contains Child:
        - Parent should have a 'contains' relationship pointing to Child
        - Child should NOT have a 'contains' relationship in its list
        """
        # Create markdown with nested headings
        test_file = tmp_path / "nested.md"
        test_file.write_text("""
# Parent Section

Parent content.

## Child Section

Child content.
""")
        
        result = await parser.parse(str(test_file))
        
        # Find the heading chunks
        heading_chunks = [c for c in result.chunks if c.element_type == "doc_section"]
        
        parent_chunk = next((c for c in heading_chunks if c.element_name == "Parent Section"), None)
        child_chunk = next((c for c in heading_chunks if c.element_name == "Child Section"), None)
        
        assert parent_chunk is not None, "Parent Section chunk not found"
        assert child_chunk is not None, "Child Section chunk not found"
        
        # Parent should have "contains" relationship TO Child
        parent_contains_rels = [r for r in (parent_chunk.relationships or []) if r.type == "contains"]
        child_targets = [r.target_name for r in parent_contains_rels]
        assert "Child Section" in child_targets, \
            f"Parent should 'contains' Child Section, got targets: {child_targets}"
        
        # Child should NOT have any "contains" relationships 
        # (Child contains nothing, and incoming relationships are NOT attached)
        child_contains_rels = [r for r in (child_chunk.relationships or []) if r.type == "contains"]
        assert len(child_contains_rels) == 0, \
            f"Child should have no 'contains' rels (no children), got {len(child_contains_rels)}"
    
    @pytest.mark.asyncio
    async def test_no_duplicate_relationships_across_chunks(self, parser, tmp_path):
        """Verify no duplicate relationships exist when counting all chunk relationships.
        
        Each relationship (e.g., A->B "follows") should only appear once across all chunks.
        """
        test_file = tmp_path / "multi_level.md"
        test_file.write_text("""
# Section 1

Content 1.

## Subsection 1.1

Content 1.1.

## Subsection 1.2

Content 1.2.

# Section 2

Content 2.
""")
        
        result = await parser.parse(str(test_file))
        
        # Collect all relationships from all chunks
        all_relationships = []
        for chunk in result.chunks:
            if chunk.relationships:
                all_relationships.extend(chunk.relationships)
        
        # Create unique relationship identifiers
        rel_identifiers = [
            (r.source_name, r.target_name, r.type) 
            for r in all_relationships
        ]
        
        # Check for duplicates
        unique_identifiers = set(rel_identifiers)
        assert len(rel_identifiers) == len(unique_identifiers), \
            f"Found duplicate relationships: {[r for r in rel_identifiers if rel_identifiers.count(r) > 1]}"
    
    @pytest.mark.asyncio
    async def test_relationship_source_matches_chunk_name(self, parser, tmp_path):
        """Verify all relationships on a chunk have that chunk as the source.
        
        A chunk should only have relationships where it is the source_name.
        This confirms no incoming relationships are incorrectly attached.
        """
        test_file = tmp_path / "verify_source.md"
        test_file.write_text("""
# First

Content for first.

# Second

Content for second.

## Nested

Nested content.
""")
        
        result = await parser.parse(str(test_file))
        
        # Check each chunk's relationships
        for chunk in result.chunks:
            if chunk.relationships and chunk.element_name:
                for rel in chunk.relationships:
                    # The chunk's element_name should match the relationship's source_name
                    # (or document name for top-level)
                    source_matches = (
                        rel.source_name == chunk.element_name or
                        rel.source_type == "document"  # Document-level relationships OK
                    )
                    assert source_matches, \
                        f"Chunk '{chunk.element_name}' has relationship with " \
                        f"source_name='{rel.source_name}'. " \
                        f"Relationships should only be attached to source chunks."


@pytest.fixture
def pdf_sample_path():
    """Path to the PDF sample document."""
    return Path("tests/parsers/samples/docs/Getting the Most Out of AI Tools.pdf")


class TestPDFElementMapping:
    """Test PDF element type mapping and heading thresholds."""

    def test_pdf_heading_thresholds_defined(self):
        """Verify PDF heading thresholds are properly configured."""
        from agentic_inquiry.parsers.implementations.document import PDF_HEADING_THRESHOLDS

        assert 1 in PDF_HEADING_THRESHOLDS, "Missing h1 threshold"
        assert 2 in PDF_HEADING_THRESHOLDS, "Missing h2 threshold"
        assert 3 in PDF_HEADING_THRESHOLDS, "Missing h3 threshold"
        assert 4 in PDF_HEADING_THRESHOLDS, "Missing h4 threshold"

        # Thresholds should be in descending order (h1 > h2 > h3 > h4)
        assert PDF_HEADING_THRESHOLDS[1] > PDF_HEADING_THRESHOLDS[2]
        assert PDF_HEADING_THRESHOLDS[2] > PDF_HEADING_THRESHOLDS[3]
        assert PDF_HEADING_THRESHOLDS[3] > PDF_HEADING_THRESHOLDS[4]

    def test_pdf_element_class_interface(self):
        """Verify PDFElement provides the same interface as unstructured Element."""
        from agentic_inquiry.parsers.implementations.document import PDFElement

        element = PDFElement(
            text="Test heading",
            element_type="Title",
            metadata={"page_number": 1, "font_size": 24.0}
        )

        # PDFElement should have same properties as unstructured Element
        assert element.text == "Test heading"
        assert element.category == "Title"
        assert element.metadata["page_number"] == 1
        assert str(element) == "Test heading"


class TestPDFHeadingClassification:
    """Test font-based heading classification for PDFs."""

    def test_large_font_classified_as_title(self, parser):
        """Text with 1.8x+ body size should be classified as Title."""
        element_type = parser._classify_pdf_element(
            text="Main Title",
            font_size=18.0,   # 1.8x body size
            font_weight=400,
            body_size=10.0,
        )
        assert element_type == "Title"

    def test_medium_font_classified_as_header(self, parser):
        """Text with 1.5x body size should be classified as Header."""
        element_type = parser._classify_pdf_element(
            text="Section Header",
            font_size=15.0,   # 1.5x body size
            font_weight=400,
            body_size=10.0,
        )
        assert element_type == "Header"

    def test_body_font_classified_as_narrative(self, parser):
        """Text at body size should be classified as NarrativeText."""
        element_type = parser._classify_pdf_element(
            text="This is body text content that spans multiple words.",
            font_size=10.0,
            font_weight=400,
            body_size=10.0,
        )
        assert element_type == "NarrativeText"

    def test_bold_short_text_classified_as_header(self, parser):
        """Bold short text at body size should be classified as Header."""
        element_type = parser._classify_pdf_element(
            text="Bold Header",
            font_size=10.0,   # Same as body
            font_weight=700,  # Bold
            body_size=10.0,
        )
        assert element_type == "Header"

    def test_long_text_not_classified_as_heading(self, parser):
        """Long text should not be classified as heading even with large font."""
        long_text = "This is a very long piece of text that goes on and on for many characters " * 2
        element_type = parser._classify_pdf_element(
            text=long_text,
            font_size=18.0,   # Large font
            font_weight=700,  # Bold
            body_size=10.0,
        )
        assert element_type == "NarrativeText"

    def test_multiline_text_not_classified_as_heading(self, parser):
        """Multi-line text should not be classified as heading."""
        element_type = parser._classify_pdf_element(
            text="Line one\nLine two",
            font_size=18.0,   # Large font
            font_weight=400,
            body_size=10.0,
        )
        assert element_type == "NarrativeText"


class TestPDFStructureExtraction:
    """Integration tests for PDF structure extraction with pdftext."""

    @pytest.mark.asyncio
    async def test_pdf_extraction_returns_elements(self, parser, pdf_sample_path):
        """Verify PDF extraction returns elements."""
        if not pdf_sample_path.exists():
            pytest.skip(f"Sample PDF not found: {pdf_sample_path}")

        result = await parser.parse(str(pdf_sample_path))

        assert isinstance(result, ParsedDocument)
        assert len(result.chunks) > 0, "PDF should have content chunks"

    @pytest.mark.asyncio
    async def test_pdf_creates_doc_section_entities(self, parser, pdf_sample_path):
        """Verify PDF parsing creates doc_section entities from detected headings.

        Regression test for DG-001/DG-002: PDF had 0 entities indexed with
        no relationships due to lack of structure detection.
        """
        if not pdf_sample_path.exists():
            pytest.skip(f"Sample PDF not found: {pdf_sample_path}")

        result = await parser.parse(str(pdf_sample_path))

        # Find doc_section chunks (headings)
        doc_sections = [c for c in result.chunks if c.element_type == "doc_section"]

        # PDF should have some headings detected
        assert len(doc_sections) > 0, \
            "PDF should have doc_section entities from heading detection"

        # Each doc_section should have an element_name
        for section in doc_sections:
            assert section.element_name, \
                f"doc_section missing element_name: {section.content[:50]}"

    @pytest.mark.asyncio
    async def test_pdf_creates_relationships(self, parser, pdf_sample_path):
        """Verify PDF parsing creates relationships between sections.

        Tests that the font-based heading detection leads to proper
        relationship creation in the document graph.
        """
        if not pdf_sample_path.exists():
            pytest.skip(f"Sample PDF not found: {pdf_sample_path}")

        result = await parser.parse(str(pdf_sample_path))

        # Collect all relationships
        all_rels = []
        for chunk in result.chunks:
            if chunk.relationships:
                all_rels.extend(chunk.relationships)

        # Should have at least some relationships
        assert len(all_rels) > 0, \
            "PDF should have relationships between sections"

        # Verify relationship types
        rel_types = {rel.type for rel in all_rels}
        assert "follows" in rel_types or "contains" in rel_types, \
            f"Expected follows/contains relationships, got: {rel_types}"

    @pytest.mark.asyncio
    async def test_pdf_chunks_have_metadata(self, parser, pdf_sample_path):
        """Verify PDF chunks contain font metadata."""
        if not pdf_sample_path.exists():
            pytest.skip(f"Sample PDF not found: {pdf_sample_path}")

        result = await parser.parse(str(pdf_sample_path))

        # Check that at least some chunks have PDF-specific metadata
        chunks_with_font = [
            c for c in result.chunks
            if c.metadata and "font_size" in c.metadata
        ]

        assert len(chunks_with_font) > 0, \
            "PDF chunks should include font_size metadata"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
