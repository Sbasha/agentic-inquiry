---
name: patterns
description: Discover and list architectural patterns in the codebase. Use when onboarding, ensuring consistency, or identifying anti-patterns.
argument-hint: "[discover|list]"
context: fork
agent: Explore
allowed-tools: Bash, Read, Grep, Glob
---

# /ai:patterns

Discover architectural patterns and conventions in your codebase.

## Your Task

Discover patterns: **$ARGUMENTS** (default: list known patterns)

## How to Execute

```bash
ai patterns $ARGUMENTS
```

After CLI output, **enrich by reading code**:

1. **Verify each pattern** - read the actual files to confirm
2. **Find additional patterns** not caught by automated analysis
3. **Identify anti-patterns** - God classes, circular dependencies, etc.
4. **Assess consistency** - are patterns applied uniformly?

## Output Format

```markdown
## Architectural Patterns

### Design Patterns Found
| Pattern | Location | Example | Consistency |
|---------|----------|---------|-------------|
| Repository | storage/providers/ | LanceDBManager | High |
| Factory | parsers/chain.py | ParserChain.create_for_language() | High |

### Anti-Patterns Detected
| Anti-Pattern | Location | Severity | Suggestion |
|-------------|----------|----------|------------|
| {name} | {file} | {high/med/low} | {fix} |

### Conventions
- Naming: {conventions observed}
- File organization: {patterns}
- Error handling: {approach}
```
