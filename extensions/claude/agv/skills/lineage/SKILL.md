---
name: lineage
description: Trace data lineage from source to sink. Use when tracking data flow, debugging data transformations, or documenting compliance paths.
argument-hint: "<entity> [trace|gaps]"
context: fork
agent: Explore
allowed-tools: Bash, Read, Grep, Glob
---

# /agv:lineage

Trace how data flows through your codebase.

## Your Task

Trace data lineage for: **$ARGUMENTS**

## How to Execute

Parse `$ARGUMENTS`:
- `<entity>` → Basic lineage
- `trace <entity>` → Full source-to-sink trace
- `gaps` → Find broken lineage chains

```bash
agv lineage $ARGUMENTS
```

## Enrich Results

After CLI output, **validate by reading code**:

1. **Follow the chain** - read each file in the lineage path
2. **Verify transformations** - how does data change at each step?
3. **Identify gaps** - where does visibility end?
4. **Check for side effects** - logging, caching, event emission along the path

## Output Format

```markdown
## Data Lineage: {entity}

### Flow Path
```
{source} (entry point)
  → {transform_1}() ({layer})
    → {transform_2}() ({layer})
      → {sink} (destination)
```

### Step Details
| Step | File | Transformation | Data Shape |
|------|------|---------------|------------|
| 1 | {file} | {what happens} | {in → out} |

### Gaps Found
- {Where lineage breaks or visibility ends}

### Compliance Notes
- {PII handling, encryption, audit logging along the path}
```

## Use Cases

1. **Compliance**: GDPR data flow documentation
2. **Debugging**: Track where data transforms incorrectly
3. **Security**: Ensure sensitive data is handled properly
4. **Refactoring**: Understand data dependencies before changes
