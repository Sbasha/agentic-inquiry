# Use Case 13: Document Graph

**Purpose:** Validate in-document structural relationship extraction and navigation
**Output Path:** test_results/document_graph/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Can the graph reveal document structure and enable navigation?"

---

## Implementation Status

> **Last Updated:** 2025-12-28
> **Database Query:** `get_project_info` shows structural relationships (contains, follows)

| Feature | Status | Notes |
|---------|--------|-------|
| Entity extraction (section/header/file) | **Implemented** | Via document parsers |
| `contains` relationships (file→section) | **Implemented** | ~52 relationships in test DB |
| `follows` relationships (section→section) | **Implemented** | ~48 relationships in test DB |
| `next_sibling` relationships | **NOT IMPLEMENTED** | Structural sibling navigation not stored |
| `previous_sibling` relationships | **NOT IMPLEMENTED** | Structural sibling navigation not stored |
| `references` relationships | **NOT IMPLEMENTED** | Cross-document references not extracted |

### Success Criteria (Updated)

**Implemented Features (Must Pass):**
- [ ] Section/header entities extracted from documents
- [ ] `contains` relationships created (file contains sections)
- [ ] `follows` relationships created (sequential sections)

**Not Yet Implemented (Expected to Fail - SKIP):**
- [ ] `next_sibling` relationships - SKIP until parser stores to graph
- [ ] `previous_sibling` relationships - SKIP until parser stores to graph
- [ ] `references` relationships - SKIP until cross-doc linking implemented

### Pre-Test Database Verification

**REQUIRED:** Before running tests, verify actual database state:

```
# Verify entities exist
list_entities(session_id, entity_type="section", limit=5)

# Verify relationships via functional test
graph_traverse(session_id, start_id="[any_file_entity_id]", relationship_types=["contains"], max_depth=1)

# Expected: Entities and contains relationships exist
# If empty: Re-index document files with structure extraction enabled
```

---

## What This Tests

**Document Graph** extracts structural relationships within documents during parsing:

| Aspect | Description |
|--------|-------------|
| **Scope** | In-document ONLY (no cross-document relationships) |
| **How Created** | Parser extracts headers, sections, nesting structure |
| **Relationship Types** | `contains`, `next_sibling`, `previous_sibling`, `references` |
| **Entity Types** | `section`, `header`, `paragraph`, `list_item`, `file` |
| **Storage** | `graph_entities` and `graph_relationships` tables |
| **Expected Count** | Lower than code graph (structural, not semantic) |

### Key Difference from Code Graph

Documents do NOT have cross-document relationships like code:
- Code: `file_a.py` imports `file_b.py` → cross-file link
- Docs: `doc_a.md` does NOT import `doc_b.md` → no cross-file link

Document relationships are **structural**:
- `# Section 1` contains `## Subsection 1.1`
- `## Subsection 1.1` is followed by `## Subsection 1.2`

### Success Criteria

- **Entity Extraction:** Headers, sections extracted with hierarchy
- **Containment:** Parent-child relationships correct
- **Siblings:** Next/previous section navigation works
- **Nesting:** Multi-level hierarchy preserved (h1 > h2 > h3)
- **No Cross-Doc:** Relationships stay within single document

**Time Limit:** 20 minutes
**Confidence Threshold:** 8/10

---

## CRITICAL: Test Data Requirements

**MUST use DOCUMENT files:**
- Markdown files (`.md`) - with headers/sections
- PDF files (`.pdf`) - with structure
- Word documents (`.docx`) - with headings
- PowerPoint (`.pptx`) - with slides

**Recommended test directory:** `tests/parsers/samples/docs/`

**DO NOT expect:**
- Import relationships
- Call relationships
- Cross-document links (unless explicit references exist)

Documents have STRUCTURAL relationships only. Expecting code-style relationships from documents will show 0 results - this is expected, not a bug.

---

## MANDATORY: Pre-Test Data Setup

> **WARNING: DO NOT SKIP THIS SECTION. Tests will return empty results without proper data.**

This section MUST complete successfully before running any tests. The document graph tests require:
- Document entities extracted (sections, headers, files)
- Structural relationships built (contains, follows)
- Documents with hierarchical structure (headings/sections)

### Step 1: Create Session with Unique Project ID

```python
project_id = "ai_test13_docgraph_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Document graph test")
```

**Save the session_id** - you'll need it for all subsequent operations.

### Step 2: Index Documents (REQUIRED)

```python
# Index documentation directory with structured documents
add_knowledge(session_id=session_id, source="docs/", content_type="document", wait_for_completion=True)
```

