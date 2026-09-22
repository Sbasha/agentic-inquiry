# Embeddings architecture

How Agentic Inquiry generates and uses vector embeddings during ingestion and
retrieval. Read this before changing the embedding layer or adding a new
embedding model.

This is a current-state description of the code as of 2026-05-02. For the
proposal to extend this surface to additional cloud embedding models
(Amazon Titan v2 first), see [RFC 0003](../rfc/0003-pluggable-embedding-providers.md).

---

## TL;DR

- One `Embedder` protocol (`agentic_inquiry/embeddings/base.py`): a class with
  `generate(texts) -> list[list[float]]`, `ndims() -> int`, and an optional
  `ensure_model_loaded()`.
- Two embedding *strategies*, declared per storage backend in
  `agentic_inquiry/storage/capabilities.py`:
  - **`LOCAL`** — the indexer / search client computes vectors in-process
    via an `Embedder` instance.
  - **`SERVER_SIDE`** — the database computes vectors in-engine. AlloyDB
    uses `embedding()` directly; the AWS path wraps `aws_bedrock.invoke_model`
    in a `ai_embed(...)` SQL helper installed by `RDSAdapter`; Azure
    uses `azure_ai.generate_embeddings` via `AzurePostgresAdapter`. The
    client uses `NoOpEmbedder` and the SQL adapter emits the
    backend-specific embedding fragment.
- The `EmbeddingRegistry` is the per-process singleton that owns the
  default embedder plus per-(table, column) overrides (e.g. `HashingEmbedder`
  for `graph_relationships`). Everything that needs a vector goes through
  the registry, not the Embedder classes directly.
- The `embeddings.factory.configure_embedder_for_backend(config)` is
  the *primary* embedder selector — used by the indexing pipeline,
  search service, MCP server, and CLI entrypoints. Storage-backend
  capabilities decide LOCAL vs SERVER_SIDE; `config.embeddings.default_provider`
  decides *which* local embedder. The factory accepts `"sentence_transformer"`
  (default), `"fastembed"`, and `"local"` (→ `LocalModelEmbedder`).
  A second selector, `EmbeddingService._create_embedder`
  (`embeddings/service.py`), is instantiated directly by the memory
  system, graph search, MCP suggestion gathering, and the CLI memory
  subcommands; it accepts `"sentence_transformer"`, `"hashing"`, and
  `"local_model"` (→ `LocalModelEmbedder`). The two dispatchers
  intentionally differ on the `LocalModelEmbedder` literal — see
  "Two `EmbeddingService`s" below.
- Same embedder is used for both ingestion and retrieval — there is no
  separate "query embedder" surface today.

---

## The `Embedder` protocol

`agentic_inquiry/embeddings/base.py:8`:

```python
class Embedder(ABC):
    @abstractmethod
    def generate(self, texts: List[str]) -> List[List[float]]: ...

    async def generate_async(self, texts: List[str]) -> List[List[float]]:
        # default: thread-pool offload to self.generate
        ...

    @abstractmethod
    def ndims(self) -> int: ...

    def ensure_model_loaded(self) -> None: ...  # optional warmup hook
```

Every concrete embedder implements this. The protocol is intentionally
narrow — there is no `embed_query` vs `embed_documents` split (the same
embedder serves both), no streaming variant, no per-call config.

### Concrete implementations

| Class | Module | Purpose |
|---|---|---|
| `SentenceTransformerEmbedder` | `embeddings/sentence_transformer.py` | Default. CPU/CUDA/MPS autodetect; pads/truncates to `ndims`; defaults to `all-MiniLM-L6-v2` (384 dim). |
| `FastEmbedEmbedder` | `embeddings/fastembed.py` | ONNX Runtime via the `fastembed` library; defaults to `BAAI/bge-small-en-v1.5`. |
| `LocalModelEmbedder` | `embeddings/local_model.py` | ONNX models loaded from disk with a `metadata.json` sidecar describing dim, pooling, normalization. Workspace-relative paths. |
| `HashingEmbedder` | `embeddings/hashing.py` | Deterministic char-n-gram hashing — used for `graph_relationships` where types are a finite string set. |
| `NoOpEmbedder` | `embeddings/noop.py` | Returns zero vectors. Slot-fills the protocol when the backend is `SERVER_SIDE`. |
| `CachingEmbedder` | `embeddings/caching.py` | Wrapper. SHA256 LRU over `list[str]` inputs; in-batch dedup; numpy float32 internal storage. |

