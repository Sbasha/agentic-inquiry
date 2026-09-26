"""Integration tests for ai Entity Tool Fixes (ISS-001, ISS-002, ISS-003/004).

These tests verify the fixes implemented for:
- ISS-001: Entity Type System - type/domain separation
- ISS-002: find_similar clustering - diversity filtering
- ISS-003/004: project_id propagation

Run with: pytest tests/mcp/test_entity_tool_fixes_integration.py -v
"""

import pytest

pytestmark = [pytest.mark.integration]


class TestEntityTypeSystemFix:
    """Tests for ISS-001: Entity Type System changes.

    Verifies that entity types now use plain structural names
    (e.g., "class", "function", "method") instead of "code_*" prefixes.
    """

    def test_entity_type_enum_values(self):
        """EntityType enum values should be plain types without code_ prefix."""
        from agentic_inquiry.models.graph_entity import EntityType

        # Verify plain type values
        assert EntityType.CODE_FUNCTION.value == "function"
        assert EntityType.CODE_CLASS.value == "class"
        assert EntityType.CODE_METHOD.value == "method"
        assert EntityType.CODE_MODULE.value == "module"
        assert EntityType.CODE_VARIABLE.value == "variable"
        assert EntityType.CODE_INTERFACE.value == "interface"
        assert EntityType.CODE_ENUM.value == "enum"
        assert EntityType.CODE_STRUCT.value == "struct"
        assert EntityType.CODE_NAMESPACE.value == "namespace"

    def test_entity_type_normalize_plain_types(self):
        """EntityType.normalize() should pass through plain types."""
        from agentic_inquiry.models.graph_entity import EntityType

        assert EntityType.normalize("function") == "function"
        assert EntityType.normalize("class") == "class"
        assert EntityType.normalize("method") == "method"
        assert EntityType.normalize("module") == "module"

    def test_entity_type_normalize_legacy_prefix(self):
        """EntityType.normalize() should strip code_ prefix for legacy types."""
        from agentic_inquiry.models.graph_entity import EntityType

        # Legacy code_* prefixed types should be normalized
        assert EntityType.normalize("code_function") == "function"
        assert EntityType.normalize("code_class") == "class"
        assert EntityType.normalize("code_method") == "method"
        assert EntityType.normalize("CODE_MODULE") == "module"  # Case insensitive

    def test_entity_type_normalize_aliases(self):
        """EntityType.normalize() should handle type aliases."""
        from agentic_inquiry.models.graph_entity import EntityType

        # Constant -> variable alias
        assert EntityType.normalize("constant") == "variable"
        # Field -> property alias
        assert EntityType.normalize("field") == "property"

    def test_graph_entity_has_domain_field(self):
        """GraphEntity should have domain field with default 'code'."""
        from agentic_inquiry.models.graph_entity import GraphEntity

        entity = GraphEntity(
            id="test-1",
            name="TestClass",
            type="class",
            file_path="/test/path.py",
            doc_id="doc-1",
            project_id="test-project",
            vector=[0.1] * 384,
        )

        # Domain should default to "code"
        assert entity.domain == "code"

        # Verify can set custom domain
        entity_with_domain = GraphEntity(
            id="test-2",
            name="TestOntology",
            type="class",
            domain="ontology",
            file_path="/test/ontology.owl",
            doc_id="doc-2",
            project_id="test-project",
            vector=[0.1] * 384,
        )
        assert entity_with_domain.domain == "ontology"

    def test_code_entity_types_set(self):
        """CODE_ENTITY_TYPES should contain plain types."""
        from agentic_inquiry.mcp.tools.search import CODE_ENTITY_TYPES

        # Should have plain types, not code_ prefixed
        assert "class" in CODE_ENTITY_TYPES
        assert "function" in CODE_ENTITY_TYPES
        assert "method" in CODE_ENTITY_TYPES

        # Should NOT have code_ prefixed types
        assert "code_class" not in CODE_ENTITY_TYPES
        assert "code_function" not in CODE_ENTITY_TYPES

    def test_parser_type_mapping(self):
        """Parser type mapping should return plain types."""
        from agentic_inquiry.parsers.implementations.unified_code import CodeUtilities

        mapping = CodeUtilities.get_element_type_mapping()

        # Verify plain type mappings
        assert mapping["function"] == "function"
        assert mapping["method"] == "method"
        assert mapping["class"] == "class"
        assert mapping["struct"] == "struct"
        assert mapping["interface"] == "interface"


