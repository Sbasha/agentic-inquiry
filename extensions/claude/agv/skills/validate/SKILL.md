---
name: validate
description: Validate index accuracy and completeness. Use when search results seem off, after large refactoring, or before important searches.
argument-hint: "[--deep]"
context: fork
agent: Explore
allowed-tools: Bash, Read, Grep, Glob
---

# /agv:validate

Verify your agv index is accurate and complete.

## Your Task

Validate the agv index. Mode: **$ARGUMENTS** (default: quick)

## Current Index State

- Index status: !`agv index status 2>/dev/null || echo "No index found"`

## Validation Checks

### Quick Validation (default)
1. Index exists and is readable
2. Basic schema integrity
3. Sample query returns results

### Deep Validation (`--deep`)
1. All files in project are indexed
2. Entity relationships are consistent
3. Embeddings are valid
4. No orphaned references
5. Search quality spot checks

## How to Execute

```bash
# Quick validation
agv validate

# Deep validation
agv validate --deep
```

After CLI output, **verify independently**:
1. Pick 3-5 known entities and search for them
2. Check that results are ranked sensibly
3. Verify file counts match actual project files
4. Report any discrepancies

## Output Format

```markdown
## Index Validation

| Check | Status | Details |
|-------|--------|---------|
| Index accessible | {pass/fail} | {details} |
| Schema valid | {pass/fail} | {details} |
| Entity count | {N} | {breakdown by type} |
| Sample search | {pass/fail} | {query → results} |
| File coverage | {N/M} | {missing files if any} |

### Issues Found
- {Any problems detected}

### Recommendation
{Next steps based on findings}
```
