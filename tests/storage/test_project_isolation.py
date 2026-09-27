"""Project isolation tests for storage providers.

These tests verify that multi-project deployments properly isolate data
and prevent cross-contamination. Tests cover:

- Cross-project data leakage prevention
- Concurrent access isolation
- Project-scoped queries
- Project deletion cleanup

Tests are parameterized to run against all storage provider implementations
(LanceDB, PostgreSQL, Memory) via the conftest fixtures.

KNOWN ISSUES:
-----------
The LanceDB provider currently has a project isolation bug where it filters
queries by the provider's initialization project_id instead of the method
parameter project_id. This means a provider initialized with project_id="A"
cannot query data from project_id="B" even when passing "B" as a parameter.

This affects multi-tenant deployments where a single provider instance needs
to access data from multiple projects. These tests correctly identify this bug.

To run tests with only working providers:
    pytest tests/storage/test_project_isolation.py -v -k "memory or postgres"

To see the LanceDB failures (demonstrating the bug):
    pytest tests/storage/test_project_isolation.py -v -k "lancedb"
"""

import asyncio
import pytest

pytestmark = [pytest.mark.unit]


@pytest.fixture
def graph_provider(vector_provider):
    """Alias for vector_provider to support graph operations.

    Providers are multi-role and support both vector and graph operations.
    This fixture provides a clearer name for tests focused on graph operations.
    """
    return vector_provider


