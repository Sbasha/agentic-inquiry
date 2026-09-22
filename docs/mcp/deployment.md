# MCP Server Deployment Guide

> **Note:** The MCP server is a secondary interface. Most users should use the [Claude Code plugins](../../README.md) instead.

This guide covers deploying the Agent-Vault MCP Server for advanced use cases requiring direct MCP access.

## Primary Interface: Claude Code Plugins

**Most users should enable the Claude Code plugins instead of running the MCP server directly.**

### Enable Plugins

Add to `.claude/settings.json` in your project:

```json
{
  "extraKnownMarketplaces": {
    "agent-vault": {
      "source": {
        "source": "directory",
        "path": "./extensions/claude"
      }
    }
  },
  "enabledPlugins": {
    "agv@agent-vault": true,
    "agv-dev@agent-vault": true
  }
}
```

### Use Plugin Skills

Once enabled, use skills directly in Claude Code:

- `/agv:search <query>` - Semantic search
- `/agv:index <path>` - Index codebase
- `/agv:onboard <path>` - Codebase onboarding
- `/agv:status` - Show project state

**Full plugin reference:** [AGENTS.md](../../AGENTS.md)

### When to Deploy the MCP Server

Only deploy the MCP server as a standalone service when you need:

- **External tool integration** - Connect non-Claude clients to Agent-Vault
- **Production HTTP API** - Deploy as a service for multiple remote clients
- **Custom MCP workflows** - Build specialized MCP-based tooling
- **Non-Claude MCP clients** - Use Agent-Vault from other MCP-compatible agents

For local development and Claude Code integration, the plugin system handles everything automatically (no deployment needed).

## Table of Contents

