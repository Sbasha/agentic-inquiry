---
name: services
description: Detect and visualize service architecture. Use when mapping how services connect, onboarding, or documenting system structure.
argument-hint: "[detect|show]"
context: fork
agent: Explore
allowed-tools: Bash, Read, Grep, Glob
---

# /agv:services

Detect and visualize the service architecture of your codebase.

## Your Task

Map the service architecture: **$ARGUMENTS** (default: detect)

## How to Execute

```bash
agv services $ARGUMENTS
```

After CLI output, **enrich**:

1. **Read entry points** - API routes, CLI commands, event handlers
2. **Map connections** - how services communicate
3. **Identify boundaries** - where one service ends and another begins
4. **Draw ASCII diagram** showing the architecture

## Output Format

```markdown
## Service Architecture

### Services Detected
| Service | Type | Entry Point | Dependencies |
|---------|------|-------------|-------------|
| {name} | API/Worker/Internal | {file} | {list} |

### Architecture Diagram
```
{ASCII diagram showing service connections}
```

### External Integrations
| Integration | Protocol | Files |
|------------|----------|-------|
| {name} | REST/gRPC/Queue | {files} |
```
