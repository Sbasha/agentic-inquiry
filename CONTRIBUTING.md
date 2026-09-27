# Contributing to Agentic Inquiry

## Getting Started

```bash
git clone https://github.com/sbasha/agentic-inquiry.git
cd agentic-inquiry
uv sync
uvx pre-commit install             # Git hooks: secret scan, ruff, file hygiene
uv run --env-file .env pytest -x   # Verify setup
```

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `agentic_inquiry/` | Core library (config, storage, search, parsers, indexing, memory, MCP, CLI) |
| `extensions/claude/ai/` | Claude Code plugin — user-facing commands, hooks, agents |
| `extensions/claude/ai-dev/` | Claude Code plugin — developer commands, skills, agents |
| `tests/` | Unit and integration tests |
| `docs/` | Architecture, design, and development guides |
| `scripts/` | Utility and infrastructure scripts |

## Development Workflow

### Code Quality

```bash
uv run --env-file .env ruff format .    # Format
uv run --env-file .env ruff check .     # Lint
uv run --env-file .env ruff check --fix # Lint + autofix
uv run --env-file .env mypy agentic_inquiry/  # Type check
```

### Before Committing

All four must pass:

```bash
uv run --env-file .env ruff format . && \
uv run --env-file .env ruff check . && \
uv run --env-file .env mypy agentic_inquiry/ && \
uv run --env-file .env pytest
```

### Pre-commit hooks

`uvx pre-commit install` points the Git hook at uv's cache. If commits fail
with "`pre-commit` not found" after `uv cache clean`, run it again. The ruff
hooks call `uv`, so it must be on the `PATH` your Git client uses.

The ruff hooks format and lint only the files you stage. Lint findings ruff
cannot fix on its own must be fixed by hand before the commit passes, even when
you did not introduce them.

### Secret scanning

The detect-secrets hook compares staged files with `.secrets.baseline`, which
lists audited false positives. The hook suppresses every entry in the baseline,
so each one must be audited; a second hook rejects a baseline with unaudited
entries or entries marked as real secrets.

When the hook blocks a string that is not a secret, either add
`# pragma: allowlist secret` to that line, or add it to the baseline with the
detect-secrets version the hook pins and audit it:

```bash
uvx --from detect-secrets==1.4.0 detect-secrets scan --baseline .secrets.baseline
uvx --from detect-secrets==1.4.0 detect-secrets audit .secrets.baseline   # "y" marks a false positive
```

If the string is a real secret, remove it and rotate it; never add it to the
baseline.

If the hook reports that the baseline file was updated, it only moved line
numbers or dropped entries for strings that no longer exist: stage
`.secrets.baseline` and commit again.

## Code Style

- **Async-only**: All database and I/O operations use `async def` / `await`
- **Type hints**: Complete annotations on all functions (`async def search(query: str, limit: int = 10) -> list[SearchResult]`)
- **Lazy logging**: `logger.info("Processing %s items", count)` — never f-strings
- **Path validation**: Use `validate_file_path()` for any user-provided paths
- **Parser metadata**: Only `str`, `int`, `float`, `bool`, `list[str]` (LanceDB compatibility)
- **Security**: Parameterized SQL queries, never string interpolation. No `pickle.loads()` on untrusted data

## Testing

> We test for confidence, not coverage metrics. Every test must answer: *can we ship this with confidence?*

Before writing a test, answer:

1. **What breaks if it fails?** — If "nothing important," don't write it.
2. **How fast does it run?** — If > 100ms, justify it.
3. **Behavior or implementation?** — Implementation tests are brittle.

### Test pyramid

| Layer | Share | Speed |
|-------|-------|-------|
| Unit (`tests/unit/`) | 55% | < 100ms each |
| Integration (`tests/integration/`) | 30% | < 1s each |
| E2E / Model (`tests/e2e/`) | 10% | < 30s each |
| Agent UAT (`tests/01-agents/`) | 5% | manual |

Other directories: `tests/golden/` (search quality regression, < 10s total), `tests/stress/` (concurrency, < 60s total), `tests/adapters/` (third-party library assumption checks, < 30s total). Markers are auto-applied by directory via the `pytest_collection_modifyitems` hook in `tests/conftest.py`.

### Running

```bash
uv run --env-file .env pytest                          # All tests
uv run --env-file .env pytest tests/path/test_file.py  # Specific file
uv run --env-file .env pytest -k parser                # By pattern
uv run --env-file .env pytest -m unit                  # By marker (unit/integration/golden/stress/adapters)
uv run --env-file .env pytest --cov=agentic_inquiry       # With coverage
```

