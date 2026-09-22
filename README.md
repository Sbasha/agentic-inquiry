# Agentic Inquiry

**Semantic code search and codebase intelligence for Teams and Agents.**

Agentic Inquiry gives people and AI coding assistants deep understanding of your codebase. It parses source code and documentation, builds a searchable knowledge graph of entities and relationships, and exposes everything through slash commands in agentic tools. Instead of relying on grep and file reads, your AI assistant can semantically search across hundreds of thousands of code chunks, trace data lineage, assess change impact, and recall project context across sessions.

```
/ai:search "how does authentication work"    # Semantic search across code + docs
/ai:onboard /path/to/project                 # AI-powered codebase onboarding
/ai:entity UserService                       # Understand any code entity
/ai:impact handleLogin                       # What breaks if I change this?
```

---

## Why Agentic Inquiry?

Standard AI code assistants search your codebase by pattern matching — grep, file globs, reading files one at a time. This breaks down on large codebases:

- **Grep can't find concepts.** Searching for "authentication" won't find `validateJWT()` or `SessionManager`.
- **Context windows overflow.** Reading every file isn't feasible at 16K+ files.
- **No memory between sessions.** Every conversation starts from scratch.

Agentic Inquiry solves this by building a persistent, searchable index of your codebase:

| Capability | What You Get |
|------------|-------------|
| **Semantic Search** | Find code by concept, not just keywords. Hybrid vector + full-text search with IDF-weighted reranking |
| **Code + Docs** | Unified index across source code, DOCX, PDF, DOC files |
| **Entity Graph** | Classes, methods, imports mapped with relationships |
| **Impact Analysis** | "What breaks if I change X?" with dependency traversal |
| **Lineage Tracing** | Follow data from UI to database and back |
| **Memory System** | Three-tier memory (working/episodic/semantic) persists across sessions |
| **Onboarding** | Auto-generated architecture reports for new codebases |

---

## Getting Started

### Prerequisites

