# Use Case 6: Code Review & Analysis

**Purpose:** Validate agent's ability to review code changes for quality and consistency
**Output Path:** test_results/code_review/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Can I catch issues before they reach production?"

---

## Test Suite Overview

This test evaluates how effectively an agent can review code changes using Agentic Inquiry to:
- Understand what's being changed and why
- Check consistency with existing patterns
- Identify potential impacts and risks
- Find missing components (tests, docs)
- Provide actionable, specific feedback
- Assess architectural fit

### Success Criteria

Code review is successful if the agent can:
- Understand changes within 10 minutes
- Identify pattern violations
- Find missing tests or documentation
- Assess impact on existing code
- Provide specific, actionable feedback
- Achieve ≥8/10 confidence in review quality

**Time Limit:** 30 minutes for complete code review
**Confidence Threshold:** 8/10 or higher on "review quality" scale

---

## Pre-Test Setup

### Prerequisites

> **CRITICAL: You MUST index the codebase yourself.** Do NOT assume pre-existing data is valid.
> See USE_CASES.md "Ensure Fresh Index" for detailed instructions.

**Step 1: Create Session with Unique Project ID**
```python
project_id = "ai_test07_review_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Code review test")
```

**Step 2: Index the Codebase (REQUIRED)**
```python
add_knowledge(session_id=session_id, source=".", content_type="directory", wait_for_completion=True)
```

**Step 3: Verify Index Health**
```python
info = get_project_info(session_id=session_id)
# Verify: entities > 0, relationships > 0, index_health: "healthy"
```

### Additional Prerequisites

1. **Code Changes Defined:** Choose realistic PR/changeset to review (see examples below)
2. **Review Criteria:** Clear standards for what to check
3. **Context Available:** Access to existing codebase for comparison

### Change Selection

Choose ONE realistic code change appropriate for your codebase:

**For new features:**
- "Add new embedder provider (OpenAI, Cohere, etc.)"
- "Add new parser for file format"
- "Add new search strategy"
- "Add new API endpoint"

**For refactoring:**
- "Refactor error handling in service layer"
- "Extract utility functions to shared module"
- "Consolidate duplicate code"

**For bug fixes:**
- "Fix race condition in concurrent operations"
- "Fix memory leak in parser"
- "Fix incorrect result ranking"

**Document Your Code Change:**
```
Pull Request / Changeset:
Title: [clear description]
Example: "Add Cohere embedder provider"

Files Changed:
- [file] - [lines added/removed]
- [file] - [lines added/removed]

Description:
[what the change does and why]

Related Issues:
[issue numbers or links]

Review Focus:
[what to pay special attention to]
```

---

## Test 1: Understand Changes

**Scenario:** Quickly understand what's being changed and why

### T1.1: Change Summary

**Objective:** Understand the high-level purpose of changes

**Execute:** Analyze the changeset:
- What is being added/modified/removed?
- Why is this change needed?
- What problem does it solve?
- How does it fit into the codebase?

**Success Criteria:**
- Describes changes accurately
- Understands motivation
- Identifies affected components
- Sees the big picture

**Document:**
```
Change Analysis:

What's Being Changed:
- Added: [files/components]
- Modified: [files/components]
- Removed: [files/components]
- Total LOC: [+added/-removed]

Purpose:
[why this change is being made]

Problem Being Solved:
[what issue this addresses]

Scope:
- Components Affected: [list]
- Subsystems Touched: [list]
- Complexity: [simple/moderate/complex]

Understanding Time: [minutes]
Confidence in Understanding (1-10): [score]
```

---

### T1.2: Change Details

**Objective:** Understand specific code changes in detail

**Execute:** Examine the actual code:
- What's the implementation approach?
- What new classes/functions/methods?
- What existing code is modified?
- What APIs or interfaces change?

**Success Criteria:**
- Understands implementation details
- Identifies new abstractions
- Recognizes modified behavior
- Spots API changes

