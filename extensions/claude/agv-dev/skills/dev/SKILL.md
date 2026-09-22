---
name: dev
description: Toggle development mode - isolates test environment from production data. Use when testing agv changes or experimenting safely.
argument-hint: "[on|off|status]"
allowed-tools: Bash, Read, Write
---

# /agv-dev:dev

Toggle between development/test environment and normal use.

## Quick Start

```bash
/agv-dev:dev on       # Enter dev mode (uses test environment)
/agv-dev:dev off      # Exit dev mode (uses normal environment)
/agv-dev:dev status   # Check current mode
```

## What Dev Mode Does

When **ON**:
- All agv operations use `.agv/dev/` environment
- Memories, index, and knowledge are isolated from production
- Banner displays each turn: `[agv DEV MODE]`
- Safe to experiment without polluting real data

When **OFF**:
- Normal agv operations use default environment
- No banner displayed
- Production data is used

## Implementation

Dev mode is tracked via `.agv/.dev-mode` file:
- File exists = dev mode ON
- File absent = dev mode OFF

Environment switching:
```bash
# Dev mode ON
export agv_CONFIG=.agv/dev/config.yaml
export agv_PROJECT_ID=agv-dev

# Dev mode OFF
unset agv_CONFIG  # uses default
export agv_PROJECT_ID=default
```

## Banner

When dev mode is active, a UserPromptSubmit hook displays:
```
[agv DEV MODE] Using test environment. `/agv-dev:dev off` to exit.
```
