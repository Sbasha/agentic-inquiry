# Contributing

Contributions should preserve Agentic Inquiry's local, cited and explicit behavior. Start with `README.md` for public behavior, `ARCHITECTURE.md` for component boundaries and `DESIGN.md` for requirements and acceptance criteria.

## Set up the checkout

Agentic Inquiry requires Python 3.11 or newer, Git and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/Sbasha/agentic-inquiry.git
cd agentic-inquiry
uv sync --locked
```

Run commands in the locked environment:

```sh
uv run ai --help
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
```

## Make a focused change

- Keep registered source roots read-only and write application state only to the selected library.
- Preserve citation identity, coverage diagnostics and stale evidence state across retrieval paths.
- Keep destructive operations and client installation preview-first with an explicit apply step.
- Keep shared memory, capture and MCP writes disabled until explicitly enabled.
- Use the existing command dispatcher for both CLI and MCP behavior.
- Add tests at the caller-visible boundary that changes. Use real temporary files, repositories and SQLite state rather than duplicating implementation details in a test harness.
- Update public documentation when supported behavior, operator steps or limitations change.

Do not commit local libraries, model caches, indexes, results, secrets, AFP projections or generated build artifacts. Do not edit `uv.lock` by hand. If dependency metadata changes, run `uv lock` and update `src/agentic_inquiry/DEPENDENCIES.txt` when the shipped dependency or model notice changes.

## Validate

Before opening a pull request, run:

```sh
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

Inspect the built source and wheel archives when packaging inputs change. They must contain the declared source, documentation, license and dependency notices, and must exclude local state and client projections.

## Report security issues

Do not open a public issue for a suspected vulnerability. Follow `SECURITY.md` to report it privately.
