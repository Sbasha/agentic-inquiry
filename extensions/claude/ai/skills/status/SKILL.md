---
name: status
description: Show current ai state - project, index, environment, and mode. Use when checking environment health or verifying configuration.
allowed-tools: Bash, Read
---

# /ai:status

Show the current state of your ai environment.

## Live State

- Working directory: !`pwd`
- Dev mode: !`test -f .agentic-inquiry/.dev-mode && echo "DEV MODE ACTIVE" || echo "normal"`
- Config file: !`echo ${AI_CONFIG:-"(default)"}`
- Project ID: !`echo ${AI_PROJECT_ID:-"(not set)"}`
- Index status: !`ai index status 2>/dev/null || echo "No index found"`
- Data directory: !`du -sh .agentic-inquiry/ 2>/dev/null || echo "No .agentic-inquiry/ directory"`
- Environment registry: !`cat .agentic-inquiry/env-registry.json 2>/dev/null || echo "No environments configured"`

## Instructions

Present the live state above in a clean, formatted status display:

```
ai Status
──────────
Mode:        {normal | DEV MODE}
Project:     {project_id}
Config:      {config path}
Storage:     {lancedb | postgresql}

Index:
  Entities:  {count}
  Files:     {count}
  Last update: {timestamp}

Environment:
  Data dir:  {path}
  Size:      {size}
```

## Common Issues

**"No index found"** → Run `/ai:index .` to build the index

**"Index is stale"** → Files changed since last index. Run `/ai:index .` to update

**"No config found"** → Run `/ai:setup local myproject` to configure
