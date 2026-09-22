# Release & Deprecation Policy (Breaking Changes)

This document defines how the project ships and deprecates changes for major refactors (like database abstraction + connectors).

## Versioning

- The project uses semantic versioning: `MAJOR.MINOR.PATCH`.
- Breaking API changes require a MAJOR bump.

## Definitions

- **Public API**: documented imports and constructor signatures in `docs/api-reference/*`.
- **Internal API**: modules/classes not documented for external use; subject to change without notice.
- **Deprecated**: still supported, but scheduled for removal.

## Deprecation Workflow

1) **Announce**
   - Add a migration doc under `docs/development/`.
   - Add a CHANGELOG entry explaining the change and timeline.
2) **Introduce**
   - Keep backward-compatible wrappers where feasible.
   - Emit deprecation warnings (optional, but preferred) from old entry points.
3) **Migrate**
   - Update internal consumers first (SearchService/IndexingPipeline/MemorySystem/MCP tools).
   - Update examples and library docs.
4) **Remove**
   - Remove deprecated APIs only in a MAJOR release.

## Required Gates for Breaking Changes

Before merging a breaking change:

- Full test suite passes (`uv run pytest`).
- Type check passes (`uv run mypy`).
- Lint passes (`uv run ruff check`).
- Migration documentation exists and is accurate.
- Adapter compliance tests exist for the default backend (LanceDB).

## Backward Compatibility Expectations

- Keep import paths stable during major refactors.
- Prefer "wrapper aliases" to avoid forcing downstream changes immediately.
- Do not break stored data silently: if schema changes require migrations, document and test them.

