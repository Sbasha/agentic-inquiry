# Outcome measures

PLAN names the requested observable result, independent acceptance evidence, regression and failure checks, concrete maintainability risks and available resource limits in the existing plan or direct-light record. EXECUTE implements those criteria; GATES and independent REVIEW assess the evidence. DECIDE reports the accepted outcome before efficiency. These measures describe work when telemetry exists; they require no new ledger, cost service or approval process.

## Quality and completion

A verified completion requires external or independent acceptance of the requested behavior with the required regression and protection checks. An agent's completion statement, small diff or passing JSON is insufficient. Report acceptance rate, regressions and independently substantiated defects separately. Assess maintainability against the change's concrete risks, not code size alone. Self-review does not become independent verification.

## Consumption and attribution

Tokens per verified completion = all observed attempted tokens in the measured cohort / independently verified completions. Include failed attempts, reviewers, retries, repeated context and compactions. Keep input, cached input and output separate when available; cached input is a subset of input and is not added twice.

Dollars per verified completion = all attributable provider cost across those attempts / independently verified completions. Show raw totals and denominators. Separate setup, indexing and other shared overhead, with an all-in view when attribution is available. Never silently remove failed work or reuse another cohort's cost as this cohort's measurement.

Zero verified completions means no finite per-completion ratio. Missing usage means unknown cost, not zero. Preserve known subtotals without presenting them as complete totals. Distinguish completed, failed, unavailable and unrun cases.

Report wall-clock time, tool calls, retries, compactions and human interventions when observed; otherwise label them unknown. Parallel worker durations do not sum to wall-clock time. State the observation boundary so startup and recovery are neither silently omitted nor counted twice.

## Comparisons

Use comparable workloads and independently assessed quality. Higher quality with lower total consumption supports the delivery hypothesis. Unchanged quality with lower consumption is an efficiency improvement; an improvement in one with deterioration in the other is a tradeoff. A small pilot cannot establish statistical equivalence or general superiority. Do not combine quality and cost into an arbitrary weighted score. Static instruction-byte reduction establishes a smaller loading surface, not measured API savings.
