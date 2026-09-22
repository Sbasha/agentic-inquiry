# AI Agent Testing Guide for agentic-inquiry Library

## Overview

This document serves as the **primary guide for agents performing tests** on the agentic-inquiry MCP server. It defines real-world use cases that AI agents need to perform when working with codebases, and provides clear references to detailed test procedures.

## How to Use This Guide

**For Agents Performing Tests:**

1. **Start with TEST_01** - Always run the smoke test first to verify core functionality
2. **Reference this document** - Understand the use case you're testing
3. **Follow the TEST_XX file** - Execute the detailed test procedure
4. **Document results** - Record outcomes in the specified format

**Document Structure:**
- **USE_CASES.md** (this file) - High-level overview and context for each use case
- **TEST_01_CORE_FUNCTIONALITY.md** - Smoke test (run first, always)
- **TEST_02 through TEST_14** - Detailed test procedures for each use case

## Quick Start for Testing

```
1. Read this guide to understand the use case
2. Run TEST_01_CORE_FUNCTIONALITY.md (smoke test)
3. If TEST_01 passes, proceed to specific use case tests
4. Follow the detailed steps in each TEST_XX.md file
5. Document results in test_results/ directory
```

---

## Test Execution Order

**IMPORTANT:** Always follow this order when testing:

1. **TEST_01_CORE_FUNCTIONALITY.md** - Smoke test (10-15 min) - **REQUIRED FIRST**
2. **TEST_02_ONBOARDING.md** - Most common starting point
3. **TEST_03_FEATURE_IMPLEMENTATION.md** - Most frequent workflow
4. **TEST_04_BUG_INVESTIGATION.md** - Critical debugging capability
5. **TEST_05_MAJOR_REFACTORING.md** - Complex operations
6. **TEST_06_KNOWLEDGE_BUILDING.md** - Learning over time
7. **TEST_07_CODE_REVIEW.md** - Quality assurance
8. **TEST_08_DOCUMENTATION_GENERATION.md** - Documentation tasks
9. **TEST_09_DEPENDENCY_ANALYSIS.md** - Maintenance tasks
10. **TEST_10_PERFORMANCE_INVESTIGATION.md** - Performance analysis
11. **TEST_11_API_DESIGN.md** - Advanced design tasks
12. **TEST_12_CODE_GRAPH.md** - Code relationship extraction and impact analysis
13. **TEST_13_DOCUMENT_GRAPH.md** - Document structural relationships
14. **TEST_14_SEMANTIC_GRAPH.md** - Vector similarity and semantic search

**If TEST_01 fails, stop and fix issues before proceeding to other tests.**

---

## Project Isolation Strategy (Required)

> **Added:** 2025-12-28

**CRITICAL:** Each test MUST use a unique `project_id` to ensure complete isolation. This prevents:
- Index contamination between tests
- Memory bleed from knowledge building tests
- Graph state conflicts
- False positives/negatives from shared state

### Project ID Naming Convention

Use the format: `ai_test{NN}_{slug}_{timestamp}`

| Test | Project ID Pattern | Example |
|------|-------------------|---------|
| TEST_01 | `ai_test01_core_{timestamp}` | `ai_test01_core_20251228_143022` |
| TEST_02 | `ai_test02_onboard_{timestamp}` | `ai_test02_onboard_20251228_143022` |
| TEST_03 | `ai_test03_feature_{timestamp}` | `ai_test03_feature_20251228_143022` |
| TEST_04 | `ai_test04_bug_{timestamp}` | `ai_test04_bug_20251228_143022` |
| TEST_05 | `ai_test05_refactor_{timestamp}` | `ai_test05_refactor_20251228_143022` |
| TEST_06 | `ai_test06_knowledge_{timestamp}` | `ai_test06_knowledge_20251228_143022` |
| TEST_07 | `ai_test07_review_{timestamp}` | `ai_test07_review_20251228_143022` |
| TEST_08 | `ai_test08_docs_{timestamp}` | `ai_test08_docs_20251228_143022` |
| TEST_09 | `ai_test09_deps_{timestamp}` | `ai_test09_deps_20251228_143022` |
| TEST_10 | `ai_test10_perf_{timestamp}` | `ai_test10_perf_20251228_143022` |
| TEST_11 | `ai_test11_api_{timestamp}` | `ai_test11_api_20251228_143022` |
| TEST_12 | `ai_test12_codegraph_{timestamp}` | `ai_test12_codegraph_20251228_143022` |
| TEST_13 | `ai_test13_docgraph_{timestamp}` | `ai_test13_docgraph_20251228_143022` |
| TEST_14 | `ai_test14_semantic_{timestamp}` | `ai_test14_semantic_20251228_143022` |

### Why Full Isolation?

1. **TEST_02 (Onboarding)** - MUST start with empty index to test cold start experience
2. **TEST_06 (Knowledge Building)** - Memories should not leak to other tests
3. **TEST_12-14 (Graph Tests)** - Need clean graph state to validate relationship extraction
4. **Reproducibility** - Each test can be re-run independently without affecting others
5. **Debugging** - Failed tests can be investigated without cross-contamination

