# Use Case 8: Dependency Analysis

**Purpose:** Validate agent's ability to map dependencies and plan migrations
**Output Path:** test_results/dependency_analysis/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "What breaks if I change this dependency?"

---

## Test Suite Overview

This test evaluates how effectively an agent can analyze dependencies using Agent-Vault to:
- Find all direct and indirect usages
- Map complete dependency chains
- Assess coupling levels
- Identify abstraction boundaries
- Quantify migration effort
- Plan safe migration paths

### Success Criteria

Dependency analysis is successful if the agent can:
- Map complete dependency tree (100% coverage)
- Identify all abstraction layers
- Quantify coupling accurately
- Estimate migration effort
- Propose safe migration strategy
- Achieve ≥9/10 confidence (critical for migration decisions)

**Time Limit:** 30 minutes for complete dependency analysis
**Confidence Threshold:** 9/10 or higher on "understand dependencies" scale

---

## Pre-Test Setup

### Prerequisites

> **CRITICAL: You MUST index the codebase yourself.** Do NOT assume pre-existing data is valid.
> Tests that skip indexing will fail because relationships won't exist for your project_id.

**Step 1: Create Session with Unique Project ID**
```python
# Use the naming convention from USE_CASES.md
project_id = "agv_test09_deps_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Dependency analysis test")
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

1. **Dependency Selected:** Choose a critical dependency to analyze (see examples below)
2. **Migration Goal:** Define what you're trying to achieve
3. **Risk Assessment:** Understand why this is high-stakes

### Dependency Selection

Choose ONE critical dependency appropriate for your codebase:

**For infrastructure dependencies:**
- "LanceDB database (storage layer)"
- "Redis cache (caching layer)"
- "Message queue (async processing)"
- "Authentication service"

**For framework dependencies:**
- "Web framework (FastAPI, Flask, etc.)"
- "ORM/database library"
- "Serialization library"
- "Logging framework"

**For core libraries:**
- "Embedding provider API"
- "Vector search engine"
- "Text processing library"

**Document Your Dependency:**
```
Dependency Analysis:
Target: [dependency name]
Example: "LanceDB (storage layer)"