The wrapper / decorator pattern (`CachingEmbedder` wrapping a base
embedder) is the only composition point that exists today. There is no
"remote API client" embedder yet — see RFC 0003.

---

## The registry: where embedders live at runtime

`agentic_inquiry/embeddings/registry.py`. One global instance:
`embedding_registry`. Owns:

- A *default* embedder (set once at startup via
  `configure_default_embedder(embedder, ndims=...)`).
- Per-`(table, column)` overrides (`register("graph_relationships",
  "vector", HashingEmbedder(...))`). Set up via
  `configure_hybrid_embeddings()` — see
  [docs/design/hybrid-embedding-strategy.md](../design/hybrid-embedding-strategy.md).
- Expected dimensions per slot. The schema layer reads these to size the
  pgvector / LanceDB vector columns.

Lookup: `registry.get_configuration("document_chunks", "vector")` returns
`(embedder, ndims)`. Falls back to the default if no override is set.

The registry does **not** select between providers — it stores instances
that someone else built. The factory does the selection.

---

## Selection: capability-driven, then config-driven

`agentic_inquiry/embeddings/factory.py:48`:

```python
configure_embedder_for_backend(config)
```

is invoked exactly once, from CLI / MCP / server entrypoints, before the
indexing pipeline or search service runs. Two-stage decision:

1. **Resolve backend type** from `config.storage.backend` (or
   `config.storage.backends[vector_backend]`). Look up
   `ProviderCapabilities` via `get_capabilities_for_backend(backend_type)`
   — registry in `agentic_inquiry/storage/capabilities.py:147`.

2. **Branch on `caps.embedding_strategy`:**

   - **`SERVER_SIDE`** (AlloyDB and Azure today). Configure
     `NoOpEmbedder(ndims=caps.embedding_dimensions)` as the default.
     Caching is skipped — the model runs in-DB, there's no local
     forward pass to memoize. AlloyDB → `text-embedding-005` (768d);
     Azure → `text-embedding-3-small` (1536d) by default, overridable
     via `BackendConfig.embedding_model` for `text-embedding-3-large`
     or any custom AOAI deployment. Aurora server-side via `aws_ml`
     is the third planned shape (RFC 0002) — its capability profile
     and `aurora` backend type land with that RFC's implementation;
     until then operators using Aurora set `type: rds` and rely on
     per-`BackendConfig.embedding_strategy` overrides.

   - **`LOCAL`** (LanceDB, Postgres, CloudSQL, RDS today, plus
     embedded-mode SQLite/memory). Read `config.embeddings.default_provider`
     to choose the concrete class:
     - `"sentence_transformer"` (default) → `SentenceTransformerEmbedder`
     - `"fastembed"` → `FastEmbedEmbedder`
     - `"local"` → `LocalModelEmbedder`
     - `"hashing"` (via the lower-level `EmbeddingService` path only —
       not in `configure_embedder_for_backend` directly)
     - `"none"` is a config-validation sentinel, not a factory branch;
       it suppresses the dim consistency check inside
       `Config.validate_embedding_consistency` (`config.py:1413`,
       sentinel branch at `:1426`) when the deployment delegates
       embedding to a SERVER_SIDE backend. Used by the AlloyDB setup
       template (`cli/setup/templates.py:146`).

     Then wrap in `CachingEmbedder` if `config.embeddings.cache.enabled`
     and `max_entries > 0`.

The registry's `_default_configured` flag short-circuits repeat calls so
tests / fixtures that pre-configure the registry win over the factory.

`agentic_inquiry/embeddings/service.py` (`EmbeddingService`) exposes a
slightly different path used by the `MemorySystem` and search-side query
embedding: it can also dispatch on `default_provider` directly (including
`"hashing"` and `"local_model"`), but defers to the registry's default
when one is already configured. The two selection paths converge on the
same `Embedder` instance once the factory has run.

