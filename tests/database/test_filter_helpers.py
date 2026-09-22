"""Tests for Filter AST builder helpers.

These helpers assist gradual migration from dict-based filters to Filter AST.
See Phase 4.5.1 in DATABASE-ABSTRACTION-TASKS.md.

Coverage:
- from_dict: Convert legacy dict filters to Filter AST
- project_scoped: Common project filter pattern
- by_id: Single ID lookup pattern
- combine_filters: Combine optional filters with AND
- by_type: Entity type filter pattern
"""

import pytest

pytestmark = pytest.mark.unit

from agent_vault.database.filters import (
    FilterOperator,
    eq,
    is_in,
    is_not_null,
)


class TestFromDict:
    """Tests for from_dict helper that converts legacy dict filters to Filter AST."""

    def test_empty_dict_returns_none(self) -> None:
        """Empty dict should return None (no filter)."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({})
        assert result is None

    def test_single_string_field(self) -> None:
        """Single field with string value becomes EQ."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"status": "active"})
        assert result is not None
        assert result.operator == FilterOperator.EQ
        assert result.field == "status"
        assert result.value == "active"

    def test_single_int_field(self) -> None:
        """Single field with int value becomes EQ."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"count": 42})
        assert result is not None
        assert result.operator == FilterOperator.EQ
        assert result.field == "count"
        assert result.value == 42

    def test_single_field_list_becomes_in(self) -> None:
        """Single field with list value becomes IN."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"type": ["code", "doc"]})
        assert result is not None
        assert result.operator == FilterOperator.IN
        assert result.field == "type"
        assert result.values is not None
        assert list(result.values) == ["code", "doc"]

    def test_single_item_list_becomes_eq(self) -> None:
        """Single-item list optimizes to EQ instead of IN."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"type": ["code"]})
        assert result is not None
        # Single-item list should optimize to EQ
        assert result.operator == FilterOperator.EQ
        assert result.field == "type"
        assert result.value == "code"

    def test_empty_list_becomes_false(self) -> None:
        """Empty list should create an IN with empty values (translates to FALSE)."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"type": []})
        assert result is not None
        assert result.operator == FilterOperator.IN
        assert result.field == "type"
        assert result.values is not None
        assert list(result.values) == []

    def test_multiple_fields_combined_with_and(self) -> None:
        """Multiple fields are combined with AND."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"status": "active", "type": "code"})
        assert result is not None
        # Should be AND of two conditions
        assert result.operator == FilterOperator.AND
        # Check both conditions are present
        assert result.left is not None
        assert result.right is not None

    def test_mixed_scalar_and_list(self) -> None:
        """Mixed scalar and list values work correctly."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"status": "active", "type": ["code", "doc"]})
        assert result is not None
        assert result.operator == FilterOperator.AND

    def test_boolean_value(self) -> None:
        """Boolean values are preserved."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"is_indexed": True})
        assert result is not None
        assert result.operator == FilterOperator.EQ
        assert result.field == "is_indexed"
        assert result.value is True

    def test_float_value(self) -> None:
        """Float values are preserved."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"score": 0.95})
        assert result is not None
        assert result.operator == FilterOperator.EQ
        assert result.field == "score"
        assert result.value == 0.95

    def test_none_value_raises(self) -> None:
        """None value should raise ValueError (use is_null filter explicitly)."""
        from agent_vault.database.filter_helpers import from_dict

        with pytest.raises(ValueError, match="None.*is_null"):
            from_dict({"deleted_at": None})

    def test_nested_dict_raises(self) -> None:
        """Nested dict values are not supported."""
        from agent_vault.database.filter_helpers import from_dict

        with pytest.raises(TypeError, match="[Nn]ested.*not supported"):
            from_dict({"metadata": {"type": "code"}})

    def test_set_values_supported(self) -> None:
        """Set values are converted to IN filter."""
        from agent_vault.database.filter_helpers import from_dict

        result = from_dict({"type": {"code", "doc"}})
        assert result is not None
        assert result.operator == FilterOperator.IN
        assert result.field == "type"
        assert result.values is not None
        # Order may vary since it's a set
        assert set(result.values) == {"code", "doc"}


