# Plan: Global `ai` invocation for plugin skills

- **Spec:** [`spec.md`](spec.md)
- **Status:** Done

## Approach

Install `ai` as a system command (`uv tool install .`) so plugin skills can
call bare `ai` from any project. The wheel must ship `config/default.yaml`
and `config/config.schema.json` inside the package, because a global install
no longer has the source-tree `config/` directory next to the code.

Order: packaging resolver first (the install fails without it), then README
and skill text, then an end-to-end `ai --help` from `/tmp`.

## Tasks

### 1. Bundle runtime config in the wheel
- **Verification:** TDD
- **Done when:** `_packaged_config_file` finds the packaged copy when present
  and falls back to `config/` in a source checkout.
- **Tests:** unit tests in `tests/unit/test_config.py` covering packaged-wins,
  source fallback, and missing-file None.

### 2. Document the global install and switch skills to bare `ai`
- **Verification:** Goal-based check
- **Done when:** `rg "uv run.*ai" extensions/claude/ai/skills/` is empty and
  README §1 contains `uv tool install .`.
- **Tests:** no stub (mode)

### 3. End-to-end install smoke
- **Verification:** Visual / manual QA
- **Done when:** `uv tool install .` then `ai --help` from `/tmp` exits 0;
  `uv run ai --help` from the clone still exits 0.
- **Tests:** no stub (mode)
