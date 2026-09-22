---
name: commit
description: Agentic Inquiry commit requirements - pre-commit checks, documentation, session tracking.
---

# ai Commit Requirements

Standards for committing changes to Agentic Inquiry.

## When to Use

- Before committing any change
- Setting up session documentation
- Reviewing commit readiness

## Pre-Commit Checklist

Run these before every commit:

```bash
# Required checks
uv run ruff check .                    # Linting
uv run ruff format . --check           # Formatting
uv run mypy agentic_inquiry/              # Type checking
uv run --env-file .env pytest          # Tests

# If parsers modified
uv run --env-file .env pytest tests/parsers/test_parser_examples.py
```

## Documentation Review

Evaluate for every change:

- [ ] New public APIs have docstrings (params, returns, raises)
- [ ] Changed behavior reflected in `docs/`
- [ ] New/changed config options documented in `docs/storage/index-configuration.md`
- [ ] README updated if setup/install/usage changed
- [ ] Breaking changes noted with migration guidance

## Session Documentation

**Structure:** `.sessions/{session_name}/`

```
.sessions/
└── parser-refactor/           # Session = body of work
    ├── 001-fix-metadata.md    # Turn 1
    ├── 002-add-validation.md  # Turn 2
    └── SESSION_SUMMARY.md     # All commit hashes
```

### Per-Turn File (Required)

Each turn file must include:
- Objective and approach
- Decisions made
- Changes and files modified
- Test results
- Commit hash (after committing)
- Outcome: `completed`, `in-progress`, or `blocked`

### Session Summary (Required)

- All turns with commit hashes
- Overall outcome and open items

## Commit Rules

1. **Every completed turn MUST be committed**
2. Clear, descriptive commit messages
3. Record commit hash in turn file immediately after commit
4. Only exception: broken/incomplete functionality — document why

## Commit Message Format

```
type(scope): brief description

- Detail 1
- Detail 2

Co-Authored-By: Claude <noreply@anthropic.com>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`
