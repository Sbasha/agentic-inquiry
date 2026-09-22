# Security Best Practices

This document outlines security best practices for developing with and extending Agent-Vault, focusing on injection prevention, path validation, and secure coding patterns.

## Filter Construction Security

### The Problem: SQL Injection Vulnerabilities

When constructing database filter expressions using string formatting, there's a risk of injection attacks:

```python
# ❌ DANGEROUS: Direct string formatting
doc_id = user_input  # Could be: "'; DROP TABLE documents; --"
filter_expr = f"doc_id = '{doc_id}'"
# Result: doc_id = ''; DROP TABLE documents; --'
```

This vulnerability allows malicious input to:
- Access unauthorized data
- Modify or delete records
- Execute arbitrary database commands
- Bypass security constraints

### The Solution: Filter AST

Agent-Vault provides a **Filter AST** (`agent_vault.database.filters`) for injection-safe filter construction:

```python
# ✅ SAFE: Using Filter AST
from agent_vault.database.filters import eq

filter_ast = eq("doc_id", user_input)  # Type-validated, auto-escaped at translation time
# Translates to: doc_id = 'escaped_value' (safe)
```

### How Filter AST Prevents Injection

**1. Field Name Validation**

Field names are validated at construction time against the pattern:

```
^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$
```

This allows simple fields (`status`, `project_id`) and nested fields (`metadata.type`) but rejects:
- Spaces: `"my field"`
- Quotes: `"field'name"`
- Brackets: `"field[0]"`
- SQL operators: `"field > 5"`
- Injection attempts: `"field; DROP TABLE"`

**2. Type Validation**

Only safe types are permitted: `str`, `int`, `float`, `bool`, `None`, and lists of these types.

```python
from agent_vault.database.filters import eq, is_in

eq("score", 0.5)              # Valid
eq("language", "python")      # Valid
is_in("type", ["a", "b"])     # Valid
eq("data", {"key": "value"})  # Raises ValueError: unsupported type
```

**3. Backend Translation with Escaping**

Backend adapters translate the AST to native queries with proper escaping:

```python
from agent_vault.database.filters import eq

# Input with single quotes
filter_ast = eq("name", "O'Brien")
# LanceDB translator output: name = 'O''Brien' (escaped)
```

**4. Explicit NULL Handling**

NULL comparisons must use dedicated operators:

```python
from agent_vault.database.filters import is_null, is_not_null

is_null("deleted_at")         # Valid: deleted_at IS NULL
is_not_null("project_id")     # Valid: project_id IS NOT NULL
eq("field", None)             # Raises ValueError: use is_null() instead
```

### Filter AST API

#### Builder Functions

Use these functions instead of constructing Filter directly:

```python
from agent_vault.database.filters import (
    eq, ne, gt, gte, lt, lte,  # Comparison
    is_in, not_in,             # Set membership
    is_null, is_not_null,      # NULL checks
    and_, or_,                 # Compound
)

# Simple comparisons
eq("status", "active")         # status = 'active'
gt("score", 0.5)               # score > 0.5
is_in("type", ["a", "b"])      # type IN ('a', 'b')

# NULL checks
is_null("deleted_at")          # deleted_at IS NULL
is_not_null("project_id")      # project_id IS NOT NULL

# Compound filters
and_(
    eq("status", "active"),
    gt("score", 0.5)
)  # (status = 'active') AND (score > 0.5)
```

#### Empty List Behavior

Empty lists have defined semantics:

```python
from agent_vault.database.filters import is_in, not_in

is_in("type", [])      # Evaluates to FALSE (no matches)
not_in("type", [])     # Evaluates to TRUE (no restrictions)
```

#### Combining Filters

```python
from agent_vault.database.filters import and_, or_, eq, gt, is_in

# AND: all conditions must match
filter_ast = and_(
    eq("language", "python"),
    gt("line_count", 100),
    is_in("status", ["active", "pending"])
)

# OR: any condition matches
filter_ast = or_(
    eq("type", "code"),
    eq("type", "documentation")
)

# Nested compound filters
filter_ast = and_(
    eq("project_id", "my_project"),
    or_(
        eq("language", "python"),
        eq("language", "javascript")
    )
)
```

### Integration with Search

Filter AST integrates with storage providers:

```python
from agent_vault.search import SearchService
from agent_vault.database.filters import and_, eq, gt

# Create filter
filter_ast = and_(
    eq("project_id", "my_project"),
    gt("score", 0.5)
)

# Use in search
search = SearchService(config=config)
results = await search.hybrid_search(
    query_vector=embedding,
    query_fts="authentication",
    limit=10,
    filters=filter_ast
)
```

### Migration from String Formatting

**Before (unsafe):**
```python
# ❌ DANGEROUS
project_id = user_input
filter_expr = f"project_id = '{project_id}' AND score > 0.5"
```

**After (safe):**
```python
# ✅ SAFE
from agent_vault.database.filters import and_, eq, gt

filter_ast = and_(
    eq("project_id", user_input),  # Validated and escaped
    gt("score", 0.5)
)
```

### Error Handling