---

## Two `EmbeddingService`s — same name, different layers

This trips people up. Both are real:

| Class | File | Role |
|---|---|---|
| `EmbeddingService` | `agentic_inquiry/embeddings/service.py` | High-level async facade: `embed_async(text)`, `embed_batch_async(texts)`, background warmup. Used by search, MCP, memory, server routes. |
| `EmbeddingService` | `agentic_inquiry/indexing/embedding_service.py` | Indexing-pipeline helper: `get_embedder_configuration(table, column)`, `generate_embeddings_batch(...)` with batch-then-per-item retry. |

The indexing one is a thin wrapper around the registry; the
embeddings/service one is the public-ish entrypoint everything else
imports. The naming collision is historic — neither has been renamed yet.

The two dispatchers also disagree on the provider literal for
`LocalModelEmbedder`: `factory.configure_embedder_for_backend` matches
`provider == "local"` (`factory.py:104`), but
`EmbeddingService._create_embedder` matches `provider == "local_model"`
(`service.py:75`). Setting one literal in `default_provider` works
through the indexing/search path but silently falls back to
`SentenceTransformerEmbedder` in the memory + MCP suggestion path
(or vice versa). RFC 0003's "both dispatchers must agree on the
provider literal" rule exists precisely because of this class of bug.

---

## Ingestion: how a chunk becomes a vector

The pipeline is in `agentic_inquiry/indexing/pipeline.py`. The relevant
sequence per parsed document
(`pipeline.py:2107-2330`, abridged):

1. **Decide embedding strategy.**
   ```python
   caps = get_capabilities_for_backend(self._backend_type)
   skip_local = caps.uses_server_side_embedding
   ```

2. **`SERVER_SIDE` path.** For each chunk, validate non-empty content
   and append a placeholder zero-vector of `caps.embedding_dimensions`.
   Insert chunks with `embedding IS NULL`. Once indexing finishes, the
   pipeline calls `provider.generate_embeddings()` which dispatches on
   the SQL adapter:

   - `AlloyDBAdapter` — `CALL ai.initialize_embeddings(...)` for fresh
     tables (~400 chunks/sec), per-row `embedding('text-embedding-005',
     content)` for incremental (~25/sec).
   - `RDSAdapter` (Aurora `aws_ml`, today incorrectly registered for
     plain RDS — see RFC 0002) — per-row `ai_embed(content, model_id)`
     wrapping `aws_bedrock.invoke_model`.
   - `AzurePostgresAdapter` — per-row `azure_ai.generate_embeddings(model,
     content)`.

   The pipeline polls until no rows have `embedding IS NULL` (or times
   out) before emitting `READY`.

3. **`LOCAL` path.** Two passes per file:
   - Pass 1: collect `(chunk, embedding_text)` pairs, drop empty /
     fallback-text chunks, emit `FILE_SKIPPED` events.
   - Pass 2: one batched `embedder.generate(texts)` for the whole file.
     Falls back to per-text retry if the batched call raises (tensor
     shape, device blip). The `executor` offload happens here, not
     inside `generate`.

4. **Graph relationships** go through the registry's per-table override
   (`HashingEmbedder` if `configure_hybrid_embeddings()` ran) — same
   `embedder.generate` call, just a different embedder instance.

5. **Insert.** `upsert_chunks(...)` writes the vector to
   `chunk_embeddings.embedding` (Postgres family) or the equivalent
   LanceDB column. `vector` columns are sized via
   `registry.get_expected_dimensions("document_chunks", "vector")` at
   schema creation time, so a dimension mismatch between embedder and
   stored data fails at insert, not at query.

---

## Retrieval: how a query becomes results

Query entrypoints are scattered (MCP tools, CLI, HTTP routes, the memory
system) but they all converge on either:

- **`embedding_service.embed_async(query)` → `vector` → `vector_search` /
  `hybrid_search`**, or
- **raw query string passed straight through to the provider** when the
  backend is `SERVER_SIDE`.

