# Use Case 4: Major Refactoring

**Purpose:** Validate agent's ability to plan and execute large-scale refactoring safely
**Output Path:** test_results/major_refactoring/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Can I refactor this without breaking everything?"

---

## Test Suite Overview

This test evaluates how effectively an agent can plan major refactoring using Agent-Vault to:
- Find all code that needs to change
- Understand current architecture deeply
- Map complete dependency chains
- Assess blast radius and risks
- Plan safe migration strategy
- Identify rollback points

### Success Criteria

Refactoring is successful if the agent can:
- Find 100% of code to refactor
- Understand current architecture completely
- Map all usages and dependencies
- Quantify blast radius accurately
- Propose safe migration steps
- Achieve ≥9/10 confidence before starting

**Time Limit:** 60 minutes from task assignment to refactoring plan
**Confidence Threshold:** 9/10 or higher on "ready to refactor" scale (high stakes)

---

## Pre-Test Setup

### Prerequisites

> **CRITICAL: You MUST index the codebase yourself.** Do NOT assume pre-existing data is valid.
> Tests that skip indexing will fail because relationships won't exist for your project_id.

**Step 1: Create Session with Unique Project ID**
```python
# Use the naming convention from USE_CASES.md
project_id = "agv_test05_refactor_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Major refactoring test")
```

**Step 2: Index the Codebase**
```python
# This step is REQUIRED - it populates entities AND relationships
add_knowledge(session_id=session_id, source=".", content_type="directory", wait_for_completion=True)
```

**Step 3: Verify Index Health**
```python
# Check that BOTH entities and relationships are populated
info = get_project_info(session_id=session_id)
# Expected: entities > 0, relationships > 0, index_health: "healthy"
# If relationships = 0, indexing failed or was skipped - DO NOT PROCEED
```

**Why This Matters:**
- Each test uses an isolated project_id to prevent cross-contamination
- The `add_knowledge` call extracts entities AND builds the relationship graph
- Without relationships, `analyze_impact` and `graph_traverse` return empty results
- Existing data from other project_ids will NOT be visible to your session

### Additional Prerequisites

1. **Refactoring Defined:** Choose a realistic large-scale refactoring (see examples below)
2. **Success Criteria:** Clear definition of what success looks like
3. **Rollback Plan:** Understanding of how to undo if things go wrong

### Refactoring Selection

Choose ONE realistic major refactoring appropriate for your codebase:

**For architecture changes:**
- "Refactor parser system to support streaming"
- "Convert synchronous API to async"
- "Extract service layer from monolith"
- "Replace ORM with repository pattern"

**For API changes:**
- "Rename core interface breaking all callers"
- "Change function signatures across codebase"
- "Consolidate multiple similar classes"
- "Replace deprecated library"

**For data model changes:**
- "Change database schema structure"
- "Migrate to new data format"
- "Restructure internal data models"

**Document Your Refactoring:**
```
Refactoring Task:
Title: [clear description]
Example: "Refactor parser system to support streaming"

Current State:
[how it works now]

Desired State:
[how it should work after]

Why Refactor:
[business/technical justification]

Success Criteria:
[how you'll know it works]

Risk Level: [critical/high/medium/low]
```

---

## Test 1: Find All Target Code

**Scenario:** Locate every piece of code that needs to change

### T1.1: Core Components Discovery

**Objective:** Find all primary components involved in the refactoring

**Execute:** Search for target code:
- What are the main classes/modules to refactor?
- Where are they defined?
- How many implementations exist?
- Are there variations or subclasses?

**Success Criteria:**
- Finds all primary components within 5 queries
- Provides complete file list
- Identifies all variations
- No components missed

**Document:**
```
Component Discovery:

Query 1: [search query]
- Results: [count]
- Relevant: [count]
- Components Found: [list]

Query 2: [search query]
- Results: [count]
- Relevant: [count]
- Components Found: [list]

[Continue as needed]

Core Components to Refactor:

1. [Component Name]
   - Location: [file:path]
   - Type: [class/module/interface]
   - Size: [LOC]
   - Complexity: [high/medium/low]

2. [Component Name]
   - Location: [file:path]
   - Type: [class/module/interface]
   - Size: [LOC]
   - Complexity: [high/medium/low]

[Continue for all components]

Total Components: [count]
Total LOC Affected: [count]
Discovery Completeness: [%]
Confidence (1-10): [score]
```

