---
name: test
description: Unified test workflow - environment setup, test selection, execution, and cleanup. Use when running Agent-Vault tests.
argument-hint: "[run|select|status|cleanup] [--env name] [--suite path]"
allowed-tools: Bash, Read, Write, Agent
---

# /agv-dev:test

Unified testing workflow for Agent-Vault.

## Quick Start

```bash
/agv-dev:test                               # Interactive test workflow
/agv-dev:test run                           # Run all tests
/agv-dev:test run --suite tests/search/     # Run specific suite
/agv-dev:test --env test-env                # Use specific environment
```

## Workflow

```
1. Environment Setup
   └── Creates isolated test environment (or uses existing)

2. Test Selection
   └── Choose tests: all, by path, by pattern

3. Execution
   └── Runs tests with functional-tester agent

4. Results & Cleanup
   └── Generate report, optionally destroy environment
```

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `run` | Execute tests (default) |
| `select` | Interactive test selection |
| `status` | Show current test session status |
| `cleanup` | Clean up test artifacts and environments |

## Options

| Option | Description |
|--------|-------------|
| `--env` | Use specific environment |
| `--suite` | Path to test suite |
| `--keep-env` | Don't destroy environment after tests |
| `--parallel` | Run tests in parallel |

## Test Suites

```bash
/agv-dev:test run --suite tests/unit/           # Unit tests
/agv-dev:test run --suite tests/integration/    # Integration tests
/agv-dev:test run --suite tests/01-agents/      # Agent tests (UAT)
```

## Output

```
test_results/agv/<timestamp>/
├── TEST_LOG.md
├── ISSUES_LOG.md
├── FINAL_REPORT.md
└── SESSION_SUMMARY.md
```
