# Use Case 2: Onboarding to a New Codebase

**Purpose:** Validate agent's ability to quickly understand and navigate an unfamiliar codebase
**Output Path:** test_results/onboarding/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Can I get productive in a new codebase within 30 minutes?"

---

## Test Suite Overview

This test evaluates how effectively an agent can onboard to a completely unfamiliar codebase using Agentic Inquiry. It simulates the real-world scenario of being assigned to work on code you've never seen before.

### Success Criteria

An agent successfully onboards if they can:
- Describe what the project does (purpose, domain)
- Identify 3-5 key modules/components
- Understand code organization patterns
- Know where to find specific functionality
- Feel confident enough to start making changes

**Time Limit:** 30 minutes for complete onboarding
**Confidence Threshold:** 7/10 or higher on "ready to work" scale

---

## Pre-Test Setup

### Prerequisites

**IMPORTANT: This is a COLD START test. Do NOT pre-index the codebase.**

1. **Fresh Codebase:** Use a codebase you've never worked with before
2. **Empty Index (Cold Start):** Do NOT pre-index - this test measures onboarding from scratch
   - Create a new session: `create_session(project_id)`
   - Verify empty state: `get_project_info(session_id)` should show `chunks: 0` or minimal
   - Indexing should happen as part of the test workflow (Test 1)
3. **No Prior Knowledge:** Simulate true cold start - don't read READMEs beforehand
4. **MCP Server Running:** Agentic Inquiry MCP server started and accessible

**Why Cold Start?**
This test validates the complete onboarding experience: from zero knowledge to productive understanding. Pre-indexing would skip the critical first step of discovery and skew time measurements.

**Contrast with other tests:**
- TEST_02 (this test): Start with empty index, index during test as part of onboarding workflow
- TEST_03-14: Each test creates its own session with unique project_id and indexes the codebase
  in the Pre-Test Setup phase (see USE_CASES.md "Ensure Fresh Index"). The test itself does the
  indexing - do NOT assume data exists from previous tests or default projects.

### Test Environment

```
Codebase: [name]
Language(s): [primary language]
Estimated Size: [file count]
Domain: [unknown at start]
```

---

## Test 1: What Does This Project Do?

**Scenario:** You just cloned the repo. What is this?

### T1.1: Project Purpose Discovery

**Objective:** Understand the project's purpose, domain, and main functionality

**Execute:** Use search and context building to discover:
- What problem does this solve?
- What domain is it in? (web app, library, CLI tool, service, etc.)
- Who would use this?
- What are the main capabilities?

**Available Tools:**
- `search_knowledge()` - Search for README, docs, high-level descriptions
- `build_context()` - Build context around "project overview"
- `get_project_info()` - Get project statistics and metadata

**Success Criteria:**
- Identifies correct domain within 3 queries
- Describes purpose in 2-3 sentences
- Lists 3-5 main capabilities
- Understanding confidence ≥7/10

**Document:**
```
Query Strategy:
1. [first query] → [results count] results
2. [second query] → [results count] results
3. [third query] → [results count] results

Findings:
- Domain: [e.g., web framework, data processing, API service]
- Purpose: [2-3 sentence description]
- Main Capabilities:
  1. [capability]
  2. [capability]
  3. [capability]
  4. [capability]
  5. [capability]

Time to discovery: [minutes]
Confidence (1-10): [score]
Could explain to stakeholder: [yes/no]
```

---

### T1.2: Technology Stack Identification

**Objective:** Identify key technologies, frameworks, and dependencies

**Execute:** Discover:
- Primary programming language(s)
- Frameworks used
- Major dependencies
- Build/deployment tools

**Success Criteria:**
- Identifies all primary languages
- Finds main framework(s)
- Lists 5-10 key dependencies
- Understands build system

**Document:**
```
Technology Stack:
- Languages: [list]
- Frameworks: [list]
- Key Dependencies:
  1. [dependency] - [purpose]
  2. [dependency] - [purpose]
  3. [dependency] - [purpose]
  ...
- Build System: [tool/approach]
- Deployment: [method if identified]

Discovery Method: [how you found this]
Accuracy Verification: [spot-checked a few - yes/no]
```

