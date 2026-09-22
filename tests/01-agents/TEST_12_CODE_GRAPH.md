# Use Case 12: Code Graph

**Purpose:** Validate code relationship extraction, cross-file resolution, and impact analysis
**Output Path:** test_results/code_graph/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Can the graph reveal import chains, call hierarchies, and change impact?"

---

## Implementation Status

> **Last Updated:** 2026-01-09
> **Database Query:** `get_project_info` shows relationship types including imports, calls, defines, inherits

| Feature | Status | Notes |
|---------|--------|-------|
| Entity extraction (class/function/method) | **Implemented** | Via tree-sitter parser |
| `contains` relationships (file→entity) | **Implemented** | Stored during indexing |
| `imports` relationships | **Implemented** | Fixed: relationships now flushed after all files indexed |
| `calls` relationships | **Implemented** | Fixed: cross-file resolution works with full symbol registry |
| `defines` relationships | **Implemented** | Fixed: class→method relationships stored |
| `inherits` relationships | **Implemented** | Fixed: parent class resolution works |
| Cross-file resolution | **Implemented** | Fix: flush_relationships=False during file iteration, flush once at end |

### Fix Applied (2026-01-09)

The issue was that `process_document()` was called with default `flush_relationships=True` during directory indexing. This caused relationships to be flushed after each file, before symbols from later files were registered in the symbol registry.

**Root Cause:** In `agentic_inquiry/mcp/tools/knowledge.py:_index_directory_async`:
- Each file's relationships were flushed immediately after processing
- Cross-file symbols weren't in the registry yet when early files were flushed
- The final `flush_pending_relationships()` found an empty queue

**Fix:** Changed to `process_document(parsed_doc, flush_relationships=False)`, deferring all relationship resolution until after all files are indexed and the full symbol registry is populated.

### Success Criteria (Updated)

**All Features Now Implemented (Must Pass):**
- [ ] Entities extracted for Python files (code_class, code_function, code_method)
- [ ] `contains` relationships created (file → entity hierarchy)
- [ ] Entity names match source code
- [ ] Entity file paths are correct
- [ ] `imports` relationships stored in graph
- [ ] `calls` relationships stored in graph
- [ ] `defines` relationships stored in graph
- [ ] `inherits` relationships stored in graph
- [ ] Cross-file relationship traversal works

### Pre-Test Database Verification

Before running this test, execute `get_project_info` and verify:
- Entities: > 500 (minimum for meaningful test)
- Relationships: Check `relationships_by_type` for available types
- Should now include: imports, calls, defines, inherits (in addition to contains, follows)

**Expected relationship types after fix:**
- `contains`: file → entity hierarchy
- `follows`: document structure
- `imports`: cross-file import statements
- `calls`: function/method call relationships
- `defines`: class → method definitions
- `inherits`: class inheritance chains

---

## What This Tests

**Code Graph** extracts relationships from AST parsing during indexing:

| Aspect | Description |
|--------|-------------|
| **Scope** | In-file AND cross-file relationships |
| **How Created** | Tree-sitter parses imports, calls, inheritance |
| **Relationship Types** | `imports`, `calls`, `defines`, `inherits`, `uses` |
| **Entity Types** | `class`, `function`, `method`, `module`, `file` |
| **Storage** | `graph_entities` and `graph_relationships` tables |
| **Expected Count** | 1000s of relationships for a codebase |

### Key Feature: Cross-File Resolution

The code graph resolves references across files:
- `from agentic_inquiry.database import LanceDBManager` → links to actual class
- `self.db_manager.query()` → links to method definition
- `class SearchService(BaseService)` → links to parent class

### Success Criteria

- **Relationship Count:** 1000+ relationships for a medium codebase
- **Cross-File Resolution:** >80% of imports resolved to actual targets
- **Entity Coverage:** Classes, functions, methods all extracted
- **Traversal:** Can follow import/call chains at depth 2+
- **Impact Analysis:** Can identify blast radius for changes

**Time Limit:** 30 minutes
**Confidence Threshold:** 8/10

---

## CRITICAL: Test Data Requirements

**MUST use CODE files:**
- Python files (`.py`) - primary
- TypeScript files (`.ts`, `.tsx`) - if available
- Other tree-sitter supported languages

**Recommended test directory:** `agentic_inquiry/` or equivalent codebase

**DO NOT test with:**
- Markdown files
- PDF/DOCX documents
- Plain text files

Documents have NO import/call relationships. Testing code graph with documents will show 0 relationships - this is expected, not a bug.

---

## MANDATORY: Pre-Test Data Setup

