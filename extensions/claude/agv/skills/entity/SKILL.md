---
name: entity
description: Understand a code entity - its purpose, dependencies, and references. Use when exploring functions, classes, or methods in a codebase.
argument-hint: "<name> [deps|refs]"
context: fork
agent: Explore
allowed-tools: Bash, Read, Grep, Glob
---

# /agv:entity

Deep understanding of code entities: functions, classes, methods.

## Your Task

Analyze the code entity: **$ARGUMENTS**

## How to Execute

Parse `$ARGUMENTS` to determine the subcommand:
- `<name>` only → Full entity understanding
- `<name> deps` → Dependencies
- `<name> refs` → References

```bash
# Full entity info
agv entity $ARGUMENTS

# Dependencies
agv entity deps <name>

# References
agv entity refs <name>
```

## Enrich Results

After CLI output, **go deeper**:

1. **Read the source file** where the entity is defined
2. **Trace key relationships** - read files that depend on or are depended upon
3. **Assess complexity** - is this a simple utility or critical path?
4. **Identify patterns** - what design pattern does this follow?

## Output Format

```markdown
## Entity: {name}

**Location**: `{file}:{line}`
**Type**: {function|class|method}
**Purpose**: {one-line description from code analysis}

### Signature
```{language}
{full function/class signature}
```

### What It Does
{2-3 sentence explanation based on reading the actual code}

### Dependencies (calls/imports)
| Entity | File | Relationship |
|--------|------|-------------|
| ... | ... | calls/imports/inherits |

### Referenced By
| Entity | File | How |
|--------|------|-----|
| ... | ... | calls/instantiates/inherits |

### Key Observations
- {design pattern, complexity, coupling notes}

### Suggested Next Steps
- `/agv:impact {name}` - What breaks if this changes?
- `/agv:lineage {name}` - Trace data flow through this entity
```
