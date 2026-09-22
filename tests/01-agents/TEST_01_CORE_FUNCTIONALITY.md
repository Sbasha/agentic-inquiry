# Core Functionality Smoke Test

**Purpose:** Validate MCP server and core features are working before running detailed use case tests
**Output Path:** test_results/smoke_test/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Is the system ready for real testing?"

---

## Test Overview

This is a **smoke test** - a quick validation that core functionality works before investing time in detailed use case tests (TEST_02 through TEST_11). If this test fails, fix the issues before proceeding to use case tests.

### What This Tests

- **Server Health** - MCP server is accessible and responding
- **Session Management** - Can create and manage sessions
- **Basic Indexing** - Can index a small codebase
- **Basic Search** - Search returns results
- **Basic Memory** - Can store and retrieve memories
- **Tool Availability** - Core tools are accessible

### What This Does NOT Test

This is not a comprehensive test. It does NOT test:
- Detailed use cases (see TEST_02 through TEST_11)
- Performance or scalability
- Edge cases or error handling
- Advanced features

**Time Limit:** 10-15 minutes
**Goal:** Quick validation that system is operational

---

## Pre-Test Setup

### Prerequisites

1. **MCP Server Running** - Agentic Inquiry MCP server must be started
2. **Test Codebase** - Small codebase to index (your own project or agentic-inquiry itself)
3. **Project Path** - Know the path to the codebase you'll test with

### Test Environment

```
Test Codebase: [name]
Path: [absolute path]
Estimated Size: [file count]
Language(s): [primary languages]
```

---

## Test 1: Server Health Check

**Objective:** Verify MCP server is accessible and responding

### T1.1: Get Server Info

**Execute:** Call `get_server_info()` or equivalent health check

**Expected:**
- Returns server information
- No errors
- Response within 2 seconds

**Document:**
```
Server responding: [yes/no]
Response time: [seconds]
Version info: [if available]
Status: [PASS/FAIL]
```

**If FAIL:** Stop and fix server startup before proceeding.

---

## Test 2: Session Management

**Objective:** Verify session creation and retrieval works

### T2.1: Create Session

**Execute:** Create a new session with your test project

**Expected:**
- Returns session ID
- Session is active
- No errors

**Document:**
```
Session created: [yes/no]
Session ID: [id]
Project ID: [id]
Status: [PASS/FAIL]
```

### T2.2: Retrieve Session

**Execute:** Get the session you just created

**Expected:**
- Returns session details
- Session ID matches
- Project info is correct

**Document:**
```
Session retrieved: [yes/no]
Details match: [yes/no]
Status: [PASS/FAIL]
```

**If FAIL:** Session management broken - investigate before proceeding.

---

## Test 3: Basic Indexing

**Objective:** Verify system can index files

### T3.1: Index Content

**Execute:** Index your test codebase (or add knowledge to session)

**Expected:**
- Indexing completes without errors
- Files are indexed (count > 0)
- Completes in reasonable time

**Document:**
```
Indexing started: [yes/no]
Files indexed: [count]
Duration: [seconds]
Errors: [yes/no - list if yes]
Status: [PASS/FAIL]
```

**If FAIL:** Indexing is broken - check logs and fix before proceeding.

---

### T3.2: Verify Indexed Content

**Execute:** Check that content was actually indexed

**Expected:**
- Can query indexed content
- Returns file count or confirmation

**Document:**
```
Content queryable: [yes/no]
Indexed files confirmed: [count]
Status: [PASS/FAIL]
```

---

## Test 4: Basic Search

**Objective:** Verify search returns results

### T4.1: Simple Search

**Execute:** Search for a term you know exists in your codebase

**Expected:**
- Returns results (count > 0)
- Results have file paths
- Results are from your project

**Document:**
```
Search term: [what you searched for]
Results returned: [count]
Has file paths: [yes/no]
From correct project: [yes/no - spot check]
Status: [PASS/FAIL]
```

**If FAIL:** Search is broken - investigate before proceeding.

---

### T4.2: Verify Result Quality

**Execute:** Check that top result is actually relevant

**Expected:**
- Top result relates to search term
- File path is valid
- Content exists at location

**Document:**
```
Top result: [file:line or description]
Relevant: [yes/no]
File exists: [yes/no - spot check]
Status: [PASS/FAIL]
```

---

## Test 5: Basic Memory

**Objective:** Verify memory storage and retrieval works

### T5.1: Store Memory

**Execute:** Store a simple memory (e.g., "Entry point is main.py:main()")