- Python 3.10–3.13
- [uv](https://docs.astral.sh/uv/) package manager
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI

### 1. Clone and Install

```bash
git clone https://github.com/sbasha/agentic-inquiry.git
cd agentic-inquiry
uv sync                 # set up the project environment
uv tool install .       # install the `ai` command globally, on your PATH
```

`uv tool install .` puts a single `ai` command on your PATH so the plugin
skills can run it from any project. If you already installed `ai` earlier,
run `uv tool install . --reinstall` so PATH picks up the current env-file
loader. If uv reports that its tool directory isn't on your PATH, run
`uv tool update-shell` once and restart your shell. Installing the command
does **not** turn Agentic Inquiry on anywhere — the `/ai:*` skills and hooks
only activate in projects where you enable the plugin (next step).

On macOS, two embedding processes using Metal/MPS at once can abort. If
that happens, uncomment `INQUIRY_EMBEDDING_DEVICE=cpu` in
`.agentic-inquiry/envs/<name>/.env`.

### 2. Enable the Plugins

Add Agentic Inquiry to `.claude/settings.json` **in the project you want to analyze** (not in the Agentic Inquiry repo itself). The `path` should point to where you cloned the repo:

```json
{
  "extraKnownMarketplaces": {
    "agentic-inquiry": {
      "source": {
        "source": "directory",
        "path": "/path/to/agentic-inquiry/extensions/claude"
      }
    }
  },
  "enabledPlugins": {
    "ai@agentic-inquiry": true,
    "ai-dev@agentic-inquiry": true
  }
}
```

The Claude Code marketplace stays the canonical source. For GitHub Copilot
app or Codex, use the repo-local `.github/` and `.codex/` mirrors, which
point back to the same `.claude/` skill and agent tree.

### 3. Configure Storage

Start Claude Code in your target project and run:

```
/ai:setup
```

This creates a local LanceDB environment; it works out of the box with zero configuration and stores everything under `.agentic-inquiry/`. Agentic Inquiry is local only. The storage layer is defined by a provider contract so that an external database for governed projects can be added later; see [Storage Backends](#storage-backends).

### 4. Index Your Codebase

```
/ai:index /path/to/your/project
```

This parses all source files (10+ languages via [tree-sitter](https://tree-sitter.github.io/tree-sitter/) AST parsing) and documents (DOCX, PDF, DOC), extracts entities and relationships, generates embeddings, and stores everything in your chosen backend. Indexing speed depends on backend — LanceDB runs locally, AlloyDB can index 16K files in ~17 minutes with server-side embedding.

### 5. Start Searching

```
/ai:search "database connection pooling"
/ai:entity ConnectionPool
/ai:status
```

You're set. Everything below is reference and advanced usage.

---

## Usage

### Search

Semantic search finds code by meaning, not just keywords:

```
/ai:search "how are users authenticated"     # Conceptual query
/ai:search "Spring @Transactional usage"      # Framework-specific
/ai:search "error handling in payment flow"   # Cross-cutting concern
```

Search combines vector similarity (understands meaning) with full-text search (catches exact terms), then applies IDF-weighted reranking to ensure rare, distinctive terms in your query dominate the results.

### Entity Analysis

Understand any code entity — its purpose, who calls it, what it depends on:

```
/ai:entity UserService              # What does this class do?
/ai:entity handleLogin              # Function analysis with callers
```

### Impact Analysis

Before changing code, understand the blast radius:

```
/ai:impact handleLogin              # What files/entities are affected?
/ai:impact DatabaseConfig           # Config change ripple effects
```

### Data Lineage

Trace how data flows through the system:

```
/ai:lineage userId                  # Follow userId from UI to database
/ai:lineage paymentAmount           # Track payment data through services
```

### Architecture Discovery

Map the structure of an unfamiliar codebase:

```
/ai:patterns                        # Discover architectural patterns
/ai:services                        # Detect and map service boundaries
```

### Memory

Save and recall project insights across Claude Code sessions:

```
/ai:memory save "Auth uses JWT with refresh tokens, issued by AuthService"
/ai:memory recall "authentication"
```

Memory has three tiers: working (current session), episodic (weeks), and semantic (permanent). Important insights are automatically promoted to longer-lived tiers through a consolidation engine that runs in the background.

### Onboarding

Generate a comprehensive architecture report for a new codebase:

```
/ai:onboard /path/to/project
```

This runs indexing, exploration, and validation in parallel, producing reports on architecture layers, key entities, data flows, and potential issues.

---

## Advanced Usage

### Environment Management

Isolate different projects or backends with named environments:

```
/ai:env create local-test --profile local
/ai:env list
```

Switch between environments with `INQUIRY_ENV`:

```bash
INQUIRY_ENV=production ai search "query"
```

### ai Server

Agentic Inquiry includes a REST + MCP server for integrations beyond Claude Code — other AI assistants, IDEs, or custom tooling:

```
/ai-dev:server start               # Start on default port 8765
/ai-dev:server status               # Check running servers
/ai-dev:server stop                 # Stop
```

Or via CLI:

```bash
ai server start --port 8765
ai server status
ai server stop
```

The server exposes:
- **REST API** at `/api/v1/*` — search, memory, session, context, hooks
- **MCP endpoint** at `/mcp` — for MCP-compatible AI clients (Gemini, Codex, etc.)
- **Health** at `/health` — liveness and readiness checks

### CLI

All plugin commands have CLI equivalents:

```bash
ai index /path/to/project
ai search "database connection"
ai entity UserService
ai serve                # MCP-only server (STDIO)
ai serve --port 8000    # MCP-only server (HTTP)
```

### Document Indexing

Agentic Inquiry indexes documentation alongside code. Supported formats: DOCX, PDF, DOC, XLSX, and Markdown. Enable in your config:

```yaml
parsers:
  document:
    enabled: true
```

Documents and code share the same search index, so queries like `/ai:search "deployment process"` return results from both source code and documentation.

### Configuration

Configuration loads with precedence: **env vars > YAML > defaults**.

Create `agentic-inquiry.yaml` in your project root to override defaults:

```yaml
storage:
  root: "./.agentic-inquiry"
  backend: lancedb

search:
  hybrid_search:
    reranker_type: rrf
    vector_weight: 0.7
    fts_weight: 0.3
    reranker_params:
      k: 30
      dual_source_bonus: 1.3
  deduplication:
    max_results_per_file: 2
```

For per-environment config (e.g., different backends for dev vs production), use overlays:

```bash
# Create overlay at ~/.agentic-inquiry/envs/production/config.yaml
# Activate with:
export INQUIRY_ENV=production
```

### Storage Backends

| Backend | Config Type | Embedding Strategy | Notes |
|---------|-------------|-------------------|-------|
| **LanceDB** | `lancedb` | Local (SentenceTransformer, 384d) | Zero setup, file-based; vectors and graph |
| **SQLite** | `sqlite` | n/a | Events, file tracking and onboarding metadata |
| **In-memory** | `memory` | Local | Tests and throwaway sessions |

Every provider implements the protocols in `agentic_inquiry/storage/protocols/`. That contract, and what an external database provider for governed projects must satisfy, is documented in [docs/storage-backends.md](docs/storage-backends.md). No such provider ships in this distribution.

### Content Sources

Content is read from the local filesystem. The connector protocol in
[docs/development/connector-guide.md](docs/development/connector-guide.md)
describes how a new source is added.

### Data Directories

| Path | Purpose |
|------|---------|
| `~/.agentic-inquiry/` | Global data (environments, registry, events, logs) |
| `.agentic-inquiry/` | Project-local data (index, cache — gitignored) |
| `INQUIRY_HOME` env var | Override global data path |

---

## Plugin Reference

### ai (v1.5.0)

User-facing plugin — 14 commands, 3 agents, 8 hook types. All commands shown in the [Usage](#usage) section above.

**Commands**: `search`, `index`, `onboard`, `entity`, `impact`, `lineage`, `patterns`, `services`, `memory`, `validate`, `status`, `setup`, `env`, `help`

**Agents**: `codebase-explorer` (architecture mapping), `command-helper` (command discovery), `env-manager` (environment lifecycle)

**Hooks**: SessionStart, UserPromptSubmit, PreToolUse[Grep], PostToolUse[Write|Edit, Bash, TaskUpdate], PreCompact, Stop — Python scripts for signal analysis, memory capture, and context injection.

### ai-dev (v1.5.0)

Developer plugin — 6 commands, 15 skills, 3 agents.

**Commands**: `dev` (toggle dev mode), `test` (test workflow), `review` (code review), `functional-tests` (UAT suite), `server` (manage ai server), `sync-agents` (sync AGENTS.md with skills)

**Skills**: `coding-guidelines`, `testing`, `quality`, `extending`, `plugins`, `commit`, `code-review`, `test-quality`, `doc-quality`, `rca`, `cleanup`, `ai-dev`, `ai-test`, `ai-functional-tester`, `ai-execute-tests`

**Agents**: `code-reviewer` (multi-phase review), `functional-tester` (UAT execution), `test-reviewer` (test result analysis)

---

## Architecture

```
agentic_inquiry/
├── config.py      # Configuration (env vars → yaml → defaults)
├── cli/           # Command-line interface (ai index, ai search, ...)
├── server/        # REST + MCP server (FastAPI, dual-surface)
├── storage/       # Unified storage abstraction
│   ├── facade.py  #   StorageFacade: vector + graph + events + file tracking
│   ├── protocols/ #   Provider contract (vector, graph, events, file tracker, lifecycle)
│   └── providers/ #   LanceDB, SQLite, in-memory
├── search/        # Search engine
│   ├── service.py       # SearchService entry point
│   ├── hybrid_search.py # Vector + FTS with IDF-weighted reranking
│   ├── rerankers/       # RRF, cross-encoder, linear combination
│   ├── normalization.py # Proportional score normalization
│   └── deduplicator.py  # Per-file result deduplication
├── indexing/      # Indexing pipeline
│   ├── pipeline.py      # IndexingPipeline orchestrator
│   └── graph_builder.py # Entity/relationship extraction
├── parsers/       # File parsing
│   ├── chain.py               # Priority-based parser chain
│   └── implementations/       # unified_code (tree-sitter), document (DOCX/PDF), fallback_text
├── embeddings/    # Embedding generation
│   ├── service.py             # Async embedding with background warmup
│   ├── sentence_transformer.py # Default: all-MiniLM-L6-v2 (384d)
│   └── noop.py                # Server-side embedding passthrough
├── memory/        # Three-tier cognitive memory
│   ├── system.py        # MemorySystem orchestrator
│   └── layers/          # working (session), episodic (weeks), semantic (permanent)
├── discovery/     # Service map detection (Docker, K8s, Terraform, AST-grep)
├── validation/    # Index accuracy validation
├── mcp/           # Model Context Protocol server (legacy STDIO/HTTP)
│   ├── server.py        # FastMCP server
│   └── tools/           # 9 tool modules (search, context, memory, analysis, ...)
└── events/        # Observability and audit trails

extensions/claude/
├── ai/           # User-facing Claude Code plugin (v1.5.0)
│   ├── commands/  #   14 slash commands
│   ├── agents/    #   codebase-explorer, command-helper, env-manager
│   ├── hooks/     #   Python lifecycle hooks (8 event types)
│   ├── scripts/   #   Shared utilities (socket client)
│   └── servers/   #   Background daemon (cache, context, memory, version managers)
└── ai-dev/       # Developer Claude Code plugin (v1.5.0)
    ├── commands/  #   6 dev commands
    ├── skills/    #   15 development guidance skills
    └── agents/    #   code-reviewer, functional-tester, test-reviewer

.github/
├── copilot-instructions.md  #   Points to AGENTS.md
├── skills/                  #   Mirrors .claude/skills/
└── agents/                  #   Mirrors .claude/agents/

.codex/
├── instructions.md          #   Points to AGENTS.md
├── skills/                  #   Mirrors .claude/skills/
└── agents/                  #   Mirrors .claude/agents/
```

---

## Search Architecture

Hybrid search combines vector similarity and full-text search with innovations that eliminate the "good enough" problem at scale:

```
Query → [Vector Search] + [Full-Text Search]
              ↓                    ↓
        Pre-filter           Two-tier AND+OR
        (score > 0.15)       (CamelCase split)
              ↓                    ↓
         Score-aware RRF (k=30, dual_source_bonus=1.3x)
              ↓
         IDF-weighted content boost
              ↓
         Proportional normalization
              ↓
         Deduplication (max 2/file)
              ↓
         Top-K results
```

Naive vector search scores ~6-7/10 on large codebases due to embedding drift, result dilution, and keyword blindness. Agentic Inquiry scores **10.0/10** across keyword, conceptual, and structural queries on a 572K-chunk enterprise corpus.

Key innovations:
- **IDF-weighted content boost**: Rare query terms get up to 20x weight. Rescues results that vector search misses entirely.
- **Score-aware RRF**: Incorporates raw similarity scores into rank fusion, preventing dilution at scale.
- **Two-tier FTS**: AND query for precision, OR fallback for recall, with CamelCase/snake_case splitting.
- **Proportional normalization**: Preserves absolute quality signal (divide by max, not min-max).

---

## Performance

Benchmarked on a Java EE monolith (16,706 source files + 98 documents) against a managed PostgreSQL backend that this distribution no longer ships; local LanceDB figures are not yet measured:

| Metric | Result |
|--------|--------|
| **Total indexed** | 572,457 chunks, 296,880 entities, 70,259 relationships |
| **Search relevance** | 10.0/10 across keyword, conceptual, structural queries |
| **Vector search latency** | <100ms (HNSW index, 140K+ chunks) |
| **FTS latency** | <50ms (GIN index) |
| **Hybrid search total** | <1s including reranking + content boost |

---

## Development

```bash
uv sync                                    # Install dependencies
uv run --env-file .env pytest -x           # Run tests (stop on first failure)
uv run --env-file .env pytest              # Run all tests
uv run --env-file .env mypy agentic_inquiry/  # Type checking
uv run --env-file .env ruff format .       # Format code
uv run --env-file .env ruff check . --fix  # Lint
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines and contribution workflows, or invoke `/ai-dev:coding-guidelines` in Claude Code.

---

## Documentation

### For agents (Claude Code, Cursor, Codex, Gemini CLI, Copilot)

Read [`AGENTS.md`](AGENTS.md) first. `CLAUDE.md` is a symlink to it. The
file is kept short on purpose — it points to the skills and specialist
subagents below, which load on demand. `.github/` and `.codex/` are
compatibility mirrors that resolve to the same canonical files.

**Skills** ([`.claude/skills/`](.claude/skills/)) — named multi-step
workflows:

- `work-loop` — plan → execute → gates → review, with explicit stop
  conditions
- `new-spec` — open a feature directory with paired spec and plan,
  assumptions first
- `bug-fix` — reproduce, root-cause, minimum fix
- `new-adr` — record an architectural decision in frozen history
- `new-rfc` — open a cross-cutting proposal

**Specialist subagents** ([`.claude/agents/`](.claude/agents/)) — sharp
lenses for diff review, plus the executor used by supervisor mode:

- `adversarial-reviewer` — spec drift, missing edge cases, scope creep
- `security-reviewer` — OWASP Top 10 (web + LLM Apps) and STRIDE
- `quality-engineer` — testability, observability, reliability,
  maintainability
- `implementer` — single-task executor used by `work-loop` in
  supervisor mode

Governance and process documents:

- [`docs/CHARTER.md`](docs/CHARTER.md) — mission, scope, principles
- [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) — how we work in this
  repo

### Full documentation index

| Document | Purpose |
|----------|---------|
| [AGENTS.md](AGENTS.md) | Canonical agent context (CLAUDE.md → symlink) |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, code style, plugin conventions, testing philosophy, PR workflow |
| [docs/CHARTER.md](docs/CHARTER.md) | Mission, scope, principles |
| [docs/CONVENTIONS.md](docs/CONVENTIONS.md) | How we work in this repo |
| [docs/architecture/](docs/architecture/) | Architecture deep-dives (search, indexing, async, parsers, events) |
| [docs/adr/](docs/adr/) | Architecture Decision Records — see CONVENTIONS § ADR |
| [docs/rfc/](docs/rfc/) | RFCs — cross-cutting proposals (governance) |
| [docs/specs/](docs/specs/) | Feature specs and plans (per-feature; see README for layout) |
| [docs/backends/](docs/backends/) | Storage backend setup (LanceDB) |
| [docs/design/](docs/design/) | Normative specs (filter AST, query semantics, schema, embedding strategy) |
| [docs/development/](docs/development/) | Async best practices, parser guidelines, security, adapters |
| [docs/storage/](docs/storage/) | Index configuration, maintenance, schema migration |
| [docs/mcp/](docs/mcp/) | MCP server configuration, deployment, troubleshooting |
| [docs/guides/](docs/guides/) | User docs (Diátaxis-organized; topic dirs above migrate here as touched) |
| [docs/product/](docs/product/) | Roadmap / changelog hub (empty — root [CHANGELOG.md](CHANGELOG.md) serves this role today) |
| [docs/api-reference/](docs/api-reference/) | Core API and embedding API reference |
| [docs/knowledge/](docs/knowledge/) | Practitioner patterns / gotchas / antipatterns (`patterns.jsonl`) |
