---
name: sync-agents
description: Synchronize AGENTS.md with agv-dev skills to keep documentation lean. Use when skills have changed and AGENTS.md needs updating.
disable-model-invocation: true
allowed-tools: Bash, Read, Write
---

# /agv-dev:sync-agents

Update AGENTS.md to reference skills instead of duplicating content.

## Process

1. **Scan agv-dev skills** for current coverage:
   - `coding-guidelines` - Code standards
   - `testing` - Test commands and patterns
   - `quality` - Quality checklists
   - `extending` - How to extend agv
   - `plugins` - CLI integrations
   - `commit` - Commit requirements

2. **Scan agv skills** for user-facing workflows

3. **Update AGENTS.md** to:
   - Keep essential quick-reference content
   - Replace detailed sections with skill references
   - Add skill invocation examples

## Target Format

```markdown
## [Section Name]

For detailed guidance, invoke the skill:
- `/agv-dev:skill-name` - Brief description

Quick reference: [1-2 key points only]
```

## Skill Reference

| Topic | Skill | Invoke |
|-------|-------|--------|
| Coding standards | coding-guidelines | `/agv-dev:coding-guidelines` |
| Testing | testing | `/agv-dev:testing` |
| Quality | quality | `/agv-dev:quality` |
| Extending agv | extending | `/agv-dev:extending` |
| CLI plugins | plugins | `/agv-dev:plugins` |
| Commits | commit | `/agv-dev:commit` |

## Output

After sync:
- AGENTS.md should be under 500 lines
- All detailed content lives in skills
- Quick reference sections remain for common operations
