# Spec: Rename the importable package `agentic-inquiry` → `agentic_inquiry`

Mode: full (changes the public import path and the package source
directory; touches packaging metadata and ~600 Python files). The risk is
mechanical breadth, not design: a single token rename that must be applied
consistently across imports, string module paths, logger names, the pickle
allowlist, and copy-pasteable docs.

- **Status:** Shipped (2026-09-03)

## Objective

Python module names cannot contain hyphens, so `from agentic-inquiry.server
.http_client import HookClient` is a `SyntaxError` (`agent` minus `vault`).
The plugin hooks import the package this way and crash on every
`/ai:*` invocation. Rename the importable package and its source
directory to the valid identifier `agentic_inquiry`, and update every Python
import, string module path, and copy-pasteable doc reference to match.

The **distribution name** (`agentic-inquiry` on PyPI), the **repo /
marketplace / plugin-cache** names, the **user config file**
(`agentic-inquiry.yaml`), and the **SQLite / Postgres DB** names
(`agentic-inquiry.db`, `POSTGRES_DB=agentic-inquiry`) stay hyphenated - none of
them is a Python identifier and none caused the crash.

| Surface | Name |
| --- | --- |
| PyPI distribution / `uv.lock` name | `agentic-inquiry` (keep) |
| GitHub repo / plugin marketplace / cache | `agentic-inquiry` (keep) |
| Python import + source folder | `agentic_inquiry` (rename) |
| User config file | `agentic-inquiry.yaml` (keep) |
| SQLite file / Postgres DB | `agentic-inquiry.db`, `POSTGRES_DB=agentic-inquiry` (keep) |
| Product name in prose | `Agentic Inquiry` (keep) |

## Acceptance Criteria

- [x] Source directory `agentic-inquiry/` renamed to `agentic_inquiry/` (via `git mv`, history preserved).
- [x] `pyproject.toml`: `name = "agentic-inquiry"` unchanged; `[project.scripts]` entry point is `agentic_inquiry.cli.__main__:main`; hatch `wheel.packages` and `sdist.include` reference `agentic_inquiry`.
- [x] Zero `from agentic-inquiry` / `import agentic-inquiry` statements remain in any `.py` file.
- [x] Zero string module paths matching `"agentic-inquiry\.` or `'agentic-inquiry\.` remain in `.py` files (importlib paths, `patch(...)` targets, pickle allowlist in `cache/document_cache.py`, provider registry/factory tuples, logger names).
- [x] `logging_setup.py` builds logger names as `agentic_inquiry.<service>` and `audit.py` uses `getLogger("agentic_inquiry.audit")`.
- [x] `Dockerfile` copies `agentic_inquiry/`; `scripts/deploy/entrypoint.py` imports `agentic_inquiry.server.app`; `python -m agentic-inquiry.*` invocations become `python -m agentic_inquiry.*`.
- [x] Docs, skills, and command files that show a Python import, a `-m` module, a `--cov=agentic-inquiry[.*]`, `mypy agentic-inquiry/`, or an `agentic-inquiry/<path>` source citation are updated to `agentic_inquiry`.
- [x] Preserved: `agentic-inquiry.yaml`, `agentic-inquiry.db`, `POSTGRES_DB=agentic-inquiry`, `name = "agentic-inquiry"` in `pyproject.toml` and `uv.lock`, and `github:sbasha/agentic-inquiry/...` URLs all still present.
- [x] `uv run python -c "import agentic_inquiry; from agentic_inquiry.server.http_client import HookClient"` succeeds.
- [x] `python -m py_compile` of the Claude hook scripts (`user_prompt_submit.py`, `stop.py`) succeeds - the exact files that raised the reported `SyntaxError`.

## Boundaries

In scope: the package directory rename and every Python-identifier
occurrence of `agentic-inquiry` (imports, string module paths, logger names,
`-m` invocations, `--cov`/`mypy` targets), plus the copy-pasteable
references to those in docs, skills, and command files.

Out of scope (`Never do`): renaming the PyPI distribution name, the
GitHub repo, the plugin marketplace/cache identifiers, the
`agentic-inquiry.yaml` config filename and its detection in `config.py`, the
`agentic-inquiry.db` SQLite path, `POSTGRES_DB=agentic-inquiry`, and the
"Agentic Inquiry" product name in prose. Also out of scope: the `/ai:setup`
backend/target/config questions - a separate concern from this import bug.

Declined: a Hatch mapping that keeps the hyphenated folder while exposing
an `agentic_inquiry` import - editable installs and the plugin hooks import
from source, so the folder must match the import name; the indirection
would leave the crash latent.

## Testing Strategy

Goal-based verification (mechanical rename, no logic change):
- Grep gates for both directions: zero `from agentic-inquiry` / `import
  agentic-inquiry` / `"agentic-inquiry\.` / `'agentic-inquiry\.` in `.py`; and the
  preserved-name greps still match (`agentic-inquiry.yaml`, `name =
  "agentic-inquiry"`).
- `python -m py_compile` of the two hook scripts that crashed.
- `uv run python -c "import agentic_inquiry; from agentic_inquiry.server.http_client import HookClient"`.
- `uv run --env-file .env ruff check .`, `mypy agentic_inquiry/`, `pytest -x`
  as the standard gate suite.
