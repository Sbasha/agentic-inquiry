# Schema Migration Guide

> Historical reference. This page describes PostgreSQL-family providers, cloud connectors or remote embedders that are not part of this local-only distribution. It is retained as design input for the external provider contract in [storage-backends.md](../storage-backends.md).

**Version:** 1.0
**Status:** Current
**Last Updated:** 2026-01-13

This guide explains how to handle schema changes in Agentic Inquiry's PostgreSQL backend, including embedding dimension migrations, Python compatibility, and backup/restore procedures.

## Overview

Schema migrations in Agentic Inquiry are **explicit and opt-in** to prevent accidental data loss. The system detects mismatches at startup and provides clear guidance for resolution.

### Migration Scenarios

| Scenario | Detection | Action Required |
|----------|-----------|-----------------|
| **Dimension mismatch** | Startup error | Run `ai schema migrate` |
| **New optional columns** | Auto-applied | None (backward compatible) |
| **Python 3.13+ upgrade** | Connection mode fallback | Update connection config |
| **SSL configuration change** | Connection error | Update SSL settings |

## Dimension Migration

### Understanding Dimension Mismatches

**What causes a mismatch:**
- Switching embedding models (e.g., OpenAI ada-002 [1536] → ada-003 [3072])
- Migrating from one model provider to another
- Upgrading to a newer embedding model version

**Why it matters:**
- PostgreSQL vector columns have fixed dimensions
- Wrong dimensions cause query failures
- Silent failures lead to incorrect results

### Detection at Startup

Agentic Inquiry automatically detects dimension mismatches when initializing:

```python
from agentic_inquiry.storage import create_storage_facade

config = BackendConfig(
    embedding_dimension=1536,  # New dimension
    # ... other config
)

storage = create_storage_facade(config)  # Raises SchemaMismatchError
```

**Error Message:**
```
SchemaMismatchError: Embedding dimension mismatch detected.
  Configured: 1536 dimensions
  Existing table: 768 dimensions

To migrate, run: ai schema migrate --project my-project --new-dimension 1536 --confirm-data-loss
This will drop and recreate the embedding column, requiring full re-indexing.
```

### Migration Process

#### Step 1: Review Impact

```bash
# Dry-run shows what will happen WITHOUT making changes
ai schema migrate --project my-project --new-dimension 1536 --dry-run
```

**Output:**
```
Schema Migration Plan
=====================

Source Configuration:
  Project: my-project
  Table: ai_v_chunks
  Current dimension: 768
  Configured dimension: 1536

Migration Steps:
  1. Create backup: _ai_migration_backup_chunks_20260113_143022
  2. Verify backup row count matches source
  3. Drop embedding column and index
  4. Add new embedding column (1536 dimensions)
  5. Mark all chunks as needs_reindex=True
  6. Recreate index (empty)

Impact:
  - All embeddings will be deleted
  - Semantic search will not work until re-indexing completes
  - Original content and metadata are preserved in backup
  - Estimated time: ~30 seconds for schema changes + re-indexing time

Backup:
  - Table: _ai_migration_backup_chunks_20260113_143022
  - Retention: 7 days (configurable)
  - Location: Same database
```

#### Step 2: Execute Migration

Migration requires explicit confirmation:

```bash
# This flag acknowledges embeddings will be deleted
ai schema migrate --project my-project --new-dimension 1536 --confirm-data-loss
```

**Migration Progress:**
```
Schema Migration
================

[1/7] Creating backup table...
  ✓ Backup created: _ai_migration_backup_chunks_20260113_143022

[2/7] Verifying backup...
  ✓ Source rows: 125,430
  ✓ Backup rows: 125,430
  ✓ Counts match

[3/7] Dropping embedding column...
  ✓ Column dropped

[4/7] Dropping vector index...
  ✓ Index dropped

[5/7] Creating new embedding column (1536 dimensions)...
  ✓ Column created

[6/7] Marking chunks for re-indexing...
  ✓ 125,430 chunks marked

[7/7] Creating empty index...
  ✓ Index created

Migration completed successfully in 28.3 seconds

Next Steps:
  1. Re-index all content:
     ai index rebuild --project my-project

  2. Monitor re-indexing progress:
     ai get-project-info --project my-project

Backup Information:
  Table: _ai_migration_backup_chunks_20260113_143022
  Retention: 7 days (auto-cleanup on 2026-01-20)
  To restore: ai schema restore --project my-project --backup 20260113_143022
```

#### Step 3: Re-Index Content

