# MCP Server Configuration Guide

> **Note:** The MCP server is a secondary interface. Most users should use the [Claude Code plugins](../../README.md) instead.

Complete guide to configuring the Agentic Inquiry MCP Server for advanced use cases.

## Primary Interface: Claude Code Plugins

**Most users should enable the Claude Code plugins instead of running the MCP server directly.**

### Enable Plugins

Add to `.claude/settings.json` in your project:

```json
{
  "extraKnownMarketplaces": {
    "agentic-inquiry": {
      "source": {
        "source": "directory",
        "path": "./extensions/claude"
      }
    }
  },
  "enabledPlugins": {
    "ai@agentic-inquiry": true,
    "ai-dev@agentic-inquiry": true
  }
}
```

### Use Plugin Skills

Once enabled, use skills directly in Claude Code:

- `/ai:search <query>` - Semantic search across code and docs
- `/ai:index <path>` - Index a codebase
- `/ai:onboard <path>` - AI-powered codebase onboarding
- `/ai:entity <name>` - Understand a code entity
- `/ai:impact <symbol>` - Analyze change impact
- `/ai:status` - Show project state

**Full plugin reference:** [AGENTS.md](../../AGENTS.md)

### When to Use the MCP Server

Only use the MCP server directly when you need:

- **External tool integration** - Connect non-Claude clients to Agentic Inquiry
- **Production HTTP API** - Deploy as a standalone service for multiple clients
- **Custom MCP workflows** - Build specialized MCP-based tooling
- **Non-Claude MCP clients** - Use Agentic Inquiry from other MCP-compatible agents

For local development and Claude Code integration, the plugin system handles everything automatically.

## Configuration File

The MCP server uses `config/mcp.yaml` for configuration. All settings can be overridden with environment variables.

## Configuration Structure

```yaml
mcp:
  enabled: true
  server: {...}
  tools: {...}
  api: {...}
  defaults: {...}
  behavior: {...}
  logging: {...}
```

---

## Command-Line Configuration

### Basic Usage

**Note:** These commands run the MCP server directly. Most users should use Claude Code plugins instead.

```bash
# Uses current directory name as project
uv run ai

# Specify a different project
uv run ai my_project

# HTTP transport for web deployments
uv run ai --transport http --port 8000

# All options combined
uv run ai my_project --transport http --host 0.0.0.0 --port 8000
```

### Project ID

The `ai` command automatically uses the current directory name as the project ID:

```bash
# Uses current directory name
uv run ai

# Override with specific project
uv run ai my_project

# Or use the flag
uv run ai --project-id my_project
```

**Project ID Requirements:**
- **Format**: Alphanumeric characters, hyphens, and underscores only
- **Pattern**: `^[a-zA-Z0-9_-]+$`
- **Length**: 1-64 characters
- **Normalization**: Automatically converted to lowercase
- **Examples**: `my-project`, `project_123`, `my_project`

**Invalid Project IDs:**
- `my project` (contains space)
- `my.project` (contains dot)
- `my@project` (contains special character)
- `` (empty string)
- `a` * 65 (too long, max 64 characters)

Use `get_server_info()` to see format requirements and discover available projects.

### Custom Configuration File

Use a custom configuration file instead of defaults:

```bash
uv run ai --config /path/to/custom.yaml

# With specific project
uv run ai my_project --config custom.yaml
```

### Command-Line Logging

Control log level and output:

```bash
# Debug logging
uv run ai --log-level DEBUG

# Log to file
uv run ai --log-file /var/log/AGV-mcp.log

# With specific project
uv run ai my_project --log-level DEBUG --log-file debug.log
```

**Available log levels:**
- `DEBUG` - Detailed diagnostic information
- `INFO` - General informational messages (default)
- `WARNING` - Warning messages
- `ERROR` - Error messages only

---

## Transport Configuration (MCP-Specific)

For users running the MCP server, three transport mechanisms are available. Most users should use the Claude Code plugins instead, which handle this automatically.

### STDIO (Standard Input/Output)

**Characteristics:**
- No network exposure
- Direct process communication
- Automatic lifecycle management
- Zero configuration required

**Usage:**
```bash
# Simple - uses current directory as project name
uv run ai

# Or specify project
uv run ai my_project
```