---

### T1.2: Related Code Discovery

**Objective:** Find all related code (tests, utilities, configurations)

**Execute:** Find supporting code:
- Where are tests for these components?
- What utilities support them?
- What configurations reference them?
- What documentation mentions them?

**Success Criteria:**
- Finds all test files
- Locates supporting utilities
- Identifies configuration files
- Finds documentation

**Document:**
```
Related Code:

Test Files:
1. [file:path] - [what it tests] - [LOC]
2. [file:path] - [what it tests] - [LOC]
3. [file:path] - [what it tests] - [LOC]

Utilities:
1. [file:path] - [purpose] - [LOC]
2. [file:path] - [purpose] - [LOC]

Configuration Files:
1. [file:path] - [what's configured]
2. [file:path] - [what's configured]

Documentation:
1. [file:path] - [what's documented]
2. [file:path] - [what's documented]

Total Related Files: [count]
All Tests Found: [yes/no]
All Configs Found: [yes/no]
```

---

## Test 2: Current Architecture Analysis

**Scenario:** Deeply understand how the system currently works

### T2.1: Architecture Deep Dive

**Objective:** Understand current implementation in detail

**Execute:** Analyze current architecture:
- How does the current system work?
- What patterns are used?
- What are the key abstractions?
- How do components interact?

**Success Criteria:**
- Can explain current architecture clearly
- Identifies all patterns
- Understands abstractions
- Maps component interactions

**Document:**
```
Current Architecture:

System Overview:
[2-3 paragraph description of how it works now]

Key Patterns:
1. [pattern] - [where/how used] - [why]
2. [pattern] - [where/how used] - [why]
3. [pattern] - [where/how used] - [why]

Core Abstractions:
1. [abstraction] - [purpose] - [file:path]
2. [abstraction] - [purpose] - [file:path]

Component Interactions:
[Component A] → [Component B] - [how they interact]
[Component B] → [Component C] - [how they interact]
[Component C] → [Component A] - [how they interact]

Data Flow:
[describe how data flows through system]

Why It's Designed This Way:
[reasoning behind current architecture]

Understanding Confidence (1-10): [score]
```

---

### T2.2: Strengths and Limitations

**Objective:** Identify what works and what doesn't in current design

**Execute:** Analyze architecture quality:
- What works well in current design?
- What are the pain points?
- What needs to change?
- What should be preserved?

**Success Criteria:**
- Lists 3-5 strengths
- Lists 3-5 limitations
- Explains why refactoring is needed
- Knows what to preserve

**Document:**
```
Architecture Analysis:

Strengths (Keep These):
1. [strength] - [why it works well]
2. [strength] - [why it works well]
3. [strength] - [why it works well]

Limitations (Must Fix):
1. [limitation] - [why it's a problem]
2. [limitation] - [why it's a problem]
3. [limitation] - [why it's a problem]

Why Refactoring Is Needed:
[clear justification for the effort]

What Must Be Preserved:
1. [feature/behavior] - [why critical]
2. [feature/behavior] - [why critical]

Technical Debt Being Addressed:
[description of debt being paid down]
```

---

## Test 3: Find All Usages

**Scenario:** Map every location that uses the code being refactored

### T3.1: Direct Usages

**Objective:** Find all code that directly uses the target components

**Execute:** Search for direct usages:
- What imports the target code?
- What calls the target functions?
- What instantiates the target classes?
- What extends the target interfaces?

**Success Criteria:**
- Finds all import statements
- Locates all call sites
- Identifies all instantiations
- Maps all implementations

