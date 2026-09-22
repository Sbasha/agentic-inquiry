# Use Case 14: Semantic Graph

**Purpose:** Validate runtime similarity discovery via vector embeddings
**Output Path:** test_results/semantic_graph/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Can the system discover non-obvious connections through meaning?"

---

## Known Issues

> **Last Updated:** 2025-12-28

### SG-001: Hard Content Type Filter (Active)

**Issue:** The search pipeline has a hard filter `filters={"content_type": "CODE"}` in `search.py:424` that blocks cross-content discovery.

**Impact on Tests:**
- **T2.2 Cross-Content Type Similarity** may fail or return only code results
- **T4.1 Find Related Components** may miss document matches
- Any test expecting mixed code+document results

**Workaround:** Until SG-001 is fixed:
1. Test code-only similarity separately
2. Test document-only similarity separately
3. Mark cross-content tests as "EXPECTED FAIL" if they fail due to this issue

**Tracking:** This issue is documented in `.sessions/system-overhaul-design/design/SDD-001_CONTENT_FILTERING_OVERHAUL.md` and will be addressed in Sprint 3.

### Test Expectations

| Test | Expected Result | With SG-001 Active |
|------|-----------------|-------------------|
| T1.x Basic Similarity | PASS | PASS |
| T2.1 Entity Similarity | PASS | PASS (code only) |
| T2.2 Cross-Content | PASS | **MAY FAIL** - Expected |
| T3.x Thresholds | PASS | PASS |
| T4.1 Discovery | PASS | **MAY FAIL** for docs - Expected |
| T4.2 Contextual | PASS | PASS |
| T5.x Performance | PASS | PASS |

---

## What This Tests

**Semantic Graph** discovers relationships at runtime via vector similarity:

| Aspect | Description |
|--------|-------------|
| **Scope** | All indexed content with embeddings |
| **How Created** | At query time via vector similarity search |
| **Relationship Types** | `similar_to` (computed, NOT stored) |
| **Entity Types** | Any entity/chunk with embeddings |
| **Storage** | Embeddings in `document_chunks` table |
| **Expected Count** | No stored relationships - infinite potential connections |

### Key Difference from Code/Document Graphs

| Aspect | Code/Document Graph | Semantic Graph |
|--------|---------------------|----------------|
| **When created** | During indexing | At query time |
| **Stored** | Yes (graph_relationships table) | No (computed on demand) |
| **Deterministic** | Yes (same result every time) | Probabilistic (similarity scores) |
| **Relationship count** | Fixed after indexing | Infinite (any-to-any) |

### How It Works

1. Content indexed → embeddings generated (384-dim vectors)
2. User queries `find_similar("database connection pooling")`
3. Query embedded → vector search finds nearest neighbors
4. Results ranked by cosine similarity

### Success Criteria

- **Embeddings Present:** All indexed content has embeddings
- **Similarity Meaningful:** High scores = semantically related
- **Cross-Content:** Can find similar items across files/types
- **Discovery:** Reveals non-obvious connections
- **Performance:** Sub-second response times

**Time Limit:** 20 minutes
**Confidence Threshold:** 8/10

---

## CRITICAL: Test Data Requirements

**MUST have EMBEDDINGS generated:**
- Check `document_chunks` table has `embedding` column
- Embeddings are 384-dimensional vectors (default)
- Generated during indexing (not retroactive)

**Works with ANY indexed content:**
- Code files with embeddings
- Documents with embeddings
- Mixed content

**Common Issue:** If embeddings weren't generated during indexing, semantic search returns empty results. Re-index with embedding generation enabled.

**Verify embeddings exist:**
```python
# Direct check
chunks = db.open_table('document_chunks')
df = chunks.to_pandas()
has_embeddings = df['embedding'].notna().sum()
print(f"Chunks with embeddings: {has_embeddings}")
```

---

## MANDATORY: Pre-Test Data Setup

> **WARNING: DO NOT SKIP THIS SECTION. Tests will return empty results without proper data.**

This section MUST complete successfully before running any tests. The semantic graph tests require:
- Content chunks with vector embeddings
- Sufficient data volume for meaningful similarity comparisons
- Both code and document content (for cross-content tests)

### Step 1: Create Session with Unique Project ID

```python
project_id = "agv_test14_semantic_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Semantic graph test")
```

**Save the session_id** - you'll need it for all subsequent operations.

### Step 2: Index the FULL Codebase (REQUIRED)

```python
# Index the entire project - code AND documents
add_knowledge(session_id=session_id, source=".", content_type="code", wait_for_completion=True)
add_knowledge(session_id=session_id, source="docs/", content_type="document", wait_for_completion=True)
```

**IMPORTANT:**
- Index from project root (`.`) to get all code files
- Also index documentation if available for cross-content similarity tests
- Embeddings are generated during indexing - cannot be added retroactively

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
        print(f"Chunks: {data.get('chunks_indexed', 0)}")
