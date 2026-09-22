"""Unit tests for GraphSearchService."""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agent_vault.search.graph_search import GraphSearchService


@pytest.fixture
def mock_storage_facade():
    """Create a mock StorageFacade with async methods for GraphSearchService."""
    mock_storage = MagicMock()
    mock_storage.project_id = "test_project"
    # Add async mock methods that GraphSearchService uses directly
    mock_storage.query_raw = AsyncMock(return_value=[])
    mock_storage.vector_search_raw = AsyncMock(return_value=[])
    mock_storage.query_across_projects = AsyncMock(return_value=[])
    mock_storage.list_tables = AsyncMock(return_value=["graph_entities", "graph_relationships"])
    return mock_storage


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = MagicMock()
    config.mcp.relationships.max_per_node = 100
    config.mcp.query.default_limit = 50
    config.mcp.query.max_limit = 1000
    config.search.default_limit = 10
    config.search.graph_search.max_depth = 3
    config.embeddings.provider = "sentence_transformers"
    config.embeddings.model_name = "all-MiniLM-L6-v2"
    return config


@pytest.fixture
def graph_search_service(mock_storage_facade, mock_config):
    """Create a GraphSearchService instance."""
    return GraphSearchService(
        storage=mock_storage_facade,
        config=mock_config,
    )


class TestGraphSearchService:
    """Tests for GraphSearchService."""

    @pytest.mark.unit
    async def test_traverse_relationships_basic(self, graph_search_service, mock_storage_facade):
        """Test basic relationship traversal."""
        # Setup mock data
        start_entity = {
            "id": "entity_1",
            "name": "TestEntity",
            "type": "function",
            "doc_id": "doc_1",
        }
        # Mock will return start entity first, then empty list for relationships
        mock_storage_facade.query_raw.side_effect = [
            [start_entity],  # First call for start entity
            [],  # Second call for relationships
        ]

        # Execute
        result = await graph_search_service.traverse_relationships(
            entity_id="entity_1",
            max_depth=1,
            direction="outgoing",
        )

        # Verify
        assert result["entity"] == start_entity
        assert result["depth_reached"] == 1
        assert isinstance(result["relationships"], list)

        # Verify correct query construction
        # First call: get entity by ID
        first_call = mock_storage_facade.query_raw.call_args_list[0]
        assert first_call.kwargs['table_name'] == "graph_entities"
        assert first_call.kwargs['filters'] == {'id': 'entity_1'}

        # Second call: get relationships (outgoing = source_id is entity)
        rel_call = mock_storage_facade.query_raw.call_args_list[1]
        assert rel_call.kwargs['table_name'] == "graph_relationships"

        # Check that we are filtering for the entity as source (outgoing)
        filters = rel_call.kwargs['filters']
        assert 'source_id' in filters
        # The source_id filter should contain entity_1
        val = filters['source_id']
        assert 'entity_1' in str(val)

    @pytest.mark.unit
    async def test_traverse_relationships_not_found(self, graph_search_service, mock_storage_facade):
        """Test traversal when entity is not found."""
        # Setup mock to return empty list
        mock_storage_facade.query_raw.return_value = []

        # Execute
        result = await graph_search_service.traverse_relationships(
            entity_id="nonexistent",
            max_depth=1,
        )

        # Verify
        assert result["entity"] is None
        assert "error" in result
        assert result["depth_reached"] == 0

    @pytest.mark.unit
    async def test_traverse_relationships_invalid_direction(self, graph_search_service):
        """Test traversal with invalid direction."""
        with pytest.raises(ValueError, match="Invalid direction"):
            await graph_search_service.traverse_relationships(
                entity_id="entity_1",
                direction="invalid",
            )

    @pytest.mark.unit
    async def test_resolve_entity_exact_match(self, graph_search_service, mock_storage_facade):
        """Test entity resolution with exact match."""
        # Setup mock data
        entity = {
            "id": "entity_1",
            "name": "TestEntity",
            "type": "function",
            "doc_id": "doc_1",
            "file_path": "/test/file.py",
            "pagerank": 0.5,
        }
        mock_storage_facade.query_raw.return_value = [entity]

        # Execute
        result = await graph_search_service.resolve_entity(
            entity_name="TestEntity",
        )

        # Verify
        assert result["found"] is True
        assert len(result["matches"]) == 1
        assert result["matches"][0]["name"] == "TestEntity"
        assert result["disambiguation_needed"] is False

    @pytest.mark.unit
    async def test_resolve_entity_no_matches(self, graph_search_service, mock_storage_facade):
        """Test entity resolution with no matches."""
        import numpy as np

        # Setup mock to return empty list
        mock_storage_facade.query_raw.return_value = []
        mock_storage_facade.vector_search_raw.return_value = []

        # Mock the embedding service at the module level
        mock_embed_service = AsyncMock()
        mock_embed_service.embed_async = AsyncMock(return_value=np.array([0.1, 0.2, 0.3]))
        graph_search_service._embedding_service = mock_embed_service

        # Execute
        result = await graph_search_service.resolve_entity(
            entity_name="NonexistentEntity",
        )

        # Verify
        assert result["found"] is False
        assert len(result["matches"]) == 0
        assert len(result["suggestions"]) == 0

    @pytest.mark.unit
    async def test_enrich_with_graph_context(self, graph_search_service, mock_storage_facade):
        """Test enriching search results with graph context."""
        # Setup mock data
        search_results = [
            {"doc_id": "doc_1", "content": "test content"},
        ]
        graph_entities = [
            {"doc_id": "doc_1", "name": "Entity1", "type": "function"},
        ]
        mock_storage_facade.query_raw.return_value = graph_entities

        # Execute
        result = await graph_search_service.enrich_with_graph_context(search_results)

        # Verify
        assert len(result) == 1
        assert "graph_context" in result[0]
        assert len(result[0]["graph_context"]) == 1

    @pytest.mark.unit
    async def test_graph_ranking_supported(self, graph_search_service, mock_storage_facade):
        """Test checking if graph ranking is supported."""
        # Execute
        result = await graph_search_service._graph_ranking_supported()

        # Verify
        assert result is True
        mock_storage_facade.list_tables.assert_called_once()

    @pytest.mark.unit
    async def test_graph_ranking_not_supported(self, graph_search_service, mock_storage_facade):
        """Test when graph ranking is not supported."""
        # Setup mock to return tables without graph tables
        mock_storage_facade.list_tables.return_value = ["document_chunks"]

        # Execute
        result = await graph_search_service._graph_ranking_supported()

        # Verify
        assert result is False