### Implementation

When spawning a test subagent, pass the unique project_id:

```
Project ID: ai_test{NN}_{slug}_{timestamp}

The subagent should:
1. Create a new session with this project_id
2. All operations use this isolated project context
3. Results are written to test_results/ai/{timestamp}/{use_case_slug}/
```

### Session Creation Example

```python
# In each test subagent
session = await mcp.create_session(project_id="ai_test01_core_20251228_143022")
# All subsequent operations use this session
```

---

## ⚠️ MANDATORY: Data Requirements for Graph Tests (TEST_12-14)

> **CRITICAL: Graph tests WILL FAIL without proper data setup.**

**Each graph test file (TEST_12, TEST_13, TEST_14) now includes a MANDATORY pre-test data setup section that MUST be completed before running tests.** These sections include:

1. **Specific data thresholds** - Minimum entity and relationship counts
2. **STOP CONDITIONS** - When NOT to proceed with tests
3. **Verification steps** - How to confirm data is sufficient
4. **Prerequisites checklists** - Everything that must be true before starting

### Quick Reference: Minimum Thresholds

| Test | Metric | Minimum | Stop Action if NOT Met |
|------|--------|---------|------------------------|
| TEST_12 | `code_class` entities | ≥ 20 | Re-index full codebase |
| TEST_12 | `code_function` entities | ≥ 50 | Re-index full codebase |
| TEST_12 | `defines` relationships | ≥ 10 | Check AST parsing |
| TEST_12 | `imports` relationships | ≥ 20 | Ensure cross-file resolution |
| TEST_13 | `section` entities | ≥ 5 | Index documentation |
| TEST_13 | `contains` relationships | ≥ 5 | Verify hierarchy extraction |
| TEST_14 | `total_chunks` | ≥ 100 | Index more content |
| TEST_14 | `indexed_file_count` | ≥ 20 | Index full codebase |

### Why Tests Fail Without Proper Data

- **Empty results**: Graph traversal returns nothing if no relationships exist
- **False failures**: Tests designed for 1000+ relationships fail with 10 relationships
- **Misleading metrics**: Coverage percentages meaningless without baseline data

**ALWAYS run the MANDATORY setup section in each test file before executing tests.**

---

## Pre-Test Database Verification (Required for Graph Tests)

> **Added:** 2025-12-28

Before running TEST_12, TEST_13, or TEST_14, verify the database state to avoid false failures.

### Quick Check Protocol

```
# 1. Get project overview
get_project_info(session_id)

# Expected output for graph tests:
# - entities: > 0
# - relationships: > 0
# - index_health: "healthy"

# 2. Verify specific relationship types exist
list_entities(session_id, limit=5)
graph_traverse(session_id, start_id="[any_entity_id]", relationship_types=["contains"], max_depth=1)

# 3. If counts are 0 or entities missing:
add_knowledge(session_id, source=".", content_type="directory", force_reindex=True)
```

### Implementation Status Awareness

Each graph test file (TEST_12, TEST_13, TEST_14) has an **Implementation Status** section that documents:
- Which features are implemented and should pass
- Which features are NOT implemented and should be skipped

**Before testing:** Read the Implementation Status section in each test file to understand:
1. What relationships actually exist in the database
2. Which tests may fail due to unimplemented features (expected failures)
3. Which tests should definitely pass (actual bugs if they fail)

### Known Issues

| Issue ID | Affects | Description | Status |
|----------|---------|-------------|--------|
| SG-001 | TEST_14 | Hard content type filter blocks cross-content discovery | Active - Sprint 3 |

See individual test files for detailed issue tracking.

### Tool Parameter Usage Patterns

This section documents common tool parameters that are frequently misused during testing.

**`graph_traverse` - Entity Identification:**
- `start_id`: Accepts either:
  1. Full entity ID: `class::project_id::file_path::EntityName`
  2. Entity name: `SearchService` (case-insensitive fallback)
- **Best Practice:** First use `list_entities` to get actual entity IDs:
  ```
  list_entities(session_id, entity_type="class", limit=5)
  # Returns: [{"id": "class::test::path/file.py::SearchService", "name": "SearchService", ...}]

  # Then use the full ID:
  graph_traverse(session_id, start_id="class::test::path/file.py::SearchService", ...)
  ```
- If using just the name, ensure exact case matching or expect case-insensitive fallback

**`build_context` - Parameters:**
- Uses `query` parameter (NOT `task`)
- Example: `build_context(session_id, query="How does indexing work?", max_tokens=4000)`

**`search_code` - Filters:**
- When using with PostgreSQL backend, filters (language, symbol_type) work correctly
- Fixed: LIMIT parameter position bug resolved in v2.x

---

## Indexing Events

The `indexing_completed` event is the source of truth for indexing results. It contains:
- `chunks_indexed`, `entities_created`, `relationships_created`

