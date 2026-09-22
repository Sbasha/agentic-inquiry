# Requests For Comments

> Proposals for change. See
> [`../CONVENTIONS.md`](../CONVENTIONS.md#3-rfc--request-for-comments--docsrfc)
> for when to open an RFC vs. an ADR vs. opening a PR.

| # | Title | Status |
|---|-------|--------|
| [0001](0001-golden-bench.md) | Golden bench: pin recall@10 + latency | accepted |
| [0002](0002-aws-support.md) | AWS support (Bedrock + RDS / Aurora pgvector) | draft |
| [0003](0003-pluggable-embedding-providers.md) | Pluggable embedding providers (Amazon Titan v2 first) | draft |

## Adding a new RFC

```bash
# Find the next number (portable across macOS, Linux, native Windows).
N=$(python3 .claude/skills/new-rfc/scripts/next-ordinal.py docs/rfc)
cp .claude/skills/new-rfc/assets/rfc.md docs/rfc/${N}-<kebab-title>.md
```

On Windows, use `py -3` instead of `python3`.

Or, in Claude Code, run `/new-rfc "<title>"` (defined in `.claude/skills/new-rfc/SKILL.md`).
