# Agent-Vault Documentation

Complete documentation index for Agent-Vault. Start with the [main README](../README.md) for setup and usage, or [AGENTS.md](../AGENTS.md) for the developer quick-reference.

---

## Architecture

How Agent-Vault is built — components, data flows, and design rationale.

| Document | Description |
|----------|-------------|
| [README.md](architecture/README.md) | Architecture section overview and quick navigation by role |
| [overview.md](architecture/overview.md) | System architecture — components, layers, plugin system, storage backends |
| [search.md](architecture/search.md) | Search pipeline — hybrid vector+FTS, RRF reranking, IDF-weighted content boost |
| [indexing.md](architecture/indexing.md) | Indexing pipeline — parsing, chunking, embedding, server-side strategy |
| [storage-adapters.md](architecture/storage-adapters.md) | Storage adapter layer — registry, unified PostgreSQL provider, config-driven routing |
| [event-system.md](architecture/event-system.md) | Event system — EventSystem (queue+batching), EventBus (pub/sub), EventStore (SQLite) |
| [async-architecture.md](architecture/async-architecture.md) | Async patterns — task coordination, cancellation, timeouts |
| [parsers.md](architecture/parsers.md) | Parser architecture — tree-sitter, priority chain, document parsing |
| [knowledge-graph.md](architecture/knowledge-graph.md) | Knowledge graph — entity extraction, relationship mapping, graph traversal |
| [design-decisions.md](architecture/design-decisions.md) | Design decisions overview and rationale |

### Architecture Decision Records

| ADR | Decision |
|-----|----------|
| [0001-protocol-based-storage.md](adr/0001-protocol-based-storage.md) | Protocol-based storage abstraction |
| [0002-storage-facade-pattern.md](adr/0002-storage-facade-pattern.md) | StorageFacade as unified entry point |
| [0003-filter-ast-consolidation.md](adr/0003-filter-ast-consolidation.md) | Filter AST replacing FilterBuilder |

---

## Design

Normative specifications — the contracts that implementations must satisfy.

| Document | Description |
|----------|-------------|
| [filter-ast.md](design/filter-ast.md) | Filter AST specification — type-safe query filtering across all backends |
| [query-semantics.md](design/query-semantics.md) | Query semantics — how search queries are parsed, split, and executed |
| [result-contract.md](design/result-contract.md) | Result contract — SearchResult shape, scoring, metadata |
| [logical-schema-reference.md](design/logical-schema-reference.md) | Schema reference — document_chunks, graph_entities, graph_relationships tables |
| [hybrid-embedding-strategy.md](design/hybrid-embedding-strategy.md) | Embedding strategy — local vs server-side, unified PostgreSQL provider, auto-config |
| [ownership-and-extension-points.md](design/ownership-and-extension-points.md) | Ownership map — who owns what, extension points, plugin layer |

---

## Storage Backends

Setup and configuration for each supported backend.

| Document | Description |
|----------|-------------|
| [storage-backends.md](storage-backends.md) | Backend comparison — all backends, capabilities, when to use each |
| [backends/lancedb.md](backends/lancedb.md) | LanceDB — zero-config local storage, file-based, default for development |
| [backends/postgresql.md](backends/postgresql.md) | PostgreSQL — self-hosted with pgvector, local embedding |
| [backends/cloudsql.md](backends/cloudsql.md) | CloudSQL — GCP managed PostgreSQL, connection pooling, proxy setup |
| [backends/rds.md](backends/rds.md) | AWS RDS / Aurora — managed PostgreSQL with optional Bedrock embeddings (Titan v2) |
| [backends/azure.md](backends/azure.md) | Azure Database for PostgreSQL — Flexible Server with `azure_ai` extension for server-side embeddings |

---

## Storage Operations

Day-to-day storage management — indexing config, maintenance, migrations.

| Document | Description |
|----------|-------------|
| [storage/index-configuration.md](storage/index-configuration.md) | Index configuration — vector indexes, FTS indexes, performance tuning |
| [storage/maintenance.md](storage/maintenance.md) | Maintenance — vacuuming, reindexing, monitoring, table health |
| [storage/schema-migration.md](storage/schema-migration.md) | Schema migration — version upgrades, table changes, data migration |

---

## API Reference

Programmatic interfaces for embedding Agent-Vault in your own code.

| Document | Description |
|----------|-------------|
| [api-reference/api.md](api-reference/api.md) | Core API — Config, StorageFacade, SearchService, IndexingPipeline, MemorySystem |
| [api-reference/embeddings.md](api-reference/embeddings.md) | Embedding API — EmbeddingService, SentenceTransformerEmbedder, server-side generation |

---

## MCP Server

Model Context Protocol server for integration beyond Claude Code plugins.

> **Note**: Most users should use [Claude Code plugins](../README.md#2-enable-the-plugins) instead of the MCP server directly. The MCP server is for advanced use cases: external tool integration, production HTTP APIs, or non-Claude MCP clients.

| Document | Description |
|----------|-------------|
| [mcp/configuration.md](mcp/configuration.md) | MCP configuration — transport modes (STDIO/HTTP), tool selection, environment |
| [mcp/deployment.md](mcp/deployment.md) | MCP deployment — Docker, health checks, monitoring, production setup |
| [mcp/troubleshooting.md](mcp/troubleshooting.md) | MCP troubleshooting — common errors, connection issues, debugging |
| [mcp/security.md](mcp/security.md) | MCP security — authentication, input validation, rate limiting |

---

## Development

Guides for contributors building on Agent-Vault.

| Document | Description |
|----------|-------------|
| [development/README.md](development/README.md) | Development section overview and quick links |
| [development/security.md](development/security.md) | Security guidelines — Filter AST, input validation, SQL injection prevention |
| [development/async-best-practices.md](development/async-best-practices.md) | Async patterns — event loops, task management, error handling |
| [development/parser-guidelines.md](development/parser-guidelines.md) | Writing parsers — tree-sitter queries, metadata constraints, chunk quality |
| [development/adapter-implementation-guide.md](development/adapter-implementation-guide.md) | Building storage adapters — BaseVectorProvider, BaseGraphProvider, embedding strategy |
| [development/connector-guide.md](development/connector-guide.md) | Connector development — FileSystem, S3, custom data sources (optional feature) |
| [development/filter-translation-guide.md](development/filter-translation-guide.md) | Filter translation — converting Filter AST nodes to backend-specific queries |
| [development/reranker-guide.md](development/reranker-guide.md) | Reranker development — RRF, cross-encoder, custom reranking strategies |
| [development/error-message-security.md](development/error-message-security.md) | Error message security — safe error reporting without information leakage |
| [development/release-policy.md](development/release-policy.md) | Release policy — versioning, changelog, backwards compatibility |
| [development/lessons-learned.md](development/lessons-learned.md) | Lessons learned — production incidents, debugging insights, gotchas |

---

## Events

Observability and event system internals.

| Document | Description |
|----------|-------------|
| [events/payload-validation.md](events/payload-validation.md) | Event payload validation — schema enforcement, type safety |

---

## Customization

Extending Agent-Vault with new backends, parsers, and features.

| Document | Description |
|----------|-------------|
| [customization/extending.md](customization/extending.md) | Extension guide — new backends, parsers, rerankers, plugin skills |