**Document:**
```
Implementation Details:

New Components:
1. [class/function] - [file:path]
   - Purpose: [what it does]
   - Key Methods: [list]
   - Complexity: [high/medium/low]

2. [class/function] - [file:path]
   - Purpose: [what it does]
   - Key Methods: [list]
   - Complexity: [high/medium/low]

[continue...]

Modified Components:
1. [component] - [file:path]
   - Changes: [what changed]
   - Reason: [why changed]
   - Impact: [behavioral changes]

API Changes:
- [old signature] → [new signature]
- Breaking: [yes/no]
- Deprecation: [yes/no]

Implementation Approach:
[description of how solution is implemented]

Code Quality Observations:
[initial impressions of code quality]
```

---

## Test 2: Check Pattern Compliance

**Scenario:** Verify changes follow established patterns

### T2.1: Find Existing Patterns

**Objective:** Identify patterns that new code should follow

**Execute:** Search for similar existing code:
- How is similar functionality implemented?
- What patterns are established?
- What conventions are used?
- How should this be implemented?

**Success Criteria:**
- Finds relevant existing code within 3 queries
- Identifies applicable patterns
- Understands conventions
- Knows what to compare against

**Document:**
```
Pattern Discovery:

Query 1: [search for similar code]
- Results: [count]
- Relevant: [count]
- Pattern Found: [description]

Query 2: [search for conventions]
- Results: [count]
- Relevant: [count]
- Convention Found: [description]

Established Patterns:

Pattern 1: [name/description]
- Where Used: [examples]
- Key Characteristics: [list]
- Should Apply To This Change: [yes/no]

Pattern 2: [name/description]
- Where Used: [examples]
- Key Characteristics: [list]
- Should Apply To This Change: [yes/no]

[continue...]

Relevant Conventions:
- Naming: [pattern]
- Structure: [pattern]
- Error Handling: [pattern]
- Testing: [pattern]

Discovery Time: [minutes]
```

---

### T2.2: Compare Against Patterns

**Objective:** Check if new code follows the patterns

**Execute:** Compare new code to patterns:
- Does naming match conventions?
- Is structure consistent?
- Are patterns applied correctly?
- What deviates from patterns?

**Success Criteria:**
- Identifies conformance
- Spots deviations
- Explains why deviations matter
- Provides specific examples

**Document:**
```
Pattern Compliance Analysis:

Naming Conventions:
- Follows Pattern: [yes/no]
- Examples:
  - [name in new code] - [compliant/non-compliant] - [reason]
  - [name in new code] - [compliant/non-compliant] - [reason]

Structure/Organization:
- Follows Pattern: [yes/no]
- Examples:
  - [structural choice] - [compliant/non-compliant] - [reason]

Error Handling:
- Follows Pattern: [yes/no]
- Examples:
  - [error handling approach] - [compliant/non-compliant] - [reason]

Deviations Found:

Deviation 1: [what deviates]
- Expected: [pattern]
- Actual: [what was done]
- Severity: [critical/high/medium/low]
- Recommendation: [what to change]

Deviation 2: [what deviates]
- Expected: [pattern]
- Actual: [what was done]
- Severity: [critical/high/medium/low]
- Recommendation: [what to change]

[continue...]

Overall Compliance: [excellent/good/fair/poor]
Critical Issues: [count]
```

---

## Test 3: Assess Impact

**Scenario:** Understand the impact of changes on existing code

### T3.1: Dependency Analysis

**Objective:** Identify what depends on the changed code

**Execute:** Find dependencies:
- What code uses the modified components?
- What might break from these changes?
- Are there backward compatibility concerns?
- What's the blast radius?

**Success Criteria:**
- Finds all direct dependencies
- Identifies potential breakage
- Assesses compatibility
- Quantifies impact

**Document:**
```
Impact Analysis:

Direct Dependencies:
1. [component] - [file:path]
   - Uses: [what from changed code]
   - Impact: [how affected]
   - Risk: [high/medium/low]

2. [component] - [file:path]
   - Uses: [what from changed code]
   - Impact: [how affected]
   - Risk: [high/medium/low]

[continue...]

Total Dependencies: [count]

Potential Breakage:
- [what might break] - Likelihood: [high/medium/low]
- [what might break] - Likelihood: [high/medium/low]

Backward Compatibility:
- Breaking Changes: [yes/no - list]
- Deprecations Needed: [yes/no - list]
- Migration Required: [yes/no - describe]

Blast Radius: [small/medium/large]
Overall Impact Risk: [high/medium/low]
```

