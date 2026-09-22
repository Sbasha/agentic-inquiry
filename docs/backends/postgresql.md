---
name: PostgreSQL
description: Self-hosted PostgreSQL with pgvector for production deployments
type: postgresql
requires_setup: true
config_file: config/postgresql.yaml
port: 5432

maintenance:
  enabled: true
  command: agv maintenance run --operation all
  threshold_gb: 10
  aggressive_threshold_gb: 50

setup:
  duration_minutes: 5
  steps:
    - description: Install PostgreSQL and pgvector
      command: |
        # Ubuntu/Debian
        sudo apt-get install postgresql postgresql-contrib
        sudo apt-get install postgresql-15-pgvector
        # macOS
        brew install postgresql@15 pgvector
    - description: Create database
      command: createdb agent-vault
    - description: Enable pgvector extension
      command: psql -d agent-vault -c "CREATE EXTENSION IF NOT EXISTS vector"

teardown:
  steps:
    - description: Drop database
      command: dropdb agent-vault
---

# PostgreSQL Backend

Self-hosted PostgreSQL with pgvector provides production-grade vector storage with full ACID compliance, connection pooling, and enterprise-grade reliability.

**Note:** This is the **unified PostgreSQL provider** that handles PostgreSQL, Cloud SQL, AND AlloyDB backends. The provider automatically adapts based on the `embedding_strategy` configuration.

## When to Use PostgreSQL

- **Production deployments** - Multi-user, ACID-compliant storage
- **Team environments** - Shared database for collaboration
- **Existing PostgreSQL infrastructure** - Leverage existing database servers
- **Custom hosting** - On-premises or any cloud provider

