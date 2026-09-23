# ADR-0004: Product lineage: the Agent Vault base over the 0.1.0 preview

- **Status:** Accepted
- **Date:** 2026-09-22
- **Decision-makers:** sammybasha
- **Supersedes:** none
- **Related:** RFC-0002, ADR-0005, `docs/specs/afp-lifecycle-contract/spec.md`, tag `v0.1.0`

## Decision summary

- **Decision:** We build Agentic Inquiry on the Agent Vault codebase imported at commit b1dbee4; the 0.1.0 preview runtime is retired and stays readable at tag `v0.1.0`.
- **Because:** the imported base already delivers indexing, hybrid search, a storage facade, three-tier memory and a large test suite, and the preview's distinguishing capability is a contract that can be reimplemented on it.
- **Applies to:** the `agentic_inquiry` package, the `ai` command, the plugins under `extensions/` and every downstream consumer, including the AFP pack.
- **Tradeoff accepted:** the preview's authored knowledge pages, collections, backup and restore, and its lifecycle contract are lost until reimplemented, and the base carries a heavier dependency footprint.
- **Revisit if:** the lifecycle contract cannot be met within the budgets in ADR-0005 on this base, or the dependency footprint blocks installation on a supported workstation.

## Context

Two codebases carried the name Agentic Inquiry in September 2026.

The 0.1.0 preview (tag `v0.1.0`, commit 86403f5, 2026-09-13) was a purpose-built local library of about 13,500 lines: SQLite records, LanceDB retrieval, authored Markdown knowledge pages, backup and restore, a Codex plugin, a Pi extension and a lifecycle contract (`ai capabilities --json`, `ai integration hook`, `ai mcp`) that the AFP pack `packs/agentic-inquiry` was written against. Its own `DESIGN.md` named nine required outcomes, and its `IMPLEMENTATION_PLAN.md` left native lifecycle acceptance, platform coverage and an independent comparison open.

The Agent Vault codebase (imported at b1dbee4 on 2026-09-21, renamed at 6668317, cut to local-only through 1a6c105 and 393ebac, merged to `main` as PR #1 on 2026-09-22) is about 106,000 lines with 4,700 collected tests: tree-sitter parsing for more than ten languages, document parsing, a hybrid search pipeline, a protocol-based storage facade (ADR-0001, ADR-0002), three-tier memory, an events subsystem, a FastMCP server and a Claude Code plugin. It has none of the preview's contract verbs.

A separate 2026-09-21 decision in the AFP repository named Agentic Inquiry the go-forward local knowledge solution and removed the Agent Vault parity arm from its benchmark, which is only coherent if the two names now denote one product.

## Decision

We adopt the Agent Vault base as the Agentic Inquiry runtime and retire the 0.1.0 preview.

Specifically:

- `main` continues from the imported base. Tag `v0.1.0` is history and is never rebased or deleted.
- The preview's lifecycle contract is reimplemented on the base as a first-class surface (ADR-0005, RFC-0002). The contract is the part of the preview that survives; the preview's storage, CLI and plugins do not.
- The preview's knowledge pages, collections and backup and restore are not carried over by this decision. Each returns only through its own spec.
- The version after this decision is 0.3.0. Versions 0.1.x belong to the preview, 0.2.0 to the unreleased import.

## Decision drivers

- Working retrieval and memory over hundreds of thousands of chunks, with tests, outranks a smaller codebase whose retrieval was measured on six questions.
- One product under one name. Two runtimes sharing `ai` on PATH would make capability discovery meaningless.
- The AFP pack must keep working: its contract is small enough to reimplement, so the base wins without breaking the consumer.

## Consequences

**Positive:**

- Search, indexing, memory and the storage contract exist today with a test suite, instead of being rebuilt.
- The AFP pack's contract survives unchanged, so the pack, the AFP bridge and the benchmark manifests keep their identifiers.
- One `ai` executable, one capability report, one owner registry.

**Negative:**

- The base imports lancedb, pyarrow and pandas at package import and configures file logging as a side effect. Meeting the contract's latency budgets requires removing those side effects (ADR-0005).
- Authored knowledge pages, collections and backup and restore are absent until specified again. The AFP pack's skill already treats them as capability-gated, so their absence is reported, not hidden.
- The runtime dependency footprint is several gigabytes with a model download on first index. Installation stays a separate, explicit step that the pack never performs.

**Revisit if:** the lifecycle contract cannot be met within the budgets in ADR-0005 on this base, or the dependency footprint blocks installation on a supported workstation.

## Confirmation

- **Mode:** lint/CI
- **Signal:** `tests/integration/test_afp_lifecycle_contract.py` passes on `main`, which proves the base meets the contract the preview defined.
- **Owner:** sammybasha

## Alternatives considered

- **Revive the 0.1.0 preview as `main`.** Rejected: it discards a working search engine, storage facade and test suite to keep a contract that costs a few hundred lines to port.
- **Keep both runtimes and let the pack pick one.** Rejected: two products under one command name defeat capability discovery and double every qualification.
- **Keep the base and abandon the contract, wrapping the base's own Claude plugin instead.** Rejected in RFC-0002: the plugin is Claude-only, imports the package from the ambient interpreter, starts a network server and injects prompts on every Stop.

## References

- `git show 86403f5:DESIGN.md` and `git show 86403f5:IMPLEMENTATION_PLAN.md` for the preview's contract and open work.
- Commits b1dbee4, 6668317, 4aca3c3, 1a6c105, 393ebac, ad53b77 for the import and the local-only cut.
- `~/projects/assets/afp/docs/decisions/benchmark-knowledge-and-workflow-comparison.md` for the go-forward decision of 2026-09-21.
