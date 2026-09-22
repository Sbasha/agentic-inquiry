---
rfc: 0002
title: AWS support (Bedrock + RDS / Aurora pgvector)
status: draft
authors: [eugeneacn]
created: 2026-04-29
related: ["#159", "#168", "#172"]
---

# RFC 0002 — AWS support (Bedrock + RDS / Aurora pgvector)

## Summary

Make AWS a peer of GCP for Agent-Vault deployments. Split the existing
single `rds` backend into two distinct backends — `rds` (RDS for
PostgreSQL, client-side embeddings) and `aurora` (Aurora PostgreSQL,
server-side embeddings via `aws_ml`) — because the two have materially
different capabilities and the unified-`rds`-everything posture in
the codebase today is silently misleading. Add Bedrock Titan as a
declared embedder option. Document, test, and deploy these as first-class
backends, not as a degraded GCP fallback.

## Motivation

Three things are simultaneously true today:

1. **AWS scaffolding is more complete than the README admits.** The
   unified PostgreSQL provider already routes `type: rds` through
   `RDSAdapter` (`agent_vault/storage/providers/postgresql/adapter.py:127`).
   `BackendType` includes `"rds"` (`agent_vault/storage/config.py:33`).
   `BackendPoolManager._build_rds_dsn` handles IAM token auth via boto3
   (`agent_vault/storage/pool.py:217`). `AWSSetup` (`cli/setup/aws_setup.py`)
   walks an interactive wizard. `cli/deploy/aws.py` + `scripts/deploy/aws-deploy.sh`
   bring up RDS + ECR + App Runner. There is even a unit test file:
   `tests/storage/providers/test_rds_vector_provider.py`.
2. **The scaffolding conflates RDS and Aurora.** `RDSAdapter` declares
   `aws_ml` as a required extension and emits SQL that calls
   `aws_bedrock.invoke_model` from inside Postgres
   (`adapter.py:139`, `adapter.py:162`). `aws_ml` is **Aurora-only** —
   it is not in the supported-extensions list for RDS for PostgreSQL.
   So the `embedding_strategy: server_side` path that the audit's
   AGENTS.md flags as the "correct" RDS configuration
   (`storage/providers/postgresql/AGENTS.md:84`) cannot run on RDS at all.
   It only runs on Aurora. The naming hides that.
3. **Audit cluster #159** rewrote its scope on 2026-04-28 from "delete
   AWS code" to "make AWS first-class because it's load-bearing for
   multi-client deployments." That issue's task list is essentially the
   ship gate for this RFC, plus the rds/aurora split that #159 didn't
   know about.

What gets better if this lands: a customer asking "can we run
Agent-Vault on AWS?" gets the same on-paper answer as the GCP customer.
Server-side embedding throughput parity — Aurora + Bedrock matches
AlloyDB + Vertex AI as a sustained-throughput option, and we stop
shipping a backend whose default config is impossible.

What stays bad if this doesn't land: the audit's "load-bearing but
under-tested and under-documented" diagnosis stays true; sales calls
keep relying on tribal knowledge ("yes, AWS works — ignore the README");
and the `rds` adapter quietly tells operators to enable an extension
they cannot actually install.

## Design

### Backends added

Two backend types, declared in `agent_vault/storage/capabilities.py`,
parallel to the existing `cloudsql` and `alloydb`:

| backend | wraps | embedding strategy | mirrors |
|---|---|---|---|
| `rds` | RDS for PostgreSQL (managed Postgres) | `LOCAL` | `cloudsql` |
| `aurora` | Aurora PostgreSQL with `aws_ml` | `SERVER_SIDE` | `alloydb` |

This is a rename + split, not a fresh start. The current `rds` backend
becomes "the RDS-or-Aurora-with-client-side-embeddings backend." A new
`aurora` backend is broken out for the server-side path. The split is
deliberate so that the embedding strategy is named in the type, not
buried in a config flag — consistent with how `cloudsql` and `alloydb`
already differ.

`RDS_CAPABILITIES` is updated to:

