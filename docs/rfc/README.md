# Requests For Comments

> Proposals for change. See
> [`../CONVENTIONS.md`](../CONVENTIONS.md#3-rfc--request-for-comments--docsrfc)
> for when to open an RFC vs. an ADR vs. opening a PR.

| # | Title | Status |
|---|-------|--------|
| [0001](0001-golden-bench.md) | Golden bench: pin recall@10 + latency | accepted |
| [0002](0002-afp-lifecycle-contract.md) | AFP lifecycle contract: capabilities, integration hook, mcp | accepted |
| [0003](0003-knowledge-architecture.md) | Knowledge architecture: governed libraries, project stores and memory | accepted (0004, draft, proposes superseding D1's memory tier, D3, D5 and D4's first arrow for this runtime, and reversing D6) |
| [0004](0004-unified-project-runtime.md) | Unified project runtime | draft |

## Adding a new RFC

```bash
# Find the next number (portable across macOS, Linux, native Windows).
N=$(python3 .claude/skills/new-rfc/scripts/next-ordinal.py docs/rfc)
cp .claude/skills/new-rfc/assets/rfc.md docs/rfc/${N}-<kebab-title>.md
```

On Windows, use `py -3` instead of `python3`.

Or, in Claude Code, run `/new-rfc "<title>"` (defined in `.claude/skills/new-rfc/SKILL.md`).
