# Use Case 10: API Design & Extension

**Purpose:** Validate agent's ability to design APIs that fit existing patterns
**Output Path:** test_results/api_design/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Does my API feel like it belongs in this codebase?"

---

## Test Suite Overview

This test evaluates how effectively an agent can design APIs using Agent-Vault to:
- Understand existing API patterns
- Follow established conventions
- Identify integration requirements
- Design consistent interfaces
- Plan proper implementation
- Validate design quality

### Success Criteria

API design is successful if the agent can:
- Understand all existing APIs in subsystem
- Identify and follow patterns
- Design consistent interface
- Plan complete implementation
- Include all required components
- Achieve ≥9/10 confidence in design quality

**Time Limit:** 60 minutes from task assignment to API design
**Confidence Threshold:** 9/10 or higher on "design quality" scale

---

## Pre-Test Setup

### Prerequisites

> **CRITICAL: You MUST index the codebase yourself.** Do NOT assume pre-existing data is valid.
> See USE_CASES.md "Ensure Fresh Index" for detailed instructions.

**Step 1: Create Session with Unique Project ID**
```python
project_id = "agv_test11_api_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="API design test")
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

1. **API Task Defined:** Clear requirement for new API (see examples below)
2. **Design Criteria:** Standards for evaluating API quality
3. **Integration Context:** Understanding of where API fits

### API Design Task Selection

Choose ONE realistic API design task appropriate for your codebase:

**For extensibility:**
- "Design new MCP tool for code navigation"
- "Add new parser for file format"
- "Create new embedder provider"
- "Design plugin system for extensions"

**For new features:**
- "Design REST API for new feature"
- "Create new service interface"
- "Add new query capability"
- "Design webhook system"

**For refactoring:**
- "Redesign existing API for better usability"
- "Create facade over complex subsystem"
- "Design abstraction for multiple implementations"

**Document Your API Task:**
```
API Design Task:
Feature: [what needs an API]
Example: "New MCP tool for code navigation"

Purpose:
[what the API should enable]

Users:
[who will use this API]

Requirements:
- [requirement 1]
- [requirement 2]
- [requirement 3]

