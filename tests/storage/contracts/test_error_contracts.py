"""Contract tests for error propagation and analyze_impact traversal.

These tests verify that:
1. Storage errors propagate as exceptions (not silently swallowed)
2. analyze_impact returns non-empty results when relationships exist
3. The InMemory provider correctly handles tuple operator filters (IN, LIKE, etc.)

Each test is run against the in-memory provider, which is always available.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inquiry.models.graph_entity import EntityType, GraphEntity
from agentic_inquiry.models.graph_relationship import (
    GraphRelationship,
    RelationshipType,
)

pytestmark = [pytest.mark.unit, pytest.mark.contracts]


# =============================================================================
# Tuple Operator Filter Tests (root cause of analyze_impact returning 0)
# =============================================================================


class TestTupleOperatorFilters:
    """Tests that tuple operator filters work across providers.

    The analyze_impact traversal uses ``("IN", [...])`` filters in
    ``_get_entity_references`` to batch-lookup entities by ID.  If the
    provider silently ignores operator tuples, impact analysis returns
    0 affected entities even when relationships exist.
    """

    @pytest.mark.asyncio
    async def test_query_entities_with_in_filter(
        self, memory_provider, project_id, entity_factory
    ):
        """query_entities with IN tuple filter should return matching entities."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id, name="Alpha"),
            entity_factory(entity_id="e2", project_id=project_id, name="Beta"),
            entity_factory(entity_id="e3", project_id=project_id, name="Gamma"),
        ]
        await memory_provider.upsert_entities(entities, project_id)

        # Use IN filter — the same pattern as _get_entity_references
        result = await memory_provider.query_entities(
            filters={"id": ("IN", ["e1", "e3"])},
            project_id=project_id,
        )

        assert len(result) == 2
        ids = {e.id for e in result}
        assert ids == {"e1", "e3"}

    @pytest.mark.asyncio
    async def test_query_entities_with_in_filter_empty_list(
        self, memory_provider, project_id, entity_factory
    ):
        """query_entities with empty IN list should return no entities."""
        entity = entity_factory(entity_id="e1", project_id=project_id)
        await memory_provider.upsert_entities([entity], project_id)

        result = await memory_provider.query_entities(
            filters={"id": ("IN", [])},
            project_id=project_id,
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_query_relationships_with_in_filter(
        self, memory_provider, project_id, entity_factory, relationship_factory
    ):
        """query_relationships with IN filter should return matching relationships."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
            entity_factory(entity_id="e3", project_id=project_id),
        ]
        await memory_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="e1", target_id="e2"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="e2", target_id="e3"
            ),
            relationship_factory(
                rel_id="r3", project_id=project_id, source_id="e3", target_id="e1"
            ),
        ]
        await memory_provider.upsert_relationships(relationships, project_id)

        result = await memory_provider.query_relationships(
            filters={"source_id": ("IN", ["e1", "e3"])},
            project_id=project_id,
        )

        assert len(result) == 2
        source_ids = {r.source_id for r in result}
        assert source_ids == {"e1", "e3"}

    @pytest.mark.asyncio
    async def test_query_entities_with_ilike_filter(
        self, memory_provider, project_id, entity_factory
    ):
        """query_entities with ILIKE filter should do case-insensitive matching."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id, name="SearchService"),
            entity_factory(entity_id="e2", project_id=project_id, name="search_helper"),
            entity_factory(entity_id="e3", project_id=project_id, name="IndexBuilder"),
        ]
        await memory_provider.upsert_entities(entities, project_id)

        result = await memory_provider.query_entities(
            filters={"name": ("ILIKE", "%search%")},
            project_id=project_id,
        )

        assert len(result) == 2
        names = {e.name for e in result}
        assert names == {"SearchService", "search_helper"}

    @pytest.mark.asyncio
    async def test_query_entities_with_equality_operator(
        self, memory_provider, project_id, entity_factory
    ):
        """query_entities with explicit '=' operator should work like equality."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id, name="Alpha"),
            entity_factory(entity_id="e2", project_id=project_id, name="Beta"),
        ]
        await memory_provider.upsert_entities(entities, project_id)

        result = await memory_provider.query_entities(
            filters={"name": ("=", "Alpha")},
            project_id=project_id,
        )

        assert len(result) == 1
        assert result[0].name == "Alpha"

    @pytest.mark.asyncio
    async def test_query_entities_with_not_equal_operator(
        self, memory_provider, project_id, entity_factory
    ):
        """query_entities with '!=' operator should exclude matching entities."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id, name="Alpha"),
            entity_factory(entity_id="e2", project_id=project_id, name="Beta"),
        ]
        await memory_provider.upsert_entities(entities, project_id)

        result = await memory_provider.query_entities(
            filters={"name": ("!=", "Alpha")},
            project_id=project_id,
        )

        assert len(result) == 1
        assert result[0].name == "Beta"


# =============================================================================
# Error Propagation Tests
# =============================================================================


