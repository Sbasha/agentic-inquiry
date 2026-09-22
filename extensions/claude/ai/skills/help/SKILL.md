---
name: help
description: List all ai commands and their descriptions. Use when looking for available ai capabilities.
argument-hint: "[command]"
allowed-tools: Read
---

# /ai:help

Quick reference for all Agentic Inquiry skills.

## All Skills

### Getting Started
| Skill | Description |
|-------|-------------|
| `/ai:onboard` | Intelligent onboarding - parallel index, explore, validate |
| `/ai:setup` | Configure storage backend (local/gcp/alloydb) |
| `/ai:status` | Show current project, index, and mode status |
| `/ai:env` | Manage isolated environments |

### Search & Discovery
| Skill | Description |
|-------|-------------|
| `/ai:index` | Index codebase for semantic search |
| `/ai:search` | Semantic search across code and docs |
| `/ai:search similar <entity>` | Find code similar to an entity |
| `/ai:entity` | Understand a code entity |
| `/ai:entity deps <name>` | Show entity dependencies |
| `/ai:entity refs <name>` | Show entity references |

### Analysis
| Skill | Description |
|-------|-------------|
| `/ai:patterns` | Discover architectural patterns |
| `/ai:lineage` | Trace data flow |
| `/ai:lineage gaps` | Find entities without full traceability |
| `/ai:impact` | Analyze change blast radius |
| `/ai:services` | Map service architecture |
| `/ai:validate` | Verify index accuracy |

### Knowledge
| Skill | Description |
|-------|-------------|
| `/ai:memory save` | Save a project insight |
| `/ai:memory recall` | Search saved memories |
| `/ai:memory list` | List all memories |

> **Dev tools** (testing, code review, server management) are in the `ai-dev` plugin.

## Quick Start

```bash
/ai:setup local myproject   # 1. Configure
/ai:index .                 # 2. Index
/ai:search "auth flow"      # 3. Search
```

## Skills 2.0 Features

Several skills run as **forked subagents** (`context: fork`) for isolation:
- `/ai:search`, `/ai:entity`, `/ai:impact`, `/ai:lineage` - Explore agents (read-only)
- `/ai:onboard` - General-purpose agent (full capabilities)
- `/ai:patterns`, `/ai:services`, `/ai:validate` - Explore agents

This keeps your main conversation clean while heavy analysis runs in the background.
