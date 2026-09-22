---
name: agv-test
description: Unified test workflow for agv. Use when running agent UAT tests, pytest, or reviewing test results.
---

# agv Test Skill

Entry point for all agv testing workflows.

## When to Use

- "Run the tests"
- "Run agent tests"
- "Execute TEST_01"
- "Run pytest"

## Test Types

| Type | Location | How to Run |
|------|----------|------------|
| **Unit** | `tests/unit/` | `uv run pytest tests/unit/` |
| **Integration** | `tests/integration/` | `uv run pytest tests/integration/` |
| **Agent UAT** | `tests/01-agents/` | See below |

## Agent UAT Testing

### Quick CLI (Individual Tests)

```bash
# List all 15 test scenarios
agv agent-test list

# Run smoke test (always run first)
agv agent-test 01

# Run specific test
agv agent-test 03

# Check results
agv agent-test status
```

### Full Suite (Orchestrated)

For comprehensive testing with subagent isolation, use:

```
/agv:execute-tests
```

This orchestrator:
- Spawns isolated subagents per test
- Manages lifecycle (disk checks, maintenance)
- Batches tests by complexity
- Generates SUMMARY.md from JSON summaries

### Test Scenarios (15 total)

| ID | Name | Time |
|----|------|------|
| 01 | Core Functionality | 10-15m |
| 02 | Onboarding | 20-30m |
| 03 | Feature Implementation | 30-45m |
| 04 | Bug Investigation | 25-40m |
| 05 | Major Refactoring | 45-60m |
| 06 | Knowledge Building | 20-30m |
| 07 | Code Review | 30-40m |
| 08 | Documentation Generation | 25-35m |
| 09 | Dependency Analysis | 30-40m |
| 10 | Performance Investigation | 35-50m |
| 11 | API Design | 40-55m |
| 12 | Code Graph | 30m |
| 13 | Document Graph | 20m |
| 14 | Semantic Graph | 20m |
| 15 | Executive Function | 20m |

## Pytest (Unit/Integration)

```bash
# All tests
uv run --env-file .env pytest

# Stop on first failure
uv run --env-file .env pytest -x

# Specific test file
uv run --env-file .env pytest tests/search/test_service.py

# With coverage
uv run --env-file .env pytest --cov=agent_vault
```

## Output Artifacts

```
test_results/agv/{timestamp}/
├── SUMMARY.md              # Aggregate (orchestrator creates)
├── test_01_core/
│   ├── TEST_LOG.md         # Execution log
│   ├── ISSUES_LOG.md       # Issues found
│   └── FINAL_REPORT.md     # Assessment
└── ...
```

## Related Skills

- `/agv:execute-tests` - Full orchestrated test run with subagents
- `/agv:functional-tester` - Single test execution (used by orchestrator)