**Document:**
```
Direct Usages:

Import Locations:
1. [file:path] - [what's imported]
2. [file:path] - [what's imported]
3. [file:path] - [what's imported]
[continue...]

Total Import Sites: [count]

Call Sites:
1. [file:function:line] - [what's called] - [context]
2. [file:function:line] - [what's called] - [context]
3. [file:function:line] - [what's called] - [context]
[continue...]

Total Call Sites: [count]

Instantiation Sites:
1. [file:function:line] - [what's created]
2. [file:function:line] - [what's created]
[continue...]

Total Instantiations: [count]

Implementations/Extensions:
1. [file:class:line] - [what implements/extends]
2. [file:class:line] - [what implements/extends]
[continue...]

Total Implementations: [count]

Overall Direct Usages: [total count]
Confidence All Found (1-10): [score]
```

---

### T3.2: Indirect Usages

**Objective:** Find code that indirectly depends on target components

**Execute:** Map indirect dependencies:
- What calls the code that calls the target?
- What depends on the dependents?
- How deep is the dependency chain?
- What's the transitive closure?

**Success Criteria:**
- Maps 2-3 levels of dependencies
- Identifies indirect call chains
- Understands transitive dependencies
- Quantifies scope

**Document:**
```
Indirect Usages:

Level 2 Dependencies (calls code that uses target):
1. [file:function] → [intermediate] → [target]
2. [file:function] → [intermediate] → [target]
3. [file:function] → [intermediate] → [target]
[continue...]

Level 3 Dependencies:
1. [file:function] → [L2] → [L1] → [target]
2. [file:function] → [L2] → [L1] → [target]
[continue...]

Dependency Chains:
- Longest Chain: [depth] levels
- Most Complex: [description]
- Most Critical: [which chain and why]

Total Indirect Dependencies: [count]

Transitive Closure Size:
[number of files transitively affected]

Dependency Graph Complexity: [simple/moderate/complex]
```

---

## Test 4: Assess Blast Radius

**Scenario:** Quantify the complete impact of the refactoring

### T4.1: Breaking Changes Analysis

**Objective:** Identify what will break during refactoring

**Execute:** Analyze breaking changes:
- What APIs are changing?
- What signatures are changing?
- What behavior is changing?
- What will stop compiling/running?

**Success Criteria:**
- Lists all breaking changes
- Categorizes by type
- Quantifies impact
- Prioritizes by severity

**Document:**
```
Breaking Changes:

API Changes:
1. [old API] → [new API]
   - Affected: [files/count]
   - Severity: [critical/high/medium/low]
   - Fixability: [automatic/manual/complex]

2. [old API] → [new API]
   - Affected: [files/count]
   - Severity: [critical/high/medium/low]
   - Fixability: [automatic/manual/complex]

[continue...]

Signature Changes:
1. [old signature] → [new signature]
   - Call Sites: [count]
   - Fix Effort: [hours/days]

[continue...]

Behavior Changes:
1. [what changes] - [old behavior] → [new behavior]
   - Impact: [description]
   - Tests Needed: [yes/no]

[continue...]

Total Breaking Changes: [count]
Auto-Fixable: [count]
Manual Fix Required: [count]
```

---

### T4.2: Risk Assessment

**Objective:** Assess risks and potential for failure

**Execute:** Identify risks:
- What could go wrong?
- What's the likelihood of each risk?
- What's the impact if it happens?
- How can we mitigate?

**Success Criteria:**
- Identifies 5-10 risks
- Assesses likelihood and impact
- Proposes mitigations
- Prioritizes risks

**Document:**
```
Risk Assessment:

Risk 1: [risk description]
- Likelihood: [high/medium/low]
- Impact: [critical/high/medium/low]
- Detection: [how we'll know if it happens]
- Mitigation: [how to prevent/minimize]
- Rollback: [how to undo]

Risk 2: [risk description]
- Likelihood: [high/medium/low]
- Impact: [critical/high/medium/low]
- Detection: [how we'll know if it happens]
- Mitigation: [how to prevent/minimize]
- Rollback: [how to undo]

[continue for 5-10 risks]

Highest Priority Risks:
1. [risk] - [why concerning]
2. [risk] - [why concerning]
3. [risk] - [why concerning]

Overall Risk Level: [critical/high/medium/low]
Refactoring Viable: [yes/no/with-conditions]
```

