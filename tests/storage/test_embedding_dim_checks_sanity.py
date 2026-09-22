"""Sanity checks for the embedding-dim immutability plumbing.

These aren't end-to-end tests — they lock down small invariants the PR
relies on so regressions show up loudly rather than as subtle drift:

- Any DDL that will be checked at init time must actually contain an
  ``embedding vector(N)`` column (otherwise the pg_attribute query
  silently returns ``None`` and the check becomes a no-op).
- The shared :class:`DimensionMismatch` requires a ``backend`` — old
  3-arg positional construction must fail at import/construct time, not
  silently pick up a stale default.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from agent_vault.storage.errors import DimensionMismatch
from agent_vault.storage.providers.alloydb.schemas import (
    AlloyDBSchemaGenerator,
)
from agent_vault.storage.providers.postgresql.schemas import (
    ENTITIES_TABLE,
    ENTITY_EMBEDDINGS_TABLE,
    SchemaGenerator,
)


class TestSchemaHasEmbeddingColumn:
    """Tables we ask the tracker to check must actually have the column.

    ``SchemaVersionTracker.detect_dimension_mismatch`` queries
    ``pg_attribute`` with a hard-coded ``attname = 'embedding'``. If the
    DDL for a checked table ever loses that column (e.g. a refactor splits
    embeddings into a sibling table), the tracker returns ``None`` and the
    check silently no-ops. These assertions surface that drift early.
    """

    def test_entities_ddl_has_embedding_vector_column(self):
        """ENTITIES_TABLE has ``embedding vector(N)`` unconditionally.

        This is the claim the graph provider relies on for both local and
        server-side modes — a dim mismatch on ``g_entities`` must be
        detectable regardless of strategy.
        """
        gen = SchemaGenerator(prefix="agv_test_", embedding_dim=384)
        ddl = gen.generate_create_table(ENTITIES_TABLE)
        assert "embedding vector(384)" in ddl

    def test_entity_embeddings_ddl_has_embedding_vector_column(self):
        gen = SchemaGenerator(prefix="agv_test_", embedding_dim=384)
        ddl = gen.generate_create_table(ENTITY_EMBEDDINGS_TABLE)
        assert "embedding vector(384)" in ddl

    def test_alloydb_entities_ddl_has_embedding_vector_column(self):
        """AlloyDB server-side schema *also* puts an embedding column on g_entities.

        It's a ``GENERATED ALWAYS`` column, but structurally still
        ``embedding vector(N)`` — so pg_attribute's ``atttypmod`` picks
        up the width and the dim check fires identically.
        """
        gen = AlloyDBSchemaGenerator(prefix="agv_test_", embedding_dim=768)
        statements = gen.get_create_statements("graph")
        entities_ddl = next(s for s in statements if "entities" in s and "CREATE TABLE" in s)
        assert "embedding vector(768)" in entities_ddl
        # And the column is GENERATED — confirm we're not just looking at
        # some other placeholder line.
        assert "GENERATED ALWAYS AS" in entities_ddl


class TestDimensionMismatchSignature:
    """Constructing ``DimensionMismatch`` with the pre-PR 3-arg shape must fail.

    The shared dataclass adds a required ``backend`` field (no default).
    Anyone upgrading an out-of-tree caller that previously did
    ``DimensionMismatch(table_name, configured, actual)`` positionally
    will get a :class:`TypeError` at construct time — loud enough to
    catch in their own tests.
    """

    def test_backend_is_required_positional_first(self):
        # Old 3-arg positional: (table_name, configured, actual) would now
        # be interpreted as (backend=<table_name>, table_name=<configured>,
        # configured=<actual>) and then error on the missing ``actual``.
        with pytest.raises(TypeError):
            DimensionMismatch("some_table", 384, 768)  # type: ignore[call-arg]

    def test_all_four_required_positional_args_work(self):
        mm = DimensionMismatch("postgresql", "t", 384, 768)
        assert mm.backend == "postgresql"
        assert mm.table_name == "t"
        assert mm.configured == 384
        assert mm.actual == 768

    def test_backend_has_no_default(self):
        """Guard against a future refactor quietly adding a default."""
        sig = inspect.signature(DimensionMismatch)
        assert sig.parameters["backend"].default is inspect.Parameter.empty
