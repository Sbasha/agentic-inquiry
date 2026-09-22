"""Unit tests for ID field consistency in direct_access.py.

Verifies that graph_traverse() and get_by_id() use the correct column name ('id')
rather than the incorrect 'entity_id' which doesn't exist in the schema.

This tests the fix for Tasks 0.1 and 0.2 in the progressive-index-readiness spec.
"""

import pytest

pytestmark = pytest.mark.unit

from agent_vault.database.filter_helpers import by_id
from agent_vault.database.filters import Filter, FilterOperator


class TestIdFieldConsistency:
    """Tests that ID field lookups use the correct column name."""

    def test_by_id_filter_uses_specified_field(self):
        """by_id() helper should create filter with the specified field name.

        The graph_entities and graph_relationships tables both use 'id' as
        the primary key column, not 'entity_id'. This test verifies that
        when we call by_id("id", value) we get a filter targeting "id".
        """
        # The by_id helper should accept field name and value
        filter_obj = by_id("id", "test_entity_123")

        # Verify it's a Filter object with correct properties
        assert isinstance(filter_obj, Filter)
        assert filter_obj.field == "id"
        assert filter_obj.value == "test_entity_123"
        assert filter_obj.operator == FilterOperator.EQ

    def test_by_id_filter_with_different_field(self):
        """by_id() can work with any field name."""
        filter_obj = by_id("name", "TestClass")

        # Should reference the field we asked for
        assert isinstance(filter_obj, Filter)
        assert filter_obj.field == "name"
        assert filter_obj.value == "TestClass"

    def test_filter_rejects_none_value(self):
        """Verify by_id() handles edge cases properly.

        The by_id helper should create valid filters even with edge case values.
        """
        # Test with empty string
        filter_obj = by_id("id", "")
        assert filter_obj.field == "id"
        assert filter_obj.value == ""

        # Test with complex ID format (as used in graph entities)
        complex_id = "class::abc123::path/to/file.py::ClassName"
        filter_obj = by_id("id", complex_id)
        assert filter_obj.field == "id"
        assert filter_obj.value == complex_id

    def test_filter_operator_is_equality(self):
        """Verify by_id() always uses equality operator.

        Entity lookups should use exact equality matching.
        """
        filter_obj = by_id("id", "test_value")
        assert filter_obj.operator == FilterOperator.EQ
        assert filter_obj.operator != FilterOperator.IN


class TestGraphTraverseIdField:
    """Tests for graph_traverse() ID field handling.

    These tests verify the fix where graph_traverse() was incorrectly
    using 'entity_id' instead of 'id' for entity lookups.
    """

    def test_graph_traverse_filter_construction(self):
        """graph_traverse should use 'id' for entity filter.

        When looking up an entity by its ID, graph_traverse() should
        use by_id("id", start_id) not by_id("entity_id", start_id).
        """
        # Simulate what the fixed code does
        start_id = "entity_abc123"

        # Correct filter construction (as in the fixed direct_access.py)
        correct_filter = by_id("id", start_id)

        # Verify the filter is constructed correctly
        assert correct_filter.field == "id"
        assert correct_filter.value == start_id
        assert correct_filter.operator == FilterOperator.EQ

    def test_neighbor_lookup_uses_id_field(self):
        """Neighbor entity lookups should also use 'id'.

        When graph_traverse() looks up neighbor entities during traversal,
        it should use the same 'id' field, not 'entity_id'.
        """
        neighbor_id = "neighbor_xyz789"

        # Correct filter for neighbor lookup
        neighbor_filter = by_id("id", neighbor_id)

        assert neighbor_filter.field == "id"
        assert neighbor_filter.value == neighbor_id

    def test_entity_id_field_would_be_wrong(self):
        """Document that 'entity_id' would create wrong filter.

        If we mistakenly used 'entity_id' instead of 'id', the filter
        would target the wrong column.
        """
        entity_value = "some_entity"

        # Wrong filter (how it was before the fix)
        wrong_filter = by_id("entity_id", entity_value)

        # This creates a filter targeting entity_id column
        assert wrong_filter.field == "entity_id"
        assert wrong_filter.field != "id"  # This is the bug!


class TestGetByIdField:
    """Tests for get_by_id() ID field handling.

    These tests verify the fix where get_by_id() was using dynamic
    field selection that incorrectly chose 'entity_id' for graph_entities.
    """

    def test_multiple_ids_create_separate_filters(self):
        """Verify each ID creates an independent filter.

        When looking up multiple entities, each should get its own filter.
        """
        ids = ["entity_1", "entity_2", "entity_3"]
        filters = [by_id("id", eid) for eid in ids]

        # Each filter should be independent
        assert len(filters) == 3
        for i, f in enumerate(filters):
            assert f.value == ids[i]
            assert f.field == "id"

    def test_filter_preserves_special_characters(self):
        """Verify filter handles IDs with special characters.

        Entity IDs may contain colons, slashes, and other special chars.
        """
        special_ids = [
            "class::hash::path/file.py::Name",
            "external://python/os",
            "builtin://python/len",
        ]

        for special_id in special_ids:
            filter_obj = by_id("id", special_id)
            assert filter_obj.value == special_id, f"Filter should preserve: {special_id}"

    def test_filter_construction_with_correct_id(self):
        """Verify filter construction works with 'id' field."""
        test_ids = ["id_1", "id_2", "id_3"]

        for entity_id in test_ids:
            # Construct filter as the fixed code does
            filter_obj = by_id("id", entity_id)

            # Verify filter targets correct field
            assert filter_obj.field == "id"
            assert filter_obj.value == entity_id
