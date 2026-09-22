# MCP Server Security Guide

> Historical reference. This page describes PostgreSQL-family providers, cloud connectors or remote embedders that are not part of this local-only distribution. It is retained as design input for the external provider contract in [storage-backends.md](../storage-backends.md).

## Overview

The Agentic Inquiry MCP Server implements multiple security layers to protect against common vulnerabilities and ensure safe operation in production environments. This guide documents security features, best practices, and configuration options.

## Security Features

### Path Validation

All file path parameters are validated to prevent directory traversal attacks.

#### How It Works

The server uses `validate_file_path()` to ensure that all file paths:
- Stay within allowed project directories
- Cannot access files outside the project scope
- Are resolved to absolute paths with symlinks followed
- Optionally verify file existence

#### Implementation

```python
from agentic_inquiry.mcp.utils.validation import validate_file_path, PathValidationError
from pathlib import Path

# Validate a file path
try:
    validated_path = validate_file_path(
        path="src/main.py",
        allowed_base=Path("/project"),
        must_exist=True
    )
    # Safe to use validated_path
except PathValidationError as e:
    # Handle invalid path
    print(f"Invalid path: {e}")
```

#### Protected Operations

The following tools validate all file paths:

- **add_knowledge**: Validates `source` parameter when `content_type` is "file" or "directory"
- **index_files**: Validates all paths in `file_paths` array
- Any tool accepting file or directory paths

#### Attack Prevention

**Directory Traversal Attempts:**

```python
# ❌ BLOCKED: Attempts to access parent directories
validate_file_path("../../../etc/passwd", Path("/project"))
# Raises: PathValidationError: Path outside allowed directory

# ❌ BLOCKED: Absolute paths outside project
validate_file_path("/etc/passwd", Path("/project"))
# Raises: PathValidationError: Path outside allowed directory

# ❌ BLOCKED: Symlink escape attempts
validate_file_path("link_to_etc", Path("/project"))
# Raises: PathValidationError if symlink points outside project

# ✅ ALLOWED: Valid paths within project
validate_file_path("src/main.py", Path("/project"))
# Returns: Path("/project/src/main.py")
```

#### Configuration

Path validation is always enabled and cannot be disabled. Configure allowed base directories per project:

```yaml
mcp:
  security:
    path_validation:
      enforce: true  # Always true, cannot be disabled
      follow_symlinks: true  # Resolve symlinks during validation
```

**Environment Variables:**
- `INQUIRY_MCP_SECURITY_PATH_VALIDATION_ENFORCE` - Always true
- `INQUIRY_MCP_SECURITY_PATH_VALIDATION_FOLLOW_SYMLINKS` - Default: true

---

### API Authentication

Optional API key authentication for HTTP endpoints.

#### Enabling Authentication

**Configuration:**

```yaml
mcp:
  api:
    auth:
      enabled: true
      api_key: "${MCP_API_KEY}"  # Load from environment
```

**Environment Variables:**

```bash
export INQUIRY_MCP_API_AUTH_ENABLED=true
export INQUIRY_MCP_API_AUTH_API_KEY="your-secure-api-key"
```

#### Generating API Keys

Generate cryptographically secure API keys:

```bash
# Generate a secure API key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Key Requirements:**
- Minimum 32 characters
- Use cryptographically secure random generation
- Store securely (environment variables, secrets manager)
- Rotate regularly (recommended: every 90 days)

#### Using API Keys

**HTTP Requests:**

```bash
# Include API key in X-API-Key header
curl -H "X-API-Key: your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"query": "authentication"}' \
     http://localhost:8765/api/search
```

**Python Client:**

```python
import httpx

headers = {
    "X-API-Key": "your-api-key",
    "Content-Type": "application/json"
}

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8765/api/search",
        headers=headers,
        json={"query": "authentication"}
    )
```

#### Timing Attack Protection

API key comparison uses constant-time algorithms to prevent timing attacks:

```python
import secrets

# ✅ SECURE: Constant-time comparison
if secrets.compare_digest(provided_key, expected_key):
    return True

# ❌ INSECURE: Direct comparison leaks timing information
if provided_key == expected_key:  # DON'T DO THIS
    return True
