---
name: Cloud SQL
description: GCP-managed PostgreSQL with automatic HA, backups, and IAM auth
type: cloudsql
requires_setup: true
config_file: config/cloudsql.yaml

maintenance:
  enabled: true
  command: agv maintenance run --operation all
  threshold_gb: 10
  aggressive_threshold_gb: 50

setup:
  duration_minutes: 10
  steps:
    - description: Create Cloud SQL instance
      command: gcloud sql instances create agent-vault --database-version=POSTGRES_15 --tier=db-f1-micro --region=us-central1
      wait_for_completion: true
    - description: Create database
      command: gcloud sql databases create agent-vault --instance=agent-vault
    - description: Create user
      command: gcloud sql users create agv_user --instance=agent-vault --password=${DB_PASSWORD}
    - description: Start Cloud SQL Proxy
      command: cloud-sql-proxy --port 5432 PROJECT:REGION:agent-vault
      background: true

teardown:
  steps:
    - description: Delete Cloud SQL instance
      command: gcloud sql instances delete agent-vault --quiet
---

# Cloud SQL Backend

Google Cloud SQL provides a fully managed PostgreSQL database with automatic high availability, backups, and seamless GCP integration.

**Note:** Cloud SQL uses the **unified PostgreSQL provider**, the same provider that handles self-hosted PostgreSQL and AlloyDB. See [PostgreSQL Backend](./postgresql.md) for full provider documentation.

## When to Use Cloud SQL

- **GCP-native deployments** - Leverage IAM, VPC, and GCP ecosystem
- **Production workloads** - Automatic HA, point-in-time recovery
- **Team environments** - Multi-user access with managed infrastructure
- **Compliance requirements** - SOC 2, HIPAA, PCI-DSS certifications

## Quick Start

### Prerequisites

1. GCP project with billing enabled
2. `gcloud` CLI installed and authenticated
3. Cloud SQL Admin API enabled

### Create Instance

```bash
# Create Cloud SQL instance (~5-8 minutes)
gcloud sql instances create agent-vault \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1 \
  --root-password=YOUR_PASSWORD

# Create database
gcloud sql databases create agent-vault --instance=agent-vault

# Create application user
gcloud sql users create agv_user \
  --instance=agent-vault \
  --password=YOUR_APP_PASSWORD
```

### Connect via Proxy

```bash
# Install Cloud SQL Proxy
brew install cloud-sql-proxy  # macOS
# or download from https://cloud.google.com/sql/docs/postgres/sql-proxy

# Start proxy
cloud-sql-proxy --port 5432 PROJECT_ID:REGION:agent-vault
```

### Configure Agent-Vault

**Option 1: Native Cloud SQL Connector (Python 3.10-3.12)**

```yaml
# config/cloudsql.yaml
storage:
  backends:
    cloudsql:
      type: cloudsql
      project: your-gcp-project
      region: us-central1
      instance: agent-vault
      database: agent-vault
      user: agv_user
      password: ${agv_DB_PASSWORD}

  vector_backend: cloudsql
  graph_backend: cloudsql
```

**Option 2: Direct Connection via Proxy (Python 3.10-3.13)**

```yaml
# config/cloudsql.yaml
storage:
  backends:
    cloudsql:
      type: postgresql  # Use postgresql type with proxy
      connection_string: postgresql://agv_user:${agv_DB_PASSWORD}@localhost:5432/agent-vault

  vector_backend: cloudsql
  graph_backend: cloudsql
```

### Run Agent-Vault

```bash
# Set password
export agv_DB_PASSWORD=your_app_password

# Start with Cloud SQL backend
uv run agv --config config/cloudsql.yaml my_project
```

## Python Version Compatibility

| Python Version | Connection Method | Notes |
|----------------|-------------------|-------|
| 3.10-3.12 | Native Connector | Full support, recommended |
| 3.13+ | Proxy + Direct | Use Cloud SQL Proxy |

For Python 3.13+, the Google Cloud SQL Connector doesn't support the latest Python. Use the Cloud SQL Proxy approach instead.

## Production Configuration

### Instance Sizing

| Workload | Tier | vCPUs | Memory | Storage |
|----------|------|-------|--------|---------|
| Development | db-f1-micro | Shared | 0.6 GB | 10 GB |
| Small Team | db-custom-2-4096 | 2 | 4 GB | 50 GB |
| Production | db-custom-4-16384 | 4 | 16 GB | 100 GB |
| Enterprise | db-custom-8-32768 | 8 | 32 GB | 500 GB |