**How it works:**
- Server communicates via stdin/stdout
- Agent starts server as subprocess
- Server lifecycle managed by agent
- No network ports required

**When to use:**
- Local development with MCP server
- Single-user scenarios
- Maximum security (no network exposure)

### HTTP (Streamable HTTP)

**Characteristics:**
- Network-accessible
- Efficient bidirectional streaming
- RESTful endpoints
- Supports authentication and CORS

**Usage:**
```bash
# Localhost only
uv run ai --transport http --host 127.0.0.1 --port 8000

# Or specify project
uv run ai my_project --transport http --port 8000

# Accessible from network
uv run ai --transport http --host 0.0.0.0 --port 8000
```

**Server endpoint:** `http://host:port/mcp`

**Advanced usage:**
```bash
uv run python -m agentic_inquiry.mcp.cli \
  --project-id my_project \
  --transport http \
  --host 0.0.0.0 \
  --port 8000
```

**When to use:**
- Production MCP deployments
- Multiple concurrent MCP clients
- Remote access to MCP server
- Need authentication/CORS

**Configuration:**
```yaml
mcp:
  api:
    enabled: true
    host: "0.0.0.0"
    port: 8000
    cors:
      enabled: true
      origins:
        - "https://app.example.com"
    auth:
      enabled: true
      api_key: "${MCP_API_KEY}"
```

### SSE (Server-Sent Events)

**Best for:** Legacy compatibility

**Characteristics:**
- Network-accessible
- One-way streaming (server to client)
- Not recommended for new deployments
- Limited compared to HTTP transport

**Usage:**
```bash
uv run ai --transport sse --port 8000
```

**Server endpoint:** `http://host:port/sse`

**When to use:**
- Legacy system compatibility
- One-way communication sufficient
- HTTP transport not available

**Note:** SSE is maintained for backward compatibility but HTTP transport is recommended for all new deployments.

### Transport Comparison

| Feature | STDIO | HTTP | SSE |
|---------|-------|------|-----|
| Network exposure | No | Yes | Yes |
| Multiple clients | No | Yes | Yes |
| Bidirectional | Yes | Yes | No |
| Authentication | N/A | Yes | Yes |
| CORS | N/A | Yes | Yes |
| Production ready | No | Yes | No |
| Best for | Development | Production | Legacy |

### Choosing a Transport

**Use STDIO when:**
- Developing locally with MCP server
- Single-user scenarios
- Maximum security needed

**Use HTTP when:**
- Deploying MCP server to production
- Multiple MCP clients need access
- Authentication/CORS required

**Use SSE when:**
- Legacy MCP compatibility required
- HTTP transport not available

---

## Server Settings

```yaml
mcp:
  server:
    name: "Agentic Inquiry"
    version: "1.0.0"
    description: "AI-powered code and knowledge search"
```

**Environment Variables:**
- `AI_MCP_SERVER_NAME` - Server name
- `AI_MCP_SERVER_VERSION` - Server version
- `AI_MCP_SERVER_DESCRIPTION` - Server description

---

## Tool Configuration (MCP-Specific)

### Cognitive Tools

```yaml
mcp:
  tools:
    cognitive:
      enabled: true  # Enable all cognitive tools
```

When using the MCP server, cognitive tools provide:
- Session management (create_session, get_session, etc.)
- Search & discovery (search_knowledge, find_patterns)
- Context building (build_context, understand_entity)
- Analysis (analyze_impact, get_project_info)
- Memory system (save_memory, recall_memories)
- Knowledge management (add_knowledge, get_events)

**Environment Variables:**
- `AI_MCP_TOOLS_COGNITIVE_ENABLED` - Enable/disable cognitive tools

### Direct Access Tools

```yaml
mcp:
  tools:
    direct_access:
      enabled: false  # Disabled by default
```

Direct access tools include:
- index_files - Granular indexing control
- search_code - Code-only search
- search_docs - Documentation-only search
- graph_traverse - Custom graph navigation
- get_by_id - Bulk entity retrieval

**Environment Variables:**
- `AI_MCP_TOOLS_DIRECT_ACCESS_ENABLED` - Enable/disable direct access tools

**CLI Override:**
```bash
uv run python -m agentic_inquiry.mcp.cli --enable-direct-tools
```

---

## API Configuration