- [Prerequisites](#prerequisites)
- [Local Development](#local-development)
- [Docker Deployment](#docker-deployment)
- [Configuration](#configuration)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Security](#security)

---

## Prerequisites

### System Requirements

- Python 3.10–3.13
- 4GB RAM minimum (8GB recommended)
- 10GB disk space for vector database
- Linux, macOS, or Windows with WSL2

### Dependencies

```bash
# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
git clone https://github.com/sbasha/agent-vault.git
cd agent-vault

# Install dependencies
uv sync
```

---

## Local Development

### Quick Start (MCP Server)

```bash
# Start MCP server with default configuration
uv run python -m agent_vault.mcp.cli

# Server will start on localhost:8765
# Cognitive tools enabled by default
# Direct access tools disabled by default
```

**Note:** Most users should use the Claude Code plugins instead, which provide the same functionality without manual server management.

### Custom Configuration

```bash
# Create custom configuration
cp config/mcp.yaml config/mcp.local.yaml

# Edit configuration
vim config/mcp.local.yaml

# Start with custom config
uv run python -m agent_vault.mcp.cli --config config/mcp.local.yaml
```

### Enable Direct Access Tools

```bash
# Enable direct access tools via CLI
uv run python -m agent_vault.mcp.cli --enable-direct-tools

# Or via configuration file
# Edit config/mcp.yaml:
# mcp:
#   tools:
#     direct_access:
#       enabled: true
```

### Set Default Project

```bash
# Set default project ID
uv run python -m agent_vault.mcp.cli --project-id my_project

# Or via environment variable
export AGV_DEFAULT_PROJECT=my_project
uv run python -m agent_vault.mcp.cli
```

---

## Docker Deployment

### Build Docker Image

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY . .

# Create data directory
RUN mkdir -p /data/vector_db

# Expose MCP API port
EXPOSE 8765

# Health check (requires HTTP transport)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8765/health')"

# Run MCP server with HTTP transport for health checks
CMD ["uv", "run", "python", "-m", "agent_vault.mcp.cli", "--transport", "http", "--host", "0.0.0.0"]
```

### Build and Run

```bash
# Build image
docker build -t agent-vault-mcp:latest .

# Run container
docker run -d \
  --name agent-vault-mcp \
  -p 8765:8765 \
  -v $(pwd)/vector_db:/data/vector_db \
  -v $(pwd)/config:/app/config \
  -e AGV_DEFAULT_PROJECT=my_project \
  agent-vault-mcp:latest

# Check logs
docker logs -f agent-vault-mcp

# Check health
curl http://localhost:8765/health
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  mcp-server:
    build: .
    image: agent-vault-mcp:latest
    container_name: agent-vault-mcp
    ports:
      - "8765:8765"
    volumes:
      - ./vector_db:/data/vector_db
      - ./config:/app/config
      - ./logs:/app/logs
    environment:
      - AGV_DEFAULT_PROJECT=my_project
      - AGV_MCP_ENABLED=true
      - AGV_MCP_API_HOST=0.0.0.0
      - AGV_MCP_API_PORT=8765
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:8765/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

---

## Configuration

### Configuration File

The MCP server uses `config/mcp.yaml` for configuration:

```yaml
mcp:
  enabled: true

  # Server settings
  server:
    name: "Agent-Vault"
    version: "1.0.0"
    description: "AI-powered code and knowledge search"

  # Tool configuration
  tools:
    cognitive:
      enabled: true
    direct_access:
      enabled: false  # OFF by default

  # API configuration
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

  # Default behavior
  defaults:
    search:
      limit: 20
      hybrid_weight: 0.7
      min_relevance: 0.3
    context:
      max_tokens: 4000
      depth: "broad"
    impact:
      max_depth: 2
      include_tests: true

  # Behavior flags
  behavior:
    suggest_on_empty: true
    include_alternatives: true
    log_all_requests: true
    track_performance: true
    cache_responses: true
    cache_ttl_seconds: 300

  # Logging
  logging:
    level: "INFO"
    format: "json"
    log_dir: "${HOME}/.AGV/logs"
    max_size_mb: 100
    retention_days: 30
```

### Environment Variables

Override configuration with environment variables:

```bash
# Server settings
export AGV_MCP_ENABLED=true
export AGV_MCP_SERVER_NAME="My MCP Server"

# API settings
export AGV_MCP_API_HOST=0.0.0.0
export AGV_MCP_API_PORT=8765
export AGV_MCP_API_AUTH_ENABLED=true
export AGV_MCP_API_AUTH_API_KEY=your-secret-key

# Tool settings
export AGV_MCP_TOOLS_DIRECT_ACCESS_ENABLED=true

# Behavior settings
export AGV_MCP_BEHAVIOR_CACHE_RESPONSES=true
export AGV_MCP_BEHAVIOR_CACHE_TTL_SECONDS=600

# Logging
export AGV_MCP_LOGGING_LEVEL=DEBUG
export AGV_MCP_LOGGING_LOG_DIR=/var/log/AGV
```

### Storage Configuration

Configure vector database storage:

```yaml
# In config/agent-vault.yaml
storage:
  uri: "vector_db"  # Local directory
  # Or remote LanceDB
  # uri: "s3://my-bucket/vector_db"
  # uri: "gs://my-bucket/vector_db"
```

---

## Monitoring (MCP Server)

### Health Checks

**Note:** Health check endpoints are only available when running the MCP server with HTTP transport (`--transport http`).

When running the MCP server with HTTP transport:

```bash
# Check server health
curl http://localhost:8765/health

# Response:
# {
#   "status": "healthy",
#   "version": "1.0.0",
#   "uptime_seconds": 3600,
#   "active_sessions": 5
# }
```

**Not available with STDIO transport** (the default for local plugin usage).

### Metrics Endpoint

**Note:** Metrics endpoints are only available when running the MCP server with HTTP transport.

```bash
# Get server metrics (HTTP mode only)
curl http://localhost:8765/metrics

# Response:
# {
#   "requests_total": 1234,
#   "requests_per_minute": 20.5,
#   "average_response_time_ms": 450,
#   "cache_hit_rate": 0.42,
#   "active_sessions": 5,
#   "tool_usage": {
#     "search_knowledge": 500,
#     "build_context": 300,
#     "understand_entity": 200
#   }
# }
```

### Logging

```bash
# View logs
tail -f logs/mcp-server.log

# JSON format logs
cat logs/mcp-server.log | jq '.level, .message'

# Filter by level
cat logs/mcp-server.log | jq 'select(.level == "ERROR")'

# Filter by session
cat logs/mcp-server.log | jq 'select(.session_id == "abc-123")'
```

### Performance Monitoring

```python
# Enable performance tracking in config
mcp:
  behavior:
    track_performance: true

# Access performance data
curl http://localhost:8765/api/performance

# Response includes:
# - Response time percentiles (p50, p95, p99)
# - Tool execution times
# - Cache performance
# - Database query times
```

---


## Troubleshooting MCP Server

### Common MCP Server Issues

#### Server Won't Start

**Symptom**: MCP server fails to start or crashes immediately

**Solutions**:

```bash
# Check Python version
python --version  # Should be 3.10–3.13

# Check dependencies
uv sync

# Check configuration
uv run python -c "from agent_vault.config import Config; Config.load()"

# Check port availability
lsof -i :8765  # On macOS/Linux
netstat -ano | findstr :8765  # On Windows

# Start with debug logging
export AGV_MCP_LOGGING_LEVEL=DEBUG
uv run python -m agent_vault.mcp.cli
```

#### Project Not Indexed

**Symptom**: Session status is "empty" or searches return no results

**Note:** This applies to both MCP server and CLI/plugin usage.

**Solutions**:

```python
# Check if project is indexed
session = await create_session(project_id="my_project")
print(session["status"])  # Should be "ready"

# If empty, index the project
result = await add_knowledge(
    session_id=session["session_id"],
    content_type="directory",
    source=".",
    watch=True
)

# Monitor indexing progress
events = await get_events(
    session_id=session["session_id"],
    event_types=["indexing"]
)
```

#### Slow Search Performance

**Symptom**: Searches take >5 seconds

**Solutions**:

```yaml
# Enable caching in config
mcp:
  behavior:
    cache_responses: true
    cache_ttl_seconds: 300

# Reduce search limit
mcp:
  defaults:
    search:
      limit: 10  # Instead of 20

# Use preview mode
results = await search_knowledge(
    session_id=session_id,
    query="...",
    preview=True  # Get summaries only
)
```

#### High Memory Usage

**Symptom**: Server uses excessive memory

**Solutions**:

```yaml
# Reduce cache size
mcp:
  behavior:
    cache_ttl_seconds: 60  # Shorter TTL

# Limit concurrent sessions
# In code, implement session cleanup:
# - Close expired sessions
# - Limit max concurrent sessions to 50

# Reduce context token limits
mcp:
  defaults:
    context:
      max_tokens: 2000  # Instead of 4000
```

#### Session Not Found Errors

**Symptom**: "SESSION_NOT_FOUND" errors

**Solutions**:

```python
# Check session expiry
session = await get_session(session_id="...")

# Resume expired session
session = await resume_session(session_id="...")

# Create new session if needed
session = await create_session(project_id="my_project")
```

#### Database Errors

**Symptom**: LanceDB errors or corruption

**Solutions**:

```bash
# Check database directory
ls -la vector_db/

# Backup database
cp -r vector_db/ vector_db.backup/

# Rebuild index if corrupted
rm -rf vector_db/
# Then reindex project

# Check disk space
df -h

# Check permissions
chmod -R 755 vector_db/
```

### Debug Mode

Enable debug mode for detailed logging:

```bash
# Via environment variable
export AGV_MCP_LOGGING_LEVEL=DEBUG
uv run python -m agent_vault.mcp.cli

# Via configuration
# Edit config/mcp.yaml:
mcp:
  logging:
    level: "DEBUG"
```

### Log Analysis

```bash
# Find errors
grep ERROR logs/mcp-server.log

# Find slow queries
cat logs/mcp-server.log | jq 'select(.duration_ms > 2000)'

# Find failed tool calls
cat logs/mcp-server.log | jq 'select(.status == "error")'

# Session-specific logs
cat logs/mcp-server.log | jq 'select(.session_id == "abc-123")'
```

### Performance Profiling

```python
# Enable performance tracking
mcp:
  behavior:
    track_performance: true

# Access performance data
curl http://localhost:8765/api/performance

# Identify slow tools
cat logs/mcp-server.log | jq 'select(.tool_name) | {tool: .tool_name, duration: .duration_ms}' | sort -k2 -n
```

---

## Security

### API Authentication

Enable API key authentication:

```yaml
# config/mcp.yaml
mcp:
  api:
    auth:
      enabled: true
      api_key: "your-secret-key-here"
```

```bash
# Generate secure API key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Use API key in requests
curl -H "X-API-Key: your-secret-key" http://localhost:8765/api/search
```

### CORS Configuration

Configure CORS for web clients:

```yaml
mcp:
  api:
    cors:
      enabled: true
      origins:
        - "https://your-app.com"
        - "https://staging.your-app.com"
      # Or allow all (development only):
      # origins: ["*"]
```

### Rate Limiting

Implement rate limiting to prevent abuse:

```yaml
# In config/mcp.yaml
mcp:
  api:
    rate_limiting:
      enabled: true
      requests_per_minute: 100
      burst: 20
```

### Input Validation

All inputs are validated via Pydantic models:

- Session IDs: UUID format
- File paths: No directory traversal
- Query length: 2-500 characters
- Project IDs: Alphanumeric + hyphens/underscores

### Data Isolation

- Sessions scoped to projects
- No cross-project data access
- Memory isolation per session
- Event filtering by session

### Secure Deployment Checklist

- [ ] Enable API authentication
- [ ] Configure CORS properly
- [ ] Enable rate limiting
- [ ] Use HTTPS in production
- [ ] Restrict network access
- [ ] Regular security updates
- [ ] Monitor access logs
- [ ] Backup vector database
- [ ] Rotate API keys regularly
- [ ] Use environment variables for secrets

### Network Security

```bash
# Bind to localhost only (development)
export AGV_MCP_API_HOST=127.0.0.1

# Bind to all interfaces (production with firewall)
export AGV_MCP_API_HOST=0.0.0.0

# Use reverse proxy (recommended)
# nginx configuration:
server {
    listen 443 ssl;
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

---

## Production Deployment

### Systemd Service

Create a systemd service for automatic startup:

```ini
# /etc/systemd/system/agent-vault-mcp.service
[Unit]
Description=Agent-Vault MCP Server
After=network.target

[Service]
Type=simple
User=AGV
Group=AGV
WorkingDirectory=/opt/agent-vault
Environment="PATH=/opt/agent-vault/.venv/bin:/usr/local/bin:/usr/bin"
ExecStart=/usr/local/bin/uv run python -m agent_vault.mcp.cli
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl enable agent-vault-mcp
sudo systemctl start agent-vault-mcp

# Check status
sudo systemctl status agent-vault-mcp

# View logs
sudo journalctl -u agent-vault-mcp -f
```

### Process Management with Supervisor

```ini
# /etc/supervisor/conf.d/agent-vault-mcp.conf
[program:agent-vault-mcp]
command=/usr/local/bin/uv run python -m agent_vault.mcp.cli
directory=/opt/agent-vault
user=AGV
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/agent-vault-mcp/stdout.log
stderr_logfile=/var/log/agent-vault-mcp/stderr.log
environment=AGV_MCP_API_HOST="0.0.0.0",AGV_MCP_API_PORT="8765"
```

```bash
# Update supervisor
sudo supervisorctl reread
sudo supervisorctl update

# Control service
sudo supervisorctl start agent-vault-mcp
sudo supervisorctl stop agent-vault-mcp
sudo supervisorctl restart agent-vault-mcp
sudo supervisorctl status agent-vault-mcp
```

### Kubernetes Deployment

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-vault-mcp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: agent-vault-mcp
  template:
    metadata:
      labels:
        app: agent-vault-mcp
    spec:
      containers:
      - name: mcp-server
        image: agent-vault-mcp:latest
        ports:
        - containerPort: 8765
        env:
        - name: AGV_MCP_API_HOST
          value: "0.0.0.0"
        - name: AGV_MCP_API_PORT
          value: "8765"
        volumeMounts:
        - name: vector-db
          mountPath: /data/vector_db
        - name: config
          mountPath: /app/config
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8765
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8765
          initialDelaySeconds: 10
          periodSeconds: 5
      volumes:
      - name: vector-db
        persistentVolumeClaim:
          claimName: vector-db-pvc
      - name: config
        configMap:
          name: mcp-config

---
apiVersion: v1
kind: Service
metadata:
  name: agent-vault-mcp
spec:
  selector:
    app: agent-vault-mcp
  ports:
  - protocol: TCP
    port: 8765
    targetPort: 8765
  type: LoadBalancer
```

```bash
# Deploy to Kubernetes
kubectl apply -f deployment.yaml

# Check status
kubectl get pods -l app=agent-vault-mcp
kubectl get svc agent-vault-mcp

# View logs
kubectl logs -f deployment/agent-vault-mcp

# Scale deployment
kubectl scale deployment agent-vault-mcp --replicas=5
```

---

## Backup and Recovery

### Backup Vector Database

```bash
# Create backup
tar -czf vector_db_backup_$(date +%Y%m%d).tar.gz vector_db/

# Automated backup script
#!/bin/bash
BACKUP_DIR="/backups/agent-vault"
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf "$BACKUP_DIR/vector_db_$DATE.tar.gz" vector_db/

# Keep only last 7 days
find "$BACKUP_DIR" -name "vector_db_*.tar.gz" -mtime +7 -delete
```

### Restore from Backup

```bash
# Stop server
sudo systemctl stop agent-vault-mcp

# Restore database
tar -xzf vector_db_backup_20240115.tar.gz

# Start server
sudo systemctl start agent-vault-mcp
```

### Disaster Recovery

```bash
# 1. Backup configuration
cp -r config/ config.backup/

# 2. Backup vector database
tar -czf vector_db.tar.gz vector_db/

# 3. Backup logs
tar -czf logs.tar.gz logs/

# 4. Document recovery procedure
# - Reinstall dependencies
# - Restore configuration
# - Restore vector database
# - Reindex if necessary
```

---

## Maintenance

### Automated Maintenance

LanceDB storage maintenance (compaction and version cleanup) is **fully automated** via `MaintenanceManager`:

- **Triggers:** Runs on `indexing.completed` and `project.closed` events
- **Configuration:** `config/default.yaml` under `maintenance` section
- **Manual override:** Use `run_maintenance` MCP tool if needed

### Regular Tasks

```bash
# Weekly: Check disk space
df -h

# Weekly: Rotate logs
find logs/ -name "*.log" -mtime +30 -delete

# Monthly: Backup vector database
tar -czf vector_db_backup_$(date +%Y%m).tar.gz vector_db/

# Monthly: Update dependencies
uv sync --upgrade

# Quarterly: Review and clean old sessions
# Implement session cleanup in code
```

### Upgrading

```bash
# 1. Backup current installation
tar -czf agent-vault-backup-$(date +%Y%m%d).tar.gz .

# 2. Pull latest changes
git pull origin main

# 3. Update dependencies
uv sync

# 5. Restart server
sudo systemctl restart agent-vault-mcp

# 6. Verify health
curl http://localhost:8765/health
```

---

## Support

For additional help:

- Documentation: [Full documentation](../README.md)
- GitHub Issues: [Report issues](https://github.com/sbasha/agent-vault/issues)
- Community: [Join discussions](https://github.com/sbasha/agent-vault/discussions)
