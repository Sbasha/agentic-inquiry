---
name: to-tickets
disable-model-invocation: true
description: "Turn an approved plan or delivery breakdown into dependency-aware, independently verifiable tickets in the project's existing tracker. Use for concrete ticket preparation or explicitly authorized publication. Use decompose-intent to shape an unresolved intent; do not invent implementation requirements or launch the work."
metadata:
  source: https://github.com/mattpocock/skills
---

# To Tickets

Preserve the supplied plan's outcomes, constraints and acceptance criteria. Suggested implementation detail remains optional unless its owning authority adopted it. Existing briefs and delivery contracts remain authoritative; tracker tickets are their requested projection, not replacement sources. Drafting tickets alone does not authorize publication.


Break a plan, spec, or conversation into **tickets** - tracer-bullet vertical slices, each declaring the tickets that **block** it.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes a reference (a spec path, an issue number or URL) as an argument, fetch it and read its full body and comments.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Ticket titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching. Look for opportunities to prefactor the code to make the implementation easier. "Make the change easy, then make the easy change."

### 3. Draft vertical slices

Break the plan into **tracer bullet** tickets. Each ticket is a thin vertical slice that cuts through ALL integration layers end-to-end, NOT a horizontal slice of one layer.

Slices may be 'HITL' or 'AFK'. HITL slices require human interaction, such as an architectural decision or a design review. AFK slices can be implemented and merged without human interaction. Prefer AFK over HITL where possible.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Each slice is sized to fit in a single fresh context window
- Prefer many thin slices over few thick ones
- Any prefactoring should be done first
</vertical-slice-rules>

Give each ticket its **blocking edges** - the other tickets that must complete before it can start. A ticket with no blockers can start immediately.

#### Wide refactors are the exception to vertical slicing

A **wide refactor** is one mechanical change - rename a column, retype a shared symbol - whose **blast radius** fans across the whole codebase, so a single edit breaks thousands of call sites at once and no vertical slice can land green. Don't force it into a tracer bullet; sequence it as **expand-contract**:

1. **Expand**: add the new form beside the old so nothing breaks.
2. **Migrate**: move the call sites over in batches sized by blast radius (per package, per directory), each batch its own ticket blocked by the expand. CI stays green batch to batch because the old form still exists.
3. **Contract**: delete the old form once no caller remains, in a ticket blocked by every migrate batch.

When even the batches can't stay green alone, keep the sequence but let them share an integration branch that all block a final integrate-and-verify ticket - green is promised only there.

### 4. Present the concrete breakdown

Present the proposed breakdown as a numbered list. For each ticket, show:

- **Title**: short descriptive name
- **Type**: HITL / AFK
- **Blocked by**: which other tickets (if any) must complete first
- **What it delivers**: the end-to-end behavior this ticket makes work
- **User stories covered**: which user stories this addresses (if the source material has them)

Honor any existing authorization to create the requested tickets. If publishing is not authorized, ask one concise approval question after presenting the concrete breakdown.
Use deeper interrogation only when the plan is ambiguous, high-consequence, or the blocking edges cannot be inferred safely.
Iterate only on the specific requested changes.

### 5. Publish the tickets to the issue tracker

For each authorized ticket, use the project's existing issue tracker and task conventions. Use the ticket body template below unless a native template applies. Apply only labels that the target project defines.

Publish tickets in dependency order (blockers first) so you can reference real issue identifiers in the "Blocked by" field. Use the platform's native blocking / sub-issue relationship where it has one; otherwise set each ticket's "Blocked by" to the blocking issues.

<ticket-template>
## Parent

A reference to the parent issue on the issue tracker (if the source was an existing issue, otherwise omit this section).

## What to build

The end-to-end behavior this ticket makes work, from the user's perspective - not layer-by-layer implementation.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Blocked by

- A reference to each blocking ticket, or "None - can start immediately".

</ticket-template>

Avoid specific file paths or code snippets - they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it and note briefly that it came from a prototype. Trim to the decision-rich parts - not a working demo, just the important bits.

Do NOT close or modify any parent issue.

Return the created ticket identifiers and their dependencies. Creating tickets does not launch implementation or take over the project's execution owner.

---

## Issue tracker: GitHub

Use this section only when the current project uses GitHub issues. Otherwise use its native task system. Inspect the selected repository and available permissions before remote operations.

### Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use `--body-file` for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` - `gh` does this automatically when run inside a clone.

### When a skill says "publish to the issue tracker"

Create an issue in the project-selected tracker; use GitHub only when it is that tracker.

### When a skill says "fetch the relevant ticket"

Read it from the project-selected tracker; for GitHub, run `gh issue view <number> --comments`.
