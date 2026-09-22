---
rfc: 0003
title: Pluggable embedding providers (Amazon Titan v2 first)
status: draft
authors: [eugeneacn]
created: 2026-05-02
related: ["0002-aws-support.md", "#159", "#168"]
---

# RFC 0003 — Pluggable embedding providers (Amazon Titan v2 first)

## Summary

Add a thin `RemoteEmbedder` wrapper layer to `agent_vault/embeddings/`
so cloud-hosted embedding APIs become first-class peers of the existing
in-process embedders (`SentenceTransformer`, `FastEmbed`, `LocalModel`,
`Hashing`). Standardize the configuration conventions for these
providers — one sub-config dataclass per provider, snake_case attribute
on `EmbeddingsConfig`, `AGV_EMBEDDINGS_<PROVIDER>_*` env vars — so
adding the next provider after this is a four-file change rather than a
new pattern. Land **Amazon Titan v2** (`amazon.titan-embed-text-v2:0`,
via Bedrock) as the first concrete `RemoteEmbedder` implementation.

This RFC is about the *abstraction* and the *conventions*. RFC 0002 is
about AWS deployment shapes; its `BedrockEmbedder` sketch slots into
this layer rather than living as a one-off.

## Motivation

The current embedding architecture (see
[`docs/architecture/embeddings.md`](../architecture/embeddings.md))
handles two situations cleanly:

1. **In-process embedding** — `Embedder` instances that load a model
   into the Python process. Four implementations today, all selected
   via `config.embeddings.default_provider`.
2. **Server-side embedding** — the database calls a cloud API from
   inside SQL. `NoOpEmbedder` slot-fills the protocol on the client;
   the SQL adapter (`AlloyDBAdapter`, `RDSAdapter`, `AzurePostgresAdapter`)
   emits the backend-specific embedding fragment.

The gap: **client-side calls to cloud embedding APIs.** A LanceDB,
plain-Postgres, or RDS-without-`aws_ml` deployment that wants to use
Amazon Titan, Vertex AI Generative, or `text-embedding-3-large` has
nowhere to plug it in. The `Embedder` protocol allows it — Titan would
work fine as a subclass — but there is no convention for *how* such a
class registers itself, configures auth/region/quota, or threads
through the `default_provider` literal and the env-var surface.

Three things are simultaneously true:

1. **Customers ask for Titan / Vertex / OpenAI client-side.** Multi-cloud
   deployments often run a database that *can't* embed (LanceDB,
   self-hosted Postgres without ML extensions, RDS without `aws_ml`)
   and want to keep their embedding model consistent with whatever
   their downstream LLM stack uses. "AWS shop on RDS, Bedrock for both
   embeddings and Claude" is a real ask.
2. **RFC 0002 ships a `BedrockEmbedder` already.** It declares the
   Bedrock client as a peer of `SentenceTransformerEmbedder`, threads
   `"bedrock"` through `EmbeddingsConfig.default_provider`, and adds a
   `BedrockConfig` sub-dataclass. The shape is right, but the wrapper
   *layer* isn't extracted, so the next remote provider (Vertex,
   OpenAI, Cohere) reinvents the same boilerplate: retry policy,
   region/credential handling, output-dim configuration, throughput
   throttling, async path.
3. **The four existing providers already follow a convention** — one
   sub-config dataclass, `<provider>` lowercase string in
   `default_provider`, factory branch in
   `configure_embedder_for_backend` — but it's been *implicit*. Adding
   the fifth one is a good time to make it explicit, before five
   becomes ten and the divergence costs us.

What gets better if this lands:

- Adding the next remote embedder (Vertex, OpenAI, Cohere) is
  "subclass `RemoteEmbedder`, fill in `_invoke`, add a
  `<Provider>Config` dataclass" — no new factory plumbing per provider.
- AWS customers on plain RDS / LanceDB get a Titan path without waiting
  for Aurora `aws_ml`.
- The IAM / region / quota knobs all sit in one place
  (`RemoteEmbedderConfig` base class) so an operator who has configured
  Bedrock once knows how to configure the next provider.

What stays bad if this doesn't land:

- RFC 0002's `BedrockEmbedder` lands as a snowflake. The next remote
  provider duplicates 80% of its logic.
