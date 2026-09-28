# Spec: Agentic Inquiry search as a native Claude Code tool

Mode: full (changes the plugin's public surface)

- **Status:** Implementing
- **Owner:** Sbasha
- **Plan:** inline (three tasks below)
- **Constrained by:** RFC-0002 (`ai mcp`), RFC-0004 (C3 evidence)

## Objective

In the RFC-0004 C3 test run, coding agents given Agentic Inquiry as a Bash command line (`ai search`) used it in 1% of runs; offered as an MCP tool on dev tasks, they used it in 2 of 3. The plugin today registers no MCP server, so a Claude Code user gets only the command line and slash commands. The plugin should give Claude a native `search` tool for the project it is working in, with no per-project configuration.

## Boundaries

- Always: keep `ai search` and the `/ai:*` skills working as they do.
- Never: expose more MCP tools by default than `search`; change search ranking.

## Acceptance Criteria

- [ ] AC1 `ai mcp` run in a project directory without `--project-id` uses the project's integration binding when one exists, otherwise `storage.default_project_id` from configuration, the same fallback `ai search` uses; with neither it exits with a message naming `--project-id`.
- [ ] AC2 The `ai` plugin registers an MCP server named `inquiry` that runs `ai mcp --tools search` in the project directory, so Claude Code sees `mcp__inquiry__search`.
- [ ] AC3 The plugin's Grep hook points Claude at the `search` tool for conceptual queries instead of the `/ai:search` slash command, which does not run in headless sessions.
- [ ] AC4 The plugin README says what the plugin registers and how to switch the server off.

## Tasks

1. `ai mcp` project fallback (AC1). Tests: `tests/cli/test_dispatch.py` - binding wins; configured default used without a binding; neither exits with guidance.
2. Plugin MCP registration and hook text (AC2, AC3). Tests: the plugin test suite asserts the server entry and the hook prompt.
3. README (AC4).