The provider-side switch lives in
`agentic_inquiry/storage/providers/postgresql/vector.py:872` and `:1404`
(chunk and entity vector search respectively). It accepts
`Union[List[float], str]` for `query_vector`; a `str` is only legal when
`embedding_strategy == "server_side"`. In that path the SQL adapter's
`get_embedding_sql("$1", model)` produces a fragment like
`embedding('text-embedding-005', $1)::vector` (AlloyDB) or
`ai_embed($1, 'amazon.titan-embed-text-v2:0')::vector` (Aurora/aws_ml),
inlined into a `WITH query_vec AS (SELECT … AS vec)` CTE.

This means *the same embedding model is used for indexing and querying*
on the server-side path, by construction — there is no client-side
choice at query time.

For `LOCAL` backends, the search service grabs the configured embedder
from the registry / `EmbeddingService` and calls `embed_async(query)`
once per call. That vector is then pgvector-distance-compared in
`PostgresVectorProvider._precomputed_vector_search_*` or the LanceDB
equivalent.

Hybrid search (`search/hybrid_search.py`) is unchanged by embedding
choice — it consumes a `query_vector` (or a `str` for server-side) and
combines vector + tsvector results via score-aware RRF. None of the
search-side code knows which embedder produced the vector.

---

## Configuration surface

Schema lives in `agentic_inquiry/config.py`:

```python
@dataclass
class EmbeddingsConfig:
    default_provider: str = "sentence_transformer"
    default_dimensions: int = 384
    sentence_transformer: SentenceTransformerConfig
    hashing: HashingConfig
    local_model: LocalModelConfig
    fastembed: FastEmbedConfig
    cache: EmbeddingsCacheConfig
```

Each provider has its own sub-dataclass (`SentenceTransformerConfig`,
`FastEmbedConfig`, `LocalModelConfig`, `HashingConfig`) declaring
provider-specific knobs (`model_name`, `model_path`, `batch_size`, etc).
The convention is: one dataclass per provider, named `<Provider>Config`,
mounted on `EmbeddingsConfig` as a snake_case attribute.

`EmbeddingsCacheConfig` is the wrapper-layer config (`enabled`,
`max_entries`). It's separate from the provider configs because the
cache is composable with any local embedder.

YAML mirrors the dataclass tree exactly:

```yaml
embeddings:
  default_provider: sentence_transformer
  default_dimensions: 384
  sentence_transformer:
    model_name: all-MiniLM-L6-v2
    ndims: 384
  fastembed:
    model_name: BAAI/bge-small-en-v1.5
    batch_size: 32
  local_model:
    model_path: models/all-MiniLM-L6-v2-onnx
    normalize: true
    batch_size: 32
  cache:
    enabled: true
    max_entries: 10000
```

Server-side embedding settings (`embedding_model`, `embedding_dim`,
`embedding_strategy`) live on `BackendConfig` under `storage.backends.<name>`,
**not** on `EmbeddingsConfig`. That is intentional — the server-side
embedder is a property of the storage backend, not a free-standing
choice.

### Environment variables

Documented overrides:

`Config._apply_env_overrides` (`config.py:1703`) walks
`AI_*` keys and resolves each underscore-segment against the actual
config dataclass tree via `_set_nested` (`config.py:1864`), trying
progressively longer joined-key combinations against the keys present
at each level. Practical implications:

| Variable | Effect |
|---|---|
| `AI_EMBEDDINGS_DEFAULT_PROVIDER` | `embeddings.default_provider` |
| `AI_EMBEDDINGS_DEFAULT_DIMENSIONS` | `embeddings.default_dimensions` |
| `AI_EMBEDDINGS_LOCAL_MODEL_MODEL_PATH` | `embeddings.local_model.model_path` |
| `AI_EMBEDDINGS_LOCAL_MODEL_NORMALIZE` | `embeddings.local_model.normalize` |
| `AI_EMBEDDINGS_LOCAL_MODEL_BATCH_SIZE` | `embeddings.local_model.batch_size` |
| `AI_EMBEDDINGS_SENTENCE_TRANSFORMER_MODEL_NAME` | `embeddings.sentence_transformer.model_name` |
| `AI_EMBEDDINGS_FASTEMBED_MODEL_NAME` | `embeddings.fastembed.model_name` |
| `AI_EMBEDDINGS_FASTEMBED_CACHE_DIR` | `embeddings.fastembed.cache_dir` |
| `AI_EMBEDDINGS_FASTEMBED_THREADS` | `embeddings.fastembed.threads` |
| `AI_EMBEDDINGS_FASTEMBED_BATCH_SIZE` | `embeddings.fastembed.batch_size` |
| `AI_EMBEDDINGS_FASTEMBED_PARALLEL` | `embeddings.fastembed.parallel` |
| `AI_EMBEDDINGS_CACHE_ENABLED` | `embeddings.cache.enabled` |
| `AI_EMBEDDINGS_CACHE_MAX_ENTRIES` | `embeddings.cache.max_entries` |
| `AI_EMBEDDING_DEVICE` | sentence-transformer device pin (`cpu`/`cuda`/`mps`) — read directly by `SentenceTransformerEmbedder`, not via the config tree |

