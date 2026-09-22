"""Cross-backend filter contract tests.

The :class:`FilterTranslator` protocol promises that a given filter input
(dict or :class:`Filter` AST) has the *same semantics* on every backend.
These tests exercise the core operator set against memory / LanceDB /
Postgres via each vector provider's ``query`` and ``count`` methods —
guarding against divergence when a new backend lands (OpenSearch,
Neptune) or when one backend's translator path drifts.

All tests use the ``vector_provider`` parametrized fixture from
``conftest.py``, which skips Postgres if the local container isn't up.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

from agentic_inquiry.database.filters import and_, eq, ilike, is_in, not_in, or_


@pytest.fixture
async def filter_chunks(vector_provider, project_id, chunk_factory):
    """Upsert a fixed set of chunks covering every filter shape we test."""
    chunks = [
        chunk_factory(
            chunk_id="auth_login",
            project_id=project_id,
            file_path="/auth/login.py",
            content="AuthService.login",
            content_type="CODE",
        ),
        chunk_factory(
            chunk_id="auth_logout",
            project_id=project_id,
            file_path="/auth/logout.py",
            content="AuthService.logout",
            content_type="CODE",
        ),
        chunk_factory(
            chunk_id="db_query",
            project_id=project_id,
            file_path="/db/query.py",
            content="DatabaseQuery.run",
            content_type="CODE",
        ),
        chunk_factory(
            chunk_id="readme",
            project_id=project_id,
            file_path="/docs/README.md",
            content="Project overview",
            content_type="PROSE",
        ),
        chunk_factory(
            chunk_id="guide",
            project_id=project_id,
            file_path="/docs/guide.md",
            content="Setup guide",
            content_type="PROSE",
        ),
    ]
    await vector_provider.upsert_chunks(chunks, project_id)
    return chunks


class TestFilterContract:
    """Every backend must honour these filter semantics identically."""

    async def test_equality(self, vector_provider, project_id, filter_chunks):
        total = await vector_provider.count(
            filters={"content_type": "CODE"}, project_id=project_id
        )
        assert total == 3

    async def test_equality_via_ast(self, vector_provider, project_id, filter_chunks):
        total = await vector_provider.count(
            filters=eq("content_type", "CODE"), project_id=project_id
        )
        assert total == 3

    async def test_in_list_matches_any(
        self, vector_provider, project_id, filter_chunks
    ):
        total = await vector_provider.count(
            filters={"file_path": ("IN", ["/auth/login.py", "/db/query.py"])},
            project_id=project_id,
        )
        assert total == 2

    async def test_in_ast(self, vector_provider, project_id, filter_chunks):
        total = await vector_provider.count(
            filters=is_in("file_path", ["/auth/login.py", "/db/query.py"]),
            project_id=project_id,
        )
        assert total == 2

    async def test_not_in_excludes(self, vector_provider, project_id, filter_chunks):
        total = await vector_provider.count(
            filters=not_in("content_type", ["PROSE"]),
            project_id=project_id,
        )
        assert total == 3

    async def test_ilike_case_insensitive(
        self, vector_provider, project_id, filter_chunks
    ):
        # ``AuthService.login`` matches the uppercase-letter pattern.
        total = await vector_provider.count(
            filters=ilike("content", "%AUTHSERVICE%"),
            project_id=project_id,
        )
        assert total == 2

    async def test_and_compound(self, vector_provider, project_id, filter_chunks):
        total = await vector_provider.count(
            filters=and_(
                eq("content_type", "CODE"),
                ilike("file_path", "/auth/%"),
            ),
            project_id=project_id,
        )
        assert total == 2

    async def test_or_compound(self, vector_provider, project_id, filter_chunks):
        total = await vector_provider.count(
            filters=or_(
                eq("content_type", "PROSE"),
                eq("file_path", "/db/query.py"),
            ),
            project_id=project_id,
        )
        assert total == 3

    async def test_query_returns_matching_rows(
        self, vector_provider, project_id, filter_chunks
    ):
        rows = await vector_provider.query(
            filters={"content_type": "PROSE"},
            project_id=project_id,
        )
        ids = sorted(r.id for r in rows)
        assert ids == ["guide", "readme"]

    async def test_empty_in_matches_nothing(
        self, vector_provider, project_id, filter_chunks
    ):
        total = await vector_provider.count(
            filters=is_in("content_type", []),
            project_id=project_id,
        )
        assert total == 0

    async def test_empty_not_in_is_no_restriction(
        self, vector_provider, project_id, filter_chunks
    ):
        total = await vector_provider.count(
            filters=not_in("content_type", []),
            project_id=project_id,
        )
        assert total == 5

    async def test_filters_reject_invalid_field_name(
        self, vector_provider, project_id, filter_chunks
    ):
        """Dict keys go through the same field-name validator as AST nodes.

        The pre-adapter Postgres path interpolated field names raw into SQL
        — this test guards against that regression. Requires at least one
        row persisted so the backends actually invoke the filter path
        (memory short-circuits ``count`` on empty collections; LanceDB
        short-circuits when the table doesn't exist yet).
        """
        with pytest.raises(ValueError):
            await vector_provider.count(
                filters={"1=1; DROP TABLE chunks--": "x"},
                project_id=project_id,
            )


# Note: a cross-backend ``GT``/``LT`` contract test is intentionally omitted
# here — the chunk schema's numeric columns diverge (Postgres stores
# ``start_line`` / ``end_line``, the DocumentChunk model exposes
# ``line_start`` / ``line_end``). Adapter-level unit tests in
# ``tests/database/test_filter_adapters.py`` cover comparison operators
# against each translator directly; this suite focuses on operator
# coverage that's field-name-portable across all three backends.
