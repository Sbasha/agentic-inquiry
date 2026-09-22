# Use Case 3: Feature Implementation

**Purpose:** Validate agent's ability to implement new features by finding patterns and understanding insertion points
**Output Path:** test_results/feature_implementation/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Can I add a feature without breaking existing code?"

---

## Test Suite Overview

This test evaluates how effectively an agent can implement a new feature using Agentic Inquiry to:
- Find related existing code
- Understand implementation patterns
- Identify correct insertion points
- Assess dependencies and impact
- Ensure consistency with codebase conventions

### Success Criteria

Feature implementation is successful if the agent can:
- Find all related existing code within 5 queries
- Identify the correct implementation pattern
- Know where to add new code
- List all affected components
- Implement without breaking existing functionality

**Time Limit:** 45 minutes from task assignment to implementation plan
**Confidence Threshold:** 8/10 or higher on "ready to implement" scale

---

## Pre-Test Setup

### Prerequisites

> **CRITICAL: You MUST index the codebase yourself.** Do NOT assume pre-existing data is valid.
> See USE_CASES.md "Ensure Fresh Index" for detailed instructions.

**Step 1: Create Session with Unique Project ID**
```python
project_id = "ai_test03_feature_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Feature implementation test")
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

1. **Feature Defined:** Choose a realistic feature to implement (see examples below)
2. **Understanding:** Basic familiarity with codebase (run TEST_02_ONBOARDING first)

### Feature Selection

Choose ONE feature appropriate for your codebase:

**For web applications:**
- Add support for new authentication method (e.g., OAuth provider)
- Add new API endpoint with similar functionality to existing ones
- Add new data export format (e.g., CSV export where only JSON exists)

**For libraries:**
- Add support for new file format (e.g., JSON where YAML exists)
- Add new search algorithm option
- Add new caching strategy

**For CLI tools:**
- Add new command similar to existing commands
- Add new output format
- Add new data source integration

**Document Your Feature:**
```
Feature: [clear description]
Example: "Add support for YAML configuration files"

Current State: [what exists now]
Example: "System currently supports only JSON config files"

Desired State: [what should exist]
Example: "System should support both JSON and YAML config files"

