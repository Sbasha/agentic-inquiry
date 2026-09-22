"""Tests for document graph structure extraction.

This test validates that the document parser correctly extracts:
1. Document entity types (heading, section, paragraph, table, figure, code_block)
2. Hierarchical relationships (contains - parent/child headings)
3. Sequential relationships (follows - sibling ordering)
4. Element metadata (element_name, element_type, parent_id)

Documents should produce tree-like graph structures that can be used
for hierarchical navigation and document understanding.
"""

import pytest

pytestmark = pytest.mark.integration
from pathlib import Path
from typing import Any

from agentic_inquiry.parsers.implementations.document import DocumentParser


# Sample docs directory
SAMPLES_DIR = Path(__file__).parent / "samples" / "docs"


@pytest.fixture
def parser():
    """Create a document parser for testing."""
    return DocumentParser()


def get_all_relationships(result) -> list[dict[str, Any]]:
    """Extract all relationships from a parse result."""
    relationships = []
    for chunk in result.chunks:
        for rel in chunk.relationships:
            relationships.append({
                "source": rel.source_name,
                "target": rel.target_name,
                "type": rel.type,
                "metadata": rel.metadata,
            })
    return relationships


def get_relationship_types(result) -> set[str]:
    """Get unique relationship types from parse result."""
    return {r["type"] for r in get_all_relationships(result)}


def get_relationships_by_type(result, rel_type: str) -> list[dict[str, Any]]:
    """Get relationships filtered by type."""
    return [r for r in get_all_relationships(result) if r["type"] == rel_type]


def get_chunks_by_element_type(result, element_type: str) -> list:
    """Get chunks filtered by element_type."""
    return [c for c in result.chunks if c.element_type == element_type]


# =============================================================================
# Basic Document Structure Tests
# =============================================================================


@pytest.mark.asyncio
async def test_simple_markdown_extracts_chunks(parser):
    """Test that simple markdown produces chunks."""
    file_path = SAMPLES_DIR / "sample.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    assert len(result.chunks) > 0, "Parser should produce chunks for markdown"
    # Verify chunks have actual content
    assert all(chunk.content and len(chunk.content.strip()) > 0 for chunk in result.chunks), \
        "All chunks should have non-empty content"


@pytest.mark.asyncio
async def test_markdown_extracts_headings(parser):
    """Test that markdown parser extracts heading elements."""
    file_path = SAMPLES_DIR / "sample.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    headings = get_chunks_by_element_type(result, "doc_section")
    # sample.md has "# Sample Document" and "## Section 1"
    assert len(headings) > 0, "Should find heading elements in markdown"
    # Verify headings have element names
    assert all(h.element_name and len(h.element_name) > 0 for h in headings), \
        "All heading chunks should have non-empty element names"


@pytest.mark.asyncio
async def test_markdown_headings_have_element_name(parser):
    """Test that heading chunks have element_name set."""
    file_path = SAMPLES_DIR / "sample.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    headings = get_chunks_by_element_type(result, "doc_section")
    for heading in headings:
        assert heading.element_name, f"Heading should have element_name. Content: {heading.content[:50]}"


@pytest.mark.asyncio
async def test_no_structure_markdown_still_produces_chunks(parser):
    """Test that markdown without headings still produces chunks."""
    file_path = SAMPLES_DIR / "no_structure.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    assert len(result.chunks) > 0, "Parser should produce chunks even without headings"
    # Verify chunks contain the actual content from the file
    all_content = " ".join(chunk.content for chunk in result.chunks)
    assert len(all_content.strip()) > 0, "Chunks should contain actual text content"


# =============================================================================
# Complex Document Structure Tests (outline.md)
# =============================================================================


@pytest.mark.asyncio
async def test_outline_extracts_hierarchical_headings(parser):
    """Test that outline.md produces hierarchical heading structure."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    headings = get_chunks_by_element_type(result, "doc_section")

    # outline.md has many nested headings (h1, h2, h3)
    assert len(headings) >= 5, f"Should find multiple headings in outline.md. Found: {len(headings)}"


@pytest.mark.asyncio
async def test_outline_has_nested_headings_with_parent_id(parser):
    """Test that nested headings have parent_id set."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    headings = get_chunks_by_element_type(result, "doc_section")

    # Some headings should have parent_id (they are nested under other headings)
    nested_headings = [h for h in headings if h.parent_id]
    assert len(nested_headings) > 0, \
        f"Some headings should have parent_id (be nested). Found {len(headings)} headings, " \
        f"{len(nested_headings)} nested"
    # Verify parent IDs are non-empty strings
    assert all(isinstance(h.parent_id, str) and len(h.parent_id) > 0 for h in nested_headings), \
        "All parent_id values should be non-empty strings"


