## Termination

Apply the linked [stop conditions](delivery-contract-lifecycle.md); an intermediate clean unit, retry cap, or stasis never completes accepted intent.

## Finish checklist

Refuse to declare done until every item is true. Light mode's checklist deltas are in [`references/light-mode.md`](light-mode.md).

- [ ] GATES were clean (lint, typecheck, tests).
- [ ] **If the change ships something a user invokes** (CLI, library API, agent, UI): the real built artifact was exercised end-to-end through its documented happy path and the observed result recorded - a passing unit gate alone does not satisfy this. Trust the running artifact, not the build exit code.
- [ ] **Full mode:** every warranted reviewer (`adversarial-reviewer` always; `security-reviewer` on security-boundary diffs; `quality-engineer` per the REVIEW trigger; `experience-reviewer` on user-facing diffs; `frontend-reviewer` on HTML/CSS/JS primary-output diffs; `design-reviewer` when an architect-pack integration activated it) has no unresolved Blocker or Concern or, only when non-mandatory, is a named skip. A missing, invalid, or named-skipped mandatory reviewer blocks. Silent skips are not allowed.
- [ ] **Light mode:** the reviewer obligations in [`references/light-mode.md`](light-mode.md) are satisfied.
- [ ] Whole-spec `quality-engineer` pass (final loop of a multi-loop spec only): same select-or-note rule.
- [ ] The resolve-vs-surface disposition record exists: every REVIEW Blocker and Concern is resolved, and every unacted Nit is deferred with its citation.
- [ ] One `json review-verdict.v1` record was emitted per [`references/review-verdict-record.md`](review-verdict-record.md); in full mode byte-identical to the PR `Review verdict` block; no score altered state.
- [ ] **Implementation completion only (code mode and direct-light):** the
  completion evidence handoff exists, including durable-output status
  and stable evidence references; tests and implementation evidence are
  capability proof, not product intent, rationale, ownership, or authority, and
  close-work remains separate.
- [ ] **Direct-light only:** the session handoff states the requested outcome, implemented scope, verification evidence, non-goals and independently scoped follow-ons, and any discovered reason future work should use a durable spec.
- [ ] The original accepted intent is complete, or its owner explicitly narrowed
  or waived the remaining matching work. A merged PR, retry cap, or review
  stasis alone is not completion; excluded work needs no backlog entry unless
  the owner explicitly requested capture through `work-intake`.
- [ ] `git status` shows no uncommitted or untracked files (except gitignored scratch).
- [ ] **When a persisted spec exists, doc-drift invariants hold**: spec `**Status:**` set to `Shipped` (code mode) or `Approved` (spec-plan mode, which ends after plan approval without proceeding to EXECUTE); **full mode:** also `plan.md` `**Status:**` `Done` - in `spec.md` use spec vocabulary only (`Draft | Approved | Implementing | Shipped | Archived`; plan vocabulary `Drafting/Executing/Done` there is invalid and will fail `lint-spec-status.py`); every final accepted AC is `[x]`; any separable follow-on is outside the AC list with its own owner/artifact reference; historical `(deferred: <slug>)` anchors still resolve in `[backlog].open`; intra-repo references the change touches resolve. Run `python '<skill-dir>/scripts/lint-spec-status.py' --root .` where Python is available. Per-spec invariants cover the specs changed against the base ref; the dangling-reference and deferral-anchor invariants always cover every spec. Add `--all` for the exhaustive per-spec sweep - use it when a base ref will not resolve, or in a gate. When no spec exists, do not run the spec-status lint.
- [ ] Conventional commit format used; no force-push to shared branches.
- [ ] Learnings captured per [Capture learnings](../SKILL.md#capture-learnings).
- [ ] **Review boundaries verified.** Each intended PR or layer has a coherent
  behavior and verification scope. Mechanical transformations identify their
  source, invariant, command, reproducibility check and rollback. Dependency
  boundaries explain any split; volume alone does not require delegation.
- [ ] PR opened (or merged directly) with the four-question template filled in.

## FIX

1. Read the sustained finding from the adjudication artifact carefully; fix the established defect, not the symptom. Never route a refuted or indeterminate source finding into FIX.
2. Split by shape: if diagnosing the failure hands you a ≤30-line fix (a missing flag, a wrong base URL, a leaked interval), implement it yourself, test it, commit it - diagnosis is the fix. If the fix is a well-specced multi-file unit, write a complete brief and dispatch it. Orchestrator context is the most expensive resource; spend it on diagnosis and judgment, not bulk edits.
3. Re-run GATES. Every fix gets the same adversarial verification as worker output - run the suite it could plausibly break. When CI disagrees with your machine, believe CI and reproduce in a clean clone before concluding anything.
4. **Full mode:** after any applied sustained REVIEW finding, re-run the reviewer or reviewer set that produced it; accept a footer-free `clean` classification directly and adjudicate every other report. Continue until no unresolved Blocker or Concern remains.
5. **Light mode:** return to GATES, then re-review under the rounds rule in [`references/light-mode.md`](light-mode.md).

## Capture learnings

Before the PR is opened: *What would have made this work materially better -
more correct, complete, reliable, recoverable, secure, privacy-preserving,
deterministic, reproducible, operable, maintainable, reviewable, efficient, or
independent of hidden context?*

Speed is one useful signal, not the objective. Capture a learning when knowing
it would materially change a future approach along one or more of those quality
attributes.

Write the **generalizable lesson**, not the incident report. Strip PR details; write what you'd tell a new team member. If the only thing you can write is "in PR#42 we had to…", it's not ready.

- **Review scratch notes** from this session's DECIDE passes. For each:
  generalisable beyond this PR and would have changed the approach → route it
  through the `project-knowledge` public seam; otherwise discard it.

  Use semantic-gate triage before writing anything. Route or discard normative
  material first, then invoke the public `project-knowledge` producer profile.
  It owns receipts and terminal-gate distillation; unresolved observations remain
  pending. Any knowledge diff returns through the next verification and review
  barrier before commit. If unavailable, record `project-knowledge unavailable`;
  create no fallback file.
- "Grepped for `<thing>` repeatedly" → pointer in `docs/architecture/<subsystem>.md`.
- "The test command for this package is unusual" → add it to the package's `AGENTS.md`.
- "Made the same wrong assumption twice" → knowledge-base-shaped: first bullet's routing. Project-conventions context: relevant `AGENTS.md`. Vocabulary issue: `docs/guides/reference/` glossary.
- "This workflow is the third time I've done it" → propose it as a new skill.