class TestProjectScoped:
    """Tests for project_scoped helper."""

    def test_project_only(self) -> None:
        """Project ID only creates simple EQ filter."""
        from agent_vault.database.filter_helpers import project_scoped

        result = project_scoped("proj_001")
        assert result.operator == FilterOperator.EQ
        assert result.field == "project_id"
        assert result.value == "proj_001"

    def test_project_with_additional_filter(self) -> None:
        """Project ID with additional filter creates AND."""
        from agent_vault.database.filter_helpers import project_scoped

        additional = eq("status", "active")
        result = project_scoped("proj_001", additional)
        assert result.operator == FilterOperator.AND
        # Left should be project filter
        assert result.left is not None
        assert result.left.operator == FilterOperator.EQ
        assert result.left.field == "project_id"
        # Right should be additional filter
        assert result.right is not None
        assert result.right.operator == FilterOperator.EQ
        assert result.right.field == "status"

    def test_project_with_none_additional(self) -> None:
        """Project ID with None additional returns just project filter."""
        from agent_vault.database.filter_helpers import project_scoped

        result = project_scoped("proj_001", None)
        assert result.operator == FilterOperator.EQ
        assert result.field == "project_id"


class TestById:
    """Tests for by_id helper."""

    def test_simple_id_lookup(self) -> None:
        """Simple ID lookup creates EQ filter."""
        from agent_vault.database.filter_helpers import by_id

        result = by_id("entity_id", "ent_001")
        assert result.operator == FilterOperator.EQ
        assert result.field == "entity_id"
        assert result.value == "ent_001"

    def test_id_with_custom_field(self) -> None:
        """ID lookup with custom field name."""
        from agent_vault.database.filter_helpers import by_id

        result = by_id("doc_id", "doc_123")
        assert result.operator == FilterOperator.EQ
        assert result.field == "doc_id"
        assert result.value == "doc_123"


class TestByType:
    """Tests for by_type helper."""

    def test_single_type(self) -> None:
        """Single type creates EQ filter."""
        from agent_vault.database.filter_helpers import by_type

        result = by_type("function")
        assert result.operator == FilterOperator.EQ
        assert result.field == "type"
        assert result.value == "function"

    def test_type_with_custom_field(self) -> None:
        """Type filter with custom field name."""
        from agent_vault.database.filter_helpers import by_type

        result = by_type("class", field="entity_type")
        assert result.operator == FilterOperator.EQ
        assert result.field == "entity_type"
        assert result.value == "class"


class TestCombineFilters:
    """Tests for combine_filters helper."""

    def test_no_filters_returns_none(self) -> None:
        """No filters returns None."""
        from agent_vault.database.filter_helpers import combine_filters

        result = combine_filters()
        assert result is None

    def test_all_none_returns_none(self) -> None:
        """All None filters returns None."""
        from agent_vault.database.filter_helpers import combine_filters

        result = combine_filters(None, None, None)
        assert result is None

    def test_single_filter_returns_filter(self) -> None:
        """Single non-None filter returns that filter."""
        from agent_vault.database.filter_helpers import combine_filters

        f = eq("status", "active")
        result = combine_filters(f)
        assert result is f

    def test_single_filter_among_nones(self) -> None:
        """Single non-None filter among Nones returns that filter."""
        from agent_vault.database.filter_helpers import combine_filters

        f = eq("status", "active")
        result = combine_filters(None, f, None)
        assert result is f

    def test_two_filters_combined_with_and(self) -> None:
        """Two filters combined with AND."""
        from agent_vault.database.filter_helpers import combine_filters

        f1 = eq("status", "active")
        f2 = eq("type", "code")
        result = combine_filters(f1, f2)
        assert result is not None
        assert result.operator == FilterOperator.AND

    def test_multiple_filters_combined(self) -> None:
        """Multiple filters combined with nested AND."""
        from agent_vault.database.filter_helpers import combine_filters

        f1 = eq("status", "active")
        f2 = eq("type", "code")
        f3 = is_not_null("name")
        result = combine_filters(f1, f2, f3)
        assert result is not None
        assert result.operator == FilterOperator.AND

    def test_mixed_filters_and_nones(self) -> None:
        """Mixed filters and Nones - Nones are ignored."""
        from agent_vault.database.filter_helpers import combine_filters

        f1 = eq("status", "active")
        f2 = eq("type", "code")
        result = combine_filters(f1, None, f2, None)
        assert result is not None
        assert result.operator == FilterOperator.AND


