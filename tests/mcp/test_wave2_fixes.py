"""Regression tests for Wave 2.0 critical fixes.

These tests verify the fixes for:
- ISS-W2-001: graph_traverse uses "type" field for relationships
- ISS-W2-002: Entity resolver prefers internal entities over external
- ISS-W2-004: Relationship resolver logs resolution attempts
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock
from agent_vault.mcp.services.entity_resolver import EntityResolver
from agent_vault.models.graph_entity import EntityType


class TestGraphTraverseTypeField:
    """Tests for ISS-W2-001: graph_traverse relationship type field fix."""

    @pytest.fixture
    def mock_services(self):
        """Create mock services dict for graph_traverse."""
        mock_db_manager = AsyncMock()
        mock_session_manager = AsyncMock()
        mock_event_system = AsyncMock()
        mock_config = MagicMock()

        # Mock session validation and lookup
        mock_session_manager.validate_session.return_value = True
        mock_session_manager.get_session.return_value = MagicMock(
            project_id="test_project"
        )

        # Mock config for graph_traverse
        mock_config.mcp.query.default_limit = 50
        mock_config.mcp.query.max_limit = 1000
        mock_config.search.graph_search.timeouts.graph_traverse_ms = 5000

        return {
            "storage": mock_db_manager,
            "session_manager": mock_session_manager,
            "event_system": mock_event_system,
            "config": mock_config
        }

    @pytest.mark.asyncio
    async def test_graph_traverse_filters_by_type_field(self, mock_services):
        """Verify graph_traverse filters relationships using 'type' field, not 'relationship_type'."""
        from agent_vault.mcp.tools.direct_access import graph_traverse

        mock_db = mock_services["storage"]

        # Mock start entity lookup and relationship queries
        mock_db.advanced_filter.side_effect = [
            # First call: find start entity
            [{"id": "entity_001", "name": "SearchService", "type": "class", "file_path": "src/search.py"}],
            # Second call: outbound relationships (imports, calls, inherits)
            [
                {"source_id": "entity_001", "target_id": "entity_002", "type": "imports", "metadata": {}},
                {"source_id": "entity_001", "target_id": "entity_003", "type": "calls", "metadata": {}},
                {"source_id": "entity_001", "target_id": "entity_004", "type": "inherits", "metadata": {}},
            ],
            # Third call: inbound relationships (empty for simplicity)
            [],
            # Subsequent calls for neighbor entity lookups
            [{"id": "entity_002", "name": "Config", "type": "class", "file_path": "src/config.py"}],
        ]

        # Test: filter to only "imports" relationships
        result = await graph_traverse(
            services=mock_services,
            session_id="sess_123",
            start_id="entity_001",
            relationship_types=["imports"],  # Only want imports
            direction="both",
            max_depth=1
        )

        # Verify success (no "status" key means success - errors have "status": "failed")
        assert "status" not in result or result.get("status") != "failed"
        # Verify only "imports" relationships are returned in edges
        assert len(result["edges"]) == 1
        assert result["edges"][0]["type"] == "imports"
        assert result["edges"][0]["target"] == "entity_002"

    @pytest.mark.asyncio
    async def test_graph_traverse_type_filter_is_case_insensitive(self, mock_services):
        """Verify graph_traverse type filtering is case-insensitive."""
        from agent_vault.mcp.tools.direct_access import graph_traverse

        mock_db = mock_services["storage"]

        mock_db.advanced_filter.side_effect = [
            # Start entity
            [{"id": "entity_001", "name": "MyClass", "type": "class", "file_path": "src/my.py"}],
            # Outbound relationships with different case types
            [
                {"source_id": "entity_001", "target_id": "entity_002", "type": "IMPORTS", "metadata": {}},
                {"source_id": "entity_001", "target_id": "entity_003", "type": "Calls", "metadata": {}},
            ],
            # Inbound
            [],
            # Neighbor lookups
            [{"id": "entity_002", "name": "Dep", "type": "class", "file_path": "src/dep.py"}],
        ]

        # Filter with lowercase - should match "IMPORTS" (uppercase in DB)
        result = await graph_traverse(
            services=mock_services,
            session_id="sess_123",
            start_id="entity_001",
            relationship_types=["imports"],  # lowercase
            direction="both",
            max_depth=1
        )

        # Verify success (no "status" key means success - errors have "status": "failed")
        assert "status" not in result or result.get("status") != "failed"
        # Should match despite case difference
        assert len(result["edges"]) == 1
        assert result["edges"][0]["type"] == "IMPORTS"

    @pytest.mark.asyncio
    async def test_graph_traverse_invalid_max_depth_returns_error(self, mock_services):
        """Verify graph_traverse returns validation error for invalid max_depth."""
        from agent_vault.mcp.tools.direct_access import graph_traverse

        # Test max_depth = 0 (below minimum)
        result = await graph_traverse(
            services=mock_services,
            session_id="sess_123",
            start_id="entity_001",
            max_depth=0
        )

        assert result["status"] == "failed"
        assert result["error_type"] == "validation_error"
        assert "max_depth must be between 1 and 5" in result["error"]

        # Test max_depth = 10 (above maximum)
        result = await graph_traverse(
            services=mock_services,
            session_id="sess_123",
            start_id="entity_001",
            max_depth=10
        )

        assert result["status"] == "failed"
        assert result["error_type"] == "validation_error"
        assert "max_depth must be between 1 and 5" in result["error"]

    @pytest.mark.asyncio
    async def test_graph_traverse_invalid_direction_returns_error(self, mock_services):
        """Verify graph_traverse returns validation error for invalid direction."""
        from agent_vault.mcp.tools.direct_access import graph_traverse

        result = await graph_traverse(
            services=mock_services,
            session_id="sess_123",
            start_id="entity_001",
            direction="sideways"  # Invalid direction
        )

        assert result["status"] == "failed"
        assert result["error_type"] == "validation_error"
        assert "direction must be one of" in result["error"]

    @pytest.mark.asyncio
    async def test_graph_traverse_entity_not_found_returns_error(self, mock_services):
        """Verify graph_traverse returns helpful error when entity not found."""
        from agent_vault.mcp.tools.direct_access import graph_traverse

        mock_db = mock_services["storage"]

        # All entity lookup attempts return empty
        mock_db.advanced_filter.return_value = []

        result = await graph_traverse(
            services=mock_services,
            session_id="sess_123",
            start_id="NonExistentEntity",
            max_depth=2
        )

        assert result["status"] == "failed"
        assert result["error_type"] == "entity_not_found"
        assert "NonExistentEntity" in result["error"]
        assert "suggestions" in result
        assert len(result["suggestions"]) > 0


class TestEntityResolverPreference:
    """Tests for ISS-W2-002: Entity resolver internal preference fix."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager."""
        db = AsyncMock()
        return db

    @pytest.fixture
    def mock_storage_facade(self, mock_db_manager):
        """Create mock StorageFacade that wraps the mock_db_manager."""
        mock_storage = MagicMock()
        mock_storage.get_db_manager = MagicMock(return_value=mock_db_manager)
        # EntityResolver calls query_entities directly on db_manager (StorageFacade)
        mock_storage.query_entities = AsyncMock(return_value=[])
        mock_storage.query_relationships = AsyncMock(return_value=[])
        return mock_storage

    @pytest.fixture
    def mock_config(self):
        """Create a mock config with entity resolution settings."""
        config = MagicMock()
        config.entity_resolution.cache_enabled = False
        config.entity_resolution.case_insensitive = True
        config.entity_resolution.fuzzy_matching.enabled = False
        # MCP query config limits
        config.mcp.query.default_limit = 1000
        config.mcp.query.traversal_limit = 100
        return config

    @pytest.fixture
    def resolver(self, mock_storage_facade, mock_config):
        """Create an entity resolver instance."""
        return EntityResolver(db_manager=mock_storage_facade, config=mock_config)

    @pytest.mark.asyncio
    async def test_exact_match_prefers_code_class_over_external(
        self, resolver, mock_storage_facade
    ):
        """Verify _exact_match prefers code_class over external_module."""
        # Simulate DB returning external_module first, then code_class
        mock_storage_facade.query_entities.return_value = [
            {
                "id": "ext_001",
                "name": "LanceDBManager",
                "type": EntityType.EXTERNAL_MODULE.value,
                "file_path": "external://python/LanceDBManager",
            },
            {
                "id": "cls_001",
                "name": "LanceDBManager",
                "type": EntityType.CODE_CLASS.value,
                "file_path": "agent_vault/database/lancedb_manager.py",
            },
        ]

        result = await resolver._exact_match("LanceDBManager", "test_project")

        assert result is not None
        assert result.entity_type == EntityType.CODE_CLASS.value
        assert result.file_path == "agent_vault/database/lancedb_manager.py"

    @pytest.mark.asyncio
    async def test_exact_match_prefers_code_function_over_external(
        self, resolver, mock_storage_facade
    ):
        """Verify _exact_match prefers code_function over external_function."""
        mock_storage_facade.query_entities.return_value = [
            {
                "id": "ext_001",
                "name": "process_data",
                "type": EntityType.EXTERNAL_FUNCTION.value,
                "file_path": "external://python/process_data",
            },
            {
                "id": "fn_001",
                "name": "process_data",
                "type": EntityType.CODE_FUNCTION.value,
                "file_path": "src/processing.py",
            },
        ]

        result = await resolver._exact_match("process_data", "test_project")

        assert result is not None
        assert result.entity_type == EntityType.CODE_FUNCTION.value

    @pytest.mark.asyncio
    async def test_exact_match_falls_back_to_first_if_no_preferred(
        self, resolver, mock_storage_facade
    ):
        """Verify _exact_match falls back to first result if no preferred type."""
        mock_storage_facade.query_entities.return_value = [
            {
                "id": "ext_001",
                "name": "some_external",
                "type": EntityType.EXTERNAL_MODULE.value,
                "file_path": "external://lib/some_external",
            },
            {
                "id": "ext_002",
                "name": "some_external",
                "type": EntityType.EXTERNAL_FUNCTION.value,
                "file_path": "external://lib/some_external",
            },
        ]

        result = await resolver._exact_match("some_external", "test_project")

        # Falls back to first result since no preferred types
        assert result is not None
        assert result.entity_type == EntityType.EXTERNAL_MODULE.value

    @pytest.mark.asyncio
    async def test_exact_match_respects_explicit_type_filter(
        self, resolver, mock_storage_facade
    ):
        """Verify _exact_match respects explicit entity_type parameter."""
        mock_storage_facade.query_entities.return_value = [
            {
                "id": "ext_001",
                "name": "Config",
                "type": EntityType.EXTERNAL_MODULE.value,
                "file_path": "external://python/Config",
            },
        ]

        result = await resolver._exact_match(
            "Config", "test_project", entity_type=EntityType.EXTERNAL_MODULE.value
        )

        assert result is not None
        assert result.entity_type == EntityType.EXTERNAL_MODULE.value
        # When type is specified, limit=1 is used
        mock_storage_facade.query_entities.assert_called_once()
        call_args = mock_storage_facade.query_entities.call_args
        assert call_args.kwargs["limit"] == 1

    @pytest.mark.asyncio
    async def test_case_insensitive_match_prefers_internal(
        self, resolver, mock_storage_facade
    ):
        """Verify _case_insensitive_match also prefers internal entities."""
        mock_storage_facade.query_entities.return_value = [
            {
                "id": "ext_001",
                "name": "SearchService",
                "type": EntityType.EXTERNAL_CLASS.value,
                "file_path": "external://lib/SearchService",
            },
            {
                "id": "cls_001",
                "name": "searchservice",  # Different case
                "type": EntityType.CODE_CLASS.value,
                "file_path": "src/search/service.py",
            },
        ]

        result = await resolver._case_insensitive_match(
            "SEARCHSERVICE", "test_project"
        )

        # Should find the code_class match (case-insensitive) and prefer it
        # Note: Both have names that match case-insensitively
        assert result is not None
        assert result.entity_type == EntityType.CODE_CLASS.value

    @pytest.mark.asyncio
    async def test_single_result_returned_directly(
        self, resolver, mock_storage_facade
    ):
        """Verify single result is returned without preference logic."""
        mock_storage_facade.query_entities.return_value = [
            {
                "id": "ext_001",
                "name": "OnlyOneMatch",
                "type": EntityType.EXTERNAL_MODULE.value,
                "file_path": "external://lib/OnlyOneMatch",
            },
        ]

        result = await resolver._exact_match("OnlyOneMatch", "test_project")

        assert result is not None
        # Single result returned directly, no preference logic
        assert result.entity_type == EntityType.EXTERNAL_MODULE.value


