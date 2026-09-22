# Maintenance Operations Guide

> Historical reference. This page describes PostgreSQL-family providers, cloud connectors or remote embedders that are not part of this local-only distribution. It is retained as design input for the external provider contract in [storage-backends.md](../storage-backends.md).

**Version:** 1.0
**Status:** Current
**Last Updated:** 2026-01-13

This guide explains how to perform routine maintenance operations on Agentic Inquiry's PostgreSQL backend for optimal performance and reliability.

## Overview

Regular maintenance is essential for:
- **Query performance** - Prevent index fragmentation
- **Storage efficiency** - Reclaim dead tuple space
- **Operational health** - Updated table statistics

### Maintenance Operations

| Operation | Purpose | Frequency | Downtime |
|-----------|---------|-----------|----------|
| **VACUUM** | Reclaim dead tuple space | Daily | None |
| **REINDEX** | Rebuild fragmented indexes | Weekly | None (CONCURRENTLY) |

## Quick Start

### Running Maintenance

**All operations (recommended):**
```bash
ai maintenance run --project my-project
```

**Specific operation:**
```bash
# VACUUM only
ai maintenance run --project my-project --operation vacuum

# Reindex only
ai maintenance run --project my-project --operation reindex
```

## VACUUM Operations

### What is VACUUM?

PostgreSQL VACUUM reclaims storage space from dead tuples created by updates and deletes. Without regular vacuuming:
- Dead tuples accumulate
- Table bloat increases
- Query performance degrades
- Disk space is wasted

### Running VACUUM

**Automatic (recommended):**
```bash
ai maintenance run --project my-project --operation vacuum
```

**Manual SQL:**
```sql
VACUUM ANALYZE ai_v_chunks;
VACUUM ANALYZE ai_g_entities;
VACUUM ANALYZE ai_g_relationships;
```

### VACUUM Modes

**VACUUM ANALYZE (default):**
```bash
ai maintenance run --project my-project --operation vacuum
```
- Reclaims space
- Updates table statistics
- No locks, queries continue
- Duration: 1-5 minutes for 1M rows

**VACUUM FULL (advanced):**
```sql
-- Only run during maintenance windows (requires table lock)
VACUUM FULL ai_v_chunks;
```
- Reclaims ALL space
- Rewrites entire table
- Requires exclusive lock
- Duration: 10-30 minutes for 1M rows

**When to use VACUUM FULL:**
- Table bloat >50%
- After massive deletes (>80% of rows)
- Before major version upgrade

## REINDEX Operations

### What is REINDEX?

Vector indexes (HNSW, IVF-Flat) can become fragmented over time:
- Frequent updates to embeddings
- Large batch operations
- Index growth from new data
- Suboptimal IVF-Flat lists after growth

### When to Reindex

**Recommended Frequency:**
- **HNSW:** Weekly (or when fragmentation >10%)
- **IVF-Flat:** Weekly (retrains clusters with current data)
- **After major updates:** When >20% of rows updated

**Signs You Need Reindex:**
- Query latency increased 2x
- p99 latency >100ms consistently
- Index fragmentation >15%
- After dimension migration

### Running REINDEX

**Standard reindex:**
```bash
ai maintenance run --project my-project --operation reindex
```

### REINDEX Strategies

**Concurrent (default, no downtime):**
```bash
ai maintenance run --project my-project --operation reindex
```
- Uses `CREATE INDEX CONCURRENTLY`
- No table locks
- Queries continue normally
- Takes longer than blocking reindex

**Blocking (faster, requires downtime):**
```sql
-- Only during maintenance windows
REINDEX INDEX ai_v_chunks_embedding_idx;
```
- Faster rebuild
- Requires exclusive lock
- Blocks queries during rebuild

## Scheduled Maintenance

### Recommended Schedule

**Production Environment:**
```bash
# Daily VACUUM (low traffic hours)
0 2 * * * ai maintenance run --project prod --operation vacuum

# Weekly REINDEX (weekend low traffic)
0 2 * * 0 ai maintenance run --project prod --operation reindex
```

**Development Environment:**
```bash
# Weekly all operations
0 2 * * 0 ai maintenance run --project dev
```

### Scheduling with Cron

**Linux/macOS crontab:**
```bash
# Edit crontab
crontab -e

# Add maintenance jobs
0 2 * * * cd /path/to/agentic-inquiry && \
    /path/to/.venv/bin/ai maintenance run --project prod --operation vacuum \
    >> /var/log/agentic-inquiry/maintenance.log 2>&1

0 2 * * 0 cd /path/to/agentic-inquiry && \
    /path/to/.venv/bin/ai maintenance run --project prod --operation reindex \
    >> /var/log/agentic-inquiry/maintenance.log 2>&1
```

