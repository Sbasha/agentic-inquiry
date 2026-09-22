---
name: quality
description: Agent-Vault quality standards - checklists, fragile areas, fix-break prevention, and agv tool guidance. Auto-loads when assessing code quality.
user-invocable: false
---

# agv Quality Standards

Quality checklists and risk awareness for Agent-Vault development.

## When to Use

- Before completing any implementation
- When modifying fragile areas
- During code review
- Debugging regressions

## Quality Checklist

Before completing any implementation task:

### Integration
- [ ] Cross-tool integration tested (tools work together)
- [ ] Entity resolution consistent across all MCP tools
- [ ] Async operations verified non-blocking (no `time.sleep()`)

### Graph & Relationships
- [ ] Relationship count > 0 after indexing
- [ ] `flush_relationships()` called before graph analysis
- [ ] Entity types consistent (same entity = same type everywhere)

### Data & Schema
- [ ] Field names match schema (check for renames)
- [ ] Parser metadata only contains allowed types
- [ ] FTS table initialized (test with fresh database)

### Cold Start
- [ ] Works with empty database
- [ ] Works with fresh index (no prior data)
- [ ] Error messages helpful when prerequisites missing

## Fragile Areas

High regression rates - require extra attention:

| File | Risk | What Breaks | Prevention |
|------|------|-------------|------------|
| `relationship_resolver.py` | HIGH | Entity resolution across tools | Test with fresh index |
| `graph_builder.py` | HIGH | Relationship extraction | Check relationship count > 0 |
| `storage/facade.py` | HIGH | Multi-backend coordination | Test vector + graph ops |
| `mcp/tools/search.py` | MEDIUM | Search result consistency | Verify FTS + vector + graph |
| `mcp/tools/analysis.py` | MEDIUM | Graph traversal, impact | Ensure relationships flushed |
| `embeddings/service.py` | MEDIUM | Embedding generation | Test varied input sizes |

## Fix-Break Cycle Prevention

When modifying fragile areas:

1. **Search for ALL usages** before changing signatures
   ```bash
   grep -r "function_name" --include="*.py"
   ```

2. **Test with fresh database**
   - Delete `.agv/` and re-index
   - Cold start reveals hidden dependencies

3. **Verify cross-tool consistency**
   - Same entity → same ID in all tools
   - Same entity → same type in all tools

4. **Run full test suite**
   ```bash
   uv run --env-file .env pytest  # Not just specific tests
   ```

5. **Check async/blocking patterns**
   - Search for `time.sleep()`, blocking calls
   - Use `asyncio.sleep()` and proper awaits

6. **Verify relationship graph**
   - Count must be > 0
   - Relationships must have valid source/target

## agv Tool Effectiveness

From usage analysis:

| Tool | Verdict | Notes |
|------|---------|-------|
| `search_knowledge` | MUST-HAVE | Primary search, 8+/10 reliability |
| `build_context` | MUST-HAVE | Context gathering, use `depth: focused` |
| `save_memory` | MUST-HAVE | Persistence, importance 0.7+ for retention |
| `recall_memories` | MUST-HAVE | Retrieval, 95%+ reliability |
| `find_similar` | RECOMMENDED | Semantic search for patterns |
| `list_entities` | RECOMMENDED | Entity browsing, stable |
| `analyze_impact` | RECOMMENDED | Requires relationships first |
| `understand_entity` | RECOMMENDED | Verify entity type consistency |
| `graph_traverse` | RECOMMENDED | Requires relationships first |

### Graph Tool Prerequisites
1. Indexing must complete successfully
2. Relationships must be flushed
3. Verify entities exist with `list_entities`