class TestRelationshipResolverLogging:
    """Tests for ISS-W2-004: Relationship resolver logging."""

    @pytest.fixture
    def mock_symbol_registry(self):
        """Create a mock symbol registry."""
        registry = MagicMock()
        registry.lookup = MagicMock(return_value=None)
        registry.fuzzy_lookup = MagicMock(return_value=[])
        return registry

    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager for resolver."""
        db = AsyncMock()
        db.advanced_filter = AsyncMock(return_value=[])
        db.query_entities = AsyncMock(return_value=[])
        return db

    @pytest.fixture
    def resolver(self, mock_symbol_registry, mock_db_manager, tmp_path):
        """Create a RelationshipResolver instance."""
        from agent_vault.indexing.relationship_resolver import RelationshipResolver

        return RelationshipResolver(
            symbol_registry=mock_symbol_registry,
            project_root=str(tmp_path),
            db_manager=mock_db_manager,
            enable_cache_prewarming=False,  # Disable for faster tests
            skip_database_lookups=False  # Enable DB lookups for logging test
        )

    @pytest.mark.asyncio
    async def test_resolve_impl_logs_strategy_attempts(self, resolver, caplog):
        """Verify _resolve_impl logs strategy attempts at runtime."""
        import logging

        # Capture debug logs
        with caplog.at_level(logging.DEBUG, logger="agent_vault.indexing.relationship_resolver"):
            # Call _resolve_impl - it will fail to resolve (no matching entities)
            _result = await resolver._resolve_impl(
                target_name="NonExistentSymbol",
                target_type=None,
                source_file="test.py",
                source_language="python",
                import_path=None
            )
            assert _result is None  # Confirms resolution failed

        # Verify logging occurred
        log_messages = [record.message for record in caplog.records]

        # Check strategy attempt logging
        strategy_logs = [m for m in log_messages if "Trying resolution strategy" in m]
        assert len(strategy_logs) > 0, "Expected 'Trying resolution strategy' debug logs"

        # Check that multiple strategies were tried
        assert any("database" in m for m in strategy_logs), "Expected 'database' strategy attempt"
        assert any("symbol" in m for m in strategy_logs), "Expected 'symbol' strategy attempt"

    @pytest.mark.asyncio
    async def test_resolve_impl_logs_warning_on_failure(self, resolver, caplog):
        """Verify _resolve_impl logs warning when all strategies fail."""
        import logging

        with caplog.at_level(logging.WARNING, logger="agent_vault.indexing.relationship_resolver"):
            result = await resolver._resolve_impl(
                target_name="UnresolvableSymbol",
                target_type=None,
                source_file="src/module.py",
                source_language="python",
                import_path=None
            )

        # Result should be None (unresolved)
        assert result is None

        # Verify warning log for failure
        warning_logs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("after trying all strategies" in m for m in warning_logs), \
            "Expected warning about failing all strategies"