- The "no remote-API embedder" gap in
  `docs/architecture/embeddings.md` persists; multi-cloud customers
  keep being told to either use the database's server-side path (often
  unavailable) or fall back to a local model.

## Design

### What this RFC proposes (and what it doesn't)

**In scope:**

- A `RemoteEmbedder` base class under `agent_vault/embeddings/remote.py`
  that captures the shared concerns of any cloud-API embedder:
  auth/region resolution, async invocation path, retry on throttling,
  per-batch chunking against provider request limits, output-dim
  validation against the configured `ndims`.
- A `RemoteEmbedderConfig` base dataclass with the common knobs
  (`region`, `model_id`, `output_dim`, `timeout_seconds`, `max_retries`,
  `request_concurrency`, `batch_size`). `batch_size` is the
  *user-facing* chunk size the base loop targets; the effective
  per-request batch is
  `min(config.batch_size, subclass._max_inputs_per_request)`. For
  Titan v2 (`_max_inputs_per_request = 1`) the config value collapses
  to 1; for higher-batch providers (Vertex 250, OpenAI 2048) it acts
  as the upper bound.
- A first concrete impl: `BedrockEmbedder` (`embeddings/bedrock.py`)
  for Titan v2 specifically, plus a `BedrockConfig` sub-dataclass.
- Factory + config wiring so `embeddings.default_provider: "bedrock"`
  routes through the new layer.
- Conventions documented in `docs/architecture/embeddings.md` and
  `docs/api-reference/embeddings.md` so the *next* remote embedder
  doesn't re-debate the shape.

**Out of scope:**

- Adding Vertex AI, OpenAI, or Cohere embedders. Those follow once the
  layer exists. This RFC ships exactly one concrete implementation
  (Titan v2) so the abstraction stays grounded in real code.
- Changing the `Embedder` protocol. Remote embedders are still
  `Embedder` subclasses and still expose `generate(texts) ->
  list[list[float]]` + `ndims()`. No public surface changes for callers.
- Replacing `NoOpEmbedder` or the SQL adapter pattern. Server-side
  embedding (AlloyDB, Aurora `aws_ml`, Azure `azure_ai`) stays exactly
  as it is — the database does the work, the client uses
  `NoOpEmbedder`. This RFC is purely additive on the client side.
- Per-table remote-embedder overrides. The hybrid-embedding registry
  already supports per-`(table, column)` overrides; nothing here
  changes that.

### `RemoteEmbedder` base class

`agent_vault/embeddings/remote.py` (new):

```python
class RemoteEmbedder(Embedder):
    """Base class for embedders that call out to a cloud API.

    Provides the cross-cutting concerns shared by Bedrock, Vertex AI
    Generative, Azure OpenAI, Cohere, etc.: retry, batch chunking,
    output-dim validation, async-native path with sync fallback.

    Subclasses implement `_invoke(texts)` (the actual API call) and
    declare a `provider_name` class attribute used for metrics and log
    correlation. Everything else — retry policy, batching, dim assertion
    — comes from this base.
    """

    provider_name: ClassVar[str]

    def __init__(
        self,
        *,
        model_id: str,
        ndims: int,
        batch_size: int = 16,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
        request_concurrency: int = 1,
    ) -> None: ...

    @abstractmethod
    def _invoke(self, texts: list[str]) -> list[list[float]]:
        """Single API call. Subclass returns one vector per input.

        Implementations use the provider's blocking SDK
        (e.g. ``boto3.client("bedrock-runtime").invoke_model``).
        Concurrency comes from the caller running ``generate_async``,
        which offloads to the executor — not from this method itself.
        """

    def generate(self, texts: list[str]) -> list[list[float]]: ...
    # generate_async inherits from Embedder (thread-pool offload of generate)
    def ndims(self) -> int: ...
```

Key behaviours:

- **Sync-native, matches the existing `Embedder` convention.**
  `generate` is synchronous and calls the blocking SDK directly —
  same shape as `SentenceTransformerEmbedder`. `generate_async`
  inherits the base class's thread-pool offload. Critically, this
  means `embedder.generate(...)` is safe to call from inside a running
  event loop (which the indexing path already does, via
  `loop.run_in_executor(executor, embedder.generate, texts)`). An
  earlier draft of this RFC proposed routing sync `generate` through
  `asyncio.run(generate_async(...))`; that breaks because
  `asyncio.run` cannot be called from a running event loop. Subclasses
  that want a truly async transport (e.g. `aioboto3`) override
  `generate_async` directly — but the default keeps the protocol
  consistent with every other `Embedder` and avoids the running-loop
  pitfall.