```yaml
mcp:
  api:
    enabled: true
    host: "localhost"
    port: 8765
    cors:
      enabled: true
      origins: ["*"]
    auth:
      enabled: false
      api_key: null
```

### API Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | true | Enable FastMCP API |
| `host` | localhost | Bind address |
| `port` | 8765 | Port number |

**Environment Variables:**
- `AI_MCP_API_ENABLED` - Enable/disable API
- `AI_MCP_API_HOST` - Bind address
- `AI_MCP_API_PORT` - Port number

### CORS Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | true | Enable CORS |
| `origins` | ["*"] | Allowed origins |

**Environment Variables:**
- `AI_MCP_API_CORS_ENABLED` - Enable/disable CORS
- `AI_MCP_API_CORS_ORIGINS` - Comma-separated origins

**Production Example:**
```yaml
mcp:
  api:
    cors:
      enabled: true
      origins:
        - "https://app.example.com"
        - "https://staging.example.com"
```

### Authentication

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | false | Enable API key auth |
| `api_key` | null | API key |

**Environment Variables:**
- `AI_MCP_API_AUTH_ENABLED` - Enable/disable auth
- `AI_MCP_API_AUTH_API_KEY` - API key

**Generate API Key:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Use API Key:**
```bash
curl -H "X-API-Key: your-key" http://localhost:8765/api/search
```

**Security Notes:**
- API key comparison uses constant-time algorithms to prevent timing attacks
- Store API keys in environment variables, never in code
- Rotate API keys regularly (recommended: every 90 days)
- Use different keys for different environments