### High Availability

```bash
# Enable HA (adds standby in different zone)
gcloud sql instances patch agent-vault \
  --availability-type=REGIONAL
```

### Connection Pooling

**CRITICAL:** CloudSQL has `max_connections=25` (22 usable). Must use conservative pool settings to avoid exhaustion.

```yaml
storage:
  backends:
    cloudsql:
      type: cloudsql
      # ... connection settings

      # Connection pooling (CRITICAL for CloudSQL)
      pool_size: 5           # CRITICAL: Keep low (max_connections=25)
      max_overflow: 2        # CRITICAL: Total = 7 max per process

      # Embedding strategy
      embedding_strategy: local  # Cloud SQL uses local embedding
      embedding_model: all-MiniLM-L6-v2
      embedding_dim: 384
```

**Why Conservative Pool Sizing:**
- CloudSQL's `max_connections=25` limit is shared across ALL connections
- Default pool settings (pool_size=10, max_overflow=5) can exhaust connections
- Orphaned "idle in transaction" connections from timed-out operations linger
- Recommended: `pool_size: 5, max_overflow: 2` (7 max per process)

**Connection Pool Exhaustion:**

CloudSQL instances have limited connections. Orphaned "idle in transaction" connections from timed-out indexing runs can exhaust the pool.

**Symptoms:**
- `Failed to acquire connection` errors
- New runs fail immediately
- CloudSQL shows 22+ active connections

**Diagnosis:**
```bash
# Check orphaned processes
ps aux | grep agent-vault

# Check DB connections
psql -d agent-vault_test -c "SELECT count(*) FROM pg_stat_activity WHERE datname='agent-vault_test'"
```

**Fix:**
```bash
# Kill orphaned processes
pkill -f "agent-vault"

# Terminate stale connections
psql -d agent-vault_test -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE datname='agent-vault_test' AND pid != pg_backend_pid()
"
```

**Prevention:**
- Use `pool_size: 5, max_overflow: 2` (7 max per process)
- Set appropriate timeouts for large file indexing:
  ```python
  await pipeline.index_directory(
      path="./src",
      timeout=1800,  # 30 minutes total
      timeout_per_file=120,  # 2 minutes per file
      base_timeout=120
  )
  ```
- Monitor connection counts regularly

## Maintenance

### Automatic Backups

Cloud SQL provides automatic daily backups. Configure retention:

```bash
gcloud sql instances patch agent-vault \
  --backup-start-time=03:00 \
  --retained-backups-count=14
```

### Manual Maintenance

```bash
# Run vacuum and reindex
uv run agv maintenance run --config config/cloudsql.yaml --operation all

# Check database health
uv run agv maintenance run --config config/cloudsql.yaml --operation vacuum --dry-run
```

### Monitoring

```bash
# View instance metrics
gcloud sql instances describe agent-vault

# Monitor connections
gcloud sql operations list --instance=agent-vault
```

## Cost Optimization

| Strategy | Savings | Implementation |
|----------|---------|----------------|
| Right-size instance | 30-50% | Start small, monitor, scale up |
| Committed use | 25-57% | 1 or 3 year commitments |
| Stop dev instances | 100% | `gcloud sql instances patch --activation-policy=NEVER` |
| Regional vs Multi-regional | 40% | Use regional for non-critical |

## Troubleshooting

### Connection Refused

```bash
# Verify proxy is running
lsof -i :5432

# Check instance status
gcloud sql instances describe agent-vault --format="value(state)"

# Verify network access
gcloud sql instances describe agent-vault --format="value(ipAddresses)"
```

### Permission Denied

```bash
# Re-authenticate
gcloud auth application-default login

# Verify IAM permissions
gcloud projects get-iam-policy YOUR_PROJECT \
  --filter="bindings.members:YOUR_EMAIL"
```

### Slow Queries

```bash
# Enable query insights
gcloud sql instances patch agent-vault \
  --insights-config-query-insights-enabled \
  --insights-config-query-string-length=4096 \
  --insights-config-record-application-tags \
  --insights-config-record-client-address
```

## Related Documentation

- [Index Configuration](../storage/index-configuration.md) - Vector index tuning
- [Schema Migration](../storage/schema-migration.md) - Dimension changes
- [Maintenance Operations](../storage/maintenance.md) - VACUUM, REINDEX
