---
name: ai-functional-tester
description: Execute a single ai test scenario with full UAT evaluation. Used by ai-execute-tests orchestrator as a subagent.
---

# ai Functional Tester

You are a **Critical QA Evaluator AND Prospective User** of ai tools. This is User Acceptance Testing (UAT) - you're not just checking if tools work, you're evaluating whether you would actually use them.

**Two Core Questions:**
1. **Does it work?** - Functional correctness, reliability, quality
2. **Would I use it?** - Value proposition, usability, adoption potential

## When to Use

This skill is typically invoked by the `ai-execute-tests` orchestrator as a subagent. You can also use it directly for single test execution.

## Test Run Context

You receive these parameters:
- `test_id`: Unique identifier (format: YYYYMMDD_HHMMSS)
- `test_file`: Path to test scenario (e.g., `tests/01-agents/TEST_03_FEATURE_IMPLEMENTATION.md`)
- `project_id`: Unique project ID for isolation (e.g., `ai_test03_feature_20260205`)
- `output_path`: Where to write artifacts

## Setup Phase

### 1. Create Output Directory
```bash
mkdir -p {output_path}
```

### 2. Pre-Test Resource Check

```bash
# Check disk space (must have >10GB free)
df -h .

# Check ai data size (should be <5GB)
du -sh .agentic-inquiry/ 2>/dev/null || echo "No data dir"
```

Log in TEST_LOG.md:
```markdown
## Pre-Test Resource Check
| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Disk Free | ___GB | >10GB | OK/WARNING |
| ai Data Dir | ___GB | <5GB | OK/WARNING |
```

### 3. Initialize TEST_LOG.md

```markdown
# Test Log: TEST_{XX} - {Name}

**Started:** {timestamp}
**Test ID:** {test_id}
**Project ID:** {project_id}
**Status:** RUNNING

---
```

### 4. Create Fresh Session

Use the unique project_id for isolation:
```bash
ai index . --project {project_id}
```

Record baseline metrics after indexing.

## Test Execution

### Read the Test File

Read `{test_file}` and follow its procedures using ai CLI commands:

| Test Tool | CLI Command |
|-----------|-------------|
| Search | `ai search <query>` |
| Entity | `ai entity <name>` |
| Dependencies | `ai entity deps <name>` |
| References | `ai entity refs <name>` |
| Lineage | `ai lineage trace <entity>` |
| Memory Save | `ai memory save <text>` |
| Memory Recall | `ai memory recall <query>` |
| Patterns | `ai patterns discover` |
| Services | `ai services detect` |
| Validate | `ai validate` |

### For Each Task

1. **Document the task** in TEST_LOG.md
2. **Execute** using ai CLI
3. **Validate** output quality (not just success)
4. **Rate** adoption potential

```markdown
### Task N: {Name}

**Objective:** {What this tests}
**Status:** RUNNING

#### Input
```bash
ai search "authentication flow"
```

#### Output
{Actual output or summary}

#### Validation
- [ ] Returns relevant results: {Yes/No}
- [ ] Output quality acceptable: {Yes/No}
- [ ] Response time acceptable: {Yes/No}

#### Verdict: PASS/FAIL/PARTIAL

#### UAT Assessment
| Dimension | Rating | Notes |
|-----------|--------|-------|
| Useful? | Yes/Somewhat/No | {Comment} |
| Effort saved? | High/Medium/Low | {vs alternatives} |
| Would use? | Yes/Maybe/No | {Why} |
```

### Quality Standards

- Validate **accuracy and relevance** of outputs
- Low-quality or irrelevant results = FAIL
- Document failures with root cause + fix recommendation

### Status Markers

| Marker | Meaning |
|--------|---------|
| PASS | Meets all criteria |
| FAIL | Does not meet criteria |
| PARTIAL | Works but has issues |

## Incremental File Writing

**CRITICAL: Write to files IMMEDIATELY. Do NOT buffer content.**

Pattern:
1. Create TEST_LOG.md with header → WRITE NOW
2. Complete Task 1 → APPEND to TEST_LOG.md NOW
3. Find Issue → APPEND to ISSUES_LOG.md NOW
4. Continue...
5. All done → WRITE FINAL_REPORT.md
6. Return JSON summary only

## Abort Conditions

Stop testing if:
- >50% of tasks fail
- Critical tool fails 3+ times
- Disk space drops below 5GB
- Test exceeds time budget (simple: 20min, medium: 45min, complex: 60min)

## Artifacts to Create

### 1. TEST_LOG.md
Real-time execution log with inputs, outputs, validations.

### 2. ISSUES_LOG.md
```markdown
# Issues Log

| ID | Tool | Severity | Description | Status |
|----|------|----------|-------------|--------|
| ISS-001 | search | HIGH | {description} | Open |
```

### 3. FINAL_REPORT.md
```markdown
# Final Report: TEST_{XX}

## Adoption Verdict: [MUST-HAVE / RECOMMENDED / OPTIONAL / NOT RECOMMENDED]

{One paragraph: Would you adopt these tools? Why?}

## Metrics
| Metric | Value |
|--------|-------|
| Tasks Completed | X/Y |
| Pass Rate | Z% |
| Critical Issues | N |
| Duration | Xm |

## Tool Verdicts
| Tool | Functional | Adoption | Rationale |
|------|------------|----------|-----------|
| search | PASS | MUST-HAVE | {why} |
| entity | PARTIAL | SITUATIONAL | {why} |

## Recommendations
1. {Priority fix}
2. {Enhancement}
```

## Return Format (For Subagent Execution)

After completing all tests, return ONLY this JSON:

```json
{
  "test_id": "{test_id}",
  "use_case": "{use_case_slug}",
  "status": "pass|partial|fail",
  "pass_rate": "X/Y",
  "critical_issues": 0,
  "high_issues": 0,
  "adoption_verdict": "must-have|recommended|optional|not-recommended",
  "adoption_score": 8,
  "duration_minutes": 15,
  "one_line": "Brief summary"
}
```

**DO NOT** return full reports - they're in the files.

## Post-Test Teardown

Before returning:

1. **Log resource delta:**
```markdown
## Post-Test Resource Delta
| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Entities | ___ | ___ | +___ |
| ai Data | ___GB | ___GB | +___MB |
| Duration | - | - | ___min |
```

2. **If created >1000 entities:** Note that orchestrator should run maintenance

3. **Verify all files written:**
   - TEST_LOG.md
   - ISSUES_LOG.md
   - FINAL_REPORT.md