**Testing cron jobs:**
```bash
# Run maintenance manually first
/path/to/.venv/bin/ai maintenance run --project prod --operation vacuum

# Check logs
tail -f /var/log/agentic-inquiry/maintenance.log
```

### Scheduling with Google Cloud Scheduler

**Create Cloud Scheduler job:**
```bash
# Daily VACUUM
gcloud scheduler jobs create http vacuum-maintenance \
    --schedule="0 2 * * *" \
    --uri="https://your-app.run.app/maintenance/vacuum" \
    --http-method=POST \
    --headers="Authorization=Bearer $(gcloud auth print-identity-token)"

# Weekly REINDEX
gcloud scheduler jobs create http reindex-maintenance \
    --schedule="0 2 * * 0" \
    --uri="https://your-app.run.app/maintenance/reindex" \
    --http-method=POST \
    --headers="Authorization=Bearer $(gcloud auth print-identity-token)"
```

**Or trigger via Pub/Sub:**
```bash
# Create topic
gcloud pubsub topics create agentic-inquiry-maintenance

# Create subscription that runs maintenance
gcloud scheduler jobs create pubsub vacuum-job \
    --schedule="0 2 * * *" \
    --topic=agentic-inquiry-maintenance \
    --message-body='{"operation": "vacuum", "project": "prod"}'
```

### Scheduling with systemd Timers

**Create service file:** `/etc/systemd/system/ai-maintenance.service`
```ini
[Unit]
Description=Agentic Inquiry Maintenance
After=network.target

[Service]
Type=oneshot
User=ai
WorkingDirectory=/opt/agentic-inquiry
ExecStart=/opt/agentic-inquiry/.venv/bin/ai maintenance run --project prod
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Create timer:** `/etc/systemd/system/ai-maintenance.timer`
```ini
[Unit]
Description=Agentic Inquiry Daily Maintenance
Requires=ai-maintenance.service

[Timer]
OnCalendar=daily
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-maintenance.timer
sudo systemctl start ai-maintenance.timer

# Check status
sudo systemctl list-timers ai-maintenance.timer
```

## Monitoring and Alerts

### Key Metrics to Monitor

**Table Health:**
```sql
-- Dead tuple ratio (alert if >5%)
SELECT
    relname,
    n_dead_tup,
    n_live_tup,
    ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup, 0), 2) AS dead_pct
FROM pg_stat_user_tables
WHERE relname LIKE 'ai_%'
ORDER BY dead_pct DESC;
```

**Index Health:**
```sql
-- Index bloat (alert if >20%)
SELECT
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
    AND tablename LIKE 'ai_%'
ORDER BY pg_relation_size(indexrelid) DESC;
```

**Last Maintenance:**
```sql
-- Last VACUUM/ANALYZE
SELECT
    relname,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze
FROM pg_stat_user_tables
WHERE relname LIKE 'ai_%';
```

### Alerting Thresholds

**Critical Alerts:**
```bash
# Dead tuple ratio >10%
# Index fragmentation >20%
# No VACUUM in 48 hours
# REINDEX failed
```

**Warning Alerts:**
```bash
# Dead tuple ratio >5%
# Index fragmentation >10%
# No VACUUM in 24 hours
# No REINDEX in 7 days
```

### Prometheus Metrics

**Export metrics for monitoring:**
```python
from prometheus_client import Gauge, Counter

# Table metrics
dead_tuples = Gauge('ai_dead_tuples_total', 'Dead tuples per table', ['table'])
table_size = Gauge('ai_table_size_bytes', 'Table size in bytes', ['table'])

# Maintenance metrics
maintenance_duration = Gauge('ai_maintenance_duration_seconds', 'Maintenance duration', ['operation'])
maintenance_runs = Counter('ai_maintenance_runs_total', 'Maintenance runs', ['operation', 'status'])

