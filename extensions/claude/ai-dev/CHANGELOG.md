# Changelog

## [1.1.0] - 2026-02-05

### Added
- **New Skills (from .prompts/):**
  - `test-quality` - Unit test anti-patterns and quality review
  - `doc-quality` - Documentation review checklist
  - `cleanup` - Repository hygiene and maintenance
  - `rca` - Root cause analysis template
  - `code-review` - Code logic and safety checklist

## [1.0.0] - 2026-02-05

### Added
- Initial release of ai-dev plugin
- **Skills:**
  - `coding-guidelines` - Parser constraints, logging, types, security, async patterns
  - `testing` - Test commands, fixtures, anti-patterns, condition polling
  - `quality` - Quality checklists, fragile areas, fix-break prevention
  - `extending` - How to add parsers, tools, config, entity types
  - `plugins` - Gemini, OpenCode, Codex, Copilot integrations
  - `commit` - Pre-commit checks, session documentation

- **Commands:**
  - `sync-agents` - Synchronize AGENTS.md with skills

### Changed
- Extracted development content from AGENTS.md (1394 → 100 lines)
- AGENTS.md now references skills for detailed guidance