> **WARNING: DO NOT SKIP THIS SECTION. Tests will return empty results without proper data.**

This section MUST complete successfully before running any tests. The graph tests require:
- Entities extracted from code files (classes, functions, methods)
- Relationships built between entities (imports, calls, defines, inherits)
- Full codebase indexing (not just a subset)

### Step 1: Create Session with Unique Project ID

```python
project_id = "ai_test12_codegraph_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Code graph test")
```

**Save the session_id** - you'll need it for all subsequent operations.

### Step 2: Index the FULL Codebase (REQUIRED)

```python
# Index the entire project root - NOT a subdirectory
add_knowledge(session_id=session_id, source=".", content_type="code", wait_for_completion=True)
```

**IMPORTANT:**
- Use `source="."` to index the full codebase from project root
- Do NOT use a subdirectory like `agentic_inquiry/` - this won't build cross-file relationships
- The `content_type="code"` ensures AST parsing for graph extraction

### Step 3: Wait for Indexing Completion

Indexing is **asynchronous**. Wait for the `indexing_completed` event - it contains the final counts.

```python
# Wait for completion event
events = get_events(session_id=session_id, event_types=["indexing_completed", "indexing_failed"])

# The event data has the truth:
# - chunks_indexed, entities_created, relationships_created
for event in events:
    if event.get("event_type") == "indexing_completed":
        data = event.get("data", {})
        print(f"Relationships: {data.get('relationships_created', 0)}")
```

**Don't trust `get_project_info` counts until this event fires.**

**Expected wait time:** 10 seconds to 5 minutes depending on codebase size.

### Step 4: Verify Data Thresholds (STOP CONDITIONS)

```python
info = get_project_info(session_id=session_id)
```

**MINIMUM THRESHOLDS - DO NOT PROCEED IF NOT MET:**

| Metric | Minimum | Stop Action |
|--------|---------|-------------|
| `entity_counts.code_class` | ≥ 20 | Re-index with full codebase |
| `entity_counts.code_function` | ≥ 50 | Re-index with full codebase |
| `relationships_by_type.defines` | ≥ 10 | Check AST parsing is enabled |
| `relationships_by_type.imports` | ≥ 20 | Ensure cross-file resolution |
| `index_health` | "healthy" | Investigate indexing errors |

**If thresholds NOT met:**
1. Check `.agentic-inquiry-server.log` for indexing errors
2. Verify source path is correct (should be `.` not a subdirectory)
3. Ensure Python files exist in the codebase
4. Re-run indexing with `add_knowledge(session_id, source=".", content_type="code")`

### Step 5: Document Your Setup

```
Test Environment:
Session ID: [id]
Project ID: [id]

Verification Results:
- entity_counts.code_class: [count] (min: 20)
- entity_counts.code_function: [count] (min: 50)
- relationships_by_type.defines: [count] (min: 10)
- relationships_by_type.imports: [count] (min: 20)
- index_health: [status]

Data Thresholds Met: [YES/NO]
Proceed with Tests: [YES/NO]
```

**STOP HERE if thresholds not met. Fix data issues before continuing.**

---

## Prerequisites Checklist

Before running tests, confirm ALL of these:

- [ ] MCP Server running and responding
- [ ] Session created with unique project_id
- [ ] Full codebase indexed (not subdirectory)
- [ ] Indexing completed (not just started)
- [ ] ≥20 code_class entities
- [ ] ≥50 code_function entities
- [ ] ≥10 defines relationships
- [ ] ≥20 imports relationships
- [ ] index_health = "healthy"

### Verify Test Data

Before running tests, verify code is indexed:

```
get_project_info(session_id)

Expected output (health check only):
- Entities: 1000+ (classes, functions, methods)
- Relationships: 1000+ (any count > 1000 indicates data exists)
- index_health: "healthy"
- status: "ready"
```

**NOTE:** Use `get_project_info` only for health checks (counts, status). Do NOT use it to validate relationship types - that tool may report statistics that don't reflect actual functionality. Relationship type validation must be done through functional tools like `understand_entity`, `analyze_impact`, and `graph_traverse`.

**Document Your Setup:**
```
Test Environment:
Session ID: [id]
Project ID: [id]

Code Content:
Path: [e.g., agentic_inquiry/]
Files Indexed: [count]
Languages: [Python, TypeScript, etc.]

Pre-Test Counts:
Entities: [count]
Relationships: [count]
- imports: [count]
- calls: [count]
- defines: [count]
- inherits: [count]
```

---

## Part 1: Entity Extraction

### T1.1: Verify Code Entities