---

### T3.2: Side Effect Analysis

**Objective:** Identify potential side effects of changes

**Execute:** Look for side effects:
- What behaviors might change?
- What assumptions might break?
- What edge cases might surface?
- What could go wrong?

**Success Criteria:**
- Identifies potential side effects
- Explains impact mechanisms
- Categorizes by severity
- Suggests mitigation

**Document:**
```
Side Effect Analysis:

Behavioral Changes:
1. [behavior] - [old] → [new]
   - Intentional: [yes/no]
   - Impact: [description]
   - Acceptable: [yes/no]

2. [behavior] - [old] → [new]
   - Intentional: [yes/no]
   - Impact: [description]
   - Acceptable: [yes/no]

Broken Assumptions:
- [assumption] - [why it might break] - [severity]
- [assumption] - [why it might break] - [severity]

Edge Cases:
- [edge case] - [how change affects it]
- [edge case] - [how change affects it]

Potential Issues:
1. [issue] - Likelihood: [high/medium/low] - Severity: [high/medium/low]
2. [issue] - Likelihood: [high/medium/low] - Severity: [high/medium/low]

Mitigation Needed: [yes/no]
Recommendations: [suggestions]
```

---

## Test 4: Find Similar Code

**Scenario:** Compare to existing implementations for consistency

### T4.1: Locate Comparable Code

**Objective:** Find existing code that solves similar problems

**Execute:** Search for similar implementations:
- How is this problem solved elsewhere?
- What similar components exist?
- How do they compare?
- What can be learned?

**Success Criteria:**
- Finds comparable implementations
- Identifies similarities and differences
- Learns from existing code
- Spots improvement opportunities

**Document:**
```
Similar Code Analysis:

Comparable Implementations:

Implementation 1: [name/description]
- Location: [file:path]
- Similarity: [what's similar]
- Approach: [how it works]
- Quality: [high/medium/low]

Implementation 2: [name/description]
- Location: [file:path]
- Similarity: [what's similar]
- Approach: [how it works]
- Quality: [high/medium/low]

[continue...]

Comparison to New Code:

Similarities:
- [what matches existing implementations]

Differences:
- [what's different from existing implementations]
- Why: [reason for difference]
- Better/Worse: [assessment]

Learnings:
- [what existing code does well that new code could adopt]
- [what new code improves upon]

Consistency: [excellent/good/fair/poor]
```

---

### T4.2: Code Reuse Opportunities

**Objective:** Identify opportunities to reuse existing code

**Execute:** Look for duplication:
- Does new code duplicate existing functionality?
- Could existing utilities be used?
- Is there copy-paste code?
- What could be shared?

**Success Criteria:**
- Identifies duplication
- Finds reuse opportunities
- Suggests refactoring
- Quantifies benefit

**Document:**
```
Code Reuse Analysis:

Duplication Found:

Duplicate 1:
- New Code: [file:function:lines]
- Existing: [file:function:lines]
- Similarity: [%]
- Should Reuse: [yes/no]
- Effort to Refactor: [hours]

Duplicate 2:
- New Code: [file:function:lines]
- Existing: [file:function:lines]
- Similarity: [%]
- Should Reuse: [yes/no]
- Effort to Refactor: [hours]

[continue...]

Reuse Opportunities:
- [existing utility] - [how it could be used in new code]
- [existing utility] - [how it could be used in new code]

Copy-Paste Code:
- Found: [yes/no]
- Locations: [list]
- Recommendation: [extract to shared function/class]

Duplication Score: [% duplicate code]
Refactoring Recommended: [yes/no]
```

---

## Test 5: Verify Completeness

**Scenario:** Check for missing components (tests, docs, etc.)