After migration, all content must be re-indexed with new embeddings:

```python
from agentic_inquiry.indexing import IndexingPipeline

pipeline = IndexingPipeline(storage_facade)

# Re-index all files in project
await pipeline.index_directory(
    path="/path/to/project",
    force_reindex=True  # Overwrite existing chunks
)
```

**Or via CLI:**
```bash
ai add-knowledge --project my-project \
    --content-type code \
    --source /path/to/project \
    --force-reindex
```

### Backup Verification

**Automatic Verification:**
Agentic Inquiry verifies backup integrity before proceeding:

```sql
-- Counts must match exactly
SELECT COUNT(*) FROM ai_v_chunks;        -- Source
SELECT COUNT(*) FROM _ai_migration_backup_...;   -- Backup
```

**If counts don't match:**
```
MigrationError: Backup verification failed
  Source rows: 125,430
  Backup rows: 125,428
  Missing: 2 rows

Migration aborted. No changes made to source table.
Backup table dropped: _ai_migration_backup_chunks_20260113_143022
```

### Backup Retention

**Default Retention:** 7 days

**Custom Retention:**
```bash
ai schema migrate --project my-project \
    --new-dimension 1536 \
    --confirm-data-loss \
    --backup-retention-days 30
```

**Manual Cleanup:**
```sql
-- List backup tables
SELECT tablename FROM pg_tables
WHERE tablename LIKE '_ai_migration_backup_%';

-- Drop specific backup
DROP TABLE _ai_migration_backup_chunks_20260113_143022;
```

**Automatic Cleanup:**
Backups are automatically cleaned up by the maintenance job (see [Maintenance Operations](maintenance.md)).

### Restore from Backup

If migration fails or you need to rollback:

```bash
# List available backups
ai schema list-backups --project my-project

# Restore from specific backup
ai schema restore --project my-project --backup 20260113_143022
```

**Restore Process:**
1. Validates backup exists
2. Drops current table
3. Renames backup to original table name
4. Recreates indexes (with original dimension)
5. Restores system metadata

**Important:** Restore is also destructive. Any changes made after backup are lost.

## Python Version Compatibility

### Connection Mode Detection

Agentic Inquiry automatically selects the appropriate connection mode based on Python version and available packages:

| Python Version | Primary Mode | Fallback Mode |
|----------------|--------------|---------------|
| 3.10-3.12 | Cloud SQL Connector | Direct asyncpg |
| 3.13+ | Direct asyncpg | N/A |

### Python 3.13+ Setup

The `cloud-sql-python-connector` package does not yet support Python 3.13. For Python 3.13+, use direct asyncpg connection with Cloud SQL Auth Proxy.

#### Option 1: Cloud SQL Auth Proxy (Recommended)

**Step 1: Install Auth Proxy**
```bash
# Using gcloud
gcloud components install cloud-sql-proxy

# Or download directly
curl -o cloud-sql-proxy \
  https://dl.google.com/cloudsql/cloud_sql_proxy.darwin.amd64
chmod +x cloud-sql-proxy
```

**Step 2: Start Auth Proxy**
```bash
# Start proxy in background
cloud-sql-proxy --port 5432 my-project:us-central1:my-instance &

# Or with IAM authentication
cloud-sql-proxy --port 5432 \
  my-project:us-central1:my-instance \
  --auto-iam-authn
```

**Step 3: Configure Direct Connection**
```python
from agentic_inquiry.storage.config import BackendConfig

config = BackendConfig(
    type="cloudsql",
    connection_string="postgresql://user:pass@localhost:5432/agentic-inquiry",
    ssl_mode="require"  # Required for direct connections
)
```

#### Option 2: Public IP with SSL (Not Recommended for Production)

**Enable Public IP:**
```bash
gcloud sql instances patch my-instance --assign-ip
```

**Download Server CA Certificate:**
```bash
gcloud sql ssl-certs create client-cert client-key \
    --instance=my-instance

gcloud sql ssl-certs describe client-cert \
    --instance=my-instance \
    --format="get(cert)" > server-ca.pem
```

**Configure with SSL Verification:**
```python
config = BackendConfig(
    type="cloudsql",
    connection_string="postgresql://user:pass@35.1.2.3:5432/agentic-inquiry",
    ssl_mode="verify-full",  # Verify server identity
    ssl_ca_cert="/path/to/server-ca.pem"
)
```

### SSL Configuration

#### SSL Modes

