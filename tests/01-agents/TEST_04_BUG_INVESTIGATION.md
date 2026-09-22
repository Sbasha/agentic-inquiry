# Use Case 3: Bug Investigation

**Purpose:** Validate agent's ability to quickly locate and understand bugs in unfamiliar code
**Output Path:** test_results/bug_investigation/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Can I find the bug before the user gives up?"

---

## Test Suite Overview

This test evaluates how effectively an agent can investigate and understand bugs using Agentic Inquiry to:
- Locate bug-related code quickly
- Trace execution paths from symptom to root cause
- Understand all components involved
- Assess impact and side effects
- Propose fix strategies

### Success Criteria

Bug investigation is successful if the agent can:
- Find the bug location within 20 minutes
- Trace the complete execution path
- Identify root cause with confidence ≥8/10
- Understand all affected components
- Propose viable fix strategies

**Time Limit:** 20 minutes from bug report to root cause identification
**Confidence Threshold:** 8/10 or higher on "understand the bug" scale

---

## Pre-Test Setup

### Prerequisites

> **CRITICAL: You MUST index the codebase yourself.** Do NOT assume pre-existing data is valid.
> See USE_CASES.md "Ensure Fresh Index" for detailed instructions.

**Step 1: Create Session with Unique Project ID**
```python
project_id = "ai_test04_bug_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Bug investigation test")
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

1. **Bug Defined:** Choose or plant a realistic bug (see examples below)
2. **Reproduction Steps:** Clear steps to reproduce the bug
3. **Expected vs Actual:** What should happen vs what does happen

### Bug Selection

Choose ONE realistic bug appropriate for your codebase:

**For search/query systems:**
- "Search returns empty results for valid queries"
- "Search crashes on queries with special characters"
- "Results are not ranked correctly"

**For data processing:**
- "Parser fails silently on certain file types"
- "Index corruption after concurrent writes"
- "Memory leak during bulk operations"

**For APIs/services:**
- "Endpoint returns 500 for valid requests"
- "Authentication fails intermittently"
- "Response data is incomplete"

**Document Your Bug:**
```
Bug Report:
Title: [clear description]
Example: "Search returns empty results for valid queries"

Reproduction Steps:
1. [step 1]
2. [step 2]
3. [step 3]

Expected Behavior:
[what should happen]

Actual Behavior:
[what does happen]

Error Messages (if any):
[error output or logs]

Affected Version:
[version/commit where bug occurs]
```

---

## Test 1: Bug Reproduction Understanding

**Scenario:** Understand what the bug actually is and how to reproduce it

### T1.1: Symptom Analysis

**Objective:** Understand the reported symptoms and their context

**Execute:** Analyze the bug report:
- What is failing?
- Under what conditions?
- What's the expected behavior?
- What's the actual behavior?
- Are there error messages or logs?

**Success Criteria:**
- Clearly describes the symptom
- Identifies triggering conditions
- Understands expected vs actual behavior
- Can explain impact to user

**Document:**
```
Symptom Analysis:

What's Failing:
[description of the failure]

Triggering Conditions:
- [condition 1]
- [condition 2]
- [condition 3]

Expected Behavior:
[what should happen]

Actual Behavior:
[what does happen]

Error Messages:
[any error output]

User Impact:
[how this affects users]

Severity: [critical/high/medium/low]
Confidence in Understanding (1-10): [score]
```

---

### T1.2: Reproduction Verification

**Objective:** Understand how to reproduce the bug reliably

**Execute:** Analyze reproduction steps:
- What steps trigger the bug?
- Are steps clear and complete?
- What data/inputs are needed?
- What environment factors matter?

**Success Criteria:**
- Can list all reproduction steps
- Identifies required inputs/data
- Understands environmental factors
- Knows what success/failure looks like

**Document:**
```
Reproduction Steps:

Steps to Reproduce:
1. [step with details]
2. [step with details]
3. [step with details]

Required Inputs:
- [input 1] - [format/constraints]
- [input 2] - [format/constraints]

Environmental Factors:
- [factor 1] - [why it matters]
- [factor 2] - [why it matters]

Success Criteria:
[how to know if bug reproduced]

