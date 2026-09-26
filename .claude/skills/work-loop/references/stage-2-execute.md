## Step 2. EXECUTE

Implement against the outcome and verification criteria established at PLAN. Keep delegated briefs bounded to the intended behavior, execution root, acceptance checks and authoritative references. Delegate substantial independent work when its capability or assurance benefit warrants another context; do not delegate reference reading by default. Preserve required role independence and reviewer coverage. Record actual failed attempts and resource limitations when available, not an estimated success-only cost.

**When a spec exists, bump its status to `Implementing`** if currently `Draft` or `Approved`. Do this before writing any code. Direct-light has no spec status to write; its decision record must already be complete before the first implementation write.

**Sequential implementer dispatch.** In full mode, when `loop-cohort schedule`
emits a plan task and an `implementer` subagent is installed, dispatch it once per plan task, with one implementer at a time. The controller supplies the execution root and retains scheduling, state transitions, final gates, review, retry, and closeout.

Match discipline to verification mode:
- **TDD** - red-green-refactor; commit each step if non-trivial. After the full-mode engine enters `CODE-IMPLEMENTATION`, materialize the approved stub from `plan.md` unchanged in the repository test location, verify byte identity, prove the intended red, and then fill deferred assertions; don't rewrite from scratch. Direct-light writes its red test here because it has no durable plan stub.
- **Goal-based check** - write code, run the `Done when:` one-liner.
- **Visual / manual QA** - implement, exercise the real artifact end-to-end, record observed output.
- **infra/deploy** - implement, then drive the deploy and read real environment output (run apply, smoke probe, log pull, teardown; read their actual output - don't reason about what they'd say). Anti-pattern: a human pasting deploy errors back by hand. Craft in [`references/infra-verification.md`](infra-verification.md).

**Controlled full-mode amendment:** use the exact authority, evidence, recovery, reapproval, and rescheduling [contract](delivery-contract-lifecycle.md).

**Execution observations:** follow the [verification-ledger procedure](delivery-contract-lifecycle.md#verification-ledger).

**EXECUTE contract-grounding gate (universal - light and full).** Before generating code against a contract you do not hold, acquire it via [`contract-acquisition`](../../contract-acquisition/SKILL.md) (one gate, one skill - extend it, never fork a parallel skill). Two surfaces: **(1) infra** - CLI invocation, IaC resource, or app code on a managed runtime against an unfamiliar platform; **(2) software** - code against an unfamiliar internal framework or third-party library whose contract (versioned signature, deprecation, call-order constraint) the agent does not hold. Not for familiar code. Not every import.

**Frontend work.** When the FE trigger fired and `frontend-engineering` is installed, its craft rules govern HTML element selection, CSS tokens, accessibility patterns, and state completeness during EXECUTE; its GATES section defines verification commands. If absent, named skip applies.

**Scope:** implement the smallest coherent unit toward the goal. Note unrelated finds in `notes/` for later.

<!-- Bundled-fixes carve-out - canonical site. Mirrored by
     implementer.md (operating envelope) and adversarial-reviewer.md
     (scope check #4). Keep all three in sync. -->
**Bundled-fixes carve-out.** Ride-alongs are admitted by verifiability, not
locality. "The change" = the current plan task for the executor; the merged PR
diff for the reviewer. List each under a standalone `Bundled fixes:` section (append below standard
template content; do not modify the template). Tier 1 reproducible work must
state its command and produce a zero diff on re-run; it may span the
repository. Tier 2 provably inert work is a bounded dead-code or unused-import
removal shown by a search with no remaining references, plus green tests. Tier 3 hand-made work remains same-area, same-concern,
visibly smaller, and mechanical. All tiers fail closed on a design call or
behavior change. In supervisor mode, the dispatch brief must explicitly
authorize the carve-out.

**Simplify pass.** After this task's GATES are green, inspect changed code for unused branches, parameters and indirection that can be removed while preserving behavior, error handling and protection boundaries. Keep helpers that own a useful operation or isolate an actual variation; caller count alone does not justify inlining or extraction. Keep tests readable and rerun affected checks after a change. In Claude Code, `/simplify` is an optional aid, never a dependency.

**Scale with a tool** when a task spans many similar items: write a script with a resumable tracking file (`pending`/`done`/`failed`), iterate idempotently. Full playbook: [`references/scale-with-a-tool.md`](scale-with-a-tool.md).

For EXECUTE or REVIEW fan-out, supervisor waves, or Phase-1 sequencing, load the [Supervisor and fan-out procedure](supervisor-mode.md).


## Anti-patterns

- **Skipping PLAN because "the task is small."** If truly small, the plan is one sentence - write it anyway. The discipline is the point.
- **Declaring an empty declined-pattern register on a non-trivial task.** Something was always tempting. Empty means you weren't looking, not that there was nothing to find.
- **Skipping pre-EXECUTE review on a structural change.** The four structural triggers exist because over-engineering is most expensive to undo at that stage.
- **Writing code before deciding how it'll be verified.** Every task picks its verification mode during PLAN; TDD tasks have the test before the production code.
- **Editing the test until it passes.** Fix the code. If the test is wrong, fix it in a separate commit with justification.
- **Deferring a test because the code fails it.** Fix the code. "Flaky / out of scope / covered elsewhere" is how regressions ship. If genuinely wrong, separate commit with reason; if the code can't pass it this session, surface it, don't bury it.
- **Declaring victory because gates pass.** Gates are necessary, not sufficient; review catches what gates can't.
- **Declaring spec-complete from per-task gates.** Run `quality-engineer` against the whole spec before the final loop's DECIDE - per-task gates verify N contracts; this is the pass that verifies the integrated journey.
- **Running an unattended loop on a fresh task.** Do at least one in-session pass first to validate the approach.
- **Looping without capturing learnings.** Every loop that ends without updating some doc, skill, or note loses its lessons.
- **Grepping top-level keys in structured config.** `grep '^key' file.toml` matches `key` under every section, not just the top level - the same trap applies to YAML and JSON. Parse structured config with its native library rather than using line-pattern greps.
- **Judging a gate through `tail` or `grep`.** `<gate> | tail -2` reports the *filter's* exit code, not the gate's, and truncates away the per-item errors. Run every gate unfiltered and read its exit code.


## Fidelity ladder

When a task needs local-infra-equivalents, push up the ladder as high as a sub-5-minute local budget tolerates:

| Tier | Levels | Budget | Notes |
|------|--------|--------|-------|
| Always in-loop | L0 (in-memory fake), L1 (contract test) | < 1–10 s | Never skip |
| Inner-loop ceiling | L2 (Docker Compose), L3 (Testcontainers / LocalStack) | < 60 s – 3 min | Right ceiling for most services |
| Outer-loop territory | L4 (k8s namespace), L4+ (vCluster), L5 (cloud sandbox) | minutes+ | CI-managed |
| Human-supervised | L6 (staging / pre-prod) | n/a | Never autonomous-zone |

When a dependency can't be represented at L0–L3 within budget, defer the integration test to CI's ephemeral environment rather than cutting the test or inflating the budget. Full specification - per-level coverage, isolation gaps, the three-dimension outer-loop qualification test, and the provability classification - in the `operational-safety` skill's `fidelity-ladder` reference module.

Build-pack handoff: check installed build pack first; fall back to the reference module's technology examples if none is installed.