class TestCrossProjectDataLeakage:
    """Tests to verify data from one project is not accessible from another."""

    @pytest.mark.asyncio
    async def test_chunks_isolated_between_projects(
        self, vector_provider, chunk_factory
    ):
        """Chunks from project A should not be visible in project B queries."""
        project_a = "project-alpha"
        project_b = "project-beta"

        # Add chunks to project A
        chunks_a = [
            chunk_factory(
                chunk_id="a1",
                project_id=project_a,
                file_path="/src/alpha.py",
                content="alpha content",
            ),
            chunk_factory(
                chunk_id="a2",
                project_id=project_a,
                file_path="/src/alpha.py",
                content="more alpha",
            ),
        ]
        await vector_provider.upsert_chunks(chunks_a, project_a)

        # Add chunks to project B
        chunks_b = [
            chunk_factory(
                chunk_id="b1",
                project_id=project_b,
                file_path="/src/beta.py",
                content="beta content",
            ),
        ]
        await vector_provider.upsert_chunks(chunks_b, project_b)

        # Query project A - should only see project A chunks
        results_a = await vector_provider.get_chunks_by_file("/src/alpha.py", project_a)
        assert len(results_a) == 2
        assert all(chunk.id in ["a1", "a2"] for chunk in results_a)

        # Query project B - should only see project B chunks
        results_b = await vector_provider.get_chunks_by_file("/src/beta.py", project_b)
        assert len(results_b) == 1
        assert results_b[0].id == "b1"

        # Project A should not see project B's files
        wrong_results_a = await vector_provider.get_chunks_by_file(
            "/src/beta.py", project_a
        )
        assert len(wrong_results_a) == 0

        # Project B should not see project A's files
        wrong_results_b = await vector_provider.get_chunks_by_file(
            "/src/alpha.py", project_b
        )
        assert len(wrong_results_b) == 0

    @pytest.mark.asyncio
    async def test_vector_search_isolated_between_projects(
        self, vector_provider, chunk_factory
    ):
        """Vector search should only return results from the queried project."""
        project_a = "project-alpha"
        project_b = "project-beta"

        # Create distinct vectors for each project
        vector_a = [0.9] * 384
        vector_b = [0.1] * 384

        chunks_a = [
            chunk_factory(
                chunk_id="a1",
                project_id=project_a,
                content="alpha",
                vector=vector_a,
            ),
        ]
        chunks_b = [
            chunk_factory(
                chunk_id="b1",
                project_id=project_b,
                content="beta",
                vector=vector_b,
            ),
        ]

        await vector_provider.upsert_chunks(chunks_a, project_a)
        await vector_provider.upsert_chunks(chunks_b, project_b)

        # Search in project A
        results_a = await vector_provider.vector_search(
            query_vector=vector_a,
            limit=10,
            project_id=project_a,
        )
        assert len(results_a) >= 1
        assert all(r.id.startswith("a") for r in results_a)

        # Search in project B
        results_b = await vector_provider.vector_search(
            query_vector=vector_b,
            limit=10,
            project_id=project_b,
        )
        assert len(results_b) >= 1
        assert all(r.id.startswith("b") for r in results_b)

    @pytest.mark.asyncio
    async def test_entities_isolated_between_projects(
        self, graph_provider, entity_factory
    ):
        """Entities from project A should not be visible in project B queries."""
        project_a = "project-alpha"
        project_b = "project-beta"

        # Add entities to project A
        entities_a = [
            entity_factory(
                entity_id="func_alpha",
                project_id=project_a,
                name="alpha_function",
                entity_type="function",
            ),
            entity_factory(
                entity_id="class_alpha",
                project_id=project_a,
                name="AlphaClass",
                entity_type="class",
            ),
        ]
        await graph_provider.upsert_entities(entities_a, project_a)

        # Add entities to project B
        entities_b = [
            entity_factory(
                entity_id="func_beta",
                project_id=project_b,
                name="beta_function",
                entity_type="function",
            ),
        ]
        await graph_provider.upsert_entities(entities_b, project_b)

        # Query project A - should only see project A entities
        results_a = await graph_provider.get_entities_by_type("function", project_a)
        entity_ids_a = [e.id for e in results_a]
        assert "func_alpha" in entity_ids_a
        assert "func_beta" not in entity_ids_a

        # Query project B - should only see project B entities
        results_b = await graph_provider.get_entities_by_type("function", project_b)
        entity_ids_b = [e.id for e in results_b]
        assert "func_beta" in entity_ids_b
        assert "func_alpha" not in entity_ids_b

    @pytest.mark.asyncio
    async def test_relationships_isolated_between_projects(
        self, graph_provider, entity_factory, relationship_factory
    ):
        """Relationships from project A should not be visible in project B."""
        # Skip if provider doesn't support relationships
        if not hasattr(graph_provider, "upsert_relationships"):
            pytest.skip("Provider does not support relationships")

        project_a = "project-alpha"
        project_b = "project-beta"

        # Setup entities and relationships in project A
        entities_a = [
            entity_factory(entity_id="a_caller", project_id=project_a),
            entity_factory(entity_id="a_callee", project_id=project_a),
        ]
        await graph_provider.upsert_entities(entities_a, project_a)

        rel_a = relationship_factory(
            source_id="a_caller",
            target_id="a_callee",
            rel_type="calls",
            project_id=project_a,
        )
        await graph_provider.upsert_relationships([rel_a], project_a)

        # Setup entities and relationships in project B
        entities_b = [
            entity_factory(entity_id="b_caller", project_id=project_b),
            entity_factory(entity_id="b_callee", project_id=project_b),
        ]
        await graph_provider.upsert_entities(entities_b, project_b)

        rel_b = relationship_factory(
            source_id="b_caller",
            target_id="b_callee",
            rel_type="calls",
            project_id=project_b,
        )
        await graph_provider.upsert_relationships([rel_b], project_b)

        # Query relationships in project A
        rels_a = await graph_provider.get_relationships_by_entity(
            "a_caller", project_id=project_a
        )
        assert len(rels_a) >= 1
        assert all(r.source_id == "a_caller" for r in rels_a)
        assert all(r.target_id != "b_callee" for r in rels_a)

        # Query relationships in project B
        rels_b = await graph_provider.get_relationships_by_entity(
            "b_caller", project_id=project_b
        )
        assert len(rels_b) >= 1
        assert all(r.source_id == "b_caller" for r in rels_b)
        assert all(r.target_id != "a_callee" for r in rels_b)