class TestFindSimilarDiversity:
    """Tests for ISS-002: find_similar clustering fix.

    Verifies that diversify_entity_results() properly limits
    results per file and interleaves from different files.
    """

    def test_diversify_function_exists(self):
        """diversify_entity_results function should be importable."""
        from agentic_inquiry.mcp.tools.search import diversify_entity_results

        assert callable(diversify_entity_results)

    def test_diversify_limits_per_file(self):
        """diversify_entity_results should limit entities per file."""
        from agentic_inquiry.mcp.tools.search import diversify_entity_results

        # Create 5 entities from same file
        entities = [
            {"name": f"Entity{i}", "file_path": "/same/file.py", "similarity": 0.9}
            for i in range(5)
        ]

        result = diversify_entity_results(entities, limit=10, max_per_file=2)

        # Should only have 2 from the same file
        assert len(result) == 2

    def test_diversify_interleaves_files(self):
        """diversify_entity_results should interleave results from different files."""
        from agentic_inquiry.mcp.tools.search import diversify_entity_results

        # Create entities from different files
        entities = [
            {"name": "A1", "file_path": "/file_a.py", "similarity": 0.95},
            {"name": "A2", "file_path": "/file_a.py", "similarity": 0.90},
            {"name": "A3", "file_path": "/file_a.py", "similarity": 0.85},
            {"name": "B1", "file_path": "/file_b.py", "similarity": 0.94},
            {"name": "B2", "file_path": "/file_b.py", "similarity": 0.89},
            {"name": "C1", "file_path": "/file_c.py", "similarity": 0.93},
        ]

        result = diversify_entity_results(entities, limit=10, max_per_file=2)

        # Should have 5 results: 2 from A, 2 from B, 1 from C
        assert len(result) == 5

        # Verify file diversity
        file_counts = {}
        for entity in result:
            fp = entity["file_path"]
            file_counts[fp] = file_counts.get(fp, 0) + 1

        assert file_counts["/file_a.py"] == 2
        assert file_counts["/file_b.py"] == 2
        assert file_counts["/file_c.py"] == 1

    def test_diversify_respects_limit(self):
        """diversify_entity_results should respect the limit parameter."""
        from agentic_inquiry.mcp.tools.search import diversify_entity_results

        # Create 10 entities across 5 files
        entities = []
        for i in range(5):
            for j in range(2):
                entities.append(
                    {
                        "name": f"Entity_{i}_{j}",
                        "file_path": f"/file_{i}.py",
                        "similarity": 0.9 - i * 0.1,
                    }
                )

        result = diversify_entity_results(entities, limit=5, max_per_file=2)

        # Should respect limit
        assert len(result) == 5

    def test_diversify_empty_input(self):
        """diversify_entity_results should handle empty input."""
        from agentic_inquiry.mcp.tools.search import diversify_entity_results

        result = diversify_entity_results([], limit=10, max_per_file=2)
        assert result == []

    def test_diversify_preserves_order_within_file(self):
        """diversify_entity_results should preserve ranking order within each file."""
        from agentic_inquiry.mcp.tools.search import diversify_entity_results

        entities = [
            {"name": "BestA", "file_path": "/a.py", "similarity": 0.99},
            {"name": "SecondA", "file_path": "/a.py", "similarity": 0.90},
            {"name": "ThirdA", "file_path": "/a.py", "similarity": 0.80},
        ]

        result = diversify_entity_results(entities, limit=10, max_per_file=2)

        # Should keep the top 2 in order
        assert result[0]["name"] == "BestA"
        assert result[1]["name"] == "SecondA"


class TestProjectIdPropagation:
    """Tests for ISS-003/ISS-004: project_id propagation fix.

    Verifies that project_id flows correctly through the storage chain.
    """

    def test_lancedb_manager_from_config_accepts_project_id(self):
        """LanceDBManager.from_config() should accept project_id parameter."""
        from agentic_inquiry.database.lancedb_manager import LanceDBManager
        import inspect

        sig = inspect.signature(LanceDBManager.from_config)
        params = list(sig.parameters.keys())

        assert "project_id" in params

    @pytest.mark.asyncio
    async def test_lancedb_provider_from_config_stores_project_id(self, tmp_path):
        """LanceDBProvider.from_config() should store and propagate project_id."""
        from agentic_inquiry.storage.providers.lancedb import LanceDBProvider
        from agentic_inquiry.config import Config

        # Create a minimal config for testing
        config = Config.load()
        # Override storage root to use temp directory
        config.storage.root = str(tmp_path)

        test_project_id = "test_project_123"
        provider = await LanceDBProvider.from_config(config, test_project_id)

        # Verify project_id is stored on the provider
        assert provider._project_id == test_project_id

        # Verify the manager was created with the correct project_id
        assert provider._db_manager is not None
        assert provider._db_manager.project_id == test_project_id

    def test_lancedb_provider_init_stores_project_id(self):
        """LanceDBProvider.__init__() should store project_id for lazy init."""
        from agentic_inquiry.storage.providers.lancedb import LanceDBProvider
        from agentic_inquiry.config import Config

        config = Config.load()
        test_project_id = "lazy_init_project"

        # Create provider without db_manager (will lazy init)
        provider = LanceDBProvider(config, test_project_id, db_manager=None)

        # Verify project_id is stored for later use in initialize()
        assert provider._project_id == test_project_id
        assert provider._db_manager is None  # Not yet initialized


class TestEndToEndIntegration:
    """End-to-end integration tests combining all fixes.

    These tests verify that the components work together correctly
    by checking code paths and static analysis rather than full
    end-to-end execution (which requires more complex fixtures).
    """

    def test_list_entities_accepts_plain_types(self):
        """list_entities MCP tool should accept plain type names."""
        from agentic_inquiry.mcp.tools.info import list_entities
        import inspect

        sig = inspect.signature(list_entities)
        params = list(sig.parameters.keys())

        # Should have entity_type parameter
        assert "entity_type" in params

    def test_find_similar_has_diversity_integration(self):
        """find_similar should integrate diversify_entity_results for entities."""
        from agentic_inquiry.mcp.tools.search import find_similar
        import inspect

        source = inspect.getsource(find_similar)

        # Verify diversity filter is called for entities scope
        assert "diversify_entity_results" in source
        assert 'effective_scope == "entities"' in source

    def test_entity_type_normalization_in_filters(self):
        """Filter helpers should use EntityType.normalize for type filtering."""
        from agentic_inquiry.database.filter_helpers import by_type
        from agentic_inquiry.models.graph_entity import EntityType

        # Create filter with plain type
        filter_obj = by_type("function")

        # Verify filter was created with normalized value
        assert filter_obj.value == EntityType.normalize("function")
        assert filter_obj.value == "function"

        # Legacy type should also normalize
        filter_legacy = by_type("code_class")
        assert filter_legacy.value == "class"


# Pytest fixtures from conftest.py are automatically available