### T5.1: Test Coverage

**Objective:** Verify adequate tests exist for changes

**Execute:** Check for tests:
- Are there tests for new code?
- Do tests cover main paths?
- Do tests cover edge cases?
- Are existing tests updated?

**Success Criteria:**
- Identifies test presence/absence
- Assesses coverage adequacy
- Finds gaps
- Provides specific test recommendations

**Document:**
```
Test Coverage Analysis:

Tests Found:

New Test 1: [file:path]
- Tests: [what it tests]
- Coverage: [main paths/edge cases/errors]
- Quality: [thorough/adequate/minimal]

New Test 2: [file:path]
- Tests: [what it tests]
- Coverage: [main paths/edge cases/errors]
- Quality: [thorough/adequate/minimal]

[continue...]

Coverage Assessment:

Main Functionality:
- [ ] Happy path tested
- [ ] Input validation tested
- [ ] Error cases tested
- [ ] Edge cases tested

Modified Code:
- [ ] Existing tests updated
- [ ] Regression tests added
- [ ] Integration tests added

Test Gaps:

Gap 1: [what's not tested]
- Severity: [high/medium/low]
- Recommendation: [specific test to add]

Gap 2: [what's not tested]
- Severity: [high/medium/low]
- Recommendation: [specific test to add]

Overall Coverage: [excellent/good/adequate/poor]
Test Quality: [high/medium/low]
Tests Required: [yes/no - list]
```

---

### T5.2: Documentation Check

**Objective:** Verify documentation is complete and updated

**Execute:** Check documentation:
- Are public APIs documented?
- Are docstrings present?
- Is README updated?
- Are examples provided?

**Success Criteria:**
- Identifies missing documentation
- Assesses doc quality
- Finds outdated docs
- Recommends additions

**Document:**
```
Documentation Review:

Code Documentation:

New Classes/Functions:
1. [name] - Docstring: [yes/no] - Quality: [good/poor]
2. [name] - Docstring: [yes/no] - Quality: [good/poor]
[continue...]

Missing Docstrings:
- [class/function] - Public: [yes/no] - Priority: [high/medium/low]
- [class/function] - Public: [yes/no] - Priority: [high/medium/low]

External Documentation:

README:
- Updated: [yes/no]
- Needs Update: [what sections]

User Guides:
- Updated: [yes/no]
- Needs Update: [what sections]

API Documentation:
- New APIs Documented: [yes/no]
- Examples Provided: [yes/no]

Documentation Gaps:

Gap 1: [what's missing]
- Type: [API docs/guide/example]
- Priority: [high/medium/low]
- Recommendation: [what to add]

Overall Documentation: [excellent/good/adequate/poor]
Documentation Required: [yes/no - list]
```

---

## Test 6: Provide Actionable Feedback

**Scenario:** Synthesize findings into clear, actionable feedback

### T6.1: Issues and Recommendations

**Objective:** Create prioritized list of issues with clear recommendations

**Execute:** Compile feedback:
- What must be fixed?
- What should be improved?
- What's nice to have?
- How to address each?

**Success Criteria:**
- Issues are specific and clear
- Recommendations are actionable
- Priorities are appropriate
- Tone is constructive

**Document:**
```
Code Review Feedback:

Critical Issues (Must Fix):

Issue 1: [description]
- Location: [file:line]
- Problem: [what's wrong]
- Impact: [why it matters]
- Recommendation: [specific fix]
- Example: [code snippet if helpful]

Issue 2: [description]
- Location: [file:line]
- Problem: [what's wrong]
- Impact: [why it matters]
- Recommendation: [specific fix]
- Example: [code snippet if helpful]

[continue...]

Important Issues (Should Fix):

Issue 1: [description]
- Location: [file:line]
- Problem: [what's wrong]
- Recommendation: [specific fix]

[continue...]

Suggestions (Nice to Have):

Suggestion 1: [description]
- Location: [file:line]
- Improvement: [what could be better]
- Benefit: [why worth doing]

[continue...]

Total Issues:
- Critical: [count]
- Important: [count]
- Suggestions: [count]
```