Convention: `AI_<SECTION>_<SUBSECTION>_<FIELD>` where each segment
matches an actual key in the dataclass tree. The provider-name segment
must match the full snake_case attribute (`local_model`, not `local`),
otherwise the lookup fails silently — `_set_nested` returns without
mutating the config.

Backend-level embedding settings (`embedding_strategy`,
`embedding_model`, `embedding_dim`) live on
`storage.backends.<name>.*`, which the convention-based mapper cannot
reach because `<name>` is dynamic. These currently have no env-var
override; set them in YAML or via a wrapper config layer.

Older docs (e.g. `docs/api-reference/embeddings.md`) list
`AI_EMBEDDINGS_PROVIDER`, `AI_EMBEDDINGS_LOCAL_*`, and
`AI_STORAGE_EMBEDDING_*` — those names predate the `_set_nested`
convention and don't reach the documented fields. Use the names in the
table above.

---

## Dimension propagation

Where dimensions come from at runtime, in the order the registry
actually consults them:

1. **Per-`(table, column)` registry override** — set explicitly via
   `registry.register(table, column, embedder, ndims=N)`. Wins over
   everything else for that slot.
2. **Default registry dimension**, set by the factory via
   `embedding_registry.configure_default_embedder(embedder, ndims=ndims)`.
   The `ndims` value here comes from the *config*, not from the
   embedder:
   - LOCAL branch: `config.embeddings.default_dimensions` (factory.py:90).
   - SERVER_SIDE branch: `caps.embedding_dimensions` (factory.py:72).

   The configured embedder's *own* declared dimension
   (`SentenceTransformerEmbedder(ndims=384)`,
   `LocalModelEmbedder(metadata.dimensions=768)`, etc.) is **not**
   consulted by the factory; it's the embedder's responsibility to
   produce vectors at the configured dim or fail. `SentenceTransformerEmbedder`
   reconciles by truncating/padding (`sentence_transformer.py:181`);
   `LocalModelEmbedder` raises if `ndims` is set and the model's
   declared dim disagrees (`local_model.py:475`).
3. **Embedder constructor argument** — only effective when the embedder
   is registered manually (path 1) or instantiated outside the factory.
   The factory ignores it for the default slot.

The practical implication: if you change `default_dimensions` without
changing the embedder, the registry believes the new size — and
`SentenceTransformerEmbedder` will silently truncate or pad, while
`LocalModelEmbedder` will refuse to load.

Mismatches surface at three points:

- **Schema creation:** the vector column gets sized to whatever the
  registry reports at the time the table is provisioned. Re-indexing
  with a different-dim embedder fails the column type check.
- **Insert time:** `pgvector` and LanceDB both reject mis-sized vectors.
- **Query time:** server-side searches embed the query at the configured
  model's dim; a mismatch with the stored corpus produces a SQL error
  before any rows are scanned.

There is no automatic re-indexing when the embedder changes. Operators
who switch models must drop + re-index. The golden bench
([RFC 0001](../rfc/0001-golden-bench.md)) currently pins recall@10
against a single MiniLM-on-LanceDB baseline; multi-embedder baselines
are not yet a supported shape and would need a `baseline.json` schema
extension before a Bedrock or Vertex baseline can be added alongside
the existing one.

---

## Hybrid embedding strategy