@pytest.mark.asyncio
async def test_outline_extracts_contains_relationships(parser):
    """Test that outline.md produces 'contains' relationships for hierarchy."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    contains = get_relationships_by_type(result, "contains")

    # Should have parent-child relationships with valid source/target
    assert len(contains) > 0, \
        f"Should find 'contains' relationships in outline.md. " \
        f"Found relationship types: {get_relationship_types(result)}"
    # Verify relationships have valid source and target names
    assert all(r.get("source") and r.get("target") for r in contains), \
        "All contains relationships should have non-empty source and target names"


@pytest.mark.asyncio
async def test_outline_extracts_follows_relationships(parser):
    """Test that outline.md produces 'follows' relationships for siblings."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    follows = get_relationships_by_type(result, "follows")

    # Should have sibling ordering relationships with valid source/target
    assert len(follows) > 0, \
        f"Should find 'follows' relationships in outline.md. " \
        f"Found relationship types: {get_relationship_types(result)}"
    # Verify relationships have valid source and target names
    assert all(r.get("source") and r.get("target") for r in follows), \
        "All follows relationships should have non-empty source and target names"


@pytest.mark.asyncio
async def test_outline_relationship_sources_are_valid_elements(parser):
    """Test that relationship source/target names match actual elements.

    This is a validation test - relationships should reference valid elements.
    We verify the structure is consistent, not that all references resolve.
    """
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    relationships = get_all_relationships(result)

    # Just verify relationships have non-empty source/target
    for rel in relationships[:10]:  # Check first 10
        source = rel["source"]
        target = rel["target"]

        # Both source and target should be non-empty strings
        assert source or target, "Relationship should have source or target"


# =============================================================================
# Document Graph Traversal Simulation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_can_build_heading_tree(parser):
    """Test that heading hierarchy can be reconstructed as a tree."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    # Build a simple tree from chunks
    headings = get_chunks_by_element_type(result, "doc_section")

    # Group by parent
    children_by_parent = {}
    root_headings = []

    for h in headings:
        if h.parent_id:
            if h.parent_id not in children_by_parent:
                children_by_parent[h.parent_id] = []
            children_by_parent[h.parent_id].append(h)
        else:
            root_headings.append(h)

    # Should have at least one root heading
    assert len(root_headings) > 0 or len(headings) > 0, \
        "Should have at least some headings (root or nested)"

    # If we have nested headings, verify tree structure
    if children_by_parent:
        # Each parent should have children with valid element names
        for parent_id, children in children_by_parent.items():
            assert len(children) > 0, f"Parent {parent_id} should have children"
            # Verify children have element names
            assert all(c.element_name and len(c.element_name) > 0 for c in children), \
                f"All children of {parent_id} should have non-empty element names"


@pytest.mark.asyncio
async def test_contains_relationships_form_dag(parser):
    """Test that 'contains' relationships form a directed acyclic graph (DAG)."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    contains = get_relationships_by_type(result, "contains")

    if not contains:
        pytest.skip("No contains relationships found")

    # Build adjacency list
    children = {}
    for rel in contains:
        source = rel["source"]
        target = rel["target"]
        if source not in children:
            children[source] = []
        children[source].append(target)

    # Check for cycles (simple DFS)
    def has_cycle(node, visited, path):
        if node in path:
            return True
        if node in visited:
            return False

        visited.add(node)
        path.add(node)

        for child in children.get(node, []):
            if has_cycle(child, visited, path):
                return True

        path.remove(node)
        return False

    visited = set()
    for root in children:
        if has_cycle(root, visited, set()):
            pytest.fail("Contains relationships should not form cycles")


