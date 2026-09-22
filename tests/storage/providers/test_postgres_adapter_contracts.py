"""Contract tests for the PostgreSQL cloud adapters.

Each adapter family (Default / AlloyDB / RDS / Azure) has to satisfy
the ``PostgreSQLAdapter`` shape and produce SQL the corresponding
cloud actually accepts. The tests here are purely unit-level — no
boto3, no live cloud, no database — and assert three things per
adapter:

1. ``backend_type`` is the literal we register in ``BackendType``
   (``storage/config.py``) and route on in ``BackendPoolManager``.
2. ``required_extensions`` lists the actual PostgreSQL extensions the
   adapter needs at runtime, in the order ``ensure_extension`` will
   try them.
3. ``get_embedding_sql(content_sql, model)`` produces SQL that the
   target engine recognises as an embedding-generating expression
   for ``model``.

The motivation is cluster #159 ship-gate: "the next audit reads the
code as supported, because it is." Anchors on the adapter classes
themselves point readers here from a ``# Supported backend`` comment
grep.
"""

from __future__ import annotations

import pytest

from agent_vault.storage.capabilities import (
    EmbeddingStrategy,
    get_capabilities_for_backend,
)
from agent_vault.storage.providers.postgresql.adapter import (
    AlloyDBAdapter,
    AzurePostgresAdapter,
    DefaultPostgresAdapter,
    RDSAdapter,
)

pytestmark = pytest.mark.unit


# ---------- Default (self-hosted Postgres / CloudSQL via direct DSN) ----------


class TestDefaultPostgresAdapterContract:
    def test_backend_type_default(self):
        adapter = DefaultPostgresAdapter(is_cloudsql=False)
        assert adapter.backend_type == "postgresql"
        assert adapter.requires_proxy is False
        assert adapter.proxy_type is None

    def test_backend_type_cloudsql(self):
        adapter = DefaultPostgresAdapter(is_cloudsql=True)
        assert adapter.backend_type == "cloudsql"
        assert adapter.requires_proxy is True
        assert adapter.proxy_type == "cloudsql"

    def test_required_extensions(self):
        adapter = DefaultPostgresAdapter()
        # pgvector is the only hard requirement — ts_vector for FTS is
        # built-in, the graph schema runs on plain SQL. No server-side
        # embedding extension exists for plain Postgres / CloudSQL,
        # so the strategy argument is ignored.
        assert adapter.required_extensions("local") == ["vector"]
        assert adapter.required_extensions("server_side") == ["vector"]

    def test_get_embedding_sql_raises(self):
        adapter = DefaultPostgresAdapter()
        # Standard PostgreSQL has no server-side embedding function;
        # the contract is to raise ``NotImplementedError`` so callers
        # know they have to embed client-side.
        with pytest.raises(NotImplementedError, match="Server-side"):
            adapter.get_embedding_sql("c.content", "any-model")


# ---------- AlloyDB ----------


class TestAlloyDBAdapterContract:
    def test_backend_type(self):
        adapter = AlloyDBAdapter()
        assert adapter.backend_type == "alloydb"
        assert adapter.requires_proxy is True
        assert adapter.proxy_type == "alloydb"

    def test_required_extensions_server_side(self):
        adapter = AlloyDBAdapter()
        # ``google_ml_integration`` is the AlloyDB extension that
        # exposes the ``embedding(...)`` SQL function used for
        # server-side Vertex AI embeddings.
        assert adapter.required_extensions("server_side") == [
            "vector",
            "google_ml_integration",
        ]

    def test_required_extensions_local_skips_ml_extension(self):
        adapter = AlloyDBAdapter()
        # Rare on AlloyDB — the whole point is the server-side path —
        # but supported for parity with the other adapters. A LOCAL
        # AlloyDB deployment doesn't need ``google_ml_integration``.
        assert adapter.required_extensions("local") == ["vector"]

    def test_get_embedding_sql_uses_native_embedding_function(self):
        adapter = AlloyDBAdapter()
        sql = adapter.get_embedding_sql("c.content", "text-embedding-005")
        # AlloyDB's own ``embedding('<model>', <text>)`` returns the
        # vector directly; cast to ``vector`` for pgvector compatibility.
        assert sql == "embedding('text-embedding-005', c.content)::vector"

    def test_get_bulk_embedding_sql_uses_initialize_embeddings(self):
        adapter = AlloyDBAdapter()
        bulk = adapter.get_bulk_embedding_sql(
            table="agv_chunk_embeddings",
            model="text-embedding-005",
            content_col="content",
            embedding_col="embedding",
        )
        # ``ai.initialize_embeddings`` is the bulk-fast-path on AlloyDB
        # — ~400 chunks/sec versus ~25/sec for per-row ``embedding(...)``.
        assert "ai.initialize_embeddings" in bulk
        assert "model_id => 'text-embedding-005'" in bulk
        assert "table_name => 'agv_chunk_embeddings'" in bulk
        assert "content_column => 'content'" in bulk
        assert "embedding_column => 'embedding'" in bulk