**IMPORTANT:**
- Index a directory with Markdown files that have headers (# ## ###)
- Can also include PDF, DOCX files with headings
- The `content_type="document"` ensures structure extraction
- If no `docs/` directory exists, use an alternative:
  - `tests/parsers/samples/` - sample documents
  - Or any directory with .md files containing headers

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

**Note:** Flat documents without headers won't have structural relationships - that's expected.

### Step 4: Verify Data Thresholds (STOP CONDITIONS)

```python
info = get_project_info(session_id=session_id)
```

**MINIMUM THRESHOLDS - DO NOT PROCEED IF NOT MET:**

| Metric | Minimum | Stop Action |
|--------|---------|-------------|
| `entity_counts.section` | ≥ 5 | Index docs with headers |
| `entity_counts.file` | ≥ 2 | Index more documents |
| `relationships_by_type.contains` | ≥ 5 | Check document parsing |
| `relationships_by_type.follows` | ≥ 3 | Ensure sequential extraction |
| `index_health` | "healthy" | Investigate indexing errors |

**If thresholds NOT met:**
1. Check `.agentic-inquiry-server.log` for parsing errors
2. Verify documents have headers (# ## ###) not just plain text
3. Ensure Markdown/PDF/DOCX files exist in the indexed path
4. Re-run indexing with correct source path

### Step 5: Document Your Setup

```
Test Environment:
Session ID: [id]
Project ID: [id]

Verification Results:
- entity_counts.section: [count] (min: 5)
- entity_counts.file: [count] (min: 2)
- relationships_by_type.contains: [count] (min: 5)
- relationships_by_type.follows: [count] (min: 3)
- index_health: [status]

Documents Indexed:
- Markdown: [count]
- PDF: [count]
- DOCX: [count]

Data Thresholds Met: [YES/NO]
Proceed with Tests: [YES/NO]
```

**STOP HERE if thresholds not met. Fix data issues before continuing.**

---

## Prerequisites Checklist

Before running tests, confirm ALL of these:

- [ ] MCP Server running and responding
- [ ] Session created with unique project_id
- [ ] Documents indexed (with headers/structure)
- [ ] Indexing completed (not just started)
- [ ] ≥5 section entities
- [ ] ≥2 file entities
- [ ] ≥5 contains relationships
- [ ] ≥3 follows relationships
- [ ] index_health = "healthy"

### Verify Test Data

Before running tests, verify documents are indexed:

```
get_project_info(session_id)

Expected output (health check only):
- Entities: > 0 (sections, headers from documents)
- Relationships: > 0 (indicates graph data exists)
- index_health: "healthy"
- status: "ready"
```

**NOTE:** Use `get_project_info` only for health checks (counts, status). Do NOT use it to validate relationship types - that tool may report statistics that don't reflect actual functionality. Relationship type validation must be done through functional tools like `graph_traverse` and `understand_entity`.

**Document Your Setup:**
```
Test Environment:
Session ID: [id]
Project ID: [id]

Document Content:
Path: [e.g., tests/parsers/samples/docs/]
Files Indexed: [count]
- Markdown: [count]
- PDF: [count]
- DOCX: [count]
- PPTX: [count]

Pre-Test Counts:
Entities: [count]
Relationships: [count]
- contains: [count]
- next_sibling: [count]
```

---

## Part 1: Entity Extraction

### T1.1: Verify Document Entities

**Objective:** Confirm document structure entities are extracted

**Execute:**
```
list_entities(session_id, entity_type="section", limit=20)
list_entities(session_id, entity_type="header", limit=20)
list_entities(session_id, entity_type="file", limit=20)
```

**Success Criteria:**
- Headers/sections extracted from documents
- Entity names match actual headers
- File entities link to source documents
- No code entities (class, function, method) in results

**Document:**
```
Document Entity Extraction:

Sections Found: [count]
Sample Sections:
1. [Section Name] - [file_path]
   - Level: [h1/h2/h3]
2. [Section Name] - [file_path]
   - Level: [h1/h2/h3]
3. [Section Name] - [file_path]
   - Level: [h1/h2/h3]

Headers Found: [count]
Sample Headers:
1. [Header Text] - [file_path]
2. [Header Text] - [file_path]

Files Found: [count]
1. [filename.md]
2. [filename.pdf]
3. [filename.docx]

Entity Type Distribution:
- section: [count]
- header: [count]
- paragraph: [count]
- file: [count]

Status: [PASS/FAIL]
```

---

### T1.2: Verify Structural Relationships via Functional Testing

**Objective:** Confirm containment and sibling relationships work through actual graph operations

**IMPORTANT:** Do NOT use `get_project_info` for relationship type validation. That tool reports statistics which may not reflect actual functionality. Instead, test relationships through functional tools.

**Execute:**
```
# Test containment via graph_traverse
graph_traverse(session_id, start_id="[top_section_entity_id]", relationship_types=["contains"], max_depth=2)
# Look for: parent-child section relationships

# Test sequential navigation via graph_traverse
graph_traverse(session_id, start_id="[section_entity_id]", relationship_types=["follows"], direction="both", max_depth=1)
# Look for: next/previous section relationships

# Test via understand_entity
understand_entity(session_id, entity="[section_name]", include_dependencies=True)
# Look for: structural relationships in dependencies
```

**Success Criteria:**
- `graph_traverse` with `contains` returns child sections (if hierarchy exists)
- `graph_traverse` with `follows` returns sequential sections
- `understand_entity` shows structural relationships
- Relationship metadata includes document source
- No code relationships (imports, calls) in document entities

**Document:**
```
Structural Relationships (Functional Validation):

Containment Relationships:
- Tool: graph_traverse with relationship_types=["contains"]
- Found contains: [yes/no]
- Sample: [Parent Section] contains [Child Section]
- Hierarchy depth: [levels]

Sequential Relationships:
- Tool: graph_traverse with relationship_types=["follows"]
- Found follows: [yes/no]
- Sample: [Section A] follows [Section B]
- Navigation works both directions: [yes/no]

understand_entity Results:
- Shows dependencies: [yes/no]
- Relationship types shown: [list]
- Document source preserved: [yes/no]

Functional Validation Summary:
- contains work: [PASS/FAIL/N/A] (N/A if flat document)
- follows work: [PASS/FAIL]
- No code relationships in docs: [PASS/FAIL]

Status: [PASS/FAIL]
```

---

## Part 2: Hierarchy Navigation

### T2.1: Parent-Child Traversal

**Objective:** Navigate document hierarchy via containment relationships

**Execute:**
```
understand_entity(session_id, entity="[Top-Level Section Name]", include_dependencies=True)
```

**Success Criteria:**
- Top-level section contains subsections
- Subsections contain their children
- Hierarchy depth matches document structure
- Can navigate up and down hierarchy

**Document:**
```
Hierarchy Navigation:

Starting Entity: [Top Section Name]
File: [file_path]
Level: h1

Contains (children):
1. [Subsection Name] (h2)
   - Contains: [count] children
2. [Subsection Name] (h2)
   - Contains: [count] children
3. [Subsection Name] (h2)
   - Contains: [count] children

Full Hierarchy:
# [Top Section]
├── ## [Subsection 1]
│   ├── ### [Sub-subsection 1.1]
│   └── ### [Sub-subsection 1.2]
├── ## [Subsection 2]
│   └── ### [Sub-subsection 2.1]
└── ## [Subsection 3]

Hierarchy Depth:
- Maximum depth found: [levels]
- Matches document structure: [yes/no]

Status: [PASS/FAIL]
```

---

### T2.2: Sibling Navigation

**Objective:** Navigate between sequential sections

**Execute:**
```
# Find a section and check its siblings
understand_entity(session_id, entity="[Section Name]", include_dependencies=True)
```

**Success Criteria:**
- `next_sibling` points to correct following section
- `previous_sibling` points to correct preceding section
- Siblings are at same hierarchy level
- Order matches document order

**Document:**
```
Sibling Navigation:

Current Section: [Section Name]
Level: h2
File: [file_path]

Previous Sibling:
- Name: [Previous Section Name]
- Level: [h2] (should match)
- Relationship: previous_sibling

Next Sibling:
- Name: [Next Section Name]
- Level: [h2] (should match)
- Relationship: next_sibling

Sibling Chain (at h2 level):
[Section 1] → [Section 2] → [Section 3] → [Section 4]

Navigation Accuracy:
- Siblings at correct level: [yes/no]
- Order matches document: [yes/no]

Status: [PASS/FAIL]
```

---

## Part 3: Multi-Document Handling

### T3.1: Document Isolation

**Objective:** Verify each document's graph is independent

**Execute:**
```
# Check entities from different documents
list_entities(session_id, file_path="sample.md")
list_entities(session_id, file_path="outline.md")
```

**Success Criteria:**
- Each document has its own entity tree
- No cross-document relationships (unless explicit links)
- Can filter entities by source document
- Document boundaries respected

**Document:**
```
Document Isolation:

Document 1: sample.md
- Entities: [count]
- Relationships: [count]
- Root sections: [list]

Document 2: outline.md
- Entities: [count]
- Relationships: [count]
- Root sections: [list]

Cross-Document Check:
- Relationships between docs: [count] (expected: 0 or only explicit refs)
- Entity IDs unique across docs: [yes/no]
- Document boundaries preserved: [yes/no]

Status: [PASS/FAIL]
```

---

### T3.2: Different Document Types

**Objective:** Verify structure extraction works across formats

**Execute:**
```
# Check structure from different file types
understand_entity(session_id, entity="[PDF section]")
understand_entity(session_id, entity="[DOCX heading]")
understand_entity(session_id, entity="[MD header]")
```

**Success Criteria:**
- Markdown headers extracted
- PDF sections/headings extracted
- DOCX headings extracted
- PPTX slides extracted (if applicable)
- Consistent entity types across formats

**Document:**
```
Multi-Format Structure:

Markdown (.md):
- Entities extracted: [count]
- Hierarchy levels: [count]
- Sample: [header name]

PDF (.pdf):
- Entities extracted: [count]
- Hierarchy levels: [count]
- Sample: [section name]

Word (.docx):
- Entities extracted: [count]
- Hierarchy levels: [count]
- Sample: [heading name]

PowerPoint (.pptx):
- Entities extracted: [count]
- Slides found: [count]
- Sample: [slide title]

Consistency:
- Entity types consistent: [yes/no]
- Relationship types consistent: [yes/no]

Status: [PASS/FAIL]
```

---

## Part 4: Edge Cases

### T4.1: Flat Document (No Structure)

**Objective:** Handle documents without clear hierarchy

**Execute:**
```
# Index a document without headers
# e.g., no_structure.md or plain text
understand_entity(session_id, entity="no_structure.md")
```

**Success Criteria:**
- Document still indexed
- File entity created
- Graceful handling of no sections
- No errors or crashes

**Document:**
```
Flat Document Handling:

Document: no_structure.md
Has Headers: No

Entities Created:
- File entity: [yes/no]
- Section entities: [count] (expected: 0 or minimal)
- Paragraph entities: [count]

Relationships Created: [count]

Behavior:
- No errors: [yes/no]
- Graceful degradation: [yes/no]

Status: [PASS/FAIL]
```

---

### T4.2: Deep Nesting

**Objective:** Handle documents with many hierarchy levels

**Execute:**
```
# Find deepest nested section
# Check if all levels preserved
```

**Success Criteria:**
- All hierarchy levels captured
- Deep nesting doesn't cause issues
- Relationships accurate at all levels

**Document:**
```
Deep Nesting:

Document with Deepest Nesting: [file]
Maximum Depth: [levels]

Hierarchy Path:
Level 1: [h1 name]
└── Level 2: [h2 name]
    └── Level 3: [h3 name]
        └── Level 4: [h4 name]
            └── Level 5: [h5 name] (if exists)

All Levels Captured: [yes/no]
Relationships Accurate: [yes/no]

Status: [PASS/FAIL]
```

---

### T4.3: Non-Existent Entity

**Objective:** Handle queries for missing entities gracefully

**Execute:**
```
understand_entity(session_id, entity="NonExistentSection12345")
```

**Success Criteria:**
- No crash or error
- Clear "not found" response
- Suggestions for similar entities (if available)

**Document:**
```
Non-Existent Entity Handling:

Query: "NonExistentSection12345"

Response:
- Error: [no]
- Not Found Message: [yes/no]
- Suggestions Provided: [yes/no]

Behavior: [graceful/error/crash]
Status: [PASS/FAIL]
```

---

## Final Evaluation

### Test Summary

```
Test Results:

Part 1: Entity Extraction
- T1.1 Verify Document Entities: [PASS/FAIL]
- T1.2 Verify Structural Relationships: [PASS/FAIL]

Part 2: Hierarchy Navigation
- T2.1 Parent-Child Traversal: [PASS/FAIL]
- T2.2 Sibling Navigation: [PASS/FAIL]

Part 3: Multi-Document
- T3.1 Document Isolation: [PASS/FAIL]
- T3.2 Different Document Types: [PASS/FAIL]

Part 4: Edge Cases
- T4.1 Flat Document: [PASS/FAIL]
- T4.2 Deep Nesting: [PASS/FAIL]
- T4.3 Non-Existent Entity: [PASS/FAIL]

Tests Passed: [X]/9
```

### Key Metrics

```
Document Graph Metrics:

Entities:
- Total: [count]
- Sections: [count]
- Headers: [count]
- Files: [count]

Relationships:
- Total: [count]
- contains: [count]
- next_sibling: [count]

Documents Processed:
- Markdown: [count]
- PDF: [count]
- DOCX: [count]
- PPTX: [count]

Hierarchy:
- Max depth: [levels]
- Average depth: [levels]
```

### Production Readiness

**Critical Checks:**
- [ ] Section/header entities extracted
- [ ] Containment relationships correct
- [ ] Sibling navigation works
- [ ] Multi-format support
- [ ] Document isolation maintained
- [ ] Edge cases handled

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