class TestConcurrentProjectAccess:
    """Tests for concurrent operations on different projects."""

    @pytest.mark.asyncio
    async def test_concurrent_chunk_upserts_dont_interfere(
        self, vector_provider, chunk_factory
    ):
        """Concurrent upserts to different projects should not interfere."""
        project_a = "project-alpha"
        project_b = "project-beta"
        project_c = "project-gamma"

        # Create chunks for three different projects
        chunks_a = [
            chunk_factory(
                chunk_id=f"a{i}",
                project_id=project_a,
                file_path=f"/src/a{i}.py",
            )
            for i in range(10)
        ]
        chunks_b = [
            chunk_factory(
                chunk_id=f"b{i}",
                project_id=project_b,
                file_path=f"/src/b{i}.py",
            )
            for i in range(10)
        ]
        chunks_c = [
            chunk_factory(
                chunk_id=f"c{i}",
                project_id=project_c,
                file_path=f"/src/c{i}.py",
            )
            for i in range(10)
        ]

        # Upsert all three concurrently
        results = await asyncio.gather(
            vector_provider.upsert_chunks(chunks_a, project_a),
            vector_provider.upsert_chunks(chunks_b, project_b),
            vector_provider.upsert_chunks(chunks_c, project_c),
        )

        # Verify all succeeded
        assert results[0] == 10
        assert results[1] == 10
        assert results[2] == 10

        # Verify isolation - each project should only see its own chunks
        for i in range(10):
            chunks_from_a = await vector_provider.get_chunks_by_file(
                f"/src/a{i}.py", project_a
            )
            assert len(chunks_from_a) == 1
            assert chunks_from_a[0].id == f"a{i}"

            chunks_from_b = await vector_provider.get_chunks_by_file(
                f"/src/b{i}.py", project_b
            )
            assert len(chunks_from_b) == 1
            assert chunks_from_b[0].id == f"b{i}"

            chunks_from_c = await vector_provider.get_chunks_by_file(
                f"/src/c{i}.py", project_c
            )
            assert len(chunks_from_c) == 1
            assert chunks_from_c[0].id == f"c{i}"

    @pytest.mark.asyncio
    async def test_concurrent_entity_upserts_dont_interfere(
        self, graph_provider, entity_factory
    ):
        """Concurrent entity upserts to different projects should not interfere."""
        project_a = "project-alpha"
        project_b = "project-beta"

        entities_a = [
            entity_factory(
                entity_id=f"a_func_{i}",
                project_id=project_a,
                name=f"func_a_{i}",
            )
            for i in range(5)
        ]
        entities_b = [
            entity_factory(
                entity_id=f"b_func_{i}",
                project_id=project_b,
                name=f"func_b_{i}",
            )
            for i in range(5)
        ]

        # Upsert concurrently
        await asyncio.gather(
            graph_provider.upsert_entities(entities_a, project_a),
            graph_provider.upsert_entities(entities_b, project_b),
        )

        # Verify isolation
        all_a = await graph_provider.get_entities_by_type("function", project_a)
        a_ids = [e.id for e in all_a]
        assert all(entity_id.startswith("a_") for entity_id in a_ids)

        all_b = await graph_provider.get_entities_by_type("function", project_b)
        b_ids = [e.id for e in all_b]
        assert all(entity_id.startswith("b_") for entity_id in b_ids)

    @pytest.mark.asyncio
    async def test_concurrent_read_write_different_projects(
        self, vector_provider, chunk_factory
    ):
        """Concurrent reads and writes to different projects should not interfere."""
        project_a = "project-alpha"
        project_b = "project-beta"

        # Setup initial data in both projects
        chunks_a = [
            chunk_factory(
                chunk_id="a1",
                project_id=project_a,
                file_path="/src/alpha.py",
            )
        ]
        chunks_b = [
            chunk_factory(
                chunk_id="b1",
                project_id=project_b,
                file_path="/src/beta.py",
            )
        ]

        await vector_provider.upsert_chunks(chunks_a, project_a)
        await vector_provider.upsert_chunks(chunks_b, project_b)

        # Concurrently: write to project A, read from project B
        async def write_to_a():
            new_chunks = [
                chunk_factory(
                    chunk_id=f"a{i}",
                    project_id=project_a,
                    file_path=f"/src/alpha_{i}.py",
                )
                for i in range(2, 12)
            ]
            return await vector_provider.upsert_chunks(new_chunks, project_a)

        async def read_from_b():
            results = []
            for _ in range(5):
                chunks = await vector_provider.get_chunks_by_file(
                    "/src/beta.py", project_b
                )
                results.append(chunks)
                await asyncio.sleep(0.01)  # Small delay to interleave operations
            return results

        write_result, read_results = await asyncio.gather(
            write_to_a(),
            read_from_b(),
        )

        # Write should succeed
        assert write_result == 10

        # All reads from project B should be consistent and unaffected
        for chunks in read_results:
            assert len(chunks) == 1
            assert chunks[0].id == "b1"