**Expected:**
- Memory stored successfully
- Returns memory ID or confirmation

**Document:**
```
Memory content: [what you stored]
Stored successfully: [yes/no]
Memory ID: [id if provided]
Status: [PASS/FAIL]
```

**If FAIL:** Memory system broken - investigate before proceeding.

---

### T5.2: Retrieve Memory

**Execute:** Search for the memory you just stored

**Expected:**
- Memory is retrieved
- Content is intact
- Retrieval is fast

**Document:**
```
Memory retrieved: [yes/no]
Content intact: [yes/no]
Retrieval time: [< 2 seconds yes/no]
Status: [PASS/FAIL]
```

---

## Test 6: Tool Availability

**Objective:** Verify core MCP tools are accessible

### T6.1: List Available Tools

**Execute:** Check what tools are available

**Expected:**
- Core tools present:
  - Session management (create_session, get_session, list_sessions)
  - Search (search_knowledge)
  - Memory (save_memory, recall_memories)
  - Context (build_context)
  - Analysis tools (understand_entity, analyze_impact)

**Document:**
```
Total tools available: [count]

Core tools present:
- create_session: [yes/no]
- get_session: [yes/no]
- search_knowledge: [yes/no]
- save_memory: [yes/no]
- recall_memories: [yes/no]
- build_context: [yes/no]
- understand_entity: [yes/no]
- analyze_impact: [yes/no]

Expected count: ~15 tools
Actual count: [count]
Status: [PASS/FAIL]
```

**If FAIL:** Tool registration broken - check server setup.

---

## Smoke Test Results

### Pass/Fail Summary

```
Test 1: Server Health         [PASS/FAIL]
Test 2: Session Management    [PASS/FAIL]
Test 3: Basic Indexing        [PASS/FAIL]
Test 4: Basic Search          [PASS/FAIL]
Test 5: Basic Memory          [PASS/FAIL]
Test 6: Tool Availability     [PASS/FAIL]

Total Passed: [X]/6
```

### Overall Status

```
All Tests Passed: [YES/NO]

Ready for Use Case Tests: [YES/NO]
```

**Decision:**
- **All PASS** → Proceed to use case tests (TEST_02 onwards)
- **Any FAIL** → Fix issues before running detailed tests

---

## Issues Encountered

**If any test failed, document the issue:**

```
Test: [which test failed]
Issue: [what went wrong]
Error Message: [exact error if any]
Logs: [relevant log excerpts]
Next Steps: [what needs to be fixed]
```

---

## Quick Fixes for Common Issues

### Server Not Responding
```bash
# Check if server is running
ps aux | grep ai

# Restart server
uv run ai [project_name]
```

### Indexing Failed
```bash
# Check logs
tail -f workspace/logs/agentic-inquiry.log

# Common issues:
# - File permissions
# - Unsupported file types
# - Out of memory
```

### Search Returns Empty
```bash
# Verify indexing completed
# Check session has correct project
# Verify search term actually exists in codebase
```

### Memory Not Persisting
```bash
# Check database is writeable
# Verify session is active
# Check logs for database errors
```

---

## Test Completion

**Test Metadata:**
```
Duration: [minutes - should be < 15]
Tester: [name/id]
Date: [YYYY-MM-DD]
Test Codebase: [name]
Files Indexed: [count]
All Tests Passed: [YES/NO]
Ready for Use Cases: [YES/NO]
```

**Next Steps:**
```
[If PASS] → Proceed to TEST_02_ONBOARDING.md
[If FAIL] → Fix issues and re-run this smoke test
```

---

## Notes

### About This Test

This smoke test is intentionally minimal. It validates that:
1. The server works
2. Basic operations complete successfully
3. No critical errors occur

It does NOT validate:
- Quality of results (see use case tests)
- Performance (see TEST_10_PERFORMANCE_INVESTIGATION.md)
- Edge cases (covered in specific use case tests)
- Advanced features (covered in specific use case tests)

### When to Run This Test

Run this smoke test:
- **After server installation** - Verify setup worked
- **After configuration changes** - Ensure nothing broke
- **Before detailed testing** - Save time by catching basic issues early
- **After updates** - Verify new version works

### Test Independence

This test is designed to be:
- **Quick** - Completes in 10-15 minutes
- **Independent** - Doesn't depend on other tests
- **Focused** - Only tests core functionality
- **Decisive** - Clear pass/fail for each test

---

**Remember:** This is a smoke test, not a comprehensive evaluation. If this passes, proceed to the detailed use case tests (TEST_02 through TEST_11) for thorough validation.