For GCP-managed PostgreSQL, see [Cloud SQL Backend](./cloudsql.md). For AlloyDB with server-side embedding, see [AlloyDB Configuration](#alloydb-unified-provider) below.

## Quick Start

### 1. Install PostgreSQL with pgvector

**macOS:**
```bash
brew install postgresql@15 pgvector
brew services start postgresql@15
```

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install postgresql-15 postgresql-15-pgvector
sudo systemctl start postgresql
```

**Docker:**
```bash
docker run -d \
  --name agent-vault-postgres \
  -e POSTGRES_PASSWORD=yourpassword \
  -e POSTGRES_DB=agent-vault \
  -p 5432:5432 \
  pgvector/pgvector:pg15
```

### 2. Create Database and Extension

```bash
# Create database
createdb agent-vault

# Enable pgvector
psql -d agent-vault -c "CREATE EXTENSION IF NOT EXISTS vector"

# Verify
psql -d agent-vault -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'"
```

### 3. Configure Agent-Vault

```yaml
# config/postgresql.yaml
storage:
  root: ".agv/"

  backends:
    primary:
      type: postgresql
      connection_string: postgresql://localhost:5432/agent-vault
      # Or use individual parameters:
      # host: localhost
      # port: 5432
      # database: agent-vault
      # user: postgres
      # password: ${POSTGRES_PASSWORD}

      # Connection pool settings
      pool_size: 20
      min_pool_size: 5
      max_overflow: 10

  vector_backend: primary
  graph_backend: primary
```

### 4. Start Agent-Vault

```bash
# Set password if using environment variable
export POSTGRES_PASSWORD=yourpassword

# Start server
uv run agv --config config/postgresql.yaml my_project
```

## Configuration Options

### Connection Methods

**Connection String (Recommended):**
```yaml
backends:
  primary:
    type: postgresql
    connection_string: postgresql://user:pass@host:5432/database

    # Embedding strategy (local or server_side)
    embedding_strategy: local  # Default: local SentenceTransformer
    embedding_model: all-MiniLM-L6-v2
    embedding_dim: 384
```

**Individual Parameters:**
```yaml
backends:
  primary:
    type: postgresql
    host: localhost
    port: 5432
    database: agent-vault
    user: agv_user
    password: ${POSTGRES_PASSWORD}

    # Embedding strategy
    embedding_strategy: local
    embedding_model: all-MiniLM-L6-v2
    embedding_dim: 384
```

### Connection Pooling

```yaml
backends:
  primary:
    type: postgresql
    connection_string: postgresql://localhost/agent-vault

    # Pool configuration
    pool_size: 20          # Maximum connections
    min_pool_size: 5       # Minimum idle connections
    max_overflow: 10       # Extra connections under load
    pool_timeout: 30       # Seconds to wait for connection
    pool_recycle: 3600     # Recycle connections after 1 hour
```

### SSL/TLS Configuration

```yaml
backends:
  primary:
    type: postgresql
    connection_string: postgresql://localhost/agent-vault?sslmode=require

    # Or with certificates
    ssl_mode: verify-full
    ssl_ca: /path/to/ca.crt
    ssl_cert: /path/to/client.crt
    ssl_key: /path/to/client.key
```

### Vector Index Configuration

```yaml
backends:
  primary:
    type: postgresql
    connection_string: postgresql://localhost/agent-vault

    # HNSW index (default, best recall)
    index_type: hnsw
    hnsw_m: 16              # Max connections per node
    hnsw_ef_construction: 64  # Index build quality

    # Or IVF-Flat (large scale)
    # index_type: ivfflat
    # expected_rows: 1000000  # Auto-calculates lists
```

## Database Schema

Agent-Vault creates these tables automatically:

| Table | Purpose |
|-------|---------|
| `agv_v_chunks` | Vector embeddings and content chunks |
| `agv_v_entities` | Code entities (classes, functions, etc.) |
| `agv_v_relationships` | Graph relationships between entities |
| `agv_schema_meta` | Schema version tracking |

### Manual Schema Creation (Optional)

```sql
-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Tables are created automatically on first use
-- But you can pre-create for custom settings:

CREATE TABLE agv_v_chunks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT,
    content TEXT,
    embedding vector(384),  -- Dimension matches your model
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create HNSW index for fast similarity search
CREATE INDEX ON agv_v_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

## Maintenance

### Automated Maintenance

```bash
# Run all maintenance (vacuum + reindex + analyze)
agv maintenance run --operation all

# Individual operations
agv maintenance run --operation vacuum    # Reclaim space
agv maintenance run --operation reindex   # Rebuild indexes
agv maintenance run --operation analyze   # Update statistics
```

### Manual PostgreSQL Commands

```bash
# VACUUM ANALYZE (reclaim space, update statistics)
psql -d agent-vault -c "VACUUM ANALYZE"

# REINDEX (rebuild indexes)
psql -d agent-vault -c "REINDEX DATABASE agent-vault"

# Check table sizes
psql -d agent-vault -c "
  SELECT tablename,
         pg_size_pretty(pg_total_relation_size('public.'||tablename)) as size
  FROM pg_tables
  WHERE schemaname = 'public' AND tablename LIKE 'agv_%'
  ORDER BY pg_total_relation_size('public.'||tablename) DESC
"

# Check index health
psql -d agent-vault -c "
  SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
  FROM pg_stat_user_indexes
  WHERE schemaname = 'public'
"
```

### Monitoring

```bash
# Active connections
psql -d agent-vault -c "SELECT count(*) FROM pg_stat_activity WHERE datname = 'agent-vault'"

# Connection states
psql -d agent-vault -c "
  SELECT state, count(*)
  FROM pg_stat_activity
  WHERE datname = 'agent-vault'
  GROUP BY state
"

# Long-running queries
psql -d agent-vault -c "
  SELECT pid, now() - pg_stat_activity.query_start AS duration, query
  FROM pg_stat_activity
  WHERE state = 'active' AND query NOT LIKE '%pg_stat_activity%'
  ORDER BY duration DESC
  LIMIT 5
"
```

## Production Recommendations

### Hardware Sizing

| Workload | RAM | CPU | Storage |
|----------|-----|-----|---------|
| Small (< 100K chunks) | 4 GB | 2 cores | 20 GB SSD |
| Medium (100K-1M chunks) | 16 GB | 4 cores | 100 GB SSD |
| Large (1M+ chunks) | 64 GB | 8+ cores | 500 GB+ SSD |

### PostgreSQL Configuration

```bash
# postgresql.conf recommendations for Agent-Vault

# Memory
shared_buffers = 4GB           # 25% of RAM
effective_cache_size = 12GB    # 75% of RAM
work_mem = 256MB               # For vector operations
maintenance_work_mem = 1GB     # For VACUUM/REINDEX

# Parallelism
max_parallel_workers_per_gather = 4
max_parallel_maintenance_workers = 4

# Write performance
wal_buffers = 64MB
checkpoint_completion_target = 0.9

# Connections
max_connections = 200
```

### Backup Strategy

```bash
# Daily logical backup
pg_dump agent-vault > backup_$(date +%Y%m%d).sql

# Continuous archiving (point-in-time recovery)
# Configure in postgresql.conf:
archive_mode = on
archive_command = 'cp %p /backup/wal/%f'
```

## Troubleshooting

### Connection Issues

```bash
# Test connection
psql -h localhost -p 5432 -U postgres -d agent-vault -c "SELECT 1"

# Check PostgreSQL is running
pg_isready -h localhost -p 5432

# Check pg_hba.conf for authentication
sudo cat /etc/postgresql/15/main/pg_hba.conf
```

### pgvector Not Found

```bash
# Check if extension is installed
psql -d agent-vault -c "SELECT * FROM pg_available_extensions WHERE name = 'vector'"

# Install pgvector (Ubuntu)
sudo apt-get install postgresql-15-pgvector

# Then enable in database
psql -d agent-vault -c "CREATE EXTENSION vector"
```

### Slow Queries

```bash
# Enable query logging
psql -d agent-vault -c "ALTER SYSTEM SET log_min_duration_statement = 1000"
psql -d agent-vault -c "SELECT pg_reload_conf()"

# Check for missing indexes
psql -d agent-vault -c "
  SELECT schemaname, tablename, indexname, idx_scan
  FROM pg_stat_user_indexes
  WHERE idx_scan = 0 AND indexname NOT LIKE 'pg_%'
"

# Analyze query plan
psql -d agent-vault -c "EXPLAIN ANALYZE SELECT ... "
```

### Out of Connections

```bash
# Kill idle connections
psql -d agent-vault -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE datname = 'agent-vault'
    AND state = 'idle'
    AND query_start < now() - interval '1 hour'
"

# Increase max_connections in postgresql.conf
# Then restart PostgreSQL
```

## Embedding Strategies

The unified PostgreSQL provider supports two embedding strategies:

| Strategy | Embedding Location | Performance | Use Case |
|----------|-------------------|-------------|----------|
| `local` | Client-side (SentenceTransformer) | ~2-4 files/sec | Self-hosted PostgreSQL, CloudSQL |
| `server_side` | Database-side (AlloyDB `text-embedding-005`) | ~16+ files/sec | AlloyDB with google_ml_integration |

### Local Embedding (Default)

```yaml
backends:
  primary:
    type: postgresql
    connection_string: postgresql://localhost/agent-vault
    embedding_strategy: local  # Default
    embedding_model: all-MiniLM-L6-v2
    embedding_dim: 384
```

Pipeline generates embeddings locally using SentenceTransformer before inserting chunks.

### Server-Side Embedding (AlloyDB)

```yaml
backends:
  alloydb:
    type: alloydb  # Auto-configures server_side strategy
    project: your-gcp-project
    region: us-central1
    cluster: your-cluster
    instance: your-instance
    database: agent-vault
    user: postgres
    password: ${ALLOYDB_PASSWORD}

    # Auto-set by validate_alloydb_config():
    embedding_strategy: server_side
    embedding_model: text-embedding-005
    embedding_dim: 768
```

Pipeline skips local embedding, calls `generate_embeddings()` after indexing to generate embeddings in AlloyDB.

## AlloyDB Unified Provider

AlloyDB is handled by the **same PostgreSQL provider** with server-side embedding support. The old `storage/providers/alloydb/` package is dead code and no longer used.

### How It Works

- **Registry mapping:** Backend type `"alloydb"` maps to `PostgresVectorProvider` and `PostgresGraphProvider`
- **Server-side embedding:** Set `embedding_strategy: "server_side"` to skip local embedding and use AlloyDB's `ai.initialize_embeddings()` or per-row `embedding()` function
- **Auto-configuration:** `validate_alloydb_config()` automatically sets server_side strategy, text-embedding-005 model, and 768 dimensions

### Configuration

```yaml
storage:
  backends:
    alloydb:
      type: alloydb  # Maps to PostgreSQL provider internally
      project: your-gcp-project
      region: us-central1
      cluster: your-cluster
      instance: your-instance
      database: agent-vault
      user: postgres
      password: ${ALLOYDB_PASSWORD}

      # AlloyDB-specific settings
      embedding_strategy: server_side  # Auto-set by validate_alloydb_config()
      embedding_model: text-embedding-005
      embedding_dim: 768

      # Connection pooling (CRITICAL: keep low for AlloyDB)
      pool_size: 5
      max_overflow: 2

  vector_backend: alloydb
  graph_backend: alloydb
```

### Server-Side Embedding

When `embedding_strategy: server_side`:

1. **Indexing:** Pipeline skips local embedding, calls `generate_embeddings()` after indexing
2. **Generation:** Uses `ai.initialize_embeddings()` at ~136-400/sec for fresh tables
3. **Fallback:** Per-row `embedding()` at ~25/sec for tables with existing embeddings
4. **Search:** Pass query text directly to `vector_search()`, AlloyDB generates embeddings server-side

**Critical Constraints:**
- `ai.initialize_embeddings()` MUST run before ANY rows have embeddings (4MB Vertex AI limit)
- Enable flag: `google_ml_integration.enable_faster_embedding_generation = on`
- Content truncation: `LEFT(content, 8000)` in fallback path (model has ~2048 token limit)
- Batch size: Must be ≤ 250 (Vertex AI instance limit)

### Connection via Proxy

```bash
# Install AlloyDB Auth Proxy
gcloud components install alloydb-auth-proxy

# Start proxy
alloydb-auth-proxy \
  --address=0.0.0.0 \
  --port=5432 \
  --public-ip \
  projects/PROJECT/locations/REGION/clusters/CLUSTER/instances/INSTANCE
```

### Performance

**Production Benchmark (large Java monolith, 2026-02-09):**
- **Files:** 16,706 indexed (Java + JSP + XML + HTML)
- **Chunks:** 525,664 chunks in 17 minutes
- **Throughput:** 16.6 files/sec average, 19.7 peak
- **Improvement:** 27x faster than GENERATED ALWAYS AS approach (0.6 → 16.6 files/sec)

### ScaNN Index Support

AlloyDB supports ScaNN (Scalable Approximate Nearest Neighbors) via `ivf` access method:

```sql
-- Create ScaNN index on chunks
CREATE INDEX idx_chunks_embedding ON agv_v_chunks
USING ivf (embedding vector_cosine_ops)
WITH (num_neighbors = 16);
```

**Benefits over HNSW:**
- **10x faster filtered search** - Superior for metadata filtering
- **4x smaller memory** - Lower overhead for large datasets
- **10x faster index build** - Reduced downtime during reindex
- **AlloyDB-optimized** - Native integration with Google infrastructure

**Current Usage:**
- **Chunks:** HNSW (m=16, ef_construction=64) - default for broad search
- **Entities:** IVFFlat (lists=100) - smaller dataset

See [Index Configuration](../storage/index-configuration.md#scann-index-alloydb) for ScaNN tuning.

## Related Documentation

- [Storage Backends Overview](./README.md) - Backend comparison
- [Cloud SQL Setup](./cloudsql.md) - GCP managed PostgreSQL
- [Index Configuration](../storage/index-configuration.md) - HNSW vs IVF-Flat vs ScaNN
- [Schema Migration](../storage/schema-migration.md) - Dimension changes
- [Maintenance Operations](../storage/maintenance.md) - VACUUM, REINDEX
