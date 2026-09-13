# Agent guide

Agentic Inquiry is a local Python library and CLI for cited retrieval, scoped memory, authored knowledge and evidence collection. The distribution is `agentic-inquiry`, the import package is `agentic_inquiry`, and the command is `ai`.

## Read first

- `README.md` describes supported user behavior and operator workflows.
- `ARCHITECTURE.md` describes component boundaries, data flow and persistence.
- `DESIGN.md` owns required behavior and acceptance criteria.
- `IMPLEMENTATION_PLAN.md` contains only remaining work, ordered for execution.

When these documents disagree, use `DESIGN.md` for product requirements and the implementation plus tests for current behavior. Correct stale documentation in the same change.

## Source map

| Area | Primary modules |
| --- | --- |
| Command parsing and dispatch | `src/agentic_inquiry/cli.py` |
| Library identity, SQLite schema, backup and restore | `src/agentic_inquiry/library.py` |
| Source inventory, indexing and retrieval | `src/agentic_inquiry/store.py` |
| Document extraction and resource limits | `src/agentic_inquiry/ingestion.py` |
| Structural code chunks | `src/agentic_inquiry/structure.py` |
| Static symbols and relationships | `src/agentic_inquiry/graph.py` |
| Memory, knowledge and capture | `src/agentic_inquiry/knowledge.py` |
| Native lifecycle policy and reconciliation | `src/agentic_inquiry/integration.py` |
| Codex and Pi installation ownership | `src/agentic_inquiry/clients.py` |
| Fixed-scope MCP server | `src/agentic_inquiry/mcp_server.py` |
| Frozen-study evidence accounting | `src/agentic_inquiry/evaluation.py` |
| Derived-cache cleanup | `src/agentic_inquiry/cache.py` |

Tests mirror these public seams under `tests/`. Bundled client assets live below `src/agentic_inquiry/assets/` and are shipped in the wheel.

## Repository rules

- Treat registered source repositories and supplied documents as read-only input.
- Keep mutable library state below the selected library directory. Do not commit `.agentic-inquiry/`, `results/`, model caches, indexes or local client projections.
- Preserve the distinction between durable SQLite records and authored knowledge, derived indexes, cached models and original source files.
- Keep the CLI and MCP server on the shared `invoke` command boundary. Do not create a second implementation of command behavior.
- Require explicit apply operations for destructive changes and client installation. Preserve ownership receipts and refuse collisions or modified owned files.
- Keep shared memory, capture and MCP writes opt-in. Do not infer authorization from installation alone.
- Keep packaging explicit in `pyproject.toml`. Do not include local AFP projections, credentials, source libraries or test results in an archive.
- Update `src/agentic_inquiry/DEPENDENCIES.txt` when a shipped dependency, model or bundled asset changes its identity or license.
- Do not hand-edit generated artifacts, lock data or build outputs. Regenerate them with their owning tool.

## Development

Install the locked environment:

```sh
uv sync --locked
```

Run the focused release checks:

```sh
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

Regenerate `uv.lock` with `uv lock` only when dependency metadata changes. Test observable behavior through the CLI-facing module boundary and use real files and repositories for end-to-end behavior.