```python
RDS_CAPABILITIES = ProviderCapabilities(
    embedding_strategy=EmbeddingStrategy.LOCAL,
    embedding_dimensions=384,
    embedding_model=None,
    requires_proxy=False,
    is_postgresql_compatible=True,
    backend_type="rds",
)

AURORA_CAPABILITIES = ProviderCapabilities(
    embedding_strategy=EmbeddingStrategy.SERVER_SIDE,
    embedding_dimensions=1024,
    embedding_model="amazon.titan-embed-text-v2:0",
    requires_proxy=False,
    is_postgresql_compatible=True,
    backend_type="aurora",
)
```

`get_capabilities_for_backend` adds an `"aurora"` registry entry. The
existing `RDS_CAPABILITIES` LOCAL strategy is already correct
(`capabilities.py:135`), so no behavioural change there — just the
declaration that the *server-side* path is `aurora`, not `rds`.

### Embedding strategy per backend

| deployment shape | backend | how chunks get embedded |
|---|---|---|
| RDS for PostgreSQL + client-side embedding | `rds` | `SentenceTransformerEmbedder` on the indexer, write 384/768-dim vector to `chunk_embeddings.embedding` |
| RDS for PostgreSQL + Bedrock client-side | `rds` + `BedrockEmbedder` (new) | `boto3.client("bedrock-runtime").invoke_model("amazon.titan-embed-text-v2:0", ...)` from the indexer, write 1024-dim vector |
| Aurora PostgreSQL + server-side Bedrock | `aurora` | Insert `embedding IS NULL`; pipeline calls `generate_embeddings()`; the helper SQL function (`agv_embed`, already drafted in `RDSAdapter.create_helper_function`) wraps `aws_bedrock.invoke_model_get_embeddings` |

The Aurora server-side path uses `aws_bedrock.invoke_model_get_embeddings`,
not the generic `invoke_model` the current adapter draft uses
(`adapter.py:162`). The `_get_embeddings` variant returns a typed
`float8[]` rather than parsing JSON in PL/SQL, which matches what the
unified vector column expects and is what AWS recommends for embeddings
specifically.

The Aurora bulk-embedding analogue of AlloyDB's `ai.initialize_embeddings`
does not exist as a single procedure call. The closest is row-at-a-time
`SELECT aws_bedrock.invoke_model_get_embeddings(...)` over a `WHERE
embedding IS NULL` cursor, which is what `_fallback_embed_rows` already
implements for the current `rds`/server_side mode
(`vector.py:1995`). Throughput is therefore bounded by Bedrock RPM
quotas (Titan v2 uses RPM, not TPM); the throughput-comparison table in
`storage/providers/postgresql/AGENTS.md:95` gives the right
order-of-magnitude — Bedrock single-row fallback at ~25 emb/sec
(applies to RDS/Aurora today, applies to Aurora under this RFC) versus
AlloyDB's `ai.initialize_embeddings` at ~400 emb/sec. **Bulk
indexing on Aurora is meaningfully slower than on AlloyDB** because
AlloyDB has the Vertex AI batch path and Bedrock does not. Call it
clearly in the docs; don't promise parity we can't keep.

### Backend types in BackendType literal

`agent_vault/storage/config.py` BackendType literal adds `"aurora"`:

```python
BackendType = Literal[
    "lancedb", "postgresql", "sqlite", "spanner",
    "cloudsql", "alloydb",
    "rds", "aurora",   # ← new
    "azure", "memory",
]
```

`BackendConfig.validate_rds_config` is split into
`validate_rds_config` (LOCAL only) and a new `validate_aurora_config`
(SERVER_SIDE only). The latter inherits everything `validate_rds_config`
already does — required region/instance/host/database/user, IAM-or-password
auth, region-format regex — and additionally:

- Default `embedding_model` to `amazon.titan-embed-text-v2:0` and
  `embedding_dim` to 1024 (consistent with the current incorrectly-named
  RDS server-side path).
- Reject `embedding_strategy: local` outright on Aurora — if you want
  client-side embedding, you don't need Aurora; use `rds`.

### Connection layer

