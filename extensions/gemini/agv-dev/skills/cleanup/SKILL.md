---
name: cleanup
description: Repository cleanup recommendations - stale files, dead code, agent artifacts, and hygiene.
---

# Repository Cleanup

Identify outdated, stale, or unnecessary files to keep the repository healthy.

## When to Use

- Monthly maintenance
- Before major releases
- When repo feels cluttered

## Cleanup Categories

### 1. Stale `.tmp_scripts/`

```bash
# Find scripts older than 30 days
find .tmp_scripts -name "*.py" -mtime +30

# Count tmp_scripts
find .tmp_scripts -name "*.py" | wc -l
```

**Criteria:**
- Age > 30 days → candidate for removal
- No references in tests/docs → delete
- Still valid and useful → promote to `tests/` or `examples/`

### 2. Agent Artifacts

Common patterns from AI agents:
- Timestamped files: `debug_xyz_20251215.py`
- Debug prefixes: `debug_`, `investigate_`, `check_`
- Versioned files: `test_v2.py`, `test_v3.py`, `test_final.py`
- Validation reports: `*_validation_report.md`

```bash
# Find timestamped files
find .tmp_scripts -name "*_2025*.py" -o -name "*_2024*.py"

# Find versioned files
find .tmp_scripts -name "*_v[0-9].py"
```

**Strategy:** Keep latest version, delete earlier versions.

### 3. Orphaned Files

```bash
# Backup files (use git instead)
find . -name "*.bak" -o -name "*.backup" -o -name "*~"

# OS artifacts
find . -name ".DS_Store"

# Log files in repo
find . -name "*.log" -not -path "./.git/*"
```

### 4. Dead Code

```bash
# Find possibly unused modules
for f in agent_vault/**/*.py; do
  module=$(echo $f | sed 's/\.py$//' | tr '/' '.')
  grep -rq "$module" agent_vault/ tests/ || echo "POSSIBLY UNUSED: $f"
done

# Find TODO/remove markers
grep -rn "TODO.*remove\|DEPRECATED" --include="*.py"
```

### 5. Test Duplication

```bash
# Find versioned test files
find tests/ -name "*_v[0-9].py" -o -name "*_final.py"

# Find duplicate test functions
grep -rh "^def test_" tests/ | sort | uniq -d
```

### 6. Configuration Sprawl

```bash
# List all config files
find . -maxdepth 2 -name "*.yaml" -o -name "*.yml" -o -name "*.toml"

# Check for unused config options
grep -rh "^[a-z_]*:" config/default.yaml | while read key; do
  grep -rq "${key%%:*}" agent_vault/ || echo "UNUSED: $key"
done
```

### 7. Memory/Cache Data

```bash
# Check data directory sizes
du -sh .agv/ .serena/ .hypothesis/ 2>/dev/null

# Find old logs
find .agv/logs -name "*.log" -mtime +30 2>/dev/null
```

### 8. Commit Hygiene

```bash
# Uncommitted changes
git status --short

# Sessions without summary
for session in .sessions/*/; do
  [ ! -f "$session/SESSION_SUMMARY.md" ] && echo "NO SUMMARY: $(basename $session)"
done
```

## Safe Automated Cleanup

```bash
# Run weekly - safe deletions
find . -name "*.bak" -o -name "*.backup" -o -name "*~" -delete
find . -name ".DS_Store" -delete
find .tmp_scripts -name "*.py" -mtime +60 -delete
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
```

## Manual Review Required

These need human judgment:
1. Specs in `.kiro/specs/` - archive completed, delete abandoned
2. Sessions in `.sessions/` - archive old completed sessions
3. Tests - consolidate duplicates
4. Documentation - update outdated examples