---

## Test 2: Architecture Understanding

**Scenario:** Need to understand how this system is organized

### T2.1: Directory Structure Mapping

**Objective:** Understand high-level code organization

**Execute:** Map out the codebase structure:
- Main directories and their purposes
- Where is core business logic?
- Where are tests?
- Where are configurations?
- Where are docs?

**Success Criteria:**
- Maps all major directories
- Understands purpose of each
- Identifies logical boundaries
- Knows where to look for different types of files

**Document:**
```
Directory Structure:
/ [root]
├── [dir1]/ - [purpose]
├── [dir2]/ - [purpose]
├── [dir3]/ - [purpose]
├── [dir4]/ - [purpose]
└── [dir5]/ - [purpose]

Core Logic Location: [directory]
Test Location: [directory]
Configuration Location: [directory]
Documentation Location: [directory]

Organization Pattern: [e.g., by feature, by layer, by domain]
Makes Sense: [yes/no + why]
```

---

### T2.2: Component Identification

**Objective:** Identify the main components/modules and their roles

**Execute:** Find 3-5 key components:
- What are the major classes/modules?
- What does each component do?
- How do they relate to each other?

**Success Criteria:**
- Identifies 3-5 core components
- Understands each component's purpose
- Can describe relationships
- Maps to actual files/locations

**Document:**
```
Key Components:

1. [ComponentName]
   - Location: [file:path]
   - Purpose: [what it does]
   - Key Responsibilities: [list]
   - Related To: [other components]

2. [ComponentName]
   - Location: [file:path]
   - Purpose: [what it does]
   - Key Responsibilities: [list]
   - Related To: [other components]

3. [ComponentName]
   - Location: [file:path]
   - Purpose: [what it does]
   - Key Responsibilities: [list]
   - Related To: [other components]

[Continue for 4-5 total]

Component Discovery Method: [how you found these]
Confidence in Accuracy (1-10): [score]
```

---

### T2.3: Architectural Patterns

**Objective:** Identify design patterns and architectural styles

**Execute:** Look for:
- What architectural patterns are used? (MVC, layered, microservices, etc.)
- What design patterns appear frequently?
- How is dependency injection handled?
- How is configuration managed?

**Success Criteria:**
- Identifies primary architectural pattern
- Finds 2-3 common design patterns
- Understands how components connect
- Recognizes conventions

**Document:**
```
Architectural Style: [pattern name]
Evidence: [where you see it]

Design Patterns Found:
1. [pattern] - [where/how used]
2. [pattern] - [where/how used]
3. [pattern] - [where/how used]

Dependency Management: [approach]
Configuration Style: [approach]

Patterns Consistency: [consistent/mixed]
Code Quality Indicators: [observations]
```

---

## Test 3: Entry Point Discovery

**Scenario:** Where does execution actually start?

### T3.1: Main Entry Points

**Objective:** Find where the application/library starts execution

**Execute:** Locate:
- Main entry point(s)
- How the application starts
- Initialization sequence
- Bootstrap/setup code

**Success Criteria:**
- Finds correct entry point(s)
- Provides exact file:line
- Understands startup sequence
- Can trace from start to first business logic

**Document:**
```
Entry Points Found:

Primary Entry Point:
- Location: [file:line]
- Function/Method: [name]
- How It Starts: [command/trigger]

Initialization Sequence:
1. [first step] - [file:function]
2. [second step] - [file:function]
3. [third step] - [file:function]
...

Bootstrap Process:
- Configuration Loading: [where/how]
- Service Initialization: [where/how]
- Ready State: [how determined]

Discovery Time: [minutes]
Could Start Debugging: [yes/no]
```

---

### T3.2: Request Flow (if applicable)

**Objective:** Understand how a typical request/operation flows through the system

**Execute:** Trace a request from entry to completion:
- HTTP request → response (for web apps)
- CLI command → output (for CLI tools)
- Function call → result (for libraries)

**Success Criteria:**
- Traces complete flow
- Identifies all major steps
- Understands data transformations
- Can predict behavior