**Objective:** Confirm code entities are extracted correctly

**Execute:**
```
list_entities(session_id, entity_type="class", limit=20)
list_entities(session_id, entity_type="function", limit=20)
list_entities(session_id, entity_type="method", limit=20)
```

**Success Criteria:**
- Classes extracted with correct names
- Functions extracted with file locations
- Methods linked to parent classes
- No document entities (sections, headers) in results

**Document:**
```
Entity Extraction:

Classes Found: [count]
Sample Classes:
1. [ClassName] - [file_path]
2. [ClassName] - [file_path]
3. [ClassName] - [file_path]

Functions Found: [count]
Sample Functions:
1. [function_name] - [file_path]
2. [function_name] - [file_path]

Methods Found: [count]
Sample Methods:
1. [ClassName.method_name] - [file_path]
2. [ClassName.method_name] - [file_path]

Entity Type Distribution:
- class: [count]
- function: [count]
- method: [count]
- module: [count]
- file: [count]

Status: [PASS/FAIL]
```

---

### T1.2: Verify Relationship Types via Functional Testing

**Objective:** Confirm relationship types work through actual graph operations

**IMPORTANT:** Do NOT use `get_project_info` for relationship type validation. That tool reports statistics which may not reflect actual functionality. Instead, test relationships through functional tools.

**Execute:**
```
# Test imports via understand_entity
understand_entity(session_id, entity="LanceDBManager", include_dependencies=True)
# Look for: imports relationships in dependencies

# Test calls via analyze_impact
analyze_impact(session_id, entity="hybrid_search", max_depth=1)
# Look for: calls relationships in impact results

# Test defines via graph_traverse
graph_traverse(session_id, start_id="[class_entity_id]", relationship_types=["defines"], max_depth=1)
# Look for: class-to-method definitions

# Test inherits (if applicable)
find_similar(session_id, query="BaseService", entity_type="class")
understand_entity(session_id, entity="[child_class]", include_dependencies=True)
# Look for: inherits relationships
```

**Success Criteria:**
- `understand_entity` returns imports in dependency list
- `analyze_impact` shows call relationships in results
- `graph_traverse` can filter by relationship type
- Relationship metadata includes confidence scores
- Cross-file relationships traceable (source file ≠ target file)

**Document:**
```
Relationship Types (Functional Validation):

Import Relationships:
- Tool: understand_entity(LanceDBManager)
- Found imports: [yes/no]
- Sample: imports [module] from [file]
- Cross-file: [yes/no]

Call Relationships:
- Tool: analyze_impact(hybrid_search)
- Found calls: [yes/no]
- Sample: calls [function] in [file]
- Cross-file: [yes/no]

Defines Relationships:
- Tool: graph_traverse with relationship_types=["defines"]
- Found defines: [yes/no]
- Sample: [Class] defines [method]

Inherits Relationships:
- Tool: understand_entity on child class
- Found inherits: [yes/no]
- Sample: [ChildClass] inherits [ParentClass]

Functional Validation Summary:
- imports work: [PASS/FAIL]
- calls work: [PASS/FAIL]
- defines work: [PASS/FAIL]
- inherits work: [PASS/FAIL]

Status: [PASS/FAIL]
```

---

## Part 2: Import Relationship Traversal

### T2.1: Trace Import Chain

**Objective:** Follow import relationships from a core class

**Execute:**
```
understand_entity(session_id, entity="LanceDBManager", include_dependencies=True)
```

Or traverse manually:
```
analyze_impact(session_id, entity="LanceDBManager", max_depth=2)
```

**Success Criteria:**
- Direct imports identified (what LanceDBManager imports)
- Direct importers identified (what imports LanceDBManager)
- Import chain traceable to depth 2+
- File paths correctly resolved

**Document:**
```
Import Chain Analysis:

Target Entity: LanceDBManager
Entity Type: class
File: agentic_inquiry/database/lancedb_manager.py

What LanceDBManager Imports:
1. [module/class] from [file]
   - Confidence: [score]
2. [module/class] from [file]
   - Confidence: [score]
[Continue...]

What Imports LanceDBManager:
1. [class/module] in [file]
2. [class/module] in [file]
3. [class/module] in [file]
[Continue...]

Total Importers: [count]

Import Chain (depth=2):
LanceDBManager
├── imports: [module1]
│   └── imports: [module1a]
├── imports: [module2]
│   └── imports: [module2a]
└── imported_by: [count] files

Resolution Quality:
- Resolved to actual files: [count]
- External (stdlib/packages): [count]
- Unresolved: [count]

Status: [PASS/FAIL]
```

