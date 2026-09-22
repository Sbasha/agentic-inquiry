# Vector Index Configuration Guide

**Version:** 1.0
**Status:** Current
**Last Updated:** 2026-01-13

This guide explains how to configure and manage vector indexes for optimal performance in Agent-Vault's PostgreSQL backend.

## Overview

Agent-Vault supports three vector index types for semantic search:

| Index Type | Best For | Pros | Cons |
|------------|---------|------|------|
| **HNSW** (Default) | Most use cases | Better recall, no tuning needed, scales well | Slightly larger memory footprint |
| **IVF-Flat** | Very large datasets (>10M vectors) | Lower memory, faster bulk inserts | Requires tuning, lower recall |
| **ScaNN** (AlloyDB) | Large-scale filtered search | 10x faster filtered, 4x smaller memory, 10x faster build | AlloyDB only |
| **None** | Development/small datasets (<1k rows) | No index overhead | Slower queries |

## Quick Start

### New Deployments (Default: HNSW)

New deployments automatically use HNSW indexes with sensible defaults:

```python
from agent_vault.storage.config import BackendConfig

# Default configuration (HNSW with m=16, ef_construction=64)
config = BackendConfig(
    type="cloudsql",
    project="my-project",
    region="us-central1",
    instance="my-instance",
    database="agent-vault"
    # index_type="hnsw" is the default
)
```

### Existing Deployments

Existing deployments with IVF-Flat indexes continue to work unchanged. To migrate to HNSW:

```bash
agv index migrate --project my-project --index-type hnsw
```

