---
name: status
description: Show current agv state - project, index, environment, and mode. Use when checking environment health or verifying configuration.
allowed-tools: Bash, Read
---

# /agv:status

Show the current state of your agv environment.

## Live State

- Working directory: !`pwd`
- Dev mode: !`test -f .agv/.dev-mode && echo "DEV MODE ACTIVE" || echo "normal"`
- Config file: !`echo ${agv_CONFIG:-"(default)"}`
- Project ID: !`echo ${agv_PROJECT_ID:-"(not set)"}`
- Index status: !`agv index status 2>/dev/null || echo "No index found"`
- Data directory: !`du -sh .agv/ 2>/dev/null || echo "No .agv/ directory"`
- Environment registry: !`cat .agv/env-registry.json 2>/dev/null || echo "No environments configured"`

## Instructions

Present the live state above in a clean, formatted status display:

```
agv Status
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

**"No index found"** → Run `/agv:index .` to build the index

**"Index is stale"** → Files changed since last index. Run `/agv:index .` to update

**"No config found"** → Run `/agv:setup local myproject` to configure
