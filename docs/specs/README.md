# Feature specs

Per-feature directories under this folder pair `spec.md` (the contract)
with `plan.md` (the work-breakdown):

```
docs/specs/<feature>/
├── spec.md      ← contract + contract tests
├── plan.md      ← strategy + construction tests, broken into tasks
└── notes/       ← (optional) research, sketches, rejected approaches
```

Conventions, lifecycle, and the contract-vs-construction test split
live in [`../CONVENTIONS.md § 4`](../CONVENTIONS.md#4-specs-and-plans--docsspecsfeature).

**Templates:** [`../_templates/spec.md`](../_templates/spec.md),
[`../_templates/plan.md`](../_templates/plan.md). Run the
[`new-spec`](../../.claude/skills/new-spec/SKILL.md) skill to scaffold a
feature directory.

**Session-scratch state.** `state.json` and `notes/implementer-*.md`
files inside any feature dir are gitignored — see
[`../CONVENTIONS.md § Work-loop state`](../CONVENTIONS.md#work-loop-state).

[`index-memory-reliability`](index-memory-reliability/spec.md) - Graph-relationship merge honesty, memory-save verify-on-write, Darwin CPU-hatch hint.

[`first-run-reliability`](first-run-reliability/spec.md) - First-run onboard gate, index exit codes, LanceDB retry, env-file bootstrap.

[`salesforce-apex-parsing`](salesforce-apex-parsing/spec.md) - Apex class and trigger extraction.

[`salesforce-intelligence`](salesforce-intelligence/spec.md) - Salesforce recognizer and metadata allowlist.