See [Security Guide](./security.md#api-authentication) for detailed security best practices.

---

## Default Behavior

### Search Defaults

```yaml
mcp:
  defaults:
    search:
      limit: 20
      hybrid_weight: 0.7
      min_relevance: 0.3
```

| Setting | Default | Description |
|---------|---------|-------------|
| `limit` | 20 | Default result limit |
| `hybrid_weight` | 0.7 | Vector vs FTS weight (0-1) |
| `min_relevance` | 0.3 | Minimum relevance score |

**Environment Variables:**
- `AI_MCP_DEFAULTS_SEARCH_LIMIT`
- `AI_MCP_DEFAULTS_SEARCH_HYBRID_WEIGHT`
- `AI_MCP_DEFAULTS_SEARCH_MIN_RELEVANCE`

### Context Defaults

```yaml
mcp:
  defaults:
    context:
      max_tokens: 4000
      depth: "broad"
      include_relationships: true
```

| Setting | Default | Description |
|---------|---------|-------------|
| `max_tokens` | 4000 | Default token budget |
| `depth` | broad | Context depth (focused/broad/comprehensive) |
| `include_relationships` | true | Include entity relationships |

**Environment Variables:**
- `AI_MCP_DEFAULTS_CONTEXT_MAX_TOKENS`
- `AI_MCP_DEFAULTS_CONTEXT_DEPTH`
- `AI_MCP_DEFAULTS_CONTEXT_INCLUDE_RELATIONSHIPS`

### Impact Analysis Defaults

```yaml
mcp:
  defaults:
    impact:
      max_depth: 2
      include_tests: true
```

| Setting | Default | Description |
|---------|---------|-------------|
| `max_depth` | 2 | Dependency traversal depth |
| `include_tests` | true | Include test coverage |

### Memory Defaults

```yaml
mcp:
  defaults:
    memory:
      default_importance: "medium"
      auto_tag: true
```

| Setting | Default | Description |
|---------|---------|-------------|
| `default_importance` | medium | Default memory importance |
| `auto_tag` | true | Auto-generate tags |

### Events Defaults

```yaml
mcp:
  defaults:
    events:
      retention_days: 7
      max_per_query: 50
```

| Setting | Default | Description |
|---------|---------|-------------|
| `retention_days` | 7 | Event retention period |
| `max_per_query` | 50 | Max events per query |

### Pattern Discovery Defaults

```yaml
mcp:
  defaults:
    patterns:
      max_clusters: 5
      examples_per_cluster: 3
```

| Setting | Default | Description |
|---------|---------|-------------|
| `max_clusters` | 5 | Max pattern clusters |
| `examples_per_cluster` | 3 | Examples per cluster |

### Temporal Analysis Defaults

```yaml
mcp:
  defaults:
    temporal:
      default_time_range_days: 7
```

| Setting | Default | Description |
|---------|---------|-------------|
| `default_time_range_days` | 7 | Default activity time range |

---

## Indexing Configuration

### Schema Mapping

```yaml
indexing:
  schema_mapping:
    enabled: true
    field_mappings:
      line_start: start_line
      line_end: end_line
```

Schema mapping automatically transforms ParserChunk fields to match database schema, preventing field mismatch errors during indexing.

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | true | Enable automatic schema mapping |
| `field_mappings` | {...} | Field name mappings (ParserChunk → database) |

**Environment Variables:**
- `AI_INDEXING_SCHEMA_MAPPING_ENABLED` - Enable/disable schema mapping

**Field Mappings:**

The `field_mappings` dictionary maps ParserChunk field names to database field names:

```yaml
indexing:
  schema_mapping:
    field_mappings:
      line_start: start_line  # ParserChunk.line_start → database.start_line
      line_end: end_line      # ParserChunk.line_end → database.end_line
```

**When to Use:**
- Enable when database schema differs from ParserChunk model
- Required for backward compatibility with existing databases
- Prevents "Field not found" errors during indexing

**Performance Impact:**
- <5ms overhead per chunk
- Negligible for typical file sizes
- Prevents costly database errors

### Schema Validation

```yaml
indexing:
  schema_validation:
    enabled: true
    strict_mode: false
    cache_schemas: true
    cache_ttl_seconds: 300
```

Schema validation performs pre-flight checks before database writes, catching errors early with clear messages.

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | true | Enable schema validation |
| `strict_mode` | false | Fail on extra fields (not just missing) |
| `cache_schemas` | true | Cache schema definitions |
| `cache_ttl_seconds` | 300 | Schema cache TTL |

**Environment Variables:**
- `AI_INDEXING_SCHEMA_VALIDATION_ENABLED` - Enable/disable validation
- `AI_INDEXING_SCHEMA_VALIDATION_STRICT_MODE` - Enable strict mode
- `AI_INDEXING_SCHEMA_VALIDATION_CACHE_SCHEMAS` - Enable schema caching

**Validation Modes:**

- **Lenient** (strict_mode=false): Only checks for missing required fields
- **Strict** (strict_mode=true): Also fails on extra fields not in schema

**Example Error:**

```json
{
  "error": "Schema validation failed for document_chunks",
  "missing_fields": ["start_line"],
  "suggestions": [
    "Enable schema mapping in configuration",
    "Check field_mappings for correct mappings"
  ]
}
```

---

## Context Building Configuration

### Context Builder

```yaml
context:
  builder:
    enabled: true
    fallback_to_search: true
```

The context builder assembles intelligent context from code, documentation, and memories.

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | true | Enable context builder service |
| `fallback_to_search` | true | Fall back to search if builder fails |

**Environment Variables:**
- `AI_CONTEXT_BUILDER_ENABLED` - Enable/disable context builder
- `AI_CONTEXT_BUILDER_FALLBACK_TO_SEARCH` - Enable fallback

**Fallback Strategy:**

When `fallback_to_search` is enabled, the tool automatically falls back to basic search if the context builder returns empty results:

```python
# Even if context builder fails, you get results
context = await build_context(
    session_id=session_id,
    query="authentication"
)
# Fallback ensures non-empty results
```

### Token Budget

```yaml
context:
  token_budget:
    default_budget: 4000
    min_budget: 500
    max_budget: 16000
    focus_allocations:
      code:
        code: 0.70
        documentation: 0.20
        memories: 0.10
      documentation:
        code: 0.20
        documentation: 0.70
        memories: 0.10
      balanced:
        code: 0.40
        documentation: 0.40
        memories: 0.20
```

Token budget management ensures context fits within LLM context windows.

| Setting | Default | Description |
|---------|---------|-------------|
| `default_budget` | 4000 | Default token budget |
| `min_budget` | 500 | Minimum allowed budget |
| `max_budget` | 16000 | Maximum allowed budget |
| `focus_allocations` | {...} | Budget allocation by focus type |

**Environment Variables:**
- `AI_CONTEXT_TOKEN_BUDGET_DEFAULT_BUDGET` - Default budget
- `AI_CONTEXT_TOKEN_BUDGET_MIN_BUDGET` - Minimum budget
- `AI_CONTEXT_TOKEN_BUDGET_MAX_BUDGET` - Maximum budget

**Focus Allocations:**

The `focus_allocations` control how tokens are distributed across content types:

- **code**: 70% code, 20% docs, 10% memories
- **documentation**: 20% code, 70% docs, 10% memories
- **balanced**: 40% code, 40% docs, 20% memories

**Example Usage:**

```python
# Use code focus for implementation tasks
context = await build_context(
    session_id=session_id,
    query="implement authentication",
    focus="code",  # 70% of tokens for code
    max_tokens=8000
)

# Use documentation focus for learning
context = await build_context(
    session_id=session_id,
    query="authentication best practices",
    focus="documentation",  # 70% of tokens for docs
    max_tokens=4000
)
```

**Token Estimation:**

The system estimates token count using approximate character-to-token ratios:
- ~4 characters per token for code
- ~5 characters per token for documentation
- Includes overhead for formatting and metadata

### Depth Limits

```yaml
context:
  depth_limits:
    minimal: 5
    focused: 15
    comprehensive: 30
```

Depth limits control the number of items returned at each depth level.

| Setting | Default | Description |
|---------|---------|-------------|
| `minimal` | 5 | Items for minimal depth |
| `focused` | 15 | Items for focused depth (default) |
| `comprehensive` | 30 | Items for comprehensive depth |

**Environment Variables:**
- `AI_CONTEXT_DEPTH_LIMITS_MINIMAL` - Minimal depth limit
- `AI_CONTEXT_DEPTH_LIMITS_FOCUSED` - Focused depth limit
- `AI_CONTEXT_DEPTH_LIMITS_COMPREHENSIVE` - Comprehensive depth limit

**Depth Levels:**

- **minimal**: Quick overview (5 items)
- **focused**: Balanced detail (15 items) - recommended default
- **comprehensive**: Deep analysis (30 items)

**Example Usage:**

```python
# Quick overview
context = await build_context(
    session_id=session_id,
    query="authentication",
    depth="minimal"  # 5 items
)

# Comprehensive analysis
context = await build_context(
    session_id=session_id,
    query="authentication",
    depth="comprehensive"  # 30 items
)
```

---

## Search Configuration

### Query Sanitization

```yaml
search:
  query_sanitization:
    enabled: true
    escape_special_chars: true
    preserve_wildcards: false
```

Query sanitization escapes special characters to prevent syntax errors in full-text search.

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | true | Enable query sanitization |
| `escape_special_chars` | true | Escape special characters |
| `preserve_wildcards` | false | Preserve * and ? as wildcards |

**Environment Variables:**
- `AI_SEARCH_QUERY_SANITIZATION_ENABLED` - Enable/disable sanitization
- `AI_SEARCH_QUERY_SANITIZATION_ESCAPE_SPECIAL_CHARS` - Escape special chars
- `AI_SEARCH_QUERY_SANITIZATION_PRESERVE_WILDCARDS` - Preserve wildcards

**Special Characters Handled:**

When `escape_special_chars` is enabled, these characters are escaped:
- Question marks (?)
- Asterisks (*)
- Brackets ([], {})
- Parentheses (())
- Backslashes (\\)

**Example Queries:**

```python
# With sanitization enabled, these all work:

# Question marks
results = await search_knowledge(
    session_id=session_id,
    query="how does authentication work?",  # ? is escaped
    limit=5
)

# Asterisks
results = await search_knowledge(
    session_id=session_id,
    query="what is the * operator?",  # * is escaped
    limit=5
)

# Brackets
results = await search_knowledge(
    session_id=session_id,
    query="find [brackets] in code",  # [] are escaped
    limit=5
)
```

**Wildcard Preservation:**

If you want to use wildcards intentionally, enable `preserve_wildcards`:

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
    query="auth*",  # * is treated as wildcard
    limit=5
)
```

**Performance Impact:**

- <1ms overhead per query
- Negligible compared to search time
- Prevents syntax errors that would fail the query

### Search Deduplication

```yaml
search:
  deduplication:
    enabled: true
    max_results_per_file: 1
    min_diversity_ratio: 0.7
