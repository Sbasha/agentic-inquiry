"""Contract tests for GraphStorageProtocol.

These tests verify that all graph storage providers correctly implement
the GraphStorageProtocol interface and behave consistently.

Each test is run against all provider implementations via the parameterized
`vector_provider` fixture (which includes graph capabilities).
"""

import pytest

from agentic_inquiry.models.graph_entity import EntityType
from agentic_inquiry.models.graph_relationship import RelationshipType

pytestmark = [pytest.mark.unit, pytest.mark.contracts]


class TestGraphEntityCRUD:
    """Tests for entity CRUD operations."""

    @pytest.mark.asyncio
    async def test_upsert_entities_returns_count(
        self, vector_provider, project_id, entity_factory
    ):
        """upsert_entities should return the number of entities upserted."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
        ]

        count = await vector_provider.upsert_entities(entities, project_id)

        assert count == 2

    @pytest.mark.asyncio
    async def test_upsert_entities_updates_existing(
        self, vector_provider, project_id, entity_factory
    ):
        """upsert_entities should update existing entities."""
        entity = entity_factory(entity_id="e1", project_id=project_id, name="original")
        await vector_provider.upsert_entities([entity], project_id)

        # Update with new name
        updated = entity_factory(entity_id="e1", project_id=project_id, name="updated")
        count = await vector_provider.upsert_entities([updated], project_id)

        assert count == 1
        # Verify the update
        retrieved = await vector_provider.get_entity("e1", project_id)
        assert retrieved is not None
        assert retrieved.name == "updated"

    @pytest.mark.asyncio
    async def test_get_entity_returns_none_for_nonexistent(
        self, vector_provider, project_id
    ):
        """get_entity should return None for non-existent entity."""
        result = await vector_provider.get_entity("nonexistent", project_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_entity_returns_entity(
        self, vector_provider, project_id, entity_factory
    ):
        """get_entity should return the entity with matching ID."""
        entity = entity_factory(
            entity_id="e1", project_id=project_id, name="TestEntity"
        )
        await vector_provider.upsert_entities([entity], project_id)

        result = await vector_provider.get_entity("e1", project_id)

        assert result is not None
        assert result.id == "e1"
        assert result.name == "TestEntity"

    @pytest.mark.asyncio
    async def test_get_entities_by_file_returns_matching(
        self, vector_provider, project_id, entity_factory
    ):
        """get_entities_by_file should return entities from the specified file."""
        file1 = "/test/file1.py"
        file2 = "/test/file2.py"

        entities = [
            entity_factory(entity_id="e1", project_id=project_id, file_path=file1),
            entity_factory(entity_id="e2", project_id=project_id, file_path=file1),
            entity_factory(entity_id="e3", project_id=project_id, file_path=file2),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        result = await vector_provider.get_entities_by_file(file1, project_id)

        assert len(result) == 2
        assert all(e.file_path == file1 for e in result)

    @pytest.mark.asyncio
    async def test_get_entities_by_type_returns_matching(
        self, vector_provider, project_id, entity_factory
    ):
        """get_entities_by_type should return entities of the specified type."""
        entities = [
            entity_factory(
                entity_id="e1",
                project_id=project_id,
                entity_type=EntityType.CODE_FUNCTION.value,
            ),
            entity_factory(
                entity_id="e2",
                project_id=project_id,
                entity_type=EntityType.CODE_CLASS.value,
            ),
            entity_factory(
                entity_id="e3",
                project_id=project_id,
                entity_type=EntityType.CODE_FUNCTION.value,
            ),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        result = await vector_provider.get_entities_by_type(
            EntityType.CODE_FUNCTION.value, project_id
        )

        assert len(result) == 2
        assert all(e.type == EntityType.CODE_FUNCTION.value for e in result)

    @pytest.mark.asyncio
    async def test_delete_entities_by_file_returns_count(
        self, vector_provider, project_id, entity_factory
    ):
        """delete_entities_by_file should return number of deleted entities."""
        file_path = "/test/delete_me.py"
        entities = [
            entity_factory(entity_id="e1", project_id=project_id, file_path=file_path),
            entity_factory(entity_id="e2", project_id=project_id, file_path=file_path),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        deleted = await vector_provider.delete_entities_by_file(file_path, project_id)

        assert deleted == 2

    @pytest.mark.asyncio
    async def test_delete_entities_by_ids_returns_count(
        self, vector_provider, project_id, entity_factory
    ):
        """delete_entities_by_ids should return number of deleted entities."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
            entity_factory(entity_id="e3", project_id=project_id),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        deleted = await vector_provider.delete_entities_by_ids(["e1", "e2"], project_id)

        assert deleted == 2

    @pytest.mark.asyncio
    async def test_count_entities_returns_total(
        self, vector_provider, project_id, entity_factory
    ):
        """count_entities should return total number of entities."""
        entities = [
            entity_factory(entity_id=f"e{i}", project_id=project_id) for i in range(5)
        ]
        await vector_provider.upsert_entities(entities, project_id)

        total = await vector_provider.count_entities(project_id=project_id)

        assert total == 5


