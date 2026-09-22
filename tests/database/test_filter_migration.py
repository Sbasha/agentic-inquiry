"""Tests for filter construction migration to FilterBuilder.

This module tests that all filter construction in the codebase uses
FilterBuilder instead of direct string formatting.
"""

import pytest

pytestmark = pytest.mark.unit
from agentic_inquiry.database.filters import FilterBuilder
from agentic_inquiry.database.query_builder import LanceDBQueryBuilder


class TestFilterBuilderUsage:
    """Test that FilterBuilder is used correctly throughout the codebase."""

    def test_query_builder_uses_filter_builder(self):
        """Test that LanceDBQueryBuilder uses FilterBuilder for filter construction."""
        # Create a mock query builder
        def mock_get_table(name: str):
            return None
        
        def mock_run_sync(fn):
            return fn()
        
        builder = LanceDBQueryBuilder(
            get_table_fn=mock_get_table,
            run_sync_fn=mock_run_sync,
            project_id="test_project"
        )
        
        # Test that _filters_to_expression uses FilterBuilder
        filters = {
            "doc_id": ["doc1", "doc2"],
            "project_id": "test_project",
            "custom_field": "value"
        }
        
        result = builder._filters_to_expression(filters)
        
        # Verify the result is a valid filter expression
        assert isinstance(result, str)
        assert "doc_id IN" in result
        assert "project_id =" in result
        assert "custom_field =" in result
        assert "doc1" in result
        assert "doc2" in result
        assert "test_project" in result

    def test_filter_builder_escapes_special_characters(self):
        """Test that FilterBuilder properly escapes special characters."""
        builder = FilterBuilder()
        
        # Test with single quote (SQL injection attempt)
        builder.add_doc_id_filter(["doc'; DROP TABLE documents; --"])
        result = builder.build()
        
        # Verify single quotes are escaped (doubled)
        assert "doc''; DROP TABLE documents; --" in result
        # The dangerous content is still there but escaped, which is safe
        assert "'doc''; DROP TABLE documents; --'" in result

    def test_filter_builder_validates_inputs(self):
        """Test that FilterBuilder validates inputs."""
        builder = FilterBuilder()
        
        # Test empty doc_ids
        with pytest.raises(ValueError, match="doc_ids cannot be empty"):
            builder.add_doc_id_filter([])
        
        # Test empty project_id
        with pytest.raises(ValueError, match="project_id cannot be empty"):
            builder.add_project_filter("")
        
        # Test invalid field name
        with pytest.raises(ValueError, match="Invalid field name"):
            builder.add_field_filter("field; DROP TABLE", "value")

    def test_filter_builder_handles_multiple_conditions(self):
        """Test that FilterBuilder combines multiple conditions correctly."""
        builder = FilterBuilder()
        
        builder.add_doc_id_filter(["doc1", "doc2"])
        builder.add_project_filter("project1")
        builder.add_field_filter("status", "active")
        
        result = builder.build()
        
        # Verify all conditions are present and combined with AND
        assert "doc_id IN" in result
        assert "project_id =" in result
        assert "status =" in result
        assert result.count(" AND ") == 2

    def test_filter_builder_handles_different_value_types(self):
        """Test that FilterBuilder handles different value types correctly."""
        builder = FilterBuilder()
        
        # String value
        builder.add_field_filter("name", "test")
        # Integer value
        builder.add_field_filter("count", 42)
        # Float value
        builder.add_field_filter("score", 3.14)
        # Boolean value
        builder.add_field_filter("active", True)
        # None value
        builder.add_field_filter("optional", None)
        # List value
        builder.add_field_filter("tags", ["tag1", "tag2"])
        
        result = builder.build()
        
        # Verify all types are handled correctly
        assert "name = 'test'" in result
        assert "count = 42" in result
        assert "score = 3.14" in result
        assert "active = true" in result
        assert "optional IS NULL" in result
        assert "tags IN ('tag1', 'tag2')" in result

    def test_no_direct_string_formatting_in_filters(self):
        """Test that filter expressions don't use direct string formatting."""
        builder = FilterBuilder()
        
        # Build a filter with potentially dangerous input
        dangerous_input = "'; DELETE FROM table WHERE '1'='1"
        builder.add_doc_id_filter([dangerous_input])
        
        result = builder.build()
        
        # Verify the dangerous input is escaped (single quotes are doubled)
        assert "'''; DELETE FROM table WHERE ''1''=''1'" in result
        # The content is wrapped in quotes, making it safe
        assert result.startswith("doc_id = '")
        assert result.endswith("'")  

    def test_query_builder_delegates_to_filter_builder(self):
        """Test that LanceDBQueryBuilder delegates filter construction to FilterBuilder."""
        def mock_get_table(name: str):
            return None
        
        def mock_run_sync(fn):
            return fn()
        
        builder = LanceDBQueryBuilder(
            get_table_fn=mock_get_table,
            run_sync_fn=mock_run_sync,
            project_id="test_project"
        )
        
        # Test with single doc_id filter (uses = not IN)
        filters = {"doc_id": "doc1"}
        result = builder._filters_to_expression(filters)
        assert "doc_id = 'doc1'" in result
        
        # Test with multiple doc_ids (uses IN)
        filters = {"doc_id": ["doc1", "doc2"]}
        result = builder._filters_to_expression(filters)
        assert "doc_id IN ('doc1', 'doc2')" in result
        
        # Test with project_id filter
        filters = {"project_id": "project1"}
        result = builder._filters_to_expression(filters)
        assert "project_id = 'project1'" in result
        
        # Test with custom field filter
        filters = {"custom": "value"}
        result = builder._filters_to_expression(filters)
        assert "custom = 'value'" in result

    def test_filter_builder_reset(self):
        """Test that FilterBuilder can be reset and reused."""
        builder = FilterBuilder()
        
        builder.add_doc_id_filter(["doc1"])
        builder.add_project_filter("project1")
        result1 = builder.build()
        
        # Reset and build new filter
        builder.reset()
        builder.add_doc_id_filter(["doc2"])
        result2 = builder.build()
        
        # Verify results are different
        assert "doc1" in result1
        assert "project1" in result1
        assert "doc1" not in result2
        assert "project1" not in result2
        assert "doc2" in result2

    def test_filter_builder_empty_build(self):
        """Test that FilterBuilder returns empty string when no conditions."""
        builder = FilterBuilder()
        result = builder.build()
        assert result == ""

    def test_filter_builder_method_chaining(self):
        """Test that FilterBuilder supports method chaining."""
        builder = FilterBuilder()
        
        result = (builder
                  .add_doc_id_filter(["doc1"])
                  .add_project_filter("project1")
                  .add_field_filter("status", "active")
                  .build())
        
        # Single doc_id uses = not IN
        assert "doc_id =" in result
        assert "project_id =" in result
        assert "status =" in result