# ---------- RDS / Aurora (currently one adapter) ----------


class TestRDSAdapterContract:
    """RDSAdapter today serves both RDS and Aurora; RFC 0002 splits
    them. Tests below pin the *current* contract so the split lands
    cleanly and any adapter rename keeps the SQL shape stable.
    """

    def test_backend_type(self):
        adapter = RDSAdapter()
        assert adapter.backend_type == "rds"
        # RDS doesn't need an in-process proxy; IAM auth uses tokens
        # generated client-side instead.
        assert adapter.requires_proxy is False
        assert adapter.proxy_type is None

    def test_required_extensions_server_side_requires_aws_ml(self):
        adapter = RDSAdapter()
        # ``aws_ml`` is the extension that exposes
        # ``aws_bedrock.invoke_model`` from inside SQL. RFC 0002 flags
        # that this is *Aurora-only* — RDS for PostgreSQL doesn't have
        # ``aws_ml`` in its supported-extensions list. So we only
        # require it on the server-side path (i.e. Aurora). Plain RDS
        # operators using LOCAL or RFC-0003 client-side Bedrock skip
        # the extension entirely.
        assert adapter.required_extensions("server_side") == ["vector", "aws_ml"]

    def test_required_extensions_local_skips_aws_ml(self):
        adapter = RDSAdapter()
        # The fix for the Shape A claim in docs/backends/rds.md —
        # plain RDS for PostgreSQL with ``embedding_strategy: local``
        # must not try to ``CREATE EXTENSION aws_ml`` (it would fail
        # with "extension is not available").
        assert adapter.required_extensions("local") == ["vector"]

    def test_get_embedding_sql_uses_agv_embed_helper(self):
        adapter = RDSAdapter()
        sql = adapter.get_embedding_sql("c.content", "amazon.titan-embed-text-v2:0")
        # ``agv_embed`` is the SQL helper the adapter installs in
        # ``create_helper_function`` — it wraps
        # ``aws_bedrock.invoke_model`` for the embedding-output path.
        assert sql == "agv_embed(c.content, 'amazon.titan-embed-text-v2:0')::vector"

    def test_get_embedding_sql_supports_parameter_placeholders(self):
        # Used by query-side flow where the content is a parameter
        # rather than a column reference.
        adapter = RDSAdapter()
        sql = adapter.get_embedding_sql("$1", "amazon.titan-embed-text-v2:0")
        assert sql == "agv_embed($1, 'amazon.titan-embed-text-v2:0')::vector"

    def test_helper_function_name_is_configurable(self):
        adapter = RDSAdapter(embed_function_name="custom_embed")
        sql = adapter.get_embedding_sql("c.content", "amazon.titan-embed-text-v2:0")
        assert sql.startswith("custom_embed(")

    def test_get_bulk_embedding_sql_unsupported(self):
        # RDS / Aurora has no equivalent of ``ai.initialize_embeddings`` —
        # bulk-embed throughput goes through per-row ``agv_embed`` calls
        # at ~25/sec (Bedrock RPM-bound). Adapter returns ``None`` so the
        # provider falls back to the per-row path.
        adapter = RDSAdapter()
        assert adapter.get_bulk_embedding_sql(
            table="agv_chunk_embeddings",
            model="amazon.titan-embed-text-v2:0",
            content_col="content",
            embedding_col="embedding",
        ) is None


# ---------- Azure Database for PostgreSQL ----------


