"""Backend contract tests — 6 critical storage behaviors.

These tests verify that all storage backends behave consistently for the
6 critical operations that must work identically across providers. They
prevent future backend behavior drift.

Contract 1: test_upsert_and_retrieve_chunks — store chunks, retrieve by ID
Contract 2: test_vector_search_returns_results — embedding-based similarity
Contract 3: test_fts_search_returns_results — full-text search with query terms
Contract 4: test_upsert_and_query_entities — entity CRUD (graph operations)
Contract 5: test_upsert_and_query_relationships — relationship CRUD
Contract 6: test_graph_traversal — recursive neighbor traversal

Each test is run against all providers via the parameterized ``vector_provider``
fixture (memory and lancedb).
"""

import pytest

from agentic_inquiry.models.graph_entity import EntityType
from agentic_inquiry.models.graph_relationship import RelationshipType
from agentic_inquiry.storage.capabilities import (
    ProviderCapabilities,
    get_capabilities_for_backend,
)

pytestmark = [pytest.mark.unit, pytest.mark.contracts]


def _capabilities_for(provider_type: str) -> ProviderCapabilities:
    """Return capabilities for a provider type string."""
    return get_capabilities_for_backend(provider_type)


def _embedding_dim_for(provider_type: str) -> int:
    """Return the expected embedding dimension for a provider."""
    caps = _capabilities_for(provider_type)
    return caps.embedding_dimensions


# =============================================================================
# Contract 1: Upsert and Retrieve Chunks
# =============================================================================


class TestContract1UpsertAndRetrieveChunks:
    """Verify that chunks can be stored and retrieved by file path."""

    @pytest.mark.asyncio
    async def test_upsert_and_retrieve_chunks(
        self, vector_provider, provider_type, project_id, chunk_factory
    ):
        """Store chunks, then retrieve them by file path.

        This is the most fundamental storage contract: data that goes in
        must come back out with the same content.
        """
        dim = _embedding_dim_for(provider_type)
        file_path = "/test/contract1.py"

        chunks = [
            chunk_factory(
                chunk_id="contract1_a",
                project_id=project_id,
                file_path=file_path,
                content="def hello(): pass",
                vector=[0.5] * dim,
            ),
            chunk_factory(
                chunk_id="contract1_b",
                project_id=project_id,
                file_path=file_path,
                content="def world(): pass",
                vector=[0.3] * dim,
            ),
        ]

        count = await vector_provider.upsert_chunks(chunks, project_id)
        assert count == 2

        retrieved = await vector_provider.get_chunks_by_file(file_path, project_id)
        assert len(retrieved) == 2

        retrieved_ids = {c.id for c in retrieved}
        assert "contract1_a" in retrieved_ids
        assert "contract1_b" in retrieved_ids

        # Verify content round-trips correctly
        by_id = {c.id: c for c in retrieved}
        assert by_id["contract1_a"].content == "def hello(): pass"
        assert by_id["contract1_b"].content == "def world(): pass"


# =============================================================================
# Contract 2: Vector Search Returns Results
# =============================================================================