---

### T6.2: Approval Recommendation

**Objective:** Make clear approval/rejection recommendation

**Execute:** Decide on approval:
- Are critical issues present?
- Is quality acceptable?
- Are tests adequate?
- Is it ready to merge?

**Success Criteria:**
- Clear recommendation
- Sound reasoning
- Conditions specified
- Next steps identified

**Document:**
```
Review Decision:

Recommendation: [Approve / Approve with Changes / Request Changes / Reject]

Reasoning:
[2-3 paragraphs explaining decision]

Approval Conditions (if conditional):
- [ ] [condition to satisfy]
- [ ] [condition to satisfy]
- [ ] [condition to satisfy]

Blockers (if rejecting):
1. [blocker] - [why it blocks]
2. [blocker] - [why it blocks]

Strengths:
- [what's good about the change]
- [what's good about the change]

Next Steps:
1. [what author should do next]
2. [what author should do next]

Re-review Required: [yes/no]
Confidence in Decision (1-10): [score]
```

---

## Final Evaluation

### Code Review Quality Metrics

**Time Metrics:**
```
Total Review Time: [minutes]
Target: ≤30 minutes
Met Target: [yes/no]

Breakdown:
- Understanding Changes: [minutes]
- Pattern Analysis: [minutes]
- Impact Assessment: [minutes]
- Completeness Check: [minutes]
- Feedback Writing: [minutes]
```

**Coverage Metrics:**
```
Review Completeness:
- Pattern compliance checked: [yes/no]
- Impact assessed: [yes/no]
- Tests verified: [yes/no]
- Documentation checked: [yes/no]
- Similar code compared: [yes/no]

Completeness Score: [X]/5
Target: 5/5
Met Target: [yes/no]
```

**Quality Metrics:**
```
Issues Found:
- Critical: [count]
- Important: [count]
- Suggestions: [count]
- Total: [count]

Feedback Quality:
- Specific: [yes/no]
- Actionable: [yes/no]
- Constructive: [yes/no]
- Prioritized: [yes/no]

Quality Score: [X]/4
Target: 4/4
Met Target: [yes/no]
```

**Confidence Metrics:**
```
Review Confidence: [1-10]
Target: ≥8
Met Target: [yes/no]

Decision Confidence: [1-10]
Covered All Aspects: [yes/no]
Would Catch Issues in Production: [yes/no]
```

### Production Readiness

**Critical Checks:**
- [ ] Reviewed in ≤30 minutes
- [ ] Pattern compliance verified
- [ ] Impact assessed thoroughly
- [ ] Tests checked
- [ ] Documentation verified
- [ ] Provided actionable feedback
- [ ] Clear approval decision
- [ ] Confidence ≥8/10

**Pass/Fail:** [PASS/FAIL]

---

## Summary & Recommendations

### What Worked Well
```
[3-5 things that helped code review]
```

### What Was Challenging
```
[3-5 challenges in reviewing code]
```

### Review Effectiveness

**Answer: [Very Effective / Effective / Somewhat Effective / Not Effective]**

**Reasoning:**
```
[2-3 paragraphs on:]
- Thoroughness of review
- Quality of feedback provided
- Value added vs manual review
- Areas for improvement
- Confidence in catching issues
```

### Recommendations

**For Review Process:**
```
[Suggestions to improve code review workflow]
```

**For Code Quality:**
```
[Patterns or standards that could prevent issues]
```

---

## Test Completion

**Test Metadata:**
```
Duration: [minutes]
Tester: [name/id]
Date: [YYYY-MM-DD]
Change Reviewed: [description]
Files Changed: [count]
Issues Found: [count]
Confidence Achieved: [score]/10
Approval Decision: [approve/changes/reject]
```

**Key Metrics:**
```
Review Completeness: [%]
Issues Found: [count]
Feedback Quality: [high/medium/low]
Time Efficiency: [on-time/slow]
Overall Success: [yes/no]
```

---

**Remember:** Effective code review means catching issues before production while being constructive and specific in feedback. Quality matters more than speed.
