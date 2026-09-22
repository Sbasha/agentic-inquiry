# Spec: Global `ai` invocation for plugin skills

- **Status:** Implementing
- **Contract:** none

Mode: full (build-system change trigger - end-to-end verification revealed the
global install needs a packaging fix, which touches `pyproject.toml` and
`config.py`).

## Objective

Make the Claude Code plugin skills invoke Agentic Inquiry as a globally installed
`ai` command instead of `uv run --env-file .env ai`, and document the global
install in the README. This removes the hidden requirement that the command run
from inside the agentic-inquiry clone (with its `.venv` and `.env`), which is what
blocked running the skills from a target project.

## Background

Every `extensions/claude/ai` skill calls `uv run --env-file .env ai ...`. That
only resolves when the current directory is the agentic-inquiry clone and contains a
`.env`. The README instructs users to run the skills from the project they want
to analyze, where neither holds - so the tool could not find itself. Option A
(chosen by the maintainer) installs `ai` as a system command, decoupling "the
tool exists" from "which directory I'm in."

## Acceptance Criteria

- [x] README documents installing `ai` globally with `uv tool install .` from
      the clone, as a first-class step alongside/after `uv sync`.
- [x] All `uv run --env-file .env ai <...>` invocations in
      `extensions/claude/ai/skills/**` become bare `ai <...>` (same
      subcommands and arguments, nothing else changed).
- [x] README's raw-CLI usage examples that call `uv run [--env-file .env] ai`
      become bare `ai` (the developer `pytest`/`mypy`/`ruff` commands stay
      `uv run`, since those are run from the clone during development).
- [x] A globally installed `ai` runs from an arbitrary directory: `ai --help`
      succeeds with cwd outside the clone (verifies the install path end-to-end).
- [x] No `--workspace` flag is added: it is unsupported outside `ai setup`, and
      a bare `ai` already defaults its workspace to the current directory.
- [x] The globally installed package bundles its runtime config data
      (`default.yaml`, `config.schema.json`) inside the `agentic_inquiry` package,
      and `config.py` resolves them via `importlib.resources` with a
      source-checkout fallback to the top-level `config/` dir.
- [x] After `uv tool install .`, `ai --help` from `/tmp` exits 0 (no
      "Default configuration not found" error), and `uv run ai --help` from the
      clone still works (fallback path intact).

## Packaging design

The runtime default config lives in the top-level `config/` directory
(`default.yaml`, `config.schema.json`), resolved today by
`Path(__file__).parent.parent / "config"` - a source-tree assumption that
breaks once `agentic_inquiry` is installed alone into `site-packages`.

Fix: map the two runtime files into the package namespace in the wheel via a
hatch `force-include` (`config/... -> agentic_inquiry/config_defaults/...`), and
resolve them in `config.py` via `importlib.resources.files("agentic_inquiry")`,
falling back to the top-level `config/` when the packaged copy is absent (the
source-checkout / `uv run` case). No files are physically moved, so the ~30
doc/test/dev-skill references to `config/*.yaml` stay valid, and nothing lands
at the `site-packages` root to collide with other packages.

## Boundaries

In scope: `extensions/claude/ai/skills/**`, `README.md`, and the
packaging resolver (`pyproject.toml` hatch `force-include`,
`agentic_inquiry/config.py`). The setup skill's "Current State" probes were
rewritten to look at `.agentic-inquiry/` (the real workspace layout) instead of the
clone's `config/*.yaml`, so Claude Code no longer has to guess where the
workspace lives.

Out of scope (deliberately unchanged):
- `CONTRIBUTING.md` and README's test/lint/typecheck commands - these are
  developer commands correctly run via `uv run` from inside the clone.
- `ai-dev` skills - the development plugin, run from the clone.
- The background hooks (`hooks/scripts/*.py`) - they `import agentic_inquiry` in the
  ambient `python3`, a separate mechanism from the `ai` command; a `uv tool`
  install does not make the package importable by system Python, so the hooks'
  existing graceful `ImportError` degradation is unchanged. Fixing hook
  importability is a separate concern to surface, not solve here.
- Gemini/Codex mirrors - `extensions/gemini/ai` has no `skills/` directory and
  there are no `.codex`/`.github` skill copies, so there is nothing to sync.

## Assumptions

- Technical: `--workspace` exists only on `ai setup` (`agentic_inquiry/cli/setup_wizard.py`); other commands use cwd. Confirmed by grep.
- Technical: hatch `force-include` maps source files into the wheel namespace without moving them on disk. Confirmed by `uv tool install .` then `ai --help` from `/tmp` exiting 0.
- Product: enabling the plugin stays per-project via `.claude/settings.json`; a global `ai` binary does not activate hooks. Confirmed by user 2026-09-04.
- Process: CONTRIBUTING and `ai-dev` stay on `uv run` because those are from-the-clone developer surfaces. User confirmation 2026-09-04 (option A, skip RFC).

## Testing Strategy

Goal-based checks (no unit tests - this is docs/markdown):
- `rg "uv run.*ai" extensions/claude/ai/skills/` returns zero hits.
- `ai --help` run from `/tmp` (outside the clone) exits 0 after
  `uv tool install .`.
- README contains a `uv tool install` line.

## Declined patterns

Tempted to add `--workspace "${CLAUDE_PROJECT_DIR}"` to every skill; declining -
only `ai setup` accepts it, and cwd already resolves the workspace correctly, so
adding it elsewhere would break those commands. Tempted to also convert the
Gemini mirror and CONTRIBUTING; declining - the mirror has no matching skills and
CONTRIBUTING is a from-the-clone developer surface where `uv run` is correct.