### Fixture naming

| Prefix | Use case |
|--------|----------|
| `mock_*` | Unit tests — mocked dependencies |
| `integration_*` | Integration tests — real but lightweight |
| `real_*` | E2E tests — production-equivalent |

### What we test, what we don't

**Test:** MCP tool contracts, search quality, data integrity, session isolation, error message safety (no leaked paths/IDs).

**Don't test:** library internals (lancedb, sentence-transformers), Python stdlib, mocked-everything pyramids — prefer an in-memory DB to mocking every layer.

### Anti-patterns

1. **Mock everything** — use the in-memory adapter (`memory/adapters/inmemory_adapter.py`) instead of mocking each call site.
2. **Brittle exact matches** — assert on semantic content, not exact strings.
3. **Sleep-based waits** — poll with timeouts.
4. **Testing third-party code** — test our wrappers, not the library.

Cross-tool integration is the highest-yield investment: most bugs we have shipped have been integration-shaped (one tool's output not matching another tool's input expectations), not unit-level. Always test "index → analyze → verify" round-trips.

## Storage Backends

Agentic Inquiry is local only. When developing:

| Backend | Config `type` | Embedding | Use Case |
|---------|--------------|-----------|----------|
| LanceDB | `lancedb` | Local (SentenceTransformer) | Vectors and graph |
| SQLite | `sqlite` | n/a | Events, file tracking, onboarding metadata |
| In-memory | `memory` | Local | Tests |

Every provider implements the protocols in `storage/protocols/`; the contract an external database provider must satisfy is in [docs/storage-backends.md](docs/storage-backends.md).

## Plugin System

Agentic Inquiry is primarily used through Claude Code plugins in `extensions/claude/`:

**ai** — User-facing plugin (`/ai:search`, `/ai:index`, `/ai:entity`, etc.)
- Commands: `extensions/claude/ai/commands/`
- Agents: `extensions/claude/ai/agents/`
- Hooks: `extensions/claude/ai/hooks/`
- Scripts: `extensions/claude/ai/scripts/`
- Servers: `extensions/claude/ai/servers/`

**ai-dev** — Developer plugin (`/ai-dev:test`, `/ai-dev:review`, etc.)
- Commands: `extensions/claude/ai-dev/commands/`
- Skills: `extensions/claude/ai-dev/skills/`
- Agents: `extensions/claude/ai-dev/agents/`

### Plugin Conventions

- Hook scripts use `${CLAUDE_PLUGIN_ROOT}` for paths (never hardcoded)
- Shared utilities live in `scripts/` (imported via `from scripts.socket_client import ...`)
- Command files use frontmatter: `description`, `argument-hint`, `allowed-tools`
- Command references use colon syntax: `/ai:search`, `/ai-dev:test`
- Plugin manifests (`plugin.json`) list explicit file paths for commands/agents

### Running the MCP Server

```bash
uv run --env-file .env ai serve                              # Default
uv run --env-file .env ai serve --project-id my_project      # Specific project
uv run --env-file .env ai serve --transport stdio             # For AI tool integration
uv run --env-file .env ai --list-tools                        # List available tools
```

## Environment System

Agentic Inquiry uses an environment system for isolating configurations:

- Global storage: `~/.agentic-inquiry/` (environments, registry, events, logs)
- Project-local: `.agentic-inquiry/` (test/dev data, gitignored)
- `INQUIRY_HOME` env var overrides `~/.agentic-inquiry/`
- Environment configs: `~/.agentic-inquiry/envs/<name>/config.yaml`
- Active environment tracked in `~/.agentic-inquiry/env-registry.json`

## Pull Requests

1. Create a feature branch from `main`
2. Make your changes following the code style above
3. Ensure all checks pass (format, lint, types, tests)
4. Open a PR against `feature-agentic-inquiry-search-implementation`
5. Include a clear description of what changed and why

## Additional Resources

- **Quick reference**: [AGENTS.md](AGENTS.md)
- **Architecture**: [docs/architecture/overview.md](docs/architecture/overview.md)
- **Design decisions (ADRs)**: [docs/adr/](docs/adr/)
- **Storage backends**: [docs/storage-backends.md](docs/storage-backends.md)
- **Parser guidelines**: [docs/development/parser-guidelines.md](docs/development/parser-guidelines.md)
- **Async patterns**: [docs/development/async-best-practices.md](docs/development/async-best-practices.md)
- **MCP troubleshooting**: [docs/mcp/troubleshooting.md](docs/mcp/troubleshooting.md)
