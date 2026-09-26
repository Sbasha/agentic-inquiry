# Comparisons and judges

Use a project-owned evaluation definition and preserve raw observations. A minimal comparison identifies the case population, stable case IDs, baseline/candidate references, execution settings, expected outcomes, evaluator and rule for incomplete results. Preserve existing formats that express these facts.

For prompt work, keep development examples separate from held-out evaluation cases. Do not revise expected answers after seeing candidate failures without identifying a new evaluation version and rerunning the comparable baseline. If retrieved context or tools differ, state that the evaluated system includes those changes.

For repeated runs, retain the run-to-case mapping and report variation within a case separately from variation across cases. Repeats of one task are correlated evidence; increasing the repeat count does not create additional independent customer tasks. Select an uncertainty method suited to the metric and sampling unit. Do not apply a binomial interval to a weighted rubric score or present overlapping marginal intervals as a calibrated paired regression test.

LLM judges need a versioned prompt/rubric, recorded model settings, parse validation and a route for unjudgeable outputs. Calibrate against independently reviewed examples, including false positives and critical failures. For pairwise judging, conceal candidate labels when feasible and inspect order effects. A judge's explanation is useful diagnostic evidence, not proof that its score is correct.

Keep the comparison honest:

- Name task counts before filtering and give reasons for exclusions.
- Show paired comparable outcomes separately from cases missing one side.
- Distinguish evaluator failure from product failure and keep both visible.
- Show critical-constraint breaches individually even when an aggregate improves.
- Preserve actual cost and elapsed time; unknown values are unavailable, not zero.
- Limit conclusions to the tested tasks, environments and configurations.

For CI, read native terminal status and assertion outcomes as well as process exit. A command can finish successfully while assertions fail or a remote run remains in progress. Emit pass only when the project's actual acceptance rule is satisfied by complete evidence; use the existing runner's supported status/exit contract rather than inventing flags.
