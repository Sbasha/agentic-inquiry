# Lessons Learned

From retrospective analysis (Jan 10, 2026). See source reports for full details.

## Technical

### High-Risk Areas
- Entity resolution needs shared logic (4+ fix sessions in 30 days)
- Graph relationships require explicit flush before analysis tools work
- Storage facade is central - bugs affect all operations

### Prevention
- Test with fresh database after changes
- Verify relationship count > 0 before graph analysis
- Run full test suite, not just targeted tests

**Source:** [01-TECHNICAL-REGRESSION-ANALYSIS.md](../../.sdd/specs/retro-01-10/reports/01-TECHNICAL-REGRESSION-ANALYSIS.md)

---

## Process

### What Works
- **Gemini reviews reduce tasks 63%** - Complex specs benefit from external review
- **Table specs correlate with 100% completion** - Structured format improves clarity
- **Parallel subagents** - 5 agents complete in 3 minutes what took 30 sequentially
- **Spec-Driven Development** - 50+ specs over project lifetime

### Recommendations
- Request Gemini review for specs with >5 implementation tasks
- Use table format for task specifications
- Parallelize independent tasks with subagents

**Source:** [02-PROCESS-WORKFLOW-ANALYSIS.md](../../.sdd/specs/retro-01-10/reports/02-PROCESS-WORKFLOW-ANALYSIS.md)

---

## Quality

### Gap Analysis
- **72% of bugs** were cross-tool integration issues
- **48% of entity bugs** were type mismatches between tools
- **Cold start testing** frequently missed

### Checklist Items
- [ ] Cross-tool integration tested
- [ ] Entity types consistent across tools
- [ ] Works with fresh (empty) database
- [ ] Error messages don't expose internal data

**Source:** [03-QUALITY-GAP-ANALYSIS.md](../../.sdd/specs/retro-01-10/reports/03-QUALITY-GAP-ANALYSIS.md)

---

## Tooling (agv MCP)

### MUST-HAVE Tools
- `search_knowledge` - Primary search, 8+/10 reliability
- `build_context` - Context gathering for tasks
- `save_memory` / `recall_memories` - 95%+ reliability

### Conditional Tools
- `analyze_impact` - **Requires relationships first**
- `graph_traverse` - **Requires relationships first**
- `understand_entity` - Verify entity type consistency

**Source:** [04-agv-TOOLING-ANALYSIS.md](../../.sdd/specs/retro-01-10/reports/04-agv-TOOLING-ANALYSIS.md)

---

## Architecture

### Key Decisions
- **27 protocols with @runtime_checkable** - Enables duck typing + type safety
- **StorageFacade pattern** - Single entry point reduces complexity
- **Filter AST consolidation** - Unified filter representation

See ADRs in `docs/adr/` for rationale.

**Source:** [05-ARCHITECTURE-DECISION-ANALYSIS.md](../../.sdd/specs/retro-01-10/reports/05-ARCHITECTURE-DECISION-ANALYSIS.md)

---

## Time Investment

### High-Effort Areas
- **Graph relationships** - Expect 2-3x estimated effort
- **Entity resolution** - Cross-tool consistency is hard
- **Test fixes** - 40% of all commits were test-related

### Mitigation
- Budget extra time for fragile areas
- Run full test suite early
- Test incrementally, verify counts frequently

**Source:** [06-TIME-SINK-ANALYSIS.md](../../.sdd/specs/retro-01-10/reports/06-TIME-SINK-ANALYSIS.md)

---

## Communication

### Effective Formats
- **Tables** for structured data (tasks, status, comparisons)
- **Bullet points** for actionable items
- **Code blocks** for examples
- **Callout boxes** for warnings

**Source:** [07-COMMUNICATION-PATTERN-ANALYSIS.md](../../.sdd/specs/retro-01-10/reports/07-COMMUNICATION-PATTERN-ANALYSIS.md)

---

## Testing Strategy

### Test Types by Purpose
- **Unit tests (55%)** - Pure logic, no I/O, < 100ms each
- **Integration (30%)** - Component interactions, < 1s each
- **E2E (10%)** - Real models, real disk, < 30s each
- **Agent UAT (5%)** - Manual execution by AI agents

### Fixture Naming
- `mock_*` - Unit tests (mocked dependencies)
- `integration_*` - Integration tests (real but lightweight)
- `real_*` - E2E tests (production-equivalent)

**Source:** [08-TEST-STRATEGY-ANALYSIS.md](../../.sdd/specs/retro-01-10/reports/08-TEST-STRATEGY-ANALYSIS.md)

---

## Quick Reference

| Category | Key Insight | Action |
|----------|-------------|--------|
| Technical | Entity resolution fragile | Test with fresh DB |
| Process | Gemini reviews -63% tasks | Use for >5 task specs |
| Quality | 72% cross-tool bugs | Test tool combinations |
| Tooling | analyze_impact needs relationships | Verify count > 0 first |
| Architecture | 27 protocols | See ADRs for rationale |
| Time | Graph = 2-3x effort | Budget accordingly |
| Communication | Tables work best | Use for specs |
| Testing | 40% commits = tests | Run full suite early |