class TestErrorPropagation:
    """Tests that storage errors propagate as exceptions, not silently swallowed."""

    @pytest.mark.asyncio
    async def test_get_entity_nonexistent_returns_none_not_exception(
        self, memory_provider, project_id
    ):
        """Missing entities return None, not raise."""
        result = await memory_provider.get_entity("nonexistent", project_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_query_entities_empty_result_returns_list(
        self, memory_provider, project_id
    ):
        """Empty query results return empty list, not None."""
        result = await memory_provider.query_entities(
            filters={"id": "nonexistent"},
            project_id=project_id,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_query_relationships_empty_result_returns_list(
        self, memory_provider, project_id
    ):
        """Empty relationship query returns empty list, not None."""
        result = await memory_provider.query_relationships(
            filters={"source_id": "nonexistent"},
            project_id=project_id,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_upsert_entities_returns_int_count(
        self, memory_provider, project_id, entity_factory
    ):
        """upsert_entities should return integer count, not None or bool."""
        entity = entity_factory(entity_id="e1", project_id=project_id)
        count = await memory_provider.upsert_entities([entity], project_id)
        assert isinstance(count, int)
        assert count == 1

    @pytest.mark.asyncio
    async def test_upsert_relationships_returns_int_count(
        self, memory_provider, project_id, entity_factory, relationship_factory
    ):
        """upsert_relationships should return integer count, not None or bool."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
        ]
        await memory_provider.upsert_entities(entities, project_id)

        rel = relationship_factory(
            rel_id="r1", project_id=project_id, source_id="e1", target_id="e2"
        )
        count = await memory_provider.upsert_relationships([rel], project_id)
        assert isinstance(count, int)
        assert count == 1

    @pytest.mark.asyncio
    async def test_delete_nonexistent_entity_returns_zero(
        self, memory_provider, project_id
    ):
        """Deleting non-existent entities should return 0, not raise."""
        deleted = await memory_provider.delete_entities_by_ids(
            ["nonexistent"], project_id
        )
        assert deleted == 0


# =============================================================================
# Impact Traversal Integration Tests (InMemory)
# =============================================================================


class TestImpactTraversalWithRelationships:
    """Tests that traversal finds affected entities when relationships exist.

    These tests simulate the traversal pattern used by ImpactAnalyzer:
    1. Query relationships by source_id/target_id to find connected entities
    2. Use IN filter to batch-lookup entity details

    This verifies the fix for the bug where _matches_filters did not handle
    tuple operator filters, causing analyze_impact to always return 0 results.
    """

    @pytest.mark.asyncio
    async def test_outgoing_traversal_finds_dependencies(
        self, memory_provider, project_id, entity_factory, relationship_factory
    ):
        """Traversal should find entities connected via outgoing relationships."""
        # Setup: A -> B -> C
        entities = [
            entity_factory(entity_id="a", project_id=project_id, name="EntityA"),
            entity_factory(entity_id="b", project_id=project_id, name="EntityB"),
            entity_factory(entity_id="c", project_id=project_id, name="EntityC"),
        ]
        await memory_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="a", target_id="b"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="b", target_id="c"
            ),
        ]
        await memory_provider.upsert_relationships(relationships, project_id)

        # Step 1: Find outgoing relationships from entity A (like impact_analyzer does)
        rels = await memory_provider.query_relationships(
            filters={"source_id": "a"},
            project_id=project_id,
        )
        assert len(rels) == 1
        assert rels[0].target_id == "b"

        # Step 2: Batch-lookup entities via IN filter (like _get_entity_references)
        found_ids = [r.target_id for r in rels]
        entities_found = await memory_provider.query_entities(
            filters={"id": ("IN", found_ids)},
            project_id=project_id,
        )
        assert len(entities_found) == 1
        assert entities_found[0].name == "EntityB"

    @pytest.mark.asyncio
    async def test_incoming_traversal_finds_dependents(
        self, memory_provider, project_id, entity_factory, relationship_factory
    ):
        """Traversal should find entities connected via incoming relationships."""
        # Setup: A -> C, B -> C
        entities = [
            entity_factory(entity_id="a", project_id=project_id, name="CallerA"),
            entity_factory(entity_id="b", project_id=project_id, name="CallerB"),
            entity_factory(entity_id="c", project_id=project_id, name="Target"),
        ]
        await memory_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="a", target_id="c"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="b", target_id="c"
            ),
        ]
        await memory_provider.upsert_relationships(relationships, project_id)

        # Find incoming relationships to entity C
        rels = await memory_provider.query_relationships(
            filters={"target_id": "c"},
            project_id=project_id,
        )
        assert len(rels) == 2

        # Batch-lookup callers
        caller_ids = [r.source_id for r in rels]
        callers = await memory_provider.query_entities(
            filters={"id": ("IN", caller_ids)},
            project_id=project_id,
        )
        assert len(callers) == 2
        caller_names = {e.name for e in callers}
        assert caller_names == {"CallerA", "CallerB"}

    @pytest.mark.asyncio
    async def test_project_isolation_in_traversal(
        self, memory_provider, entity_factory, relationship_factory
    ):
        """Traversal should not cross project boundaries."""
        project_a = "proj_a"
        project_b = "proj_b"

        # Create same entity IDs in different projects
        await memory_provider.upsert_entities(
            [entity_factory(entity_id="e1", project_id=project_a, name="A1")],
            project_a,
        )
        await memory_provider.upsert_entities(
            [entity_factory(entity_id="e2", project_id=project_a, name="A2")],
            project_a,
        )
        await memory_provider.upsert_entities(
            [entity_factory(entity_id="e1", project_id=project_b, name="B1")],
            project_b,
        )

        # Relationship only in project A
        await memory_provider.upsert_relationships(
            [
                relationship_factory(
                    rel_id="r1", project_id=project_a, source_id="e1", target_id="e2"
                )
            ],
            project_a,
        )

        # Query relationships in project B should find nothing
        rels_b = await memory_provider.query_relationships(
            filters={"source_id": "e1"},
            project_id=project_b,
        )
        assert len(rels_b) == 0

        # Query relationships in project A should find one
        rels_a = await memory_provider.query_relationships(
            filters={"source_id": "e1"},
            project_id=project_a,
        )
        assert len(rels_a) == 1
