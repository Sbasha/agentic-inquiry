"""Cross-backend contract tests for ``entity_vector_search``.

The method moved off ``GraphStorageProtocol`` onto ``VectorStorageProtocol``
— these tests pin that every in-tree backend (memory / LanceDB / Postgres)
serves it with matching semantics:

- filters by ``project_id``,
- honours the optional ``entity_type`` argument,
- ranks by similarity (ascending ``_distance``),
- respects ``limit``.

Contract tests run via the parameterized ``vector_provider`` fixture —
Postgres is skipped when the container isn't up.
"""

from __future__ import annotations

import math

import pytest

pytestmark = pytest.mark.asyncio


def _orthogonal_pair(dim: int) -> tuple[list[float], list[float]]:
    """Two orthogonal unit vectors at 90°.

    Their cosine similarity is 0, giving a cosine distance of 1 under the
    ``1 - cosine_similarity`` convention (maximum is 2, achieved by
    opposite vectors with similarity -1; these tests don't need that).
    Using axis-aligned unit vectors avoids floating-point noise across
    backends that normalize internally.
    """
    a = [1.0] + [0.0] * (dim - 1)
    b = [0.0, 1.0] + [0.0] * (dim - 2)
    return a, b


async def _seed_entities(
    vector_provider,
    project_id: str,
    entity_factory,
    dim: int = 384,
) -> tuple[str, str, str]:
    """Insert three entities whose embeddings rank predictably.

    - ``auth_fn``: vector points along axis 0 (query target).
    - ``other_fn``: vector along axis 1 (orthogonal to query).
    - ``auth_cls``: vector along axis 0 but entity_type is 'class' so the
      type filter can exclude it.

    Returns a tuple of their IDs.
    """
    axis0, axis1 = _orthogonal_pair(dim)
    auth_fn = entity_factory(
        entity_id="auth_fn",
        project_id=project_id,
        name="authenticate",
        entity_type="function",
        vector=axis0,
    )
    other_fn = entity_factory(
        entity_id="other_fn",
        project_id=project_id,
        name="unrelated",
        entity_type="function",
        vector=axis1,
    )
    auth_cls = entity_factory(
        entity_id="auth_cls",
        project_id=project_id,
        name="AuthController",
        entity_type="class",
        vector=axis0,
    )
    # Check if the provider has upsert_entities (it's a graph op, so not
    # every fixture backend will). When it doesn't, skip — the entity
    # vector search has nothing to search against.
    if not hasattr(vector_provider, "upsert_entities"):
        pytest.skip(f"{type(vector_provider).__name__} is vector-only in this fixture")
    await vector_provider.upsert_entities([auth_fn, other_fn, auth_cls], project_id)
    return auth_fn.id, other_fn.id, auth_cls.id


class TestEntityVectorSearchContract:
    async def test_ranks_matching_entity_first(
        self, vector_provider, project_id, entity_factory
    ):
        auth_id, other_id, _ = await _seed_entities(
            vector_provider, project_id, entity_factory
        )
        query, _ = _orthogonal_pair(384)

        results = await vector_provider.entity_vector_search(
            query_vector=query,
            project_id=project_id,
            limit=10,
        )
        assert len(results) >= 1
        # The axis-aligned match must rank ahead of the orthogonal one.
        ranked_ids = [e.id for e in results]
        assert ranked_ids.index(auth_id) < ranked_ids.index(other_id)

    async def test_respects_entity_type_filter(
        self, vector_provider, project_id, entity_factory
    ):
        auth_fn_id, _, auth_cls_id = await _seed_entities(
            vector_provider, project_id, entity_factory
        )
        query, _ = _orthogonal_pair(384)

        results = await vector_provider.entity_vector_search(
            query_vector=query,
            project_id=project_id,
            limit=10,
            entity_type="class",
        )
        ids = {e.id for e in results}
        assert auth_cls_id in ids
        assert auth_fn_id not in ids

    async def test_respects_limit(self, vector_provider, project_id, entity_factory):
        await _seed_entities(vector_provider, project_id, entity_factory)
        query, _ = _orthogonal_pair(384)

        results = await vector_provider.entity_vector_search(
            query_vector=query,
            project_id=project_id,
            limit=1,
        )
        assert len(results) <= 1

    async def test_annotates_distance(
        self, vector_provider, project_id, entity_factory
    ):
        await _seed_entities(vector_provider, project_id, entity_factory)
        query, _ = _orthogonal_pair(384)

        results = await vector_provider.entity_vector_search(
            query_vector=query,
            project_id=project_id,
            limit=5,
        )
        assert results, "expected at least one result"
        for entity in results:
            assert hasattr(entity, "_distance")
            assert isinstance(entity._distance, (int, float))
            assert not math.isnan(entity._distance)

    async def test_project_isolation(self, vector_provider, project_id, entity_factory):
        """Entities in a different project must not appear in results.

        A weaker version of this test (just asserting ``[] == []``) can
        pass spuriously because the LanceDB impl catches all exceptions
        and returns ``[]``. Strengthen by verifying the row **is**
        reachable from its own project — so ``[]`` from a different
        project really means "filtered out" and not "whole query failed".
        """
        await _seed_entities(vector_provider, project_id, entity_factory)
        query, _ = _orthogonal_pair(384)

        # Sanity: the seeded rows are reachable from their own project.
        own_project = await vector_provider.entity_vector_search(
            query_vector=query,
            project_id=project_id,
            limit=10,
        )
        assert own_project, (
            "Expected at least one result from the seeded project; got [] — "
            "either the upsert didn't land or the query failed silently."
        )

        # Different project scope: must be empty.
        other_project = await vector_provider.entity_vector_search(
            query_vector=query,
            project_id="some_other_project_id_not_seeded",
            limit=10,
        )
        assert other_project == []

    async def test_str_query_rejected_on_client_side_embedding(
        self, vector_provider, project_id, entity_factory
    ):
        """Per the protocol, backends without server-side embedding SHOULD
        raise ``TypeError`` on ``str`` input. Memory and LanceDB both
        qualify; Postgres is skipped by the fixture shape. AlloyDB /
        server-side RDS paths would *accept* ``str`` — covered by their
        own live-integration tests, not this contract suite.
        """
        if not hasattr(vector_provider, "upsert_entities"):
            pytest.skip(
                f"{type(vector_provider).__name__} is vector-only in this fixture"
            )
        with pytest.raises(TypeError):
            await vector_provider.entity_vector_search(
                query_vector="a raw string query",  # type: ignore[arg-type]
                project_id=project_id,
                limit=5,
            )

    async def test_project_id_with_apostrophe_does_not_break(
        self, vector_provider, entity_factory
    ):
        """Project IDs containing ``'`` must be escaped, not break the query.

        Regression guard for the LanceDB f-string interpolation path that
        used to emit ``project_id = 'alice's_proj'`` — unclosed quote,
        query breaks, potential expression injection. After the fix the
        value flows through the AST translator which doubles the quote.
        """
        if not hasattr(vector_provider, "upsert_entities"):
            pytest.skip(
                f"{type(vector_provider).__name__} is vector-only in this fixture"
            )
        apostrophe_project = "alice's_proj"
        axis0, _ = _orthogonal_pair(384)
        entity = entity_factory(
            entity_id="quoted",
            project_id=apostrophe_project,
            name="fn",
            entity_type="function",
            vector=axis0,
        )
        await vector_provider.upsert_entities([entity], apostrophe_project)

        results = await vector_provider.entity_vector_search(
            query_vector=axis0,
            project_id=apostrophe_project,
            limit=5,
        )
        assert [e.id for e in results] == ["quoted"]
