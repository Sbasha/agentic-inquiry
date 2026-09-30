# Plan: RFC-0004 claims harness

## Approach

One new orchestration module, `evals/claims.py`, runs a claim end to end and writes its results; it reuses the Level A arms and collection (`evals/arms.py`, `evals/run.py`), the LLM helpers (`evals/answer.py`), the agent runner (`evals/agent.py`) and the competitor worker. `evals/fresh.py` mines and loads the C3 tasks.

The `claude -p` overhead correction applies to calls that stand in for a tool's own API call (shim-routed ingestion, answering, judging). C3 agent runs are Claude Code sessions, so their full usage is their cost.

## Tasks

### T1: C3 task mining
Depends on: none
Mode: TDD for the filters; goal-based for the mined list.
Tests: `tests/evals/test_fresh.py` - `is_test_path` cases; `candidate` rejects two closing issues, an issue created before the window, short text, zero or six non-test files, no gold function.
Done when: `evals/tasks/fresh-2026.jsonl` is committed with its per-repository counts.

### T2: LLM accounting
Depends on: none
Mode: TDD.
Tests: `tests/evals/test_claims.py` - dollars from tokens and the price table; overhead subtraction floors at zero; the shim's per-prefix counters sum calls, tokens and API seconds.
Done when: every `claude -p` record carries `api_ms`, and the shim serves `/<prefix>/stats`.

### T3: Statistics
Depends on: none
Mode: TDD.
Tests: exact McNemar p on hand-computed discordant counts (including zero discordant pairs); Holm on three p-values; ratio bootstrap is deterministic under the seed.

### T4: C2
Depends on: T2, T3.
Mode: TDD for the correctness rule (a rendered line inside a changed function; a Graphify location inside it; neither); goal-based for `claim c2 --split dev`.

### T5: Competitor methods for C1
Depends on: T2
Mode: TDD for message and document building (mem0 pairs with dates; Cognee JSON-list turn pairs); goal-based for one dev question per tool.
Done when: a build records its health counts and refuses a build with no stored items or a failed session.

### T6: C1
Depends on: T2, T3, T5.
Mode: TDD for the proportional per-type sample and the per-type judge prompt selection; goal-based for `claim c1 --split dev`.

### T7: C3
Depends on: T1, T2, T3.
Mode: TDD for the correctness rule on cited locations; goal-based for `claim c3 --split dev` on SWE-bench dev tasks.

### T8: Ledger and claims report
Depends on: T2, T3
Mode: TDD for start and end entries and the dirty-tree guard; goal-based for `claims-report`.

### T10: Retire RFC-0003 test paths
Depends on: none
Mode: goal-based. RFC-0004 supersedes RFC-0003 for test runs: `run`, `answer` and `agent` refuse `--split test`, and the Level B competitor arms and H6 (OpenKB, Graphify's text path) are removed.
Done when: each of those commands exits with a message naming `claim` on `--split test`.

### T9: Test runs
Depends on: T1 to T8, reviewed.
Mode: goal-based. C2, then C1, then C3, each once; the ledger and results committed after each; the report published.

## Risks

- **Subscription rate limits** on about 80,000 ingestion calls for C1. Mitigation: the shim cache makes an interrupted build resumable; builds run at a fixed concurrency.
- **Index time for C3's 100 repository snapshots.** Mitigation: the content-hash embedding cache shares work across snapshots of one repository; builds start as soon as the task list is committed.
