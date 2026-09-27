# Repository Conventions

This document is the single source of truth for **how we work in Agentic Inquiry**.
It exists so that contributors — human and agent — can answer "where does this
information go?" and "how do I propose a change?" without guessing.

It is opinionated. If a convention here doesn't fit your case, propose a
change via RFC, not by silently ignoring it.

---

## Document hierarchy

```
                       ┌──── CHARTER.md ────┐
                       │  Mission, scope,    │   The why. Stable for years.
                       │  principles.        │   Living, rarely changed.
                       └──────────┬──────────┘
                                  │
            ┌─────────────────────┼─────────────────────┐
            │                     │                     │
   ┌────────▼────────┐   ┌────────▼────────┐   ┌────────▼────────┐
   │  adr/           │   │  rfc/           │   │  specs/         │
   │  Why we chose   │   │  Should we      │   │  What a feature │
   │  X over Y.      │   │  change?        │   │  does + plan.   │
   │  Frozen history │   │  Governance     │   │  Living during  │
   │                 │   │  (open→closed)  │   │  build          │
   └─────────────────┘   └─────────────────┘   └─────────────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                │                                   │
        Internal current state             External current state
                │                                   │
   ┌────────────▼────────────┐       ┌──────────────▼─────────────┐
   │  architecture/          │       │  product/, guides/         │
   │  How the code is        │       │  product/ for maintainers, │
   │  organized today.       │       │  guides/ for users         │
   │  Living. For contributors│      │  (Diátaxis).               │
   └─────────────────────────┘       └────────────────────────────┘
```

Bottom layers cite upper layers; upper layers do not know about lower
layers. That's the whole point of the hierarchy.

### Lifecycle classes

| Class | Files | Rule |
| --- | --- | --- |
| **Living** | `CHARTER.md`, `architecture/*`, `product/*`, `guides/*`, active `specs/*` | Must match current reality. Updated in the same PR as any change that affects them. Drift is a bug. |
| **Frozen** | `adr/*`, shipped `specs/*`, accepted/rejected `rfc/*` | Immutable history. Status fields can change (Accepted → Superseded); bodies cannot. |
| **Governance** | open `rfc/*` | In flight. Updated through the RFC process. Closes to Frozen on acceptance/rejection. |

The frozen layer gives us decision history *without* the burden of
keeping it in sync. Living docs can be honest about the present
because they don't have to also be a record of how we got here.

---

## 1. Charter — `docs/CHARTER.md`

One page: mission, scope (in *and* out), principles (5–7 with one
concrete example each). Substantive edits go through an RFC; trivial
fixes are normal PRs. The out-of-scope list is the highest-leverage
part of the charter — it tells contributors and agents when a request
is out of bounds.

---

## 2. ADR — Architecture Decision Records — `docs/adr/`

An immutable record of a decision and the context that produced it. The
key property of an ADR is that it is **never edited after acceptance**.
If a decision is reversed, write a new ADR that supersedes the old one
and update the old one's status to `Superseded by ADR-NNNN`.

**Filename:** `NNNN-kebab-case-title.md`. Numbers are sequential and
never reused.

**Status values:** `Proposed` → `Accepted` → (`Deprecated` |
`Superseded by ADR-NNNN`).

**Template:** [`docs/_templates/adr.md`](_templates/adr.md). Run the
[`new-adr`](../.claude/skills/new-adr/SKILL.md) skill to scaffold one.

Agentic Inquiry's existing ADRs live in [`docs/adr/`](adr/) under the
4-digit form (`0001-protocol-based-storage.md`,
`0002-storage-facade-pattern.md`,
`0003-filter-ast-consolidation.md`). New ADRs continue in the same
directory; the numbering picks up at the next free number.

**When to write an ADR:** the choice was non-trivial, the rationale
involves tradeoffs a future maintainer can't reconstruct from the code,
or someone asks "why did we do it this way?" and there is no good
answer in writing. If you'd shrug, don't write one.

---

## 3. RFC — Request For Comments — `docs/rfc/`

A proposal to change something significant — a new feature area, a
new convention, a deprecation, or a breaking change to a public
interface. RFCs are *forward-looking governance*; ADRs are
*backward-looking record*.

**Format:** Use the `new-rfc` skill to scaffold, and follow `docs/rfc/README.md` for the current RFC workflow and index format.

**Lifecycle:** `Draft → Open for comment → Final comment period →
Accepted | Rejected | Withdrawn`.

Once accepted, an RFC produces follow-on artifacts:

