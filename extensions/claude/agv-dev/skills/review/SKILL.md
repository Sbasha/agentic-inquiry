---
name: review
description: Run comprehensive multi-phase code review. Use when reviewing uncommitted changes, commits, branches, or specific files.
argument-hint: "[files|commit|branch]"
context: fork
agent: general-purpose
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash, Agent
---

# /agv-dev:review

Comprehensive, multi-phase code review.

## Your Task

Review code changes: **$ARGUMENTS** (default: uncommitted changes)

## Change Context

- Git status: !`git status --short 2>/dev/null || echo "Not a git repo"`
- Recent commits: !`git log --oneline -5 2>/dev/null || echo "No git history"`
- Staged diff stats: !`git diff --cached --stat 2>/dev/null`
- Unstaged diff stats: !`git diff --stat 2>/dev/null`

## Review Protocol

### Phase 1: Foundational Validity (Gate)
- Root cause verification for bug fixes
- Was the right problem solved?
- **Blocks if**: No root cause analysis for bugs

### Phase 2: Core Reliability (Critical)
- Code logic & safety
- Async correctness (all I/O must be `async def`)
- Architecture compliance (concrete types, project isolation)
- Security vulnerabilities (path traversal, SQL injection, pickle)
- Test coverage
- **Blocks if**: Safety or architecture violations

### Phase 3: Project Health (Polish)
- Documentation accuracy
- Repository hygiene
- Config documentation

## Review Checklist

**Architecture Compliance:**
- [ ] Async-only enforcement
- [ ] Concrete types (not protocols)
- [ ] Project isolation via project_id
- [ ] Uses existing components

**Security:**
- [ ] Path traversal prevention
- [ ] Query sanitization
- [ ] No pickle on untrusted data

**Async Safety:**
- [ ] Semaphore limits for batch ops
- [ ] gather uses return_exceptions=True
- [ ] Proper resource cleanup

## Output Format

```markdown
# Code Review

**Status:** PASS | NEEDS_WORK | BLOCKED

## Executive Summary
[1-2 sentences on overall assessment]

## Findings

### Critical (Blockers)
1. [file:line] Issue description
   - Impact: [why this matters]
   - Fix: [suggested resolution]

### Warnings
1. [file:line] Issue description

### Suggestions
1. [file:line] Improvement opportunity

## Action Items
1. [Required before merge]
```
