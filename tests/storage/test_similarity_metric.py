"""Tests for the similarity_metric config surface and translation helpers."""

from __future__ import annotations

import pytest

from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.postgresql.index_config import (
    HNSWParams,
    IndexConfig,
    IndexType,
    IVFFlatParams,
)
from agent_vault.storage.providers.postgresql.schemas import (
    CHUNKS_TABLE,
    ENTITIES_TABLE,
    SchemaGenerator,
)
from agent_vault.storage.similarity import (
    DEFAULT_SIMILARITY_METRIC,
    distance_to_similarity,
    lancedb_metric,
    normalize_metric,
    opensearch_metric,
    pgvector_distance_operator,
    pgvector_operator_class,
)


pytestmark = pytest.mark.unit


class TestSimilarityTranslations:
    """Canonical names translate to each backend's spelling."""

    @pytest.mark.parametrize(
        "metric,expected",
        [("cosine", "cosine"), ("l2", "l2"), ("dot", "dot")],
    )
    def test_lancedb_metric(self, metric: str, expected: str) -> None:
        assert lancedb_metric(metric) == expected

    @pytest.mark.parametrize(
        "metric,expected",
        [
            ("cosine", "vector_cosine_ops"),
            ("l2", "vector_l2_ops"),
            ("dot", "vector_ip_ops"),
        ],
    )
    def test_pgvector_operator_class(self, metric: str, expected: str) -> None:
        assert pgvector_operator_class(metric) == expected

    @pytest.mark.parametrize(
        "metric,expected",
        [("cosine", "<=>"), ("l2", "<->"), ("dot", "<#>")],
    )
    def test_pgvector_distance_operator(self, metric: str, expected: str) -> None:
        assert pgvector_distance_operator(metric) == expected

    @pytest.mark.parametrize(
        "metric,expected",
        [("cosine", "cosinesimil"), ("l2", "l2"), ("dot", "innerproduct")],
    )
    def test_opensearch_metric(self, metric: str, expected: str) -> None:
        assert opensearch_metric(metric) == expected

    def test_normalize_metric_rejects_unknown(self) -> None:
        with pytest.raises(ValueError, match="unsupported similarity_metric"):
            normalize_metric("hamming")


class TestBackendConfigSimilarityMetric:
    """BackendConfig validates similarity_metric per backend."""

    def test_default_is_cosine(self) -> None:
        cfg = BackendConfig(type="lancedb", database_path="./data")
        assert cfg.similarity_metric == DEFAULT_SIMILARITY_METRIC == "cosine"

    def test_lancedb_accepts_non_cosine(self) -> None:
        cfg = BackendConfig(
            type="lancedb",
            database_path="./data",
            similarity_metric="l2",
        )
        assert cfg.similarity_metric == "l2"

    @pytest.mark.parametrize(
        "backend_type,extra",
        [
            ("postgresql", {"connection_string": "postgresql://u:p@h/d"}),
            (
                "cloudsql",
                {
                    "project": "proj-123456",
                    "region": "us-central1",
                    "instance": "instance-a",
                    "database": "db",
                    "user": "u",
                },
            ),
            (
                "rds",
                {
                    "region": "us-east-1",
                    "instance": "instance-a",
                    "host": "h.rds.amazonaws.com",
                    "database": "db",
                    "user": "u",
                    "password": "pw",
                },
            ),
        ],
    )
    @pytest.mark.parametrize("metric", ["cosine", "l2", "dot"])
    def test_pgvector_backends_accept_all_canonical_metrics(
        self, backend_type: str, extra: dict, metric: str
    ) -> None:
        """All canonical metrics are honoured end-to-end on pgvector backends."""
        cfg = BackendConfig(type=backend_type, similarity_metric=metric, **extra)
        assert cfg.similarity_metric == metric

    def test_unknown_metric_is_rejected(self) -> None:
        # pydantic's Literal type enforcement catches this before the
        # model validator runs.
        with pytest.raises(ValueError, match="Input should be 'cosine', 'l2' or 'dot'"):
            BackendConfig(
                type="lancedb",
                database_path="./data",
                similarity_metric="hamming",  # type: ignore[arg-type]
            )


