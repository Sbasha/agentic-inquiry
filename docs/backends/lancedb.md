# LanceDB Backend

---
name: LanceDB
description: Local embedded vector database with zero configuration
type: lancedb
requires_setup: false
mcp_server: agv-test
config_file: config/test-lancedb.yaml
data_directory: .agv/test/
port: null

maintenance:
  enabled: true
  command: run_maintenance
  threshold_gb: 5
  aggressive_threshold_gb: 15

setup:
  steps: []
  duration_minutes: 0

teardown:
  steps:
    - description: Remove test data directory
      command: rm -rf .agv/test/
  cleanup_files:
    - .agv/test/
---

## Overview

LanceDB is a modern, embedded vector database designed for AI applications. It requires no external services and stores data locally, making it ideal for development and testing.

## When to Use

- **Development**: Fast iteration without infrastructure setup
- **Testing**: Quick test runs without external dependencies
- **CI/CD**: Automated testing pipelines
- **Offline**: No network connectivity required

## Setup

No setup required. LanceDB initializes automatically on first use.

```bash
# Verify config exists
cat config/test-lancedb.yaml
```

## Configuration

Standard test configuration is at `config/test-lancedb.yaml`:

```yaml
storage:
  root: ".agv/test/"
  backends:
    default:
      type: lancedb
      uri: "${storage.root}/lancedb"
  vector_backend: default
  graph_backend: default
```

## Running Tests

```bash
# Set config path
export agv_CONFIG_PATH=config/test-lancedb.yaml

# Run tests using the agv-test MCP server
# (MCP tools will use local LanceDB automatically)
```

## Maintenance

LanceDB requires periodic maintenance to compact data and reclaim disk space. This is critical during extended test sessions.

### Monitoring Disk Usage

```bash
# Check data directory size
du -sh .agv/test/

# Check available disk space
df -h .
```

### Resource Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Data Directory | >5GB | >15GB | Run maintenance |
| Disk Space | <15GB free | <5GB free | Stop tests, run maintenance |
| Entities/Test | >10,000 | >25,000 | Split into smaller scope |

### Running Maintenance

Use the CLI maintenance command:

```bash
# Run all maintenance operations
agv maintenance run --operation all

# With custom config file
agv maintenance run --config config/test-lancedb.yaml --operation all
```

Or manually compact:

```bash
# Remove stale data files
find .agv/test/ -name "*.tmp" -delete
find .agv/test/ -name "*.lock" -mmin +60 -delete
```

### When to Run Maintenance

1. **Before each test batch**: If data directory >5GB
2. **After each test**: Compact to prevent accumulation
3. **Before test session**: Clean slate for accurate metrics
4. **Emergency**: If disk space drops below 10GB

## Teardown

Remove all test data:

```bash
# Remove test data directory
rm -rf .agv/test/

# Verify cleanup
ls -la .agv/test/ 2>/dev/null || echo "Clean"
```

## Troubleshooting

### Data Directory Not Cleaned

If tests fail to clean up:

```bash
# Force remove with sudo if permissions issue
sudo rm -rf .agv/test/

# Or check for processes holding files
lsof +D .agv/test/
```

### Disk Space Issues

If disk space is exhausted:

1. Stop all tests immediately
2. Run aggressive cleanup:
   ```bash
   rm -rf .agv/test/
   ```
3. Free up system disk space if needed
4. Restart with smaller test scope

### Corrupted Data

If LanceDB reports corruption:

```bash
# Remove and recreate
rm -rf .agv/test/
# Data will be recreated on next test run
```

## Performance Characteristics

| Operation | Typical Latency | Notes |
|-----------|-----------------|-------|
| Startup | <1 second | No connection overhead |
| Indexing | ~100 files/sec | Depends on file size |
| Search | <100ms | Local disk access |
| Maintenance | 1-5 minutes | Depends on data size |

## Limitations

- **Single process**: No concurrent access from multiple processes
- **Local only**: Data not shared across machines
- **No replication**: Not suitable for production deployments
- **Memory usage**: Large datasets may require more RAM