See [Migration Guide](#migrating-indexes) below.

## Index Type Selection Guide

### When to Use HNSW (Recommended)

HNSW (Hierarchical Navigable Small World) is the default and recommended choice for most deployments:

**Use HNSW when:**
- Starting a new deployment
- Dataset size: 1k to 10M+ vectors
- You want better recall without tuning
- You have sufficient memory (8GB+ recommended)

**Advantages:**
- Better recall (>95% typical)
- No parameter tuning needed
- Scales to millions of vectors
- Production-ready in pgvector

**Default Parameters:**
```python
BackendConfig(
    index_type="hnsw",
    index_params={
        "m": 16,                # Connections per layer (higher = better recall, more memory)
        "ef_construction": 64   # Build-time search width (higher = better quality, slower build)
    }
)
```

### When to Use IVF-Flat

IVF-Flat (Inverted File with Flat Storage) is suited for very large datasets or memory-constrained environments:

**Use IVF-Flat when:**
- Dataset size: >10M vectors
- Memory is limited (<8GB)
- Bulk insert performance is critical
- Lower recall (90-95%) is acceptable

**Advantages:**
- Lower memory footprint
- Faster bulk inserts
- Proven at massive scale

**Configuration with Auto-Tuning:**
```python
BackendConfig(
    index_type="ivfflat",
    expected_rows=1_000_000  # Auto-calculates lists parameter
)
```

**Configuration with Explicit Override:**
```python
BackendConfig(
    index_type="ivfflat",
    index_params={
        "lists": 1000  # Explicit lists parameter (overrides calculation)
    }
)
```

### When to Use ScaNN (AlloyDB Only)

ScaNN (Scalable Approximate Nearest Neighbors) is Google's production-grade vector index, available exclusively on AlloyDB via the `ivf` access method.

**Use ScaNN when:**
- Running on AlloyDB (not available on standard PostgreSQL or CloudSQL)
- Dataset size: >1M vectors
- Heavy use of metadata filtering in queries
- Memory constraints or cost optimization needed

**Advantages:**
- **10x faster filtered search** - Superior performance with metadata predicates
- **4x smaller memory footprint** - Reduced memory usage vs HNSW
- **10x faster index build** - Significantly faster reindexing
- **Production-proven** - Powers Google-scale workloads

**Configuration:**
```sql
-- Create ScaNN index on chunks table
CREATE INDEX idx_chunks_embedding ON agv_v_chunks
USING ivf (embedding vector_cosine_ops)
WITH (num_neighbors = 16);

-- Create ScaNN index on entities table
CREATE INDEX idx_entities_embedding ON agv_v_entities
USING ivf (embedding vector_cosine_ops)
WITH (num_neighbors = 16);
```

**Parameter Tuning:**
- `num_neighbors`: Number of nearest centroids to search (default: 16)
  - Lower (4-8): Faster search, lower recall
  - Default (16): Balanced performance
  - Higher (32-64): Better recall, slower search

**Performance (AlloyDB, 525K chunks production benchmark):**
- **Search:** p50 10ms, p99 30ms (vs HNSW p50 15ms, p99 45ms)
- **Build:** ~3 minutes (vs HNSW ~8 minutes)
- **Memory:** ~1.5 GB (vs HNSW ~6 GB)

### When to Disable Indexing

For development or very small datasets:

```python
BackendConfig(
    index_type="none"  # No index, full table scan
)
```

**Use when:**
- Dataset size: <1k rows
- Development/testing
- Index is being rebuilt

## IVF-Flat Parameter Tuning

### Automatic Lists Calculation

Agent-Vault automatically calculates the optimal `lists` parameter using:

```
lists = max(1, min(floor(sqrt(expected_rows)), 10000))
```

| Expected Rows | Calculated Lists | Rationale |
|---------------|------------------|-----------|
| 1,000 | 31 | Small dataset |
| 10,000 | 100 | Default sweet spot |
| 100,000 | 316 | Medium scale |
| 1,000,000 | 1,000 | Large scale |
| 100,000,000 | 10,000 (capped) | PostgreSQL practical limit |

### Configuration Options

**Option 1: Specify Expected Size (Recommended)**
```python
BackendConfig(
    index_type="ivfflat",
    expected_rows=500_000  # Lists auto-calculated to ~707
)
```

**Option 2: Query Current Table Size**
```python
# If expected_rows not provided, queries actual row count
BackendConfig(
    index_type="ivfflat"
    # Lists calculated from SELECT COUNT(*) at startup
)
```

**Option 3: Explicit Override**
```python
BackendConfig(
    index_type="ivfflat",
    index_params={"lists": 500}  # Explicit value
)
```

### Validation Rules

The `lists` parameter is validated at configuration time:

- **Minimum:** 1
- **Maximum:** 10,000 (PostgreSQL practical limit)
- **Out of range:** Raises `ConfigurationError`
- **Negative expected_rows:** Raises `ConfigurationError`

## HNSW Parameter Tuning

### Parameter Reference

```python
BackendConfig(
    index_type="hnsw",
    index_params={
        "m": 16,                # Default: 16, Range: 4-64
        "ef_construction": 64   # Default: 64, Range: 16-512
    }
)
```

### Parameter Guidelines

**`m` (connections per layer):**
- **Lower (4-8):** Faster build, lower memory, lower recall
- **Default (16):** Balanced performance
- **Higher (32-64):** Better recall, higher memory

**`ef_construction` (build-time search width):**
- **Lower (16-32):** Faster build, lower quality
- **Default (64):** Balanced quality
- **Higher (128-512):** Better quality, slower build

### Typical Configurations

**Fast Build (Development):**
```python
index_params={"m": 8, "ef_construction": 32}
```

**Balanced (Production Default):**
```python
index_params={"m": 16, "ef_construction": 64}
```

**High Recall (Production Critical):**
```python
index_params={"m": 32, "ef_construction": 128}
```

## Migrating Indexes

### Migration Process

Agent-Vault provides a CLI command for safe index migration:

```bash
# Dry-run (shows plan without making changes)
agv index migrate --project my-project --index-type hnsw --dry-run

# Actual migration
agv index migrate --project my-project --index-type hnsw
```

**Migration Steps:**
1. Validates configuration
2. Creates new index with `CONCURRENTLY` (no table lock)
3. Drops old index
4. Renames new index to standard name
5. Returns statistics (duration, rows indexed)

### Migration Examples

**IVF-Flat → HNSW:**
```bash
agv index migrate --project my-project --index-type hnsw
```

**HNSW → IVF-Flat (with auto-tuning):**
```bash
agv index migrate --project my-project --index-type ivfflat --expected-rows 1000000
```

**HNSW → HNSW (parameter change):**
```bash
agv index migrate --project my-project \
    --index-type hnsw \
    --index-params '{"m": 32, "ef_construction": 128}'
```

### Migration Considerations

**Downtime:**
- **Zero downtime:** `CONCURRENTLY` option allows queries during rebuild
- **Table readable:** No locks during index creation
- **Table writable:** Writes continue normally

**Duration Estimates (Cloud SQL db-standard-4):**

| Row Count | HNSW Build | IVF-Flat Build |
|-----------|------------|----------------|
| 10,000 | ~5 seconds | ~2 seconds |
| 100,000 | ~45 seconds | ~15 seconds |
| 1,000,000 | ~8 minutes | ~2 minutes |
| 10,000,000 | ~90 minutes | ~20 minutes |

**Disk Space:**
- Requires temporary space for new index
- Peak usage: old_index + new_index
- Released after old index dropped

### Transaction Limitations

Index rebuild **cannot** run inside a transaction:

```python
# This will raise IndexRebuildError
async with storage_facade.transaction():
    await maintenance_service.rebuild_index(...)  # ERROR
```

**Correct usage:**
```python
# Run outside transaction context
await maintenance_service.rebuild_index(...)  # OK
```

## Performance Benchmarks

### Query Performance (Cloud SQL db-standard-4)

| Dataset Size | Index Type | p50 Latency | p99 Latency | Recall |
|--------------|------------|-------------|-------------|--------|
| 10k chunks | HNSW | 8ms | 25ms | 98% |
| 10k chunks | IVF-Flat | 12ms | 35ms | 92% |
| 100k chunks | HNSW | 15ms | 45ms | 97% |
| 100k chunks | IVF-Flat | 25ms | 70ms | 91% |
| 1M chunks | HNSW | 35ms | 85ms | 96% |
| 1M chunks | IVF-Flat | 55ms | 150ms | 89% |

### Build Performance

| Dataset Size | HNSW Build | IVF-Flat Build | Winner |
|--------------|------------|----------------|--------|
| 10k | 5s | 2s | IVF-Flat |
| 100k | 45s | 15s | IVF-Flat |
| 1M | 8m | 2m | IVF-Flat |

### Memory Usage (Approximate)

| Dataset Size | HNSW (m=16) | IVF-Flat (lists=100) |
|--------------|-------------|----------------------|
| 100k vectors | ~400 MB | ~200 MB |
| 1M vectors | ~4 GB | ~2 GB |
| 10M vectors | ~40 GB | ~20 GB |

## Best Practices

### Development Environments

```python
BackendConfig(
    index_type="none",  # Skip indexing for fast iteration
    # Or use HNSW with fast params
    index_type="hnsw",
    index_params={"m": 8, "ef_construction": 32}
)
```

### Staging Environments

```python
BackendConfig(
    index_type="hnsw",  # Production-like config
    index_params={"m": 16, "ef_construction": 64}
)
```

### Production Environments

**Default (Recommended):**
```python
BackendConfig(
    index_type="hnsw",  # Best recall, no tuning
    # Use defaults: m=16, ef_construction=64
)
```

**High-Scale (>10M vectors):**
```python
BackendConfig(
    index_type="ivfflat",
    expected_rows=50_000_000  # Auto-calculates lists=7071
)
```

### Monitoring Index Health

```python
from agent_vault.storage import create_storage_facade

storage = create_storage_facade(config)
status = await storage.get_maintenance_status()

print(f"Index type: {status.index_type}")
print(f"Index size: {status.index_size_mb} MB")
print(f"Fragmentation: {status.fragmentation_pct}%")
```

### Scheduled Maintenance

Run periodic reindexing during low-traffic windows:

```bash
# Weekly reindex (retrain IVF-Flat with current data)
0 2 * * 0 agv maintenance run --operation reindex --project my-project
```

## Troubleshooting

### Slow Query Performance

**Symptom:** Queries taking >100ms at p99

**Diagnosis:**
```python
status = await storage.get_maintenance_status()
if status.fragmentation_pct > 20:
    print("Index fragmentation detected")
```

**Solution:**
```bash
# Rebuild index to defragment
agv index migrate --project my-project --index-type hnsw
```

### High Memory Usage

**Symptom:** PostgreSQL OOM errors or high memory pressure

**Diagnosis:**
- HNSW with high `m` parameter
- Dataset larger than expected

**Solution 1 (Reduce HNSW parameters):**
```bash
agv index migrate --project my-project \
    --index-type hnsw \
    --index-params '{"m": 8, "ef_construction": 32}'
```

**Solution 2 (Switch to IVF-Flat):**
```bash
agv index migrate --project my-project --index-type ivfflat
```

### Index Build Failures

**Symptom:** Migration times out or fails

**Common Causes:**
1. Instance too small (upgrade to db-standard-4+)
2. Disk space exhausted (need space for old + new index)
3. Lock conflicts (ensure migration runs outside transactions)

**Solution:**
```bash
# Check disk space
gcloud sql instances describe my-instance | grep dataDiskSizeGb

# Upgrade instance if needed
gcloud sql instances patch my-instance --tier db-standard-8
```

## Configuration Reference

### BackendConfig Index Fields

```python
@dataclass
class BackendConfig:
    # Index configuration
    index_type: Literal["hnsw", "ivfflat", "none"] = "hnsw"
    index_params: dict | None = None
    expected_rows: int | None = None
```

### Index Parameters

**HNSW:**
```python
index_params = {
    "m": int,                # 4-64, default 16
    "ef_construction": int   # 16-512, default 64
}
```

**IVF-Flat:**
```python
index_params = {
    "lists": int  # 1-10000, or omit for auto-calculation
}
```

## Related Documentation

- [Schema Migration Guide](schema-migration.md) - Handling dimension changes
- [Maintenance Operations](maintenance.md) - Scheduled operations and VACUUM
- [Cloud SQL Backend](../backends/cloudsql.md) - Cloud SQL configuration and setup

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-13 | Initial release with HNSW default and IVF-Flat tuning |