Current Usage:
[how it's currently used]

Migration Goal:
[what you're trying to achieve]
Example: "Evaluate upgrading to v2" or "Consider alternatives"

Risk Level: [critical/high/medium/low]

Constraint:
[any constraints - zero downtime, data preservation, etc.]
```

---

## Test 1: Find Direct Usages

**Scenario:** Locate every place that directly uses the dependency

### T1.1: Import and Usage Discovery

**Objective:** Find all files that import or reference the dependency

**Execute:** Search for direct usage:
- What files import the dependency?
- Where is it instantiated?
- What classes/functions use it?
- What's the import pattern?

**Success Criteria:**
- Finds all import statements
- Locates all instantiations
- Identifies usage patterns
- Provides file:line locations

**Document:**
```
Direct Usage Discovery:

Import Search:
Query: [import statement pattern]
- Files Found: [count]
- Import Patterns: [list unique patterns]

Import Locations:
1. [file:line]
   - Import: [import statement]
   - Alias: [if any]
   - Usage: [where used in file]

2. [file:line]
   - Import: [import statement]
   - Alias: [if any]
   - Usage: [where used in file]

[Continue for all imports]

Instantiation Sites:
1. [file:function:line]
   - Code: [how it's created]
   - Context: [where/why]
   - Pattern: [singleton/factory/direct/etc]

2. [file:function:line]
   - Code: [how it's created]
   - Context: [where/why]
   - Pattern: [singleton/factory/direct/etc]

[Continue for all instantiations]

Total Import Sites: [count]
Total Instantiations: [count]
Discovery Time: [minutes]
```

---

### T1.2: Direct Usage Patterns

**Objective:** Understand how the dependency is used directly

**Execute:** Analyze usage patterns:
- What operations are performed?
- What methods are called?
- What features are used?
- What's the usage intensity?

**Success Criteria:**
- Catalogs all operations
- Identifies most-used features
- Measures usage intensity
- Spots patterns

**Document:**
```
Usage Pattern Analysis:

Operations Performed:

Operation 1: [operation name]
- Methods Called: [list]
- Frequency: [high/medium/low]
- Locations: [count] sites
- Example: [file:line]

Operation 2: [operation name]
- Methods Called: [list]
- Frequency: [high/medium/low]
- Locations: [count] sites
- Example: [file:line]

[Continue for all operations]

Most Used Features:
1. [feature] - Used at [count] sites
2. [feature] - Used at [count] sites
3. [feature] - Used at [count] sites

Least Used Features:
- [feature] - Used at [count] sites
- [feature] - Used at [count] sites

Feature Coverage:
- Total Features Available: [count]
- Features Actually Used: [count]
- Coverage: [%]

Usage Intensity: [heavy/moderate/light]
Usage Diversity: [focused/varied/broad]
```

---

## Test 2: Find Indirect Dependencies

**Scenario:** Map what depends on code that depends on the dependency

### T2.1: Second-Level Dependencies

**Objective:** Find code that depends on direct users

**Execute:** Trace dependency chain:
- What calls code that uses the dependency?
- What depends on those components?
- How deep is the dependency chain?
- What's the transitive closure?

**Success Criteria:**
- Maps level-2 dependencies
- Traces dependency chains
- Quantifies scope
- Shows relationships

**Document:**
```
Second-Level Dependencies:

Direct User 1: [component that imports dependency]
↓ Used By:
1. [component] - [file:path]
   - How: [calls/imports/inherits]
   - Frequency: [high/medium/low]

2. [component] - [file:path]
   - How: [calls/imports/inherits]
   - Frequency: [high/medium/low]

[Continue...]

Direct User 2: [component that imports dependency]
↓ Used By:
[Same structure...]

Level 2 Dependency Count: [count]

Dependency Chains:

Chain 1:
[Root] → [Direct User] → [L2] → [L3]
- Depth: [levels]
- Strength: [tight/moderate/loose]

Chain 2:
[Root] → [Direct User] → [L2]
- Depth: [levels]
- Strength: [tight/moderate/loose]

Longest Chain: [depth] levels
Most Complex Chain: [description]
```

---

### T2.2: Transitive Closure

**Objective:** Calculate complete set of affected code

**Execute:** Map full dependency tree:
- What's the complete set of affected files?
- How many components transitively depend?
- What's the total scope?
- Where are the boundaries?

**Success Criteria:**
- Complete dependency set
- Accurate count
- Identifies boundaries
- Shows scope

**Document:**
```
Transitive Dependency Closure:

Complete Dependency Tree:

Level 0 (Direct): [count] files
- [file1]
- [file2]
- [file3]
[continue...]

Level 1 (Indirect): [count] files
- [file1]
- [file2]
[continue...]

Level 2: [count] files
- [file1]
- [file2]

Level 3+: [count] files

Total Affected Files: [count]
Total Affected Components: [count]
Total Affected LOC: [estimate]

Dependency Boundaries:

Strong Boundary 1:
- Location: [component/layer]
- Isolates: [what's isolated]
- Strength: [strong/weak]

Strong Boundary 2:
- Location: [component/layer]
- Isolates: [what's isolated]
- Strength: [strong/weak]

Scope Assessment: [very large/large/medium/small]
Migration Risk: [critical/high/medium/low]
```

---

## Test 3: Assess Coupling Level

**Scenario:** Evaluate how tightly coupled the dependency is

### T3.1: Coupling Analysis

**Objective:** Measure coupling strength and types

**Execute:** Assess coupling:
- How tight is the coupling?
- What types of coupling exist?
- Where is coupling strongest?
- Can it be reduced?

**Success Criteria:**
- Categorizes coupling types
- Measures strength
- Identifies tight spots
- Suggests improvements

**Document:**
```
Coupling Assessment:

Coupling Types Found:

1. Data Coupling
   - Locations: [count]
   - Severity: [tight/moderate/loose]
   - Examples:
     - [file:line] - [description]
     - [file:line] - [description]

2. Stamp Coupling
   - Locations: [count]
   - Severity: [tight/moderate/loose]
   - Examples:
     - [file:line] - [description]

3. Control Coupling
   - Locations: [count]
   - Severity: [tight/moderate/loose]
   - Examples:
     - [file:line] - [description]

4. Common Coupling
   - Locations: [count]
   - Severity: [tight/moderate/loose]
   - Examples:
     - [file:line] - [description]

5. Content Coupling
   - Locations: [count]
   - Severity: [critical/high/medium/low]
   - Examples:
     - [file:line] - [description]

Tightest Coupling Points:

1. [location]
   - Type: [coupling type]
   - Why Tight: [explanation]
   - Impact: [what breaks if changed]
   - Reducible: [yes/no - how]

2. [location]
   [Same structure...]

Overall Coupling: [very tight/tight/moderate/loose]
Migration Difficulty: [very hard/hard/moderate/easy]
```

---

### T3.2: Interface Analysis

**Objective:** Analyze how dependency is accessed

**Execute:** Examine interfaces:
- Is there an abstraction layer?
- How clean are the interfaces?
- Where does dependency leak?
- What's the API surface?

**Success Criteria:**
- Identifies abstraction layers
- Measures interface quality
- Finds leakage points
- Assesses API surface

**Document:**
```
Interface Analysis:

Abstraction Layers:

Layer 1: [name/component]
- Location: [file:path]
- Purpose: [what it abstracts]
- Quality: [clean/leaky/non-existent]
- Coverage: [% of dependency hidden]

Layer 2: [name/component]
[Same structure...]

Interface Leakage:

Leak 1:
- Location: [file:line]
- Problem: [dependency-specific type/concept exposed]
- Severity: [high/medium/low]
- Fix: [how to abstract]

Leak 2:
[Same structure...]

API Surface:

Direct Dependency API:
- Methods: [count]
- Complexity: [high/medium/low]

Abstracted API:
- Methods: [count]
- Complexity: [high/medium/low]
- Abstraction Quality: [excellent/good/poor]

Interface Quality: [well-abstracted/partially-abstracted/not-abstracted]
Leakage Points: [count]
Migration Impact: [high/medium/low based on abstraction]
```

---

## Test 4: Find Abstraction Layers

**Scenario:** Identify existing abstractions and their quality

### T4.1: Protocol/Interface Discovery

**Objective:** Find protocols, interfaces, and abstract base classes

**Execute:** Search for abstractions:
- What protocols/interfaces exist?
- What do they abstract?
- How complete are they?
- Are they actually used?

**Success Criteria:**
- Finds all abstractions
- Evaluates completeness
- Checks actual usage
- Assesses quality

**Document:**
```
Abstraction Discovery:

Protocols/Interfaces Found:

Protocol 1: [name]
- Location: [file:path]
- Purpose: [what it abstracts]
- Methods Defined: [count]
- Implementations: [count]
- Used By: [count] components

Completeness:
- Abstracts All Operations: [yes/no]
- Missing Operations: [list]
- Abstraction Level: [appropriate/too low/too high]

Protocol 2: [name]
[Same structure...]

Abstract Base Classes:

ABC 1: [name]
- Location: [file:path]
- Purpose: [what it abstracts]
- Abstract Methods: [count]
- Concrete Implementations: [count]
- Usage: [where used]

Adapter/Wrapper Classes:

Adapter 1: [name]
- Location: [file:path]
- Wraps: [what dependency]
- Abstracts: [how much]
- Quality: [excellent/good/poor]

Total Abstractions: [count]
Abstraction Coverage: [%]
Abstraction Quality: [excellent/good/adequate/poor]
```

---

### T4.2: Abstraction Effectiveness

**Objective:** Assess if abstractions actually help migration

**Execute:** Evaluate abstractions:
- Do abstractions hide the dependency?
- Can dependency be swapped?
- What leaks through?
- What needs improvement?

**Success Criteria:**
- Tests abstraction isolation
- Evaluates swappability
- Identifies improvements
- Assesses migration readiness

**Document:**
```
Abstraction Effectiveness:

Isolation Test:

Can Dependency Be Replaced?
- Behind Abstraction: [yes/no/partially]
- Changes Needed: [list if no]

Dependency-Specific Concepts Leaked:
1. [concept] - [where leaked] - [impact]
2. [concept] - [where leaked] - [impact]

Swappability Assessment:

To Swap Dependency:
1. [change required]
   - Location: [where]
   - Effort: [hours/days]
   - Risk: [high/medium/low]

2. [change required]
   [Same structure...]

Total Changes Required: [count]
Total Effort: [hours/days]

Abstraction Improvements Needed:

Improvement 1: [what to improve]
- Current Problem: [issue]
- Suggested Fix: [solution]
- Benefit: [impact on migration]

Improvement 2:
[Same structure...]

Migration Readiness:
- With Current Abstractions: [ready/partially/not ready]
- With Improvements: [ready/partially/not ready]
- Abstraction Quality: [excellent/good/needs work/poor]
```

---

## Test 5: Plan Migration Path

**Scenario:** Design strategy for migrating to alternative

### T5.1: Migration Strategy

**Objective:** Plan how to replace or upgrade the dependency

**Execute:** Design migration:
- What's the target (upgrade/replace)?
- What's the migration approach?
- What's the sequence?
- What are the milestones?

**Success Criteria:**
- Clear target state
- Detailed approach
- Safe sequence
- Measurable milestones

**Document:**
```
Migration Strategy:

Current State:
- Dependency: [name and version]
- Usage: [description]
- Coupling: [level]

Target State:
- New Dependency: [name and version] or [alternative]
- Why: [rationale]
- Benefits: [list]

Migration Approach: [big bang / strangler pattern / parallel run / etc]

Reasoning:
[why this approach]

Migration Sequence:

Phase 1: Preparation
Step 1: [what to do]
- Purpose: [why]
- Duration: [estimate]
- Validation: [how to verify]

Step 2: [what to do]
[Same structure...]

Phase 2: Abstraction (if needed)
Step 3: [what to do]
[Same structure...]

Phase 3: Implementation
Step 4: [what to do]
[Same structure...]

Phase 4: Validation
Step 5: [what to do]
[Same structure...]

Phase 5: Cleanup
Step 6: [what to do]
[Same structure...]

Milestones:
- [ ] [milestone] - Completion Criteria: [specific]
- [ ] [milestone] - Completion Criteria: [specific]
- [ ] [milestone] - Completion Criteria: [specific]

Total Steps: [count]
Estimated Duration: [weeks/months]
```

---

### T5.2: Risk Mitigation

**Objective:** Identify and plan for migration risks

**Execute:** Plan risk mitigation:
- What could go wrong?
- How to prevent issues?
- How to detect problems?
- How to rollback?

**Success Criteria:**
- Identifies all major risks
- Plans prevention
- Defines detection
- Enables rollback

**Document:**
```
Migration Risk Mitigation:

Risks Identified:

Risk 1: [description]
- Likelihood: [high/medium/low]
- Impact: [critical/high/medium/low]
- Prevention:
  - [action to prevent]
  - [action to prevent]
- Detection:
  - [how to detect if it happens]
  - [metrics to monitor]
- Mitigation:
  - [what to do if it happens]
- Rollback:
  - [how to undo]

Risk 2: [description]
[Same structure...]

[Continue for all significant risks]

Rollback Strategy:

Rollback Triggers:
- [metric/condition] - Threshold: [value]
- [metric/condition] - Threshold: [value]

Rollback Procedure:
1. [step]
2. [step]
3. [step]

Rollback Time: [estimate]
Data Safety: [preserved/at-risk/requires-backup]

Safety Measures:

1. [safety measure]
   - Type: [testing/monitoring/backup/etc]
   - When: [phase]
   - Purpose: [what it protects against]

2. [safety measure]
   [Same structure...]

Overall Risk Level: [critical/high/medium/low]
Migration Viability: [safe/risky/very risky]
```

---

## Test 6: Estimate Effort

**Scenario:** Quantify the work required for migration

### T6.1: Work Breakdown

**Objective:** Break down migration into measurable tasks

**Execute:** Estimate effort:
- What code needs changing?
- What tests need updating?
- What documentation needs revision?
- What's the total effort?

**Success Criteria:**
- Comprehensive task list
- Realistic estimates
- All work included
- Confidence in estimates

**Document:**
```
Effort Estimation:

Code Changes:

Direct Dependency Usage:
- Files to Modify: [count]
- LOC to Change: [estimate]
- Complexity: [high/medium/low]
- Effort: [hours/days]

Abstraction Layer:
- Create New: [yes/no] - Effort: [hours]
- Modify Existing: [yes/no] - Effort: [hours]

Indirect Dependencies:
- Files to Review: [count]
- Files to Modify: [estimate]
- Effort: [hours/days]

Test Changes:

Unit Tests:
- Tests to Update: [count]
- Tests to Create: [count]
- Effort: [hours/days]

Integration Tests:
- Tests to Update: [count]
- Tests to Create: [count]
- Effort: [hours/days]

Documentation:

API Documentation: [hours]
User Guides: [hours]
Architecture Docs: [hours]
Migration Guide: [hours]

Total Documentation Effort: [hours]

Effort Summary:

Code Development: [hours/days]
Testing: [hours/days]
Documentation: [hours/days]
Code Review: [hours/days]
Deployment: [hours/days]

Total Effort: [hours/days/weeks]
Team Size: [people]
Calendar Time: [weeks/months]
```

---

### T6.2: Cost-Benefit Analysis

**Objective:** Evaluate if migration is worth the effort

**Execute:** Analyze costs vs benefits:
- What are the costs?
- What are the benefits?
- What are the risks?
- Is it worth it?

**Success Criteria:**
- Quantifies costs
- Quantifies benefits
- Assesses risks
- Makes recommendation

**Document:**
```
Cost-Benefit Analysis:

Costs:

Development Effort:
- Hours: [total]
- Cost: [$ if relevant]

Risk Costs:
- Downtime Risk: [hours] × [cost/hour] = [total]
- Bug Risk: [probability] × [impact] = [risk cost]

Opportunity Cost:
- What Else Could Be Done: [features/improvements]
- Value: [estimate]

Total Cost: [hours + risk + opportunity]

Benefits:

Performance:
- Improvement: [metric]
- Value: [$ or impact]

Features:
- New Capabilities: [list]
- Value: [estimate]

Maintenance:
- Reduced Complexity: [description]
- Time Saved: [hours/year]
- Value: [$/year]

Risk Reduction:
- Current Risk: [description]
- Reduced Risk: [how much]
- Value: [estimate]

Total Benefits: [quantified]

Analysis:

Cost-Benefit Ratio: [benefit/cost]
Payback Period: [time to recoup cost]
Net Present Value: [if applicable]

Recommendation: [do it / don't do it / defer / do with modifications]

Reasoning:
[2-3 paragraphs explaining recommendation]

Confidence in Recommendation (1-10): [score]
```

---

## Final Evaluation

### Dependency Analysis Metrics

**Discovery Metrics:**
```
Direct Usages Found: [count]
Indirect Dependencies: [count]
Total Affected Files: [count]
Discovery Completeness: [%]
Target: 100%
Met Target: [yes/no]
```

**Analysis Metrics:**
```
Coupling Level: [very tight/tight/moderate/loose]
Abstraction Quality: [excellent/good/adequate/poor]
Migration Difficulty: [very hard/hard/moderate/easy]

Dependency Tree Depth: [levels]
Strongest Coupling: [location]
Weakest Abstraction: [location]
```

**Planning Metrics:**
```
Migration Strategy: [defined/partial/undefined]
Risk Assessment: [comprehensive/adequate/minimal]
Effort Estimate: [detailed/rough/none]
Confidence in Plan: [1-10]

Target: ≥9 confidence
Met Target: [yes/no]
```

**Time Metrics:**
```
Analysis Duration: [minutes]
Target: ≤30 minutes
Met Target: [yes/no]

Breakdown:
- Direct Usage Discovery: [minutes]
- Indirect Dependencies: [minutes]
- Coupling Assessment: [minutes]
- Abstraction Analysis: [minutes]
- Migration Planning: [minutes]
```

### Production Readiness

**Critical Checks:**
- [ ] 100% of dependencies mapped
- [ ] All coupling points identified
- [ ] Abstraction layers evaluated
- [ ] Migration path defined
- [ ] Risks identified and mitigated
- [ ] Effort estimated realistically
- [ ] Cost-benefit analyzed
- [ ] Confidence ≥9/10

**Pass/Fail:** [PASS/FAIL]

---

## Summary & Recommendations

### What Worked Well
```
[3-5 things that helped dependency analysis]
```

### What Was Challenging
```
[3-5 challenges in analyzing dependencies]
```

### Analysis Effectiveness

**Answer: [Very Effective / Effective / Somewhat Effective / Not Effective]**

**Reasoning:**
```
[2-3 paragraphs on:]
- Completeness of dependency mapping
- Quality of coupling assessment
- Viability of migration plan
- Confidence in proceeding
- Value of the analysis
```

### Recommendations

**For Migration:**
```
[Specific recommendations about whether/how to migrate]
```

**For Architecture:**
```
[Suggestions to improve abstraction and reduce coupling]
```

---

## Test Completion

**Test Metadata:**
```
Duration: [minutes]
Tester: [name/id]
Date: [YYYY-MM-DD]
Dependency Analyzed: [name]
Files Affected: [count]
Migration Effort: [hours/days]
Confidence Achieved: [score]/10
Recommendation: [proceed/defer/don't do]
```

**Key Metrics:**
```
Dependency Coverage: [%]
Coupling Level: [tight/moderate/loose]
Abstraction Quality: [high/medium/low]
Migration Viability: [yes/no/with-changes]
Overall Success: [yes/no]
```

---

**Remember:** Dependency analysis for migration is high-stakes. Missing dependencies or underestimating coupling can lead to production failures. Aim for ≥9/10 confidence.
