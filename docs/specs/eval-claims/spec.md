# Spec: RFC-0004 claims harness (C1 memory, C2 code retrieval, C3 coding agent)

Mode: full (multi-feature, subprocess and network I/O, public claims)

- **Status:** Implementing
- **Owner:** Sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** RFC-0004, ADR-0006
- **Contract:** the results files and the claims report described below

> **Spec contract:** this document defines what "done" means. The implementing
> PR must match this spec, or update it. Verification must be derivable from it.

## Objective

Run the three RFC-0004 claims once each and report, per claim, whether `inquiry` is significantly ahead of each other arm, together with the time and cost of every arm. The harness extends `evals/` (RFC-0003) rather than replacing it.

## Boundaries

### Always do
- Take samples, arms, prompts, metrics and tests exactly from RFC-0004; a change needs an RFC amendment committed before the affected run.
- Count every failure (ingest, retrieve, answer, judge, agent) as a wrong result for that item.
- Log every LLM call any arm makes, with its model, token counts and API duration.

### Ask first
- Any metered API call.
- Rerunning a claim's test run.

### Never do
- Tune `inquiry` or any adapter on a test item.
- Start a test run with uncommitted code, ledger or results.

## Acceptance Criteria

- [ ] AC1 `python -m evals mine-fresh` applies the RFC-0004 C3 rules and caps, writes `evals/tasks/fresh-2026.jsonl`, and refuses to overwrite it; the `fresh` suite loads it with every task on the test split.
- [ ] AC2 `python -m evals claim c1|c2|c3 --split dev|test` runs one claim's arms on its registered sample (for `dev`, a small sample from the dev split) and writes `evals/results/claims/<claim>-<split>-<utc>-<sha8>.json` with per-item rows (arm, item, correct, time, tokens, dollars) and per-arm summaries.
- [ ] AC3 C1 arms: `inquiry` (2,000-token context), `full` (every session in date order), `mem0` and `cognee` (RFC-0004 methods), all answered by `claude-haiku-4-5-20251001` with one answer prompt that includes the question date, and judged by `claude-sonnet-5` with LongMemEval's per-type prompts; a second judge (Ollama `qwen2.5:14b-instruct`) labels every answer.
- [ ] AC4 C2 arms `inquiry` and `graphify` score each task correct when a changed function has a rendered line, or a Graphify location, inside it within 2,000 tokens.
- [ ] AC5 C3 arms `floor`, `inquiry` and `graphify` run `claude -p --model claude-sonnet-5` with at most 14 turns and each tool's published agent instructions; a run is correct when one of its first five cited locations falls inside a changed function; tool-call counts are recorded.
- [ ] AC6 Each arm's setup (index or ingest) records wall-clock seconds, LLM calls, input and output tokens, API seconds and dollars; each item records the same for its query and its answer or agent run. Dollars use the RFC-0004 prices; calls through `claude -p` subtract the CLI's per-call overhead measured once per run on an empty prompt.
- [ ] AC7 Each comparison reports the paired counts, the exact two-sided McNemar p-value, the Holm-adjusted p-value within the claim, and paired ratios of time and dollars per item with 95% bootstrap intervals.
- [ ] AC8 A test run appends a `start` ledger entry before computing and an `end` entry with the results file's sha256; it refuses to start on a tree with any uncommitted or untracked change.
- [ ] AC9 `python -m evals claims-report` prints, per claim and arm, accuracy, time and cost per correct answer, and the verdict against each arm.

## Testing Strategy

- **TDD:** C3 mining filters (`is_test_path`, text length, one closing issue), the McNemar test and Holm adjustment, the C2 and C3 correctness rules, cost accounting with overhead subtraction, the ledger start and end entries.
- **Goal-based:** `mine-fresh` output counts per repository; `claim c1|c2|c3 --split dev` completes for every arm on a small dev sample.
- **Manual QA:** read one dev result per arm end to end, including one transcript per C3 arm.

## Assumptions

- The Claude subscription serves `claude-haiku-4-5-20251001` and `claude-sonnet-5` through `claude -p` for the whole run; rate limits slow runs but do not fail them after retries.
- Ollama serves `bge-m3` and `qwen2.5:14b-instruct` locally.
