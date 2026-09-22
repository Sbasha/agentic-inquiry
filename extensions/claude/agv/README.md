# agv

Agent-Vault integration for Claude Code - semantic code search, memory, and AI-powered code understanding.

## Installation

**Local development (this project):**
The plugin is auto-enabled via `.claude/settings.json` - just start Claude Code.

**External installation:**
```bash
# Add the marketplace
claude plugin marketplace add ./extensions/claude

# Install the plugin
claude plugin install agv@agent-vault
```

**Or install directly from GitHub:**
```bash
claude plugin marketplace add github:sbasha/agent-vault/extensions/claude
claude plugin install agv@agent-vault
```

## First 5 Minutes

Get productive with agv immediately:

```bash
# 1. Set up (pick a project name)
/agv:setup local myproject

# 2. Index your code (takes 1-5 min depending on size)
/agv:index .

# 3. Check it worked
/agv:status

# 4. Try a search
/agv:search "main entry point"
/agv:search "error handling"

# 5. Understand something specific
/agv:entity <function-name-from-search>
```

**That's it!** You now have semantic search. Use `/agv:help` to see all commands.

## Overview

Agent-Vault provides semantic understanding of codebases through:
- **Semantic Search**: Find code by concept, not just keywords
- **Similar Code**: Find code patterns similar to a known entity
- **Entity Understanding**: Deep analysis of functions, classes, methods
- **Data Lineage**: Trace how data flows through your code
- **Impact Analysis**: Understand change blast radius
- **Memory**: Persistent project knowledge

## Commands

### Getting Started

| Command | Description |
|---------|-------------|
| `/agv:help` | List all commands and quick reference |
| `/agv:status` | Show current project, index, and mode |
| `/agv:setup` | Configure storage backend (LanceDB, PostgreSQL, AlloyDB) |

### Search & Discovery

| Command | Description |
|---------|-------------|
| `/agv:index [path]` | Index codebase for search |
| `/agv:search <query>` | Semantic code search |
| `/agv:entity <name>` | Understand code entities (purpose, deps, refs) |
| `/agv:onboard [path]` | AI-powered codebase onboarding with reports |

### Analysis

| Command | Description |
|---------|-------------|
| `/agv:patterns` | Discover architectural patterns |
| `/agv:lineage <symbol>` | Trace data flow from source to sink |
| `/agv:impact <symbol>` | Analyze change blast radius |
| `/agv:services` | Detect and map service architecture |
| `/agv:validate` | Verify index accuracy and completeness |
| `/agv:memory` | Save and recall project knowledge |
| `/agv:env` | Manage isolated environments |

## Agents

| Agent | Role |
|-------|------|
| `codebase-explorer` | Explore and map codebase architecture during onboarding |
| `command-helper` | List and describe available agv commands |
| `env-manager` | Environment lifecycle (create, destroy, status) |

## Hooks

The plugin includes lifecycle hooks that run as Python scripts:

- **SessionStart**: Start agv daemon, inject behavioral contract for memory capture
- **UserPromptSubmit**: Signal analysis and dynamic context injection
- **PreToolUse[Grep]**: Suggest `/agv:search` for conceptual queries
- **PostToolUse[Write|Edit]**: Record file changes, prompt for memory capture
- **PostToolUse[Bash]**: Classify commands, capture test/build/deploy events
- **PostToolUse[TaskUpdate]**: Prompt for memory capture on task transitions
- **PreCompact**: Auto-save working memory before context compaction
- **Stop**: Force session reflection and memory storage before exit

## Storage Backends

| Backend | Best For | Embedding |
|---------|----------|-----------|
| **LanceDB** | Local development | Local (SentenceTransformer, 384d) |
| **PostgreSQL** | Self-hosted production | Local (SentenceTransformer, 384d) |
| **AlloyDB** | GCP production | Server-side (`text-embedding-005`, 768d) |

## Example Workflows

### Onboarding to a New Codebase

```bash
/agv:setup local newproject
/agv:index .
/agv:patterns
/agv:services
/agv:search "main entry point"
```

### Before Making Changes

```bash
/agv:entity SomeClass
/agv:impact SomeClass
/agv:lineage some_data
```

## Related

- [AGENTS.md](../../../AGENTS.md) - Full developer guide
- [CLAUDE.md](../../../CLAUDE.md) - Quick reference
- [docs/](../../../docs/) - Detailed documentation

## License

MIT