---

### T2.2: Verify Cross-File Resolution

**Objective:** Confirm imports resolve to actual target files

**Execute:** Pick several import relationships and verify:
- Source file exists
- Target file exists
- Target symbol exists in target file

**Success Criteria:**
- >80% of imports resolve to actual targets
- Resolution confidence scores are meaningful
- Unresolved imports are external (stdlib, third-party)

**Document:**
```
Cross-File Resolution Verification:

Sample 1:
- Source: [file] imports [symbol]
- Target: [resolved_file]
- Symbol Found: [yes/no]
- Confidence: [score]

Sample 2:
- Source: [file] imports [symbol]
- Target: [resolved_file]
- Symbol Found: [yes/no]
- Confidence: [score]

Sample 3:
- Source: [file] imports [symbol]
- Target: [resolved_file]
- Symbol Found: [yes/no]
- Confidence: [score]

Resolution Statistics:
- Total imports: [count]
- Resolved to internal: [count] ([%])
- External (stdlib): [count] ([%])
- External (third-party): [count] ([%])
- Unresolved: [count] ([%])

Resolution Rate: [%]
Status: [PASS/FAIL]
```

---

## Part 3: Call Graph Traversal

### T3.1: Trace Call Relationships

**Objective:** Follow function/method call relationships

**Execute:**
```
understand_entity(session_id, entity="search_knowledge", include_usage=True)
```

**Success Criteria:**
- Functions this entity calls identified
- Functions that call this entity identified
- Call chain traceable
- Method calls within classes tracked

**Document:**
```
Call Graph Analysis:

Target Entity: [function/method name]
Entity Type: [function/method]
File: [file_path]

Functions Called (outgoing):
1. [function_name] in [file]
   - Call Location: line [X]
2. [function_name] in [file]
   - Call Location: line [X]
[Continue...]

Called By (incoming):
1. [function_name] in [file]
2. [function_name] in [file]
[Continue...]

Call Statistics:
- Direct calls: [count]
- Direct callers: [count]
- Depth 2 calls: [count]

Status: [PASS/FAIL]
```

---

### T3.2: Method Calls Within Classes

**Objective:** Verify method-to-method calls are tracked

**Execute:** Find a class with internal method calls and verify:
```
understand_entity(session_id, entity="IndexingPipeline", include_dependencies=True)
```

**Success Criteria:**
- `self.method()` calls detected
- Links between methods in same class
- Distinguishes internal vs external calls

**Document:**
```
Internal Method Calls:

Class: IndexingPipeline
File: agentic_inquiry/indexing/pipeline.py

Method Call Map:
- process_document() calls:
  - self._validate_input()
  - self._parse_content()
  - self._generate_embeddings()

- _parse_content() calls:
  - self.parser_chain.parse()

Internal Calls Found: [count]
External Calls Found: [count]

Status: [PASS/FAIL]
```

---

## Part 4: Impact Analysis

### T4.1: Blast Radius Assessment

**Objective:** Identify all code affected by changing a component

**Execute:**
```
analyze_impact(session_id, entity="LanceDBManager", max_depth=2)
```

**Success Criteria:**
- All direct dependents found
- Indirect dependents found (depth 2)
- Affected files listed
- Critical paths identified

**Document:**
```
Impact Analysis:

Target: LanceDBManager
Change Type: Hypothetical modification

Direct Impact (Level 1):
Components: [count]
Files: [count]

1. SearchService - agentic_inquiry/search/service.py
   - Relationship: imports
   - Impact: Would need import update

2. IndexingPipeline - agentic_inquiry/indexing/pipeline.py
   - Relationship: imports
   - Impact: Would need import update

[Continue...]

Indirect Impact (Level 2):
Components: [count]
Files: [count]

1. [component] via [intermediate]
2. [component] via [intermediate]

Blast Radius Summary:
- Level 1: [count] components in [count] files
- Level 2: [count] components in [count] files
- Total Affected: [count] unique files

Critical Paths:
1. LanceDBManager → SearchService → MCP search_knowledge tool
2. LanceDBManager → IndexingPipeline → MCP add_knowledge tool

Risk Assessment: [HIGH/MEDIUM/LOW]
Status: [PASS/FAIL]
```

---

### T4.2: Inheritance Impact

**Objective:** Trace impact through class inheritance

**Execute:** Find a base class and check inheritance chain:
```
find_similar(session_id, query="BaseService", entity_type="class")
understand_entity(session_id, entity="BaseService", include_usage=True)
```

