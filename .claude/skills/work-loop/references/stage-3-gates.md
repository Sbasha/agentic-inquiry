## Step 3. GATES

Check the requested observable behavior and its relevant regressions and failure cases. Preserve raw check outcomes and distinguish failed, unavailable and unrun checks. A reduction in instruction bytes, test count or elapsed time is not evidence that the requested quality was achieved.

Run in order; proceed only if each passes:

```
<lint command>      # style and basic correctness
<typecheck command> # type safety (if applicable)
<test command>      # behavior
```

Don't move past a failing gate by editing the gate. On failure → FIX.

**Full mode - after gates pass (wave routing):**
```
# More waves remain - fire wave-passed, advance cohort wave pointer, return to EXECUTE:
python '<skill-dir>/scripts/loop-engine.py' transition docs/specs/<feature> wave-passed \
    --wave-index <n>   # guard: wave check --expect more
python '<skill-dir>/scripts/loop-cohort.py' wave advance docs/specs/<feature> \
    --from-index <n> --expect-run-id <run_id>

# Final wave - fire gates-clean, proceed to REVIEW:
python '<skill-dir>/scripts/loop-engine.py' transition docs/specs/<feature> gates-clean
                   # guard: wave check --expect last
```

**Full mode - if gates fail:**
```
python '<skill-dir>/scripts/loop-engine.py' transition docs/specs/<feature> gates-failed
python '<skill-dir>/scripts/loop-cohort.py' record-attempt docs/specs/<feature> \
    --phase implement --cycle-id <run_id>:<seq> --expect-run-id <run_id>
```
Fix the failure and return to EXECUTE.

**Gate failure triage.** A failure in an unchanged file may come from changed dependencies, shared state or environment. Compare with recorded baseline evidence or reproduce against the actual starting candidate under comparable conditions before labelling it pre-existing. If comparison is unavailable, report the origin as unknown. Follow the project's hygiene requirements and repair authorized failures; a known earlier failure is not automatically a skip. Preserve existing work and record unresolved findings through the project's current task/evidence owner. See [`references/pre-flight-failures.md`](pre-flight-failures.md).

**Mechanical doc-drift check.** `scripts/lint-spec-status.py` (sibling to `loop-cohort.py`) checks: status vocabulary, every AC checked at a new ship transition, dangling references (warn-only), and historical deferral anchors in `[backlog].open`. A `(deferred: <slug>)` marker no longer makes a newly shipped AC valid. Run at the finish-time checklist (below). No-ops without Python. Do not wire into `pre-pr.py`.