class TestProjectScopedQueries:
    """Tests for project-scoped query operations."""

    @pytest.mark.asyncio
    async def test_count_respects_project_scope(self, vector_provider, chunk_factory):
        """Count operations should only count chunks in the specified project."""
        project_a = "project-alpha"
        project_b = "project-beta"

        # Add different numbers of chunks to each project
        chunks_a = [
            chunk_factory(chunk_id=f"a{i}", project_id=project_a) for i in range(5)
        ]
        chunks_b = [
            chunk_factory(chunk_id=f"b{i}", project_id=project_b) for i in range(3)
        ]

        await vector_provider.upsert_chunks(chunks_a, project_a)
        await vector_provider.upsert_chunks(chunks_b, project_b)

        # Count should respect project boundaries
        count_a = await vector_provider.count(project_id=project_a)
        count_b = await vector_provider.count(project_id=project_b)

        assert count_a == 5
        assert count_b == 3

    @pytest.mark.asyncio
    async def test_delete_by_file_respects_project_scope(
        self, vector_provider, chunk_factory
    ):
        """Deleting by file should only affect chunks in the specified project."""
        project_a = "project-alpha"
        project_b = "project-beta"
        shared_file_path = "/src/shared_name.py"

        # Both projects have files with the same name
        chunks_a = [
            chunk_factory(
                chunk_id="a1",
                project_id=project_a,
                file_path=shared_file_path,
            ),
            chunk_factory(
                chunk_id="a2",
                project_id=project_a,
                file_path=shared_file_path,
            ),
        ]
        chunks_b = [
            chunk_factory(
                chunk_id="b1",
                project_id=project_b,
                file_path=shared_file_path,
            ),
        ]

        await vector_provider.upsert_chunks(chunks_a, project_a)
        await vector_provider.upsert_chunks(chunks_b, project_b)

        # Delete from project A only
        deleted = await vector_provider.delete_chunks_by_file(
            shared_file_path, project_a
        )

        assert deleted == 2

        # Verify project A's chunks are deleted
        remaining_a = await vector_provider.get_chunks_by_file(
            shared_file_path, project_a
        )
        assert len(remaining_a) == 0

        # Verify project B's chunks are untouched
        remaining_b = await vector_provider.get_chunks_by_file(
            shared_file_path, project_b
        )
        assert len(remaining_b) == 1
        assert remaining_b[0].id == "b1"

    @pytest.mark.asyncio
    async def test_get_entities_by_type_respects_project_scope(
        self, graph_provider, entity_factory
    ):
        """Getting entities by type should respect project boundaries."""
        project_a = "project-alpha"
        project_b = "project-beta"

        # Both projects have function entities with distinct names
        entities_a = [
            entity_factory(
                entity_id="a_process",
                project_id=project_a,
                name="process_data_a",
                entity_type="function",
            ),
        ]
        entities_b = [
            entity_factory(
                entity_id="b_process",
                project_id=project_b,
                name="process_data_b",
                entity_type="function",
            ),
        ]

        await graph_provider.upsert_entities(entities_a, project_a)
        await graph_provider.upsert_entities(entities_b, project_b)

        # Query by type in each project
        results_a = await graph_provider.get_entities_by_type("function", project_a)
        results_b = await graph_provider.get_entities_by_type("function", project_b)

        # Each project should only see its own entity
        a_ids = [e.id for e in results_a]
        b_ids = [e.id for e in results_b]

        assert "a_process" in a_ids
        assert "b_process" not in a_ids

        assert "b_process" in b_ids
        assert "a_process" not in b_ids


