# Spec: Pin `requires-python` upper bound to `<3.14`

Mode: light (borderline — pins published packaging metadata, but fully
specified by issue #154 and the risk is mechanical: missed co-located
version declarations + lock consistency. Escalate if anything structural
surfaces.)

- **Status:** Shipped (2026-07-31)

## Objective

Cap Agentic Inquiry's supported Python range at `>=3.10,<3.14`. Some
dependencies do not yet ship cp314 (CPython 3.14) wheels, so declaring
3.14 support is a lie the resolver can't honor. Narrow the declared
range, align user-facing docs, and regenerate the lock so it carries no
3.14-only resolution artifacts.

Migrated PR: sbasha/311256_agentic-inquiry#154 (from
sbasha/agentic-inquiry#125).

## Acceptance Criteria

- [x] `pyproject.toml` `requires-python = ">=3.10,<3.14"`.
- [x] README supported-version line reads `Python 3.10–3.13` (was `Python 3.10+`).
- [x] `docs/mcp/deployment.md` package-level prerequisites read `Python 3.10–3.13` (System Requirements line + the `python --version` check comment).
- [x] `uv.lock` regenerated: zero `python_full_version >= '3.14'` markers, zero `cp314` wheels.
- [x] `uv lock --locked` passes (lock consistent with `pyproject.toml`).
- [x] No dependency versions bumped by the regeneration (installed set unchanged).
- [x] No *other* co-located package-level version declaration left stale: verified no `classifiers` block, no ruff `target-version` (inferred from `requires-python`), mypy `python_version` is an unaffected floor, no `.github/workflows` CI matrix, README badge count = 1 (updated). Dependency-specific version notes (Cloud SQL connector `< '3.13'` in `docs/backends/`, `docs/storage/`) and language-feature notes (`docs/development/async-best-practices.md` "3.10+") are intentionally left — they track a library's or the language's behavior, not this package's declared range.

## Boundaries

In scope: the `requires-python` constraint, every user-facing
package-level supported-version statement (README prerequisites +
`docs/mcp/deployment.md` System Requirements), and the lock regeneration.

Out of scope: docs that describe a *dependency's own* Python support
(e.g. the Cloud SQL connector's `< '3.13'` note in `docs/backends/`,
`docs/storage/`) — those track that library's support matrix, not the
package's declared range. The repo-wide pre-existing ruff findings (284,
in Python files this change does not touch) are also out of scope.

## Testing Strategy

Goal-based verification (config + lockfile change, no logic):
- `grep` assertions on the three edited files.
- `uv lock --locked` for lock consistency.
- `uv sync` + `import agentic_inquiry` + `pytest --collect-only` as the
  environment smoke gate — the regenerated resolution still installs and
  imports.
- Diff inspection of `uv.lock` to confirm no `name`/`version` block changed.