A new `AuroraConnectionManager` lives at
`agent_vault/storage/providers/aurora/connection.py`, alongside a
slimmed-down `RDSConnectionManager` at
`agent_vault/storage/providers/rds/connection.py`. Both extract
the AWS-specific bits (IAM token generation, SSL configuration, the
`aws_ml` extension bootstrap on Aurora) from `BackendPoolManager._build_rds_dsn`.
The connection managers parallel `CloudSQLConnectionManager` and
`AlloyDBConnectionManager` in shape; same `from_config` factory, same
`is_initialized` / `close` lifecycle.

The unified `PostgresConnectionManager` stays the workhorse for actual
asyncpg pool management, exactly as it does for AlloyDB and CloudSQL
today — Aurora and RDS subclass nothing, they just produce a configured
DSN and hand off. `BackendPoolManager` already routes `rds` through
`_create_postgres_pool` (`pool.py:169`); the same routing applies to
`aurora`.

The IAM-token path needs one fix on top of the current code: the boto3
RDS client generates a token with a 15-minute lifetime (per AWS IAM
authentication docs), and the current `_build_rds_dsn` generates the
token once at pool-creation time. The right primitive is asyncpg's
**`connect` callback** on `create_pool`, which fires per new connection
*before* asyncpg sends the password — that's the only place a fresh
token can actually be substituted, since the password is consumed during
connection establishment. asyncpg's `init` hook runs *after* auth has
already succeeded, so it's too late for this purpose.

The pattern mirrors `CloudSQLConnectionManager` in spirit but not in
mechanism: CloudSQL uses the Cloud SQL Connector library's
`connect` callback for IAM token injection plus
`max_inactive_connection_lifetime` for connection recycling
(see `storage/providers/cloudsql/connection.py`). For RDS/Aurora, we
hand-roll the equivalent: `boto3.client("rds").generate_db_auth_token()`
inside a `connect=` callback passed to `asyncpg.create_pool`, plus a
`max_inactive_connection_lifetime` shorter than the 15-minute token
TTL (e.g. 10 min) so connections recycle before the token they were
born with expires. AWS recommends fewer than 200 new IAM-auth
connections per second per instance; with `pool_size: 5–10` and a
10-minute lifetime, that's nowhere near the limit.

The existing `BackendPoolManager` (`storage/pool.py`) does not need a
new pool manager — it works for RDS today and will work for Aurora
unchanged once the BackendType literal accepts `"aurora"` and the
routing in `_create_pool` adds an `aurora` arm that delegates to the
same `_create_postgres_pool` (Aurora is wire-compatible Postgres).
This is consistent with #131 (share pool across same-backend roles).

### Adapter split

`agent_vault/storage/providers/postgresql/adapter.py` today has one
`RDSAdapter` that does Bedrock-via-`aws_ml`. Split into two:

- `RDSAdapter` (renamed in spirit, kept under the same class name to
  avoid breaking imports — `pgvector` only, no `aws_ml`,
  `get_embedding_sql` raises `NotImplementedError` like
  `DefaultPostgresAdapter`).
- `AuroraAdapter` (new) — `required_extensions = ["vector", "aws_ml"]`,
  `get_embedding_sql` returns `agv_embed(...)::vector` over
  `aws_bedrock.invoke_model_get_embeddings`, and `create_helper_function`
  installs the SQL helper.

`PostgresVectorProvider.from_config` and `PostgresGraphProvider.from_config`
add the `aurora` branch (~10 lines each).

The current adapter's `aws_bedrock.invoke_model` call gets replaced with
`aws_bedrock.invoke_model_get_embeddings` (the embedding-specific variant).
That is a one-line SQL change inside `AuroraAdapter.create_helper_function`.

### Embedder for the RDS-with-Bedrock path

A new `BedrockEmbedder` in `agent_vault/embeddings/bedrock.py`,
parallel to `SentenceTransformerEmbedder` and `FastEmbedEmbedder`.
Wraps `boto3.client("bedrock-runtime").invoke_model` against
`amazon.titan-embed-text-v2:0`. Honours the existing `Embedder`
protocol (`embeddings/base.py`).

Wired into the existing config surface (no new keys invented):

