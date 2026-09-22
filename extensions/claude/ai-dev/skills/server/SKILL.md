---
name: server
description: Manage the Agentic Inquiry MCP server (start, stop, status, restart). Use when working with the ai MCP server lifecycle.
argument-hint: "[start|stop|status|restart]"
allowed-tools: Bash, Read
---

# /ai-dev:server

Manage the Agentic Inquiry MCP server lifecycle.

## Commands

```bash
/ai-dev:server start     # Start server in background
/ai-dev:server stop      # Stop running server
/ai-dev:server status    # Check if server is running
/ai-dev:server restart   # Restart server
```

## Server Details

The MCP server provides:
- Semantic search tools
- Entity understanding
- Memory operations
- Pattern discovery

## Start Server

```bash
uv run --env-file .env ai serve &
```

## Check Status

```bash
pgrep -f "ai serve" && echo "Running" || echo "Stopped"
```

## Environment

Requires:
- `OPENAI_API_KEY` for embeddings
- `AI_CONFIG` or default config at `config/default.yaml`
- `AI_PROJECT_ID` for project isolation
