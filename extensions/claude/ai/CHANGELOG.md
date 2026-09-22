# Changelog

## [1.1.0] - 2026-02-05

### Added
- **`ai-execute-tests` skill**: Orchestrator for UAT with subagent isolation
  - Spawns isolated subagents per test to prevent context exhaustion
  - Manages lifecycle (disk checks, maintenance between tests)
  - Batches tests by complexity
  - Generates SUMMARY.md from JSON summaries
- **`ai-functional-tester` skill**: Single test execution for subagents
  - Follows test scenarios from `tests/01-agents/`
  - Writes TEST_LOG.md, ISSUES_LOG.md, FINAL_REPORT.md
  - Returns minimal JSON summary to orchestrator
- **`ai agent-test` CLI command**: Quick test execution
  - `ai agent-test list` - List 15 test scenarios
  - `ai agent-test 01` - Run specific test
  - `ai agent-test --all` - Run all tests
  - `ai agent-test status` - Show test run status

### Changed
- **`ai-test` skill**: Now serves as unified entry point
  - Routes to CLI for quick tests
  - Routes to orchestrator for comprehensive runs
- **Gemini `execute-tests` command**: Updated to support agent-test CLI

### Removed
- **`.prompts/execute_tests.md`**: Migrated to `ai-execute-tests` skill
- **`.prompts/functional_tester.md`**: Migrated to `ai-functional-tester` skill

## [1.0.2] - 2026-02-04

### Added
- **`/ai-help`**: Quick reference for all commands
- **`/ai-status`**: Show current project, index stats, environment, and mode
- **"First 5 Minutes"** section in README for fast onboarding
- **`--json` output** documentation across commands
- **MCP clarification**: README now explains plugin uses CLI, not MCP

### Changed
- **`/ai-search similar`**: Made more prominent as key feature
- **README restructured**: Commands grouped by purpose, better discoverability
- **`/ai-lineage gaps`**: Now explicitly documented in help

## [1.0.1] - 2026-02-04

### Changed
- **ai-dev**: Reworked from "how to develop" guide to **mode toggle**
  - `/ai-dev on` activates isolated test environment
  - `/ai-dev off` returns to normal environment
  - Banner displays each turn when dev mode active
  - Prevents test data from polluting production index/memories
- Development guidance now comes from AGENTS.md and CLAUDE.md (no duplication)

### Added
- **UserPromptSubmit hook**: Shows `[ai DEV MODE]` banner when dev mode is active
- **Dev environment isolation**: `.agentic-inquiry/dev/` for all dev mode operations

## [1.0.0] - 2026-02-04

### Added
- **Full CLI coverage**: All ai CLI commands now have corresponding plugin commands
- **Consistent naming**: All commands prefixed with `ai-` (e.g., `/ai-search`, `/ai-entity`)
- **New commands**:
  - `/ai-index` - Index codebase for search
  - `/ai-search` - Semantic code search
  - `/ai-entity` - Entity understanding
  - `/ai-patterns` - Pattern discovery
  - `/ai-lineage` - Data lineage tracing
  - `/ai-impact` - Change impact analysis
  - `/ai-services` - Service architecture mapping
  - `/ai-validate` - Index validation
  - `/ai-memory` - Memory operations
- **New skills**:
  - `ai-search` - Semantic search workflow
  - `ai-index` - Indexing workflow
  - `ai-env` - Environment management (renamed from `env`)
  - `ai-test` - Unified test workflow (consolidated from multiple commands)
  - `ai-dev` - ai development workflow
  - `ai-onboard` - Project onboarding
- **Documentation**:
  - README.md with installation, quick start, command reference
  - CHANGELOG.md for version history
- **DevX improvements**:
  - Hooks for search suggestions and index reminders
  - Comprehensive skill documentation

### Changed
- **Renamed commands** for consistency:
  - `setup` → `ai-setup`
  - `env` → `ai-env`
  - `code-review` → `ai-review`
- **Consolidated test commands**:
  - `agent-tests`, `execute-tests`, `review-test-results`, `test-cleanup` → unified `/ai-test`
- **Renamed skills**:
  - `env` → `ai-env` (avoids conflicts with other plugins)
  - `setup` → removed (command is sufficient)
  - `agent-tests` → merged into `ai-test`

### Removed
- Redundant commands that are now consolidated into `/ai-test`
- Overly generic skill names that conflicted with other plugins

## [0.1.0] - 2026-02-04

### Added
- Initial plugin structure
- Basic commands for server management and testing
- Functional tester and test reviewer agents
- Environment management skill
