---
name: plugins
description: Agent-Vault CLI extensions and plugin integrations - Gemini, OpenCode, Codex, Copilot.
---

# agv Plugin Integrations

Reference for integrating Agent-Vault with AI coding tools.

## When to Use

- Setting up agv with a new AI tool
- Debugging extension connectivity
- Creating a new CLI extension

## Available Integrations

| Tool | Location | Config Type |
|------|----------|-------------|
| Gemini CLI | `extensions/agv/` | `gemini-extension.json` |
| OpenCode | `plugins/opencode/` | `opencode.json` |
| Codex | `plugins/codex/` | Skill + TOML |
| Copilot | `plugins/copilot/` | Python setup |

## Gemini CLI

**Install:**
```bash
gemini extensions install /path/to/agent-vault/extensions/agv
# Or for development
gemini extensions link /path/to/agent-vault/extensions/agv
```

**Usage:**
```bash
gemini -e agv-agent-kit "Find authentication functions"
gemini -e agv-agent-kit /agv:search "JWT validation"
gemini -e agv-agent-kit /serve
```

## OpenCode

**Config (`opencode.json`):**
```json
{
  "mcp": {
    "agent-vault": {
      "type": "local",
      "command": ["uv", "run", "agv", "serve"],
      "args": ["--project-id", "my_project", "--transport", "stdio"],
      "enabled": true
    }
  }
}
```

## Codex

**Install:**
```bash
cp -r plugins/codex ~/.agents/skills/agent-vault
cat plugins/codex/codex-mcp.toml >> ~/.codex/config.toml
```

## Direct CLI

```bash
# STDIO transport (for AI tools)
uv run agv serve --project-id my_project --transport stdio

# HTTP transport (for web clients)
uv run agv serve --project-id my_project --transport http --port 8000

# List tools
uv run agv --list-tools
```

## Core agv Commands

| Command | Description |
|---------|-------------|
| `/agv:search` | Semantic search with context |
| `/agv:index` | Index a codebase |
| `/agv:entity` | Understand a code entity |
| `/agv:impact` | Analyze change impact |
| `/agv:lineage` | Trace data flow paths |
| `/agv:patterns` | Discover patterns |
| `/agv:memory` | Save/recall insights |

## MCP Tools (All Extensions)

All extensions connect to agv's MCP server providing:
- `search_knowledge` - Semantic search
- `find_similar` - Similar code discovery
- `understand_entity` - Symbol analysis
- `analyze_impact` - Impact analysis
- `build_context` - Context assembly
- `save_memory` / `recall_memories` - Memory persistence

## Extension Development

To create a new extension:

1. **Gemini:** Create `gemini-extension.json` with `mcpServers` config
2. **OpenCode:** Add MCP server config to `opencode.json`
3. **Codex:** Create `SKILL.md` with workflow instructions