| Mode | Server Auth | MITM Protection | Use Case |
|------|-------------|-----------------|----------|
| `disable` | ❌ | ❌ | **Not allowed** for direct connections |
| `allow` | ❌ | ❌ | **Not allowed** for direct connections |
| `prefer` | ❌ | ❌ | **Not allowed** for direct connections |
| `require` | ❌ | ✅ | Minimum for direct connections |
| `verify-ca` | ✅ | ✅ | Verifies server certificate |
| `verify-full` | ✅ | ✅ | Verifies certificate + hostname |

#### Required SSL Configuration

**Minimum (Development):**
```python
config = BackendConfig(
    connection_string="...",
    ssl_mode="require"  # Encrypts connection
)
```

**Recommended (Production):**
```python
config = BackendConfig(
    connection_string="...",
    ssl_mode="verify-full",               # Full verification
    ssl_ca_cert="/etc/ssl/server-ca.pem"  # Required for verify-full
)
```

#### SSL Configuration Errors

**Error: `SSLRequiredError`**
```
SSLRequiredError: Direct connection requires ssl_mode='require' or stricter.
Got: ssl_mode='disable'

For security, direct asyncpg connections must use SSL.
Set ssl_mode to one of: require, verify-ca, verify-full
```

**Solution:**
```python
config = BackendConfig(
    connection_string="...",
    ssl_mode="require"  # Add this
)
```

**Error: `SSLRequiredError` (CA cert missing)**
```
SSLRequiredError: ssl_mode='verify-full' requires ssl_ca_cert path to CA certificate

Download CA certificate:
  gcloud sql ssl-certs describe client-cert \
      --instance=my-instance \
      --format="get(cert)" > server-ca.pem
```

**Solution:**
```python
config = BackendConfig(
    connection_string="...",
    ssl_mode="verify-full",
    ssl_ca_cert="/path/to/server-ca.pem"  # Add this
)
```

### Connection Mode Warnings

When direct connection mode is used, Agentic Inquiry logs a warning:

```
WARNING: Using direct asyncpg connection. IAM authentication is not available.
For production, consider using Cloud SQL Auth Proxy.

Connection: postgresql://user@localhost:5432/agentic-inquiry
SSL Mode: require
Python Version: 3.13.0
```

This is informational only and does not indicate a problem if Auth Proxy is running.

### Connector Availability Error

**Error when connector unavailable:**
```
CloudSQLConnectorUnavailable: The cloud-sql-python-connector package is not available.

This can happen because:
  1. The 'cloudsql' extras were not installed: pip install agentic-inquiry[cloudsql]
  2. Python 3.13+ is being used (connector not yet supported)

Options:
  A) Install extras: pip install agentic-inquiry[cloudsql]
  B) Use direct connection: Set 'connection_string' instead of 'project/instance/region'
     Note: Direct connection requires Cloud SQL Auth Proxy or public IP with SSL.

See: https://docs.agentic-inquiry.dev/storage/cloudsql-setup#python-313
```

## Additive Schema Changes

### Supported Changes

Agentic Inquiry supports adding new optional columns without breaking existing deployments:

```sql
-- Automatically handled at startup
ALTER TABLE ai_v_chunks
ADD COLUMN IF NOT EXISTS new_column TEXT;
```

**Supported additive changes:**
- New nullable columns
- New indexes on existing columns
- New constraints with defaults

**Not supported (requires migration):**
- Modifying existing columns (type, dimension)
- Dropping columns
- Non-nullable columns without defaults

### Backward Compatibility

Existing deployments automatically receive additive changes:

```python
# Older version (no new_column)
storage = create_storage_facade(config)  # Works fine

# Newer version (has new_column)
storage = create_storage_facade(config)  # Works fine, column auto-added
```

## Schema Version Tracking

### Version Metadata

Agentic Inquiry tracks schema versions in a metadata table:

