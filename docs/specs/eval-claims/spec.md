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
- [ ] AC3 C1a arms `inquiry`, `full` (every session in date order), `dense`, `hybrid`, `mem0-raw` and `cognee-chunks` (RFC-0004), each retrieval arm cut at 2,000 tokens, all answered by `claude-haiku-4-5-20251001` with one answer prompt that includes the question date, and judged by `claude-sonnet-5` with LongMemEval's per-type prompts and scorer (correct when the reply contains "yes"); a check judge (Ollama `qwen2.5:14b-instruct`) labels at least 95% of answers or the test run fails, and its failures never score an item. No haystack text shows a dataset session ID.
- [ ] AC3b `python -m evals claim c1b` builds `inquiry`, `mem0` and `cognee` on the 7 registered histories and reports dollars, LLM API seconds, wall-clock seconds and LLM calls per million conversation tokens, with an exact sign test per tool on dollars and Holm across the two tools; a failed build counts against its tool.
- [ ] AC4 C2 arms `inquiry` and `graphify` (default `graphify update .` build) score each task correct when a changed function has a rendered line, or a Graphify location, inside it within 2,000 tokens; each task's time is one cold command-line query per tool.
- [ ] AC5 C3 arms `floor`, `inquiry` and `graphify` run `claude -p --model claude-sonnet-5` with at most 14 turns and each tool's published agent instructions, with every snapshot and index prepared before any agent runs; a run is correct when one of its first five cited `path:line` pairs, with absolute prefixes stripped, falls inside a changed function; a tool counts as used only when its own command ran without error, and other Bash commands are reported.
- [ ] AC6 Each item records wall-clock seconds, API seconds, tokens and dollars; in C1 these include its haystack's build. Dollars use the RFC-0004 prices; calls standing in for a tool's API subtract the CLI's per-call overhead, measured per call shape (plain, schema); C3 prices every model the session used.
- [ ] AC7 Each comparison reports the paired counts, the exact two-sided McNemar p-value, the Holm-adjusted p-value within the claim, paired ratios of time, tokens and dollars per item with 95% bootstrap intervals (null when the denominator is zero), and is invalid when either arm has more than 5% infrastructure failures.
- [ ] AC8 A test run refuses to start on a tree with any uncommitted or untracked change, or unless `inquiry`'s `code_hash` is the frozen value with no configuration override; it commits a `start` ledger entry before computing and appends an `end` entry with the results file's sha256.
- [ ] AC9 `python -m evals claims-report` prints every claim test run with its status (verified, aborted, start never committed, results changed) and, per claim and arm, accuracy, time and cost per correct answer, and the verdict against each arm.
- [ ] AC10 A memory-tool build is retried up to three times for infrastructure failures, then refused on any failed LLM call, any reply from another model, or more than 1% unparseable JSON replies; the shim logs every call.
- [ ] AC11 Each C1 run writes a seeded sample of 100 verdicts for human review.

## Testing Strategy

- **TDD:** C3 mining filters (`is_test_path`, text length, one closing issue), the McNemar test and Holm adjustment, the C2 and C3 correctness rules, cost accounting with overhead subtraction, the ledger start and end entries.
- **Goal-based:** `mine-fresh` output counts per repository; `claim c1|c2|c3 --split dev` completes for every arm on a small dev sample.
- **Manual QA:** read one dev result per arm end to end, including one transcript per C3 arm.

## Assumptions

- The Claude subscription serves `claude-haiku-4-5-20251001` and `claude-sonnet-5` through `claude -p` for the whole run; rate limits slow runs but do not fail them after retries.
- Ollama serves `bge-m3` and `qwen2.5:14b-instruct` locally.