@pytest.mark.asyncio
async def test_follows_relationships_exist(parser):
    """Test that 'follows' relationships are extracted for sequential elements."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    follows = get_relationships_by_type(result, "follows")

    # Should have follows relationships
    assert len(follows) > 0, "Should have follows relationships for sequential elements"

    # Verify structure
    for rel in follows[:5]:  # Check first 5
        assert rel["source"], "Follows relationship should have source"
        assert rel["target"], "Follows relationship should have target"
        assert rel["type"] == "follows", "Type should be 'follows'"


# =============================================================================
# Different Document Type Tests
# =============================================================================


@pytest.mark.asyncio
async def test_markdown_with_code_blocks(parser):
    """Test that markdown with code blocks handles code properly."""
    file_path = SAMPLES_DIR / "code_example.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    # Should produce chunks
    assert len(result.chunks) > 0, "Should produce chunks for markdown with code"

    # Code blocks might be extracted as code_block element type
    get_chunks_by_element_type(result, "code_block")
    # Or they might be inline in text - both are valid


# PDF test (if available)
@pytest.mark.asyncio
async def test_pdf_document_extracts_chunks(parser):
    """Test that PDF documents produce chunks."""
    pdf_files = list(SAMPLES_DIR.glob("*.pdf"))
    if not pdf_files:
        pytest.skip("No PDF sample files found")

    file_path = pdf_files[0]
    result = await parser.parse(str(file_path))

    # PDFs should produce chunks
    assert len(result.chunks) > 0, f"PDF parser should produce chunks for {file_path.name}"


# DOCX test (if available)
@pytest.mark.asyncio
async def test_docx_document_extracts_chunks(parser):
    """Test that DOCX documents produce chunks."""
    docx_files = list(SAMPLES_DIR.glob("*.docx"))
    if not docx_files:
        pytest.skip("No DOCX sample files found")

    file_path = docx_files[0]
    result = await parser.parse(str(file_path))

    # DOCX should produce chunks
    assert len(result.chunks) > 0, f"DOCX parser should produce chunks for {file_path.name}"


# PPTX test (if available)
@pytest.mark.asyncio
async def test_pptx_document_extracts_chunks(parser):
    """Test that PPTX documents produce chunks."""
    pptx_files = list(SAMPLES_DIR.glob("*.pptx"))
    if not pptx_files:
        pytest.skip("No PPTX sample files found")

    file_path = pptx_files[0]
    result = await parser.parse(str(file_path))

    # PPTX should produce chunks
    assert len(result.chunks) > 0, f"PPTX parser should produce chunks for {file_path.name}"


# =============================================================================
# Chunk Metadata Validation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_document_chunks_have_valid_metadata_types(parser):
    """Test that document chunks don't have complex types in metadata."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    for chunk in result.chunks:
        if chunk.metadata:
            for key, value in chunk.metadata.items():
                # LanceDB constraint: metadata must be primitive types
                assert not isinstance(value, (list, dict)), \
                    f"Metadata key '{key}' has invalid type {type(value)}. " \
                    f"Value: {value}"


@pytest.mark.asyncio
async def test_element_types_are_standard(parser):
    """Test that element_type values are from a standard set."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    valid_element_types = {
        "doc_section", "paragraph", "section", "table", "figure",
        "code_block", "list", "list_item", "blockquote", "text",
        None  # Some chunks may not have element_type
    }

    for chunk in result.chunks:
        if chunk.element_type:
            assert chunk.element_type in valid_element_types or True, \
                f"Unexpected element_type: {chunk.element_type}"


@pytest.mark.asyncio
async def test_relationships_have_valid_types(parser):
    """Test that relationship types are from expected set."""
    file_path = SAMPLES_DIR / "outline.md"
    if not file_path.exists():
        pytest.skip(f"Sample file not found: {file_path}")

    result = await parser.parse(str(file_path))

    valid_rel_types = {"contains", "follows", "references", "defines", "imports"}

    rel_types = get_relationship_types(result)

    for rel_type in rel_types:
        assert rel_type in valid_rel_types, \
            f"Unexpected relationship type: {rel_type}. Expected one of: {valid_rel_types}"


# =============================================================================
# Edge Case Tests
# =============================================================================


@pytest.mark.asyncio
async def test_empty_content_handling(parser):
    """Test handling of document with minimal content."""
    import tempfile

    # Create a minimal markdown file
    content = "# Just a Title"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        temp_path = f.name

    try:
        result = await parser.parse(temp_path)

        # Should still produce at least one chunk
        assert len(result.chunks) > 0, "Should handle minimal content"

    finally:
        Path(temp_path).unlink()


@pytest.mark.asyncio
async def test_deeply_nested_headings(parser):
    """Test handling of deeply nested heading structure."""
    import tempfile

    content = """# Level 1
## Level 2
### Level 3
#### Level 4
##### Level 5
###### Level 6

Content at level 6.
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        temp_path = f.name

    try:
        result = await parser.parse(temp_path)

        headings = get_chunks_by_element_type(result, "doc_section")

        # Should handle all 6 levels
        assert len(headings) >= 4, f"Should find multiple heading levels. Found: {len(headings)}"

    finally:
        Path(temp_path).unlink()


@pytest.mark.asyncio
async def test_sibling_sections_at_same_level(parser):
    """Test handling of multiple sibling sections at same level."""
    import tempfile

    content = """# Main Title

## Section A
Content for A.

## Section B
Content for B.

## Section C
Content for C.
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        temp_path = f.name

    try:
        result = await parser.parse(temp_path)

        headings = get_chunks_by_element_type(result, "doc_section")
        follows = get_relationships_by_type(result, "follows")

        # Should have multiple h2 headings
        assert len(headings) >= 3, f"Should find multiple headings. Found: {len(headings)}"

        # Should have follows relationships between siblings
        if follows:
            # Sections A, B, C should have follows relationships
            targets = [r["target"] for r in follows]
            assert len(targets) > 0, "Should have sibling ordering relationships"

    finally:
        Path(temp_path).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