---

## Test 5: Migration Planning

**Scenario:** Create detailed step-by-step migration plan

### T5.1: Refactoring Sequence

**Objective:** Plan the sequence of changes to minimize breakage

**Execute:** Design migration sequence:
- What should change first?
- What depends on what?
- How to maintain working state?
- Where are the checkpoints?

**Success Criteria:**
- Detailed step-by-step plan
- Each step is safe
- Dependencies respected
- Rollback points identified

**Document:**
```
Migration Sequence:

Phase 1: Preparation
Step 1: [what to do]
- Files: [list]
- Purpose: [why this step]
- Validation: [how to verify]
- Duration: [estimate]
- Risk: [low/medium/high]

Step 2: [what to do]
- Files: [list]
- Purpose: [why this step]
- Validation: [how to verify]
- Duration: [estimate]
- Risk: [low/medium/high]

[continue...]

Phase 2: Core Migration
Step 3: [what to do]
- Files: [list]
- Purpose: [why this step]
- Validation: [how to verify]
- Duration: [estimate]
- Risk: [low/medium/high]

[continue...]

Phase 3: Update Usages
Step N: [what to do]
- Files: [list]
- Purpose: [why this step]
- Validation: [how to verify]
- Duration: [estimate]
- Risk: [low/medium/high]

[continue...]

Phase 4: Cleanup
[final steps]

Rollback Points:
- After Step [N]: [how to rollback]
- After Step [M]: [how to rollback]

Total Steps: [count]
Total Estimated Duration: [hours/days]
Confidence in Plan (1-10): [score]
```

---

### T5.2: Parallel Work Opportunities

**Objective:** Identify work that can be done in parallel

**Execute:** Find parallelizable work:
- What changes are independent?
- What can multiple people work on?
- How to coordinate?
- What must be sequential?

**Success Criteria:**
- Identifies parallel tracks
- Shows dependencies
- Coordinates timing
- Maximizes efficiency

**Document:**
```
Parallel Work Tracks:

Track 1: [description]
- Owner: [team/person]
- Steps: [which steps from main plan]
- Duration: [estimate]
- Dependencies: [what must finish first]
- Deliverable: [what's produced]

Track 2: [description]
- Owner: [team/person]
- Steps: [which steps from main plan]
- Duration: [estimate]
- Dependencies: [what must finish first]
- Deliverable: [what's produced]

[continue...]

Coordination Points:
1. [when] - [what syncs] - [who coordinates]
2. [when] - [what syncs] - [who coordinates]

Sequential Bottlenecks:
- [what must be sequential and why]

Time Savings:
- Sequential: [total hours]
- Parallel: [total hours]
- Savings: [%]
```

---

## Test 6: Risk Mitigation

**Scenario:** Plan safety measures and rollback strategies

### T6.1: Safety Measures

**Objective:** Define measures to prevent and detect problems

**Execute:** Plan safety measures:
- What tests to add/update?
- What monitoring to implement?
- What code reviews needed?
- What staging steps?

**Success Criteria:**
- Comprehensive test plan
- Monitoring strategy
- Review process
- Safe deployment plan

**Document:**
```
Safety Measures:

Testing Strategy:

Unit Tests:
- [ ] [test suite] - [coverage target]
- [ ] [test suite] - [coverage target]
- Total New Tests: [count]

Integration Tests:
- [ ] [test scenario] - [what it validates]
- [ ] [test scenario] - [what it validates]
- Total Integration Tests: [count]

Regression Tests:
- [ ] [critical path] - [must not break]
- [ ] [critical path] - [must not break]

Performance Tests:
- [ ] [benchmark] - [acceptable threshold]

Monitoring:
- Metric 1: [what to monitor] - [alert threshold]
- Metric 2: [what to monitor] - [alert threshold]

Code Review:
- Review Type: [depth/focus]
- Reviewers: [who/how many]
- Checklist: [key items]

Staged Rollout:
1. [environment] - [validation criteria]
2. [environment] - [validation criteria]
3. [environment] - [validation criteria]
```

---

### T6.2: Rollback Strategy