```

**Why This Matters:**

Direct string comparison (`==`) returns as soon as characters differ, allowing attackers to guess keys character-by-character by measuring response times. The `secrets.compare_digest()` function ensures comparison time is constant regardless of where strings differ.

#### Authentication Errors

**Missing API Key:**

```json
{
  "error": {
    "code": "AUTHENTICATION_REQUIRED",
    "message": "API key required",
    "help": "Include X-API-Key header with valid API key"
  }
}
```

**Invalid API Key:**

```json
{
  "error": {
    "code": "INVALID_API_KEY",
    "message": "Invalid API key",
    "help": "Check API key is correct and not expired"
  }
}
```

---

### Input Validation

All tool parameters are validated using Pydantic models.

#### Validation Features

- **Type Checking**: Ensures parameters match expected types
- **Range Validation**: Enforces min/max values for numeric parameters
- **Length Validation**: Enforces string length limits
- **Format Validation**: Validates formats (UUIDs, dates, etc.)
- **Enum Validation**: Restricts values to allowed options

#### Example Validations

**String Length:**

```python
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    # ❌ Rejected: query=""
    # ❌ Rejected: query="a"
    # ✅ Accepted: query="authentication"
```

**Numeric Ranges:**

```python
class SearchRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    # ❌ Rejected: limit=0
    # ❌ Rejected: limit=101
    # ✅ Accepted: limit=20
```

**Enum Values:**

```python
class ContextRequest(BaseModel):
    depth: str = Field(default="broad", pattern="^(focused|broad|comprehensive)$")
    # ❌ Rejected: depth="invalid"
    # ✅ Accepted: depth="broad"
```

#### Validation Errors

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid parameters",
    "details": {
      "query": ["String too short (minimum 2 characters)"],
      "limit": ["Value must be between 1 and 100"]
    }
  }
}
```

---

### Session Isolation

Sessions are scoped to projects to prevent cross-project data access.

#### How It Works

- Each session is tied to a specific `project_id`
- All queries automatically filter by `project_id`
- Sessions cannot access data from other projects
- Session IDs are UUIDs (cryptographically random)

#### Example

```python
# Create session for project A
session_a = await create_session(project_id="project-a")

# Create session for project B
session_b = await create_session(project_id="project-b")

# Search in session A only returns project A data
results_a = await search_knowledge(
    session_id=session_a["session_id"],
    query="authentication"
)
# Results only include data from project-a

# Search in session B only returns project B data
results_b = await search_knowledge(
    session_id=session_b["session_id"],
    query="authentication"
)
# Results only include data from project-b
```

#### Session Validation

All tools requiring a session validate:
- Session exists and is not expired
- Session belongs to the correct project
- Session is in active state

**Session Not Found:**

```json
{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Session 'abc-123' not found or expired",
    "help": "Create a new session with 'create_session'",
    "suggestions": [
      "Create a new session",
      "Check if session ID is correct",
      "Verify session has not expired"
    ]
  }
}
```

---

### Rate Limiting

Optional rate limiting for API endpoints (production deployments).

#### Configuration

```yaml
mcp:
  api:
    rate_limiting:
      enabled: true
      requests_per_minute: 60
      burst_size: 10
```

**Environment Variables:**
- `INQUIRY_MCP_API_RATE_LIMITING_ENABLED` - Enable rate limiting
- `INQUIRY_MCP_API_RATE_LIMITING_REQUESTS_PER_MINUTE` - Rate limit
- `INQUIRY_MCP_API_RATE_LIMITING_BURST_SIZE` - Burst allowance

#### Rate Limit Headers

Responses include rate limit information:

```http
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1642345678
```

#### Rate Limit Exceeded

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded",
    "help": "Wait 30 seconds before retrying",
    "retry_after": 30
  }
}
```

---

### CORS Configuration

Cross-Origin Resource Sharing (CORS) configuration for web clients.

#### Development Configuration

```yaml
mcp:
  api:
    cors:
      enabled: true
      origins: ["*"]  # Allow all origins (development only)
```

#### Production Configuration

```yaml
mcp:
  api:
    cors:
      enabled: true
      origins:
        - "https://app.example.com"
        - "https://staging.example.com"
      allow_credentials: true
      max_age: 3600