**Success Criteria:**
- Child classes identified via `inherits` relationship
- Changes to base class would affect all children
- Multiple inheritance levels tracked

**Document:**
```
Inheritance Analysis:

Base Class: [class_name]
File: [file_path]

Child Classes (inherits from this):
1. [ChildClass] - [file]
2. [ChildClass] - [file]
[Continue...]

Inheritance Depth:
- Direct children: [count]
- Grandchildren: [count]

Impact of Base Class Change:
- All [count] child classes affected
- Files affected: [count]

Status: [PASS/FAIL]
```

---

## Part 5: Entity Resolution

### T5.1: Resolve Ambiguous Names

**Objective:** Test resolution when multiple entities have same name

**Execute:**
```
find_similar(session_id, query="Config", entity_type="class")
find_similar(session_id, query="process", entity_type="function")
```

**Success Criteria:**
- Multiple matches returned
- Results ranked by relevance
- Type filtering works
- Context helps disambiguation

**Document:**
```
Ambiguous Name Resolution:

Query: "Config"
Results:
1. Config (class) - agentic_inquiry/config.py
   - Relevance: [score]
2. [other Config references]

Query: "process" (type=function)
Results:
1. process_document - agentic_inquiry/indexing/pipeline.py
2. process_chunk - agentic_inquiry/parsers/...
3. [other matches]

Disambiguation:
- Type filter reduces results: [yes/no]
- Most relevant ranked first: [yes/no]

Status: [PASS/FAIL]
```

---

## Part 6: Performance

### T6.1: Traversal Performance

**Objective:** Verify acceptable performance at various depths

**Execute:** Time traversal operations:
```
# Depth 1
analyze_impact(session_id, entity="LanceDBManager", max_depth=1)

# Depth 2
analyze_impact(session_id, entity="LanceDBManager", max_depth=2)

# Depth 3 (if supported)
analyze_impact(session_id, entity="LanceDBManager", max_depth=3)
```

**Success Criteria:**
- Depth 1: <1 second
- Depth 2: <5 seconds
- Depth 3: <15 seconds (or graceful timeout)

**Document:**
```
Traversal Performance:

Entity: LanceDBManager
Total Relationships in Graph: [count]

Depth 1:
- Time: [ms]
- Entities Found: [count]
- Status: [PASS/FAIL]

Depth 2:
- Time: [ms]
- Entities Found: [count]
- Status: [PASS/FAIL]

Depth 3:
- Time: [ms]
- Entities Found: [count]
- Status: [PASS/FAIL]

Performance Acceptable: [yes/no]
```

---

## Final Evaluation

### Test Summary

```
Test Results:

Part 1: Entity Extraction
- T1.1 Verify Code Entities: [PASS/FAIL]
- T1.2 Verify Relationship Types: [PASS/FAIL]

Part 2: Import Traversal
- T2.1 Trace Import Chain: [PASS/FAIL]
- T2.2 Cross-File Resolution: [PASS/FAIL]

Part 3: Call Graph
- T3.1 Trace Call Relationships: [PASS/FAIL]
- T3.2 Method Calls Within Classes: [PASS/FAIL]

Part 4: Impact Analysis
- T4.1 Blast Radius Assessment: [PASS/FAIL]
- T4.2 Inheritance Impact: [PASS/FAIL]

Part 5: Entity Resolution
- T5.1 Resolve Ambiguous Names: [PASS/FAIL]

Part 6: Performance
- T6.1 Traversal Performance: [PASS/FAIL]

Tests Passed: [X]/10
```

### Key Metrics

```
Code Graph Metrics:

Entities:
- Total: [count]
- Classes: [count]
- Functions: [count]
- Methods: [count]

Relationships:
- Total: [count]
- imports: [count]
- calls: [count]
- defines: [count]
- inherits: [count]

Resolution:
- Cross-file rate: [%]
- Average confidence: [score]

Performance:
- Depth 2 traversal: [ms]
```

### Production Readiness

**Critical Checks:**
- [ ] 1000+ relationships extracted
- [ ] >80% cross-file resolution
- [ ] Import chains traceable
- [ ] Call graphs accurate
- [ ] Impact analysis works
- [ ] Performance acceptable

**Pass/Fail:** [PASS/FAIL]

---

## Summary

### What Worked Well
```
1. [First strength]
2. [Second strength]
3. [Third strength]
```

### Issues Found
```
1. [First issue]
2. [Second issue]
```

### Recommendations
```
1. [First recommendation]
2. [Second recommendation]
```

---

**Test Completed:** [YYYY-MM-DD HH:MM]
**Duration:** [minutes]
**Confidence:** [X]/10