class TestGraphTraversalEdgeCases:
    """Edge case tests for graph traversal operations."""

    @pytest.mark.unit
    async def test_traverse_relationships_with_cycle(self, graph_search_service, mock_storage_facade):
        """Test traversal with cycles in the graph (A -> B -> C -> A)."""
        # Setup entities
        entity_a = {
            "id": "entity_a",
            "name": "EntityA",
            "type": "function",
            "doc_id": "doc_a",
        }
        entity_b = {
            "id": "entity_b",
            "name": "EntityB",
            "type": "function",
            "doc_id": "doc_b",
        }
        entity_c = {
            "id": "entity_c",
            "name": "EntityC",
            "type": "function",
            "doc_id": "doc_c",
        }

        # Setup relationships forming a cycle: A -> B -> C -> A
        rel_a_to_b = {
            "id": "rel_1",
            "source_id": "entity_a",
            "target_id": "entity_b",
            "type": "calls",
        }
        rel_b_to_c = {
            "id": "rel_2",
            "source_id": "entity_b",
            "target_id": "entity_c",
            "type": "calls",
        }
        rel_c_to_a = {
            "id": "rel_3",
            "source_id": "entity_c",
            "target_id": "entity_a",
            "type": "calls",
        }

        # Configure mock to return entities and relationships
        mock_storage_facade.query_raw.side_effect = [
            [entity_a],  # Get starting entity
            [rel_a_to_b],  # Depth 1: outgoing from A
            [entity_b],  # Fetch entity B
            [rel_b_to_c],  # Depth 2: outgoing from B
            [entity_c],  # Fetch entity C
            [rel_c_to_a],  # Depth 3: outgoing from C (would cycle back to A)
            [],  # No new entities (A already visited)
        ]

        # Execute with depth that would traverse the cycle
        result = await graph_search_service.traverse_relationships(
            entity_id="entity_a",
            direction="outgoing",
            max_depth=3,
        )

        # Verify cycle is detected and handled correctly
        assert result["entity"]["id"] == "entity_a"
        assert result["total_entities"] == 3  # A, B, C (not duplicate A)
        assert result["total_relationships"] == 3

        # Verify that entity_a is not duplicated in entities
        entity_ids = list(result["entities"].keys())
        assert entity_ids.count("entity_a") == 1

        # Verify relationship to already-visited entity is still recorded
        relationship_ids = [rel["id"] for rel in result["relationships"]]
        assert "rel_3" in relationship_ids  # C -> A relationship should exist

    @pytest.mark.unit
    async def test_traverse_relationships_disconnected_node(self, graph_search_service, mock_storage_facade):
        """Test traversal from a node with no relationships (isolated node)."""
        # Setup an isolated entity with no relationships
        isolated_entity = {
            "id": "isolated_1",
            "name": "IsolatedEntity",
            "type": "function",
            "doc_id": "doc_isolated",
        }

        # Configure mock to return entity but no relationships
        mock_storage_facade.query_raw.side_effect = [
            [isolated_entity],  # Get starting entity
            [],  # No outgoing relationships
        ]

        # Execute
        result = await graph_search_service.traverse_relationships(
            entity_id="isolated_1",
            direction="outgoing",
            max_depth=3,
        )

        # Verify
        assert result["entity"]["id"] == "isolated_1"
        assert result["total_relationships"] == 0
        assert result["total_entities"] == 1  # Only the starting entity
        assert len(result["relationships"]) == 0
        assert result["depth_reached"] == 1  # Stopped at depth 1 due to no relationships

    @pytest.mark.unit
    async def test_traverse_relationships_bidirectional_disconnected(self, graph_search_service, mock_storage_facade):
        """Test bidirectional traversal from an isolated node."""
        isolated_entity = {
            "id": "isolated_2",
            "name": "IsolatedNode",
            "type": "class",
            "doc_id": "doc_isolated_2",
        }

        # Configure mock for both directions
        mock_storage_facade.query_raw.side_effect = [
            [isolated_entity],  # Get starting entity
            [],  # No outgoing relationships
            [],  # No incoming relationships
        ]

        # Execute with "both" direction
        result = await graph_search_service.traverse_relationships(
            entity_id="isolated_2",
            direction="both",
            max_depth=2,
        )

        # Verify
        assert result["entity"]["id"] == "isolated_2"
        assert result["total_relationships"] == 0
        assert result["total_entities"] == 1
        assert result["depth_reached"] == 1

    @pytest.mark.unit
    async def test_traverse_relationships_max_depth_limit(self, graph_search_service, mock_storage_facade):
        """Test that max_depth properly limits traversal depth."""
        # Create a deep chain: A -> B -> C -> D -> E
        entities = [
            {"id": f"entity_{i}", "name": f"Entity{i}", "type": "function", "doc_id": f"doc_{i}"}
            for i in range(5)
        ]

        relationships = [
            {"id": f"rel_{i}", "source_id": f"entity_{i}", "target_id": f"entity_{i+1}", "type": "calls"}
            for i in range(4)
        ]

        # Configure mock to return entities and relationships
        # Depth 1: A -> B
        # Depth 2: B -> C
        # Should stop at depth 2
        mock_storage_facade.query_raw.side_effect = [
            [entities[0]],  # Get starting entity A
            [relationships[0]],  # Depth 1: A -> B
            [entities[1]],  # Fetch entity B
            [relationships[1]],  # Depth 2: B -> C
            [entities[2]],  # Fetch entity C
        ]

        # Execute with max_depth=2
        result = await graph_search_service.traverse_relationships(
            entity_id="entity_0",
            direction="outgoing",
            max_depth=2,
        )

        # Verify traversal stopped at depth 2
        assert result["entity"]["id"] == "entity_0"
        assert result["depth_reached"] == 2
        assert result["total_relationships"] == 2  # Only 2 relationships traversed
        assert result["total_entities"] == 3  # A, B, C (not D or E)

        # Verify depth markers in relationships
        depths = [rel["depth"] for rel in result["relationships"]]
        assert max(depths) == 2
        assert min(depths) == 1

    @pytest.mark.unit
    async def test_traverse_relationships_very_deep_chain(self, graph_search_service, mock_storage_facade):
        """Test traversal of a very deep chain to ensure depth limiting works."""
        # Create a 10-level deep chain but only traverse to depth 5
        start_entity = {
            "id": "entity_start",
            "name": "StartEntity",
            "type": "function",
            "doc_id": "doc_start",
        }

        # We'll simulate finding relationships up to depth 5
        # Each depth finds one new entity
        side_effects = [[start_entity]]  # Start with the initial entity in a list

        for depth in range(1, 6):  # Depths 1-5
            # Add relationship at this depth
            side_effects.append([{
                "id": f"rel_depth_{depth}",
                "source_id": f"entity_depth_{depth-1}" if depth > 1 else "entity_start",
                "target_id": f"entity_depth_{depth}",
                "type": "calls",
            }])
            # Add the target entity
            side_effects.append([{
                "id": f"entity_depth_{depth}",
                "name": f"EntityDepth{depth}",
                "type": "function",
                "doc_id": f"doc_depth_{depth}",
            }])

        mock_storage_facade.query_raw.side_effect = side_effects

        # Execute with max_depth=5
        result = await graph_search_service.traverse_relationships(
            entity_id="entity_start",
            direction="outgoing",
            max_depth=5,
        )

        # Verify
        assert result["depth_reached"] == 5
        assert result["total_relationships"] == 5
        assert result["total_entities"] == 6  # start + 5 more

    @pytest.mark.unit
    async def test_traverse_relationships_empty_graph(self, graph_search_service, mock_storage_facade):
        """Test traversal when the graph has no entities."""
        # Configure mock to return empty list for entity lookup
        mock_storage_facade.query_raw.return_value = []

        # Execute
        result = await graph_search_service.traverse_relationships(
            entity_id="nonexistent",
            direction="outgoing",
            max_depth=3,
        )

        # Verify graceful handling of empty graph
        assert result["entity"] is None
        assert "error" in result
        assert "not found" in result["error"].lower()
        assert result["depth_reached"] == 0
        assert result["relationships"] == []
        assert result["entities"] == {}

    @pytest.mark.unit
    async def test_traverse_relationships_single_node_graph(self, graph_search_service, mock_storage_facade):
        """Test graph with only one node and no relationships."""
        single_entity = {
            "id": "single_1",
            "name": "OnlyEntity",
            "type": "function",
            "doc_id": "doc_single",
        }

        # Configure mock to return single entity but no relationships
        mock_storage_facade.query_raw.side_effect = [
            [single_entity],  # Get the single entity
            [],  # No relationships
        ]

        # Execute
        result = await graph_search_service.traverse_relationships(
            entity_id="single_1",
            direction="outgoing",
            max_depth=10,  # Even with high depth, should handle gracefully
        )

        # Verify
        assert result["entity"]["id"] == "single_1"
        assert result["total_entities"] == 1
        assert result["total_relationships"] == 0
        assert result["depth_reached"] == 1  # Stops early due to no relationships

    @pytest.mark.unit
    async def test_traverse_relationships_self_loop(self, graph_search_service, mock_storage_facade):
        """Test entity with a self-referential relationship (A -> A)."""
        self_loop_entity = {
            "id": "self_loop",
            "name": "SelfLoopEntity",
            "type": "function",
            "doc_id": "doc_self_loop",
        }

        self_loop_rel = {
            "id": "rel_self",
            "source_id": "self_loop",
            "target_id": "self_loop",
            "type": "recursive_call",
        }

        # Configure mock
        mock_storage_facade.query_raw.side_effect = [
            [self_loop_entity],  # Get starting entity
            [self_loop_rel],  # Find self-loop relationship
            [],  # No new entities (target is already visited)
        ]

        # Execute
        result = await graph_search_service.traverse_relationships(
            entity_id="self_loop",
            direction="outgoing",
            max_depth=3,
        )

        # Verify
        assert result["entity"]["id"] == "self_loop"
        assert result["total_entities"] == 1  # Only one entity (itself)
        assert result["total_relationships"] == 1  # The self-loop
        assert result["relationships"][0]["source_id"] == "self_loop"
        assert result["relationships"][0]["target_id"] == "self_loop"

    @pytest.mark.unit
    async def test_traverse_relationships_multiple_paths_to_same_node(self, graph_search_service, mock_storage_facade):
        """Test diamond pattern: A -> B -> D and A -> C -> D."""
        # Setup entities
        entities = {
            "a": {"id": "entity_a", "name": "A", "type": "function", "doc_id": "doc_a"},
            "b": {"id": "entity_b", "name": "B", "type": "function", "doc_id": "doc_b"},
            "c": {"id": "entity_c", "name": "C", "type": "function", "doc_id": "doc_c"},
            "d": {"id": "entity_d", "name": "D", "type": "function", "doc_id": "doc_d"},
        }

        # Setup relationships: A->B, A->C, B->D, C->D
        mock_storage_facade.query_raw.side_effect = [
            [entities["a"]],  # Get starting entity A
            [  # Depth 1: outgoing from A
                {"id": "rel_ab", "source_id": "entity_a", "target_id": "entity_b", "type": "calls"},
                {"id": "rel_ac", "source_id": "entity_a", "target_id": "entity_c", "type": "calls"},
            ],
            [entities["b"], entities["c"]],  # Fetch entities B and C
            [  # Depth 2: outgoing from B and C
                {"id": "rel_bd", "source_id": "entity_b", "target_id": "entity_d", "type": "calls"},
                {"id": "rel_cd", "source_id": "entity_c", "target_id": "entity_d", "type": "calls"},
            ],
            [entities["d"]],  # Fetch entity D (only once despite two paths)
        ]

        # Execute
        result = await graph_search_service.traverse_relationships(
            entity_id="entity_a",
            direction="outgoing",
            max_depth=2,
        )

        # Verify
        assert result["entity"]["id"] == "entity_a"
        assert result["total_entities"] == 4  # A, B, C, D (D counted once)
        assert result["total_relationships"] == 4  # All 4 relationships

        # Verify D is only in entities dict once
        assert "entity_d" in result["entities"]
        entity_ids = list(result["entities"].keys())
        assert entity_ids.count("entity_d") == 1

    @pytest.mark.unit
    async def test_traverse_relationships_complex_cycle_detection(self, graph_search_service, mock_storage_facade):
        """Test complex graph with multiple interconnected cycles."""
        # Graph: A -> B -> C -> A (cycle 1)
        #        B -> D -> E -> B (cycle 2)
        entities = {
            "a": {"id": "entity_a", "name": "A", "type": "function", "doc_id": "doc_a"},
            "b": {"id": "entity_b", "name": "B", "type": "function", "doc_id": "doc_b"},
            "c": {"id": "entity_c", "name": "C", "type": "function", "doc_id": "doc_c"},
            "d": {"id": "entity_d", "name": "D", "type": "function", "doc_id": "doc_d"},
            "e": {"id": "entity_e", "name": "E", "type": "function", "doc_id": "doc_e"},
        }

        mock_storage_facade.query_raw.side_effect = [
            [entities["a"]],  # Get starting entity A
            [{"id": "rel_ab", "source_id": "entity_a", "target_id": "entity_b", "type": "calls"}],  # Depth 1: A->B
            [entities["b"]],  # Fetch B
            [  # Depth 2: B->C and B->D
                {"id": "rel_bc", "source_id": "entity_b", "target_id": "entity_c", "type": "calls"},
                {"id": "rel_bd", "source_id": "entity_b", "target_id": "entity_d", "type": "calls"},
            ],
            [entities["c"], entities["d"]],  # Fetch C and D
            [  # Depth 3: C->A (back to visited) and D->E
                {"id": "rel_ca", "source_id": "entity_c", "target_id": "entity_a", "type": "calls"},
                {"id": "rel_de", "source_id": "entity_d", "target_id": "entity_e", "type": "calls"},
            ],
            [entities["e"]],  # Fetch E (A already visited)
        ]

        # Execute
        result = await graph_search_service.traverse_relationships(
            entity_id="entity_a",
            direction="outgoing",
            max_depth=3,
        )

        # Verify
        assert result["total_entities"] == 5  # A, B, C, D, E (no duplicates)
        assert result["total_relationships"] == 5  # All relationships including back-edges

        # Verify no duplicate entities
        for entity_id in result["entities"].keys():
            entity_ids = list(result["entities"].keys())
            assert entity_ids.count(entity_id) == 1

    @pytest.mark.unit
    async def test_traverse_relationships_zero_depth(self, graph_search_service, mock_storage_facade):
        """Test traversal with max_depth=0 (should return only the starting entity)."""
        start_entity = {
            "id": "entity_zero",
            "name": "ZeroDepth",
            "type": "function",
            "doc_id": "doc_zero",
        }

        mock_storage_facade.query_raw.side_effect = [
            [start_entity],  # Get starting entity
        ]

        # Execute with max_depth=0
        result = await graph_search_service.traverse_relationships(
            entity_id="entity_zero",
            direction="outgoing",
            max_depth=0,
        )

        # Verify - should return just the entity with no traversal
        assert result["entity"]["id"] == "entity_zero"
        assert result["total_entities"] == 1
        assert result["total_relationships"] == 0
        assert result["depth_reached"] == 0

    @pytest.mark.unit
    async def test_traverse_relationships_fully_connected_subgraph(self, graph_search_service, mock_storage_facade):
        """Test a fully connected subgraph where every node connects to every other node."""
        # Triangle: A <-> B <-> C <-> A (bidirectional)
        entities = {
            "a": {"id": "entity_a", "name": "A", "type": "function", "doc_id": "doc_a"},
            "b": {"id": "entity_b", "name": "B", "type": "function", "doc_id": "doc_b"},
            "c": {"id": "entity_c", "name": "C", "type": "function", "doc_id": "doc_c"},
        }

        # All possible outgoing relationships from A
        mock_storage_facade.query_raw.side_effect = [
            [entities["a"]],  # Get starting entity A
            [  # Depth 1: A connects to B and C
                {"id": "rel_ab", "source_id": "entity_a", "target_id": "entity_b", "type": "calls"},
                {"id": "rel_ac", "source_id": "entity_a", "target_id": "entity_c", "type": "calls"},
            ],
            [entities["b"], entities["c"]],  # Fetch B and C
            [  # Depth 2: B->C, B->A, C->B, C->A (but A already visited)
                {"id": "rel_bc", "source_id": "entity_b", "target_id": "entity_c", "type": "calls"},
                {"id": "rel_ba", "source_id": "entity_b", "target_id": "entity_a", "type": "calls"},
                {"id": "rel_cb", "source_id": "entity_c", "target_id": "entity_b", "type": "calls"},
                {"id": "rel_ca", "source_id": "entity_c", "target_id": "entity_a", "type": "calls"},
            ],
            [],  # No new entities (all visited)
        ]

        # Execute
        result = await graph_search_service.traverse_relationships(
            entity_id="entity_a",
            direction="outgoing",
            max_depth=2,
        )

        # Verify
        assert result["total_entities"] == 3  # A, B, C
        assert result["total_relationships"] == 6  # All 6 directed edges

        # Verify relationship uniqueness
        rel_ids = [rel["id"] for rel in result["relationships"]]
        assert len(rel_ids) == len(set(rel_ids))  # No duplicate relationships