- Architectural decisions → one or more ADRs
- Concrete features → specs in `docs/specs/`
- Convention changes → edits to this file (the change itself, not a
  copy of it)

**When to open an RFC:**

- The change touches more than one package or affects external users.
- The change reverses a previous ADR.
- The change adds, removes, or modifies a top-level directory or a
  convention in this file.
- Substantive edits to `docs/CHARTER.md`.

**When NOT to open an RFC:** bug fixes, refactors, or new features
that fit cleanly inside an existing module and don't change a public
interface — just open a PR (with a spec if non-trivial).

---

## 4. Specs and Plans — `docs/specs/<feature>/`

The precise definition of a single feature, sized to days or weeks.
Each feature gets a directory:

```
docs/specs/<feature>/
├── spec.md      ← contract + contract tests
├── plan.md      ← strategy + construction tests, broken into tasks
└── notes/       ← (optional) research, sketches, rejected approaches
```

`spec.md` is the contract. `plan.md` is the implementation strategy.
Specs are living during build, frozen after ship. If implementation
diverges from the spec, the spec is wrong — update it in the same PR.

**Templates:** [`docs/_templates/spec.md`](_templates/spec.md),
[`docs/_templates/plan.md`](_templates/plan.md).

### Contract tests vs. construction tests

Tests are designed *up front, before any implementation*. They live in two
places, with different shapes and different lifecycles:

- **Contract tests** live in `spec.md`. Black-box, behaviour-only — they
  define "done" for the feature. Any valid implementation must pass them.
  They are stable against *implementation* change; they evolve with
  *spec* (behavioural) change during the spec's living phase, and
  freeze when the spec freezes.
- **Construction tests** live in `plan.md`, attached to each step.
  Units, edge cases, property tests, fixtures — they guide the
  implementer through the build. They are *revisable* if one
  over-specifies an internal detail the plan changed.

Within a plan step, the **Tests** subsection comes *before* Approach.
Tests drive implementation, not the other way around.
Red-green-refactor: write the failing test, make it pass, refactor —
separate commits when the change is non-trivial.

The typical mix follows the test pyramid — roughly 80% fast unit /
construction tests, 15% integration, 5% end-to-end — a target shape,
not a quota. For Agentic Inquiry, storage-layer changes must be verified
against a real database (LanceDB and SQLite on disk); do not mock the
database.

---

## 5. Current-state docs — `architecture/`, `product/`, `guides/`

The *living* layer. Each directory serves a different audience.

### 5a. `docs/architecture/` — for contributors

How the code is *currently* organized. Not why (ADRs); not what we want
(RFCs); what is. Agentic Inquiry already has `architecture/overview.md`
plus per-subsystem files (`search.md`, `indexing.md`,
`storage-adapters.md`, etc.). One file per non-trivial subsystem; link
to the ADR or RFC that explains *why*.

### 5b. `docs/product/` — for maintainers