class TestGraphRelationshipCRUD:
    """Tests for relationship CRUD operations."""

    @pytest.mark.asyncio
    async def test_upsert_relationships_returns_count(
        self, vector_provider, project_id, entity_factory, relationship_factory
    ):
        """upsert_relationships should return the number of relationships upserted."""
        # Create entities first
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
            entity_factory(entity_id="e3", project_id=project_id),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="e1", target_id="e2"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="e2", target_id="e3"
            ),
        ]

        count = await vector_provider.upsert_relationships(relationships, project_id)

        assert count == 2

    @pytest.mark.asyncio
    async def test_get_relationships_by_entity_outgoing(
        self, vector_provider, project_id, entity_factory, relationship_factory
    ):
        """get_relationships_by_entity should return outgoing relationships."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
            entity_factory(entity_id="e3", project_id=project_id),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="e1", target_id="e2"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="e1", target_id="e3"
            ),
            relationship_factory(
                rel_id="r3", project_id=project_id, source_id="e2", target_id="e1"
            ),
        ]
        await vector_provider.upsert_relationships(relationships, project_id)

        result = await vector_provider.get_relationships_by_entity(
            "e1", direction="outgoing", project_id=project_id
        )

        assert len(result) == 2
        assert all(r.source_id == "e1" for r in result)

    @pytest.mark.asyncio
    async def test_get_relationships_by_entity_incoming(
        self, vector_provider, project_id, entity_factory, relationship_factory
    ):
        """get_relationships_by_entity should return incoming relationships."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="e1", target_id="e2"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="e2", target_id="e1"
            ),
        ]
        await vector_provider.upsert_relationships(relationships, project_id)

        result = await vector_provider.get_relationships_by_entity(
            "e2", direction="incoming", project_id=project_id
        )

        assert len(result) == 1
        assert result[0].target_id == "e2"

    @pytest.mark.asyncio
    async def test_get_relationships_by_entity_both(
        self, vector_provider, project_id, entity_factory, relationship_factory
    ):
        """get_relationships_by_entity should return both directions."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
            entity_factory(entity_id="e3", project_id=project_id),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="e1", target_id="e2"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="e3", target_id="e2"
            ),
        ]
        await vector_provider.upsert_relationships(relationships, project_id)

        result = await vector_provider.get_relationships_by_entity(
            "e2", direction="both", project_id=project_id
        )

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_relationships_with_type_filter(
        self, vector_provider, project_id, entity_factory, relationship_factory
    ):
        """get_relationships_by_entity should filter by relationship type."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1",
                project_id=project_id,
                source_id="e1",
                target_id="e2",
                rel_type=RelationshipType.CALLS.value,
            ),
            relationship_factory(
                rel_id="r2",
                project_id=project_id,
                source_id="e1",
                target_id="e2",
                rel_type=RelationshipType.IMPORTS.value,
            ),
        ]
        await vector_provider.upsert_relationships(relationships, project_id)

        result = await vector_provider.get_relationships_by_entity(
            "e1",
            direction="outgoing",
            relationship_types=[RelationshipType.CALLS.value],
            project_id=project_id,
        )

        assert len(result) == 1
        assert result[0].type == RelationshipType.CALLS.value

    @pytest.mark.asyncio
    async def test_delete_relationships_by_entity_returns_count(
        self, vector_provider, project_id, entity_factory, relationship_factory
    ):
        """delete_relationships_by_entity should return number deleted."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="e1", target_id="e2"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="e2", target_id="e1"
            ),
        ]
        await vector_provider.upsert_relationships(relationships, project_id)

        deleted = await vector_provider.delete_relationships_by_entity("e1", project_id)

        assert deleted == 2


class TestGraphTraversal:
    """Tests for graph traversal operations."""

    @pytest.mark.asyncio
    async def test_get_neighbors_returns_connected_entities(
        self, vector_provider, project_id, entity_factory, relationship_factory
    ):
        """get_neighbors should return entities connected to the start entity."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id, name="Start"),
            entity_factory(entity_id="e2", project_id=project_id, name="Neighbor1"),
            entity_factory(entity_id="e3", project_id=project_id, name="Neighbor2"),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="e1", target_id="e2"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="e1", target_id="e3"
            ),
        ]
        await vector_provider.upsert_relationships(relationships, project_id)

        neighbors = await vector_provider.get_neighbors(
            "e1", direction="outgoing", project_id=project_id
        )

        assert len(neighbors) == 2
        neighbor_ids = [n.id for n in neighbors]
        assert "e2" in neighbor_ids
        assert "e3" in neighbor_ids

    @pytest.mark.asyncio
    async def test_get_neighbors_returns_empty_for_no_connections(
        self, vector_provider, project_id, entity_factory
    ):
        """get_neighbors should return empty list for isolated entity."""
        entity = entity_factory(entity_id="e1", project_id=project_id)
        await vector_provider.upsert_entities([entity], project_id)

        neighbors = await vector_provider.get_neighbors(
            "e1", direction="outgoing", project_id=project_id
        )

        assert neighbors == []

    @pytest.mark.asyncio
    async def test_traverse_returns_traversal_result(
        self, vector_provider, project_id, entity_factory, relationship_factory
    ):
        """traverse should return a dict with entities and relationships."""
        entities = [
            entity_factory(entity_id="e1", project_id=project_id),
            entity_factory(entity_id="e2", project_id=project_id),
            entity_factory(entity_id="e3", project_id=project_id),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="r1", project_id=project_id, source_id="e1", target_id="e2"
            ),
            relationship_factory(
                rel_id="r2", project_id=project_id, source_id="e2", target_id="e3"
            ),
        ]
        await vector_provider.upsert_relationships(relationships, project_id)

        result = await vector_provider.traverse(
            "e1", max_depth=2, project_id=project_id
        )

        assert isinstance(result, dict)
        assert "entities" in result
        assert "relationships" in result