class TestProjectDeletionCleanup:
    """Tests for cleanup when deleting all data for a project."""

    @pytest.mark.asyncio
    async def test_delete_all_chunks_for_project(self, vector_provider, chunk_factory):
        """Should be able to delete all chunks for a specific project."""
        project_a = "project-alpha"
        project_b = "project-beta"

        # Setup data in both projects
        chunks_a = [
            chunk_factory(
                chunk_id=f"a{i}",
                project_id=project_a,
                file_path=f"/src/file_{i}.py",
            )
            for i in range(5)
        ]
        chunks_b = [
            chunk_factory(
                chunk_id=f"b{i}",
                project_id=project_b,
                file_path=f"/src/file_{i}.py",
            )
            for i in range(3)
        ]

        await vector_provider.upsert_chunks(chunks_a, project_a)
        await vector_provider.upsert_chunks(chunks_b, project_b)

        # Delete all chunks from project A
        total_deleted = 0
        for i in range(5):
            deleted = await vector_provider.delete_chunks_by_file(
                f"/src/file_{i}.py", project_a
            )
            total_deleted += deleted

        assert total_deleted == 5

        # Verify project A has no chunks
        count_a = await vector_provider.count(project_id=project_a)
        assert count_a == 0

        # Verify project B is unaffected
        count_b = await vector_provider.count(project_id=project_b)
        assert count_b == 3

    @pytest.mark.asyncio
    async def test_delete_all_entities_for_project(
        self, graph_provider, entity_factory
    ):
        """Should be able to delete all entities for a specific project."""
        project_a = "project-alpha"
        project_b = "project-beta"

        # Setup entities in both projects
        entities_a = [
            entity_factory(
                entity_id=f"a_entity_{i}",
                project_id=project_a,
                entity_type="function",
            )
            for i in range(4)
        ]
        entities_b = [
            entity_factory(
                entity_id=f"b_entity_{i}",
                project_id=project_b,
                entity_type="function",
            )
            for i in range(2)
        ]

        await graph_provider.upsert_entities(entities_a, project_a)
        await graph_provider.upsert_entities(entities_b, project_b)

        # Delete all entities from project A
        entity_ids_a = [f"a_entity_{i}" for i in range(4)]
        deleted = await graph_provider.delete_entities_by_ids(entity_ids_a, project_a)

        assert deleted == 4

        # Verify project A has no entities
        remaining_a = await graph_provider.get_entities_by_type("function", project_a)
        assert len(remaining_a) == 0

        # Verify project B is unaffected
        remaining_b = await graph_provider.get_entities_by_type("function", project_b)
        assert len(remaining_b) == 2

    @pytest.mark.asyncio
    async def test_delete_relationships_cascade_respects_project(
        self, graph_provider, entity_factory, relationship_factory
    ):
        """Deleting entities should only cascade delete relationships in same project."""
        # Skip if provider doesn't support relationships
        if not hasattr(graph_provider, "upsert_relationships"):
            pytest.skip("Provider does not support relationships")

        project_a = "project-alpha"
        project_b = "project-beta"

        # Setup entities in both projects with similar structure
        entities_a = [
            entity_factory(entity_id="a_caller", project_id=project_a),
            entity_factory(entity_id="a_callee", project_id=project_a),
        ]
        entities_b = [
            entity_factory(entity_id="b_caller", project_id=project_b),
            entity_factory(entity_id="b_callee", project_id=project_b),
        ]

        await graph_provider.upsert_entities(entities_a, project_a)
        await graph_provider.upsert_entities(entities_b, project_b)

        # Create relationships in both projects
        rel_a = relationship_factory(
            source_id="a_caller",
            target_id="a_callee",
            rel_type="calls",
            project_id=project_a,
        )
        rel_b = relationship_factory(
            source_id="b_caller",
            target_id="b_callee",
            rel_type="calls",
            project_id=project_b,
        )

        await graph_provider.upsert_relationships([rel_a], project_a)
        await graph_provider.upsert_relationships([rel_b], project_b)

        # Delete entity from project A
        await graph_provider.delete_entities_by_ids(["a_caller"], project_a)

        # Verify project A relationship is deleted
        rels_a = await graph_provider.get_relationships_by_entity(
            "a_caller", project_id=project_a
        )
        assert len(rels_a) == 0

        # Verify project B is unaffected
        rels_b = await graph_provider.get_relationships_by_entity(
            "b_caller", project_id=project_b
        )
        assert len(rels_b) >= 1

    @pytest.mark.asyncio
    async def test_complete_project_cleanup(
        self,
        vector_provider,
        graph_provider,
        chunk_factory,
        entity_factory,
        relationship_factory,
    ):
        """Should be able to completely clean up all data for a project."""
        project_to_delete = "project-to-delete"
        project_to_keep = "project-to-keep"

        # Setup comprehensive data in both projects
        # Chunks
        chunks_delete = [
            chunk_factory(
                chunk_id=f"del_{i}",
                project_id=project_to_delete,
                file_path=f"/src/delete_{i}.py",
            )
            for i in range(3)
        ]
        chunks_keep = [
            chunk_factory(
                chunk_id=f"keep_{i}",
                project_id=project_to_keep,
                file_path=f"/src/keep_{i}.py",
            )
            for i in range(2)
        ]

        await vector_provider.upsert_chunks(chunks_delete, project_to_delete)
        await vector_provider.upsert_chunks(chunks_keep, project_to_keep)

        # Entities
        entities_delete = [
            entity_factory(
                entity_id=f"del_func_{i}",
                project_id=project_to_delete,
                entity_type="function",
            )
            for i in range(3)
        ]
        entities_keep = [
            entity_factory(
                entity_id=f"keep_func_{i}",
                project_id=project_to_keep,
                entity_type="function",
            )
            for i in range(2)
        ]

        await graph_provider.upsert_entities(entities_delete, project_to_delete)
        await graph_provider.upsert_entities(entities_keep, project_to_keep)

        # Relationships
        rel_delete = relationship_factory(
            source_id="del_func_0",
            target_id="del_func_1",
            rel_type="calls",
            project_id=project_to_delete,
        )
        rel_keep = relationship_factory(
            source_id="keep_func_0",
            target_id="keep_func_1",
            rel_type="calls",
            project_id=project_to_keep,
        )

        await graph_provider.upsert_relationships([rel_delete], project_to_delete)
        await graph_provider.upsert_relationships([rel_keep], project_to_keep)

        # Perform cleanup for project_to_delete
        # 1. Delete all chunks
        for i in range(3):
            await vector_provider.delete_chunks_by_file(
                f"/src/delete_{i}.py", project_to_delete
            )

        # 2. Delete all entities (which should cascade delete relationships)
        entity_ids_to_delete = [f"del_func_{i}" for i in range(3)]
        await graph_provider.delete_entities_by_ids(
            entity_ids_to_delete, project_to_delete
        )

        # Verify project_to_delete is completely cleaned up
        chunks_remaining = await vector_provider.count(project_id=project_to_delete)
        assert chunks_remaining == 0

        entities_remaining = await graph_provider.get_entities_by_type(
            "function", project_to_delete
        )
        assert len(entities_remaining) == 0

        # Verify project_to_keep is unaffected
        chunks_kept = await vector_provider.count(project_id=project_to_keep)
        assert chunks_kept == 2

        entities_kept = await graph_provider.get_entities_by_type(
            "function", project_to_keep
        )
        assert len(entities_kept) == 2

        rels_kept = await graph_provider.get_relationships_by_entity(
            "keep_func_0", project_id=project_to_keep
        )
        assert len(rels_kept) >= 1


