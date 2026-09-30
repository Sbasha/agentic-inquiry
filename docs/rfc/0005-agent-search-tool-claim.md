# RFC-0005: Does a native search tool improve a coding agent?

- **Status:** Accepted
- **Author:** Sbasha
- **Approver:** Sbasha
- **Date opened:** 2026-09-28
- **Date closed:** 2026-09-28
- **Decision weight:** standard
- **Related:** RFC-0004 (C3), `docs/specs/claude-mcp-search/spec.md`, `docs/specs/eval-claims/spec.md`

## The ask

**Recommendation.** Pre-register one new claim, C3b, before any of its tasks is mined or run.

**Why.** RFC-0004's C3 found no difference between a coding agent with and without Agentic Inquiry, but its agents called the tool in 1% of runs. They were offered it only as a restricted Bash command, and the refused commands cost them turns. On the 45 C3 tasks whose issue named a changed file, every arm solved 43 to 44, leaving nothing for search to add. The plugin now gives Claude a native MCP `search` tool (commit `2fa739a`). C3b asks whether that tool helps where finding the code is the actual problem.

## Claim

**C3b.** On issues that do not name the code to change, a Claude Code agent with Agentic Inquiry's MCP `search` tool names a changed function more often than the same agent without it, and more often than with Graphify's MCP tools.

## Design

- **Tasks.** Mined once with RFC-0004's C3 rules from the same seven repositories and merge window. Every task must also meet two further conditions:
  - it is not one of the 100 C3 tasks;
  - its issue title and body do not contain any changed file's name, module path or repository path.

  The 100 eligible tasks with the lowest `sha256("20260926:" + task id)` are taken. The list is committed before any C3b run, as `evals/tasks/fresh-2026b.jsonl`.
- **Arms.** The same agent (`claude-sonnet-5`, at most 14 turns, the C3 prompt) with:
  - `floor`: Read, Grep and Glob.
  - `inquiry`: the floor, plus the `search` tool from `ai mcp --tools search`, the server the plugin registers.
  - `graphify`: the floor, plus Graphify's MCP server over its default `graphify update .` graph, with `query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `god_nodes`, `graph_stats` and `get_community`.

  Each tool arm gets the parallel one-paragraph guidance from RFC-0003 Level C (`ARM_GUIDANCE` in `evals/agent.py`), so neither tool gets a stronger nudge. No Bash is offered.
- **Metric, test and accounting.** C3's in full:
  - Solved: one of the first five cited `path:line` pairs falls inside a changed function.
  - Test: exact McNemar with Holm across the two comparisons.
  - Accounting: time, tokens and dollars per run, plus each tool's use rate.
  - The run records each agent's MCP tool manifest, and a run whose tools differ from its arm is an infrastructure failure.
- **Frozen system.** `inquiry` as at `a0faf7b`, `code_hash` `4c370115c21d645b`. The run refuses to start if it differs.

## Known before this claim

- Among C3's 55 tasks that name no changed file, the floor agent solved 40 (73%). That leaves about 27 points of headroom.
- At 100 paired tasks the smallest detectable gap after Holm is about 17 points, so C3b needs `inquiry` to reach about 90% where the floor reaches about 73%.
- In a dev probe on 3 older SWE-bench tasks, the agent called the MCP `search` tool in 2 of 3 runs, and Graphify's MCP tools in none. All 9 runs solved their task.

## Consequences

- About 100 new repository snapshots must be indexed before the run: roughly 30 hours of local compute, with no LLM calls.
- About 300 agent runs follow, roughly $90 at list prices on the Claude subscription.
- A null result would mean a native tool does not make this agent better at localization on these repositories. That would be reported as found.
