---
name: index
description: Index a codebase for semantic search. Use when setting up agv for a project, updating the index after changes, or checking index status.
argument-hint: "[path] [--project-id name] [status]"
allowed-tools: Bash, Read
---

# /agv:index

Index code and documentation for semantic search.

## Your Task

Execute indexing command: **$ARGUMENTS** (default: index current directory)

## Current State

- Existing index: !`agv index status 2>/dev/null || echo "No index found"`

## How to Execute

Parse `$ARGUMENTS`:
- `status` → Show index statistics only
- `<path>` → Index that path
- (empty) → Index current directory

```bash
# Index current directory
agv index .

# Index specific path
agv index <path>

# Check status
agv index status
```

## What Gets Indexed

- **Code**: Functions, classes, methods with relationships
- **Docs**: Markdown, text files, docstrings
- **Structure**: Import graphs, call hierarchies

## After Indexing

Report the results:
- Total entities indexed (by type)
- Files processed
- Time taken
- Any warnings or skipped files

Suggest next steps:
- `/agv:search "main entry point"` - Try a search
- `/agv:validate` - Verify index quality
