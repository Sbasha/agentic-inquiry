# Storage Providers

Implementations of the four storage role protocols (`vector`, `graph`, `events`, `file_tracker`). Providers are instantiated by `storage.registry.create_provider` and composed into a `StorageFacade`.

## Directory layout

| Path | Purpose | Has AGENTS.md? |
|---|---|---|
| `base.py` | `BaseProvider` + `MaintenanceMixin` lifecycle helpers | no |
| `memory.py` | `InMemoryProvider` — vector + graph, testing only | covered here |
| `lancedb/` | LanceDB vector + graph (default) | yes |
| `postgresql/` | Unified pg provider for `postgresql`, `cloudsql`, `alloydb`, `rds`, `azure` | yes |
| `sqlite/` | SQLite events + file_tracker (default) | yes |
| `alloydb/` | GCP connection/auth helpers only (delegates runtime to `postgresql/`) | no |
| `cloudsql/` | GCP connection/auth helpers only (delegates runtime to `postgresql/`) | no |

## Protocols every provider must honour

Defined in `agent_vault/storage/protocols/`. A backend registers for one or more roles:

| Protocol | Required lifecycle | Required ops (partial) |
|---|---|---|
| `VectorStorageProtocol` | `initialize()`, `close()` | `upsert_chunks`, `vector_search`, `fts_search`, `hybrid_search`, `entity_vector_search`, `count`, `query` |
| `GraphStorageProtocol` | `initialize()`, `close()` | `upsert_entities`, `upsert_relationships`, `get_neighbors`, `traverse`, `query_entities`, `query_relationships` |
| `EventStorageProtocol` | `initialize()`, `close()` | `write_events`, `query_events`, `delete_before`, `run_maintenance` |
| `FileTrackerProtocol` | `initialize()`, `close()` | `get_hash`, `update_hash`, `has_changed`, `remove_file` |

All lifecycle methods must be idempotent.

## Registry integration (`storage/registry.py`)

`PROVIDER_REGISTRY` maps `backend_type → role → (module_path, class_name)`. `create_provider` has two dispatch branches with **different kwarg handling** — get this wrong and providers fail to construct:

- **Sync `from_config` path** (PostgreSQL family): provider classes expose `@classmethod def from_config(cls, config_dict, project_id)`. Registry passes `backend_config` verbatim (keeps `type` — adapters dispatch on it), drops `pool_manager`, passes `project_id` as a second positional arg.
- **Direct `__init__` path** (LanceDB, InMemory, SQLite): registry calls `provider_class(**merged_kwargs)` after stripping `type` and `pool_manager`. `config` is *kept* so LanceDB and InMemory receive their `Config` instance.

If you're adding a new backend:

1. Decide which dispatch branch fits. Async factories are fine but end up on the direct-`__init__` path.
2. Accept `**kwargs` in `__init__` unless you're sure the registry can't hand you anything extra.
3. Don't accept `type` — the registry strips it on the direct path and Postgres-style `from_config` receives it in the config dict, not as a kwarg.

## Memory provider (`memory.py`)

In-memory `InMemoryProvider` aliased as `InMemoryVectorProvider` and `InMemoryGraphProvider` in the registry. Purpose: unit tests and the `from_config` end-to-end test in `tests/storage/test_facade.py` — no external deps, no filesystem I/O.

- `SUPPORTED_ROLES = frozenset({"vector", "graph"})` — no events, no file_tracker. Use `sqlite` for those in tests.
- Signature: `InMemoryProvider(config=None, project_id="default")` — no `**kwargs`, so the registry's `type`-stripping is load-bearing.
- Vector search is brute-force cosine (`_cosine_similarity`) over every stored chunk. O(n·d) per query.

### Defaults for memory

There's no config surface — no knobs, no pool, no batching. The only "default" is an implicit one: **usable up to ~10k chunks in a test** (brute-force search, single Python process). Beyond that, test time dominates. If a test suite is pushing more rows than that through the memory provider, the test is wrong, not the provider.

## StorageFacade boundary

`StorageFacade` composes providers and owns lifecycle (`initialize`/`close`). A `BackendPoolManager` is allocated when any role uses a pooled backend (`postgresql`, `cloudsql`, `alloydb`, `spanner`, `rds`), but **is not currently wired through to providers** — the registry strips the `pool_manager` kwarg. Today its only effect is centralised `close_all()` on teardown. Wiring it to provider construction is tracked in issue #131.

The facade tracks `_backend_type` (vector-role) and `_graph_backend_type` separately. `get_connection_manager()` checks either role's pg-compatibility so mixed pairings (LanceDB vector + Postgres graph) correctly surface the graph-side connection.

## Adding a new backend

1. Implement the protocol(s) your backend serves.
2. Add an entry to `PROVIDER_REGISTRY` in `storage/registry.py`.
3. Add a `ProviderCapabilities` entry in `storage/capabilities.py` — this is what `StorageFacade.get_capabilities()` reads.
4. If it's a pooled backend, add its type string to `pooled_backend_types` in `StorageFacade.from_config`.
5. Add an entry to `agent-vault.yaml.example` so users see the shape.
6. Tests: at minimum, protocol-conformance via the contracts suite (`tests/storage/contracts/`) and one integration test through `StorageFacade.from_config` with the real registry.

## Don't

- Don't accept a `type` kwarg in a direct-`__init__` provider — the registry strips it. Add a new backend-type string to `PROVIDER_REGISTRY` instead.
- Don't rely on `pool_manager` being passed to your constructor. It isn't today.
- Don't implement vector and graph roles by composing a single monolithic class unless you actually need shared state — the registry can point both roles at the same class, but split providers (e.g. `PostgresVectorProvider` + `PostgresGraphProvider`) scale better and test cleanly. LanceDB's combined `LanceDBProvider` is kept for backward compatibility; new backends should split.