Per-table embedder overrides are how the codebase optimizes embedding
cost without changing the protocol. Today only one such override is
shipped: `graph_relationships.vector → HashingEmbedder`. Rationale:
relationship types are a finite string set ("imports", "calls",
"defines", …), so deterministic hashing matches type-equality lookups
~1000× faster than running them through a transformer.

Full design: [docs/design/hybrid-embedding-strategy.md](../design/hybrid-embedding-strategy.md).

The same mechanism is the natural home for any future per-corpus
specialization (e.g. doc-strings vs code chunks).

---

## Remote embedders

`RemoteEmbedder` (`agentic_inquiry/embeddings/remote.py`) is the base
class for cloud-API embedders that run client-side. It implements the
`Embedder` protocol and adds the cross-cutting concerns shared by every
hosted-embedding provider:

- **Per-request batch chunking.** Subclasses declare a class attribute
  `_max_inputs_per_request` (Titan v2: 1, Vertex AI: 250, OpenAI: 2048).
  `RemoteEmbedder.generate` chunks the caller's input into
  `min(batch_size, _max_inputs_per_request)` per call.
- **Optional parallel dispatch.** When `request_concurrency > 1`,
  chunks fan out across an instance-scoped `ThreadPoolExecutor` so a
  multi-input batch doesn't run strictly serially. With Titan v2's
  one-input-per-call constraint this is the single biggest throughput
  knob and the only way to amortize per-call latency at indexing time.
- **Retry on subclass-declared throttle exceptions.** Subclasses set
  `_throttle_exceptions` to the SDK exception types they want retried;
  the base loop applies exponential backoff (capped at 30s) up to
  `max_retries`. Auth / quota / validation errors fall through
  immediately — they need operator attention, not retries.
- **Output-dim validation.** Each returned vector is checked against
  the configured `ndims`; mismatches raise `ValueError` so a wrong-dim
  vector never reaches the storage layer.
- **Async path inherits the base.** `generate` is sync (blocking SDK
  call). `generate_async` uses the inherited thread-pool offload from
  `Embedder.generate_async` — same convention as every other embedder,
  so `embedder.generate(...)` is safe to call from inside a running
  event loop. Subclasses that want truly async transport (e.g.
  `aioboto3`) override `generate_async` directly.

### Concrete impl: `BedrockEmbedder`

`agentic_inquiry/embeddings/bedrock.py` ships the first concrete remote
embedder, targeting Amazon Titan Text Embeddings V2
(`amazon.titan-embed-text-v2:0`). Selected via
`config.embeddings.default_provider = "bedrock"`. Specifics:

- `_max_inputs_per_request = 1` — Titan's `InvokeModel` accepts one
  input per call. Larger user-facing `batch_size` works because the
  base loop chunks; `request_concurrency` is the only way to exceed
  one-call-at-a-time throughput.
- Output dim ∈ `{256, 512, 1024}`, configured via
  `embeddings.bedrock.output_dim`. Default 1024.
- Region is required at runtime — Titan v2 isn't available in every
  Bedrock region. The factory raises `ConfigurationError` if
  `embeddings.bedrock.region` is empty when bedrock is selected.
- AWS credentials use the standard boto3 provider chain (env vars,
  instance profile, `~/.aws/credentials`). The embedder doesn't
  shadow `AWS_*` variables.
- Throttle filter: only `ThrottlingException` and
  `ServiceQuotaExceededException` retry. `AccessDeniedException` and
  validation errors surface immediately.
- Composes with `CachingEmbedder` exactly like the in-process
  embedders — every cache hit avoids a billable Bedrock call, so the
  cache earns its keep faster on the remote path.

### Decoupling from storage backend

A `LOCAL`-strategy backend (LanceDB, plain Postgres, RDS without
`aws_ml`, CloudSQL) paired with `default_provider: "bedrock"` runs the
indexer client-side against Bedrock and writes the resulting 1024-dim
vectors into pgvector / LanceDB just like a sentence-transformer
deployment would. The embedder choice is independent of the backend
choice; `SERVER_SIDE` backends (AlloyDB today, future Aurora /
azure_ai) ignore the embedder entirely and embed in-DB.

### Adding the next remote embedder