- **Batch chunking + parallel dispatch.** Provider request limits
  (Bedrock: 1 input per call for Titan v2; Vertex: 250; OpenAI: 2048)
  live in the subclass via a `_max_inputs_per_request` class attribute.
  `RemoteEmbedder.generate` chunks the caller's `texts` into provider-
  sized sub-batches and, when `request_concurrency > 1`, dispatches
  them through an instance-scoped `ThreadPoolExecutor(max_workers=
  request_concurrency)` with `_invoke` running on each worker.
  Concurrency = 1 (default) means serial — one chunk at a time. With
  Titan v2's one-input-per-request, sustained throughput on a
  100-chunk batch is `request_concurrency × per-call latency`, so this
  knob is the single biggest performance lever for Bedrock indexing
  and the reason it lives in the base class. Bound by Bedrock's RPM
  quota (Titan v2: 2000 RPM default in `us-east-1`); the retry/backoff
  layer (next bullet) absorbs throttle responses without losing
  vectors.
- **Retry on throttling.** Tenacity-style exponential backoff on the
  provider-specific throttle / rate-limit exception. Default 3 retries.
  Doesn't retry on auth / quota-exceeded errors — those need operator
  attention, not retries.
- **Output-dim validation.** Asserts each returned vector matches
  `ndims`. Fails loudly on first mismatch — silently truncating /
  padding (as `SentenceTransformerEmbedder` does) is wrong here; if
  Bedrock returns a 768-dim vector when the schema expects 1024, the
  schema is already wrong and we want the error at insert, not after
  the corpus is half-corrupted.
- **Composable with `CachingEmbedder`.** The factory wraps
  `RemoteEmbedder` in `CachingEmbedder` exactly the same way it wraps
  in-process embedders — the SHA256 LRU is even more valuable for
  remote calls (per-hit cost is an entire round-trip, not a forward
  pass).

### `BedrockEmbedder` for Titan v2

`agent_vault/embeddings/bedrock.py` (new):

```python
class BedrockEmbedder(RemoteEmbedder):
    provider_name = "bedrock"

    def __init__(
        self,
        *,
        model_id: str = "amazon.titan-embed-text-v2:0",
        ndims: int = 1024,
        region: str,
        normalize: bool = True,
        **kwargs,
    ) -> None: ...

    def _invoke(self, texts: list[str]) -> list[list[float]]:
        # Blocking boto3.client("bedrock-runtime").invoke_model.
        # Titan v2 takes one input per call — parent class handles
        # the batching loop and (when request_concurrency > 1)
        # parallel dispatch.
        ...
```

Titan v2 specifics that go in this class, not in the base:

- **One input per request.** `_max_inputs_per_request = 1` on the
  class. Higher user-facing batch sizes work because the base class
  chunks and (when `request_concurrency > 1`) parallelizes through
  the instance-scoped thread pool.
- **Output dim ∈ {256, 512, 1024}.** Configurable via `ndims`. Default
  1024. Lower dims trade recall for storage and faster pgvector index
  build.
