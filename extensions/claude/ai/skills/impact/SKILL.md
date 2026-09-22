---
name: impact
description: Analyze what would be affected by changing an entity. Use when assessing change blast radius before refactoring or modifying code.
argument-hint: "<entity>"
context: fork
agent: Explore
allowed-tools: Bash, Read, Grep, Glob
---

# /ai:impact

Understand the blast radius of changes before you make them.

## Your Task

Analyze the impact of changing: **$ARGUMENTS**

## How to Execute

```bash
ai lineage impact $ARGUMENTS
```

## Enrich Results

After CLI output, **validate and expand**:

1. **Read each impacted file** to confirm the relationship is real
2. **Classify severity** - direct callers vs transitive dependencies
3. **Check test coverage** - are impacted paths covered by tests?
4. **Identify critical paths** - API endpoints, auth flows, data pipelines

## Output Format

```markdown
## Impact Analysis: {entity}

**Risk Level**: {HIGH|MEDIUM|LOW}
**Direct Impact**: {N} files
**Transitive Impact**: {N} files
**Test Coverage**: {covered|partial|uncovered}

### Direct Impact
| File | Entity | Relationship | Risk |
|------|--------|-------------|------|
| {file} | {entity} | calls/inherits/imports | {high/med/low} |

### Transitive Impact
| File | Entity | Path | Risk |
|------|--------|------|------|
| {file} | {entity} | via {intermediate} | {risk} |

### Critical Paths Affected
- {API endpoint / auth flow / data pipeline}

### Test Coverage
- {Which impacted paths have tests}
- {Which are uncovered}

### Recommended Change Strategy
1. {Update tests first}
2. {Change entity}
3. {Verify callers}
```
