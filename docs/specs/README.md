# Feature specs

Per-feature directories under this folder pair `spec.md` (the contract)
with `plan.md` (the work-breakdown):

```
docs/specs/<feature>/
├── spec.md      ← contract + contract tests
├── plan.md      ← strategy + construction tests, broken into tasks
└── notes/       ← (optional) research, sketches, rejected approaches
```

Conventions, lifecycle, and the contract-vs-construction test split
live in [`../CONVENTIONS.md § 4`](../CONVENTIONS.md#4-specs-and-plans--docsspecsfeature).

**Templates:** [`../_templates/spec.md`](../_templates/spec.md),
[`../_templates/plan.md`](../_templates/plan.md). Run the
[`new-spec`](../../.claude/skills/new-spec/SKILL.md) skill to scaffold a
feature directory.

**Session-scratch state.** `state.json` and `notes/implementer-*.md`
files inside any feature dir are gitignored; see
[`../CONVENTIONS.md § Work-loop state`](../CONVENTIONS.md#work-loop-state).

[`afp-lifecycle-contract`](afp-lifecycle-contract/spec.md) - The `ai capabilities` and `ai integration hook` contract for host adapters (AFP pack), SQLite ledger, queued-then-reconciled capture, `ai mcp`, `ai status`.

[`index-memory-reliability`](index-memory-reliability/spec.md) - Graph-relationship merge honesty, memory-save verify-on-write, Darwin CPU-hatch hint.

[`first-run-reliability`](first-run-reliability/spec.md) - First-run onboard gate, index exit codes, LanceDB retry, env-file bootstrap.

[`salesforce-apex-parsing`](salesforce-apex-parsing/spec.md) - Apex class and trigger extraction.

[`salesforce-intelligence`](salesforce-intelligence/spec.md) - Salesforce recognizer and metadata allowlist.

[`ruff-format-baseline`](ruff-format-baseline/spec.md) - Repo-wide `ruff format` baseline and pre-commit ruff hooks pinned to `uv.lock`.

[`main-suite-green`](main-suite-green/spec.md) - The full test suite passes deterministically, with each failure fixed at its root cause.

[`mypy-clean`](mypy-clean/spec.md) - Zero mypy errors on `agentic_inquiry/`, with a regression test for each runtime defect behind a type error.

[`lazy-default-watcher`](lazy-default-watcher/spec.md) - Import `agentic_inquiry.watching` without creating files; build the default watcher on first lookup.

[`secrets-baseline`](secrets-baseline/spec.md) - Audited detect-secrets baseline and working pre-commit hooks.

[`clean-process-exit`](clean-process-exit/spec.md) - `ai memory` commands, `ai mcp`, integration reconcile and the test suite close the stores they open that own a non-daemon thread and exit when their work ends; a test that leaks a blocking thread fails and names it.

[`config-overlay-defaults`](config-overlay-defaults/spec.md) - `Config.load()` merges one user config file over the packaged `default.yaml`, so a partial file loads and omitted keys take the packaged default.

[`hybrid-reranker-default`](hybrid-reranker-default/spec.md) - Hybrid search fuses vector and full-text results with Reciprocal Rank Fusion unless the config selects another reranker.

[`java-rust-calls-edges`](java-rust-calls-edges/spec.md) - Language-aware call extraction and containing-definition lookup, so Java and Rust produce method-to-method `calls` graph edges.

[`lancedb-single-commit-upsert`](lancedb-single-commit-upsert/spec.md) - Session, record and memory-item row replacement is one LanceDB commit, so concurrent writers leave one complete row; `negate_memory` and `supersede_memory` write only the columns they change.

[`local-only-config-cleanup`](local-only-config-cleanup/spec.md) - Shipped configs, examples and user docs describe only local storage, and every full config we ship loads against the schema.

[`local-only-rerankers`](local-only-rerankers/spec.md) - Every hybrid-search reranker runs locally; a config naming a hosted reranker such as `cohere` fails at load and lists the valid options.

[`memory-update-atomicity`](memory-update-atomicity/spec.md) - Access bookkeeping, `update_importance` and `update_confidence` write only the columns they change in one LanceDB commit, so an update made right after `retrieve()` is never reverted or duplicated.

[`pin-python-upper-bound`](pin-python-upper-bound/spec.md) - Supported Python range capped at `>=3.10,<3.14` in packaging metadata, user docs and `uv.lock`.

[`ruff-clean-stale-fts-retry`](ruff-clean-stale-fts-retry/spec.md) - One stale-table retry path shared by vector, FTS, hybrid and filter search, and zero `ruff check` findings in `agentic_inquiry` and `tests`.

[`skill-global-invocation`](skill-global-invocation/spec.md) - Claude Code plugin skills call a globally installed `ai` command instead of `uv run --env-file .env ai`, so they run from a target project; the README documents the global install.