- `agent_vault/config.py` — extend `EmbeddingsConfig.default_provider`
  literal/validator to accept `"bedrock"` alongside the current
  `"sentence_transformer" | "fastembed" | "local" | "none"`.
  Add a sibling `BedrockConfig` dataclass (model_id, region,
  output_dim ∈ {256, 512, 1024}) on `EmbeddingsConfig`,
  paralleling `FastEmbedConfig` / `LocalModelConfig`.
- `agent_vault/embeddings/factory.py` —
  `configure_embedder_for_backend()` already dispatches on
  `config.embeddings.default_provider` for the `LOCAL` path and
  short-circuits to `NoOpEmbedder` for `SERVER_SIDE`. Add a
  `provider == "bedrock"` arm in the local branch that constructs
  `BedrockEmbedder` from `config.embeddings.bedrock`. No call-site
  changes elsewhere; CLI/index/search/serve all flow through the
  factory and pick up the new provider transparently.
- `agent_vault/storage/capabilities.py` — `RDS_CAPABILITIES`
  declares `EmbeddingStrategy.LOCAL` (this RFC), so the factory's
  existing capability-driven branch chooses the configured
  `default_provider`. Aurora declares `SERVER_SIDE` and bypasses
  the embedder entirely (in-DB Bedrock).

Titan v2 supports configurable output dimensions of 256, 512, or 1024.
The default is 1024 (matching what `validate_rds_config` already sets).
Lower dimensions trade recall for storage and faster pgvector index
builds. The recommendation: stick with 1024 unless storage cost forces
otherwise. **Cross-cloud recall comparability with AlloyDB
`text-embedding-005` (768-dim) is not preserved** — different model,
different dimension. The audit's golden suite (issue #156) needs a
separate baseline per embedder. This is the same situation we already
have between LanceDB (384-dim MiniLM) and AlloyDB (768-dim Vertex), so
not a new problem, just a new entry in the matrix.

### Setup / deploy CLI gaps

The current scaffolding (`aws_setup.py` + `aws-deploy.sh`) has these
gaps:

- **No Aurora flow.** Wizard talks to RDS (`describe-db-instances`) but
  not Aurora (`describe-db-clusters`). `RDSInstance` dataclass conflates
  the two via `engine == "aurora-postgresql"`
  (`aws_utils.py:203`); split into `RDSInstance` and `AuroraCluster`.
- **No embedding-strategy prompt.** Wizard hard-codes
  `embedding_strategy` defaulting to local. Aurora path needs to default
  to `server_side` and validate the `aws_ml` extension.
- **No Bedrock readiness check.** Server-side path needs an IAM
  pre-flight: the RDS / Aurora cluster's IAM role needs
  `bedrock:InvokeModel` permission. Add a `_check_bedrock_iam` step.
- **`scripts/deploy/aws-deploy.sh` creates RDS, never Aurora.** Either
  parameterize over engine, or write `scripts/deploy/aurora-deploy.sh`.
  Recommend the latter for clarity, mirroring `cloudsql-deploy.sh` /
  `alloydb-deploy.sh` if/when those exist.
- **Dependency declaration.** `pyproject.toml` doesn't declare `boto3`
  even though `pool.py:240` imports it. Move `boto3` from "soft"
  (raises ImportError at runtime) to a documented optional extra
  (`[project.optional-dependencies] aws = ["boto3>=1.34"]`), parallel to
  whatever GCP currently does.

### What gets reused (mostly) unchanged

The unified PostgreSQL provider is the workhorse — most files go
through untouched, with surgical adapter/dispatch updates called
out earlier in the RFC:

- `agent_vault/storage/providers/postgresql/` — vector, graph,
  events, file_tracker, transaction, schemas, index_config,
  migration, schema_tracker, consistency, maintenance,
  backup_cleanup all unchanged. The exceptions are explicit and
  small:
    - `adapter.py` — split `RDSAdapter` into RDS-only (no
      `aws_ml`, pgvector only) and a new `AuroraAdapter` for the
      `aws_ml` path (per the **Adapter split** section above).
    - `vector.py` / `graph.py` — `PostgresVectorProvider.from_config`
      and `PostgresGraphProvider.from_config` add an `aurora`
      dispatch arm alongside the existing `cloudsql`/`alloydb`/`rds`
      branches; routing is mechanical.
    - `pool.py` — one `elif config.type == "aurora"` arm that
      delegates to the existing `_create_postgres_pool`.