class TestEdgeCases:
    """Edge cases and boundary conditions for project isolation."""

    @pytest.mark.asyncio
    async def test_whitespace_project_id_handled_safely(
        self, vector_provider, chunk_factory
    ):
        """Project IDs with whitespace should be handled correctly."""
        whitespace_project = "project with spaces"
        normal_project = "normal-project"

        # Add chunks to both
        chunk_whitespace = chunk_factory(
            chunk_id="ws1",
            project_id=whitespace_project,
            file_path="/src/ws.py",
        )
        chunk_normal = chunk_factory(
            chunk_id="normal1",
            project_id=normal_project,
            file_path="/src/normal.py",
        )

        await vector_provider.upsert_chunks([chunk_whitespace], whitespace_project)
        await vector_provider.upsert_chunks([chunk_normal], normal_project)

        # Verify isolation
        ws_results = await vector_provider.get_chunks_by_file(
            "/src/ws.py", whitespace_project
        )
        normal_results = await vector_provider.get_chunks_by_file(
            "/src/normal.py", normal_project
        )

        assert len(ws_results) == 1
        assert len(normal_results) == 1
        assert ws_results[0].id != normal_results[0].id

    @pytest.mark.asyncio
    async def test_special_characters_in_project_id(
        self, vector_provider, chunk_factory
    ):
        """Project IDs with special characters should be properly isolated."""
        project_with_special = "project-with-special_chars.123"
        normal_project = "normal"

        chunks_special = [
            chunk_factory(
                chunk_id="special1",
                project_id=project_with_special,
                file_path="/src/special.py",
            )
        ]
        chunks_normal = [
            chunk_factory(
                chunk_id="normal1",
                project_id=normal_project,
                file_path="/src/normal.py",
            )
        ]

        await vector_provider.upsert_chunks(chunks_special, project_with_special)
        await vector_provider.upsert_chunks(chunks_normal, normal_project)

        # Verify isolation
        special_results = await vector_provider.get_chunks_by_file(
            "/src/special.py", project_with_special
        )
        normal_results = await vector_provider.get_chunks_by_file(
            "/src/normal.py", normal_project
        )

        assert len(special_results) == 1
        assert len(normal_results) == 1

    @pytest.mark.asyncio
    async def test_many_projects_isolation_scales(self, vector_provider, chunk_factory):
        """Isolation should work correctly with many concurrent projects."""
        num_projects = 10
        projects = [f"project-{i}" for i in range(num_projects)]

        # Add chunks to each project
        for i, project_id in enumerate(projects):
            chunk = chunk_factory(
                chunk_id=f"chunk_{i}",
                project_id=project_id,
                file_path=f"/src/file_{i}.py",
            )
            await vector_provider.upsert_chunks([chunk], project_id)

        # Verify each project only sees its own chunk
        for i, project_id in enumerate(projects):
            results = await vector_provider.get_chunks_by_file(
                f"/src/file_{i}.py", project_id
            )
            assert len(results) == 1
            assert results[0].id == f"chunk_{i}"

            # Should not see chunks from other projects
            for j in range(num_projects):
                if j != i:
                    wrong_results = await vector_provider.get_chunks_by_file(
                        f"/src/file_{j}.py", project_id
                    )
                    assert len(wrong_results) == 0