class TestAzurePostgresAdapterContract:
    def test_backend_type(self):
        adapter = AzurePostgresAdapter()
        assert adapter.backend_type == "azure"
        assert adapter.requires_proxy is False
        assert adapter.proxy_type is None

    def test_required_extensions_server_side(self):
        adapter = AzurePostgresAdapter()
        # ``azure_ai`` exposes ``azure_ai.generate_embeddings`` for
        # server-side Azure OpenAI calls.
        assert adapter.required_extensions("server_side") == ["vector", "azure_ai"]

    def test_required_extensions_local_skips_azure_ai(self):
        adapter = AzurePostgresAdapter()
        # LOCAL Azure (rare — most teams want SERVER_SIDE) doesn't
        # need ``azure_ai``. Without this conditional, the wizard's
        # LOCAL path would fail at extension-allowlist time on a
        # server that hasn't enabled azure_ai.
        assert adapter.required_extensions("local") == ["vector"]

    def test_get_embedding_sql_uses_generate_embeddings(self):
        adapter = AzurePostgresAdapter()
        sql = adapter.get_embedding_sql("c.content", "text-embedding-3-small")
        # The deployment name is interpolated into the call, the
        # content is referenced as-is, and the ``real[]`` return is
        # cast to ``vector``.
        assert (
            sql
            == "azure_ai.generate_embeddings('text-embedding-3-small', c.content)::vector"
        )

    def test_get_embedding_sql_supports_parameter_placeholders(self):
        adapter = AzurePostgresAdapter()
        sql = adapter.get_embedding_sql("$1", "text-embedding-3-large")
        assert (
            sql
            == "azure_ai.generate_embeddings('text-embedding-3-large', $1)::vector"
        )

    def test_get_bulk_embedding_sql_unsupported(self):
        # Azure has no ``initialize_embeddings`` analogue — the
        # extension call is per-row. Polling proceeds through the
        # standard ``WHERE embedding IS NULL`` cursor.
        adapter = AzurePostgresAdapter()
        assert adapter.get_bulk_embedding_sql(
            table="agv_chunk_embeddings",
            model="text-embedding-3-small",
            content_col="content",
            embedding_col="embedding",
        ) is None


# ---------- Capability-registry coverage ----------


class TestCapabilityRegistry:
    """``get_capabilities_for_backend`` is the registry every consumer
    uses to decide LOCAL vs SERVER_SIDE routing. Pin every backend
    string the README + ``cli/setup/templates.py`` advertise so a
    silent fallthrough to LANCEDB defaults can't ship.
    """

    def test_postgresql_is_local(self):
        caps = get_capabilities_for_backend("postgresql")
        assert caps.embedding_strategy == EmbeddingStrategy.LOCAL
        assert caps.backend_type == "postgresql"

    def test_cloudsql_is_local(self):
        caps = get_capabilities_for_backend("cloudsql")
        assert caps.embedding_strategy == EmbeddingStrategy.LOCAL
        assert caps.backend_type == "cloudsql"
        assert caps.requires_proxy is True

    def test_alloydb_is_server_side(self):
        caps = get_capabilities_for_backend("alloydb")
        assert caps.embedding_strategy == EmbeddingStrategy.SERVER_SIDE
        assert caps.embedding_model == "text-embedding-005"
        assert caps.embedding_dimensions == 768

    def test_rds_is_local(self):
        caps = get_capabilities_for_backend("rds")
        assert caps.embedding_strategy == EmbeddingStrategy.LOCAL
        assert caps.backend_type == "rds"

    def test_azure_is_server_side(self):
        caps = get_capabilities_for_backend("azure")
        assert caps.embedding_strategy == EmbeddingStrategy.SERVER_SIDE
        assert caps.embedding_model == "text-embedding-3-small"
        assert caps.embedding_dimensions == 1536
        assert caps.backend_type == "azure"

    def test_unknown_falls_back_to_lancedb(self):
        # Defensive: unknown backend strings default to LanceDB
        # capabilities (LOCAL, 384 dim). Documented in
        # ``get_capabilities_for_backend``'s docstring.
        caps = get_capabilities_for_backend("does-not-exist")
        assert caps.embedding_strategy == EmbeddingStrategy.LOCAL
        assert caps.backend_type == "lancedb"