**Objective:** Plan how to undo changes if things go wrong

**Execute:** Design rollback approach:
- How to detect failure?
- What to rollback?
- How to rollback?
- Data migrations?

**Success Criteria:**
- Clear failure detection
- Fast rollback procedure
- Data handled safely
- Tested rollback

**Document:**
```
Rollback Strategy:

Failure Detection:
- Signal 1: [metric/behavior] - [threshold]
- Signal 2: [metric/behavior] - [threshold]
- Signal 3: [metric/behavior] - [threshold]

Decision Criteria:
[when to rollback vs. when to fix forward]

Rollback Procedure:

Step 1: [action]
- Duration: [estimate]
- Data Impact: [none/reversible/requires restore]

Step 2: [action]
- Duration: [estimate]
- Data Impact: [none/reversible/requires restore]

[continue...]

Total Rollback Time: [estimate]

Data Migration Rollback:
- Backward Migration: [yes/no - how]
- Data Backup: [what/when]
- Data Validation: [how to verify]

Rollback Testing:
- Test in: [environment]
- Verify: [what to check]
- Practice: [yes/no - when]

Confidence in Rollback (1-10): [score]
```

---

## Final Evaluation

### Refactoring Readiness Score

**Discovery Metrics:**
```
Components Found: [count]
Expected Components: [count]
Completeness: [%]
Target: 100%
Met Target: [yes/no]

Usages Found: [count]
Confidence All Found: [1-10]
Target: ≥9
Met Target: [yes/no]
```

**Planning Metrics:**
```
Migration Plan Completeness:
- All steps defined: [yes/no]
- Dependencies mapped: [yes/no]
- Risks identified: [yes/no]
- Mitigations planned: [yes/no]
- Rollback defined: [yes/no]

Completeness Score: [X]/5
Target: 5/5
Met Target: [yes/no]
```

**Confidence Metrics:**
```
Ready to Refactor: [yes/no]
Confidence Level: [1-10]
Target: ≥9
Met Target: [yes/no]

Could Execute Safely: [yes/no]
Could Rollback if Needed: [yes/no]
Team Could Execute: [yes/no]
```

**Time Metrics:**
```
Planning Duration: [minutes]
Target: ≤60 minutes
Met Target: [yes/no]

Estimated Execution: [hours/days]
Confidence in Estimate: [1-10]
```

### Production Readiness

**Critical Checks:**
- [ ] Found 100% of components to refactor
- [ ] Mapped all direct and indirect usages
- [ ] Assessed blast radius completely
- [ ] Identified all breaking changes
- [ ] Created detailed migration plan
- [ ] Defined safety measures
- [ ] Planned rollback strategy
- [ ] Confidence ≥9/10

**Pass/Fail:** [PASS/FAIL]

---

## Summary & Recommendations

### What Worked Well
```
[3-5 things that helped refactoring planning]
```

### What Was Challenging
```
[3-5 challenges in planning the refactoring]
```

### Refactoring Confidence

**Answer: [Very Confident / Confident / Somewhat Confident / Not Confident]**

**Reasoning:**
```
[2-3 paragraphs on:]
- Completeness of discovery
- Quality of impact analysis
- Safety of migration plan
- Confidence in execution
- Readiness to proceed
```

### Recommendations

**For Tool Improvement:**
```
[Suggestions to improve refactoring workflow]
```

**For Refactoring Process:**
```
[Process improvements or safety measures]
```

---

## Test Completion

**Test Metadata:**
```
Duration: [minutes]
Tester: [name/id]
Date: [YYYY-MM-DD]
Refactoring: [description]
Components Affected: [count]
Usages Found: [count]
Confidence Achieved: [score]/10
Ready to Proceed: [yes/no]
```

**Key Metrics:**
```
Discovery Completeness: [%]
Impact Assessment Completeness: [%]
Plan Detail Level: [high/medium/low]
Risk Mitigation: [comprehensive/adequate/insufficient]
Overall Success: [yes/no]
```

---

**Remember:** Major refactoring requires near-perfect understanding (≥9/10 confidence). Missing even one usage can cause production failures. Be thorough.