class TestGraphProjectIsolation:
    """Tests for project-based data isolation in graph storage."""

    @pytest.mark.asyncio
    async def test_entities_isolated_by_project(self, vector_provider, entity_factory):
        """Entities from different projects should be isolated."""
        project_a = "graph_project_a"
        project_b = "graph_project_b"

        entity_a = entity_factory(entity_id="ea", project_id=project_a)
        entity_b = entity_factory(entity_id="eb", project_id=project_b)

        await vector_provider.upsert_entities([entity_a], project_a)
        await vector_provider.upsert_entities([entity_b], project_b)

        count_a = await vector_provider.count_entities(project_id=project_a)
        count_b = await vector_provider.count_entities(project_id=project_b)

        assert count_a == 1
        assert count_b == 1

    @pytest.mark.asyncio
    async def test_get_entity_respects_project(self, vector_provider, entity_factory):
        """get_entity should only return entity from specified project."""
        project_a = "graph_iso_a"
        project_b = "graph_iso_b"

        entity_a = entity_factory(entity_id="same_id", project_id=project_a, name="A")
        entity_b = entity_factory(entity_id="same_id", project_id=project_b, name="B")

        await vector_provider.upsert_entities([entity_a], project_a)
        await vector_provider.upsert_entities([entity_b], project_b)

        result_a = await vector_provider.get_entity("same_id", project_a)
        result_b = await vector_provider.get_entity("same_id", project_b)

        assert result_a is not None
        assert result_b is not None
        assert result_a.name == "A"
        assert result_b.name == "B"
