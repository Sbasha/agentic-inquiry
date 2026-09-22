"""Unit tests for shared storage error types.

Covers the contract that LanceDB, PostgreSQL, and future backends share the
same error and mismatch-data shape so cross-cutting callers (CLI, migration
tooling) can handle them uniformly.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from agent_vault.storage.errors import DimensionMismatch, SchemaMismatchError


class TestSchemaMismatchError:
    def test_is_exception_subclass(self):
        assert issubclass(SchemaMismatchError, Exception)

    def test_constructs_with_message(self):
        err = SchemaMismatchError("dim mismatch: configured=768 actual=384")
        assert "768" in str(err)
        assert "384" in str(err)


class TestDimensionMismatch:
    def test_fields_populate_and_format(self):
        mismatch = DimensionMismatch(
            backend="postgresql",
            table_name="agv_v_chunks",
            configured=1536,
            actual=768,
        )
        assert mismatch.backend == "postgresql"
        assert mismatch.table_name == "agv_v_chunks"
        assert mismatch.configured == 1536
        assert mismatch.actual == 768
        assert mismatch.column == "embedding"  # default

        rendered = str(mismatch)
        assert "postgresql" in rendered
        assert "agv_v_chunks" in rendered
        assert "1536" in rendered
        assert "768" in rendered

    def test_custom_column_name(self):
        mismatch = DimensionMismatch(
            backend="lancedb",
            table_name="document_chunks",
            configured=384,
            actual=768,
            column="vector",
        )
        assert mismatch.column == "vector"
        assert "vector" in str(mismatch)
        assert "lancedb" in str(mismatch)

    def test_remediation_is_appended_when_provided(self):
        mismatch = DimensionMismatch(
            backend="postgresql",
            table_name="agv_v_chunks",
            configured=1536,
            actual=768,
            remediation="Run: agv schema migrate --project foo --confirm-data-loss",
        )
        rendered = str(mismatch)
        assert "agv schema migrate" in rendered
        assert "--confirm-data-loss" in rendered

    def test_remediation_absent_by_default(self):
        mismatch = DimensionMismatch(
            backend="lancedb",
            table_name="document_chunks",
            configured=384,
            actual=768,
        )
        # No remediation means no dangling section in the rendered error.
        rendered = str(mismatch)
        assert mismatch.remediation is None
        assert "agv schema migrate" not in rendered


class TestBackwardCompatReExport:
    """Legacy code imports from ``schema_tracker``; that path must still work."""

    def test_schema_mismatch_error_reexported(self):
        from agent_vault.storage.providers.postgresql.schema_tracker import (
            SchemaMismatchError as LegacyError,
        )

        assert LegacyError is SchemaMismatchError

    def test_dimension_mismatch_reexported(self):
        from agent_vault.storage.providers.postgresql.schema_tracker import (
            DimensionMismatch as LegacyMismatch,
        )

        assert LegacyMismatch is DimensionMismatch
