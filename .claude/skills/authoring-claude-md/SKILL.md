---
name: authoring-claude-md
disable-model-invocation: true
description: "Review or edit Claude-specific project instructions when explicitly requested. Use for CLAUDE.md and scoped rules while preserving existing instruction authority. Reusable SKILL.md authoring belongs to author-or-update-agent-skill; rewriting one supplied prompt belongs to prompt-enhancer."
---

# Claude project instructions

Inspect the project's existing instruction sources and the user's requested edit
scope. Review-only requests return a proposed diff. Preserve native owners and
unrelated configuration; do not create a second AGENTS.md or CLAUDE.md authority.

Read the current installed client's help or official documentation before relying
on rule discovery, precedence, path matching or context loading behavior. Do not
infer that a written rule was loaded. Identify any unverified loading behavior in
the result and use a native observation before claiming it works.

Include only stable, project-specific context that changes an agent's decisions:
non-obvious interfaces, required validation commands, ownership boundaries and
links to canonical requirements. Keep each fact in one source. Reference relevant
documentation rather than copying it into instructions.

Exclude generic coding advice, personal design opinions, development history,
completed-task logs, secrets and private identity material. Current architecture
belongs in its native documentation; historical rationale belongs in the designated
decision log. Instructions can point to either when it is useful for execution.

When scoped rules would materially reduce irrelevant context, use the current
client's documented format and the repository's existing rule layout. A scope
refines the parent instruction; it does not silently reverse it. Check conflicting
instructions before writing, and resolve them using the actual source authority.

Keep global user instructions unchanged unless the user specifically requests that
scope. Do not add hooks, permissions, memory behavior, models or account settings
as a side effect of authoring project instructions. Report the files changed, their
intended scope and which loading behavior was actually observed.
