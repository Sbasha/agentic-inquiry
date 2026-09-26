## Step 5. DECIDE

Compare the delivered behavior with the PLAN outcome and independent evidence before reporting efficiency. For measured work, load [outcome measures](outcome-measures.md): retain all attempted tokens and attributable costs, including failed work, reviewers, retries and compactions. Report raw totals and verified completions; missing usage stays unknown and zero verified completions yields no finite per-completion ratio. State quality and consumption changes separately, including any tradeoff. Instruction-size reduction alone is not measured API savings.

Route each implementation or reviewer discovery by intent fit before deciding
whether it belongs in the current review unit. The work-loop interprets the
result; the reviewer keeps its narrow Blockers / Concerns / Nits contract:

| Intent fit | Session decision | Disposition |
| --- | --- | --- |
| Matches | Include now | Add it to the current plan or session. |
| Matches | Do not include | Stop incomplete unless the owner explicitly narrows or waives the intent. |
| Does not match | Include now | Obtain an explicit scope change; it then becomes accepted intent. |
| Does not match | Do not include | Exclude it with no durable follow-on by default. |
| Unclear | - | Ask the owner before acting. |

Only the owner may narrow or waive an accepted intent. A matching discovery
may share the current review unit only when the accepted contract authorizes it
and it qualifies under the bundled-fixes tiers. Otherwise, it is the next
independently reviewed unit in the same session: use the existing human-gate
`blocker-applied` return edge, then run GATES, REVIEW, and the human gate again.

**Execution-path check.** Before routing any finding to `apply`: confirm the fix reaches a live code path - grep for callers or trace the entry point. A guard that no caller exercises doesn't close a finding; a test that drives a mock seam instead of the real entry point doesn't count.

- **Blockers** → include the correction required by the accepted intent. Re-run
  GATES and REVIEW after each fix; use the next review unit when it cannot
  safely share this one.
- **Concerns** → apply now only when authorized by the accepted contract and
  bundled-fixes tiers; matching work that cannot share this unit moves to the next.
- **Nits** → never fix automatically. Defer an unacted Nit in `findings[]` with
  its citation and `status: deferred`; adjudicate only when the thread intends to
  mutate. Before any edit, promote `effective_severity` to at least Concern if
  its intended repair changes behavior, architecture, dependencies, or more than one file.
- **Excluded work** → acknowledge it in the PR's *What did you not change that
  you considered?* answer. Do not create a durable follow-on by default. If
  the owner explicitly asks to remember it, route the request through
  `work-intake`; do not create a `[backlog].open` entry or `(deferred: <slug>)`
  marker merely because this loop did not include the work.

**Scratch note.** After routing each finding: if it revealed a non-obvious trap - something that would have changed your approach - save a one-line note to your IDE's native scratch (Claude Code: memory file; Codex: `.context/` scratch). Format: `[kind] title - what triggered it`. These feed [Capture learnings](../SKILL.md#capture-learnings).

### Review verdict record

Emit exactly one fenced `json review-verdict.v1` block per review unit; full mode copies the pre-gate block byte-identical into the PR `Review verdict` section. States are `BLOCKED` → `CHANGES_REQUIRED` → `READY_WITH_RESIDUAL_RISK` → `READY`; no score is a gate; it never replaces the human merge decision. Load schema, state precedence, and residual-eligibility from [`references/review-verdict-record.md`](review-verdict-record.md).

**Completion handoff:** produce the bounded evidence [record](delivery-contract-lifecycle.md); it never performs closeout or grants authority.

When gates are green and the mode's review requirements are satisfied → proceed to [Finish checklist](../SKILL.md#finish-checklist).

