---
name: ai-execute-tests
description: Orchestrate agent UAT test execution with subagent isolation. Use when running multiple ai tests or the full test suite.
context: fork
agent: general-purpose
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Agent, AskUserQuestion
---

# ai Execute Tests - Orchestrator

You coordinate test execution for agent UAT testing. You help users select tests, generate a unique test run ID, and **spawn subagents** to execute each test case in isolation.

**This is User Acceptance Testing (UAT)** - agents who will actually use these tools are evaluating them. The goal isn't just "does it work?" but "would I use this? Is it valuable?"

## When to Use

- "Run the ai agent tests"
- "Execute the full test suite"
- "Run TEST_02 through TEST_05"
- "Test all the ai tools"

## Critical: Subagent Architecture

**WHY SUBAGENTS ARE REQUIRED:**
- Each test produces 300-600+ lines of output
- Running 14 tests sequentially in one context causes context exhaustion
- Tests that ran in previous attempts: only 5-8 completed before overflow

**HOW IT WORKS:**
1. You (orchestrator) maintain a small context with only test plan + summaries
2. Each test runs in an isolated subagent that writes full details to files
3. Subagents return ONLY a brief JSON summary (not full reports)
4. You collect summaries and generate the final SUMMARY.md

```
ORCHESTRATOR (you)
    │
    ├── Spawn subagent: TEST_01 → writes files → returns JSON
    ├── Spawn subagent: TEST_02 → writes files → returns JSON
    └── ...
    │
    └── Generate SUMMARY.md from collected summaries
```

## Execution Flow

### Step 1: Detect Available Environments

**Before asking the user anything**, discover what test environments exist and their readiness.

#### 1a. Read the environment registry

```bash
cat .agentic-inquiry/env-registry.json 2>/dev/null
```

This returns all registered environments with `name`, `backend_type`, `config_path`, and `metadata`.

#### 1b. Check config files for test profiles

```bash
ls config/test-*.yaml 2>/dev/null
```

Maps to available test config profiles (e.g., `test-lancedb.yaml`).

#### 1d. Build environment status table

Combine findings into a status table:

| Environment | Backend | Status | Config |
|-------------|---------|--------|--------|
| ai | lancedb | ACTIVE | .agentic-inquiry/envs/ai/config.yaml |
| test-lancedb | lancedb | Available (no setup needed) | config/test-lancedb.yaml |

Status values:
- **ACTIVE** — registered as active and its directory exists
- **Available** — config exists
- **Not configured** — no config file found

### Step 2: Ask User (Environment + Test Selection)

Present the detected environments using `AskUserQuestion` with **two questions in one call**:

1. **Environment** — Show only environments that were detected, with status. Pre-select the active one as "(Recommended)". If only one environment exists, skip this question.
2. **Test scope** — Which tests to run (All, Smoke, Simple, Core subset, or specific IDs).


### Step 3: Load Use Cases

Read available tests from `tests/01-agents/USE_CASES.md`

Available tests (15 total):
| ID | Name | Time | Complexity |
|----|------|------|------------|
| 01 | Core Functionality | 10-15m | Simple (smoke test) |
| 02 | Onboarding | 20-30m | Simple |
| 03 | Feature Implementation | 30-45m | Medium |
| 04 | Bug Investigation | 25-40m | Medium |
| 05 | Major Refactoring | 45-60m | Complex |
| 06 | Knowledge Building | 20-30m | Simple |
| 07 | Code Review | 30-40m | Medium |
| 08 | Documentation Generation | 25-35m | Medium |
| 09 | Dependency Analysis | 30-40m | Medium |
| 10 | Performance Investigation | 35-50m | Complex |
| 11 | API Design | 40-55m | Complex |
| 12 | Code Graph | 30m | Medium |
| 13 | Document Graph | 20m | Simple |
| 14 | Semantic Graph | 20m | Simple |
| 15 | Executive Function | 20m | Medium |

### Step 4: Generate Test Run ID

```python
TEST_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
AGENT_NAME = "ai"
BASE_PATH = f"test_results/{AGENT_NAME}/{TEST_ID}/"
```