Reproducibility: [always/sometimes/rarely]
Confidence (1-10): [score]
```

---

## Test 2: Find Bug Location

**Scenario:** Quickly locate the code where the bug manifests

### T2.1: Component Identification

**Objective:** Identify which component(s) contain the bug

**Execute:** Search for the failing component:
- What component handles the failing operation?
- Where is that component implemented?
- What file(s) contain relevant code?

**Success Criteria:**
- Identifies correct component within 3 queries
- Provides file paths
- Knows component boundaries
- Understands component purpose

**Document:**
```
Component Search:

Query 1: [search query]
- Results: [count]
- Relevant: [count]
- Key Finding: [what you learned]

Query 2: [search query]
- Results: [count]
- Relevant: [count]
- Key Finding: [what you learned]

Query 3: [search query]
- Results: [count]
- Relevant: [count]
- Key Finding: [what you learned]

Component Found:
- Name: [component name]
- Location: [file:path]
- Purpose: [what it does]
- Confidence: [1-10]

Time to Discovery: [minutes]
```

---

### T2.2: Narrow to Specific Code

**Objective:** Find the exact function/method where bug occurs

**Execute:** Locate the specific code:
- What function/method is failing?
- Where is it defined?
- What does it do?
- How is it called?

**Success Criteria:**
- Identifies exact function/method
- Provides file:line location
- Understands function purpose
- Knows how function is invoked

**Document:**
```
Specific Code Location:

Function/Method: [name]
- Location: [file:line]
- Purpose: [description]
- Signature: [parameters and return type]

Called By:
- [caller 1] - [file:line]
- [caller 2] - [file:line]

What It Does:
[brief description of implementation]

Suspicious Code:
[specific lines or blocks that look problematic]

Confidence This Is Bug Location (1-10): [score]
```

---

## Test 3: Trace Execution Path

**Scenario:** Understand the flow from trigger to failure

### T3.1: Entry Point to Bug

**Objective:** Trace execution from entry point to bug location

**Execute:** Build execution path:
- Where does the operation start?
- What functions are called in sequence?
- What data flows through?
- Where does it fail?

**Success Criteria:**
- Traces complete path
- Identifies all intermediate steps
- Understands data flow
- Knows where failure occurs

**Document:**
```
Execution Path:

Entry Point:
- Location: [file:function:line]
- Trigger: [what initiates this]
- Input: [data passed in]

Execution Flow:
1. [entry] → [function/method] - [file:line]
   - Does: [what happens]
   - Data: [transformations]

2. [prev] → [function/method] - [file:line]
   - Does: [what happens]
   - Data: [transformations]

3. [prev] → [function/method] - [file:line]
   - Does: [what happens]
   - Data: [transformations]

[Continue to failure point]

Failure Point:
- Location: [file:function:line]
- Why It Fails: [description]

Total Steps: [count]
Confidence in Path (1-10): [score]
```

---

### T3.2: Data Flow Analysis

**Objective:** Understand how data transforms along the path

**Execute:** Track data transformations:
- What data enters the system?
- How is it transformed at each step?
- What's the data state at failure?
- What should the data look like?

**Success Criteria:**
- Tracks data through all steps
- Identifies transformations
- Spots anomalies
- Understands expected vs actual state

**Document:**
```
Data Flow:

Input Data:
- Type: [data type]
- Value: [example value]
- Source: [where it comes from]

Transformations:

Step 1: [function name]
- Input: [data state before]
- Operation: [what's done to data]
- Output: [data state after]

Step 2: [function name]
- Input: [data state before]
- Operation: [what's done to data]
- Output: [data state after]

[Continue to failure]

At Failure Point:
- Expected Data: [what should be]
- Actual Data: [what it is]
- Difference: [what's wrong]

Data Anomaly Detected: [yes/no]
Where: [which step]
```

---

## Test 4: Find Root Cause

**Scenario:** Determine the underlying cause of the bug

### T4.1: Hypothesis Formation

**Objective:** Form hypotheses about the root cause

**Execute:** Based on execution trace and data flow:
- What could cause this failure?
- Why does data end up incorrect?
- What assumptions might be violated?
- What edge cases aren't handled?

**Success Criteria:**
- Lists 2-3 plausible hypotheses
- Each hypothesis is specific
- Can explain how each would cause symptoms
- Prioritizes by likelihood

**Document:**
```
Root Cause Hypotheses:

Hypothesis 1: [description]
- Evidence: [what supports this]
- Would Explain: [how this causes symptoms]
- Likelihood: [high/medium/low]
- How to Test: [verification approach]

Hypothesis 2: [description]
- Evidence: [what supports this]
- Would Explain: [how this causes symptoms]
- Likelihood: [high/medium/low]
- How to Test: [verification approach]

Hypothesis 3: [description]
- Evidence: [what supports this]
- Would Explain: [how this causes symptoms]
- Likelihood: [high/medium/low]
- How to Test: [verification approach]

Most Likely: [hypothesis number]
Reasoning: [why this is most likely]
```

---

### T4.2: Root Cause Verification

**Objective:** Verify the root cause by examining code

**Execute:** Look for evidence of root cause:
- Does the code match the hypothesis?
- Are there validation gaps?
- Are error cases handled?
- What about edge cases?

**Success Criteria:**
- Finds code that confirms hypothesis
- Identifies specific bug in code
- Explains why bug wasn't caught
- Can describe exact failure mechanism

**Document:**
```
Root Cause Verification:

Code Evidence:
- Location: [file:line]
- Problematic Code: [specific snippet]
- Why It's Wrong: [explanation]

What Should Happen:
[correct behavior]

What Actually Happens:
[incorrect behavior]

Why Bug Wasn't Caught:
- Missing Validation: [yes/no - details]
- Missing Tests: [yes/no - details]
- Edge Case: [yes/no - details]

Root Cause:
[clear statement of the bug]

Confidence (1-10): [score]
```

---

## Test 5: Impact Assessment

**Scenario:** Understand the full scope of the bug's impact

### T5.1: Direct Impact

**Objective:** Identify what's directly affected by the bug

**Execute:** Find direct impacts:
- What operations fail?
- What users are affected?
- What data might be corrupted?
- What features are broken?

**Success Criteria:**
- Lists all affected operations
- Identifies user impact
- Assesses data risk
- Categorizes severity

**Document:**
```
Direct Impact:

Affected Operations:
1. [operation] - [how affected] - Severity: [high/medium/low]
2. [operation] - [how affected] - Severity: [high/medium/low]
3. [operation] - [how affected] - Severity: [high/medium/low]

User Impact:
- Affected Users: [who/how many]
- Impact Type: [data loss/downtime/incorrect results]
- Workaround Available: [yes/no - description]

Data Risk:
- Data Corruption: [yes/no - details]
- Data Loss: [yes/no - details]
- Rollback Needed: [yes/no - details]

Overall Severity: [critical/high/medium/low]
```

---

### T5.2: Blast Radius

**Objective:** Identify indirect impacts and dependencies

**Execute:** Find cascading effects:
- What depends on the broken code?
- What downstream operations fail?
- What other bugs might be related?
- What similar code might have same bug?

**Success Criteria:**
- Maps dependency chain
- Identifies cascading failures
- Finds related code
- Assesses total scope

**Document:**
```
Blast Radius:

Dependent Components:
1. [component] - [file:path] - [how it depends]
2. [component] - [file:path] - [how it depends]
3. [component] - [file:path] - [how it depends]

Cascading Failures:
- [failure 1] - [why it happens]
- [failure 2] - [why it happens]

Similar Code (potential same bug):
- [location 1] - [similarity]
- [location 2] - [similarity]

Related Issues:
- [issue/bug] - [relationship]

Total Blast Radius: [small/medium/large]
Confidence (1-10): [score]
```

---

## Test 6: Fix Strategy

**Scenario:** Propose strategies for fixing the bug

### T6.1: Fix Approaches

**Objective:** Identify possible fix approaches

**Execute:** Design fix options:
- What are different ways to fix this?
- What's the minimal fix?
- What's the proper fix?
- What are tradeoffs?

**Success Criteria:**
- Proposes 2-3 fix approaches
- Each approach is concrete
- Explains tradeoffs
- Recommends best approach

**Document:**
```
Fix Approaches:

Approach 1: [name/description]
- What to Change: [specific changes]
- Files Affected: [list]
- Pros: [benefits]
- Cons: [drawbacks]
- Risk Level: [high/medium/low]
- Estimated Effort: [hours/days]

Approach 2: [name/description]
- What to Change: [specific changes]
- Files Affected: [list]
- Pros: [benefits]
- Cons: [drawbacks]
- Risk Level: [high/medium/low]
- Estimated Effort: [hours/days]

Approach 3: [name/description]
- What to Change: [specific changes]
- Files Affected: [list]
- Pros: [benefits]
- Cons: [drawbacks]
- Risk Level: [high/medium/low]
- Estimated Effort: [hours/days]

Recommended Approach: [number]
Reasoning: [why this is best]
```

---

### T6.2: Fix Implementation Plan

**Objective:** Create detailed plan for implementing the fix

**Execute:** Plan the fix:
- What code changes are needed?
- What tests should be added?
- How to verify the fix?
- What's the rollout strategy?

**Success Criteria:**
- Detailed code changes
- Test strategy defined
- Verification plan clear
- Rollout considered

**Document:**
```
Implementation Plan:

Code Changes:

1. [file:path]
   - Change: [what to modify]
   - Lines: [approximate line numbers]
   - Code: [pseudo-code or sketch]

2. [file:path]
   - Change: [what to modify]
   - Lines: [approximate line numbers]
   - Code: [pseudo-code or sketch]

Test Strategy:

Unit Tests:
- [ ] [test description] - [file]
- [ ] [test description] - [file]

Integration Tests:
- [ ] [test description] - [file]

Regression Tests:
- [ ] [test description] - [file]

Verification Plan:
1. [verification step]
2. [verification step]
3. [verification step]

Rollout:
- Deploy to: [environment sequence]
- Monitor: [what to watch]
- Rollback Plan: [how to rollback if needed]

Confidence in Fix (1-10): [score]
```

---

## Final Evaluation

### Bug Investigation Metrics

**Time Metrics:**
```
Total Investigation Time: [minutes]
Target: ≤20 minutes
Met Target: [yes/no]

Breakdown:
- Understanding Bug: [minutes]
- Finding Location: [minutes]
- Tracing Execution: [minutes]
- Finding Root Cause: [minutes]
- Impact Assessment: [minutes]
- Fix Planning: [minutes]
```

**Discovery Metrics:**
```
Queries to Find Bug: [count]
Target: ≤5 queries
Met Target: [yes/no]

Root Cause Found: [yes/no]
Confidence Level: [1-10]
Target: ≥8
Met Target: [yes/no]
```

**Accuracy Metrics:**
```
Correct Component: [yes/no]
Correct Function: [yes/no]
Correct Root Cause: [yes/no]
Complete Impact Assessment: [yes/no]
Viable Fix Proposed: [yes/no]

Accuracy Score: [X]/5
Target: ≥4/5
Met Target: [yes/no]
```

### Production Readiness

**Critical Checks:**
- [ ] Bug found in ≤20 minutes
- [ ] Root cause identified with ≥8/10 confidence
- [ ] Complete execution path traced
- [ ] All affected components identified
- [ ] Viable fix strategy proposed
- [ ] Impact properly assessed
- [ ] Could implement fix immediately

**Pass/Fail:** [PASS/FAIL]

---

## Summary & Recommendations

### What Worked Well
```
[3-5 things that helped bug investigation]
```

### What Was Challenging
```
[3-5 challenges in finding the bug]
```

### Investigation Effectiveness

**Answer: [Very Effective / Effective / Somewhat Effective / Not Effective]**

**Reasoning:**
```
[2-3 paragraphs on:]
- Speed of bug discovery
- Accuracy of root cause identification
- Completeness of impact assessment
- Quality of fix proposal
- Comparison to manual debugging
```

### Recommendations

**For Tool Improvement:**
```
[Suggestions to improve bug investigation workflow]
```

**For Debugging Workflow:**
```
[Patterns that helped or slowed investigation]
```

---

## Test Completion

**Test Metadata:**
```
Duration: [minutes]
Tester: [name/id]
Date: [YYYY-MM-DD]
Bug: [description]
Root Cause Found: [yes/no]
Confidence Achieved: [score]/10
Ready to Fix: [yes/no]
```

**Key Metrics:**
```
Time to Bug Location: [minutes]
Queries Required: [count]
Root Cause Accuracy: [correct/incorrect]
Impact Assessment Completeness: [%]
Overall Success: [yes/no]
```

---

**Remember:** Effective bug investigation means finding the root cause quickly with high confidence. Speed matters, but accuracy is critical.