class TestSchemaGeneratorSimilarityMetric:
    """SchemaGenerator threads similarity_metric through DDL."""

    def test_default_uses_cosine_op_class(self) -> None:
        gen = SchemaGenerator(prefix="t_", embedding_dim=128)
        ddl = "\n".join(gen.generate_indexes(CHUNKS_TABLE))
        assert "vector_cosine_ops" in ddl
        assert "vector_l2_ops" not in ddl

    @pytest.mark.parametrize(
        "metric,op_class",
        [
            ("cosine", "vector_cosine_ops"),
            ("l2", "vector_l2_ops"),
            ("dot", "vector_ip_ops"),
        ],
    )
    def test_static_index_template_uses_configured_op_class(
        self, metric: str, op_class: str
    ) -> None:
        gen = SchemaGenerator(prefix="t_", embedding_dim=128, similarity_metric=metric)

        chunks_ddl = "\n".join(gen.generate_indexes(CHUNKS_TABLE))
        entities_ddl = "\n".join(gen.generate_indexes(ENTITIES_TABLE))

        assert op_class in chunks_ddl
        assert op_class in entities_ddl
        # Make sure no other op-class leaked in.
        for other in {"vector_cosine_ops", "vector_l2_ops", "vector_ip_ops"} - {
            op_class
        }:
            assert other not in chunks_ddl
            assert other not in entities_ddl

    @pytest.mark.parametrize(
        "metric,op_class",
        [
            ("cosine", "vector_cosine_ops"),
            ("l2", "vector_l2_ops"),
            ("dot", "vector_ip_ops"),
        ],
    )
    def test_generate_vector_index_uses_configured_op_class(
        self, metric: str, op_class: str
    ) -> None:
        gen = SchemaGenerator(prefix="t_", embedding_dim=128, similarity_metric=metric)

        hnsw_sql = gen.generate_vector_index(
            "t_v_chunks",
            "embedding",
            IndexConfig(index_type=IndexType.HNSW, hnsw_params=HNSWParams()),
        )
        ivfflat_sql = gen.generate_vector_index(
            "t_v_chunks",
            "embedding",
            IndexConfig(
                index_type=IndexType.IVFFLAT, ivfflat_params=IVFFlatParams(lists=50)
            ),
        )

        assert op_class in hnsw_sql
        assert op_class in ivfflat_sql

    def test_invalid_metric_fails_at_init_not_at_ddl_time(self) -> None:
        with pytest.raises(ValueError, match="unsupported similarity_metric"):
            SchemaGenerator(prefix="t_", embedding_dim=128, similarity_metric="hamming")


