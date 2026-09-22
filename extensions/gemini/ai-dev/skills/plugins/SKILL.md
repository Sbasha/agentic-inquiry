---
name: plugins
description: Agentic Inquiry CLI extensions and plugin integrations - Gemini, OpenCode, Codex, Copilot.
---

# ai Plugin Integrations

Reference for integrating Agentic Inquiry with AI coding tools.

## When to Use

- Setting up ai with a new AI tool
- Debugging extension connectivity
- Creating a new CLI extension

## Available Integrations

| Tool | Location | Config Type |
|------|----------|-------------|
| Gemini CLI | `extensions/ai/` | `gemini-extension.json` |
| OpenCode | `plugins/opencode/` | `opencode.json` |
| Codex | `plugins/codex/` | Skill + TOML |
| Copilot | `plugins/copilot/` | Python setup |

## Gemini CLI

**Install:**
```bash
gemini extensions install /path/to/agentic-inquiry/extensions/ai
# Or for development
gemini extensions link /path/to/agentic-inquiry/extensions/ai
```

**Usage:**
```bash
gemini -e ai-agent-kit "Find authentication functions"
gemini -e ai-agent-kit /ai:search "JWT validation"
gemini -e ai-agent-kit /serve
```

## OpenCode

**Config (`opencode.json`):**
```json
{
  "mcp": {
    "agentic-inquiry": {
      "type": "local",
      "command": ["uv", "run", "ai", "serve"],
      "args": ["--project-id", "my_project", "--transport", "stdio"],
      "enabled": true
    }
  }
}
```

## Codex

**Install:**
```bash
cp -r plugins/codex ~/.agents/skills/agentic-inquiry
cat plugins/codex/codex-mcp.toml >> ~/.codex/config.toml
```

## Direct CLI

```bash
# STDIO transport (for AI tools)
uv run ai serve --project-id my_project --transport stdio

# HTTP transport (for web clients)
uv run ai serve --project-id my_project --transport http --port 8000

# List tools
uv run ai --list-tools
```

## Core ai Commands

| Command | Description |
|---------|-------------|
| `/ai:search` | Semantic search with context |
| `/ai:index` | Index a codebase |
| `/ai:entity` | Understand a code entity |
| `/ai:impact` | Analyze change impact |
| `/ai:lineage` | Trace data flow paths |
| `/ai:patterns` | Discover patterns |
| `/ai:memory` | Save/recall insights |

## MCP Tools (All Extensions)

All extensions connect to ai's MCP server providing:
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