**Always wait for this event before checking counts.** The `get_project_info` tool also includes `recent_indexing_events` to make this easy - check the last event to see if indexing is complete.

```python
# Wait for completion
events = get_events(session_id, event_types=["indexing_completed", "indexing_failed"])

# Event data has final counts
for event in events:
    if event.get("event_type") == "indexing_completed":
        data = event.get("data", {})
        print(f"Final counts: {data}")
```

---

## Parallel Execution Guidelines

When running multiple tests, agents may choose to execute tests in parallel for efficiency. This section provides guidelines to prevent hanging or resource exhaustion.

### Batch Size Recommendations

**Do NOT run all tests in parallel at once.** This can cause:
- Memory exhaustion from multiple concurrent indexing operations
- Context buildup that causes agents to hang
- Timeout failures due to resource contention

**Recommended batch sizes:**

| Test Complexity | Batch Size | Examples |
|-----------------|------------|----------|
| Simple/Fast (10-20 min) | 4-5 tests | TEST_01, TEST_02, TEST_06 |
| Medium (25-40 min) | 3-4 tests | TEST_03, TEST_04, TEST_07, TEST_12, TEST_13 |
| Complex (45+ min) | 2-3 tests | TEST_05, TEST_10, TEST_11 |

### Sequential vs Parallel Execution

**Parallel execution is OPTIONAL.** Agents should:
1. **Evaluate their capabilities** - Not all agents support efficient parallel execution
2. **Consider resource constraints** - Check available memory and CPU before parallelizing
3. **Default to sequential** - When in doubt, run tests one at a time

**When to run sequentially:**
- Agent does not have explicit parallel task support
- Running on resource-constrained systems
- First time running the test suite
- Debugging test failures

**When parallel execution is acceptable:**
- Agent explicitly supports parallel subagent spawning
- Sufficient system resources available
- Tests are independent and don't share sessions

### Incremental Output Requirements

**Subagents MUST write results incrementally.** Do NOT build up large context and write at the end. This prevents:
- Context overflow causing agent hangs
- Lost work if agent times out
- Difficulty tracking progress

