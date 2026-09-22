# Changelog

## [1.1.0] - 2026-02-05

### Added
- **`agv-execute-tests` skill**: Orchestrator for UAT with subagent isolation
  - Spawns isolated subagents per test to prevent context exhaustion
  - Manages lifecycle (disk checks, maintenance between tests)
  - Batches tests by complexity
  - Generates SUMMARY.md from JSON summaries
- **`agv-functional-tester` skill**: Single test execution for subagents
  - Follows test scenarios from `tests/01-agents/`
  - Writes TEST_LOG.md, ISSUES_LOG.md, FINAL_REPORT.md
  - Returns minimal JSON summary to orchestrator
- **`agv agent-test` CLI command**: Quick test execution
  - `agv agent-test list` - List 15 test scenarios
  - `agv agent-test 01` - Run specific test
  - `agv agent-test --all` - Run all tests
  - `agv agent-test status` - Show test run status

### Changed
- **`agv-test` skill**: Now serves as unified entry point
  - Routes to CLI for quick tests
  - Routes to orchestrator for comprehensive runs
- **Gemini `execute-tests` command**: Updated to support agent-test CLI

### Removed
- **`.prompts/execute_tests.md`**: Migrated to `agv-execute-tests` skill
- **`.prompts/functional_tester.md`**: Migrated to `agv-functional-tester` skill

## [1.0.2] - 2026-02-04

### Added
- **`/agv-help`**: Quick reference for all commands
- **`/agv-status`**: Show current project, index stats, environment, and mode
- **"First 5 Minutes"** section in README for fast onboarding
- **`--json` output** documentation across commands
- **MCP clarification**: README now explains plugin uses CLI, not MCP

### Changed
- **`/agv-search similar`**: Made more prominent as key feature
- **README restructured**: Commands grouped by purpose, better discoverability
- **`/agv-lineage gaps`**: Now explicitly documented in help

## [1.0.1] - 2026-02-04

### Changed
- **agv-dev**: Reworked from "how to develop" guide to **mode toggle**
  - `/agv-dev on` activates isolated test environment
  - `/agv-dev off` returns to normal environment
  - Banner displays each turn when dev mode active
  - Prevents test data from polluting production index/memories
- Development guidance now comes from AGENTS.md and CLAUDE.md (no duplication)

### Added
- **UserPromptSubmit hook**: Shows `[agv DEV MODE]` banner when dev mode is active
- **Dev environment isolation**: `.agv/dev/` for all dev mode operations

## [1.0.0] - 2026-02-04

### Added
- **Full CLI coverage**: All agv CLI commands now have corresponding plugin commands
- **Consistent naming**: All commands prefixed with `agv-` (e.g., `/agv-search`, `/agv-entity`)
- **New commands**:
  - `/agv-index` - Index codebase for search
  - `/agv-search` - Semantic code search
  - `/agv-entity` - Entity understanding
  - `/agv-patterns` - Pattern discovery
  - `/agv-lineage` - Data lineage tracing
  - `/agv-impact` - Change impact analysis
  - `/agv-services` - Service architecture mapping
  - `/agv-validate` - Index validation
  - `/agv-memory` - Memory operations
- **New skills**:
  - `agv-search` - Semantic search workflow
  - `agv-index` - Indexing workflow
  - `agv-env` - Environment management (renamed from `env`)
  - `agv-test` - Unified test workflow (consolidated from multiple commands)
  - `agv-dev` - agv development workflow
  - `agv-onboard` - Project onboarding
- **Documentation**:
  - README.md with installation, quick start, command reference
  - CHANGELOG.md for version history
- **DevX improvements**:
  - Hooks for search suggestions and index reminders
  - Comprehensive skill documentation

### Changed
- **Renamed commands** for consistency:
  - `setup` → `agv-setup`
  - `env` → `agv-env`
  - `code-review` → `agv-review`
- **Consolidated test commands**:
  - `agent-tests`, `execute-tests`, `review-test-results`, `test-cleanup` → unified `/agv-test`
- **Renamed skills**:
  - `env` → `agv-env` (avoids conflicts with other plugins)
  - `setup` → removed (command is sufficient)
  - `agent-tests` → merged into `agv-test`

### Removed
- Redundant commands that are now consolidated into `/agv-test`
- Overly generic skill names that conflicted with other plugins

## [0.1.0] - 2026-02-04

### Added
- Initial plugin structure
- Basic commands for server management and testing
- Functional tester and test reviewer agents
- Environment management skill
