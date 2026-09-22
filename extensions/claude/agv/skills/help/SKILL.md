---
name: help
description: List all agv commands and their descriptions. Use when looking for available agv capabilities.
argument-hint: "[command]"
allowed-tools: Read
---

# /agv:help

Quick reference for all Agent-Vault skills.

## All Skills

### Getting Started
| Skill | Description |
|-------|-------------|
| `/agv:onboard` | Intelligent onboarding - parallel index, explore, validate |
| `/agv:setup` | Configure storage backend (local/gcp/alloydb) |
| `/agv:status` | Show current project, index, and mode status |
| `/agv:env` | Manage isolated environments |

### Search & Discovery
| Skill | Description |
|-------|-------------|
| `/agv:index` | Index codebase for semantic search |
| `/agv:search` | Semantic search across code and docs |
| `/agv:search similar <entity>` | Find code similar to an entity |
| `/agv:entity` | Understand a code entity |
| `/agv:entity deps <name>` | Show entity dependencies |
| `/agv:entity refs <name>` | Show entity references |

### Analysis
| Skill | Description |
|-------|-------------|
| `/agv:patterns` | Discover architectural patterns |
| `/agv:lineage` | Trace data flow |
| `/agv:lineage gaps` | Find entities without full traceability |
| `/agv:impact` | Analyze change blast radius |
| `/agv:services` | Map service architecture |
| `/agv:validate` | Verify index accuracy |

### Knowledge
| Skill | Description |
|-------|-------------|
| `/agv:memory save` | Save a project insight |
| `/agv:memory recall` | Search saved memories |
| `/agv:memory list` | List all memories |

> **Dev tools** (testing, code review, server management) are in the `agv-dev` plugin.

## Quick Start

```bash
/agv:setup local myproject   # 1. Configure
/agv:index .                 # 2. Index
/agv:search "auth flow"      # 3. Search
```

## Skills 2.0 Features

Several skills run as **forked subagents** (`context: fork`) for isolation:
- `/agv:search`, `/agv:entity`, `/agv:impact`, `/agv:lineage` - Explore agents (read-only)
- `/agv:onboard` - General-purpose agent (full capabilities)
- `/agv:patterns`, `/agv:services`, `/agv:validate` - Explore agents

This keeps your main conversation clean while heavy analysis runs in the background.
