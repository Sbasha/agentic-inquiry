# AGENTS.md

> **Canonical agent context for Agentic Inquiry.** `CLAUDE.md` is a symlink to
> this file. Cursor, Codex, Gemini CLI, and Copilot also read it.
>
> Keep this file under ~250 lines. Detail belongs in `docs/` or
> `.claude/skills/`, not here.

## What this repo is

**Agentic Inquiry** is a Claude Code plugin (with a secondary MCP surface) for
semantic code search, codebase intelligence, and AI-powered onboarding —
hybrid vector + full-text search over code and docs, behind `/ai:*`
slash commands.

For the architecture-doc navigation hub (role-based entry points to
subsystems), start at
[`docs/architecture/overview.md`](docs/architecture/overview.md);
[`docs/README.md`](docs/README.md) is the broader doc index.

## Source of truth

| Question                                  | Where it lives                       |
| ----------------------------------------- | ------------------------------------ |
| What is this project, what's in/out of scope? | [`docs/CHARTER.md`](docs/CHARTER.md) |
| Why did we choose X over Y?               | [`docs/adr/`](docs/adr/) |
| What should we change, and how?           | [`docs/rfc/`](docs/rfc/)             |
| What exactly does this feature do?        | `docs/specs/<feature>/spec.md`       |
| How will we build it, step by step?       | `docs/specs/<feature>/plan.md`       |
| How is the code organized today?          | [`docs/architecture/`](docs/architecture/) |
| User-visible changes by release?          | [`CHANGELOG.md`](CHANGELOG.md)       |
| How do users use the product?             | [`docs/backends/`](docs/backends/), [`docs/mcp/`](docs/mcp/), [`docs/customization/`](docs/customization/) today; new user docs land in [`docs/guides/`](docs/guides/) (Diátaxis) - see [CONVENTIONS § 5c](docs/CONVENTIONS.md#5c-docsguides--for-users) |
| How do agents do `<repeating task>`?      | `.claude/skills/<task>/SKILL.md`     |

If you can't find the answer in one of these places, **the answer doesn't
exist yet** — ask, or open an RFC. Lifecycle and mechanics live in
[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).

## How we work

For anything beyond a one-line edit, follow the **plan → execute → verify →
review** loop. The mechanics — verification modes, gate sequence, iteration
cap, capture-learnings, specialist-reviewer pass — live in the
[`work-loop`](.claude/skills/work-loop/SKILL.md) skill. Load it before
non-trivial work. [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md#how-we-do-non-trivial-work)
covers the *why*. Commits follow Conventional Commits — see
[`CONVENTIONS.md § Commits`](docs/CONVENTIONS.md#commits).

Specs are validation gates, not write-once docs. If implementation diverges
from the spec, update the spec in the same PR — drift is a bug.

For unattended/AFK work, the [Ralph harness](tools/RALPH.md) runs the loop
in fresh sessions. Read it first; Ralph fits *some* tasks, not most.

## Commands you'll need

```bash
uv sync                                    # one-time setup
uv run --env-file .env pytest -x           # run tests (stop on first failure)
uv run --env-file .env pytest              # run all tests
uv run --env-file .env mypy agentic_inquiry/  # typecheck
uv run --env-file .env ruff check . --fix  # lint
uv run --env-file .env ruff format .       # format
```

## Plugin skills (the user-facing surface)

Users interact with Agentic Inquiry through plugin skills in
`extensions/claude/`:

| Skill | Purpose |
|-------|---------|
| `/ai:search <query>` | Semantic search across code and docs |
| `/ai:index <path>` | Index a codebase |
| `/ai:onboard <path>` | AI-powered codebase onboarding |
| `/ai:entity <name>` | Understand a code entity |
| `/ai:impact <symbol>` | Analyze change impact |
| `/ai:lineage <symbol>` | Trace data flow |
| `/ai:memory` | Save/recall project insights |
| `/ai:setup` | Configure storage backend |
| `/ai:env` | Manage environments |
| `/ai:status` | Show project state |

Dev skills: `/ai-dev:coding-guidelines`, `/ai-dev:testing`,
`/ai-dev:quality`, `/ai-dev:review`, `/ai-dev:commit`.

Both plugins (**ai**, **ai-dev**) are enabled via
`.claude/settings.json` — see [`README.md`](README.md#2-enable-the-plugins).
Repo-local `.github/` and `.codex/` mirrors point back to the same
canonical `.claude/` tree for Copilot and Codex compatibility.

## Core architecture

| Component | Location | Purpose |
|-----------|----------|---------|
| Config | `agentic_inquiry/config.py` | Env → yaml → defaults |
| Storage | `agentic_inquiry/storage/facade.py` | Unified `StorageFacade` over the LanceDB, SQLite and in-memory providers |
| Search | `agentic_inquiry/search/service.py` | Vector + FTS + hybrid with IDF-weighted reranking |
| Parsers | `agentic_inquiry/parsers/chain.py` | Tree-sitter code + DOCX/PDF/DOC docs |
| Indexing | `agentic_inquiry/indexing/pipeline.py` | Parse → embed → store |
| Memory | `agentic_inquiry/memory/system.py` | Three-tier memory (working / episodic / semantic) |
| MCP | `agentic_inquiry/mcp/` | Model Context Protocol server (secondary to plugins) |
| Integration | `agentic_inquiry/integration/` | AFP lifecycle contract: capabilities, hooks, ledger, reconcile |
| CLI | `agentic_inquiry/cli/` | `ai index`, `ai search`, … |

Storage is local only: LanceDB for vectors and graph, SQLite for events,
file tracking and onboarding metadata. The provider contract for a future
external database is in [`docs/storage-backends.md`](docs/storage-backends.md).

**Operational guardrails worth knowing before you touch the affected
code** (full detail in the per-subsystem docs):

- **Document parsing is single-worker by design.** `pypdfium2` segfaults
  under concurrency, so `parsers/implementations/document.py` uses a
  single-worker `ThreadPoolExecutor`. The hard file-size limit is 50 MB
  (`_MAX_DOC_FILE_SIZE`). See [`docs/architecture/parsers.md`](docs/architecture/parsers.md).
- **Hybrid-search tunables** (`MIN_VECTOR_SCORE`, `MIN_FTS_SCORE`,
  RRF `k`, `dual_source_bonus`, `max_results_per_file`) live in
  `search/` constants — change them deliberately, with a justification
  in the PR. See [`docs/architecture/search.md`](docs/architecture/search.md).

## Skills available to you

`.claude/skills/` contains workflows that have been used enough to deserve
a name. Every token loaded into context degrades performance somewhere, so
the list stays short by design — additions are gated by the three-times
rule in [`docs/CONVENTIONS.md § Skills`](docs/CONVENTIONS.md#skills).
`.github/skills/` and `.codex/skills/` are compatibility pointers to the
same source tree.

The directory listing is the source of truth — start with
[`work-loop`](.claude/skills/work-loop/SKILL.md) for any non-trivial
change. The complete current set (with one-line descriptions) is in
[`docs/CONVENTIONS.md § Skills`](docs/CONVENTIONS.md#skills).

## Specialist subagents

`.claude/agents/` contains sharp, differentiable lenses for diff review,
plus the executor used by `work-loop`'s supervisor mode. Pick the reviewers
the diff actually warrants; don't run all three by default.
`.github/agents/` and `.codex/agents/` mirror the same files.

- [`adversarial-reviewer`](.claude/agents/adversarial-reviewer.md) — spec /
  plan / implementation drift; missing edge cases; scope creep. Default
  reviewer; runs after gates pass.
- [`security-reviewer`](.claude/agents/security-reviewer.md) — OWASP Top 10
  (web + LLM Apps) and STRIDE lens. Use when the diff touches auth, secrets,
  user input, deserialization, file/network I/O, dependencies, or LLM/agent
  code. Complements SAST/SCA scanners; does not replace them.
- [`quality-engineer`](.claude/agents/quality-engineer.md) — testability,
  observability, reliability, maintainability lens. Also drafts contract or
  construction tests on request.
- [`implementer`](.claude/agents/implementer.md) — single-task executor;
  `work-loop` dispatches one per task in supervisor mode. Not a reviewer;
  not selected by hand.

## Code style and critical guidelines

Run lint / typecheck (see [Commands](#commands-youll-need)) and follow what
they tell you. The non-negotiables not covered by a linter:

- **Async-only at the I/O boundary.** Every database, network, and
  subprocess call is `async def` / `await`. The lifecycle ledger
  (`agentic_inquiry/integration/state.py`) uses synchronous `sqlite3`;
  a caller that already has an event loop reaches it through
  `asyncio.to_thread`.
- **Validate at boundaries** (user input, MCP clients, external APIs) with
  `agentic_inquiry.mcp.utils.validation`. Trust internal callers.
- **Never `pickle.loads()` untrusted data.** Use parameterized queries,
  never string interpolation for SQL.
- **Complete type annotations** on every function.
- **Lazy logging:** `logger.info("Processing %s items", count)` — not
  f-strings (eager evaluation).
- **Parser metadata uses LanceDB-compatible types only:** `str`, `int`,
  `float`, `bool`, `list[str]`.

Subsystem-specific rationale:
[`async-best-practices.md`](docs/development/async-best-practices.md),
[`parser-guidelines.md`](docs/development/parser-guidelines.md),
[`security.md`](docs/development/security.md),
[`error-message-security.md`](docs/development/error-message-security.md).

## Check before acting

- **Get user confirmation for destructive commands** (`rm -rf`,
  `git push --force`, dropping database tables) before running them.
- **Route substantive `docs/CHARTER.md` edits through an RFC.** Trivial
  fixes (typos, broken links) are fine as normal PRs.
- **Record new dependencies in `pyproject.toml` and an ADR**
  before adding them. Dependencies are forever.
- **Grep to verify a function or class exists** before importing it.
- **Don't drop a provider, embedder, or connector** on a "no tests
  + no docs" heuristic — multi-client support is a hard product
  constraint, and the storage provider contract is the seam for a future
  external database (see [`CHARTER.md`](docs/CHARTER.md)).
- **Propose new top-level directories via RFC.** The structure is
  intentional.

### Excuses we don't accept

Rationalizations the agent hits *before* the work-loop loads — when it's
deciding whether to load it at all. The in-loop set lives in
[`work-loop` § Anti-patterns](.claude/skills/work-loop/SKILL.md#anti-patterns-to-refuse).

| Excuse | What to do instead |
| --- | --- |
| "Small enough to not bother loading the work-loop." | Load `work-loop` and write its trio anyway — three sentences. The discipline is the point, not the length. |
| "I don't need a spec, I understand the task." | If it touches more than one file, run `new-spec`. The spec exists to surface what you don't know you don't know. |
| "I'll grep the codebase as I go." | Verify APIs *before* you start writing, not while you're writing. |
| "I'll match the surrounding code's pattern." | Check [Source of truth](#source-of-truth) first; local style may already conflict with the canonical convention. |

## When this file is wrong

Flag drift in your PR — don't silently work around it. AGENTS.md vs.
reality drift is the biggest cause of agent quality decay. Substantive
changes go through RFC; small fixes are normal PRs.

---

*Adapted from the [`agent-ready-repo`](https://github.com/eugenelim/agent-ready-repo)
template. See [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) for the full
conventions, or [`docs/architecture/overview.md`](docs/architecture/overview.md)
to start exploring.*
