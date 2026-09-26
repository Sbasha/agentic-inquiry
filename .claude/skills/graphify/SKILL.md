---
name: graphify
description: Build or query an optional Graphify knowledge graph for explicit codebase mapping, dependency paths, blast-radius analysis, subsystem discovery, or task partitioning. Use only when the user invokes Graphify or approves graph generation; treat output as Git-tree-scoped derived evidence, not project authority or persistent agent memory.
disable-model-invocation: true
---

# Graphify

A graph extraction or query is the deliverable here. Use `architect-assess` for a repository architecture assessment and `architect-diagram` for a Mermaid view; neither requires graph generation.


Use Graphify when relationship traversal adds material value beyond targeted
source search. Keep the graph optional, inspectable, and tied to the exact source
tree it represents.

## Preconditions

1. Confirm the request explicitly calls for Graphify or the user has approved
   generating/updating the graph.
2. Check for the `graphify` executable. If missing, report the reviewed package
   name (`graphifyy`) and ask before installing it. Do not install dependencies
   as a side effect of this skill.
3. Read `.agents/project.json` when present. Respect its graph path and whether
   graph output is tracked or local.
4. Inspect `git status` and the current Git tree before building or querying.

Read the installed CLI version and its current help before choosing an operation.
Respect any project-declared version pin; the skill carries no ambient version authority.

## Choose the smallest operation

- Existing, fresh graph and a relationship question: `graphify query`, `path`,
  or `explain`.
- Missing or stale graph and the user approved generation: build or update the
  requested project path.
- Simple symbol lookup or a narrow file question: use repository-native search
  instead of building a graph.

Examples:

```bash
graphify query "what connects authentication to persistence?"
graphify path "SessionService" "DatabasePool"
graphify explain "RateLimiter"
graphify extract .
```

Use `graphify --help` to confirm current flags rather than copying older skill
syntax. The package is `graphifyy`; the executable is `graphify`.

## Build and stamp

Before generation, confirm the source scope and whether documents or media may
leave the machine for semantic processing. Code extraction can be local; other
input types may use a configured model backend.

After a successful build or update, return the source commit/tree, working-tree
status, graph path and installed Graphify version with the result. The commit/tree
alone does not identify uncommitted source changes; disclose them and treat
freshness as unknown unless the graph's existing metadata binds their exact content.
Use a project-owned graph manifest when one exists. This skill does not require a
legacy agent-harness command or create a second state authority.

## Use in orchestration

The conductor may use graph output to:

- identify dependency paths and likely blast radius;
- find subsystem boundaries and high-coupling hubs;
- partition work into file-disjoint tasks;
- give a worker a bounded source map;
- compare a proposed plan with actual code relationships.

Verify consequential graph claims against source files. Mark inferred edges as
inferred. Put durable conclusions in reviewed project documentation or decision
records.

## Collaboration and safety

- A graph is derived data. It does not override source, tests, plans, approvals,
  issue state, or architecture decisions.
- Use a graph generated from the same Git tree as the worker's checkout.
- Keep credentials, local cost records, and caches out of commits.
- Treat committed graph output like any generated artifact: define one owner and
  a reproducible refresh procedure.
- Use worktrees for parallel writers; a shared graph does not make a shared
  checkout safe.
- Leave hook installation, assistant-instruction edits, auto-watch, graph merges,
  exports, cloning, Q&A persistence, and “lesson” generation off unless the user
  requests that specific mutation.

## Report

Return the graph path, Graphify version, source Git tree, operation performed,
material findings with source locations, inferred-versus-extracted status, and
any freshness or backend caveat.