### Step 5: Pre-Execution Checks

```bash
# Check disk space (must have >10GB free)
df -h .

# Check ai data size (should be <5GB)
du -sh .agentic-inquiry/ 2>/dev/null || echo "No data dir yet"
```

If `.agentic-inquiry/` exceeds 5GB, run maintenance first.

### Step 6: Execute Tests (Subagent Pattern)

**IMPORTANT:** Do NOT run tests yourself. Spawn subagents for isolation.

#### Batching Strategy

| Batch | Tests | Run Mode |
|-------|-------|----------|
| 1 | TEST_01 (smoke) | Sequential first (must pass) |
| 2 | TEST_02, TEST_06, TEST_12, TEST_13 | Parallel (4) |
| 3 | TEST_03, TEST_04, TEST_07, TEST_14 | Parallel (4) |
| 4 | TEST_08, TEST_09 | Parallel (2) |
| 5 | TEST_05, TEST_10, TEST_11, TEST_15 | Parallel (4) |

#### For Each Test:

1. **Create directory:** `{BASE_PATH}/{use_case_slug}/`

2. **Spawn subagent** using Agent tool with `subagent_type: "ai-dev:functional-tester"`:
   ```
   You are a functional tester. Follow the ai-functional-tester skill protocol.

   Execute this test:
   - Test File: tests/01-agents/TEST_{XX}_{USE_CASE}.md
   - Test ID: {TEST_ID}
   - Agent Name: ai
   - Project ID: ai_test{XX}_{slug}_{TEST_ID}
   - Output Path: {BASE_PATH}/{use_case_slug}/
   - Environment: {env_name}
   - Config Path: {env_config_path}
   - Backend: {env_backend_type}

   Environment notes:
   - Use INQUIRY_CONFIG={env_config_path} when starting the MCP server
   - LanceDB needs no external dependencies

   Write full results to:
   - {output_path}/TEST_LOG.md
   - {output_path}/ISSUES_LOG.md
   - {output_path}/FINAL_REPORT.md

   After completing, return ONLY this JSON:
   {
     "test_id": "{TEST_ID}",
     "use_case": "{use_case_slug}",
     "status": "pass|partial|fail",
     "pass_rate": "X/Y",
     "critical_issues": 0,
     "high_issues": 0,
     "adoption_score": 8,
     "one_line": "Brief summary"
   }
   ```

3. **Collect JSON summary** (NOT full report content)

4. **Post-test:** Run maintenance if significant data created

### Step 7: Generate Summary

After all tests complete, create `{BASE_PATH}/SUMMARY.md`:

```markdown
# Test Run Summary

## Metadata
| Field | Value |
|-------|-------|
| **Test ID** | {test_id} |
| **Agent** | ai |
| **Environment** | {env_name} ({env_backend_type}) |
| **Config** | {env_config_path} |
| **Executed** | {timestamp} |
| **Duration** | {total_duration} |

## Results Overview

| Use Case | Status | Pass Rate | Issues | Adoption | Report |
|----------|--------|-----------|--------|----------|--------|
| Core | PASS | 8/8 | 0 | 5/5 | [Report](./core/FINAL_REPORT.md) |
| ... | ... | ... | ... | ... | ... |

## Overall Adoption Verdict

**[MUST-HAVE / RECOMMENDED / OPTIONAL / NOT RECOMMENDED]**

{2-3 sentence synthesis}

## Priority Actions
1. {Most critical fix needed}
2. {Second priority}
3. {Third priority}
```

## Lifecycle Management

### Between Tests
- Check disk space grew by <500MB
- If >500MB growth, consider running maintenance
- 30-second cooldown before next test

### Emergency Stop Conditions

**STOP all testing if:**
1. Disk space drops below 5GB free
2. Any test exceeds 60 minutes
3. Two consecutive tests fail completely
4. Debug logs show "Event queue full"

## CLI Alternative

For quick individual tests without subagent orchestration:
```bash
ai agent-test list        # List tests
ai agent-test 01          # Run smoke test
ai agent-test status      # Check results
```
