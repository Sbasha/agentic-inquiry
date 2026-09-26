---
name: agent-evaluation
description: "Design or assess prompt, model, tool-policy and agent-runtime evaluations using a project's native runner. Use for baseline comparisons, task outcomes, cost, failures and judge calibration; reusable skill activation and Salesforce native test execution belong to their specialized owners."
metadata:
  source-state: authored
  native-qualification: not-run
---

# Agent evaluation

Start with the user's product decision and existing acceptance criteria. Identify the actual evaluator and raw result format. Define the task population, success observable, critical failures and comparison before running a candidate. Preserve the project's runner, datasets and result owner; do not invent a second evaluation pipeline for a report.

## Compare the intended behavior

- Freeze baseline and candidate identities, case IDs and inputs, tool availability, runtime/model parameters, context policy, environment, budgets and evaluator version. A comparison with multiple changed factors can measure the combined system but cannot attribute gains to one factor.
- Use the existing native runner for execution. Authorizing an assessment does not authorize paid model calls or external actions in cases. For unexecuted work, prepare the exact runner configuration and state the missing execution boundary.
- Keep raw outputs immutable. Derive assessment from recorded results with stable case mapping. Preserve failed, blocked, cancelled, incomplete, error and unknown outcomes in the denominator; do not silently discard them to improve a score.
- Separate task success, critical constraints, latency, cost and recovery. A weighted quality score must not hide a critical authorization failure. Report metric definitions and eligible counts alongside values.
- Read [comparisons and judges](references/comparisons.md) for repeated runs, LLM judges or statistical claims. Use explicit rubrics and calibrated examples; judge feedback is an observation, not task authority.

## Use the owning evaluator

When the artifact is a reusable skill, use the installed skill authoring/review capability for activation and instruction-quality evaluations. For a Salesforce Agentforce agent, use the selected native Agentforce testing owner for execution and its evaluation companion for assessment when present. This skill can help define the product hypothesis without substituting a generic result schema for native output.

Report the decision, comparison scope, observed success/failure counts, critical outcomes, measured cost/latency and evidence limitations. Separate source verification, runner completion and actual task success. Baseline promotion requires an explicit project decision; never replace baseline records because the latest run exists. Avoid ranking configurations on incomparable or absent evidence.
