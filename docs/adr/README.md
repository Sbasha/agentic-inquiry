# Architecture Decision Records

Lifecycle, filenames, status values, and "when to write an ADR" rules
live in [`../CONVENTIONS.md § 2`](../CONVENTIONS.md#2-adr--architecture-decision-records--docsadr).

**Template:** [`../_templates/adr.md`](../_templates/adr.md). Run the
[`new-adr`](../../.claude/skills/new-adr/SKILL.md) skill to scaffold one.

## Numbering

Filenames use the 4-digit form `NNNN-kebab-title.md`; new ADRs follow
the same shape. ADRs 0001–0003 predate the convention, so their bodies
still title themselves `ADR-001` / `ADR-002` / `ADR-003` and
cross-reference each other in the 3-digit form — treat those bare
labels as equivalent to `ADR-0001` etc. for the purpose of citations
from new ADRs or RFCs.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-protocol-based-storage.md) | Protocol-based storage architecture | Accepted |
| [0002](0002-storage-facade-pattern.md) | StorageFacade as unified entry point | Accepted |
| [0003](0003-filter-ast-consolidation.md) | Filter AST replacing FilterBuilder | Accepted |
| [0004](0004-agent-vault-base-as-product-lineage.md) | Product lineage: the Agent Vault base over the 0.1.0 preview | Accepted |
| [0005](0005-afp-lifecycle-contract-public-surface.md) | Host integration: a stdlib-only CLI lifecycle contract over plugin-embedded logic | Accepted |

(The `new-adr` skill appends new rows to this table; keep the header
above intact.)
