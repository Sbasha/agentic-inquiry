# Spec: Rename the importable package `agent-vault` → `agent_vault`

Mode: full (changes the public import path and the package source
directory; touches packaging metadata and ~600 Python files). The risk is
mechanical breadth, not design: a single token rename that must be applied
consistently across imports, string module paths, logger names, the pickle
allowlist, and copy-pasteable docs.

- **Status:** Shipped (2026-09-03)

## Objective

Python module names cannot contain hyphens, so `from agent-vault.server
.http_client import HookClient` is a `SyntaxError` (`agent` minus `vault`).
The plugin hooks import the package this way and crash on every
`/agv:*` invocation. Rename the importable package and its source
directory to the valid identifier `agent_vault`, and update every Python
import, string module path, and copy-pasteable doc reference to match.

The **distribution name** (`agent-vault` on PyPI), the **repo /
marketplace / plugin-cache** names, the **user config file**
(`agent-vault.yaml`), and the **SQLite / Postgres DB** names
(`agent-vault.db`, `POSTGRES_DB=agent-vault`) stay hyphenated - none of
them is a Python identifier and none caused the crash.

| Surface | Name |
| --- | --- |
| PyPI distribution / `uv.lock` name | `agent-vault` (keep) |
| GitHub repo / plugin marketplace / cache | `agent-vault` (keep) |
| Python import + source folder | `agent_vault` (rename) |
| User config file | `agent-vault.yaml` (keep) |
| SQLite file / Postgres DB | `agent-vault.db`, `POSTGRES_DB=agent-vault` (keep) |
| Product name in prose | `Agent-Vault` (keep) |

## Acceptance Criteria

- [x] Source directory `agent-vault/` renamed to `agent_vault/` (via `git mv`, history preserved).
- [x] `pyproject.toml`: `name = "agent-vault"` unchanged; `[project.scripts]` entry point is `agent_vault.cli.__main__:main`; hatch `wheel.packages` and `sdist.include` reference `agent_vault`.
- [x] Zero `from agent-vault` / `import agent-vault` statements remain in any `.py` file.
- [x] Zero string module paths matching `"agent-vault\.` or `'agent-vault\.` remain in `.py` files (importlib paths, `patch(...)` targets, pickle allowlist in `cache/document_cache.py`, provider registry/factory tuples, logger names).
- [x] `logging_setup.py` builds logger names as `agent_vault.<service>` and `audit.py` uses `getLogger("agent_vault.audit")`.
- [x] `Dockerfile` copies `agent_vault/`; `scripts/deploy/entrypoint.py` imports `agent_vault.server.app`; `python -m agent-vault.*` invocations become `python -m agent_vault.*`.
- [x] Docs, skills, and command files that show a Python import, a `-m` module, a `--cov=agent-vault[.*]`, `mypy agent-vault/`, or an `agent-vault/<path>` source citation are updated to `agent_vault`.
- [x] Preserved: `agent-vault.yaml`, `agent-vault.db`, `POSTGRES_DB=agent-vault`, `name = "agent-vault"` in `pyproject.toml` and `uv.lock`, and `github:sbasha/agent-vault/...` URLs all still present.
- [x] `uv run python -c "import agent_vault; from agent_vault.server.http_client import HookClient"` succeeds.
- [x] `python -m py_compile` of the Claude hook scripts (`user_prompt_submit.py`, `stop.py`) succeeds - the exact files that raised the reported `SyntaxError`.

## Boundaries

In scope: the package directory rename and every Python-identifier
occurrence of `agent-vault` (imports, string module paths, logger names,
`-m` invocations, `--cov`/`mypy` targets), plus the copy-pasteable
references to those in docs, skills, and command files.

Out of scope (`Never do`): renaming the PyPI distribution name, the
GitHub repo, the plugin marketplace/cache identifiers, the
`agent-vault.yaml` config filename and its detection in `config.py`, the
`agent-vault.db` SQLite path, `POSTGRES_DB=agent-vault`, and the
"Agent-Vault" product name in prose. Also out of scope: the `/agv:setup`
backend/target/config questions - a separate concern from this import bug.

Declined: a Hatch mapping that keeps the hyphenated folder while exposing
an `agent_vault` import - editable installs and the plugin hooks import
from source, so the folder must match the import name; the indirection
would leave the crash latent.

## Testing Strategy

Goal-based verification (mechanical rename, no logic change):
- Grep gates for both directions: zero `from agent-vault` / `import
  agent-vault` / `"agent-vault\.` / `'agent-vault\.` in `.py`; and the
  preserved-name greps still match (`agent-vault.yaml`, `name =
  "agent-vault"`).
- `python -m py_compile` of the two hook scripts that crashed.
- `uv run python -c "import agent_vault; from agent_vault.server.http_client import HookClient"`.
- `uv run --env-file .env ruff check .`, `mypy agent_vault/`, `pytest -x`
  as the standard gate suite.
