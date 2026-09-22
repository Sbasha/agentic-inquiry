---
name: index
description: Index a codebase for semantic search. Use when setting up ai for a project, updating the index after changes, or checking index status.
argument-hint: "[path] [--project-id name] [status]"
allowed-tools: Bash, Read
---

# /ai:index

Index code and documentation for semantic search.

## Your Task

Execute indexing command: **$ARGUMENTS** (default: index current directory)

## Current State

- Existing index: !`ai index status 2>/dev/null || echo "No index found"`

## How to Execute

Parse `$ARGUMENTS`:
- `status` → Show index statistics only
- `<path>` → Index that path
- (empty) → Index current directory

```bash
# Index current directory
ai index .

# Index specific path
ai index <path>

# Check status
ai index status
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
- `/ai:search "main entry point"` - Try a search
- `/ai:validate` - Verify index quality
