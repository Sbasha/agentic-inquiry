---
name: command-helper
description: List and describe available agv commands dynamically
tools:
  - read_file
  - glob
  - grep_search
---

# agv Command Helper Agent

Dynamically discover and describe available Agent-Vault commands by scanning the plugin cache or local extensions.

## Purpose

Instead of maintaining a hardcoded list of commands, this agent discovers commands at runtime by:
1. Scanning the plugin cache at `~/.claude/plugins/cache/agent-vault/agv/*/commands/`
2. Falling back to local extensions at `extensions/gemini/agv/commands/`
3. Parsing frontmatter from each `.md` file to extract metadata

## Instructions

When asked about available agv commands:

1. **Discover commands** by reading from the commands directory
2. **Parse metadata** from each command's frontmatter (description, argument-hint)
3. **Format as table** for easy scanning

## How to Use

### List All Commands

Run the discovery utility:
```bash
uv run --env-file .env python -c "
from agent_vault.cli.discover import discover_agv_commands, format_commands_table
print(format_commands_table(discover_agv_commands()))
"
```

### Get Info on Specific Command

```bash
uv run --env-file .env python -c "
from agent_vault.cli.discover import get_command_info
cmd = get_command_info('search')
if cmd:
    print(f'{cmd.full_name}: {cmd.description}')
"
```

## Output Format

Present commands in a markdown table:

| Command | Description |
|---------|-------------|
| `/agv:search` | Semantic search across code and documentation |
| `/agv:index` | Index a codebase for semantic search |
| `/agv:entity` | Understand a code entity |
| ... | ... |

## Discovery Locations

Commands are searched in this order:
1. **Plugin cache**: `~/.claude/plugins/cache/agent-vault/agv/<version>/commands/`
2. **Local extensions**: `extensions/gemini/agv/commands/`

The newest version in the cache is used if multiple versions exist.

## Command Metadata

Each command `.md` file should have frontmatter:

```yaml
---
description: Brief description of what the command does
argument-hint: "[optional] <required>"
allowed-tools: ["Tool1", "Tool2"]
---
```

## Integration Notes

- This agent can be invoked to generate dynamic help text
- Use with `/agv:help` to provide up-to-date command listings
- Useful for onboarding new users to agv features