Success Criteria:
[how you'll know design is good]
```

---

## Test 1: Understand Existing APIs

**Scenario:** Learn from existing APIs in the same subsystem

### T1.1: Existing API Discovery

**Objective:** Find all relevant existing APIs

**Execute:** Search for existing APIs:
- What APIs exist in this subsystem?
- How are they structured?
- What patterns do they follow?
- What's the public interface?

**Success Criteria:**
- Finds all relevant APIs within 5 queries
- Understands structure
- Identifies patterns
- Maps public interfaces

**Document:**
```
Existing API Discovery:

Search Strategy:
Query 1: [search for API components]
- Results: [count]
- APIs Found: [count]
- Examples: [list]

Query 2: [refine search]
- Results: [count]
- APIs Found: [count]

Existing APIs:

API 1: [name]
- Location: [file:path]
- Purpose: [what it does]
- Type: [class/function/module]
- Public Methods: [count]
- Complexity: [simple/moderate/complex]

API 2: [name]
[Same structure...]

[Continue for all relevant APIs]

Total Existing APIs: [count]
Most Similar To Task: [which API]
Discovery Time: [minutes]
```

---

### T1.2: API Signature Analysis

**Objective:** Understand how existing APIs are designed

**Execute:** Analyze API signatures:
- What parameters do they take?
- What do they return?
- How are they named?
- What patterns appear?

**Success Criteria:**
- Documents all signatures
- Identifies naming patterns
- Understands parameter patterns
- Recognizes return patterns

**Document:**
```
API Signature Analysis:

Signature Pattern 1: [pattern description]

Examples:
```python
def similar_api_1(param1: Type1, param2: Type2) -> ReturnType:
def similar_api_2(param1: Type1, param2: Type2) -> ReturnType:
```

Common Elements:
- Parameter Types: [patterns]
- Parameter Names: [conventions]
- Return Types: [patterns]
- Async/Sync: [which is used]

Signature Pattern 2: [pattern description]
[Same analysis...]

Parameter Patterns:

Naming Convention:
- [pattern] - Examples: [list]

Type Patterns:
- [pattern] - Why: [reason]

Optional Parameters:
- Pattern: [how handled]
- Defaults: [strategy]

Return Patterns:

Success Returns:
- [pattern] - Examples: [list]

Error Handling:
- [pattern] - Exceptions/Results/etc

Async Patterns:
- Used For: [when]
- Not Used For: [when]

Overall Consistency: [excellent/good/mixed/poor]
```

---

## Test 2: Find API Patterns

**Scenario:** Identify design patterns used in APIs

### T2.1: Structural Patterns

**Objective:** Identify structural design patterns

**Execute:** Analyze API structures:
- What design patterns are used?
- How are classes organized?
- What inheritance patterns exist?
- What composition patterns exist?

**Success Criteria:**
- Identifies patterns
- Understands why used
- Shows examples
- Recognizes when to apply

**Document:**
```
Structural Pattern Analysis:

Patterns Found:

Pattern 1: [pattern name]
- Where Used: [examples]
- Purpose: [why it's used]
- Structure:
  [description or diagram]
- When To Use: [guidelines]
- Example:
  ```python
  [code example]
  ```

Pattern 2: [pattern name]
[Same structure...]

Inheritance Patterns:

Base Classes:
1. [BaseClass] - [file:path]
   - Purpose: [what it abstracts]
   - Subclasses: [count]
   - Pattern: [template method/strategy/etc]

Composition Patterns:

1. [pattern description]
   - Example: [code location]
   - Why: [benefit]

Interface Patterns:

Protocol/ABC Usage:
- Frequency: [high/medium/low]
- Pattern: [how used]
- Examples: [locations]

Total Patterns: [count]
Most Important: [which pattern]
```

---

### T2.2: Behavioral Patterns

**Objective:** Understand behavioral patterns and conventions

**Execute:** Analyze behaviors:
- How is state managed?
- How are errors handled?
- How is validation done?
- What conventions exist?

**Success Criteria:**
- Identifies behavioral patterns
- Understands error handling
- Recognizes validation patterns
- Documents conventions

**Document:**
```
Behavioral Pattern Analysis:

State Management:

Pattern: [how state is managed]
Examples:
- [location] - [approach]
- [location] - [approach]

Conventions:
- [convention]
- [convention]

Error Handling:

Pattern: [exceptions/results/both]
Examples:
```python
[code showing error pattern]
```

When To Raise:
- [scenario] - [exception type]
- [scenario] - [exception type]

Custom Exceptions:
- [ExceptionType] - [when used]
- [ExceptionType] - [when used]

Validation:

Pattern: [where/how validation happens]
Examples:
- [location] - [what's validated]

Validation Strategies:
- Input: [pattern]
- State: [pattern]
- Output: [pattern]

Configuration:

Pattern: [how APIs are configured]
Examples:
- [location] - [config approach]

Dependency Injection:
- Pattern: [constructor/property/method]
- Consistency: [yes/no]

Overall Pattern Consistency: [excellent/good/fair/poor]
```

---

## Test 3: Check Conventions

**Scenario:** Identify naming and organizational conventions

### T3.1: Naming Conventions

**Objective:** Document naming standards

**Execute:** Analyze naming:
- How are classes named?
- How are methods named?
- How are parameters named?
- What prefixes/suffixes are used?

**Success Criteria:**
- Documents all conventions
- Shows examples
- Identifies variations
- Explains rationale

**Document:**
```
Naming Convention Analysis:

Class Naming:

Pattern: [PascalCase/etc]
Conventions:
- [pattern] - Examples: [names]
- [pattern] - Examples: [names]

Suffixes/Prefixes:
- [suffix] - Meaning: [what it indicates] - Examples: [list]
- [prefix] - Meaning: [what it indicates] - Examples: [list]

Method Naming:

Pattern: [snake_case/camelCase/etc]
Conventions:
- Verbs: [pattern] - Examples: [names]
- Getters: [pattern] - Examples: [names]
- Setters: [pattern] - Examples: [names]
- Boolean: [pattern] - Examples: [names]

Parameter Naming:

Conventions:
- [convention] - Examples: [names]
- [convention] - Examples: [names]

Reserved Names:
- [name] - Always means: [what]
- [name] - Always means: [what]

Module/File Naming:

Pattern: [snake_case/etc]
Conventions:
- [pattern] - Examples: [names]

Internal vs Public:
- Private: [prefix pattern]
- Public: [pattern]

Consistency Level: [excellent/good/fair/poor]
Clarity Level: [high/medium/low]
```

---

### T3.2: Organizational Conventions

**Objective:** Understand file and module organization

**Execute:** Analyze organization:
- How are APIs organized in files?
- What's the directory structure?
- How are modules grouped?
- What's the import pattern?

**Success Criteria:**
- Maps organization pattern
- Understands grouping logic
- Identifies placement rules
- Documents import conventions

**Document:**
```
Organizational Convention Analysis:

File Organization:

Pattern: [one class per file/grouped/etc]
Examples:
- [file] - Contains: [what]
- [file] - Contains: [what]

File Size:
- Typical: [LOC range]
- Maximum: [LOC]
- Pattern: [small/medium/large files]

Directory Structure:

Pattern:
```
subsystem/
├── [directory] - Purpose: [what goes here]
├── [directory] - Purpose: [what goes here]
└── [directory] - Purpose: [what goes here]
```

Grouping Logic:
- [criterion] - Examples: [directories]
- [criterion] - Examples: [directories]

Module Organization:

Import Patterns:
```python
[typical import structure]
```

Relative vs Absolute:
- Pattern: [which is used]
- Consistency: [yes/no]

__init__.py Pattern:
- Exports: [what's exported]
- Re-exports: [yes/no]

Where New API Should Go:

Directory: [path]
File: [name] or [create new]
Reasoning: [why this location]

Organization Consistency: [excellent/good/fair/poor]
```

---

## Test 4: Identify Requirements

**Scenario:** Determine what the new API needs

### T4.1: Functional Requirements

**Objective:** Define what the API must do

**Execute:** Analyze requirements:
- What operations are needed?
- What data does it work with?
- What's the expected behavior?
- What edge cases exist?

**Success Criteria:**
- Lists all operations
- Defines data model
- Describes behavior
- Identifies edge cases

**Document:**
```
Functional Requirements:

Core Operations:

Operation 1: [name/description]
- Input: [what it takes]
- Output: [what it returns]
- Behavior: [what it does]
- Example Use: [scenario]

Operation 2: [name/description]
[Same structure...]

[Continue for all operations]

Data Model:

Input Data:
- Type: [structure]
- Constraints: [validations]
- Examples: [samples]

Output Data:
- Type: [structure]
- Format: [how structured]
- Examples: [samples]

State (if any):
- What State: [description]
- How Managed: [pattern]

Behavior Requirements:

Normal Operation:
- [behavior requirement]
- [behavior requirement]

Error Conditions:
- [condition] - Response: [how to handle]
- [condition] - Response: [how to handle]

Edge Cases:
- [edge case] - Handling: [approach]
- [edge case] - Handling: [approach]

Total Operations: [count]
Complexity: [simple/moderate/complex]
```

---

### T4.2: Non-Functional Requirements

**Objective:** Identify performance, security, and quality requirements

**Execute:** Define constraints:
- What performance is needed?
- What security considerations?
- What compatibility constraints?
- What quality standards?

**Success Criteria:**
- Sets performance targets
- Identifies security needs
- Lists compatibility requirements
- Defines quality criteria

**Document:**
```
Non-Functional Requirements:

Performance:

Response Time:
- Target: [milliseconds/seconds]
- Acceptable: [threshold]

Throughput:
- Target: [operations/second]
- Load: [expected volume]

Resource Usage:
- Memory: [constraints]
- CPU: [constraints]

Security:

Authentication:
- Required: [yes/no]
- Method: [how]

Authorization:
- Required: [yes/no]
- Model: [role-based/etc]

Data Protection:
- Sensitive Data: [yes/no]
- Protection: [how]

Input Validation:
- Required: [yes/no]
- Strategy: [what to validate]

Compatibility:

Python Version: [requirement]
Dependencies: [what's allowed]
Breaking Changes: [acceptable/no]
Backward Compatibility: [required/no]

Quality:

Testing:
- Coverage Target: [%]
- Test Types: [unit/integration/etc]

Documentation:
- Required: [API docs/guide/examples]
- Format: [docstrings/markdown/etc]

Code Quality:
- Standards: [PEP8/etc]
- Type Hints: [required/optional]

Total Requirements: [count]
Most Critical: [which ones]
```

---

## Test 5: Plan Integration

**Scenario:** Design how new API integrates with existing system

### T5.1: Integration Points

**Objective:** Identify where new API connects to existing code

**Execute:** Map integration:
- Where does API plug in?
- What does it depend on?
- What depends on it?
- How is it registered/discovered?

**Success Criteria:**
- Maps all integration points
- Identifies dependencies
- Plans registration
- Shows data flow

**Document:**
```
Integration Planning:

Integration Points:

Point 1: [where/what]
- Type: [plugin/service/utility]
- Integration Method: [how it connects]
- Location: [file:line to modify]
- Code Change Required: [yes/no - what]

Point 2: [where/what]
[Same structure...]

Dependencies:

New API Depends On:
1. [component] - [file:path]
   - Used For: [purpose]
   - Coupling: [tight/loose]

2. [component] - [file:path]
   [Same structure...]

Dependents (what will use new API):
1. [component] - [file:path]
   - Use Case: [how they'll use it]

2. [component] - [file:path]
   [Same structure...]

Registration/Discovery:

Pattern: [how APIs are registered]
Location: [where registration happens]
Code Required:
```python
[registration code]
```

Data Flow:

Input Source: [where data comes from]
↓
Processing: [what API does]
↓
Output Destination: [where results go]

Total Integration Points: [count]
Integration Complexity: [simple/moderate/complex]
```

---

### T5.2: Backward Compatibility

**Objective:** Ensure new API doesn't break existing code

**Execute:** Plan compatibility:
- Does it change existing APIs?
- What breaks?
- How to maintain compatibility?
- What migration path?

**Success Criteria:**
- Identifies breaking changes
- Plans mitigation
- Provides migration path
- Ensures compatibility

**Document:**
```
Compatibility Planning:

Breaking Changes:

Change 1: [what breaks]
- Affected: [what code]
- Impact: [severity]
- Mitigation: [how to avoid]

Change 2: [what breaks]
[Same structure...]

Total Breaking Changes: [count]

Compatibility Strategy:

Approach: [additive/versioned/deprecation]
Reasoning: [why this approach]

If Deprecation:
- Deprecate: [what]
- Timeline: [how long]
- Migration: [how to migrate]
- Warnings: [how communicated]

If Versioning:
- Version: [new version number]
- Old Version: [still supported yes/no]

Migration Path:

For Existing Users:
1. [migration step]
2. [migration step]
3. [migration step]

Migration Effort: [hours/days]
Automated: [yes/no/partially]

Backward Compatibility:
- Maintained: [yes/no/partially]
- Cost: [effort to maintain]
- Worth It: [yes/no]
```

---

## Test 6: Design Validation

**Scenario:** Validate design quality and completeness

### T6.1: Design Review

**Objective:** Check design against best practices

**Execute:** Review design:
- Does it follow patterns?
- Is it consistent?
- Is it complete?
- Is it well-designed?

**Success Criteria:**
- Follows all patterns
- Maintains consistency
- Includes all components
- Meets quality standards

**Document:**
```
Design Review Checklist:

Pattern Compliance:
- [ ] Follows existing structural patterns
- [ ] Uses consistent naming conventions
- [ ] Matches behavioral patterns
- [ ] Integrates properly
- [ ] Handles errors consistently

Completeness:
- [ ] All operations defined
- [ ] All parameters specified
- [ ] Return types defined
- [ ] Error cases handled
- [ ] Edge cases addressed

Quality:
- [ ] Type hints complete
- [ ] Docstrings planned
- [ ] Examples ready
- [ ] Tests planned
- [ ] Documentation outlined

Consistency:
- [ ] Naming matches conventions
- [ ] Signatures match patterns
- [ ] Organization matches structure
- [ ] Imports follow patterns
- [ ] Code style consistent

Pattern Compliance Score: [X]/5
Completeness Score: [X]/5
Quality Score: [X]/5
Consistency Score: [X]/5

Overall Design Quality: [excellent/good/adequate/poor]
```

---

### T6.2: Design Presentation

**Objective:** Document complete API design

**Execute:** Write API specification:
- Document interface
- Provide examples
- Explain design decisions
- Show implementation plan

**Success Criteria:**
- Clear interface spec
- Working examples
- Justified decisions
- Implementable plan

**Document:**
```
API Design Specification:

---
## API Overview

**Name:** [API name]
**Purpose:** [what it does]
**Location:** [where it will be]

## Interface

### Classes

#### [ClassName]

```python
class ClassName(BaseClass):
    """[Docstring]"""

    def __init__(self, param1: Type1, param2: Type2):
        """[Docstring]"""

    def method1(self, param: Type) -> ReturnType:
        """[Docstring]"""

    def method2(self, param: Type) -> ReturnType:
        """[Docstring]"""
```

### Functions

```python
def function_name(param1: Type1, param2: Type2) -> ReturnType:
    """[Docstring]"""
```

## Usage Examples

### Example 1: [Use Case]

```python
[Complete working example]
```

### Example 2: [Use Case]

```python
[Complete working example]
```

## Design Decisions

### Decision 1: [What was decided]
- Options Considered: [alternatives]
- Chosen: [which one]
- Reasoning: [why]

### Decision 2: [What was decided]
[Same structure...]

## Implementation Plan

### Phase 1: Core Implementation
- [ ] [task] - Estimate: [hours]
- [ ] [task] - Estimate: [hours]

### Phase 2: Integration
- [ ] [task] - Estimate: [hours]

### Phase 3: Testing
- [ ] [task] - Estimate: [hours]

### Phase 4: Documentation
- [ ] [task] - Estimate: [hours]

Total Effort: [hours/days]

## Testing Strategy

Unit Tests:
- [test description]
- [test description]

Integration Tests:
- [test description]

## Documentation

- API Reference: [plan]
- User Guide: [plan]
- Examples: [plan]

---

Design Completeness: [%]
Implementation Readiness: [yes/no]
```

---

## Final Evaluation

### API Design Quality Metrics

**Time Metrics:**
```
Design Duration: [minutes]
Target: ≤60 minutes
Met Target: [yes/no]

Breakdown:
- Existing API Study: [minutes]
- Pattern Analysis: [minutes]
- Requirements: [minutes]
- Design: [minutes]
- Validation: [minutes]
```

**Consistency Metrics:**
```
Pattern Compliance: [%]
Naming Consistency: [%]
Structure Consistency: [%]
Behavioral Consistency: [%]

Overall Consistency: [%]
Target: ≥95%
Met Target: [yes/no]
```

**Completeness Metrics:**
```
Design Completeness:
- Operations: [all defined yes/no]
- Parameters: [all specified yes/no]
- Returns: [all defined yes/no]
- Errors: [all handled yes/no]
- Edge Cases: [all addressed yes/no]

Completeness Score: [X]/5
Target: 5/5
Met Target: [yes/no]
```

**Quality Metrics:**
```
Design Quality:
- Follows Patterns: [yes/no]
- Well Documented: [yes/no]
- Examples Included: [yes/no]
- Tests Planned: [yes/no]
- Implementable: [yes/no]

Quality Score: [X]/5
Target: 5/5
Met Target: [yes/no]
```

**Confidence Metrics:**
```
Design Confidence: [1-10]
Target: ≥9
Met Target: [yes/no]

Ready to Implement: [yes/no]
Would Pass Review: [yes/no]
Fits Codebase: [yes/no]
```

### Production Readiness

**Critical Checks:**
- [ ] Studied all existing APIs
- [ ] Identified and followed patterns
- [ ] Met naming conventions
- [ ] Designed complete interface
- [ ] Planned integration
- [ ] Validated design
- [ ] Created implementation plan
- [ ] Confidence ≥9/10

**Pass/Fail:** [PASS/FAIL]

---

## Summary & Recommendations

### What Worked Well
```
[3-5 things that helped API design]
```

### What Was Challenging
```
[3-5 challenges in designing the API]
```

### Design Quality

**Answer: [Excellent / Good / Adequate / Poor]**

**Reasoning:**
```
[2-3 paragraphs on:]
- How well design fits codebase
- Quality of pattern matching
- Completeness of specification
- Implementability
- Value added by the API
```

### Recommendations

**For Implementation:**
```
[Specific guidance for implementing the design]
```

**For Improvement:**
```
[How design could be enhanced]
```

---

## Test Completion

**Test Metadata:**
```
Duration: [minutes]
Tester: [name/id]
Date: [YYYY-MM-DD]
API Designed: [name]
Operations: [count]
Integration Points: [count]
Confidence Achieved: [score]/10
Ready to Implement: [yes/no]
```

**Key Metrics:**
```
Pattern Compliance: [%]
Design Completeness: [%]
Quality Score: [X]/5
Consistency Score: [X]/5
Overall Success: [yes/no]
```

---

**Remember:** Great API design feels natural in its codebase. It should look like it was always there, following all patterns and conventions perfectly.
