# Troubleshooting Guide

## Bind address (0.3.0)

The server binds to 127.0.0.1 by default. In short, a non-loopback bind requires an API key. MCP http and sse bind loopback only in 0.3.0.

> **Note:** The MCP server is a secondary/advanced interface. **Most users should use the [Claude Code plugins](../../README.md) as the primary interface.** This troubleshooting guide applies to all usage modes (CLI, plugins, MCP server). MCP-specific issues are clearly marked.

This guide helps you diagnose and resolve common issues with Agentic Inquiry. Most sections apply to all usage modes (CLI, plugins, MCP server). MCP-specific issues are clearly marked.

## Table of Contents

- [Quick Diagnostics](#quick-diagnostics)
- [Entity Resolution Issues](#entity-resolution-issues)
- [Impact Analysis Issues](#impact-analysis-issues)
- [Search Quality Issues](#search-quality-issues)
- [Session Management Issues](#session-management-issues)
- [Indexing Issues](#indexing-issues)
- [Schema Mismatch Issues](#schema-mismatch-issues)
- [Context Building Issues](#context-building-issues)
- [Query Sanitization Issues](#query-sanitization-issues)
- [Storage Maintenance Issues](#storage-maintenance-issues)
- [Performance Issues](#performance-issues)
- [Configuration Issues](#configuration-issues)
- [FAQ](#faq)

## Quick Diagnostics

### MCP Not Enabled (MCP Server Only)

**Symptoms:**
- MCP server won't start
- Error: "MCP is disabled"

**Solution:**
```yaml
# agentic-inquiry.yaml
mcp:
  enabled: true
```

**Note:** This only applies if you're running the MCP server directly. Claude Code plugin users can ignore this.

### Project Not Found

**Symptoms:**
- Error: "Project not found: my_project"
- Can't create session with project

**Solution:**
```python
# Discover available projects first
info = await get_server_info()
print("Available:", [p['project_id'] for p in info['available_projects']])

# If your project isn't indexed, use add_knowledge to index it
result = await add_knowledge(
    session_id=session_id,
    content_type="directory",
    source="."
)
```

### Entity Not Found

**Symptoms:**
- Error: "Entity not found"
- `understand_entity` returns empty results

**Solution:**
```python
# Try case-insensitive search
entity = await understand_entity(
    session_id=session_id,
    entity="searchservice"  # lowercase works
)
```

### No Search Results

**Symptoms:**
- Empty results array
- "No indexed content found" message

**Solution:**
```python
# Check if content is indexed
info = await get_project_info(session_id=session_id)
if info['project_summary']['overview']['total_chunks'] == 0:
    # Index content on-demand
    await add_knowledge(
        session_id=session_id,
        content_type="directory",
        source="."
    )
```

### Port Already in Use (MCP Server HTTP Mode Only)

**Symptoms:**
- Error: "Address already in use"
- Server won't start on specified port

**Solution:**
```bash
# Choose a different port
uv run ai --transport http --port 8001
```

**Note:** This only applies to MCP server HTTP mode. STDIO mode and Claude Code plugins don't use network ports.

## Error Codes and Recovery

### Common Error Codes

All tools (CLI, plugins, MCP) return structured errors with helpful guidance. See the sections below for specific error codes and recovery strategies.

#### SESSION_NOT_FOUND

**Message**: Session '{session_id}' not found or expired

**Recovery**:
```python
# Create a new session
session = await create_session(
    project_id="my_project",
    description="New session"
)

# Or resume an expired session
session = await resume_session(session_id=old_session_id)
```

#### INVALID_PROJECT_ID

**Message**: Invalid project_id format

**Cause**: Project ID doesn't meet validation requirements (alphanumeric, hyphens, underscores only)

**Recovery**:
```python
# Discover format requirements
info = await get_server_info()
print(f"Format: {info['project_id_rules']['format']}")
print(f"Examples: {info['project_id_rules']['examples']}")

# Create session with valid project_id
session = await create_session(project_id="my-project")
```

#### PROJECT_NOT_INDEXED

**Message**: Project '{project_id}' has no indexed content

**Recovery**:
```python
# Index the project
result = await add_knowledge(
    session_id=session_id,
    content_type="directory",
    source=".",
    watch=True
)

# Monitor indexing progress
events = await get_events(
    session_id=session_id,
    event_types=["indexing"]
)
```

#### NO_RESULTS

**Message**: No results found for query '{query}'

**Cause**: Query doesn't match any indexed content

**Recovery**:
```python
# Check debug info
results = await search_knowledge(
    session_id=session_id,
    query="authentication"
)

if not results['results']:
    debug = results.get('debug_info', {})
    
    if debug.get('indexed_chunks', 0) == 0:
        # Empty project - need to index
        await add_knowledge(
            session_id=session_id,
            content_type="directory",
            source="."
        )
    else:
        # Try broader terms
        results = await search_knowledge(
            session_id=session_id,
            query="auth",  # Broader term
            search_type="fts"
        )
```

#### ENTITY_NOT_FOUND

**Message**: Entity '{entity}' not found in index

**Recovery**:
```python
# Search for the entity first
results = await search_knowledge(
    session_id=session_id,
    query=entity_name,
    filters={"type": "code"}
)

if results['results']:
    # Use exact entity name from results
    entity_info = await understand_entity(
        session_id=session_id,
        entity=results['results'][0]['title']
    )
```

### Error Recovery Strategies

#### Retry with Exponential Backoff

```python
import asyncio

async def retry_with_backoff(func, max_retries=3, base_delay=1.0, **kwargs):
    """Retry function with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return await func(**kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            await asyncio.sleep(delay)

# Usage
result = await retry_with_backoff(
    search_knowledge,
    session_id=session_id,
    query="authentication"
)
```

#### Graceful Degradation

```python
async def search_with_fallback(session_id: str, query: str):
    """Search with fallback strategies"""
    try:
        # Try full search
        return await search_knowledge(
            session_id=session_id,
            query=query,
            include_content=True
        )
    except Exception as e:
        if "NO_RESULTS" in str(e):
            # Try broader search
            return await search_knowledge(
                session_id=session_id,
                query=" ".join(query.split()[:2]),
                preview=True
            )
        elif "TOKEN_BUDGET_EXCEEDED" in str(e):
            # Try without content
            return await search_knowledge(
                session_id=session_id,
                query=query,
                include_content=False
            )
        else:
            raise
```

### Can't Connect from Remote Machine (MCP Server HTTP Mode Only)

**Symptoms:**
- MCP server starts but remote connections fail
- Connection refused errors

**Solution:**
```bash
# Bind to 127.0.0.1 instead of 127.0.0.1
uv run ai --transport http --host 127.0.0.1 --port 8000
```

**Note:** This only applies to MCP server HTTP mode. Most users should use Claude Code plugins instead.

### Check Server Status

```python
# Get server information
info = await get_server_info()

print(f"Server: {info['server']['name']} v{info['server']['version']}")
print(f"Available projects: {len(info['available_projects'])}")

# Check default project
default = info['default_project']
print(f"Default project: {default['project_id']}")
```

### Verify Project Indexing

```python
# Create session and check project info
session = await create_session(project_id="my_project")

info = await get_project_info(session_id=session['session_id'])
overview = info['project_summary']['overview']

print(f"Total files: {overview['total_files']}")
print(f"Total chunks: {overview['total_chunks']}")
print(f"Total entities: {overview['total_entities']}")
print(f"Index coverage: {overview['index_coverage']}%")
```

### Check Recent Events

```python
# Monitor for errors
events = await get_events(
    session_id=session_id,
    status_filter=["error", "warning"],
    limit=20
)

for event in events['events']:
    print(f"[{event['status']}] {event['message']}")
```

## Entity Resolution Issues

### Problem: understand_entity Returns Empty Results

**Symptoms:**
- `understand_entity` returns no entity data
- Error: "Entity not found"
- Empty dependencies or usage examples

**Diagnostic Steps:**

1. **Verify Entity Exists in Index**

```python
# Check if entities are indexed
info = await get_project_info(session_id=session_id)
total_entities = info['project_summary']['overview']['total_entities']

if total_entities == 0:
    print("⚠ No entities indexed - need to index code files")
else:
    print(f"✓ {total_entities} entities indexed")
```

2. **Check Entity Name**

```python
# Try case-insensitive search
entity = await understand_entity(
    session_id=session_id,
    entity="searchservice"  # lowercase
)

# Try with entity type
entity = await understand_entity(
    session_id=session_id,
    entity="SearchService",
    entity_type="class"
)
```

3. **Search for Similar Entities**

```python
# Use search to find entity
results = await search_knowledge(
    session_id=session_id,
    query="SearchService",
    filters={"type": "code"}
)

for result in results['results']:
    print(f"Found: {result['title']} in {result['file_path']}")
```

**Common Causes:**

1. **Entity Not Indexed**
   - **Solution**: Index the directory containing the entity
   ```python
   await add_knowledge(session_id=session_id, source="src/")
   ```

2. **Wrong Entity Name**
   - **Solution**: Check spelling and case (case-insensitive matching is supported)
   - Use suggestions from error messages

3. **Entity Type Mismatch**
   - **Solution**: Try without entity_type parameter or use correct type

4. **Project ID Mismatch**
   - **Solution**: Verify you're using the correct project_id
   ```python
   info = await get_server_info()
   print("Available projects:", [p['project_id'] for p in info['available_projects']])
   ```

**Performance Expectations:**
- Response time: <1.5s (95th percentile)
- Success rate: >80% for indexed entities
- Case-insensitive matching supported
- Fuzzy matching with similarity threshold

## Impact Analysis Issues

### Problem: analyze_impact Returns Zero Impact

**Symptoms:**
- `impact_radius` is 0
- Empty `affected_files` and `affected_entities`
- No relationships found

**Diagnostic Steps:**

1. **Verify Entity Exists**

```python
# First check if entity exists
entity = await understand_entity(
    session_id=session_id,
    entity="MyClass"
)

if entity['success']:
    print(f"✓ Entity found: {entity['entity']['name']}")
else:
    print("⚠ Entity not found - cannot analyze impact")
```

2. **Check Relationship Data**

```python
# Get project info to see if relationships exist
info = await get_project_info(session_id=session_id)
overview = info['project_summary']['overview']

print(f"Total entities: {overview['total_entities']}")
print(f"Most connected: {info['project_summary']['most_connected']}")
```

3. **Try Different Depth**

```python
# Try deeper traversal
impact = await analyze_impact(
    session_id=session_id,
    entity="MyClass",
    depth=3  # Increase depth
)

print(f"Impact radius: {impact['impact_radius']}")
```

**Common Causes:**

1. **Entity Has No Dependencies**
   - **Solution**: This is expected for isolated entities
   - Check if entity is actually used elsewhere in codebase

2. **Relationships Not Indexed**
   - **Solution**: Re-index with relationship extraction enabled
   ```python
   await add_knowledge(session_id=session_id, source=".")
   ```

3. **Depth Too Shallow**
   - **Solution**: Increase depth parameter (1-5)
   ```python
   impact = await analyze_impact(
       session_id=session_id,
       entity="MyClass",
       depth=3
   )
   ```

4. **Circular Dependencies**
   - **Solution**: Tool handles this automatically with cycle detection
   - Check `circular_dependencies_detected` field in response

**Performance Expectations:**
- Response time: <2.5s (95th percentile)
- Handles circular dependencies without infinite loops
- Configurable depth (1-5 levels)
- Returns relationship types and affected files

## Search Quality Issues

### Problem: Too Many Duplicate Results

**Symptoms:**
- Multiple results from the same file
- Low diversity ratio (<70%)
- Redundant information

**Diagnostic Steps:**

1. **Check Diversity Metrics**

```python
results = await search_knowledge(
    session_id=session_id,
    query="authentication",
    limit=10
)

print(f"Total results: {len(results['results'])}")
print(f"Unique files: {results['unique_files']}")
print(f"Diversity ratio: {results['diversity_ratio']:.0%}")
print(f"Deduplication applied: {results['deduplication_applied']}")
```

2. **Verify Deduplication Configuration**

Check `agentic-inquiry.yaml`:
```yaml
search:
  deduplication:
    enabled: true
    max_results_per_file: 1
    min_diversity_ratio: 0.7
```

**Common Causes:**

1. **Deduplication Disabled**
   - **Solution**: Enable in configuration
   ```yaml
   search:
     deduplication:
       enabled: true
   ```

2. **Configuration Not Loaded**
   - **Solution**: Restart server after configuration changes
   ```bash
   uv run ai --config agentic-inquiry.yaml
   ```

3. **Very Similar Content**
   - **Solution**: This is expected for files with similar content
   - Use filters to narrow search scope

**Quality Targets:**
- Duplication rate: <30%
- Diversity ratio: >70%
- Highest-scoring chunk per file kept
- Relevance ordering maintained

### Problem: No Search Results

**Symptoms:**
- Empty results array
- "No indexed content found" message

**Diagnostic Steps:**

1. **Check Index Status**

```python
info = await get_project_info(session_id=session_id)
overview = info['project_summary']['overview']

if overview['total_chunks'] == 0:
    print("⚠ No content indexed")
else:
    print(f"✓ {overview['total_chunks']} chunks indexed")
```

2. **Try Broader Query**

```python
# Try simpler, broader terms
results = await search_knowledge(
    session_id=session_id,
    query="function",  # Broader term
    limit=5
)
```

3. **Check Available Content**

```python
# Use preview mode to see what's available
results = await search_knowledge(
    session_id=session_id,
    query="",  # Empty query to see all
    preview=True
)

print(f"Content types: {results['facets']['by_type']}")
print(f"Languages: {results['facets']['by_language']}")
```

**Common Causes:**

1. **No Content Indexed**
   - **Solution**: Index your project
   ```python
   await add_knowledge(session_id=session_id, source=".")
   ```

2. **Query Too Specific**
   - **Solution**: Use broader search terms
   - Try synonyms or related concepts

3. **Wrong Project**
   - **Solution**: Verify project_id
   ```python
   info = await get_server_info()
   print("Available:", [p['project_id'] for p in info['available_projects']])
   ```

## Session Management Issues

### Problem: Session Not Found

**Symptoms:**
- Error: "Session not found or expired"
- Tools return SESSION_NOT_FOUND error

**Diagnostic Steps:**

1. **List Available Sessions**

```python
sessions = await list_sessions(
    project_id="my_project",
    include_expired=True
)

for session in sessions['sessions']:
    print(f"{session['session_id']}: {session['status']}")
```

2. **Check Session Status**

```python
try:
    session = await get_session(session_id=session_id)
    print(f"Status: {session['status']}")
    print(f"Last active: {session['last_active']}")
except Exception as e:
    print(f"Session error: {e}")
```

**Common Causes:**

1. **Session Expired**
   - **Solution**: Create new session
   ```python
   session = await create_session(project_id="my_project")
   ```

2. **Wrong Session ID**
   - **Solution**: Verify session_id is correct
   - List sessions to find active ones

3. **Session Timeout**
   - **Solution**: Sessions expire after 24 hours of inactivity
   - Resume or create new session

### Problem: Invalid Project ID

**Symptoms:**
- Error: "Invalid project_id format"
- Error: "Project not found"

**Diagnostic Steps:**

1. **Check Project ID Format**

```python
info = await get_server_info()
rules = info['project_id_rules']

print(f"Format: {rules['format']}")
print(f"Pattern: {rules['pattern']}")
print(f"Examples: {rules['examples']}")
```

2. **List Available Projects**

```python
info = await get_server_info()

for project in info['available_projects']:
    print(f"- {project['project_id']}")
    print(f"  Chunks: {project['total_chunks']}")
    print(f"  Health: {project['index_health']}")
```

**Common Causes:**

1. **Invalid Characters**
   - **Solution**: Use only alphanumeric, hyphens, underscores
   - Valid: `my-project`, `project_123`, `my_project`
   - Invalid: `my project` (space), `my.project` (dot), `my@project` (special char)

2. **Project Doesn't Exist**
   - **Solution**: Use `get_server_info()` to discover projects
   - Or create session with default project

3. **Case Sensitivity**
   - **Solution**: Project IDs are normalized to lowercase
   - `My_Project` becomes `my_project`

## Indexing Issues

### Problem: Indexing Fails or Hangs

**Applies to:** All usage modes (CLI, plugins, MCP)

**Symptoms:**
- Indexing returns errors
- Indexing takes very long time
- No progress events

**Diagnostic Steps:**

1. **Check Progress Events**

```python
result = await add_knowledge(
    session_id=session_id,
    source="src/"
)

print(f"Status: {result['status']}")
print(f"Processed: {result['items_processed']}")
print(f"Failed: {result['items_failed']}")

if result['errors']:
    print("Errors:")
    for error in result['errors']:
        print(f"  - {error}")
```

2. **Monitor Events**

```python
events = await get_events(
    session_id=session_id,
    event_types=["indexing"],
    status_filter=["error"],
    limit=20
)

for event in events['events']:
    print(f"[{event['timestamp']}] {event['message']}")
```

**Common Causes:**

1. **File Permission Issues**
   - **Solution**: Ensure files are readable
   - Check file permissions

2. **Unsupported File Types**
   - **Solution**: Check supported formats
   - Supported: Python, JS, TS, Java, Go, Rust, Markdown, PDF, DOCX, HTML

3. **Large Files**
   - **Solution**: Files >10MB may be slow
   - Consider splitting large files

4. **Path Validation Errors**
   - **Solution**: Ensure paths are within project directory
   - No directory traversal (../) allowed

**Performance Expectations:**
- Progress events every 10 files
- Completion event with summary
- Async processing for speed

### Problem: Entities Not Created During Indexing

**Symptoms:**
- `total_entities` is 0 after indexing
- `understand_entity` finds nothing
- No code symbols extracted

**Diagnostic Steps:**

1. **Verify Code Files Indexed**

```python
info = await get_project_info(session_id=session_id)
overview = info['project_summary']['overview']

print(f"Total files: {overview['total_files']}")
print(f"Total chunks: {overview['total_chunks']}")
print(f"Total entities: {overview['total_entities']}")
print(f"Languages: {overview['languages']}")
```

2. **Check File Types**

```python
# Ensure you're indexing code files
result = await add_knowledge(
    session_id=session_id,
    source="src/"  # Directory with code files
)

# Check what was processed
print(f"Processed: {result['items_processed']} items")
```

**Common Causes:**

1. **No Code Files**
   - **Solution**: Ensure directory contains code files (.py, .js, .ts, etc.)
   - Check `languages` in project info

2. **Parser Errors**
   - **Solution**: Check errors in add_knowledge response
   - Some files may fail to parse

3. **Empty Files**
   - **Solution**: Empty files don't create entities
   - This is expected behavior

## Schema Mismatch Issues

### Problem: Schema Validation Errors During Indexing

**Applies to:** All usage modes (CLI, plugins, MCP)

**Symptoms:**
- Error: "Schema validation failed for document_chunks"
- Error: "Field 'line_start' not found"
- Indexing fails with field mismatch errors

**Diagnostic Steps:**

1. **Check Error Details**

```python
try:
    result = await add_knowledge(
        session_id=session_id,
        source="src/auth.py"
    )
except Exception as e:
    print(f"Error: {e}")
    # Look for schema validation details
```

2. **Verify Schema Mapping Configuration**

Check `agentic-inquiry.yaml`:
```yaml
indexing:
  schema_mapping:
    enabled: true
    field_mappings:
      line_start: start_line
      line_end: end_line
```

3. **Check Database Schema**

```python
# Use diagnostic script to inspect schema
# See .tmp_scripts/inspect_schema.py for example
```

**Common Causes:**

1. **Schema Mapping Disabled**
   - **Solution**: Enable schema mapping in configuration
   ```yaml
   indexing:
     schema_mapping:
       enabled: true
   ```

2. **Missing Field Mappings**
   - **Solution**: Add field mappings to configuration
   ```yaml
   indexing:
     schema_mapping:
       field_mappings:
         line_start: start_line
         line_end: end_line
         # Add other mappings as needed
   ```

3. **Database Schema Changed**
   - **Solution**: Update field mappings to match new schema
   - Check test_results/schema_comparison_document.md for reference

4. **Configuration Not Loaded**
   - **Solution**: Restart server after configuration changes
   ```bash
   uv run ai --config agentic-inquiry.yaml
   ```

**Resolution Steps:**

1. **Enable Schema Mapping**:
   ```yaml
   # agentic-inquiry.yaml
   indexing:
     schema_mapping:
       enabled: true
       field_mappings:
         line_start: start_line
         line_end: end_line
   ```

2. **Enable Schema Validation**:
   ```yaml
   indexing:
     schema_validation:
       enabled: true
       strict_mode: false
       cache_schemas: true
   ```

3. **Restart Server**:
   ```bash
   uv run ai
   ```

4. **Retry Indexing**:
   ```python
   result = await add_knowledge(
       session_id=session_id,
       source="src/"
   )
   print(f"Status: {result['status']}")
   ```

**Prevention:**

- Keep schema mapping configuration up to date
- Enable schema validation for early error detection
- Review schema comparison documents in test_results/
- Test indexing with sample files before bulk operations

**Performance Impact:**

- Schema mapping adds <5ms overhead per chunk
- Negligible for typical file sizes
- Pre-flight validation prevents costly database errors

## Context Building Issues

### Problem: build_context Returns Empty Results

**Symptoms:**
- Empty code, documentation, and memories arrays
- No context assembled despite indexed content
- Error: "No context found"

**Diagnostic Steps:**

1. **Verify Content is Indexed**

```python
# Check if content exists
info = await get_project_info(session_id=session_id)
overview = info['project_summary']['overview']

print(f"Total chunks: {overview['total_chunks']}")
print(f"Total files: {overview['total_files']}")

if overview['total_chunks'] == 0:
    print("⚠ No content indexed - need to index first")
```

2. **Try Basic Search**

```python
# Verify search works
results = await search_knowledge(
    session_id=session_id,
    query="authentication",
    limit=5
)

print(f"Search results: {len(results['results'])}")
```

3. **Check Context Builder Configuration**

Check `agentic-inquiry.yaml`:
```yaml
context:
  builder:
    enabled: true
    fallback_to_search: true
```

**Common Causes:**

1. **No Indexed Content**
   - **Solution**: Index your project first
   ```python
   await add_knowledge(session_id=session_id, source=".")
   ```

2. **Context Builder Disabled**
   - **Solution**: Enable in configuration
   ```yaml
   context:
     builder:
       enabled: true
   ```

3. **Query Too Specific**
   - **Solution**: Use broader search terms
   ```python
   # Instead of very specific query
   context = await build_context(
       session_id=session_id,
       query="authentication"  # Broader term
   )
   ```

4. **Token Budget Too Small**
   - **Solution**: Increase max_tokens
   ```python
   context = await build_context(
       session_id=session_id,
       query="authentication",
       max_tokens=8000  # Increase from default 4000
   )
   ```

**Resolution Steps:**

1. **Enable Context Builder**:
   ```yaml
   # agentic-inquiry.yaml
   context:
     builder:
       enabled: true
       fallback_to_search: true
   ```

2. **Configure Token Budget**:
   ```yaml
   context:
     token_budget:
       default_budget: 4000
       min_budget: 500
       max_budget: 16000
   ```

3. **Restart Server**:
   ```bash
   uv run ai
   ```

4. **Try with Different Parameters**:
   ```python
   # Try comprehensive depth
   context = await build_context(
       session_id=session_id,
       query="authentication",
       depth="comprehensive",
       focus="balanced",
       max_tokens=8000
   )
   ```

**Fallback Strategy:**

The tool automatically falls back to basic search if context builder fails:

```python
# Even if context builder fails, you get results
context = await build_context(
    session_id=session_id,
    query="authentication"
)

# Check if fallback was used
if context.get('fallback_used'):
    print("⚠ Context builder failed, using search fallback")
```

**Performance Expectations:**

- Response time: <3s (95th percentile)
- Token budget enforced (used <= max_tokens)
- Focus parameter affects code vs. docs ratio
- Depth parameter affects result count

### Problem: Token Budget Exceeded

**Symptoms:**
- Warning: "Token budget exceeded"
- Context truncated unexpectedly
- Missing expected results

**Diagnostic Steps:**

1. **Check Token Usage**

```python
context = await build_context(
    session_id=session_id,
    query="authentication",
    max_tokens=4000
)

usage = context['token_usage']
print(f"Used: {usage['estimated_tokens']}")
print(f"Budget: {usage['budget']}")
print(f"Remaining: {usage['remaining']}")
```

2. **Verify Token Budget Configuration**

Check `agentic-inquiry.yaml`:
```yaml
context:
  token_budget:
    default_budget: 4000
    min_budget: 500
    max_budget: 16000
```

**Common Causes:**

1. **Budget Too Small**
   - **Solution**: Increase max_tokens parameter
   ```python
   context = await build_context(
       session_id=session_id,
       query="authentication",
       max_tokens=8000  # Increase budget
   )
   ```

2. **Too Many Results**
   - **Solution**: Use focused depth instead of comprehensive
   ```python
   context = await build_context(
       session_id=session_id,
       query="authentication",
       depth="focused",  # Instead of "comprehensive"
       max_tokens=4000
   )
   ```

3. **Large Content Items**
   - **Solution**: This is expected for large files
   - Token budget prevents context overflow

**Resolution Steps:**

1. **Adjust Token Budget**:
   ```python
   # Increase for comprehensive analysis
   context = await build_context(
       session_id=session_id,
       query="authentication",
       max_tokens=8000
   )
   ```

2. **Use Appropriate Depth**:
   ```python
   # Use focused for most tasks
   context = await build_context(
       session_id=session_id,
       query="authentication",
       depth="focused",  # 10-15 items
       max_tokens=4000
   )
   ```

3. **Check Token Usage**:
   ```python
   # Monitor token usage
   usage = context['token_usage']
   if usage['remaining'] < 500:
       print("⚠ Token budget nearly exhausted")
   ```

## Query Sanitization Issues

### Problem: Search Queries with Special Characters Fail

**Symptoms:**
- Error: "Syntax error in query"
- Error: "Invalid query format"
- Queries with "?" or "*" fail

**Diagnostic Steps:**

1. **Test Query Sanitization**

```python
# Try query with special characters
try:
    results = await search_knowledge(
        session_id=session_id,
        query="how does authentication work?",  # Contains "?"
        limit=5
    )
    print(f"✓ Query sanitization working: {len(results['results'])} results")
except Exception as e:
    print(f"✗ Query sanitization failed: {e}")
```

2. **Check Configuration**

Check `agentic-inquiry.yaml`:
```yaml
search:
  query_sanitization:
    enabled: true
    escape_special_chars: true
    preserve_wildcards: false
```

**Common Causes:**

1. **Query Sanitization Disabled**
   - **Solution**: Enable in configuration
   ```yaml
   search:
     query_sanitization:
       enabled: true
   ```

2. **Special Characters Not Escaped**
   - **Solution**: Enable escape_special_chars
   ```yaml
   search:
     query_sanitization:
       escape_special_chars: true
   ```

3. **Configuration Not Loaded**
   - **Solution**: Restart server after configuration changes
   ```bash
   uv run ai
   ```

**Resolution Steps:**

1. **Enable Query Sanitization**:
   ```yaml
   # agentic-inquiry.yaml
   search:
     query_sanitization:
       enabled: true
       escape_special_chars: true
       preserve_wildcards: false
   ```

2. **Restart Server**:
   ```bash
   uv run ai
   ```

3. **Test with Special Characters**:
   ```python
   # Test various special characters
   test_queries = [
       "how does authentication work?",
       "what is the * operator?",
       "find [brackets] in code",
       "search (parentheses) usage"
   ]
   
   for query in test_queries:
       results = await search_knowledge(
           session_id=session_id,
           query=query,
           limit=5
       )
       print(f"✓ '{query}': {len(results['results'])} results")
   ```

**Special Characters Handled:**

- **Question marks** (?): Escaped for literal matching
- **Asterisks** (*): Escaped unless preserve_wildcards=true
- **Brackets** ([], {}): Escaped for literal matching
- **Parentheses** (()): Escaped for literal matching
- **Backslashes** (\\): Escaped for literal matching

**Example Queries:**

```python
# All these queries work with sanitization enabled

# Question marks
results = await search_knowledge(
    session_id=session_id,
    query="how does authentication work?",
    limit=5
)

# Asterisks
results = await search_knowledge(
    session_id=session_id,
    query="what is the * operator?",
    limit=5
)

# Brackets
results = await search_knowledge(
    session_id=session_id,
    query="find [brackets] in code",
    limit=5
)

# Parentheses
results = await search_knowledge(
    session_id=session_id,
    query="search (parentheses) usage",
    limit=5
)
```

**Performance Impact:**

- Query sanitization adds <1ms overhead per query
- Negligible compared to search time
- Prevents syntax errors that would fail the query

**Wildcard Preservation:**

If you want to use wildcards intentionally:

```yaml
search:
  query_sanitization:
    preserve_wildcards: true
```

Then use wildcards explicitly:
```python
# With preserve_wildcards=true
results = await search_knowledge(
    session_id=session_id,
    query="auth*",  # Wildcard search
    limit=5
)
```

## Storage Maintenance Issues

**Applies to:** All usage modes when using LanceDB backend

> **Note:** As of v1.0, LanceDB maintenance is **automated** via `MaintenanceManager`. Maintenance runs automatically on `indexing.completed` and `project.closed` events. The information below is provided for troubleshooting or manual intervention when needed.

### Problem: Disk Space Exhausted or Indexes Extremely Large

**Symptoms:**
- Disk running out of space after running tests
- LanceDB indexes growing to tens or hundreds of GB
- Queries becoming slow
- `run_maintenance` doesn't reclaim expected space

**Diagnostic Steps:**

1. **Check Index Sizes**

```bash
# Check total size of LanceDB data
du -sh .agentic-inquiry/lancedb/

# Check individual table sizes
du -sh .agentic-inquiry/lancedb/*.lance | sort -rh
```

2. **Check Version Count**

```python
import lancedb

db = lancedb.connect('.agentic-inquiry/lancedb')
for table_name in db.table_names():
    table = db.open_table(table_name)
    versions = table.list_versions()
    print(f"{table_name}: {len(versions)} versions")
```

**Root Cause:**

LanceDB uses MVCC (Multi-Version Concurrency Control), creating new versions on every write. During test runs, thousands of versions accumulate. The `run_maintenance` tool defaults to `cleanup_hours=1.0`, meaning it only removes versions older than 1 hour. If tests ran within the last hour, **no versions are cleaned up**.

**Example:**
- 2,600+ versions across tables = 158GB
- After aggressive cleanup = 608MB
- Space reclaimed = 157GB

**Solution: Aggressive Cleanup for Test Environments**

```python
import lancedb
from datetime import timedelta

db = lancedb.connect('.agentic-inquiry/lancedb')

for table_name in db.table_names():
    table = db.open_table(table_name)

    # Compact fragments, refresh indexes, and prune versions older
    # than 60 seconds (aggressive) in one call
    table.optimize(
        cleanup_older_than=timedelta(seconds=60),
        delete_unverified=True,
    )

    print(f"Cleaned up {table_name}")
```

**Via MCP Tool:**

```python
# Use a very short cleanup window for test data
result = await run_maintenance(
    session_id=session_id,
    cleanup_hours=0.01  # ~36 seconds - removes almost all old versions
)
```

**Recommended Cleanup Timings:**

| Environment | `cleanup_hours` | Description |
|-------------|-----------------|-------------|
| After tests | `0.01` (36 sec) | Aggressive - removes almost all old versions |
| Development | `0.5` (30 min) | Keeps recent work for debugging |
| Production | `1.0` (1 hour) | Default - preserves recent rollback capability |
| High-availability | `24.0` (1 day) | Conservative - maximum rollback window |

**Automated Test Cleanup:**

Add to your test teardown or CI/CD pipeline:

```python
# tests/conftest.py
import pytest
import lancedb
from datetime import timedelta

@pytest.fixture(scope="session", autouse=True)
def cleanup_lancedb_after_tests():
    """Clean up LanceDB versions after test session."""
    yield  # Run tests

    # Aggressive cleanup after tests complete
    try:
        db = lancedb.connect('.agentic-inquiry/lancedb')
        for table_name in db.table_names():
            table = db.open_table(table_name)
            table.optimize(
                cleanup_older_than=timedelta(seconds=60),
                delete_unverified=True
            )
    except Exception:
        pass  # Ignore errors during cleanup
```

**Prevention:**

1. **Run maintenance after bulk operations**: Always run `run_maintenance` after indexing or test runs
2. **Use appropriate cleanup timing**: Use `cleanup_hours=0.01` for test environments
3. **Monitor disk usage**: Set up alerts for storage thresholds
4. **Consider fresh indexes for tests**: Delete `.agentic-inquiry/lancedb/` before test runs if data isn't needed

**Common Causes:**

1. **Default cleanup_hours too long**
   - **Solution**: Use `cleanup_hours=0.01` for test data

2. **Maintenance ran but versions too recent**
   - **Solution**: Wait 1+ hour or use shorter cleanup window

3. **Many small writes during tests**
   - **Solution**: Each write creates a version; cleanup after tests complete

4. **Compaction without cleanup**
   - **Solution**: `table.optimize()` with a short `cleanup_older_than` compacts and reclaims space; `compact_files()` and `cleanup_old_versions()` need `pylance`, which lancedb 0.26+ no longer bundles

**Performance Expectations:**

- Cleanup speed: ~1000 versions/second
- Space reclaimed: Up to 99% in test environments
- Query performance improves after compaction

## Performance Issues

**Applies to:** All usage modes (CLI, plugins, MCP)

### Problem: Slow Response Times

**Symptoms:**
- Operations take >5 seconds to respond
- Timeouts occur
- Poor user experience

**Diagnostic Steps:**

1. **Check Response Times**

```python
import time

start = time.time()
results = await search_knowledge(
    session_id=session_id,
    query="authentication"
)
duration = time.time() - start

print(f"Search took {duration:.2f}s")
print(f"Target: <2s (95th percentile)")
```

2. **Check Index Size**

```python
info = await get_project_info(session_id=session_id)
overview = info['project_summary']['overview']

print(f"Total chunks: {overview['total_chunks']}")
print(f"Total entities: {overview['total_entities']}")
```

**Performance Targets:**
- Entity resolution: <1.5s (95th percentile)
- Impact analysis: <2.5s (95th percentile)
- Search: <2s (95th percentile)
- Context building: <3s (95th percentile)

**Common Causes:**

1. **Large Index**
   - **Solution**: Consider splitting into multiple projects
   - Use filters to narrow searches

2. **Deep Traversal**
   - **Solution**: Reduce depth parameter
   ```python
   impact = await analyze_impact(
       session_id=session_id,
       entity="MyClass",
       depth=1  # Reduce from 3 to 1
   )
   ```

3. **No Caching**
   - **Solution**: Enable caching in configuration
   ```yaml
   entity_resolution:
     cache_enabled: true
     cache_ttl_seconds: 3600
   ```

4. **Cold Start**
   - **Solution**: First query after restart is slower
   - Subsequent queries use cache

## Configuration Issues

**Applies to:** All usage modes (CLI, plugins, MCP)

### Problem: Configuration Not Applied

**Symptoms:**
- Changes to `agentic-inquiry.yaml` not taking effect
- Default values used instead of configured values

**Diagnostic Steps:**

1. **Verify Configuration File Location**

```bash
# Check if file exists
ls -la agentic-inquiry.yaml

# Check configuration is valid YAML
uv run python -c "
import yaml
with open('agentic-inquiry.yaml') as f:
    config = yaml.safe_load(f)
    print('✓ Configuration is valid YAML')
"
```

2. **Check Configuration Loading**

For MCP server:
```bash
# Start with explicit config file
uv run ai --config agentic-inquiry.yaml --log-level DEBUG
```

For CLI or plugins, configuration is loaded automatically from the project root.

3. **Verify Configuration Loaded**

```python
# Check server info for configuration
info = await get_server_info()
print(f"Server version: {info['server']['version']}")
```

**Common Causes:**

1. **Wrong File Location**
   - **Solution**: Place `agentic-inquiry.yaml` in project root
   - Or use `--config` flag to specify path

2. **Invalid YAML Syntax**
   - **Solution**: Validate YAML syntax
   - Check indentation (use spaces, not tabs)

3. **Server Not Restarted (MCP server only)**
   - **Solution**: Restart MCP server after configuration changes
   ```bash
   # Stop server (Ctrl+C)
   # Start again
   uv run ai
   ```
   - **Note:** CLI and plugin users don't need to restart a server; configuration is loaded on each operation.

4. **Environment Variables Override**
   - **Solution**: Check for `AI_*` environment variables
   - Environment variables take precedence over config file

## FAQ

### How do I verify entity indexing is working?

```python
# 1. Index code
await add_knowledge(session_id=session_id, source="src/")

# 2. Check entity count
info = await get_project_info(session_id=session_id)
entities = info['project_summary']['overview']['total_entities']
print(f"Entities indexed: {entities}")

# 3. Try to find an entity
entity = await understand_entity(
    session_id=session_id,
    entity="MyClass"
)
print(f"Found: {entity['success']}")
```

### Why are my search results all from the same file?

This indicates deduplication is disabled. Enable it:

```yaml
# agentic-inquiry.yaml
search:
  deduplication:
    enabled: true
    max_results_per_file: 1
```

Then restart the server.

### How do I improve entity resolution success rate?

1. **Ensure code is indexed**: Run `add_knowledge` on your source directories
2. **Use correct entity names**: Check spelling and case
3. **Try entity type**: Specify `entity_type="class"` or `entity_type="function"`
4. **Check suggestions**: Error messages include similar entity names

### What's the difference between depth levels in impact analysis?

- **depth=1**: Direct dependencies only (fast, focused)
- **depth=2**: Two levels of relationships (recommended, balanced)
- **depth=3**: Three levels (comprehensive, slower)
- **depth=4-5**: Deep traversal (very comprehensive, may be slow)

### How do I handle circular dependencies?

The tool automatically detects and handles circular dependencies. Check the response:

```python
impact = await analyze_impact(
    session_id=session_id,
    entity="MyClass",
    depth=3
)

if impact['circular_dependencies_detected']:
    print("⚠ Circular dependencies found")
    # Tool still returns valid results
```

### Why do memory summaries sometimes appear empty?

This was fixed in v1.0. All memories now have 100% summary persistence. If you're seeing empty summaries:

1. **Update to v1.0+**: Ensure you're running the latest version
2. **Re-save memories**: Old memories may need to be re-saved
3. **Check response**: Summaries should always be present

### How do I monitor indexing progress?

```python
result = await add_knowledge(
    session_id=session_id,
    source="src/"
)

# Check progress events
for event in result['progress_events']:
    if event['event_type'] == 'progress':
        print(f"[{event['percent']}%] {event['file']}")
```

### What file types are supported?

**Code:**
- Python (.py)
- JavaScript (.js)
- TypeScript (.ts)
- Java (.java)
- Go (.go)
- Rust (.rs)
- C# (.cs)
- C/C++ (.c, .cpp, .h)

**Documents:**
- Markdown (.md)
- PDF (.pdf)
- DOCX (.docx)
- HTML (.html)
- Plain text (.txt)

### How do I debug "Entity not found" errors?

1. **Check if entity exists**:
   ```python
   results = await search_knowledge(
       session_id=session_id,
       query="MyClass",
       filters={"type": "code"}
   )
   ```

2. **Check entity count**:
   ```python
   info = await get_project_info(session_id=session_id)
   print(f"Total entities: {info['project_summary']['overview']['total_entities']}")
   ```

3. **Try case-insensitive**:
   ```python
   entity = await understand_entity(
       session_id=session_id,
       entity="myclass"  # lowercase
   )
   ```

4. **Check suggestions**:
   - Error messages include similar entity names
   - Use suggestions to find correct name

### How do I fix schema validation errors?

Schema validation errors occur when ParserChunk fields don't match database schema:

1. **Enable schema mapping**:
   ```yaml
   # agentic-inquiry.yaml
   indexing:
     schema_mapping:
       enabled: true
   ```

2. **Add field mappings**:
   ```yaml
   indexing:
     schema_mapping:
       field_mappings:
         line_start: start_line
         line_end: end_line
   ```

3. **Restart server**:
   ```bash
   uv run ai
   ```

4. **Retry indexing**:
   ```python
   result = await add_knowledge(
       session_id=session_id,
       source="src/"
   )
   ```

### Why is build_context returning empty results?

Common causes and solutions:

1. **No indexed content**: Run `add_knowledge` first
2. **Context builder disabled**: Enable in configuration
3. **Query too specific**: Use broader search terms
4. **Token budget too small**: Increase max_tokens parameter

The tool automatically falls back to search if context builder fails, so you should always get some results.

### How do I use queries with special characters?

Enable query sanitization to handle special characters:

```yaml
# agentic-inquiry.yaml
search:
  query_sanitization:
    enabled: true
    escape_special_chars: true
```

Then queries with ?, *, [], (), etc. work correctly:

```python
results = await search_knowledge(
    session_id=session_id,
    query="how does authentication work?",  # ? is escaped
    limit=5
)
```

### What's the difference between focus parameters in build_context?

- **balanced**: 40% code, 40% docs, 20% memories (default)
- **code**: 70% code, 20% docs, 10% memories
- **documentation**: 20% code, 70% docs, 10% memories

Choose based on your task:
- Use "code" for implementation tasks
- Use "documentation" for understanding concepts
- Use "balanced" for general exploration

### How do I control token usage in build_context?

Use the max_tokens parameter and depth setting:

```python
# Focused context with 4000 token budget
context = await build_context(
    session_id=session_id,
    query="authentication",
    depth="focused",  # 10-15 items
    max_tokens=4000
)

# Comprehensive context with larger budget
context = await build_context(
    session_id=session_id,
    query="authentication",
    depth="comprehensive",  # up to 30 items
    max_tokens=8000
)

# Check usage
print(f"Used: {context['token_usage']['estimated_tokens']}")
print(f"Remaining: {context['token_usage']['remaining']}")
```

## Getting Help

If you're still experiencing issues:

1. **Check Logs**: Review logs for detailed error information
2. **Enable Debug Logging**:
   - MCP server: `uv run ai --log-level DEBUG`
   - CLI: `ai --log-level DEBUG <command>`
3. **Review Documentation**: See [Main Documentation](../../README.md) or [MCP Documentation](./README.md)
4. **Report Issues**: Include error messages, logs, and reproduction steps

## Performance Tuning

### Optimize Entity Resolution

```yaml
# agentic-inquiry.yaml
entity_resolution:
  case_insensitive: true
  fuzzy_matching:
    enabled: true
    threshold: 0.8
  cache_enabled: true
  cache_ttl_seconds: 3600
```

### Optimize Search

```yaml
# agentic-inquiry.yaml
search:
  deduplication:
    enabled: true
    max_results_per_file: 1
  cache:
    enabled: true
    ttl_seconds: 300
```

### Optimize Impact Analysis

```yaml
# agentic-inquiry.yaml
impact_analysis:
  default_depth: 2
  max_depth: 5
  include_indirect: true
```

### Optimize Indexing

```yaml
# agentic-inquiry.yaml
indexing:
  concurrent_files: 10
  chunk_size: 1000
  overlap: 200
```

## Quick Reference: Common Issues

From retrospective analysis (Jan 10, 2026). For detailed diagnosis, see sections above.

| Problem | Cause | Solution |
|---------|-------|----------|
| Zero relationships after indexing | flush_relationships not called | Wait for indexing to complete fully |
| Entity not found | Type mismatch between tools | Use consistent entity_type across tools |
| FTS search returns nothing | FTS table not initialized | Re-index with fresh database |
| analyze_impact shows no impact | Empty relationship graph | Verify relationships > 0 with list_entities |
| Different IDs for same entity | Entity resolution inconsistent | File bug - each tool should resolve same ID |
| Slow search performance | Missing index or cache | Enable caching, check LanceDB indexes |
| Memory not persisting | Importance too low | Use importance >= 0.7 for cross-session |
| Graph traverse returns empty | No relationships of that type | Check relationship_types filter |
| Duplicate entities | Re-indexing without cleanup | Delete data dir before full re-index |
| Timeout on large files | Processing limit too low | Increase processing_semaphore_limit |

**Prevention:** See AGENTS.md "Fragile Areas" and "Quality Checklist" sections.

## Next Steps

- Review [Tool Reference](./tools/README.md) for complete tool documentation
- Check [Workflows](./workflows/README.md) for common usage patterns
- See [Configuration Guide](./configuration.md) for advanced settings