```

**Don't trust `get_project_info` counts until this event fires.**

**Expected wait time:** 30 seconds to 10 minutes (embedding generation takes time).

### Step 4: Verify Data Thresholds (STOP CONDITIONS)

```python
info = get_project_info(session_id=session_id)
```

**MINIMUM THRESHOLDS - DO NOT PROCEED IF NOT MET:**

| Metric | Minimum | Stop Action |
|--------|---------|-------------|
| `total_chunks` | ≥ 100 | Index more content |
| `statistics.indexed_file_count` | ≥ 20 | Index full codebase |
| `index_health` | "healthy" | Investigate indexing errors |

**Verify embeddings exist:**
```python
# Quick test - search should return results if embeddings exist
results = search_knowledge(session_id=session_id, query="test query", limit=5)
# If results.total_results > 0, embeddings are working
```

**If thresholds NOT met:**
1. Check `.agv-server.log` for embedding errors
2. Verify embedding model is configured and accessible
3. Ensure source path is correct (`.` for project root)
4. Re-run indexing - embeddings cannot be added after the fact

### Step 5: Document Your Setup

```
Test Environment:
Session ID: [id]
Project ID: [id]

Verification Results:
- total_chunks: [count] (min: 100)
- indexed_file_count: [count] (min: 20)
- index_health: [status]

Search Verification:
- Test query returned results: [YES/NO]
- Result count: [count]

Content Types Indexed:
- Code files: [count]
- Document files: [count]

Data Thresholds Met: [YES/NO]
Proceed with Tests: [YES/NO]
```

**STOP HERE if thresholds not met. Fix data issues before continuing.**

---

## Prerequisites Checklist

Before running tests, confirm ALL of these:

- [ ] MCP Server running and responding
- [ ] Session created with unique project_id
- [ ] Full codebase indexed (from project root)
- [ ] Indexing completed (not just started)
- [ ] ≥100 total chunks
- [ ] ≥20 indexed files
- [ ] Test search query returns results (proves embeddings exist)
- [ ] index_health = "healthy"

### Verify Embeddings

Before running tests:

```
get_project_info(session_id)

Check for:
- Chunks count > 0
- Embedding dimension: 384 (or configured value)
```

**Document Your Setup:**
```
Test Environment:
Session ID: [id]
Project ID: [id]

Indexed Content:
- Total chunks: [count]
- Chunks with embeddings: [count]
- Embedding dimension: [384]

Content Types:
- Code chunks: [count]
- Document chunks: [count]
```

---

## Part 1: Basic Similarity Search

### T1.1: Single Query Similarity

**Objective:** Find content similar to a natural language query

**Execute:**
```
find_similar(session_id, query="database connection pooling", limit=10)
```

**Success Criteria:**
- Returns relevant results
- Results ranked by similarity score
- Top results semantically related to query
- Scores decrease as relevance decreases

**Document:**
```
Single Query Similarity:

Query: "database connection pooling"
Results: [count]

Top Results:
1. [chunk/entity description]
   - File: [path]
   - Similarity: [score]
   - Relevance: [high/medium/low]
   - Why relevant: [brief explanation]

2. [chunk/entity description]
   - File: [path]
   - Similarity: [score]
   - Relevance: [high/medium/low]

3. [chunk/entity description]
   - File: [path]
   - Similarity: [score]
   - Relevance: [high/medium/low]

[Continue for top 5...]

Score Distribution:
- Highest: [score]
- Lowest (in top 10): [score]
- Score dropoff meaningful: [yes/no]

Result Quality:
- Top 3 relevant: [yes/no]
- Top 5 relevant: [X/5]
- Top 10 relevant: [X/10]

Status: [PASS/FAIL]
```

---

### T1.2: Multiple Query Types

**Objective:** Test various query styles

**Execute:**
```
# Technical query
find_similar(session_id, query="async error handling", limit=5)

# Conceptual query
find_similar(session_id, query="how to process documents", limit=5)

# Short query
find_similar(session_id, query="search", limit=5)

# Long query
find_similar(session_id, query="implement a caching layer for database queries to improve performance", limit=5)
```

**Success Criteria:**
- All query types return results
- Results match query intent
- Different query lengths handled
- Technical vs conceptual both work

**Document:**
```
Query Type Comparison:

Query 1 (Technical): "async error handling"
- Results: [count]
- Top result relevance: [high/medium/low]
- Top result: [description]

Query 2 (Conceptual): "how to process documents"
- Results: [count]
- Top result relevance: [high/medium/low]
- Top result: [description]

Query 3 (Short): "search"
- Results: [count]
- Top result relevance: [high/medium/low]
- Top result: [description]