- `agent_vault/search/` — hybrid search, RRF reranker,
  normalization, deduplication, IDF-weighted boost. Truly
  unchanged; wire-compatible with any pgvector + tsvector backend.
- `agent_vault/indexing/pipeline.py` — orchestration. Already
  polls `generate_embeddings()` when `caps.needs_embedding_polling`
  is true; the Aurora capability declares `SERVER_SIDE` so the
  same code path runs.
- `agent_vault/onboard/providers/postgresql/` — onboarding
  metadata. Aurora and RDS are wire-compatible Postgres; the
  `azure` and `rds` registry entries already prove the pattern.

### What does *not* change

The MCP server / Claude API path. Agent-Vault's MCP server does not
itself call Anthropic models — it ships a Claude Code plugin and an
MCP tool surface. The actual LLM calls happen in the *client* (Claude
Code, the Anthropic SDK, or whatever else mounts the MCP server). So
"does agent-vault need a Bedrock LLM client?" is a no in the runtime;
it's only relevant for downstream customers who want their Claude Code
or app-side calls to go through Bedrock. That's outside this RFC's
scope, but for completeness:

- Bedrock supports prompt caching for Claude 4.x and 3.5+ Sonnet using
  `cache_control: {type: "ephemeral", ttl: "5m" | "1h"}` on
  `system` / `messages` / `tools`. Same shape as native Anthropic API
  with one Bedrock-specific simplification (automatic prefix matching
  across ~20 content blocks).
- Customers running Claude Code through Bedrock get prompt caching
  natively; agent-vault doesn't need to coordinate.

### Documentation deliverables

- `docs/backends/rds.md` (new, mirror of `docs/backends/cloudsql.md`)
- `docs/backends/aurora.md` (new, mirror of an implicit
  `docs/backends/alloydb.md` — the AlloyDB doc itself doesn't exist
  yet; opening a parallel issue to add it).