class TestDistanceToSimilarity:
    """pgvector distances normalize into [0, 1] scores per-metric."""

    @pytest.mark.parametrize(
        "distance,expected",
        [
            (0.0, 1.0),  # perfect match: cosine_sim = 1
            (0.5, 0.5),
            (1.0, 0.0),  # orthogonal for normalized vectors
            (2.0, 0.0),  # opposite direction — clamped to 0
            (-0.1, 1.0),  # negative distance clamped up (pgvector edge)
        ],
    )
    def test_cosine(self, distance: float, expected: float) -> None:
        assert distance_to_similarity(distance, "cosine") == pytest.approx(expected)

    @pytest.mark.parametrize(
        "distance,expected",
        [
            (0.0, 1.0),
            (1.0, 0.5),
            (3.0, 0.25),
        ],
    )
    def test_l2_monotone_in_unit_interval(
        self, distance: float, expected: float
    ) -> None:
        got = distance_to_similarity(distance, "l2")
        assert 0.0 < got <= 1.0
        assert got == pytest.approx(expected)

    @pytest.mark.parametrize(
        "distance,expected",
        [
            (-1.0, 1.0),  # pgvector <#> = -inner; inner=1 → distance=-1 → sim=1
            (0.0, 0.5),
            (1.0, 0.0),
            (-5.0, 1.0),  # unnormalized: clamped to 1
            (5.0, 0.0),  # unnormalized: clamped to 0
        ],
    )
    def test_dot(self, distance: float, expected: float) -> None:
        assert distance_to_similarity(distance, "dot") == pytest.approx(expected)

    def test_scores_are_always_in_unit_interval(self) -> None:
        """All three metrics produce scores in [0, 1] over their respective domains.

        pgvector guarantees: ``<=>`` (cosine) ∈ [0, 2], ``<->`` (l2) ∈ [0, ∞),
        ``<#>`` (-inner) ∈ (-∞, ∞). We only check within those domains.
        """
        domain = {
            "cosine": (0.0, 0.25, 0.5, 1.0, 1.5, 2.0),
            "l2": (0.0, 0.5, 1.0, 5.0, 100.0),
            "dot": (-10.0, -1.0, 0.0, 0.5, 1.0, 10.0),
        }
        for metric, distances in domain.items():
            for d in distances:
                s = distance_to_similarity(d, metric)
                assert 0.0 <= s <= 1.0, (metric, d, s)

    def test_rejects_unknown_metric(self) -> None:
        with pytest.raises(ValueError, match="unsupported similarity_metric"):
            distance_to_similarity(0.0, "hamming")


class TestMaintenanceServiceHonoursMetric:
    """PostgresMaintenanceService must emit the configured pgvector op-class.

    Regression for the silent-correctness hole where `SchemaGenerator()` was
    instantiated with no arguments in `rebuild_index`, so rebuilds against an
    l2/dot database always wrote `vector_cosine_ops` into the new index.
    """

    @pytest.mark.parametrize(
        "metric,expected_op_class,forbidden_op_classes",
        [
            ("cosine", "vector_cosine_ops", {"vector_l2_ops", "vector_ip_ops"}),
            ("l2", "vector_l2_ops", {"vector_cosine_ops", "vector_ip_ops"}),
            ("dot", "vector_ip_ops", {"vector_cosine_ops", "vector_l2_ops"}),
        ],
    )
    @pytest.mark.asyncio
    async def test_rebuild_index_uses_configured_op_class(
        self,
        metric: str,
        expected_op_class: str,
        forbidden_op_classes: set[str],
    ) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from agent_vault.storage.providers.postgresql.maintenance import (
            PostgresMaintenanceService,
        )

        connection_manager = MagicMock()
        connection_manager.similarity_metric = metric

        mock_connection = AsyncMock()
        # fetchval order: _is_in_transaction → COUNT(*) → pg_total_relation_size
        mock_connection.fetchval.side_effect = [False, 1234, 4096]
        # execute captures every SQL string run during rebuild.
        executed: list[str] = []

        async def _capture(sql: str, *args, **kwargs):
            executed.append(sql)
            return None

        mock_connection.execute.side_effect = _capture

        connection_manager.acquire_for_transaction = AsyncMock(
            return_value=mock_connection
        )
        connection_manager.release_transaction_connection = AsyncMock()

        service = PostgresMaintenanceService(connection_manager)

        result = await service.rebuild_index(
            table_name="test_chunks",
            column_name="embedding",
            index_config=IndexConfig(
                index_type=IndexType.HNSW,
                hnsw_params=HNSWParams(m=16, ef_construction=64),
            ),
        )

        # First execute call is the CREATE INDEX CONCURRENTLY statement.
        assert executed, "rebuild_index did not execute any SQL"
        create_sql = executed[0]
        assert "CREATE INDEX CONCURRENTLY" in create_sql
        assert expected_op_class in create_sql, (
            f"rebuild DDL for metric={metric} missing {expected_op_class}: {create_sql}"
        )
        for forbidden in forbidden_op_classes:
            assert forbidden not in create_sql, (
                f"rebuild DDL for metric={metric} unexpectedly contains "
                f"{forbidden}: {create_sql}"
            )
        assert result.rows_indexed == 1234
