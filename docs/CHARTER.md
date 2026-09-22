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
- **Multi-cloud, multi-backend storage.** LanceDB (local), PostgreSQL
  (self-hosted), Google Cloud SQL, Google AlloyDB, AWS RDS / Aurora, and
  Azure Database for PostgreSQL with the `azure_ai` extension — all
  behind the same `StorageFacade`. Pluggable server-side embedders for
  AWS Bedrock (Titan v2) and other providers are scoped in
  [`docs/rfc/`](rfc/); the in-scope set above tracks what is shipped
  in the codebase today.
- **Code intelligence primitives.** Entity extraction, impact analysis,
  data lineage tracing, and onboarding reports — surfaced as `/ai:*`
  slash commands.
- **Persistent multi-tier memory.** Working / episodic / semantic memory
  tiers that survive across Claude Code sessions.
- **Two delivery surfaces.** Claude Code plugins (`ai`, `ai-dev`) are
  the primary interface; the MCP server is the secondary surface for
  non-Claude or HTTP integrations.

### Out of scope

- **A general-purpose ML or LLM training platform.** Agentic Inquiry
  consumes embeddings and chat models; it does not train them.
- **A general-purpose vector database.** We layer on top of pgvector,
  LanceDB, and managed cloud equivalents — we do not build a new one.
- **A code-modification agent.** Agentic Inquiry surfaces understanding;
  edits are performed by Claude Code (or whoever invokes the plugin).
- **Bespoke per-customer forks.** Customer-specific behaviour belongs in
  configuration and plugin extensions, not in branching the core.
- **Replacing user-facing documentation.** Docs in `docs/guides/`
  describe how users use Agentic Inquiry; the system itself is not a
  substitute for written docs.

## Principles

1. **Multi-cloud is a hard product constraint.** Every storage backend,
   embedder, and connector exists because a real deployment depends on
   it. *Example:* an unused-looking AlloyDB setup path is still load-bearing
   for GCP customers and is not safe to delete on a "no tests + no docs"
   heuristic.

2. **The plugins are the primary interface; the library is the
   contract.** Slash commands in `extensions/claude/ai/` are how users
   interact; the Python API in `agentic_inquiry/` is the supported surface
   for tests, integrations, and the MCP server. *Example:* a new
   capability lands as a Python API change *and* a plugin command in
   the same PR, not one without the other.

3. **Storage abstractions stay backend-agnostic.** The `StorageFacade`
   never leaks provider-specific concepts to callers. *Example:*
   server-side embedding via `ai.initialize_embeddings()` is hidden
   behind `embedding_strategy: server_side`; callers never know it's
   AlloyDB-only.

4. **Async-only at the I/O boundary.** Every database, network, and
   subprocess call is `async def` / `await`. *Example:* a sync helper
   that performs a blocking `requests.get` is a bug even if it
   "happens to work" under the current load.

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
