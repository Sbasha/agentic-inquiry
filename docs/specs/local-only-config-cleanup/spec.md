# Spec: Remove PostgreSQL leftovers from shipped configs and docs

Mode: light (no risk trigger fired)

- **Status:** Shipped (2026-09-26)

## Objective

Storage is local only (LanceDB, SQLite, in-memory), but shipped config
files, examples and user docs still describe PostgreSQL, Cloud SQL,
AlloyDB, RDS and Bedrock as paths a user can take today. Some of those
files fail the schema the runtime enforces. Remove or correct every
shipped config and user-facing statement that describes a removed path
as supported, and make every full config we ship load cleanly.

## Acceptance Criteria

- [x] `config/test-postgresql.yaml` is gone, and nothing in the repo
      references it except `.env.example`, which agents cannot edit
      (deferred: local-only-config-cleanup).
- [x] `.mcp.json.example` has no `ai-test-postgres` server and no
      `CLOUDSQL_*` variables.
- [x] A user who copies `agentic-inquiry.yaml.example` to
      `agentic-inquiry.yaml` can run `ai index` and `ai search` and get
      results. Before this change the copy crashed with
      `AttributeError: 'NoneType' object has no attribute 'get'`, because
      `Config.load` validates the file as written (no merge with
      `config/default.yaml`) and several section headers had no body.
- [x] `agentic-inquiry.yaml.example` has no PostgreSQL, Bedrock, AlloyDB
      or RDS examples, and its environment-variable note names the real
      `INQUIRY_` prefix.
- [x] `config/default.yaml`, `config/test-lancedb.yaml` and
      `agentic-inquiry.yaml.example` pass `config/config.schema.json`
      and load through `Config.load` from an empty directory, as on a
      fresh clone, enforced by a test. `config/test-lancedb.yaml` roots
      its data at `./.agentic-inquiry_test`, because a root nested under
      the gitignored `./.agentic-inquiry/` failed there.
- [x] Docs under `docs/` (excluding specs, ADRs and RFCs, which are
      history), `extensions/`, `README.md` and `AGENTS.md` no longer
      describe a PostgreSQL-family backend or Bedrock embedder as usable.
      Pages that exist only to document a removed backend are deleted;
      pages kept as design input for a future external provider carry the
      historical-reference banner; live pages do not, except
      `docs/architecture/embeddings.md`, whose rewrite is tracked in the
      backlog. The relevance-enhancements history in
      `docs/architecture/search.md` carries a section-scoped historical
      note until its owner decides whether that history stays.
- [x] The storage configuration snippets in `docs/storage-backends.md`
      load through `Config.load`, enforced by a test, and through
      `StorageFacade.from_config`, checked by hand.

## Boundaries

Out of scope, each tracked under `local-only-config-cleanup` in
`docs/backlog.md`:

- `config/mcp.yaml` fails the schema and no code loads it.
- `Config._validate_config` raises `AttributeError` for an empty section.
- `ai search` ignores `--project` when building its event system, and
  does not exit after printing results.
- A rewrite of `docs/architecture/embeddings.md` around the shipped
  embedders, PostgreSQL-family code leftovers and the provider
  `AGENTS.md` files that describe them.
- LanceDB ignoring `database_path`, and `ai index` ignoring
  `embeddings.default_provider: hashing`.

## Tasks

1. Delete `config/test-postgresql.yaml`; drop its server from
   `.mcp.json.example`. Done when the grep for `test-postgresql` finds only
   `.env.example`, this spec and the backlog entry.
2. Rewrite the empty sections and removed-backend examples in
   `agentic-inquiry.yaml.example`; add a test that loads every full
   shipped config. Done when the test passes, fails on the old example,
   and the copied example indexes and searches.
3. Sweep user docs for supported-path references to removed backends.
   Done when the grep over the in-scope docs returns only design-input,
   history or neutral mentions.