**Document:**
```
Request Flow Traced:

Input: [type of request/call]
Entry: [where it enters]

Flow Steps:
1. [component/function] - [what happens]
2. [component/function] - [what happens]
3. [component/function] - [what happens]
...

Output: [what returns]

Data Transformations:
- [step]: [input type] → [output type]
- [step]: [input type] → [output type]

Error Handling: [where/how]
Validation: [where/how]

Flow Complexity: [simple/moderate/complex]
Confidence (1-10): [score]
```

---

## Test 4: Find Functionality

**Scenario:** Stakeholder asks "where is the [X] functionality?"

### T4.1: Feature Location

**Objective:** Quickly locate specific functionality in the codebase

**Execute:** Pick 3 features that should exist (based on project purpose) and find them:
- Authentication (if applicable)
- Data storage/retrieval
- Main business logic
- Error handling
- Configuration

**Success Criteria:**
- Finds each feature within 2-3 queries
- Provides exact locations
- Understands implementation approach
- Can describe how it works

**Document:**
```
Feature Location Tests:

Feature 1: [name]
- Search Query: [query used]
- Location Found: [file:path]
- Implementation: [brief description]
- Time to Find: [seconds]
- Confidence: [1-10]

Feature 2: [name]
- Search Query: [query used]
- Location Found: [file:path]
- Implementation: [brief description]
- Time to Find: [seconds]
- Confidence: [1-10]

Feature 3: [name]
- Search Query: [query used]
- Location Found: [file:path]
- Implementation: [brief description]
- Time to Find: [seconds]
- Confidence: [1-10]

Average Time per Feature: [seconds]
Success Rate: [found/attempted]
```

---

### T4.2: Common Utilities

**Objective:** Find frequently used utility functions/helpers

**Execute:** Locate common utilities:
- Logging/error handling
- Validation functions
- Helper utilities
- Constants/enums
- Type definitions

**Success Criteria:**
- Finds utility locations
- Understands conventions
- Knows where to add new utilities
- Recognizes patterns

**Document:**
```
Utility Locations:

Logging: [file:path and pattern]
Error Handling: [file:path and pattern]
Validation: [file:path and pattern]
Helpers: [file:path and pattern]
Constants: [file:path and pattern]

Naming Conventions: [observed patterns]
Organization: [how utilities are structured]
Reuse Patterns: [how they're used across codebase]

Would Add New Utility Here: [location]
Reasoning: [why]
```

---

## Test 5: Knowledge Persistence

**Scenario:** Store learnings for future reference

### T5.1: Store Onboarding Insights

**Objective:** Persist key onboarding discoveries

**Execute:** Store 5-10 memories about the codebase:
- Project purpose and domain
- Key components and their roles
- Architectural patterns
- Entry points and flow
- Location of important functionality

**Success Criteria:**
- All memories stored successfully
- Tagged appropriately (e.g., "onboarding", "architecture")
- Importance levels set correctly
- Content is clear and actionable

**Document:**
```
Memories Stored:

1. [Summary] - Importance: [0.0-1.0] - Tags: [tags]
2. [Summary] - Importance: [0.0-1.0] - Tags: [tags]
3. [Summary] - Importance: [0.0-1.0] - Tags: [tags]
...

Total Memories: [count]
Storage Success Rate: [100%/less]
Tagging Strategy: [approach]
```

---

### T5.2: Knowledge Retrieval

**Objective:** Verify stored knowledge is retrievable

**Execute:** Query for stored onboarding knowledge:
- Search by tag ("onboarding")
- Search by topic ("architecture", "entry point")
- Search by component name

**Success Criteria:**
- Retrieves all stored memories
- Results are relevant
- Ranking makes sense
- Content intact

**Document:**
```
Retrieval Tests:

Query: "onboarding"
- Results: [count]
- Relevant: [count]
- Precision: [%]

Query: [topic/component]
- Results: [count]
- Relevant: [count]
- Precision: [%]

Overall Retrieval Success: [yes/no]
Would Rely On Memory: [yes/no + reasoning]
```

---

## Test 6: Readiness Assessment

**Scenario:** Evaluate if you're ready to start working on this codebase