What the product is currently doing. Holds `roadmap.md` (direction for
the next 2–4 quarters; reviewed quarterly) and `changelog.md`
([Keep a Changelog](https://keepachangelog.com/) format, updated in
the same PR as any user-visible change). The repo-root `CHANGELOG.md`
serves this role today.

### 5c. `docs/guides/` — for users

Diátaxis-organized user docs. Four kinds of content, each in its own
subdirectory:

- `tutorials/` — *learning-oriented.* Lessons.
- `how-to/` — *task-oriented.* Recipes.
- `reference/` — *information-oriented.* Authoritative interface docs.
- `explanation/` — *understanding-oriented.* Why something works.

Each piece belongs in exactly one bucket. When a tutorial wants to
explain *why*, link out to an explanation page; when a how-to wants
every option, link out to reference. Agentic Inquiry's current backend,
MCP, and customization docs live under sibling directories of
`docs/` (`backends/`, `mcp/`, `customization/`); migration into `guides/` is incremental - when a
page is touched, move it.

---

## Commits

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`,
`ci`, `chore`.
**Scope:** the package or area touched (`storage`, `search`, `mcp`,
`docs`, etc.).

**Footer references:** if the commit implements a spec, end with
`Spec: docs/specs/<feature>/spec.md`. If it follows from an ADR or
RFC, cite it the same way.

To link an issue, use a `Closes: #<n>` footer on the commit that
resolves it, or `Refs: #<n>` on commits that contribute without closing
it. Issue footers are **encouraged but optional**, and apply to any
commit type — including `chore` and `docs`. They are not required: the
linking PR's `Closes #<n>` is sufficient for traceability and auto-close.

---

## Pull requests

A PR description answers four questions in this order:

1. **What does this change?** (Two sentences in plain English.)
2. **Why?** (Link to the spec, ADR, RFC, or issue.)
3. **How do I verify it?** (Specific commands, manual steps, or
   screenshots.)
4. **What did you not change that you considered?** (The dog that
   didn't bark.)

Aim for under ~100 lines of diff. PRs over ~400 lines should be split
unless the change is atomic (generated file, single rename across many
call-sites). CI must be green; specs must match implementation;
user-visible changes must be noted in `CHANGELOG.md`.

---

## How we do non-trivial work

For anything beyond a one-line edit, follow the **plan → execute →
verify → review → iterate** loop. The mechanics live in the
[`work-loop`](../.claude/skills/work-loop/SKILL.md) skill; this section
is the *why*.

**Why a loop, not a single pass.** LLM self-assessment is unreliable:
agents declare victory when they *feel* done. Mechanical gates (lint,
typecheck, tests) plus an adversarial review pass replace "feel" with
verifiable termination.

**Why iterate, not retry-from-scratch.** Most loops converge: gates
fail, review surfaces a finding, the next pass fixes it.
Restart-from-scratch loses the planning context. We do that only when
fresh context is the *point* — which is what the Ralph harness in
[`tools/RALPH.md`](../tools/RALPH.md) is for.

**Why a hard iteration cap.** Without one, you're hoping. The cap
lives as data in `state.json` (see below) and is enforced by
[`tools/check-done.py`](../tools/check-done.py); if you hit it, the
task is bigger than you thought — stop, re-plan, or split.

**Why capture learnings.** A loop that finishes without updating
*some* doc, skill, or note has wasted what it learned. The work-loop
skill enumerates where each kind of learning belongs.

### Work-loop state

A spec-driven loop carries session-scoped state — iteration count,
token budget, last reviewer findings. Putting that in prose leaves it
un-enforceable; putting it on disk as data lets a tiny script gate
each phase. That script is
[`tools/check-done.py`](../tools/check-done.py); the data lives at
`docs/specs/<feature>/state.json`, schema at
[`docs/_templates/state.json`](_templates/state.json).

**Fields:**

| Field | Meaning |
|---|---|
| `feature` | spec slug (informational) |
| `iteration_count` / `max_iterations` | how many in-session loops have run / hard cap |
| `token_budget_used_pct` / `token_budget_cap_pct` | session token budget — **advisory in Phase 1** |
| `consecutive_same_error_count` / `consecutive_same_error_threshold` | gate-error stuck-loop counter / cap; **advisory in Phase 1** |
| `plan_review_status` | `pending` until the spec-mode adversarial review clears, then `approved`. Enforced as a gate on **all phases** |
| `last_commit_sha` | latest commit produced by the loop (informational; advisory in Phase 1) |
| `finding_fingerprints` / `previous_finding_fingerprints` | hashes of reviewer findings, rotated each REVIEW iteration; used to detect circling |
| `worktrees` | one entry per `implementer` subagent in the current session's supervisor pass: `{task_id, branch, path, status, report_path}` — see [§ Supervisor mode](#supervisor-mode) |

**Exit contract.** `check-done.py` exits 0 when the phase is satisfied
and non-zero when it isn't, with a one-line reason on stderr. The
SKILL's PLAN-init step calls the script with `--phase plan` *expecting*
exit 1 with `plan not approved`; that's the cue to run the spec-mode
reviewer. Any other non-zero exit terminates the loop.

**Lifecycle.** `state.json` is per-session scratch, not history. The
file is gitignored (`docs/specs/**/state.json`); the SKILL
initializes it from the template at PLAN start. A fresh session
re-initializes — intentionally.

**Atomic writes.** The orchestrator updates `state.json`
mid-iteration; `check-done.py` reads it between phases. Always write
atomically (tmp-file + `os.replace`, or shell `mv`) so a partial
write doesn't present as malformed JSON.

### Model selection

Every subagent file declares `model:` in its frontmatter explicitly.
The [`lint-agent-artifacts.sh`](../tools/lint-agent-artifacts.sh)
linter enforces this. Reasoning:

| Subagent | Model | Why |
|---|---|---|
| `adversarial-reviewer` | `opus` | Adversarial judgment; stakes are correctness. Output drives a hard gate. |
| `security-reviewer` | `opus` | Threat-model reasoning; stakes are security. |
| `quality-engineer` | `opus` | Maintenance lens; spec-level coverage pass. |
| `implementer` | `sonnet` | One narrow plan task per dispatch; gates rerun in the primary; cost beats capability here. |

Changing a subagent's model is a behaviour change, not a config tweak
— note it in the PR with a one-line justification.

### Supervisor mode

When a plan has multiple tasks declaring `Depends on: none`, the
work-loop enters **supervisor mode**: one primary orchestrator
dispatches `implementer` subagents in parallel, each working in its
own git worktree, then merges the results back and runs gates in the
primary. Mechanics live in the
[`work-loop` skill](../.claude/skills/work-loop/SKILL.md) §EXECUTE.

**Worktrees as the coordination primitive.** Each independent task
gets `.worktrees/<task-id>/` checked out on its own branch
(`<base-branch>-<task-id>`). The directory is gitignored; branches
live in git history for traceability.

**Merge discipline.** The supervisor merges with `git merge --no-ff
<base>-<task-id>` into the primary branch, sequentially in task-id
order. If a sequential merge conflicts, the tasks weren't actually
independent — surface that as a PLAN-level escalation, not a `git
mergetool` session.

**Gates run in the primary, not the worktree.** Each implementer
runs gates inside its worktree and reports the result, but those
results are advisory. The supervisor reruns lint / typecheck / tests
against the merged state.

**Escalating implementer failures.** If an implementer reports
`blocked` or `failed`, the supervisor surfaces the failure list to a
human and returns to PLAN. It does not redispatch the same
implementer on the same task.

### Knowledge base

The repo accumulates practitioner-level lessons in
[`docs/knowledge/patterns.jsonl`](knowledge/patterns.jsonl):
patterns ("when you touch X, also remember Y"), gotchas, and
antipatterns. One JSON object per line, scoped to a file glob. The
schema and curation conventions live in
[`docs/knowledge/README.md`](knowledge/README.md).

**Why a separate bucket.** ADRs answer *why we decided X*;
`architecture/` describes *current structure*; `guides/` is for
*users*. Knowledge entries are practitioner residue — the things you
learn by building, not by deciding or documenting. They earn a home
because they're scoped to globs and append-only (a lesson that stops
being true gets a *new* entry citing the old one).

**How agents see it.**
[`tools/hooks/session-start.sh`](../tools/hooks/session-start.sh)
reads the file at session open and prints matching entries. The
work-loop SKILL's `Capture what was learned` section points
contributors here for pattern / gotcha / antipattern-shaped
learnings.

### Enforcement (the triplet)

| Layer | Mechanism | What it gates |
|---|---|---|
| Caps | [`tools/check-done.py`](../tools/check-done.py) | Iteration cap, token budget, plan approval, fingerprint stasis. |
| Artifacts | [`tools/lint-agents-md.sh`](../tools/lint-agents-md.sh), [`tools/lint-agent-artifacts.sh`](../tools/lint-agent-artifacts.sh) | Shape, manifest, and content hygiene for every `.claude/`, `AGENTS.md`, and `docs/knowledge/` artifact. |
| Aggregation | [`tools/hooks/pre-pr.sh`](../tools/hooks/pre-pr.sh) | Runs caps + artifact linters together before a PR opens. |

The triplet is **Shift Left**: catch problems as early as possible,
locally before CI, at PLAN before EXECUTE. The pre-EXECUTE
adversarial review is the same pattern at a different layer.

### Skills

Workflows agents invoke for repeating tasks, under
`.claude/skills/<name>/SKILL.md`. Add a skill when you've done the
same multi-step thing three times — speculative skills bloat context
and degrade adherence.

Currently installed: `work-loop`, `new-spec`, `bug-fix`, `new-adr`,
`new-rfc`. The initial set was seeded from the `agent-ready-repo`
template (Path C retrofit) — the rule-of-three governs *additions*
from here, not the initial bootstrap. The remaining template skills
(`new-package`, `update-conventions`) are intentionally not installed;
add them only when the rule-of-three fires.

---

## Common rationalizations

| The lie | The rebuttal |
| --- | --- |
| "We'll update the spec after the PR." | Spec drift is a bug, not follow-up work — update spec and code in the same PR. |
| "I'll verify this manually, just this once." | Verification mode is declared in the plan task, not improvised at the keyboard. If manual QA is the right mode, write it down. |
| "I can fix this while I'm here." | Out-of-scope changes need a separate PR or an explicit note in the plan. Scope creep is the most common cause of failed adversarial review. |
| "This decision doesn't need an ADR — it's obvious." | If you're making it, it isn't obvious to the next person. Writing an ADR now costs less than re-litigating in six months. |

---

## When this file is wrong

If a convention here is causing friction, **say so in an RFC**. Don't
quietly deviate. The whole point of writing this down is that the
rules are visible and contestable.
