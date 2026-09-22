# ai

Agentic Inquiry integration for Claude Code - semantic code search, memory, and AI-powered code understanding.

## Installation

**Local development (this project):**
The plugin is auto-enabled via `.claude/settings.json` - just start Claude Code.

**External installation:**
```bash
# Add the marketplace
claude plugin marketplace add ./extensions/claude

# Install the plugin
claude plugin install ai@agentic-inquiry
```

**Or install directly from GitHub:**
```bash
claude plugin marketplace add github:sbasha/agentic-inquiry/extensions/claude
claude plugin install ai@agentic-inquiry
```

## First 5 Minutes

Get productive with ai immediately:

```bash
# 1. Set up (pick a project name)
/ai:setup local myproject

# 2. Index your code (takes 1-5 min depending on size)
/ai:index .

# 3. Check it worked
/ai:status

# 4. Try a search
/ai:search "main entry point"
/ai:search "error handling"

# 5. Understand something specific
/ai:entity <function-name-from-search>
```

**That's it!** You now have semantic search. Use `/ai:help` to see all commands.

## Overview

Agentic Inquiry provides semantic understanding of codebases through:
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
| `/ai:help` | List all commands and quick reference |
| `/ai:status` | Show current project, index, and mode |
| `/ai:setup` | Configure storage backend (LanceDB, PostgreSQL, AlloyDB) |

### Search & Discovery

| Command | Description |
|---------|-------------|
| `/ai:index [path]` | Index codebase for search |
| `/ai:search <query>` | Semantic code search |
| `/ai:entity <name>` | Understand code entities (purpose, deps, refs) |
| `/ai:onboard [path]` | AI-powered codebase onboarding with reports |

### Analysis

| Command | Description |
|---------|-------------|
| `/ai:patterns` | Discover architectural patterns |
| `/ai:lineage <symbol>` | Trace data flow from source to sink |
| `/ai:impact <symbol>` | Analyze change blast radius |
| `/ai:services` | Detect and map service architecture |
| `/ai:validate` | Verify index accuracy and completeness |
| `/ai:memory` | Save and recall project knowledge |
| `/ai:env` | Manage isolated environments |

## Agents

| Agent | Role |
|-------|------|
| `codebase-explorer` | Explore and map codebase architecture during onboarding |
| `command-helper` | List and describe available ai commands |
| `env-manager` | Environment lifecycle (create, destroy, status) |

## Hooks

The plugin includes lifecycle hooks that run as Python scripts:

- **SessionStart**: Start ai daemon, inject behavioral contract for memory capture
- **UserPromptSubmit**: Signal analysis and dynamic context injection
- **PreToolUse[Grep]**: Suggest `/ai:search` for conceptual queries
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
/ai:setup local newproject
/ai:index .
/ai:patterns
/ai:services
/ai:search "main entry point"
```

### Before Making Changes

```bash
/ai:entity SomeClass
/ai:impact SomeClass
/ai:lineage some_data
```

## Related

- [AGENTS.md](../../../AGENTS.md) - Full developer guide
- [CLAUDE.md](../../../CLAUDE.md) - Quick reference
- [docs/](../../../docs/) - Detailed documentation

## License

MIT