class TestIdInList:
    """Tests for id_in_list helper."""

    def test_single_id_becomes_eq(self) -> None:
        """Single ID optimizes to EQ."""
        from agent_vault.database.filter_helpers import id_in_list

        result = id_in_list("doc_id", ["doc1"])
        assert result.operator == FilterOperator.EQ
        assert result.field == "doc_id"
        assert result.value == "doc1"

    def test_multiple_ids_becomes_in(self) -> None:
        """Multiple IDs become IN."""
        from agent_vault.database.filter_helpers import id_in_list

        result = id_in_list("doc_id", ["doc1", "doc2", "doc3"])
        assert result.operator == FilterOperator.IN
        assert result.field == "doc_id"
        assert result.values is not None
        assert list(result.values) == ["doc1", "doc2", "doc3"]

    def test_empty_list_becomes_false(self) -> None:
        """Empty list creates IN that translates to FALSE."""
        from agent_vault.database.filter_helpers import id_in_list

        result = id_in_list("doc_id", [])
        assert result.operator == FilterOperator.IN
        assert result.field == "doc_id"
        assert result.values is not None
        assert list(result.values) == []


class TestFilePath:
    """Tests for file_path helper."""

    def test_file_path_creates_eq(self) -> None:
        """File path creates EQ filter."""
        from agent_vault.database.filter_helpers import file_path

        result = file_path("/src/main.py")
        assert result.operator == FilterOperator.EQ
        assert result.field == "file_path"
        assert result.value == "/src/main.py"


class TestSourceTarget:
    """Tests for source_id and target_id helpers."""

    def test_source_id(self) -> None:
        """Source ID creates EQ filter."""
        from agent_vault.database.filter_helpers import source_id

        result = source_id("ent_001")
        assert result.operator == FilterOperator.EQ
        assert result.field == "source_id"
        assert result.value == "ent_001"

    def test_target_id(self) -> None:
        """Target ID creates EQ filter."""
        from agent_vault.database.filter_helpers import target_id

        result = target_id("ent_002")
        assert result.operator == FilterOperator.EQ
        assert result.field == "target_id"
        assert result.value == "ent_002"


class TestTranslationIntegration:
    """Integration tests verifying helpers work with translator."""

    def test_from_dict_translates_correctly(self) -> None:
        """from_dict results translate correctly."""
        from agent_vault.database.filter_helpers import from_dict
        from agent_vault.database.filters import translate_filter

        result = from_dict({"status": "active", "type": ["code", "doc"]})
        assert result is not None
        sql = translate_filter(result)
        assert sql is not None
        # Should contain both conditions
        assert "status = 'active'" in sql
        assert "type IN" in sql
        assert "'code'" in sql
        assert "'doc'" in sql

    def test_project_scoped_translates_correctly(self) -> None:
        """project_scoped results translate correctly."""
        from agent_vault.database.filter_helpers import project_scoped
        from agent_vault.database.filters import translate_filter

        result = project_scoped("proj_001", eq("status", "active"))
        sql = translate_filter(result)
        assert sql is not None
        assert "project_id = 'proj_001'" in sql
        assert "status = 'active'" in sql
        assert "AND" in sql

    def test_combine_filters_translates_correctly(self) -> None:
        """combine_filters results translate correctly."""
        from agent_vault.database.filter_helpers import combine_filters
        from agent_vault.database.filters import translate_filter

        result = combine_filters(
            eq("project_id", "proj_001"),
            eq("status", "active"),
            is_in("type", ["code", "doc"]),
        )
        assert result is not None
        sql = translate_filter(result)
        assert sql is not None
        assert "project_id = 'proj_001'" in sql
        assert "status = 'active'" in sql
        assert "type IN" in sql