- `README.md` storage table updated with `rds` + `aurora` rows (the
  audit cluster #159 task 3.1 ship gate).

## Alternatives considered

### A. Keep `rds` as the only AWS backend, toggle by `embedding_strategy`

This is the status quo. Rejected because:

- The status quo claim "RDS supports server-side Bedrock embeddings" is
  factually wrong — `aws_ml` is Aurora-only. Operators following the
  AGENTS.md `Genuinely wrong if left alone` advice
  (`storage/providers/postgresql/AGENTS.md:84`, "flip RDS to
  server_side") would hit a CREATE EXTENSION failure on RDS.
- The naming hides a real architectural difference. AlloyDB and Cloud
  SQL are split for the same reason — even though they're both GCP
  managed Postgres — and that split has paid off for clarity.
- The split costs ~50 LOC (one capability profile, one config validator,
  one connection manager file, one adapter). Cheap.

### B. Bedrock-only with no in-DB embedding (client-side via boto3)

Drop the Aurora path entirely. Always embed client-side, even when the
user is on Aurora. Rejected because:

- The whole point of Aurora over RDS for this workload is server-side
  embedding throughput parity with AlloyDB. If we don't use `aws_ml`,
  we're just paying Aurora's premium for nothing.
- We *do* offer this path — it's the `rds` backend with a
  `BedrockEmbedder`. So customers who want it can have it. We don't
  need to take Aurora away to give them the option.
- Multi-client constraint (memory: aggressive deletion approved, with
  limits — multi-cloud is load-bearing): operators on AWS who *want*
  AlloyDB-shaped throughput on AWS need a path. Aurora `aws_ml` is
  the only one available today.

### C. OpenSearch Serverless instead of pgvector

Use OpenSearch Serverless for vector search and full-text search,
ditching pgvector / Postgres on the AWS path. Rejected because:

- The unified PostgreSQL provider is the workhorse. Five backend types
  (`postgresql`, `cloudsql`, `alloydb`, `rds`, `azure`) already share
  it. Adding a sixth that goes through OpenSearch fragments the search
  pipeline — `search/hybrid_search.py`, `search/rerankers/rrf.py`, the
  pgvector-tuned IDF weighting, and the `tsvector` FTS path all assume
  Postgres semantics. Reimplementing them on OpenSearch is a quarter
  of work with no clear win.
- OpenSearch Serverless does have native vector + BM25 hybrid search.
  But agent-vault's hybrid search has been *tuned* for the pgvector
  + tsvector combination (score-aware RRF with k=30, `MIN_VECTOR_SCORE
  = 0.15`, etc — see `AGENTS.md` Search Pipeline section). Throwing
  that away to chase OpenSearch's defaults is a regression on day one.
- Cost: OpenSearch Serverless prices in OCUs, and small workloads end
  up paying for 2 OCU minimum (~$700/month) vs an `db.t3.medium`
  Aurora at ~$70/month. Wrong shape for the typical agent-vault
  install.
- Future: OpenSearch could become a fifth role (`search` alongside
  `vector`/`graph`/`events`/`file_tracker`) for customers who already
  run it. Out of scope here.

### D. DocumentDB instead of RDS Postgres

Use AWS DocumentDB (Mongo-compatible) for both code chunks and graph
entities. Rejected:

- DocumentDB has no pgvector and no native vector index. Its vector
  support is via Atlas-style $vectorSearch which is a different query
  shape entirely.
- Mongo-compatibility is irrelevant — agent-vault's data model is
  relational + graph, not document.
- Stated for completeness; this was never a real candidate.

### E. Aurora Serverless v2 with auto-scale

Use Aurora Serverless v2 instead of provisioned Aurora. Not really an
*alternative* to this RFC — it's a config knob within the `aurora`
backend. Note it as a Risks-section item: Serverless v2's cold-start
behaviour interacts badly with bulk indexing because of the ACU
ramp-up curve. Recommend provisioned for the indexing instance,
Serverless v2 for read-heavy search instances. Not enforced in code.

## Risks

| risk | severity | mitigation |
|---|---|---|
| `aws_ml` extension version drift across Aurora minor versions (currently 2.0 on Aurora 15.13+ and all of 16) | medium | Setup wizard checks `SHOW rds.extensions` and refuses to write the config if `aws_ml >= 2.0` is unavailable. |
| Bedrock IAM gap silently breaks indexing | medium | `_check_bedrock_iam` pre-flight in setup. Pipeline `generate_embeddings()` surface raises a typed error that points to the IAM doc. |
| Bedrock quota throttling (Titan v2 RPM limits, default 2000 RPM in most regions) | medium | Pipeline already retries; document quota request URL. Aurora vs AlloyDB throughput gap is real (~25 emb/sec sustained vs AlloyDB's ~400) — call it out, don't hide it. |
| IAM-token expiry mid-pool (15 min lifetime) | low | Per-connection regeneration via asyncpg `init` hook, mirroring `CloudSQLConnectionManager`. |
| Aurora Serverless v2 cold-start during bulk indexing | low | Documented in `docs/backends/aurora.md`; not enforced in code. |
| Cross-cloud recall comparability — Titan v2 (1024-dim) vs Vertex (768-dim) vs MiniLM (384-dim) | medium | Golden suite (issue #156) gets one baseline per embedder. Document that recall@10 numbers are not comparable across embedders. |
| `RDSAdapter` → `AuroraAdapter` rename breaks existing configs in customer deployments | low (no GA users on this code path yet) | Keep `RDSAdapter` exported with a deprecation alias for one minor version; emit a warning when `type: rds` is seen with `embedding_strategy: server_side`. |
| Vendor lock-in: `aws_ml` is AWS-specific just as `embedding()` is AlloyDB-specific | accepted | This is the same trade we already made on the GCP side. Embedding strategy is a per-backend concern; backends are interchangeable. |
| Ops cost: Aurora minimum is ~$70/month vs RDS-t3.micro at ~$15/month | low | Default the wizard to `rds` (LOCAL embedding), require an opt-in `--server-side` flag for Aurora. |

## Ship gate

A reviewer can call this RFC "implemented" when:

- `agent_vault/storage/capabilities.py` exposes both `RDS_CAPABILITIES`
  (LOCAL) and `AURORA_CAPABILITIES` (SERVER_SIDE);
  `get_capabilities_for_backend("aurora")` returns the latter.
- `agent_vault/storage/config.py` `BackendType` literal includes
  `"aurora"`; `validate_aurora_config` rejects `embedding_strategy:
  local` and defaults the Bedrock model + dim correctly.
- `agent_vault/storage/providers/postgresql/adapter.py` exposes
  `AuroraAdapter` distinct from `RDSAdapter`; `RDSAdapter` no longer
  declares `aws_ml` as required and no longer emits Bedrock SQL.
- `agent_vault/storage/providers/aurora/connection.py` and
  `agent_vault/storage/providers/rds/connection.py` exist, paralleling
  `cloudsql/connection.py` and `alloydb/connection.py`.
- `agent_vault/embeddings/bedrock.py` exists; selectable via
  `embedder.provider: bedrock`.
- `cli/setup/aws_setup.py` walks RDS *or* Aurora; `aws-deploy.sh` and a
  new `aurora-deploy.sh` cover both targets.
- Adapter unit tests for `RDSAdapter` and `AuroraAdapter` assert
  `backend_type`, `required_extensions`, and `get_embedding_sql` shape
  (the test pattern audit cluster #159 task 3.2 already specified). No
  live AWS credentials required.
- `tests/golden/baseline.json` (issue #156) gains an
  `aurora-bedrock-titan-v2` recall@10 row, distinct from the AlloyDB
  baseline.
- `README.md` storage-backends table includes `rds` and `aurora` rows
  with their embedding-strategy + proxy + dim defaults.
- `docs/backends/rds.md` and `docs/backends/aurora.md` exist; both
  follow the shape of `docs/backends/cloudsql.md`.
- `pyproject.toml` declares `boto3` as an optional `aws` extra.
- `grep -rn "aws_ml" agent_vault/storage/providers/postgresql/adapter.py`
  shows `aws_ml` only inside `AuroraAdapter`, never `RDSAdapter`.

## What we are *not* doing

- Adding a Bedrock LLM client to agent-vault. The MCP server doesn't
  call Anthropic models directly; the client (Claude Code, customer
  app) does. Bedrock-based clients work without changes here.
- OpenSearch backend. See alternative C.
- Switching the default LanceDB-development experience to S3-backed
  LanceDB on the AWS path. Connector-cluster work (#160).
- Deleting the existing `rds` test file or renaming the boto3 import
  surface. Backwards compatibility for one minor version.

## References

### AWS documentation (cited inline)

- Aurora ML extension (`aws_ml`):
  <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/postgresql-ml.html>
- Aurora PostgreSQL extension version matrix (confirms `aws_ml`
  Aurora-only, pgvector 0.8.1 on 15.17 / 16.13):
  <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraPostgreSQLReleaseNotes/AuroraPostgreSQL.Extensions.html>
- RDS for PostgreSQL extension matrix (no `aws_ml`):
  <https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html>
- Titan Text Embeddings V2 (1024 / 512 / 256 dims, RPM-quota-based):
  <https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html>
- Bedrock prompt caching for Claude:
  <https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html>
- IAM database authentication (15-min token, ~200 conns/sec ceiling):
  <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.html>
- RDS Proxy considerations:
  <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html>
- Bedrock model availability (Claude on Bedrock):
  <https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards-anthropic.html>

### Repo references

- `agent_vault/storage/capabilities.py` — `EmbeddingStrategy`,
  `RDS_CAPABILITIES`.
- `agent_vault/storage/providers/postgresql/adapter.py` — current
  `RDSAdapter`.
- `agent_vault/storage/providers/postgresql/AGENTS.md` — per-variant
  matrix that this RFC cleans up.
- `agent_vault/storage/pool.py:217` — current `_build_rds_dsn`.
- `agent_vault/cli/setup/aws_setup.py`, `aws_utils.py`,
  `cli/deploy/aws.py`, `scripts/deploy/aws-deploy.sh` — current
  scaffolding.
- Issue #159 (audit cluster — make AWS/Azure first-class).
- Issue #168 (audit tracking).