```

Search deduplication ensures diverse results across files.

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | true | Enable deduplication |
| `max_results_per_file` | 1 | Max results per file |
| `min_diversity_ratio` | 0.7 | Target diversity ratio (unique files / total results) |

**Environment Variables:**
- `AI_SEARCH_DEDUPLICATION_ENABLED` - Enable/disable deduplication
- `AI_SEARCH_DEDUPLICATION_MAX_RESULTS_PER_FILE` - Max per file
- `AI_SEARCH_DEDUPLICATION_MIN_DIVERSITY_RATIO` - Target diversity

**Quality Metrics:**

- **Duplication rate**: <30% (target)
- **Diversity ratio**: >70% (target)
- **Relevance**: Maintains ranking order

**Example:**

```python
results = await search_knowledge(
    session_id=session_id,
    query="authentication",
    limit=10
)

# Check diversity
print(f"Total results: {len(results['results'])}")
print(f"Unique files: {results['unique_files']}")
print(f"Diversity: {results['diversity_ratio']:.0%}")
```

---

## Security Configuration

```yaml
mcp:
  security:
    path_validation:
      enforce: true  # Always enabled, cannot be disabled
      follow_symlinks: true  # Resolve symlinks during validation
```

### Path Validation

Path validation is always enabled to prevent directory traversal attacks. All file paths are validated before any file operations.

| Setting | Default | Description |
|---------|---------|-------------|
| `enforce` | true | Always true, cannot be disabled |
| `follow_symlinks` | true | Resolve symlinks during validation |

**Environment Variables:**
- `AI_MCP_SECURITY_PATH_VALIDATION_ENFORCE` - Always true
- `AI_MCP_SECURITY_PATH_VALIDATION_FOLLOW_SYMLINKS` - Default: true

**How it works:**
- All file paths are resolved to absolute paths
- Paths must be within allowed project directories
- Symlinks are followed and validated
- Directory traversal attempts (e.g., `../../../etc/passwd`) are blocked

See [Security Guide](./security.md) for comprehensive security documentation.

---

## Behavior Flags

```yaml
mcp:
  behavior:
    suggest_on_empty: true
    include_alternatives: true
    log_all_requests: true
    track_performance: true
    cache_responses: true
    cache_ttl_seconds: 300