Query 4 (Long): "implement a caching layer..."
- Results: [count]
- Top result relevance: [high/medium/low]
- Top result: [description]

Best Query Type: [which worked best]
Worst Query Type: [which struggled]

Status: [PASS/FAIL]
```

---

## Part 2: Entity-Based Similarity

### T2.1: Find Similar to Entity

**Objective:** Find content similar to an existing entity

**Execute:**
```
# Find entities similar to a known class/function
find_similar(session_id, query="LanceDBManager", entity_type="class", limit=10)
find_similar(session_id, query="SearchService", limit=10)
```

**Success Criteria:**
- Finds semantically related entities
- Not just name matches - conceptual similarity
- Cross-file discovery works
- Entity type filtering works (if supported)

**Document:**
```
Entity-Based Similarity:

Query: Similar to "LanceDBManager"
Results: [count]

Similar Entities:
1. [entity name] - [type]
   - File: [path]
   - Similarity: [score]
   - Why similar: [conceptual reason]

2. [entity name] - [type]
   - File: [path]
   - Similarity: [score]
   - Why similar: [conceptual reason]

3. [entity name] - [type]
   - File: [path]
   - Similarity: [score]

Cross-File Results: [count] (results from different files)

Discovery Value:
- Found non-obvious connections: [yes/no]
- Useful for understanding codebase: [yes/no]

Status: [PASS/FAIL]
```

---

### T2.2: Cross-Content Type Similarity

**Objective:** Find similar content across code and documents

**Execute:**
```
# Query that could match both code and docs
find_similar(session_id, query="embedding generation", limit=10)
find_similar(session_id, query="configuration options", limit=10)
```

**Success Criteria:**
- Results from both code and documents
- Similarity scores comparable across types
- Relevant matches regardless of content type

**Document:**
```
Cross-Content Similarity:

Query: "embedding generation"
Total Results: [count]

Code Results:
1. [code chunk/entity]
   - File: [.py file]
   - Similarity: [score]

2. [code chunk/entity]
   - File: [.py file]
   - Similarity: [score]

Document Results:
1. [doc section/chunk]
   - File: [.md/.pdf file]
   - Similarity: [score]

2. [doc section/chunk]
   - File: [.md/.pdf file]
   - Similarity: [score]

Content Type Distribution:
- Code results: [count]
- Document results: [count]
- Mixed in top 10: [yes/no]

Cross-Content Discovery:
- Found doc that explains code: [yes/no]
- Found code that implements doc concept: [yes/no]

Status: [PASS/FAIL]
```

---

## Part 3: Similarity Thresholds

### T3.1: Threshold Filtering

**Objective:** Test filtering by similarity threshold

**Execute:**
```
# High threshold (strict matching)
find_similar(session_id, query="LanceDB vector search", similarity_threshold=0.8, limit=10)

# Medium threshold
find_similar(session_id, query="LanceDB vector search", similarity_threshold=0.5, limit=10)

# Low threshold (loose matching)
find_similar(session_id, query="LanceDB vector search", similarity_threshold=0.3, limit=10)
```

**Success Criteria:**
- Higher threshold = fewer, more relevant results
- Lower threshold = more results, some less relevant
- Threshold filtering works correctly

**Document:**
```
Threshold Comparison:

Query: "LanceDB vector search"

High Threshold (0.8):
- Results: [count]
- All highly relevant: [yes/no]
- Sample: [top result]

Medium Threshold (0.5):
- Results: [count]
- Mix of relevance: [description]
- Sample: [top result]

Low Threshold (0.3):
- Results: [count]
- Includes marginal matches: [yes/no]
- Sample: [lowest relevance result]

Threshold Effect:
- 0.8 too strict: [yes/no]
- 0.5 good balance: [yes/no]
- 0.3 too loose: [yes/no]

Recommended Threshold: [value]
Status: [PASS/FAIL]
```

---

### T3.2: Empty Results Handling

**Objective:** Handle queries with no good matches gracefully

**Execute:**
```
# Query with no matches
find_similar(session_id, query="quantum blockchain neural cryptography", limit=10)

# Very high threshold
find_similar(session_id, query="common term", similarity_threshold=0.99, limit=10)
```

**Success Criteria:**
- No crash on empty results
- Clear indication of no matches
- Graceful response

**Document:**
```
Empty Results Handling:

Query 1: "quantum blockchain neural cryptography"
- Results: [count]
- Response: [description]
- Graceful: [yes/no]

Query 2: Very high threshold (0.99)
- Results: [count]
- Response: [description]
- Graceful: [yes/no]

Error Handling: [good/adequate/poor]
Status: [PASS/FAIL]
```

---

## Part 4: Discovery Use Cases

### T4.1: Find Related Components

**Objective:** Discover components related to a concept

**Execute:**
```
# What's related to "caching"?
find_similar(session_id, query="caching and memoization", limit=15)