- **`normalize: bool`.** Titan returns L2-normalized vectors when
  `normalize=true` is sent in the request body. Default true (matches
  what pgvector's cosine distance assumes downstream).
- **Region scoping.** Titan v2 is available in most Bedrock regions
  but not all. The `BedrockEmbedder` constructor takes `region` as a
  required keyword argument with no default; the factory checks
  `BedrockConfig.region` is set before constructing (see Configuration
  conventions below) so a misconfigured deployment surfaces a typed
  `ConfigurationError` at startup, not a `boto3` exception at first
  call.

### Configuration conventions

The convention codified by this RFC:

#### 1. One `<Provider>Config` dataclass per provider

In `agent_vault/config.py`, mounted on `EmbeddingsConfig` as a
snake_case attribute:

```python
@dataclass
class BedrockConfig:
    """Amazon Bedrock embedder configuration."""
    model_id: str = "amazon.titan-embed-text-v2:0"
    region: Optional[str] = None         # required iff provider == "bedrock"
    output_dim: int = 1024               # 256 | 512 | 1024 for Titan v2
    normalize: bool = True
    batch_size: int = 16                 # client-side batching loop
    max_retries: int = 3
    timeout_seconds: float = 30.0
    request_concurrency: int = 1
```

`region` is `Optional[str] = None` rather than `str = ""` because the
`BedrockConfig` dataclass is constructed unconditionally (it's a
default factory on `EmbeddingsConfig` even when the chosen provider
isn't `bedrock`). Defaulting to an empty string would make
"unconfigured" and "intentionally empty" indistinguishable. The
factory arm validates explicitly:

```python
elif provider == "bedrock":
    bd = config.embeddings.bedrock
    if not bd.region:
        raise ConfigurationError(
            "embeddings.bedrock.region is required when "
            "default_provider == 'bedrock'. Set it in YAML or via "
            "AGV_EMBEDDINGS_BEDROCK_REGION."
        )
    # construct BedrockEmbedder ...

@dataclass
class EmbeddingsConfig:
    default_provider: str = "sentence_transformer"
    default_dimensions: int = 384
    sentence_transformer: SentenceTransformerConfig = ...
    hashing: HashingConfig = ...
    local_model: LocalModelConfig = ...
    fastembed: FastEmbedConfig = ...
    bedrock: BedrockConfig = field(default_factory=BedrockConfig)   # ← new
    cache: EmbeddingsCacheConfig = ...
```

#### 2. `default_provider` literal extension

`EmbeddingsConfig.default_provider` accepts (existing values plus
`bedrock`):

```
"sentence_transformer" | "fastembed" | "local" | "local_model"
| "hashing" | "none" | "bedrock"
```

Existing values preserved for backwards compatibility:

- `"none"` — sentinel used by the AlloyDB setup template
  (`cli/setup/templates.py:146`) and respected by
  `Config.validate_embedding_consistency` (`config.py:1413`) to skip
  dim-consistency checks for SERVER_SIDE deployments. Must not be
  removed.
- `"local"` (factory) and `"local_model"` (`EmbeddingService._create_embedder`)
  both map to `LocalModelEmbedder` — the existing-code drift documented
  in `docs/architecture/embeddings.md` § "Two `EmbeddingService`s".
  This RFC does not collapse the two literals (out of scope, cluster
  #168) but the new `bedrock` literal must be added to *both*
  dispatchers (see Factory dispatch below) so it doesn't inherit the
  drift.

Future providers extend this literal. The factory dispatches on it.

#### 3. Factory dispatch

`configure_embedder_for_backend` in `embeddings/factory.py` adds a
`provider == "bedrock"` arm in the LOCAL branch, mirroring the existing
`fastembed`/`local`/`sentence_transformer` arms:

```python
elif provider == "bedrock":
    from agent_vault.embeddings.bedrock import BedrockEmbedder
    bd = config.embeddings.bedrock
    embedder = BedrockEmbedder(
        model_id=bd.model_id,
        region=bd.region,
        ndims=bd.output_dim,
        normalize=bd.normalize,
        batch_size=bd.batch_size,
        max_retries=bd.max_retries,
        timeout_seconds=bd.timeout_seconds,
        request_concurrency=bd.request_concurrency,
    )
    model_display_name = bd.model_id
```

The `CachingEmbedder` wrap follows the same logic as the existing
in-process providers — `cache.enabled and max_entries > 0`.

The same arm has to land in
`agent_vault/embeddings/service.py::EmbeddingService._create_embedder`,
which is the second dispatcher: it's instantiated directly by
`MemorySystem`, `MemoryConsolidation`, `MemoryRetrieval`,
`graph_search.GraphSearchService`, `mcp.utils.suggestions`, and the
CLI memory subcommands without going through
`configure_embedder_for_backend`. Both dispatchers must agree on the
provider literal; otherwise `default_provider: "bedrock"` works for
indexing/search but silently falls back to `SentenceTransformerEmbedder`
for memory and a few MCP tools. The redundancy is technical debt
flagged in cluster #168 (collapse to a single dispatcher); this RFC
keeps the duplication and pays the cost on both sides until that
cleanup lands.

#### 4. Env-var convention

`AGV_EMBEDDINGS_<PROVIDER>_<FIELD>` for each sub-config field, where
`<PROVIDER>` matches the full snake_case provider attribute on
`EmbeddingsConfig`. The convention is enforced by `_set_nested` in
`agent_vault/config.py`, which walks the dataclass tree segment by
segment — the env var must match the actual key path, no shortcuts.
For Bedrock:

| Env var | Maps to |
|---|---|
| `AGV_EMBEDDINGS_BEDROCK_MODEL_ID` | `embeddings.bedrock.model_id` |
| `AGV_EMBEDDINGS_BEDROCK_REGION` | `embeddings.bedrock.region` |
| `AGV_EMBEDDINGS_BEDROCK_OUTPUT_DIM` | `embeddings.bedrock.output_dim` |
| `AGV_EMBEDDINGS_BEDROCK_NORMALIZE` | `embeddings.bedrock.normalize` |
| `AGV_EMBEDDINGS_BEDROCK_BATCH_SIZE` | `embeddings.bedrock.batch_size` |
| `AGV_EMBEDDINGS_BEDROCK_MAX_RETRIES` | `embeddings.bedrock.max_retries` |
| `AGV_EMBEDDINGS_BEDROCK_TIMEOUT_SECONDS` | `embeddings.bedrock.timeout_seconds` |

AWS auth is *not* a Agent-Vault env var. boto3 already reads
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
`AWS_PROFILE` / IAM role from the environment via the standard provider
chain. Don't shadow that.

#### 5. YAML shape

```yaml
embeddings:
  default_provider: bedrock
  default_dimensions: 1024
  bedrock:
    model_id: amazon.titan-embed-text-v2:0
    region: us-east-1
    output_dim: 1024
    normalize: true
    batch_size: 16
    max_retries: 3
    timeout_seconds: 30
  cache:
    enabled: true
    max_entries: 10000
```

The agent-vault.yaml.example template gets a commented `bedrock:` block
mirroring the other providers.

### Decoupling from storage backend

Critical invariant: **embedder choice is independent of storage backend
choice**, except that `SERVER_SIDE` backends ignore the embedder
entirely.

Concretely, after this RFC the supported (backend × embedder)
combinations are:

| Backend | embedding_strategy | Compatible embedders |
|---|---|---|
| `lancedb` | LOCAL | sentence_transformer, fastembed, local, **bedrock** |
| `postgresql` | LOCAL | sentence_transformer, fastembed, local, **bedrock** |
| `cloudsql` | LOCAL | sentence_transformer, fastembed, local, **bedrock** |
| `rds` | LOCAL | sentence_transformer, fastembed, local, **bedrock** |
| `alloydb` | SERVER_SIDE | (NoOpEmbedder; embedder choice ignored) |
| `aurora` ([RFC 0002][rfc0002], capability registry entry pending — [#159][cluster159]) | SERVER_SIDE | (NoOpEmbedder; embedder choice ignored) |
| `azure` (capability registry entry pending — [#159][cluster159]) | SERVER_SIDE | (NoOpEmbedder; embedder choice ignored) |

[rfc0002]: 0002-aws-support.md
[cluster159]: https://github.com/sbasha/agent-vault/issues/159

Caveat: `azure` is in the `BackendType` literal and has a working
`AzurePostgresAdapter`, but `get_capabilities_for_backend` has no
`azure` arm today — the factory falls through to LANCEDB defaults for
that backend type. Wiring the capability registry is the audit
cluster #159 / RFC 0002's responsibility; this RFC depends on it for
the SERVER_SIDE rows but adds nothing to it.

This is the property that makes "RDS + Bedrock client-side" possible
without needing `aws_ml` — the deployment shape RFC 0002 calls out
specifically and that's currently unreachable.

### Ndims contract for remote embedders

Remote embedders publish their dim via `ndims()` from constructor
configuration (Titan: `output_dim`; future Vertex: model-defined;
future OpenAI: `dimensions` request parameter on
`text-embedding-3-*`). The `default_dimensions` field on
`EmbeddingsConfig` is overridden by the provider sub-config's explicit
dim — same pattern as `LocalModelConfig.ndims`. The factory passes the
provider-specific dim to `embedding_registry.configure_default_embedder
(embedder, ndims=...)` so the schema layer sizes columns correctly.

A 1024-dim Titan embedder writing into a corpus indexed at 384 dims
(MiniLM default) is the same kind of error as switching MiniLM to
mpnet-base — the column type rejects it at insert. The
[golden-bench RFC](0001-golden-bench.md) currently pins one
recall@10 baseline (MiniLM-on-LanceDB); cross-embedder comparability
needs a `baseline.json` schema bump (see Ship gate), keyed by
embedder, before a Titan baseline can land alongside it.

### Wrapper composition order

For a Bedrock-backed local-strategy deployment:

```
configure_embedder_for_backend(config) →
    BedrockEmbedder (raw API client) →
    CachingEmbedder (SHA256 LRU)     →
    embedding_registry.configure_default_embedder(...)
```

Same order as in-process embedders. The cache wins more here: every
hit is a saved network round-trip plus billable token cost.

### What does *not* change

- The `Embedder` protocol stays exactly as it is. Existing call sites
  (search, MCP, memory, server routes) work unchanged.
- `NoOpEmbedder` and the SERVER_SIDE path are untouched. AlloyDB,
  Aurora `aws_ml`, and Azure `azure_ai` continue to embed in-DB.
- The `EmbeddingRegistry` and per-table override mechanism are
  untouched. `HashingEmbedder` for `graph_relationships` still works.
- Hybrid search, RRF reranker, IDF boost — all unchanged. They consume
  vectors and don't care which embedder produced them.
- The two `EmbeddingService` classes still have the same name. Renaming
  is a separate cluster (#168) and not blocking on this.

### Documentation deliverables

- `docs/architecture/embeddings.md` — current-state doc, already
  written, gains a "Remote embedders" section once this RFC lands.
- `docs/api-reference/embeddings.md` — gains `BedrockEmbedder` /
  `RemoteEmbedder` reference and a "Configuring a new remote embedder"
  recipe.
- `agent-vault.yaml.example` — adds the commented Bedrock block.
- README storage-backends table gains a footnote that any LOCAL backend
  can be paired with `bedrock`.

## Alternatives considered

### A. Land `BedrockEmbedder` directly without a `RemoteEmbedder` base

This is what RFC 0002 currently sketches. It works for one provider.
Rejected because:

- The next remote provider (Vertex, OpenAI) reimplements retry,
  batching, dim validation, and the async path from scratch — and
  they'll inevitably diverge.
- Five-line cost to extract the base class while we have exactly one
  concrete impl. Costs more later when there are three.

### B. Generic LangChain / LlamaIndex embedding adapter

Wrap a LangChain `Embeddings` instance in our `Embedder` protocol and
get every provider for free. Rejected because:

- LangChain pulls a transitive dep tree we don't want and that the
  audit (cluster #160) is already trying to keep out.
- The retry / batching / quota behaviour is opaque — we'd be exporting
  problems to LangChain's release cycle.
- Our protocol is narrower and clearer. Wrapping LangChain to satisfy
  it is more glue than just writing the four methods.

### C. Replace `Embedder` with an `EmbeddingClient` facade

Bigger refactor: collapse `EmbeddingService`, `EmbeddingRegistry`, and
`Embedder` into a single facade with method-level provider dispatch.
Rejected because:

- The existing protocol is fine. The gap is that it has no client-side
  cloud-API implementation, not that the protocol shape is wrong.
- Changing the call surface across search / MCP / memory / server is
  out of proportion to the problem.
- This is a refactor cluster, not an RFC. If it ever happens, this
  layer slots in cleanly.

### D. Per-table cloud embedder (e.g. Bedrock for docs, MiniLM for code)

Tempting because the registry already supports per-table overrides, and
"premium model on docs only" sounds like cost optimization. Rejected for
this RFC:

- Out of scope. Once the layer exists, this is a config change
  (`registry.register("document_chunks", "vector", BedrockEmbedder(...))`)
  with no new code. Don't pre-design a knob nobody asked for.
- Mixing dims across tables works with the existing pgvector / LanceDB
  schema but operationally it's a footgun. If we pursue it, it gets its
  own RFC focused on the cost-vs-recall tradeoff.

### E. Add `EmbeddingStrategy.REMOTE_CLIENT` enum value

Make remote-API embedders a third strategy alongside `LOCAL` and
`SERVER_SIDE`. Rejected because:

- They *are* `LOCAL` from the schema/pipeline's point of view: the
  client computes the vector, the database stores it. The fact that
  computation happens over HTTP rather than in CPython is irrelevant
  to the strategy switch.
- Adding a third enum value forces every consumer of `caps.embedding_strategy`
  to handle three branches. Today they handle two; the third would be
  identical to the first.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Quota/cost surprise — every indexing run hits Bedrock | medium | `CachingEmbedder` enabled by default; document throughput vs cost in `docs/api-reference/embeddings.md`; surface per-run vector counts in indexing diagnostics. |
| Dim-mismatch with existing 384/768 corpora | medium | Hard-fail at construction if `output_dim` mismatches an existing schema; document re-index requirement; extend `tests/golden/baseline.json` to support multiple embedder rows (the current single-baseline shape from RFC 0001 doesn't accommodate this yet — schema bump lands with this RFC). |
| AWS auth misconfiguration — silent fallback or hangs | low | Boto3 fail-closed on missing credentials; the factory does a one-shot probe before calling `configure_default_embedder`. The cheapest IAM-meaningful probe on the actual runtime path is `boto3.client("bedrock-runtime").invoke_model(modelId=titan_model_id, body=b'{"inputText":"ping"}')` — wrapped in try/except, returns 200 + a vector or raises `AccessDeniedException` with a message naming the missing IAM action. (Avoid `bedrock.list_foundation_models` — it's on the control-plane service, requires `bedrock:ListFoundationModels`, and a successful list does not imply `bedrock:InvokeModel` is granted on the Titan model ARN.) Burn one billable token at startup; surface a typed `BedrockAuthError` pointing at the IAM policy doc. |
| Bedrock throttling under bulk indexing | medium | Exponential backoff in base class; `request_concurrency` knob defaults to 1; document RPM-based quotas (Titan v2: 2000 RPM default in `us-east-1`). |
| Network timeout during search latency budget | medium | Search-side `embed_async` already runs the embedder on a separate executor; remote embedder times out at `timeout_seconds` (default 30s) which is well above the search budget — surface a typed error rather than hanging. |
| Drift from RFC 0002's `BedrockEmbedder` sketch | low | RFC 0002 is in `draft`. This RFC supersedes the embedder portion of 0002's design (Adapter split + Aurora-server-side stay 0002's). Update 0002's "Embedder for the RDS-with-Bedrock path" section to point here when both land. |
| Optional `boto3` dep | low | Declare under `[project.optional-dependencies] aws = ["boto3>=1.34"]` (also needed by RFC 0002); raise an actionable `ImportError` in `BedrockEmbedder.__init__` if missing. |
| Async / sync path divergence | low | `RemoteEmbedder` follows the existing `Embedder` convention — sync `generate` calls the blocking SDK; async callers go through the inherited thread-pool offload in `Embedder.generate_async`. Same shape as every other embedder, avoids the "asyncio.run from running loop" footgun. |

## Ship gate

A reviewer can call this RFC "implemented" when:

- `agent_vault/embeddings/remote.py` exposes `RemoteEmbedder` with
  the documented interface.
- `agent_vault/embeddings/bedrock.py` exposes `BedrockEmbedder`
  subclassing `RemoteEmbedder`; `provider_name == "bedrock"`.
- `agent_vault/config.py` `EmbeddingsConfig` has a `bedrock:
  BedrockConfig` field; `default_provider` accepts `"bedrock"`.
- `agent_vault/embeddings/factory.py` `configure_embedder_for_backend`
  dispatches on `provider == "bedrock"` and wires the config in.
- `agent_vault/embeddings/service.py` `EmbeddingService._create_embedder`
  also gets a `provider == "bedrock"` arm. This is the second dispatch
  path — used by `MemorySystem`, `MemoryConsolidation`,
  `MemoryRetrieval`, `agent_vault.search.graph_search`,
  `agent_vault.mcp.utils.suggestions`, and the CLI memory subcommands,
  which instantiate `EmbeddingService(config)` directly without going
  through the factory. Without this arm, `default_provider: "bedrock"`
  silently falls back to `SentenceTransformerEmbedder` in those
  consumers. (Long-term cleanup: collapse the two dispatchers into one
  helper. Out of scope for this RFC; tracked in cluster #168.)
- `agent-vault.yaml.example` shows a commented `embeddings.bedrock`
  block.
- `docs/architecture/embeddings.md` "What's missing" section is gone;
  a "Remote embedders" section replaces it.
- `docs/api-reference/embeddings.md` documents `RemoteEmbedder` /
  `BedrockEmbedder` and the env-var convention.
- `tests/embeddings/test_bedrock.py` covers: dim mismatch raises,
  retry on throttle, in-batch dedup via `CachingEmbedder` works,
  factory-driven construction from config. Bedrock client is mocked
  via `moto` or a hand-rolled fake — no live AWS credentials required.
- `pyproject.toml` declares `boto3` as the `aws` optional extra (this
  is shared with RFC 0002, whichever lands first owns it).
- `tests/golden/baseline.json` (RFC 0001) is extended from a single
  baseline to a per-embedder shape, with a `bedrock-titan-v2-1024`
  entry alongside the existing MiniLM-on-LanceDB entry. RFC 0002
  needs the same shape change for its Aurora-Bedrock entry —
  **whichever RFC ships first owns the schema bump; if 0002 lands
  first, drop this bullet from 0003's gate** (the only remaining
  obligation is adding the `bedrock-titan-v2-1024` row, which folds
  into the next bullet).
- `grep -rn '== "bedrock"' agent_vault/` returns exactly two hits —
  `embeddings/factory.py::configure_embedder_for_backend` and
  `embeddings/service.py::EmbeddingService._create_embedder`. Anything
  more is a third hand-rolled dispatch that needs to be folded into
  one of the two existing ones (or into the consolidation tracked by
  cluster #168).

## What we are *not* doing

- Adding Vertex AI Generative, Azure OpenAI, OpenAI direct, or Cohere
  embedders. Those follow once the layer exists; each gets a small
  follow-up PR (subclass + config + factory branch + doc) under the
  conventions established here.
- Per-table remote embedder selection (Bedrock for docs, MiniLM for
  code). Possible with the existing registry, deliberately not
  pre-designed.
- Replacing `EmbeddingService` or `EmbeddingRegistry`. Those stay.
- Changing the `Embedder` protocol or any consumer call sites.
- Anthropic-API or Bedrock-as-LLM integration. This RFC covers
  embedding APIs only; Claude-via-Bedrock is a downstream-customer
  concern (see RFC 0002 § "What does not change").

## References

### AWS documentation

- Titan Text Embeddings V2 (output dims, request/response shape, RPM
  quotas):
  <https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html>
- Bedrock runtime API (`InvokeModel`):
  <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html>
- Bedrock model availability per region:
  <https://docs.aws.amazon.com/bedrock/latest/userguide/models-regions.html>
- IAM permissions for Bedrock (`bedrock:InvokeModel`):
  <https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html>

### Repo references

- `docs/architecture/embeddings.md` — current-state architecture doc
  (companion to this RFC).
- `agent_vault/embeddings/base.py` — `Embedder` protocol.
- `agent_vault/embeddings/factory.py` — `configure_embedder_for_backend`
  dispatch.
- `agent_vault/embeddings/registry.py` — `EmbeddingRegistry` and the
  per-table override mechanism.
- `agent_vault/embeddings/caching.py` — wrapper composition pattern
  this RFC reuses.
- `agent_vault/storage/capabilities.py` — `EmbeddingStrategy` enum
  and per-backend capability declarations (untouched by this RFC).
- `agent_vault/storage/providers/postgresql/adapter.py` — the
  server-side SQL adapters (untouched, included for context).
- [RFC 0001](0001-golden-bench.md) — golden bench, currently a
  single-baseline shape; this RFC extends it to a per-embedder shape
  to accommodate the new entry.
- [RFC 0002](0002-aws-support.md) — AWS deployment shapes; this RFC
  supersedes its "Embedder for the RDS-with-Bedrock path" section.
- Issue #159 (audit cluster — make AWS/Azure first-class).
- Issue #168 (audit tracking).