```

| Setting | Default | Description |
|---------|---------|-------------|
| `suggest_on_empty` | true | Suggest alternatives for empty results |
| `include_alternatives` | true | Include alternative suggestions |
| `log_all_requests` | true | Log all tool requests |
| `track_performance` | true | Track performance metrics |
| `cache_responses` | true | Enable response caching |
| `cache_ttl_seconds` | 300 | Cache TTL in seconds |

**Environment Variables:**
- `AI_MCP_BEHAVIOR_SUGGEST_ON_EMPTY`
- `AI_MCP_BEHAVIOR_INCLUDE_ALTERNATIVES`
- `AI_MCP_BEHAVIOR_LOG_ALL_REQUESTS`
- `AI_MCP_BEHAVIOR_TRACK_PERFORMANCE`
- `AI_MCP_BEHAVIOR_CACHE_RESPONSES`
- `AI_MCP_BEHAVIOR_CACHE_TTL_SECONDS`

---

## Logging Configuration

```yaml
mcp:
  logging:
    level: "INFO"
    format: "json"
    log_dir: "${HOME}/.AGV/logs"
    max_size_mb: 100
    retention_days: 30
```

| Setting | Default | Description |
|---------|---------|-------------|
| `level` | INFO | Log level (DEBUG/INFO/WARNING/ERROR) |
| `format` | json | Log format (json/text) |
| `log_dir` | ~/.AGV/logs | Log directory |
| `max_size_mb` | 100 | Max log file size |
| `retention_days` | 30 | Log retention period |

**Environment Variables:**
- `AI_MCP_LOGGING_LEVEL`
- `AI_MCP_LOGGING_FORMAT`
- `AI_MCP_LOGGING_LOG_DIR`
- `AI_MCP_LOGGING_MAX_SIZE_MB`
- `AI_MCP_LOGGING_RETENTION_DAYS`

---

## Configuration Examples

### Development Configuration

```yaml
mcp:
  enabled: true
  api:
    host: "localhost"
    port: 8765
    auth:
      enabled: false
  tools:
    cognitive:
      enabled: true
    direct_access:
      enabled: true  # Enable for development
  behavior:
    cache_responses: false  # Disable caching for testing
    log_all_requests: true
  logging:
    level: "DEBUG"