# What's related to "validation"?
find_similar(session_id, query="input validation and sanitization", limit=15)
```

**Success Criteria:**
- Discovers multiple related components
- Reveals non-obvious connections
- Useful for understanding codebase patterns

**Document:**
```
Component Discovery:

Query: "caching and memoization"
Discovered Components:
1. [component] - [why related]
2. [component] - [why related]
3. [component] - [why related]
[Continue...]

Non-Obvious Discoveries:
- [Something unexpected but relevant]
- [Something unexpected but relevant]

Query: "input validation and sanitization"
Discovered Components:
1. [component] - [why related]
2. [component] - [why related]
[Continue...]

Discovery Value:
- Found components I didn't know existed: [yes/no]
- Revealed patterns across codebase: [yes/no]
- Useful for learning codebase: [yes/no]

Status: [PASS/FAIL]
```

---

### T4.2: Contextual Search

**Objective:** Use semantic search to build relevant context

**Execute:**
```
build_context(session_id, query="How does the indexing pipeline work?", max_tokens=4000)
```

**Success Criteria:**
- Context includes relevant chunks
- Semantic search finds conceptually related content
- Context is coherent and useful

**Document:**
```
Contextual Search:

Query: "How does the indexing pipeline work?"
Max Tokens: 4000

Context Built:
- Chunks included: [count]
- Total tokens: [count]

Content Included:
1. [chunk description] - Relevance: [high/medium/low]
2. [chunk description] - Relevance: [high/medium/low]
3. [chunk description] - Relevance: [high/medium/low]
[Continue...]

Context Quality:
- Covers query topic: [yes/no]
- Includes key components: [yes/no]
- Coherent narrative: [yes/no]
- Would help answer question: [yes/no]

Status: [PASS/FAIL]
```

---

## Part 5: Performance

### T5.1: Response Time

**Objective:** Verify acceptable search performance

**Execute:** Time multiple similarity searches:
```
# Time each query
find_similar(session_id, query="query 1", limit=10)
find_similar(session_id, query="query 2", limit=50)
find_similar(session_id, query="query 3", limit=100)
```

**Success Criteria:**
- limit=10: <500ms
- limit=50: <1s
- limit=100: <2s

**Document:**
```
Performance Testing:

Query with limit=10:
- Time: [ms]
- Status: [PASS/FAIL]

Query with limit=50:
- Time: [ms]
- Status: [PASS/FAIL]

Query with limit=100:
- Time: [ms]
- Status: [PASS/FAIL]

Performance Summary:
- Average response: [ms]
- Acceptable for interactive use: [yes/no]

Status: [PASS/FAIL]
```

---

### T5.2: Scalability

**Objective:** Verify performance doesn't degrade with data size

**Document:**
```
Scalability Check:

Index Size:
- Total chunks: [count]
- Total embeddings: [count]

Performance at Scale:
- Response time consistent: [yes/no]
- Memory issues: [none/some/significant]

Status: [PASS/FAIL]
```

---

## Final Evaluation

### Test Summary

```
Test Results:

Part 1: Basic Similarity
- T1.1 Single Query Similarity: [PASS/FAIL]
- T1.2 Multiple Query Types: [PASS/FAIL]

Part 2: Entity Similarity
- T2.1 Find Similar to Entity: [PASS/FAIL]
- T2.2 Cross-Content Type: [PASS/FAIL]

Part 3: Thresholds
- T3.1 Threshold Filtering: [PASS/FAIL]
- T3.2 Empty Results Handling: [PASS/FAIL]

Part 4: Discovery
- T4.1 Find Related Components: [PASS/FAIL]
- T4.2 Contextual Search: [PASS/FAIL]

Part 5: Performance
- T5.1 Response Time: [PASS/FAIL]
- T5.2 Scalability: [PASS/FAIL]

Tests Passed: [X]/10
```

### Key Metrics

```
Semantic Graph Metrics:

Embeddings:
- Total chunks: [count]
- Chunks with embeddings: [count]
- Embedding dimension: [384]

Quality:
- Top-3 relevance rate: [%]
- Top-10 relevance rate: [%]
- Cross-content discovery: [yes/no]

Performance:
- Average response time: [ms]
- Max response time: [ms]
```

### Production Readiness

**Critical Checks:**
- [ ] Embeddings present for all content
- [ ] Similarity scores meaningful
- [ ] Cross-content search works
- [ ] Threshold filtering effective
- [ ] Performance acceptable
- [ ] Empty results handled gracefully

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

### Discovery Value Assessment

**Answer: [Excellent / Good / Adequate / Poor]**

**Reasoning:**
```
[2-3 paragraphs on:]
- Quality of similarity matching
- Value for codebase exploration
- Non-obvious connections discovered
- Comparison to grep/exact search
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
