# Spec: Ruff format baseline and pre-commit enforcement

Mode: light (borderline: three sequential tasks, but each is mechanical)

- **Status:** Shipped (2026-09-26)
- **Constrained by:** none

## Objective

`uv run ruff format --check .` passes on `main`, and the repo's pre-commit
ruff hooks run the same ruff version as `uv run ruff`, so a contributor who
runs the hooks cannot commit code the documented format gate rejects.
The reformat changes layout only: no runtime behavior, lint finding or type
error changes in reformatted code.

## Acceptance Criteria

- [x] `uv run ruff format --check .` exits 0.
- [x] Every reformatted `.py` file parses to the same AST as on `main`,
      except docstring whitespace that ruff format reindents.
- [x] No `# type: ignore` comment ends up on a line other than the one
      mypy reports its error on.
- [x] The failing-test set with `-p no:randomly` and
      `INQUIRY_EMBEDDING_DEVICE=cpu` matches `main`'s (K-0001), apart from
      tests shown to fail on `main` too when rerun in isolation.
- [x] The golden bench (`tests/golden/bench.py --reindex`) reports the same
      recall on the branch as on `main`. The bench indexes this repo's own
      source, so reformatting changes its corpus.
- [x] `ruff check` and `mypy agentic_inquiry/` report the same findings as on
      `main`, compared by file, code and message (line numbers move), apart
      from the two scope changes below.
- [x] Ruff skips `.claude/`. The files there are managed by the pack
      installer, and reformatting them makes them diverge from the pack seeds
      and forces `*.upstream.*` collisions on reinstall.
- [x] `scripts/finetune_model.py` parses. On `main` its docstrings are
      written as `\"\"\"`, which is a syntax error that makes
      `ruff format --check` exit 2.
- [x] `.pre-commit-config.yaml` ruff hooks call `uv run ruff`, not a
      separately pinned `ruff-pre-commit` rev.
- [x] `pre-commit run ruff-format --all-files` passes, and a staged
      unformatted file fails the hook.

## Boundaries

Out of scope:

- The pre-existing `ruff check` findings and mypy errors.
- A line-length or other formatter setting. The default 88 is the closest
  fit to the existing code. With `.claude/` excluded and the script fix in
  place, 572 files change at 88, 608 at 100 and 614 at 120.
- The detect-secrets hook. It needs a `.secrets.baseline` that the repo
  has never had, so `pre-commit install` still blocks commits until that
  baseline is audited and added. For the same reason, CONTRIBUTING does
  not yet tell contributors to install the hooks.
- CI. The repo has no CI workflow and never had one. Adding `.github/` is
  a new top-level directory, so it goes through an RFC.