# Update metrics
status = await storage.get_maintenance_status()
dead_tuples.labels(table='chunks').set(status.dead_tuples)
table_size.labels(table='chunks').set(status.table_size_bytes)
```

## Performance Impact

### VACUUM Performance

**Resource Usage:**
- CPU: Low (5-10% during operation)
- Memory: Moderate (work_mem per table)
- I/O: Moderate (sequential reads/writes)
- Locks: None (concurrent operations allowed)

**Duration Estimates:**

| Table Size | Row Count | Typical Duration |
|------------|-----------|------------------|
| 100 MB | 10k | 5-10 seconds |
| 1 GB | 100k | 30-60 seconds |
| 10 GB | 1M | 3-5 minutes |
| 100 GB | 10M | 20-40 minutes |

### REINDEX Performance

**Resource Usage:**
- CPU: High (50-80% during operation)
- Memory: High (entire index built in memory)
- I/O: Very High (index rebuild)
- Locks: None (CONCURRENTLY mode)

**Duration Estimates (HNSW):**

| Row Count | Index Size | Duration |
|-----------|------------|----------|
| 10k | 40 MB | 30 seconds |
| 100k | 400 MB | 5 minutes |
| 1M | 4 GB | 45 minutes |
| 10M | 40 GB | 6-8 hours |

**Duration Estimates (IVF-Flat):**

| Row Count | Index Size | Duration |
|-----------|------------|----------|
| 10k | 20 MB | 10 seconds |
| 100k | 200 MB | 2 minutes |
| 1M | 2 GB | 15 minutes |
| 10M | 20 GB | 2-3 hours |

### Optimization Tips

**Speed up VACUUM:**
```sql
-- Increase maintenance_work_mem (per session)
SET maintenance_work_mem = '1GB';
VACUUM ANALYZE ai_v_chunks;
```

**Speed up REINDEX:**
```sql
-- Increase max_parallel_maintenance_workers
SET max_parallel_maintenance_workers = 4;
REINDEX INDEX CONCURRENTLY ai_v_chunks_embedding_idx;
```

**Reduce I/O impact:**
```bash
# Use ionice on Linux
ionice -c 3 ai maintenance run --project prod --operation reindex
```

## Troubleshooting

### VACUUM Issues

**Issue: VACUUM not reclaiming space**

**Symptoms:**
- Dead tuples remain after VACUUM
- Table size doesn't decrease

**Causes:**
1. Long-running transactions blocking cleanup
2. Replication slots preventing cleanup
3. Table bloat >50% (needs VACUUM FULL)

**Solution:**
```sql
-- Check for blocking transactions
SELECT pid, age(clock_timestamp(), query_start), usename, query
FROM pg_stat_activity
WHERE state != 'idle' AND query NOT ILIKE '%pg_stat_activity%'
ORDER BY query_start;

-- Kill blocking transaction
SELECT pg_terminate_backend(PID);

-- Check replication slots
SELECT slot_name, active, restart_lsn FROM pg_replication_slots;

-- If bloat >50%, run VACUUM FULL during maintenance window
VACUUM FULL ai_v_chunks;
```

### REINDEX Issues

**Issue: REINDEX fails with "out of memory"**

**Symptoms:**
- PostgreSQL crashes during REINDEX
- Error: "out of memory"

**Solution:**
```bash
# Increase instance memory (Cloud SQL)
gcloud sql instances patch my-instance --tier db-standard-8

# Or increase maintenance_work_mem
psql -c "ALTER SYSTEM SET maintenance_work_mem = '2GB';"
psql -c "SELECT pg_reload_conf();"
```

**Issue: REINDEX takes too long**

**Symptoms:**
- REINDEX running >12 hours
- High CPU usage

**Solution:**
```bash
# Check progress (PostgreSQL 12+)
SELECT
    phase,
    blocks_done,
    blocks_total,
    tuples_done,
    tuples_total
FROM pg_stat_progress_create_index;

# If stuck, cancel and retry during low-traffic window
SELECT pg_cancel_backend(PID);
```

## Configuration Reference

### CLI Command Reference

**Run maintenance:**
```bash
ai maintenance run [OPTIONS]

Options:
  --project, -p TEXT         Project ID for table prefix (overrides config)
  --operation, -o TEXT       Operation: vacuum, reindex, all [default: all]
  --config, -c PATH          Path to storage configuration file
```

## Best Practices

### Daily Operations

1. **Monitor dead tuple ratio** - Alert if >5%
2. **Check last VACUUM time** - Alert if >24 hours
3. **Review error logs** - Check for maintenance failures
4. **Monitor disk space** - Ensure space for reindex

### Weekly Operations

1. **Run REINDEX** - Rebuild vector indexes
2. **Analyze query performance** - Compare to baseline
3. **Review storage growth** - Plan capacity as needed

### Monthly Operations

1. **Review maintenance schedule** - Adjust based on growth
2. **Capacity planning** - Project storage needs
3. **Performance baseline** - Update expected metrics
4. **Test restore procedures** - Verify backups work

## Related Documentation

- [Index Configuration Guide](index-configuration.md) - Index types and tuning
- [Schema Migration Guide](schema-migration.md) - Handling schema changes
- [Cloud SQL Backend](../backends/cloudsql.md) - Cloud SQL configuration and setup

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-13 | Initial release with VACUUM and REINDEX operations |