Filter AST provides clear validation errors:

```python
from agent_vault.database.filters import eq, is_in

try:
    eq("field; DROP TABLE", "value")  # Invalid field name
except ValueError as e:
    print(e)  # Field name validation failed

try:
    eq("status", {"nested": "dict"})  # Unsupported type
except ValueError as e:
    print(e)  # Value must be str, int, float, bool, or None
```

## Path Validation Security

### The Problem: Directory Traversal

Path traversal attacks attempt to access files outside the intended directory:

```python
# ❌ DANGEROUS: No validation
file_path = user_input  # Could be: "../../etc/passwd"
content = open(file_path).read()
```

### The Solution: validate_file_path

Use the built-in path validation utility:

```python
# ✅ SAFE: Path validation
from agent_vault.mcp.utils.validation import validate_file_path

try:
    validated_path = validate_file_path(user_input, project_root)
    content = open(validated_path).read()
except ValueError as e:
    print(f"Invalid path: {e}")
```

### How Path Validation Works

**1. Absolute Path Resolution**

Resolves paths to absolute form:

```python
validate_file_path("./src/main.py", "/project")
# Returns: /project/src/main.py
```

**2. Symlink Resolution**

Resolves symlinks to prevent traversal:

```python
# If /project/link -> /etc/passwd
validate_file_path("link", "/project")
# Raises: ValueError (outside project root)
```

**3. Containment Verification**

Ensures path is within project root:

```python
validate_file_path("../../etc/passwd", "/project")
# Raises: ValueError (outside project root)
```

**4. Existence Check**

Verifies file exists:

```python
validate_file_path("nonexistent.py", "/project")
# Raises: ValueError (file does not exist)
```

## API Key Security

### Timing Attack Prevention

When comparing API keys or secrets, use constant-time comparison:

```python
# ❌ VULNERABLE: Timing attack possible
if provided_key == expected_key:
    grant_access()

# ✅ SAFE: Constant-time comparison
import secrets
if secrets.compare_digest(provided_key, expected_key):
    grant_access()
```

### Why This Matters

Regular string comparison (`==`) can leak information through timing:
- Comparison stops at first mismatch
- Attacker can measure response time
- Gradually discover correct key character by character

`secrets.compare_digest()` always compares all characters, preventing timing attacks.

## Environment Variable Security

### Sensitive Configuration

Never commit sensitive values to version control:

```yaml
# ❌ BAD: Hardcoded secrets in config
embeddings:
  api_key: "sk-1234567890abcdef"  # Don't do this!
```

Use environment variables instead:

```bash
# ✅ GOOD: Environment variables
export AGV_EMBEDDINGS_API_KEY="sk-1234567890abcdef"
```

```yaml
# Config references environment variable
embeddings:
  api_key: ${AGV_EMBEDDINGS_API_KEY}
```

### .gitignore Configuration

Ensure sensitive files are gitignored:

```gitignore
# Agent-Vault
agent-vault.yaml
.env
.agv/

# API keys and secrets
*.key
*.pem
secrets/
```

## Dependency Security

### Regular Updates

Keep dependencies updated to patch security vulnerabilities:

```bash
# Check for outdated packages
uv pip list --outdated

# Update dependencies
uv sync --upgrade
```

### Vulnerability Scanning

Use security scanning tools:

```bash
# Scan for known vulnerabilities
pip-audit

# Or use safety
safety check
```

## Logging Security

### Avoid Logging Sensitive Data

Never log sensitive information:

```python
# ❌ BAD: Logging sensitive data
logger.info("User API key: %s", api_key)
logger.debug("Database password: %s", db_password)

# ✅ GOOD: Log without sensitive data
logger.info("User authenticated successfully")
logger.debug("Database connection established")
```

### Sanitize User Input in Logs

Sanitize user input before logging:

```python
# ❌ BAD: Logging unsanitized input
logger.info("Processing file: %s", user_provided_path)

# ✅ GOOD: Sanitize before logging
safe_path = os.path.basename(user_provided_path)
logger.info("Processing file: %s", safe_path)
```

## Security Checklist

When developing with Agent-Vault:

- [ ] Use **Filter AST** (`agent_vault.database.filters`) for all database filter construction
- [ ] Use `validate_file_path()` for all file path operations
- [ ] Use `secrets.compare_digest()` for API key comparison
- [ ] Store sensitive configuration in environment variables
- [ ] Never commit secrets to version control
- [ ] Keep dependencies updated
- [ ] Scan for vulnerabilities regularly
- [ ] Avoid logging sensitive data
- [ ] Sanitize user input before logging
- [ ] Validate all user input
- [ ] Use type hints and validation (Pydantic)
- [ ] Write security-focused tests

## Reporting Security Issues

If you discover a security vulnerability in Agent-Vault:

1. **Do not** open a public GitHub issue
2. Email security concerns to the maintainers
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We take security seriously and will respond promptly to all reports.

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [Pydantic Security](https://docs.pydantic.dev/latest/concepts/security/)
- [LanceDB Security](https://lancedb.github.io/lancedb/)
