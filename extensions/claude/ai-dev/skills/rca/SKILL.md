---
name: rca
description: Root cause analysis template - investigate before fixing to prevent symptom-level fixes. Auto-loads when investigating bugs or debugging failures.
user-invocable: false
---

# Root Cause Analysis

Document the root cause before implementing any fix.

## When to Use

- Before implementing any bug fix
- When a fix doesn't stick
- When the same issue recurs

## Template

### Problem Statement

**Symptom:** [What is the observable problem?]

**Impact:** [Who/what is affected? How severe?]

**Reproduction:** [Steps to reproduce]

### Investigation

**Evidence Collected:**
1. [Log entries, error messages, stack traces]
2. [Database queries and results]
3. [Code paths traced]
4. [Test results or failures]

**Initial Hypothesis:** [What did you first think was wrong?]

**Investigation Steps:**
1. [What did you check first?]
2. [What did that reveal?]
3. [What did you check next?]

### Root Cause Identification

**Root Cause:** [The fundamental reason, not the symptom]

**Evidence Supporting This:**
- Why do you believe this is the root cause?
- What would happen if you only fixed the symptom?
- What test proves this is the root cause?

**Why Wasn't This Caught Earlier?**
- [ ] Missing test for this scenario
- [ ] Missing validation at boundary
- [ ] Missing documentation
- [ ] Incorrect assumptions in existing code

### Proposed Solution

**Approach:** [How will this fix the root cause?]

**Why This Approach?**
| Alternative | Why Rejected |
|-------------|--------------|
| [Alternative 1] | [Reason] |
| [Alternative 2] | [Reason] |

**Architectural Alignment:**
- [ ] Uses existing patterns from AGENTS.md
- [ ] Uses central components (SchemaProcessor, EventBus, etc.)
- [ ] Does not introduce unnecessary complexity

**Risks:**
- [ ] Could break existing functionality?
- [ ] Could introduce performance regression?
- [ ] Could affect other components?

### Validation Plan

**How will we verify the fix works?**

1. **Unit Test:** [Test to add or modify]
2. **Integration Test:** [End-to-end verification]
3. **Manual Verification:** [Steps to confirm]
4. **Regression Check:** [Existing tests that must still pass]

**Proof of Fix:**
```bash
# Command to verify the fix
```

### Prevention

**How will we prevent this class of bug in the future?**

- [ ] Add schema validation at [location]
- [ ] Add test for [scenario]
- [ ] Update [documentation]
- [ ] Add type hint enforcement

### Sign-Off

- [ ] Root cause confirmed (not just symptom)
- [ ] Solution addresses root cause directly
- [ ] Validation plan defined
- [ ] Prevention measures identified
- [ ] Ready for implementation
