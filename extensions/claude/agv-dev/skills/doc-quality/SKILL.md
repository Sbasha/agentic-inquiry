---
name: doc-quality
description: Documentation quality review - staleness, accuracy, navigation, and developer experience. Auto-loads when reviewing or writing documentation.
user-invocable: false
---

# Documentation Quality Review

Ensure documentation enables developers to install, run, modify, and debug quickly.

## When to Use

- Reviewing documentation PRs
- Auditing doc freshness
- Improving developer onboarding

## Core Test

**Can a new developer go from clone to running to first meaningful change in under an hour?**

## Anti-Pattern Categories

### Category 1: Staleness & Drift

| Pattern | Detection |
|---------|-----------|
| Dead code examples | Run every example - if it errors, it's broken |
| Ghost configuration | Grep codebase for every documented env var |
| Phantom files/paths | Verify every referenced path exists |
| Version rot | Cross-reference with pyproject.toml/requirements |
| TODO graveyard | Search for TODO, FIXME, WIP, TBD |

### Category 2: Installation Purgatory

| Pattern | Problem |
|---------|---------|
| Assumed prerequisites | Missing: Python version, system deps, platform notes |
| Missing env setup | .env.example with 47 vars, no indication which are required |
| No verification step | "You're all set!" isn't a verification |
| Command sequence gaps | Missing: migrations, seed data, building assets |
| Platform blindness | Mac-only instructions (60% of devs aren't on Mac) |

### Category 3: The "What" Without the "How"

| Pattern | Problem |
|---------|---------|
| Architecture without application | Describes system, doesn't explain how to work in it |
| API reference without examples | No request/response examples |
| Config docs without context | No defaults, ranges, or consequences |

### Category 4: Contribution Void

| Pattern | Problem |
|---------|---------|
| No codebase map | 200+ files, no directory explanation |
| Missing "How to Add X" guides | No guide for common extension points |
| No local dev workflow | Missing: test, lint, debug commands |

### Category 5: Debugging Black Hole

| Pattern | Problem |
|---------|---------|
| No troubleshooting section | Every failure becomes wasted time |
| Error messages unexplained | Common errors not documented |
| No logging guidance | How to change log levels, enable debug |

### Category 6: Navigation Failure

| Pattern | Problem |
|---------|---------|
| Monolithic README | 1500+ lines covering everything |
| No entry point | No index, no "start here" |
| Broken internal links | Dead ends |
| Duplicate divergence | Same topic in 3 places, all different |

### Category 7: DevX Hostility

| Pattern | Problem |
|---------|---------|
| Minimizing language | "Simply," "just," "obviously" |
| Context-free snippets | Where does `client` come from? |
| Placeholder confusion | `your-api-key-here` vs `<YOUR_API_KEY>` |

## Validation Checklist

### Installation & Running
- [ ] All prerequisites listed with versions
- [ ] Platform-specific instructions
- [ ] Every command runs without modification
- [ ] Verification step confirms success
- [ ] Time to running < 15 minutes

### Accuracy
- [ ] All code examples execute
- [ ] All referenced files exist
- [ ] No TODOs in published docs

### Making Changes
- [ ] Directory structure explained
- [ ] "How to add X" guides exist
- [ ] Local dev workflow complete

### Debugging
- [ ] Troubleshooting section exists
- [ ] Common errors documented
- [ ] Logging configuration explained

### Navigation
- [ ] README is focused, not monolithic
- [ ] TOC for long documents
- [ ] All internal links work