class TestContract2VectorSearch:
    """Verify that embedding-based similarity search works."""

    @pytest.mark.asyncio
    async def test_vector_search_returns_results(
        self, vector_provider, provider_type, project_id, chunk_factory
    ):
        """Insert chunks with distinct vectors, then search.

        The chunk whose vector is most similar to the query vector
        should appear first in results.
        """
        dim = _embedding_dim_for(provider_type)

        # Create two chunks with very different vectors
        similar_vector = [0.9] * dim
        dissimilar_vector = [0.1] * dim

        chunks = [
            chunk_factory(
                chunk_id="vec_similar",
                project_id=project_id,
                content="similar content for vector search",
                vector=similar_vector,
            ),
            chunk_factory(
                chunk_id="vec_dissimilar",
                project_id=project_id,
                content="dissimilar content for vector search",
                vector=dissimilar_vector,
            ),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        # Query with a vector close to similar_vector
        query_vector = [0.9] * dim
        results = await vector_provider.vector_search(
            query_vector, limit=10, project_id=project_id
        )

        assert len(results) >= 1
        assert results[0].id == "vec_similar"


# =============================================================================
# Contract 3: FTS Search Returns Results
# =============================================================================


class TestContract3FTSSearch:
    """Verify that full-text search works with query terms."""

    @pytest.mark.asyncio
    async def test_fts_search_returns_results(
        self, vector_provider, provider_type, project_id, chunk_factory
    ):
        """Insert chunks with distinct text, search for a unique term.

        The chunk containing the query term should be returned.
        Providers that do not support FTS are skipped.
        """
        caps = _capabilities_for(provider_type)
        if not caps.supports_fts:
            pytest.skip(f"{provider_type} does not support full-text search")

        dim = _embedding_dim_for(provider_type)

        chunks = [
            chunk_factory(
                chunk_id="fts_match",
                project_id=project_id,
                content="authentication login security middleware",
                vector=[0.5] * dim,
            ),
            chunk_factory(
                chunk_id="fts_nomatch",
                project_id=project_id,
                content="database query optimization indexing",
                vector=[0.5] * dim,
            ),
        ]
        await vector_provider.upsert_chunks(chunks, project_id)

        results = await vector_provider.fts_search(
            "authentication", limit=10, project_id=project_id
        )

        assert len(results) >= 1
        assert results[0].id == "fts_match"


# =============================================================================
# Contract 4: Upsert and Query Entities
# =============================================================================


class TestContract4UpsertAndQueryEntities:
    """Verify entity CRUD (graph operations)."""

    @pytest.mark.asyncio
    async def test_upsert_and_query_entities(
        self, vector_provider, provider_type, project_id, entity_factory
    ):
        """Store entities, retrieve by ID and by file.

        This verifies the entity storage contract: entities can be created,
        retrieved individually, and queried by file path.
        """
        caps = _capabilities_for(provider_type)
        if not caps.supports_graph:
            pytest.skip(f"{provider_type} does not support graph storage")

        dim = _embedding_dim_for(provider_type)
        file_path = "/test/contract4.py"

        entities = [
            entity_factory(
                entity_id="ent_func",
                project_id=project_id,
                name="process_data",
                entity_type=EntityType.CODE_FUNCTION.value,
                file_path=file_path,
                vector=[0.4] * dim,
            ),
            entity_factory(
                entity_id="ent_class",
                project_id=project_id,
                name="DataProcessor",
                entity_type=EntityType.CODE_CLASS.value,
                file_path=file_path,
                vector=[0.6] * dim,
            ),
        ]

        count = await vector_provider.upsert_entities(entities, project_id)
        assert count == 2

        # Retrieve by ID
        retrieved = await vector_provider.get_entity("ent_func", project_id)
        assert retrieved is not None
        assert retrieved.name == "process_data"
        assert retrieved.type == EntityType.CODE_FUNCTION.value

        # Retrieve by file
        by_file = await vector_provider.get_entities_by_file(file_path, project_id)
        assert len(by_file) == 2

        # Retrieve by type
        functions = await vector_provider.get_entities_by_type(
            EntityType.CODE_FUNCTION.value, project_id
        )
        assert len(functions) >= 1
        assert any(e.id == "ent_func" for e in functions)


# =============================================================================
# Contract 5: Upsert and Query Relationships
# =============================================================================


class TestContract5UpsertAndQueryRelationships:
    """Verify relationship CRUD."""

    @pytest.mark.asyncio
    async def test_upsert_and_query_relationships(
        self,
        vector_provider,
        provider_type,
        project_id,
        entity_factory,
        relationship_factory,
    ):
        """Store relationships between entities and query by direction.

        Creates a call graph: A -> B -> C, then verifies outgoing/incoming
        relationship queries return correct results.
        """
        caps = _capabilities_for(provider_type)
        if not caps.supports_graph:
            pytest.skip(f"{provider_type} does not support graph storage")

        dim = _embedding_dim_for(provider_type)

        # Create entities first
        entities = [
            entity_factory(
                entity_id="rel_a",
                project_id=project_id,
                name="func_a",
                vector=[0.3] * dim,
            ),
            entity_factory(
                entity_id="rel_b",
                project_id=project_id,
                name="func_b",
                vector=[0.5] * dim,
            ),
            entity_factory(
                entity_id="rel_c",
                project_id=project_id,
                name="func_c",
                vector=[0.7] * dim,
            ),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        # Create relationships: A calls B, B calls C
        relationships = [
            relationship_factory(
                rel_id="rel_ab",
                project_id=project_id,
                source_id="rel_a",
                target_id="rel_b",
                rel_type=RelationshipType.CALLS.value,
                vector=[0.4] * dim,
            ),
            relationship_factory(
                rel_id="rel_bc",
                project_id=project_id,
                source_id="rel_b",
                target_id="rel_c",
                rel_type=RelationshipType.CALLS.value,
                vector=[0.6] * dim,
            ),
        ]

        count = await vector_provider.upsert_relationships(relationships, project_id)
        assert count == 2

        # Query outgoing from A — should find A -> B
        outgoing = await vector_provider.get_relationships_by_entity(
            "rel_a", direction="outgoing", project_id=project_id
        )
        assert len(outgoing) == 1
        assert outgoing[0].target_id == "rel_b"

        # Query incoming to C — should find B -> C
        incoming = await vector_provider.get_relationships_by_entity(
            "rel_c", direction="incoming", project_id=project_id
        )
        assert len(incoming) == 1
        assert incoming[0].source_id == "rel_b"

        # Query both directions for B — should find 2 (A->B and B->C)
        both = await vector_provider.get_relationships_by_entity(
            "rel_b", direction="both", project_id=project_id
        )
        assert len(both) == 2


# =============================================================================
# Contract 6: Graph Traversal
# =============================================================================


class TestContract6GraphTraversal:
    """Verify recursive neighbor traversal."""

    @pytest.mark.asyncio
    async def test_graph_traversal(
        self,
        vector_provider,
        provider_type,
        project_id,
        entity_factory,
        relationship_factory,
    ):
        """Build a 3-node chain A -> B -> C and traverse from A with depth=2.

        The traversal result should include all 3 entities and both
        relationships when max_depth is sufficient.
        """
        caps = _capabilities_for(provider_type)
        if not caps.supports_graph:
            pytest.skip(f"{provider_type} does not support graph storage")

        dim = _embedding_dim_for(provider_type)

        # Build chain: A -> B -> C
        entities = [
            entity_factory(
                entity_id="trav_a",
                project_id=project_id,
                name="entry_point",
                vector=[0.2] * dim,
            ),
            entity_factory(
                entity_id="trav_b",
                project_id=project_id,
                name="middleware",
                vector=[0.5] * dim,
            ),
            entity_factory(
                entity_id="trav_c",
                project_id=project_id,
                name="handler",
                vector=[0.8] * dim,
            ),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="trav_ab",
                project_id=project_id,
                source_id="trav_a",
                target_id="trav_b",
                vector=[0.3] * dim,
            ),
            relationship_factory(
                rel_id="trav_bc",
                project_id=project_id,
                source_id="trav_b",
                target_id="trav_c",
                vector=[0.6] * dim,
            ),
        ]
        await vector_provider.upsert_relationships(relationships, project_id)

        # Traverse from A with depth 2 — should reach C
        result = await vector_provider.traverse(
            "trav_a", max_depth=2, project_id=project_id
        )

        assert isinstance(result, dict)
        assert "entities" in result
        assert "relationships" in result

        entity_ids = {e.id if hasattr(e, "id") else e["id"] for e in result["entities"]}
        assert "trav_a" in entity_ids
        assert "trav_b" in entity_ids
        assert "trav_c" in entity_ids

        # Should have found both relationships
        assert len(result["relationships"]) >= 2

    @pytest.mark.asyncio
    async def test_graph_traversal_depth_1_limited(
        self,
        vector_provider,
        provider_type,
        project_id,
        entity_factory,
        relationship_factory,
    ):
        """Traverse with depth=1 should only reach immediate neighbors.

        From A -> B -> C, depth=1 from A should find A and B but NOT C.
        """
        caps = _capabilities_for(provider_type)
        if not caps.supports_graph:
            pytest.skip(f"{provider_type} does not support graph storage")

        dim = _embedding_dim_for(provider_type)

        entities = [
            entity_factory(
                entity_id="d1_a",
                project_id=project_id,
                name="root",
                vector=[0.2] * dim,
            ),
            entity_factory(
                entity_id="d1_b",
                project_id=project_id,
                name="child",
                vector=[0.5] * dim,
            ),
            entity_factory(
                entity_id="d1_c",
                project_id=project_id,
                name="grandchild",
                vector=[0.8] * dim,
            ),
        ]
        await vector_provider.upsert_entities(entities, project_id)

        relationships = [
            relationship_factory(
                rel_id="d1_ab",
                project_id=project_id,
                source_id="d1_a",
                target_id="d1_b",
                vector=[0.3] * dim,
            ),
            relationship_factory(
                rel_id="d1_bc",
                project_id=project_id,
                source_id="d1_b",
                target_id="d1_c",
                vector=[0.6] * dim,
            ),
        ]
        await vector_provider.upsert_relationships(relationships, project_id)

        result = await vector_provider.traverse(
            "d1_a", max_depth=1, project_id=project_id
        )

        entity_ids = {e.id if hasattr(e, "id") else e["id"] for e in result["entities"]}
        assert "d1_a" in entity_ids
        assert "d1_b" in entity_ids
        # depth=1 should NOT reach the grandchild
        assert "d1_c" not in entity_ids


# =============================================================================
# AlloyDB-Specific Contract: Server-Side Embedding
# =============================================================================