### T6.1: Comprehension Check

**Objective:** Self-assess understanding level

**Can you answer these questions confidently?**
1. What does this project do?
2. How is it architected?
3. Where would you add a new feature in domain X?
4. How do you run/test the code?
5. What are the main components and how do they interact?

**Document:**
```
Comprehension Self-Assessment:

1. Project Purpose: [can explain yes/no] - Confidence: [1-10]
2. Architecture: [can explain yes/no] - Confidence: [1-10]
3. Feature Addition: [know where yes/no] - Confidence: [1-10]
4. Run/Test: [can do yes/no] - Confidence: [1-10]
5. Components: [can explain yes/no] - Confidence: [1-10]

Average Confidence: [score]
Ready to Work: [yes/no]
```

---

### T6.2: Simulated Task

**Objective:** Attempt a simple task to validate understanding

**Execute:** Simulate one of these tasks:
- "Where would you add input validation for X?"
- "Where would you fix a bug in feature Y?"
- "Where would you add a new endpoint/command/function?"

**Success Criteria:**
- Identifies correct location within 5 minutes
- Explains reasoning
- Shows understanding of code flow
- Doesn't need external help

**Document:**
```
Simulated Task: [description]

Approach:
1. [step] - Time: [seconds]
2. [step] - Time: [seconds]
3. [step] - Time: [seconds]

Solution:
- Location: [file:line]
- Reasoning: [why here]
- Related Changes Needed: [list]
- Confidence: [1-10]

Total Time: [minutes]
Needed External Help: [yes/no]
Correct Location: [yes/no - verify if possible]
```

---

## Final Evaluation

### Onboarding Effectiveness Score

**Time Metrics:**
```
Total Onboarding Time: [minutes]
Target: ≤30 minutes
Met Target: [yes/no]

Breakdown:
- Project Purpose: [minutes]
- Architecture: [minutes]
- Entry Points: [minutes]
- Feature Location: [minutes]
- Knowledge Storage: [minutes]
```

**Understanding Metrics:**
```
Comprehension Scores:
- Project Purpose: [1-10]
- Architecture: [1-10]
- Components: [1-10]
- Patterns: [1-10]
- Workflow: [1-10]

Average: [score]
Target: ≥7
Met Target: [yes/no]
```

**Confidence Metrics:**
```
Ready to Work: [yes/no]
Confidence Level: [1-10]
Could Start Coding: [yes/no]
Could Review PRs: [yes/no]
Could Debug Issues: [yes/no]
```

### Production Readiness

**Critical Checks:**
- [ ] Understood project in ≤30 minutes
- [ ] Confidence ≥7 on all comprehension areas
- [ ] Can locate key functionality quickly (≤2-3 queries)
- [ ] Knowledge persisted and retrievable
- [ ] Feel ready to start actual work

**Pass/Fail:** [PASS/FAIL]

---

## Summary & Recommendations

### What Worked Well
```
[3-5 things that helped onboarding]
```

### What Was Challenging
```
[3-5 things that slowed onboarding]
```

### Onboarding Effectiveness

**Answer: [Very Effective / Effective / Somewhat Effective / Not Effective]**

**Reasoning:**
```
[2-3 paragraphs on:]
- Speed of understanding vs. manual approach
- Confidence level after onboarding
- Quality of insights gained
- Readiness to contribute
```

### Recommendations

**For Tool Improvement:**
```
[Suggestions to improve onboarding experience]
```

**For Documentation:**
```
[What documentation would have helped]
```

---

## Test Completion

**Test Metadata:**
```
Duration: [minutes]
Tester: [name/id]
Date: [YYYY-MM-DD]
Codebase: [name and size]
Tests Completed: [X]/6
Confidence Achieved: [score]/10
Ready to Work: [yes/no]
```

**Key Metrics:**
```
Time to Understanding: [minutes]
Query Efficiency: [avg queries per discovery]
Memory Reliability: [% retrieved]
Overall Success: [yes/no]
```

---

**Remember:** Effective onboarding means you can start contributing within 30 minutes. Be honest about whether Agentic Inquiry got you there.