```sql
CREATE TABLE IF NOT EXISTS _ai_schema_meta (
    table_name TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    embedding_dimension INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Querying Schema Version

**Via Health Check:**
```bash
curl http://localhost:8080/health
```

**Response:**
```json
{
  "status": "healthy",
  "schema_version": 2,
  "embedding_dimension": 1536,
  "database": "agentic-inquiry",
  "index_type": "hnsw"
}
```

**Via Python API:**
```python
status = await storage.get_maintenance_status()
print(f"Schema version: {status.schema_version}")
print(f"Dimension: {status.embedding_dimension}")
```

### Version Increment

Schema version increments on:
- Dimension migration
- Major schema changes (ALTER TABLE)
- Index type changes (tracked separately)

Version does NOT increment on:
- Additive changes (new nullable columns)
- Data-only changes (INSERT/UPDATE/DELETE)
- Index rebuilds with same type

## Audit Logging

All schema changes are logged for compliance and debugging:

```python
import logging
logger = logging.getLogger("agentic_inquiry.storage.audit")
```

**Logged Events:**

| Event | Level | Example |
|-------|-------|---------|
| Migration start | INFO | `Migration started: dimension 768→1536, user=service-account@...` |
| Backup created | INFO | `Backup created: _ai_migration_backup_chunks_20260113_143022, rows=125430` |
| Migration success | INFO | `Migration completed: duration=28.3s, rows=125430` |
| Migration failure | ERROR | `Migration failed: backup verification mismatch, source=125430, backup=125428` |
| Restore start | INFO | `Restore started: backup=20260113_143022, user=admin@...` |
| Restore success | INFO | `Restore completed: duration=15.2s, rows=125430` |

**Audit Log Location:**
```bash
# Default location
tail -f /var/log/agentic-inquiry/audit.log

# Or configured via environment
export INQUIRY_AUDIT_LOG=/path/to/audit.log
```

## Troubleshooting

### Migration Hangs

**Symptom:** Migration doesn't complete after 5+ minutes

**Possible Causes:**
1. Table has active long-running queries
2. Instance is undersized for table size
3. Disk I/O bottleneck

**Solution:**
```bash
# Check active connections
gcloud sql operations list --instance my-instance --limit 5

# Identify blocking queries
psql -c "SELECT pid, state, query FROM pg_stat_activity
         WHERE state != 'idle' AND query NOT LIKE '%pg_stat_activity%';"

# Upgrade instance temporarily
gcloud sql instances patch my-instance --tier db-standard-8
```

### Backup Verification Fails

**Symptom:** Migration aborts with count mismatch

**Possible Causes:**
1. Concurrent writes during backup
2. Replication lag (if using read replicas)
3. Corrupted backup

**Solution:**
```bash
# Retry migration (creates new backup)
ai schema migrate --project my-project --new-dimension 1536 --confirm-data-loss

# Or manually verify and force
psql -c "SELECT COUNT(*) FROM ai_v_chunks;"
psql -c "SELECT COUNT(*) FROM _ai_migration_backup_chunks_..."
```

### SSL Connection Fails

**Symptom:** `SSLRequiredError` or SSL handshake failure

**Common Issues:**
```bash
# Issue 1: Missing ssl_mode
# Solution: Add ssl_mode="require"

# Issue 2: Wrong CA certificate
# Solution: Re-download from Cloud SQL
gcloud sql ssl-certs describe client-cert --instance=my-instance

# Issue 3: Auth Proxy not running
# Solution: Check proxy status
ps aux | grep cloud-sql-proxy
```

### Python 3.13 Connection Fails

**Symptom:** `CloudSQLConnectorUnavailable` on Python 3.13

**Solution (Preferred):**
```bash
# Use Auth Proxy
cloud-sql-proxy --port 5432 my-project:region:instance

# Update config
config = BackendConfig(
    connection_string="postgresql://user:pass@localhost:5432/agentic-inquiry",
    ssl_mode="require"
)
```

**Alternative (Downgrade):**
```bash
# Use Python 3.12
pyenv install 3.12.7
pyenv local 3.12.7
pip install agentic-inquiry[cloudsql]
```

## Configuration Reference

### BackendConfig Schema Fields

```python
@dataclass
class BackendConfig:
    # Schema configuration
    embedding_dimension: int = 1536

    # Connection (for Python 3.13+ or direct mode)
    connection_string: str | None = None
    ssl_mode: str = "require"  # require, verify-ca, verify-full
    ssl_ca_cert: str | None = None

    # Migration
    backup_retention_days: int = 7
```

### Migration CLI Options

```bash
ai schema migrate --help

Options:
  --project TEXT              Project name [required]
  --new-dimension INT         New embedding dimension [required]
  --dry-run                   Show plan without making changes
  --confirm-data-loss         Required flag to confirm embeddings will be deleted
  --backup-retention-days INT Backup retention in days [default: 7]
```

## Related Documentation

- [Index Configuration Guide](index-configuration.md) - Vector index types and tuning
- [Maintenance Operations](maintenance.md) - Scheduled operations
- [Cloud SQL Backend](../backends/cloudsql.md) - Cloud SQL configuration, setup, and Python compatibility

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-13 | Initial release with dimension migration and Python 3.13 support |