**Required incremental output pattern:**
1. **Create output directory immediately** after starting a test
2. **Write TEST_LOG.md continuously** as steps complete
3. **Write ISSUES_LOG.md** as issues are discovered (don't batch)
4. **Write FINAL_REPORT.md** as the last step

**Example structure:**
```
test_results/ai/{timestamp}/
├── test_name/
│   ├── TEST_LOG.md      # Updated after each step
│   ├── ISSUES_LOG.md    # Updated as issues found
│   └── FINAL_REPORT.md  # Written at completion
```

### Timeout Handling

If a test is taking longer than its time estimate:
1. **Write current progress** to TEST_LOG.md
2. **Note incomplete steps** with "IN PROGRESS" status
3. **Do NOT retry automatically** - let the orchestrating agent decide

---

## Use Case 1: **Onboarding to a New Codebase**

**Test File:** `TEST_02_ONBOARDING.md`
**Priority:** Essential - Every agent starts here
**Time Estimate:** 20-30 minutes

### Scenario
An AI agent encounters a codebase for the first time and needs to understand its structure, purpose, and key components.

### Agent Needs
1. **High-level overview**: What does this codebase do?
2. **Architecture understanding**: How is the code organized?
3. **Key components**: What are the main modules/classes?
4. **Entry points**: Where does execution start?
5. **Common patterns**: What patterns are used?
6. **Dependencies**: What external libraries are used?

### agentic-inquiry Operations
- Index entire codebase
- Search for README, architecture docs, main modules
- Query knowledge graph for top-level entities
- Find patterns across the codebase
- Build context about project structure

### Success Metrics
- Agent can describe what the project does
- Agent identifies 3-5 key modules
- Agent understands code organization patterns
- Agent knows where to find specific functionality

### Testing This Use Case
See **TEST_02_ONBOARDING.md** for detailed test procedures including:
- Initial codebase exploration steps
- Architecture discovery workflow
- Component identification tests
- Success criteria validation
- Result documentation format

---

## Use Case 2: **Feature Implementation**

**Test File:** `TEST_03_FEATURE_IMPLEMENTATION.md`
**Priority:** High - Most common workflow
**Time Estimate:** 30-45 minutes

### Scenario
Agent is asked to implement a new feature (e.g., "Add support for JSON config files")

### Agent Needs
1. **Find related code**: Where is config handling currently?
2. **Understand patterns**: How are other formats handled?
3. **Identify insertion points**: Where should new code go?
4. **Check dependencies**: What libraries/modules are needed?
5. **Find tests**: How is similar functionality tested?

### agentic-inquiry Operations
- Semantic search: "configuration file loading"
- Entity understanding: ConfigLoader, Config classes
- Pattern finding: "file format handlers"
- Impact analysis: What depends on config system?
- Context building: Gather all relevant config code

### Success Metrics
- Agent finds existing config code within 3 queries
- Agent identifies the right pattern to follow
- Agent understands where to add new code
- Agent can list affected components

### Testing This Use Case
See **TEST_03_FEATURE_IMPLEMENTATION.md** for detailed test procedures including:
- Related code discovery workflow
- Pattern identification tests
- Integration point analysis
- Dependency checking steps
- Test discovery procedures

---

## Use Case 3: **Bug Investigation**

**Test File:** `TEST_04_BUG_INVESTIGATION.md`
**Priority:** Critical - Essential for debugging
**Time Estimate:** 25-40 minutes

### Scenario
Agent needs to investigate a bug: "Search results are empty for valid queries"

### Agent Needs
1. **Find search code**: Where is search implemented?
2. **Trace execution**: What's the flow from query to results?
3. **Find dependencies**: What components are involved?
4. **Check related issues**: Have similar bugs been fixed?
5. **Understand data flow**: How does data move through the system?

### agentic-inquiry Operations
- Hybrid search: "search query results empty"
- Entity analysis: SearchService, vector_search
- Relationship traversal: What calls SearchService?
- Memory recall: Previous similar issues
- Impact analysis: Dependencies of search components

### Success Metrics
- Agent finds search implementation in <2 queries
- Agent traces complete execution path
- Agent identifies all involved components
- Agent can suggest likely root causes

### Testing This Use Case
See **TEST_04_BUG_INVESTIGATION.md** for detailed test procedures including:
- Bug reproduction steps
- Code location discovery
- Execution tracing workflow
- Root cause analysis methods
- Fix validation procedures

---

## Use Case 4: **Major Refactoring**

**Test File:** `TEST_05_MAJOR_REFACTORING.md`
**Priority:** Medium - Complex but important
**Time Estimate:** 45-60 minutes

### Scenario
Agent needs to refactor the parser system to support streaming

### Agent Needs
1. **Find all parser code**: What needs to change?
2. **Understand current architecture**: How does it work now?
3. **Find all usages**: What calls the parsers?
4. **Assess impact**: What will break?
5. **Plan migration**: What's the sequence of changes?

### agentic-inquiry Operations
- Pattern analysis: Parser implementations
- Entity understanding: ParserChain, BaseParse
- Impact analysis: What depends on parser interface?
- Relationship queries: All files importing parsers
- Context building: Complete parser subsystem

### Success Metrics
- Agent identifies all parser classes
- Agent maps all parser call sites
- Agent quantifies blast radius
- Agent proposes migration steps

### Testing This Use Case
See **TEST_05_MAJOR_REFACTORING.md** for detailed test procedures including:
- Subsystem identification workflow
- Architecture analysis steps
- Impact assessment methods
- Migration planning procedures
- Refactoring validation tests

---

## Use Case 5: **Knowledge Building & Learning**

**Test File:** `TEST_06_KNOWLEDGE_BUILDING.md`
**Priority:** Medium - Enables improvement over time
**Time Estimate:** 20-30 minutes

### Scenario
Agent works on the codebase over time and needs to remember learnings

### Agent Needs
1. **Store insights**: "The parser chain uses chain-of-responsibility pattern"
2. **Recall patterns**: "How did we handle X before?"
3. **Track decisions**: "Why was Y implemented this way?"
4. **Build expertise**: Accumulate knowledge over sessions
5. **Share knowledge**: Help other agents/developers

### agentic-inquiry Operations
- Memory save: Important insights and patterns
- Memory recall: Query past learnings
- Event tracking: Record what was done
- Session management: Track work over time
- Context preservation: Resume where left off

### Success Metrics
- Agent recalls past insights accurately
- Agent builds on previous knowledge
- Agent avoids repeating mistakes
- Agent improves over time

### Testing This Use Case
See **TEST_06_KNOWLEDGE_BUILDING.md** for detailed test procedures including:
- Memory storage workflow
- Knowledge recall tests
- Pattern recognition validation
- Session continuity tests
- Learning progression measurement

---

## Use Case 6: **Code Review & Analysis**

**Test File:** `TEST_07_CODE_REVIEW.md`
**Priority:** Medium - Quality assurance
**Time Estimate:** 30-40 minutes

### Scenario
Agent reviews a pull request adding a new embedder

### Agent Needs
1. **Understand changes**: What's being added?
2. **Check patterns**: Does it follow existing patterns?
3. **Assess impact**: What else might be affected?
4. **Find similar code**: How are other embedders implemented?
5. **Verify completeness**: Are tests included?

### agentic-inquiry Operations
- Pattern finding: Existing embedder implementations
- Entity analysis: New classes/functions added
- Impact analysis: What depends on embedder interface?
- Hybrid search: Test patterns for embedders
- Context building: Related code for comparison

### Success Metrics
- Agent identifies pattern violations
- Agent finds missing components (tests, docs)
- Agent assesses architectural fit
- Agent provides specific feedback

### Testing This Use Case
See **TEST_07_CODE_REVIEW.md** for detailed test procedures including:
- Change analysis workflow
- Pattern compliance checking
- Impact assessment steps
- Completeness verification
- Feedback generation tests

---

## Use Case 7: **Documentation Generation**

**Test File:** `TEST_08_DOCUMENTATION_GENERATION.md`
**Priority:** Low-Medium - Helpful but not critical
**Time Estimate:** 25-35 minutes

### Scenario
Agent needs to generate documentation for the search module

### Agent Needs
1. **Find all search code**: What needs documenting?
2. **Understand purpose**: What does each component do?
3. **Map relationships**: How do components interact?
4. **Find examples**: How is it used?
5. **Identify edge cases**: What special handling exists?

### agentic-inquiry Operations
- Entity queries: All search-related classes
- Relationship traversal: Component interactions
- Code search: Usage examples
- Pattern analysis: Common usage patterns
- Context building: Complete module context

### Success Metrics
- Agent documents all public APIs
- Agent includes accurate examples
- Agent describes relationships
- Agent covers edge cases

### Testing This Use Case
See **TEST_08_DOCUMENTATION_GENERATION.md** for detailed test procedures including:
- Module discovery workflow
- API documentation steps
- Example generation tests
- Relationship mapping procedures
- Documentation quality validation

---

## Use Case 8: **Dependency Analysis**

**Test File:** `TEST_09_DEPENDENCY_ANALYSIS.md`
**Priority:** Medium - Important for maintenance
**Time Estimate:** 30-40 minutes

### Scenario
Agent needs to understand what would break if we change LanceDB

### Agent Needs
1. **Find direct usages**: What imports LanceDB?
2. **Find indirect usages**: What depends on those?
3. **Assess coupling**: How tight is the integration?
4. **Find abstractions**: Are there interface layers?
5. **Plan migration**: What's the upgrade path?

### agentic-inquiry Operations
- Impact analysis: LanceDBManager dependencies
- Relationship queries: Multi-level dependency chains
- Pattern analysis: Database abstraction patterns
- Entity understanding: DatabaseProtocol interface
- Context building: All database-related code

### Success Metrics
- Agent maps complete dependency tree
- Agent identifies abstraction boundaries
- Agent quantifies migration effort
- Agent suggests migration strategy

### Testing This Use Case
See **TEST_09_DEPENDENCY_ANALYSIS.md** for detailed test procedures including:
- Dependency discovery workflow
- Impact tree mapping
- Coupling assessment methods
- Abstraction layer identification
- Migration planning steps

---

## Use Case 9: **Performance Investigation**

**Test File:** `TEST_10_PERFORMANCE_INVESTIGATION.md`
**Priority:** Low - Specialized use case
**Time Estimate:** 35-50 minutes

### Scenario
Agent investigates why search is slow for large codebases

### Agent Needs
1. **Find performance-critical code**: Where's the bottleneck?
2. **Understand data flow**: How much data is processed?
3. **Find optimizations**: How are similar problems solved?
4. **Check configurations**: Are there tuning options?
5. **Identify alternatives**: What other approaches exist?

### agentic-inquiry Operations
- Semantic search: "performance optimization indexing"
- Entity analysis: SearchService, vector_search methods
- Memory recall: Previous performance work
- Pattern finding: Caching, batching patterns
- Context building: Performance-related code

### Success Metrics
- Agent identifies bottleneck location
- Agent finds existing optimizations
- Agent suggests concrete improvements
- Agent estimates impact

### Testing This Use Case
See **TEST_10_PERFORMANCE_INVESTIGATION.md** for detailed test procedures including:
- Bottleneck identification workflow
- Performance profiling steps
- Optimization discovery methods
- Configuration tuning tests
- Impact estimation procedures

---

## Use Case 10: **API Design & Extension**

**Test File:** `TEST_11_API_DESIGN.md`
**Priority:** Low - Advanced usage
**Time Estimate:** 40-55 minutes

### Scenario
Agent designs a new MCP tool for code navigation

### Agent Needs
1. **Understand existing tools**: What tools exist?
2. **Find patterns**: How are tools structured?
3. **Check conventions**: What's the naming/structure pattern?
4. **Identify requirements**: What infrastructure is needed?
5. **Plan integration**: How does it fit in?

### agentic-inquiry Operations
- Pattern analysis: Existing MCP tool implementations
- Entity understanding: BaseMCPTool, tool decorators
- Impact analysis: MCP server integration points
- Context building: Complete tool subsystem
- Memory recall: Tool design decisions

### Success Metrics
- Agent follows established patterns
- Agent uses correct abstractions
- Agent integrates properly with server
- Agent includes all required components

### Testing This Use Case
See **TEST_11_API_DESIGN.md** for detailed test procedures including:
- Existing pattern analysis
- Design convention discovery
- Integration point identification
- Infrastructure requirement assessment
- Design validation tests

---

## Use Case 11: **Code Graph Testing**

**Test File:** `TEST_12_CODE_GRAPH.md`
**Priority:** Medium - Essential for code relationship discovery
**Time Estimate:** 30 minutes

### Scenario
Agent needs to validate that code relationships (imports, calls, inheritance) are correctly extracted from source files, and that impact analysis can identify blast radius for changes.

### Agent Needs
1. **Entity extraction**: Are classes, functions, methods extracted from code?
2. **Import tracking**: Are import relationships captured across files?
3. **Call graph**: Are function/method call relationships tracked?
4. **Impact analysis**: Can we identify what would break if we change a component?
5. **Cross-file resolution**: Are imports resolved to actual target files?

### agentic-inquiry Operations
- `list_entities` with type filters (class, function, method)
- `understand_entity` to see dependencies and usage
- `analyze_impact` to compute blast radius
- `find_similar` for entity-based similarity

### Success Metrics
- 1000+ relationships extracted for medium codebase
- >80% cross-file resolution for imports
- Entity coverage: classes, functions, methods all extracted
- Traversal works at depth 2+
- Impact analysis identifies blast radius

### Testing This Use Case
See **TEST_12_CODE_GRAPH.md** for detailed test procedures including:
- Entity extraction validation
- Import chain traversal
- Call graph analysis
- Impact assessment
- Performance testing

---

## Use Case 12: **Document Graph Testing**

**Test File:** `TEST_13_DOCUMENT_GRAPH.md`
**Priority:** Medium - Essential for document structure navigation
**Time Estimate:** 20 minutes

### Scenario
Agent needs to validate that document structural relationships (sections, headings, hierarchy) are correctly extracted and can be navigated.

### Agent Needs
1. **Structure extraction**: Are headings and sections extracted?
2. **Hierarchy**: Are parent-child relationships (contains) captured?
3. **Siblings**: Can we navigate between sequential sections?
4. **Multi-format**: Do MD, PDF, DOCX, PPTX all work?
5. **Document isolation**: Are relationships within documents only?

### agentic-inquiry Operations
- `list_entities` with type filters (section, heading)
- `understand_entity` to see document hierarchy
- Index documents from multiple formats

### Success Metrics
- Section/header entities extracted from documents
- Containment relationships correct (parent-child)
- Sibling navigation works (next/previous)
- Multi-format support (MD, PDF, DOCX, PPTX)
- Document isolation maintained

### Testing This Use Case
See **TEST_13_DOCUMENT_GRAPH.md** for detailed test procedures including:
- Entity extraction validation
- Hierarchy navigation
- Sibling traversal
- Multi-format testing
- Edge case handling

---

## Use Case 13: **Semantic Graph Testing**

**Test File:** `TEST_14_SEMANTIC_GRAPH.md`
**Priority:** Medium - Essential for similarity discovery
**Time Estimate:** 20 minutes

### Scenario
Agent needs to validate that semantic similarity search works correctly, finding conceptually related content across code and documents.

### Agent Needs
1. **Embeddings**: Are embeddings generated for all content?
2. **Similarity search**: Does `find_similar` return relevant results?
3. **Cross-content**: Can we find similar items across code and docs?
4. **Threshold filtering**: Do similarity thresholds work?
5. **Context building**: Does `build_context` gather relevant content?

### agentic-inquiry Operations
- `find_similar` with various queries
- `build_context` for query-based context gathering
- `search_knowledge` for hybrid search

### Success Metrics
- Embeddings present for all indexed content
- Similarity scores are meaningful (high = semantically related)
- Cross-content search works (code and docs)
- Threshold filtering is effective
- Performance acceptable (<500ms for limit=10)

### Testing This Use Case
See **TEST_14_SEMANTIC_GRAPH.md** for detailed test procedures including:
- Basic similarity search
- Entity-based similarity
- Cross-content discovery
- Threshold testing
- Performance validation

---

## Testing Guidelines for Agents

### Before You Start Testing

1. **Read the use case** in this document to understand the context
2. **Check prerequisites** - Ensure MCP server is running and accessible
3. **Prepare test environment** - Have a suitable codebase ready
4. **Ensure fresh index** - See "Ensure Fresh Index" section below
5. **Review success criteria** - Know what you're measuring
6. **Review Parallel Execution Guidelines** - If running multiple tests, see the guidelines above for batch sizes and incremental output requirements

### Ensure Fresh Index (Required Before Testing)

> **CRITICAL: Each test MUST index the codebase itself.** Do NOT rely on pre-existing data.

### ⚠️ Graph Tests Require Full Codebase Indexing

**For TEST_12, TEST_13, TEST_14:** See the **MANDATORY: Pre-Test Data Setup** section in each test file. These sections have specific thresholds and STOP CONDITIONS that must be verified.

### ⛔ No Lightweight Indexing

**DO NOT** index only 2-3 files or a single subdirectory. Graph features require full codebase indexing.

```python
# ❌ WRONG - Will cause graph tests to fail
index_files(file_paths=["config.py", "service.py"])
add_knowledge(source="agentic_inquiry/config.py", content_type="code")

# ✅ CORRECT - Full codebase indexing
add_knowledge(source=".", content_type="code")  # From project root
add_knowledge(source="docs/", content_type="document")  # Plus documentation
```

**Minimum thresholds for graph tests:**
- `get_project_info` must show ≥500 chunks, ≥20 files
- TEST_12: ≥20 code_class entities, ≥50 code_function entities
- TEST_13: ≥5 section entities, ≥5 contains relationships
- TEST_14: ≥100 total_chunks with embeddings
>
> **Why?** Each test uses a unique `project_id` for isolation. Data indexed under a different
> project_id (e.g., `agentic-inquiry` or another test's project_id) will NOT be visible to your
> session. You must call `add_knowledge` to populate entities AND relationships for YOUR project_id.

**Step 1: Create Session with Unique Project ID**
```python
# Use the naming convention from Project Isolation Strategy above
project_id = "ai_test{NN}_{slug}_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Test description")
```

**Step 2: Index the Codebase (REQUIRED - not optional)**
```python
# This populates entities AND builds the relationship graph
# IMPORTANT: Use wait_for_completion=True to block until indexing finishes.
# Without it, add_knowledge returns immediately and searches will find nothing.
add_knowledge(
    session_id=session_id,
    source=".",
    content_type="directory",
    wait_for_completion=True,
    wait_timeout=1800
)
```

> **⚠️ Critical:** Directory indexing is async by default. If you omit `wait_for_completion=True`,
> you MUST poll `get_events(session_id, event_types=['indexing_completed'])` before proceeding.
> Searching before indexing completes will return 0 results.

**Step 3: Verify Index Health**
```
get_project_info(session_id)

Verify:
- index_health: "healthy" (not "stale" or "incomplete")
- status: "ready"
- entities: > 50 (confirms entity extraction worked)
- relationships: > 0 (confirms relationship graph is populated)

⚠️ If relationships = 0, indexing failed or was skipped. DO NOT PROCEED.
   The graph-dependent tools (analyze_impact, graph_traverse, understand_entity
   with dependencies) will return empty results.
```

**IMPORTANT: `get_project_info` Usage Guidelines**

Use `get_project_info` ONLY for:
- Health checks (index_health, status)
- Counts (chunks, entities, relationships exist)
- Project metadata

Do NOT use `get_project_info` for:
- Validating relationship types (imports, calls, contains, follows)
- Determining if specific features work

**Why?** The `get_project_info` tool reports aggregate statistics that may not accurately reflect functional behavior. For example, it may report relationship types incorrectly while the actual graph traversal tools work perfectly.

**For functional validation, use:**
- `list_entities` - verify entity extraction
- `understand_entity` - verify relationships work
- `graph_traverse` - verify graph navigation
- `analyze_impact` - verify impact analysis

**Step 2: If Index is Stale or Incomplete, Refresh**
```
add_knowledge(
    session_id=session_id,
    source=".",
    content_type="directory",
    force_reindex=True
)
```

**Step 3: Wait for Indexing to Complete**
```
# Poll until ready
get_project_info(session_id)

Verify:
- status: "ready"
- No active indexing operations
```

**Why This Matters:**
- Stale indexes may return incomplete or outdated search results
- Graph tests require relationships to be fully extracted
- Performance tests assume warm, complete indexes

### Test Category Reference

Different tests have different index requirements:

| Test Type | Index State | Setup Requirement |
|-----------|-------------|-------------------|
| **Cold Start (TEST_02)** | Empty | Do NOT pre-index - test measures onboarding from scratch |
| **Pre-Indexed (TEST_03-11)** | Fresh, complete | Refresh index before test if stale |
| **Graph Tests (TEST_12-14)** | Fresh, with verified relationships | **MANDATORY setup section** in each test file |

**Cold Start Tests (TEST_02):**
- Start with empty or no index
- Indexing happens as part of the test
- Measures true onboarding experience

**Pre-Indexed Tests (TEST_03-11):**
- Require existing, fresh index
- Test assumes all content is searchable
- Stale index will cause test failures

**Graph Tests (TEST_12-14):**

> **⚠️ IMPORTANT: Each graph test file has a MANDATORY: Pre-Test Data Setup section. DO NOT SKIP IT.**

- Require **full codebase** indexing (not partial)
- Must verify specific entity counts before proceeding
- Each test has **STOP CONDITIONS** - do not proceed if not met:
  - **TEST_12 (Code Graph):** ≥20 code_class, ≥50 code_function, ≥10 defines, ≥20 imports
  - **TEST_13 (Document Graph):** ≥5 section entities, ≥5 contains, ≥3 follows
  - **TEST_14 (Semantic Graph):** ≥100 total_chunks, ≥20 indexed files, embeddings verified

### During Testing

1. **Follow the TEST_XX.md file exactly** - Don't skip steps
2. **Document as you go** - Record results immediately (write to files incrementally, don't buffer)
3. **Note unexpected behavior** - Even if test passes
4. **Track time** - Stay within estimated time limits
5. **Be objective** - Report what actually happens, not what should happen
6. **Write output files incrementally** - Create TEST_LOG.md immediately and update after each step to prevent context overflow

### After Testing

1. **Complete all documentation** - Fill in all required fields
2. **Save results** - Use the specified output path format
3. **Review findings** - Summarize key observations
4. **Report issues** - Document any problems encountered
5. **Verify test cleanup** - Automated maintenance handles LanceDB cleanup (see below)

### Post-Test Storage Maintenance (Automated)

> **Note:** As of v1.0, LanceDB maintenance is **fully automated** via `MaintenanceManager`. Manual maintenance is no longer required but remains available for troubleshooting.

**Automatic Triggers:**
- `indexing.completed` - Runs after each indexing operation
- `project.closed` - Runs when a project is closed/session ends

**Configuration:** See `config/default.yaml` under `maintenance`:
```yaml
maintenance:
  enabled: true
  cleanup_retention_minutes: 60  # How long to keep old versions
  triggers:
    - indexing.completed
    - project.closed
```

**Manual Maintenance (Optional):**

If you need to run maintenance manually (e.g., for debugging or after disabling auto-maintenance):

```python
# Via MCP tool
result = await run_maintenance(
    session_id=session_id,
    cleanup_hours=0.01  # ~36 seconds - aggressive for test cleanup
)
```

**Verification:**
```bash
# Check index sizes
du -sh .agentic-inquiry/lancedb/*.lance | sort -rh

# Expected: ~100-500MB total
# Warning sign: > 1GB may indicate maintenance isn't running
```

**Troubleshooting:**
If disk usage grows unexpectedly, check:
1. `maintenance.enabled` is `true` in config
2. Event system is running (`events.enabled: true`)
3. See `docs/mcp/troubleshooting.md` for manual cleanup steps

### Test Result Documentation

Each test should produce a markdown file in `test_results/` with:
- Test metadata (date, duration, tester)
- Pass/fail status for each step
- Actual vs expected results
- Issues encountered
- Overall assessment
- Next steps or recommendations

---

## Common Testing Patterns

### Pattern 1: Discovery Workflow
Used in: Onboarding, Feature Implementation, Bug Investigation
1. Start with broad search
2. Narrow down to specific components
3. Understand relationships
4. Build complete context

### Pattern 2: Analysis Workflow
Used in: Code Review, Dependency Analysis, Performance Investigation
1. Identify target component
2. Map dependencies/relationships
3. Assess impact or quality
4. Generate recommendations

### Pattern 3: Learning Workflow
Used in: Knowledge Building, Documentation Generation
1. Gather information
2. Synthesize understanding
3. Store/document knowledge
4. Validate accuracy

### Pattern 4: Planning Workflow
Used in: Refactoring, API Design
1. Understand current state
2. Identify patterns and constraints
3. Design solution
4. Plan implementation steps

---

## Test Success Criteria

### General Criteria (All Tests)

A test passes if:
- **Completeness**: All required steps executed
- **Accuracy**: Results match expected outcomes (>80%)
- **Efficiency**: Completes within time estimate
- **Usability**: Agent doesn't get stuck or confused
- **Quality**: Output is useful for the intended purpose

### Specific Metrics by Use Case

| Use Case | Key Metric | Target |
|----------|------------|--------|
| Onboarding | Components identified | 3-5 key modules |
| Feature Implementation | Queries to find code | ≤ 3 queries |
| Bug Investigation | Execution path traced | Complete path |
| Refactoring | Blast radius quantified | All affected files |
| Knowledge Building | Recall accuracy | >90% |
| Code Review | Issues identified | All major issues |
| Documentation | API coverage | 100% public APIs |
| Dependency Analysis | Dependency tree depth | Complete tree |
| Performance | Bottleneck identified | Specific location |
| API Design | Pattern compliance | 100% |
| Graph Functionality | Relationship resolution rate | >70% confidence |

---

## Troubleshooting Test Failures

### Server Issues
- **Symptom**: Server not responding
- **Check**: Is MCP server running? `ps aux | grep ai`
- **Fix**: Restart server with `uv run ai [project]`

### Indexing Issues
- **Symptom**: No results or empty searches
- **Check**: Was indexing successful? Check file count
- **Fix**: Re-index with proper project path

### Search Issues
- **Symptom**: Irrelevant results
- **Check**: Is search term too broad/narrow?
- **Fix**: Refine query, try hybrid search

### Memory Issues
- **Symptom**: Can't recall stored information
- **Check**: Was memory saved to correct session?
- **Fix**: Verify session ID, check database

### Tool Issues
- **Symptom**: Tool not available or errors
- **Check**: Is tool registered? Check tool list
- **Fix**: Verify server configuration, check logs

---

## Test Maintenance

### When to Update Tests

Update test files when:
- **API changes** - Tool signatures or behavior changes
- **New features** - Additional capabilities added
- **Bug fixes** - Known issues are resolved
- **Performance improvements** - Time estimates change
- **Documentation updates** - Better procedures discovered

### Test Review Schedule

- **Monthly**: Review test results and update success criteria
- **Quarterly**: Validate all tests still reflect real-world usage
- **After major releases**: Update tests for new features
- **When patterns emerge**: Document common issues/solutions