The convention RFC 0003 establishes:

1. Subclass `RemoteEmbedder`. Declare `provider_name`,
   `_max_inputs_per_request`, and `_throttle_exceptions`. Implement
   `_invoke(texts) -> list[list[float]]` calling the provider SDK.
2. Add a `<Provider>Config` dataclass to `agentic_inquiry/config.py` with
   the common knobs (`region`, `model_id`, `output_dim`,
   `timeout_seconds`, `max_retries`, `request_concurrency`,
   `batch_size`) plus any provider-specific ones. Mount on
   `EmbeddingsConfig` as a snake_case attribute.
3. Add the provider literal to the `default_provider` enum in
   `config/config.schema.json`.
4. Add a dispatch arm to **both**
   `embeddings/factory.py::configure_embedder_for_backend` and
   `embeddings/service.py::EmbeddingService._create_embedder` (see
   "Two `EmbeddingService`s" above for why both).
5. Document the `AI_EMBEDDINGS_<PROVIDER>_*` env vars and add a
   commented block to `agentic-inquiry.yaml.example`.
6. Add a row to the golden bench (`tests/golden/baseline.json`) — a
   different embedding model = a different recall@10 baseline.

---

## Files touched by this layer

Embedding code:
- `agentic_inquiry/embeddings/base.py` — `Embedder` protocol
- `agentic_inquiry/embeddings/factory.py` — `configure_embedder_for_backend`
- `agentic_inquiry/embeddings/registry.py` — `EmbeddingRegistry`,
  `embedding_registry` singleton
- `agentic_inquiry/embeddings/service.py` — `EmbeddingService` (async facade)
- `agentic_inquiry/embeddings/{sentence_transformer,fastembed,local_model,
  hashing,noop,caching}.py` — concrete in-process embedders + wrappers
- `agentic_inquiry/embeddings/remote.py` — `RemoteEmbedder` base for
  cloud-API embedders
- `agentic_inquiry/embeddings/bedrock.py` — `BedrockEmbedder` for Amazon
  Titan v2

Storage / capability layer:
- `agentic_inquiry/storage/capabilities.py` — `EmbeddingStrategy`,
  `ProviderCapabilities`, the per-backend defaults
- `agentic_inquiry/storage/providers/postgresql/adapter.py` — server-side
  SQL adapters (Default / AlloyDB / RDS / Azure)
- `agentic_inquiry/storage/providers/postgresql/vector.py` — query-side
  `Union[List[float], str]` dispatch

Pipeline / search:
- `agentic_inquiry/indexing/pipeline.py` — ingestion flow + post-indexing
  `generate_embeddings()` polling
- `agentic_inquiry/indexing/embedding_service.py` — pipeline-side helper
- `agentic_inquiry/search/service.py` — retrieval flow, lazy
  `embedding_service` property
- `agentic_inquiry/search/graph_search.py`, `agentic_inquiry/mcp/tools/*.py`,
  `agentic_inquiry/server/routes/search.py` — query embedding sites
- `agentic_inquiry/memory/{system,consolidation,retrieval}.py` — memory
  embedding sites

Configuration:
- `agentic_inquiry/config.py` — `EmbeddingsConfig` and per-provider
  sub-configs
- `agentic-inquiry.yaml.example` — annotated template
- `docs/api-reference/embeddings.md` — public API surface
- `docs/design/hybrid-embedding-strategy.md` — per-table override
  design rationale

---

## See also

- [RFC 0003 — Pluggable embedding providers](../rfc/0003-pluggable-embedding-providers.md)
  proposes a `RemoteEmbedder` wrapper layer + Amazon Titan v2 as the
  first concrete cloud-API embedder.
- [RFC 0002 — AWS support](../rfc/0002-aws-support.md) covers the
  Aurora-server-side and RDS-client-side AWS deployment shapes; its
  `BedrockEmbedder` proposal is subsumed by RFC 0003's wrapper layer.
- [Hybrid embedding strategy](../design/hybrid-embedding-strategy.md)
  for per-table embedder overrides.
- [Storage backends](../storage-backends.md) for the
  capability + adapter pattern that drives `LOCAL` vs `SERVER_SIDE`
  routing.