```

**Environment Variables:**
- `INQUIRY_MCP_API_CORS_ENABLED` - Enable CORS
- `INQUIRY_MCP_API_CORS_ORIGINS` - Comma-separated allowed origins
- `INQUIRY_MCP_API_CORS_ALLOW_CREDENTIALS` - Allow credentials
- `INQUIRY_MCP_API_CORS_MAX_AGE` - Preflight cache duration

#### CORS Headers

```http
Access-Control-Allow-Origin: https://app.example.com
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type, X-API-Key
Access-Control-Max-Age: 3600
```

---

## Security Best Practices

### Production Deployment

**Required Security Measures:**

1. **Enable API Authentication**
   ```yaml
   mcp:
     api:
       auth:
         enabled: true
         api_key: "${MCP_API_KEY}"
   ```

2. **Restrict CORS Origins**
   ```yaml
   mcp:
     api:
       cors:
         origins:
           - "https://your-app.com"
   ```

3. **Enable Rate Limiting**
   ```yaml
   mcp:
     api:
       rate_limiting:
         enabled: true
         requests_per_minute: 60
   ```

4. **Use HTTPS**
   - Deploy behind reverse proxy (nginx, Caddy)
   - Terminate TLS at proxy level
   - Redirect HTTP to HTTPS

5. **Secure API Keys**
   - Store in environment variables or secrets manager
   - Never commit to version control
   - Rotate regularly (every 90 days)
   - Use different keys per environment

### API Key Management

**Generation:**

```bash
# Generate secure API key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Storage:**

```bash
# Environment variable (recommended)
export MCP_API_KEY="your-secure-key"

# Secrets manager (production)
aws secretsmanager get-secret-value --secret-id mcp-api-key
```

**Rotation:**

1. Generate new API key
2. Update configuration with new key
3. Restart MCP server
4. Update all clients with new key
5. Revoke old key after grace period

### Network Security

**Firewall Rules:**

```bash
# Allow only specific IPs
iptables -A INPUT -p tcp --dport 8765 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 8765 -j DROP
```

**Reverse Proxy (nginx):**

```nginx
server {
    listen 443 ssl http2;
    server_name mcp.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Logging and Monitoring

**Security Event Logging:**

```yaml
mcp:
  logging:
    level: "INFO"
    format: "json"
    security_events: true
```

**Monitor for:**
- Failed authentication attempts
- Path validation failures
- Rate limit violations
- Unusual access patterns
- Error spikes

**Example Log Entry:**

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "WARNING",
  "event": "authentication_failed",
  "ip": "192.168.1.100",
  "details": {
    "reason": "invalid_api_key",
    "endpoint": "/api/search"
  }
}
```

### Input Sanitization

**Always Validate:**
- File paths (use `validate_file_path()`)
- User queries (length, content)
- Filter parameters (type, values)
- Session IDs (format, existence)

**Never Trust:**
- User-provided file paths
- Query parameters from URLs
- Request headers (except authentication)
- Client-side validation

### Secure Configuration

**Configuration File Permissions:**

```bash
# Restrict access to configuration files
chmod 600 config/mcp.yaml
chown mcp-user:mcp-group config/mcp.yaml
```

**Environment Variables:**

```bash
# Use environment variables for secrets
export MCP_API_KEY="$(cat /secure/path/api-key)"
export INQUIRY_STORAGE_URI="$(cat /secure/path/db-uri)"
```

**Secrets Management:**

```python
# Load secrets from secure storage
import boto3

def load_api_key():
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId='mcp-api-key')
    return response['SecretString']
```

---

## Security Checklist

### Pre-Deployment

- [ ] API authentication enabled
- [ ] Strong API keys generated and stored securely
- [ ] CORS origins restricted to known domains
- [ ] Rate limiting configured
- [ ] HTTPS/TLS configured
- [ ] Firewall rules in place
- [ ] Security logging enabled
- [ ] Configuration files have restricted permissions
- [ ] Secrets stored in secure location (not in code)
- [ ] All dependencies updated to latest secure versions

### Post-Deployment

- [ ] Monitor authentication failures
- [ ] Review security logs regularly
- [ ] Test path validation with attack vectors
- [ ] Verify rate limiting works
- [ ] Check CORS configuration
- [ ] Audit API key usage
- [ ] Review access patterns
- [ ] Update dependencies regularly

### Ongoing Maintenance

- [ ] Rotate API keys every 90 days
- [ ] Review and update firewall rules
- [ ] Monitor for security advisories
- [ ] Update dependencies promptly
- [ ] Review security logs weekly
- [ ] Test security controls quarterly
- [ ] Conduct security audits annually

---

## Vulnerability Reporting

If you discover a security vulnerability:

1. **Do NOT** open a public GitHub issue
2. Email security@example.com with details
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)
4. Allow 90 days for response and fix
5. Coordinate disclosure timing

---

## Security Updates

Subscribe to security updates:

- GitHub Security Advisories
- Release notes for security patches
- Security mailing list (security-announce@example.com)

---

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE Top 25](https://cwe.mitre.org/top25/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)

---

## Next Steps

- Review [Configuration Guide](./configuration.md) for security settings
- Check [Deployment Guide](./deployment.md) for production setup
- Explore [Tool Reference](./tools/README.md) for tool-specific security
