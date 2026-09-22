---
name: functional-tests
description: Run full UAT functional test suite - environment setup, indexing, and test execution. Use when running end-to-end agv validation.
argument-hint: "[all|TEST_XX] [--env local|gcp-prod|<name>] [--skip-index] [--batch N]"
context: fork
agent: general-purpose
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Agent, AskUserQuestion
---

# /agv-dev:functional-tests

End-to-end functional test workflow.

## Your Task

Run functional tests: **$ARGUMENTS** (default: all tests)

## Current State

- Environments: !`cat .agv/env-registry.json 2>/dev/null || echo "No environments"`
- Index status: !`uv run --env-file .env agv index status 2>/dev/null || echo "No index"`
- Disk space: !`df -h . | tail -1`
- agv data size: !`du -sh .agv/ 2>/dev/null || echo "No .agv/ dir"`

## Workflow

```
Phase 1: Environment       → Check/create environment
Phase 2: Index              → Ensure codebase is indexed
Phase 3: Execute            → Run tests via subagent orchestration
Phase 4: Report             → Generate summary
```

## Phase 1: Environment Setup

1. Check existing environments from live state above
2. If `--env` not specified, ask user which environment to use
3. Validate connectivity before proceeding

## Phase 2: Indexing

1. Check index status from live state above
2. Index if needed (unless `--skip-index`)
3. Verify entity count > 0

## Phase 3: Test Execution

### Test Batches

| Batch | Tests | Complexity |
|-------|-------|------------|
| 1 | TEST_01 (smoke) | Simple - must pass first |
| 2 | TEST_02, 06, 12, 13 | Simple - parallel |
| 3 | TEST_03, 04, 07, 14 | Medium - parallel |
| 4 | TEST_08, 09 | Medium - parallel |
| 5 | TEST_05, 10, 11, 15 | Complex - parallel |

For each test, spawn a background Agent following the `agv-functional-tester` skill.

### Emergency Stop Conditions

- Disk space drops below 5GB free
- Any test exceeds 60 minutes
- Two consecutive tests fail completely
- Smoke test (TEST_01) fails

## Phase 4: Report

Generate `SUMMARY.md` and spawn `test-reviewer` agent for executive summary.

## Examples

```bash
/agv-dev:functional-tests                          # Run everything
/agv-dev:functional-tests all --env gcp-prod       # Use specific env
/agv-dev:functional-tests TEST_01 --env local      # Just smoke test
/agv-dev:functional-tests --batch 2 --skip-index   # Batch 2 only
```