# Indexing configuration
indexing:
  schema_mapping:
    enabled: true
  schema_validation:
    enabled: true
    strict_mode: false  # Lenient for development

# Context building configuration
context:
  builder:
    enabled: true
    fallback_to_search: true
  token_budget:
    default_budget: 4000
  depth_limits:
    focused: 15

# Search configuration
search:
  query_sanitization:
    enabled: true
    escape_special_chars: true
  deduplication:
    enabled: true
```

### Production Configuration

```yaml
mcp:
  enabled: true
  api:
    host: "0.0.0.0"
    port: 8765
    cors:
      enabled: true
      origins:
        - "https://app.example.com"
    auth:
      enabled: true
      api_key: "${MCP_API_KEY}"  # From environment
  tools:
    cognitive:
      enabled: true
    direct_access:
      enabled: false  # Disabled in production
  behavior:
    cache_responses: true
    cache_ttl_seconds: 600
    log_all_requests: true
    track_performance: true
  logging:
    level: "INFO"
    format: "json"
    log_dir: "/var/log/agentic-inquiry"

# Indexing configuration
indexing:
  schema_mapping:
    enabled: true
  schema_validation:
    enabled: true
    strict_mode: true  # Strict in production
    cache_schemas: true

# Context building configuration
context:
  builder:
    enabled: true
    fallback_to_search: true
  token_budget:
    default_budget: 4000
    max_budget: 16000
  depth_limits:
    focused: 15
    comprehensive: 30

# Search configuration
search:
  query_sanitization:
    enabled: true
    escape_special_chars: true
    preserve_wildcards: false
  deduplication:
    enabled: true
    max_results_per_file: 1
    min_diversity_ratio: 0.7
```

### High-Performance Configuration

```yaml
mcp:
  defaults:
    search:
      limit: 10  # Reduce default limit
    context:
      max_tokens: 2000  # Reduce token budget
  behavior:
    cache_responses: true
    cache_ttl_seconds: 900  # Longer cache
  logging:
    level: "WARNING"  # Less logging
```

---

## Environment Variable Reference

Complete list of environment variables:

```bash
# Server
AI_MCP_ENABLED=true
AI_MCP_SERVER_NAME="Agentic Inquiry"
AI_MCP_SERVER_VERSION="1.0.0"

# API
AI_MCP_API_ENABLED=true
AI_MCP_API_HOST=localhost
AI_MCP_API_PORT=8765
AI_MCP_API_CORS_ENABLED=true
AI_MCP_API_CORS_ORIGINS="*"
AI_MCP_API_AUTH_ENABLED=false
AI_MCP_API_AUTH_API_KEY=""

# Tools
AI_MCP_TOOLS_COGNITIVE_ENABLED=true
AI_MCP_TOOLS_DIRECT_ACCESS_ENABLED=false

# Defaults
AI_MCP_DEFAULTS_SEARCH_LIMIT=20
AI_MCP_DEFAULTS_SEARCH_HYBRID_WEIGHT=0.7
AI_MCP_DEFAULTS_CONTEXT_MAX_TOKENS=4000
AI_MCP_DEFAULTS_CONTEXT_DEPTH=broad
AI_MCP_DEFAULTS_IMPACT_MAX_DEPTH=2

# Behavior
AI_MCP_BEHAVIOR_SUGGEST_ON_EMPTY=true
AI_MCP_BEHAVIOR_CACHE_RESPONSES=true
AI_MCP_BEHAVIOR_CACHE_TTL_SECONDS=300
AI_MCP_BEHAVIOR_TRACK_PERFORMANCE=true

# Logging
AI_MCP_LOGGING_LEVEL=INFO
AI_MCP_LOGGING_FORMAT=json
AI_MCP_LOGGING_LOG_DIR="${HOME}/.AGV/logs"
```

---

## Configuration Validation

Validate configuration before starting:

```bash
# Validate configuration file
uv run python -c "
from agentic_inquiry.config import Config
config = Config.load('config/mcp.yaml')
print('Configuration valid!')
print(f'MCP enabled: {config.mcp.enabled}')
print(f'API port: {config.mcp.api.port}')
"
```

---

## Next Steps

- Review [Tool Reference](./tools/README.md) for tool-specific configuration
- Check [Deployment Guide](./deployment.md) for production setup
- Explore [Workflows](./workflows/README.md) for usage examples
