---
name: memory
description: Save and recall project memories and insights. Use when capturing learnings, decisions, or institutional knowledge about a codebase.
argument-hint: "[save|recall|list] <text|query>"
allowed-tools: Bash, Read
---

# /agv:memory

Persistent memory for project insights and learnings.

## Your Task

Execute memory operation: **$ARGUMENTS**

## How to Execute

Parse `$ARGUMENTS`:
- `save "<text>"` → Store a new memory
- `recall "<query>"` → Search memories semantically
- `list` → Show all saved memories

```bash
agv memory save "insight here"
agv memory recall "query"
agv memory list
```

## Tips for Good Memories

Save insights that are **not obvious from the code**:
- Architecture decisions and their rationale
- Gotchas and edge cases discovered during debugging
- Configuration quirks and environment-specific behavior
- Performance characteristics learned through testing
- External system integration details

## Use Cases

1. **Knowledge capture**: Save learnings as you go
2. **Onboarding**: Build institutional knowledge
3. **Debugging**: Remember past solutions
4. **Decisions**: Document why things are the way they are
