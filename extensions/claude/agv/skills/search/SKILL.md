---
name: search
description: Semantic search across code and documentation. Use when searching for code concepts, finding implementations, or exploring the codebase.
argument-hint: "<query> [similar <entity>] [--type code|docs] [--limit n] [--json]"
context: fork
agent: Explore
allowed-tools: Bash, Read, Grep, Glob
---

# /agv:search

Semantic search that understands code concepts, not just keywords.

## Your Task

Execute a agv semantic search for the user's query: **$ARGUMENTS**

## How to Execute

Run the search via CLI:

```bash
agv search "$ARGUMENTS"
```

Parse the arguments to determine search type:
- If `$ARGUMENTS` starts with `similar`: `agv search similar <entity>`
- If `--type code`: `agv search "$ARGUMENTS" --type code`
- If `--type docs`: `agv search "$ARGUMENTS" --type docs`
- If `--json`: Add `--json` flag and return raw JSON
- If `--limit N`: Add `--limit N` flag

## Enrich Results

After getting search results, **enrich them** by:

1. **Read the top 2-3 matching files** at the reported line numbers
2. **Show surrounding context** (5 lines before/after the match)
3. **Explain relevance** - why each result matches the query
4. **Suggest next steps** - related entities to explore, deeper searches

## Output Format

```markdown
## Search Results: "{query}"

### 1. {file}:{function} (score: {score})
{Brief explanation of what this code does and why it matches}

```{language}
{relevant code snippet from the file}
```

### 2. {file}:{function} (score: {score})
...

## Suggested Next Steps
- `/agv:entity {top_entity}` - Understand this entity deeper
- `/agv:impact {top_entity}` - See what depends on it
- `/agv:search "{refined_query}"` - Refine your search
```

## Tips

- Use natural language ("how does X work") not keywords
- `similar` finds structurally/semantically similar code to a known entity
- Combine with `/agv:entity` to dive deeper into results