Success Criteria: [how you'll know it works]
Example: "Can load config from .yaml files same as .json files"
```

---

## Test 1: Find Related Code

**Scenario:** Find existing code that's similar to what you need to build

### T1.1: Existing Implementation Search

**Objective:** Locate code that implements similar functionality

**Execute:** Search for existing implementations:
- How is similar functionality currently implemented?
- What files contain related code?
- What patterns are being used?

**Success Criteria:**
- Finds existing implementation within 3 queries
- Identifies all relevant files
- Understands current approach
- Can describe how it works

**Document:**
```
Search Strategy:

Query 1: [query]
- Results: [count]
- Relevant: [count]
- Key Finding: [what you learned]

Query 2: [query]
- Results: [count]
- Relevant: [count]
- Key Finding: [what you learned]

Query 3: [query]
- Results: [count]
- Relevant: [count]
- Key Finding: [what you learned]

Related Code Found:
1. [file:path] - [purpose] - [relevance]
2. [file:path] - [purpose] - [relevance]
3. [file:path] - [purpose] - [relevance]
...

Time to Discovery: [minutes]
Confidence in Findings (1-10): [score]
```

---

### T1.2: Pattern Recognition

**Objective:** Understand the pattern used for similar features

**Execute:** Analyze the related code to identify:
- What design pattern is used?
- How is the implementation structured?
- What are the key components?
- How do they interact?

**Success Criteria:**
- Identifies the pattern clearly
- Understands why it's used
- Can describe implementation steps
- Knows what to replicate

**Document:**
```
Pattern Analysis:

Design Pattern: [name/description]
Example: "Factory pattern with registration"

Structure:
1. [component] - [role] - [file:path]
2. [component] - [role] - [file:path]
3. [component] - [role] - [file:path]

Interaction Flow:
[describe how components work together]

Why This Pattern:
[reasoning based on code observations]

Should Follow Same Pattern: [yes/no]
Reasoning: [why/why not]
```

---

### T1.3: Code Convention Discovery

**Objective:** Identify conventions that new code should follow

**Execute:** Look for conventions in related code:
- Naming conventions
- File organization patterns
- Error handling approach
- Testing patterns
- Documentation style

**Success Criteria:**
- Lists 5+ conventions
- Shows examples from codebase
- Understands importance
- Can apply to new code

**Document:**
```
Conventions Identified:

1. Naming:
   - Pattern: [description]
   - Example: [from code]
   
2. File Organization:
   - Pattern: [description]
   - Example: [from code]

3. Error Handling:
   - Pattern: [description]
   - Example: [from code]

4. Testing:
   - Pattern: [description]
   - Example: [from code]

5. Documentation:
   - Pattern: [description]
   - Example: [from code]

[Add more as needed]

Consistency Level: [high/medium/low]
Easy to Follow: [yes/no]
```

---

## Test 2: Identify Insertion Points

**Scenario:** Determine where new code should be added

### T2.1: Primary Implementation Location

**Objective:** Find where to add the main implementation

**Execute:** Determine:
- Which file(s) should contain the new code?
- Where in each file should it go?
- Should you create new files or modify existing ones?

**Success Criteria:**
- Identifies correct file(s)
- Specifies approximate line numbers or sections
- Reasoning is sound
- Follows codebase organization patterns

**Document:**
```
Primary Implementation:

File: [path]
Location: [line number or section description]
Reasoning: [why here]
New File Needed: [yes/no]

If New File:
- Location: [directory]
- Name: [filename]
- Reasoning: [why new file]

Alternative Locations Considered:
1. [location] - Rejected because: [reason]
2. [location] - Rejected because: [reason]

Confidence (1-10): [score]
```

---

### T2.2: Integration Points

**Objective:** Identify where new code needs to connect with existing code

**Execute:** Find:
- What existing code will call your new feature?
- What will your new feature call?
- Where do you register/wire up the new feature?
- What interfaces need to be implemented?

**Success Criteria:**
- Identifies all integration points
- Provides file:line locations
- Understands data flow
- No missing connections

**Document:**
```
Integration Points:

1. Registration/Setup:
   - Location: [file:line]
   - What to Add: [description]
   - Example from Similar: [file:line]

2. Entry Point:
   - Location: [file:line]
   - What Calls New Code: [description]
   - Data Passed In: [types/format]

3. Dependencies:
   - What New Code Calls: [list with locations]
   - Interfaces to Implement: [list]
   - Services to Inject: [list]

4. Configuration:
   - Location: [file:line]
   - What to Add: [description]

Total Integration Points: [count]
Complexity: [low/medium/high]
```

---

### T2.3: Test Location

**Objective:** Determine where to add tests for new feature

**Execute:** Find:
- Where are similar features tested?
- What test file(s) should you create/modify?
- What test patterns are used?
- What fixtures/helpers are available?

**Success Criteria:**
- Identifies correct test location
- Knows test file naming convention
- Understands test patterns
- Can list required test cases

**Document:**
```
Test Strategy:

Test File Location:
- Directory: [path]
- Filename: [name]
- Follows Pattern: [yes/no - pattern description]

Similar Test Example:
- File: [path]
- Tests: [what it tests]
- Pattern: [how it's structured]

Test Cases Needed:
1. [test case description]
2. [test case description]
3. [test case description]
...

Fixtures Available:
- [fixture] - [purpose] - [location]
- [fixture] - [purpose] - [location]

Test Confidence (1-10): [score]
```

---

## Test 3: Dependency Analysis

**Scenario:** Understand what depends on your changes

### T3.1: Direct Dependencies

**Objective:** Identify code that will directly depend on new feature

**Execute:** Find:
- What existing code might use your new feature?
- What imports/references will you add?
- What interfaces are you implementing?

**Success Criteria:**
- Lists direct dependencies
- Provides file locations
- Understands impact
- No surprises

**Document:**
```
Direct Dependencies:

Code That Will Use New Feature:
1. [component] - [file:path] - [how it will use it]
2. [component] - [file:path] - [how it will use it]
...

New Imports/References:
- In [file]: import [what]
- In [file]: reference [what]

Interfaces Implemented:
- [interface] - [file:path] - [methods needed]

Dependency Risk: [low/medium/high]
Reasoning: [why]
```

---

### T3.2: Impact Assessment

**Objective:** Assess blast radius of adding this feature

**Execute:** Analyze:
- What breaks if implementation is wrong?
- What tests might fail?
- What backward compatibility issues exist?
- What side effects are possible?

**Success Criteria:**
- Identifies all risks
- Categorizes by severity
- Plans mitigation
- Knows what to monitor

**Document:**
```
Impact Assessment:

Risk Categories:

1. Breaking Changes:
   - Risk: [description]
   - Affected: [what/where]
   - Severity: [high/medium/low]
   - Mitigation: [approach]

2. Backward Compatibility:
   - Risk: [description]
   - Affected: [what/where]
   - Severity: [high/medium/low]
   - Mitigation: [approach]

3. Performance:
   - Risk: [description]
   - Affected: [what/where]
   - Severity: [high/medium/low]
   - Mitigation: [approach]

Tests That Might Fail:
- [test file] - [why it might fail]
- [test file] - [why it might fail]

Monitoring Needed:
- [what to watch]
- [how to verify]

Overall Risk: [low/medium/high]
Confidence in Assessment (1-10): [score]
```

---

## Test 4: Implementation Planning

**Scenario:** Create detailed implementation plan

### T4.1: Step-by-Step Plan

**Objective:** Break down implementation into clear steps

**Execute:** Create implementation sequence:
1. What to create first?
2. What to modify second?
3. What to test third?
4. What to integrate fourth?

**Success Criteria:**
- Steps are in logical order
- Each step is actionable
- Dependencies respected
- Can estimate time

**Document:**
```
Implementation Plan:

Phase 1: Foundation
Step 1: [what to do]
- Files: [list]
- Time Estimate: [minutes]
- Validation: [how to verify]

Step 2: [what to do]
- Files: [list]
- Time Estimate: [minutes]
- Validation: [how to verify]

Phase 2: Integration
Step 3: [what to do]
- Files: [list]
- Time Estimate: [minutes]
- Validation: [how to verify]

Step 4: [what to do]
- Files: [list]
- Time Estimate: [minutes]
- Validation: [how to verify]

Phase 3: Testing
Step 5: [what to do]
- Files: [list]
- Time Estimate: [minutes]
- Validation: [how to verify]

Phase 4: Documentation
Step 6: [what to do]
- Files: [list]
- Time Estimate: [minutes]
- Validation: [how to verify]

Total Steps: [count]
Total Time Estimate: [hours]
Confidence in Plan (1-10): [score]
```

---

### T4.2: Code Checklist

**Objective:** Create checklist of what code to write

**Execute:** List all code artifacts:
- New files to create
- Existing files to modify
- Tests to write
- Docs to update

**Success Criteria:**
- Complete list of artifacts
- Nothing forgotten
- Follows patterns
- Matches conventions

**Document:**
```
Code Checklist:

New Files:
- [ ] [filename] - [purpose] - [estimated LOC]
- [ ] [filename] - [purpose] - [estimated LOC]
- [ ] [filename] - [purpose] - [estimated LOC]

Modified Files:
- [ ] [filename] - [what to change] - [estimated LOC]
- [ ] [filename] - [what to change] - [estimated LOC]
- [ ] [filename] - [what to change] - [estimated LOC]

Test Files:
- [ ] [filename] - [what to test] - [estimated LOC]
- [ ] [filename] - [what to test] - [estimated LOC]

Documentation:
- [ ] [filename] - [what to document]
- [ ] [filename] - [what to document]

Configuration:
- [ ] [filename] - [what to add]

Total Artifacts: [count]
Estimated Total LOC: [count]
Complexity: [low/medium/high]
```

---

## Test 5: Knowledge Capture

**Scenario:** Store implementation decisions for reference

### T5.1: Store Implementation Plan

**Objective:** Persist the implementation plan and decisions

**Execute:** Store memories about:
- Feature implementation approach
- Pattern to follow
- Integration points
- Risk mitigation strategies

**Success Criteria:**
- All key decisions stored
- Tagged for retrieval
- Importance levels set
- Can be recalled

**Document:**
```
Memories Stored:

1. Implementation Approach
   - Summary: [brief]
   - Importance: [0.0-1.0]
   - Tags: [tags]

2. Pattern to Follow
   - Summary: [brief]
   - Importance: [0.0-1.0]
   - Tags: [tags]

3. Integration Points
   - Summary: [brief]
   - Importance: [0.0-1.0]
   - Tags: [tags]

4. Risks and Mitigation
   - Summary: [brief]
   - Importance: [0.0-1.0]
   - Tags: [tags]

Total Memories: [count]
Storage Success: [yes/no]
```

---

### T5.2: Verify Retrievability

**Objective:** Ensure stored knowledge is accessible

**Execute:** Query for implementation knowledge:
- By feature name
- By pattern
- By affected component

**Success Criteria:**
- Retrieves all memories
- Results are complete
- Can reconstruct plan

**Document:**
```
Retrieval Test:

Query: [feature name]
- Memories Found: [count]
- Complete Plan Retrieved: [yes/no]

Query: [pattern name]
- Memories Found: [count]
- Pattern Details Retrieved: [yes/no]

Overall Retrievability: [excellent/good/poor]
Would Rely on Memory: [yes/no]
```

---

## Final Evaluation

### Implementation Readiness Score

**Discovery Metrics:**
```
Time to Find Patterns: [minutes]
Queries Needed: [count]
Pattern Match Accuracy: [%]
Target: ≤5 queries, ≤15 minutes
Met Target: [yes/no]
```

**Planning Metrics:**
```
Implementation Plan Completeness:
- All insertion points identified: [yes/no]
- All integration points identified: [yes/no]
- All risks identified: [yes/no]
- Test strategy defined: [yes/no]

Completeness Score: [X]/4
Target: 4/4
Met Target: [yes/no]
```

**Confidence Metrics:**
```
Ready to Implement: [yes/no]
Confidence Level: [1-10]
Could Code Without Help: [yes/no]
Could Pass Code Review: [yes/no]
Follows Codebase Patterns: [yes/no]
```

### Production Readiness

**Critical Checks:**
- [ ] Found all related code in ≤5 queries
- [ ] Identified correct pattern
- [ ] Knows exact insertion points
- [ ] Understands all integration points
- [ ] Has complete test strategy
- [ ] Risks identified and mitigated
- [ ] Plan is actionable
- [ ] Confidence ≥8/10

**Pass/Fail:** [PASS/FAIL]

---

## Summary & Recommendations

### What Worked Well
```
[3-5 things that helped feature planning]
```

### What Was Challenging
```
[3-5 challenges in finding information]
```

### Implementation Confidence

**Answer: [Very Confident / Confident / Somewhat Confident / Not Confident]**

**Reasoning:**
```
[2-3 paragraphs on:]
- Quality of pattern discovery
- Completeness of implementation plan
- Understanding of integration points
- Readiness to code
```

### Recommendations

**For Tool Improvement:**
```
[Suggestions to improve feature implementation workflow]
```

**For Codebase:**
```
[Patterns or conventions that could be clearer]
```

---

## Test Completion

**Test Metadata:**
```
Duration: [minutes]
Tester: [name/id]
Date: [YYYY-MM-DD]
Feature: [description]
Queries Executed: [count]
Confidence Achieved: [score]/10
Ready to Implement: [yes/no]
```

**Key Metrics:**
```
Pattern Discovery Time: [minutes]
Integration Points Found: [count]
Risks Identified: [count]
Plan Completeness: [%]
Overall Success: [yes/no]
```

---

**Remember:** Successful feature implementation means you can code with confidence, following established patterns, without breaking existing functionality.
