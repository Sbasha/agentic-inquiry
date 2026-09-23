# Agentic Inquiry Charter

## Mission

Agentic Inquiry gives AI coding assistants deep, persistent understanding of a
codebase by indexing source and docs into a hybrid (vector + full-text)
search layer exposed through Claude Code plugin skills.

## Scope

### In scope

- **Hybrid semantic search.** Vector + FTS retrieval with RRF reranking,
  IDF-weighted boosting, and proportional normalization across the whole
  corpus (code chunks, DOCX, PDF, DOC).
- **Local storage behind one contract.** LanceDB for vectors and graph,
  SQLite for events, file tracking and onboarding metadata, all behind
  the same `StorageFacade`. Every provider implements the protocols in
  `storage/protocols/`; that contract is the seam for a future external
  database provider for governed projects, documented in
  [`storage-backends.md`](storage-backends.md). No cloud database,
  managed service or remote embedder is in scope.
- **Code intelligence primitives.** Entity extraction, impact analysis,
  data lineage tracing, and onboarding reports — surfaced as `/ai:*`
  slash commands.
- **Persistent multi-tier memory.** Working / episodic / semantic memory
  tiers that survive across Claude Code sessions.
- **Two delivery surfaces.** Claude Code plugins (`ai`, `ai-dev`) are
  the primary interface; the MCP server is the secondary surface for
  non-Claude or HTTP integrations. The lifecycle contract on the `ai`
  command is a third surface: `ai capabilities` and `ai integration hook`
  are what an AFP pack calls.

### Out of scope

- **A general-purpose ML or LLM training platform.** Agentic Inquiry
  consumes embeddings and chat models; it does not train them.
- **A general-purpose vector database.** We layer on top of LanceDB —
  we do not build a new one.
- **Cloud deployment.** No provisioning, proxies, managed databases or
  hosted embedding services. An external database for governed projects
  is future design work behind the provider contract, not a deployment
  target of this codebase.
- **A code-modification agent.** Agentic Inquiry surfaces understanding;
  edits are performed by Claude Code (or whoever invokes the plugin).
- **Bespoke per-customer forks.** Customer-specific behaviour belongs in
  configuration and plugin extensions, not in branching the core.
- **Replacing user-facing documentation.** Docs in `docs/guides/`
  describe how users use Agentic Inquiry; the system itself is not a
  substitute for written docs.

## Principles

1. **Local only, by design.** Everything runs on the user's machine:
   indexing, embeddings, storage and the MCP server. *Example:* a feature
   that needs a hosted service to work is out of scope until the external
   provider contract exists and is implemented; it is not added as an
   optional cloud path.

2. **The plugins are the primary interface; the library is the
   contract.** Slash commands in `extensions/claude/ai/` are how users
   interact; the Python API in `agentic_inquiry/` is the supported surface
   for tests, integrations, and the MCP server. *Example:* a new
   capability lands as a Python API change and a plugin command in
   the same PR, or, under the lifecycle contract, as a CLI verb.

3. **Storage abstractions stay provider-agnostic.** The `StorageFacade`
   never leaks provider-specific concepts to callers. *Example:* where
   embeddings are produced is declared through `ProviderCapabilities`;
   callers query capabilities and never test a backend type string.

4. **Async-only at the I/O boundary.** Every database, network, and
   subprocess call is `async def` / `await`. The ledger module
   `agentic_inquiry/integration/state.py` is the exception: it uses
   synchronous `sqlite3` because a hook is a short-lived process, and a
   caller that already has an event loop reaches it through
   `asyncio.to_thread`. *Example:* a sync helper that performs a
   blocking `requests.get` is a bug even if it happens to work under
   the current load.

5. **Validate at boundaries, trust internal callers.** Input from
   users, MCP clients, and external APIs goes through
   `agentic_inquiry.mcp.utils.validation`. *Example:* `validate_file_path`
   protects path-traversal at the MCP edge so internal indexing code
   doesn't need redundant checks.

6. **Documentation matches reality or it is a bug.** Specs are
   validation gates, not write-once docs; ADRs are frozen history,
   never edited. *Example:* if a PR changes the behaviour described
   in a spec, the spec is updated in the same PR.

7. **The structure is intentional.** Top-level directories, doc
   buckets, and convention boundaries are load-bearing. *Example:*
   adding a top-level directory or moving `agentic_inquiry/parsers/`
   under `storage/` goes through an RFC, not a refactor PR.

## How to change this charter

Trivial fixes (typos, broken links, dead references) land as normal
PRs. Substantive edits — mission, scope, or principles — go through
an RFC under [`docs/rfc/`](rfc/). See
[`docs/CONVENTIONS.md`](CONVENTIONS.md) for the RFC lifecycle.
