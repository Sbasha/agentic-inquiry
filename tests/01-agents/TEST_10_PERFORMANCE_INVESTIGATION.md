# Use Case 9: Performance Investigation

**Purpose:** Validate agent's ability to identify and resolve performance bottlenecks
**Output Path:** test_results/performance_investigation/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Why is this slow and how can I make it faster?"

---

## Test Suite Overview

This test evaluates how effectively an agent can investigate performance issues using Agentic Inquiry to:
- Identify performance bottlenecks
- Understand data flow and volume
- Find existing optimizations
- Discover tuning options
- Identify alternative approaches
- Estimate improvement impact

### Success Criteria

Performance investigation is successful if the agent can:
- Locate bottleneck within 20 minutes
- Understand what's slow and why
- Find existing optimization patterns
- Identify 3-5 improvement opportunities
- Estimate impact of each improvement
- Achieve ≥8/10 confidence in recommendations

**Time Limit:** 45 minutes from problem statement to optimization plan
**Confidence Threshold:** 8/10 or higher on "understand performance" scale

---

## Pre-Test Setup

### Prerequisites

> **CRITICAL: You MUST index the codebase yourself.** Do NOT assume pre-existing data is valid.
> See USE_CASES.md "Ensure Fresh Index" for detailed instructions.

**Step 1: Create Session with Unique Project ID**
```python
project_id = "ai_test10_perf_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Performance investigation test")
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

1. **Performance Problem Defined:** Clear description of slowness (see examples below)
2. **Baseline Metrics:** Current performance measurements if available
3. **Performance Goals:** Target performance level

### Performance Problem Selection

Choose ONE realistic performance issue appropriate for your codebase:

**For search/query operations:**
- "Search queries take 5+ seconds for large codebases"
- "Index build takes hours for medium codebases"
- "Memory usage grows unbounded during indexing"

**For data processing:**
- "Parser processing is very slow"
- "Embedding generation bottlenecks pipeline"
- "Bulk operations don't scale"

**For API/services:**
- "API response times degrade under load"
- "Database queries are slow"
- "Concurrent requests block each other"

**Document Your Performance Problem:**
```
Performance Issue:
Symptom: [what's slow]
Example: "Search queries take 5+ seconds"

Current Performance:
- Metric: [measurement]
- Value: [current value]
- Acceptable: [target value]

Environment:
- Data Size: [records/files/etc]
- Load: [concurrent users/requests]
- Resources: [hardware/limits]

Impact:
[how this affects users/system]
```

---

## Test 1: Identify Bottleneck Location

**Scenario:** Find where time/resources are being spent

### T1.1: Performance-Critical Code Discovery

**Objective:** Locate the code that's slow

**Execute:** Search for the slow operation:
- Where is the slow operation implemented?
- What's the call path to get there?
- What methods/functions are involved?
- Where should profiling focus?

**Success Criteria:**
- Finds implementation within 5 queries
- Identifies call path
- Locates critical methods
- Provides file:line locations

**Document:**
```
Bottleneck Discovery:

Initial Search:
Query 1: [search for operation]
- Results: [count]
- Relevant: [count]
- Found: [what was located]

Query 2: [refine search]
- Results: [count]
- Relevant: [count]
- Found: [what was located]

[Continue as needed]

Critical Code Located:

Primary Location:
- Component: [name]
- File: [file:path]
- Function/Method: [name]
- Lines: [range]

Call Path:
1. Entry: [file:function:line]
2. → [file:function:line]
3. → [file:function:line]
4. → Critical Code: [file:function:line]

Related Methods:
1. [method] - [file:line] - Role: [what it does]
2. [method] - [file:line] - Role: [what it does]

Discovery Time: [minutes]
Confidence (1-10): [score]
```

---

### T1.2: Bottleneck Characterization

**Objective:** Understand what makes it slow

**Execute:** Analyze the bottleneck:
- Is it CPU-bound?
- Is it I/O-bound?
- Is it memory-bound?
- Is it network-bound?
- What's the specific issue?

**Success Criteria:**
- Identifies bottleneck type
- Explains why it's slow
- Quantifies impact
- Pinpoints specific cause

**Document:**
```
Bottleneck Characterization:

Bottleneck Type: [CPU/I/O/Memory/Network/Algorithm]

Analysis:

CPU Usage:
- Expected: [description]
- Actual: [observation from code]
- Issue: [if any]

I/O Operations:
- Disk Reads: [how many/how large]
- Disk Writes: [how many/how large]
- Network Calls: [how many]
- Issue: [if any]

Memory Usage:
- Allocations: [pattern]
- Data Structures: [what's in memory]
- Growth: [bounded/unbounded]
- Issue: [if any]

Algorithm:
- Complexity: [O(n), O(n²), etc]
- Data Volume: [how much processed]
- Issue: [if any]

Specific Cause:

Root Cause: [what specifically is slow]

Evidence:
- [code pattern that causes slowness]
- [data structure that's inefficient]
- [algorithm that doesn't scale]

Why It's Slow:
[clear explanation of performance issue]

Impact Quantification:
- Operations Per Request: [count]
- Time Per Operation: [estimate]
- Total Time: [calculation]
```

---

## Test 2: Understand Data Flow

**Scenario:** Understand what data is processed and how

### T2.1: Data Volume Analysis

**Objective:** Quantify how much data is processed

**Execute:** Trace data flow:
- How much data enters the operation?
- How is data transformed?
- How much data is processed at each step?
- What's the amplification factor?

**Success Criteria:**
- Quantifies input data
- Traces transformations
- Measures intermediate volumes
- Identifies amplification

**Document:**
```
Data Flow Analysis:

Input Data:
- Source: [where data comes from]
- Volume: [count/size]
- Format: [structure]
- Rate: [items/second or similar]

Data Transformations:

Step 1: [operation]
- Input Volume: [count/size]
- Processing: [what's done]
- Output Volume: [count/size]
- Amplification: [output/input ratio]

Step 2: [operation]
- Input Volume: [count/size]
- Processing: [what's done]
- Output Volume: [count/size]
- Amplification: [output/input ratio]

[Continue for all steps]

Final Output:
- Volume: [count/size]
- Format: [structure]

Data Amplification:

Total Amplification: [final/initial ratio]
Amplification Points:
- [step with high amplification] - [ratio]
- [step with high amplification] - [ratio]

Data Volume Impact:
[how volume affects performance]

Scalability:
- Scales With: [what dimension]
- Relationship: [linear/quadratic/exponential]
```

---

### T2.2: Data Structure Analysis

**Objective:** Evaluate efficiency of data structures used

**Execute:** Examine data structures:
- What data structures are used?
- Are they appropriate?
- What's the access pattern?
- What's the complexity?

**Success Criteria:**
- Identifies all structures
- Evaluates appropriateness
- Analyzes access patterns
- Calculates complexity

**Document:**
```
Data Structure Analysis:

Structures Used:

Structure 1: [type, e.g., list/dict/set/tree]
- Location: [where used]
- Size: [elements]
- Operations: [what's done]
- Access Pattern: [sequential/random/mixed]
- Complexity:
  - Insert: [O(?)]
  - Lookup: [O(?)]
  - Delete: [O(?)]
- Appropriate: [yes/no]
- Alternative: [if not appropriate]

Structure 2: [type]
[Same analysis...]

[Continue for all structures]

Structure Efficiency:

Inefficient Structures:
1. [structure] - [location]
   - Problem: [why inefficient]
   - Impact: [performance cost]
   - Better Option: [alternative]

2. [structure] - [location]
   [Same pattern...]

Access Pattern Issues:
- [pattern] - [why problematic]
- [pattern] - [why problematic]

Overall Assessment:
- Structures Appropriate: [yes/no/mostly]
- Major Issues: [count]
- Quick Wins: [improvements that are easy]
```

---

## Test 3: Find Existing Optimizations

**Scenario:** Learn from existing performance work

### T3.1: Optimization Pattern Discovery

**Objective:** Find how similar problems are optimized

**Execute:** Search for optimizations:
- Where is caching used?
- Where is batching used?
- Where are indexes used?
- What other optimizations exist?

**Success Criteria:**
- Finds caching patterns
- Identifies batching strategies
- Locates indexes
- Discovers other optimizations

**Document:**
```
Optimization Pattern Discovery:

Search Strategy:
Query 1: [search for "cache"]
- Patterns Found: [count]
- Examples: [locations]

Query 2: [search for "batch"]
- Patterns Found: [count]
- Examples: [locations]

Query 3: [search for performance keywords]
- Patterns Found: [count]
- Examples: [locations]

Optimization Patterns Found:

Caching:
1. [what's cached] - [file:line]
   - Strategy: [LRU/TTL/etc]
   - Hit Rate: [if observable]
   - Benefit: [what it speeds up]

2. [what's cached] - [file:line]
   [Same structure...]

Batching:
1. [what's batched] - [file:line]
   - Batch Size: [count]
   - Benefit: [efficiency gain]

Indexing:
1. [what's indexed] - [file:line]
   - Type: [hash/tree/etc]
   - Benefit: [lookup speed]

Other Optimizations:
1. [optimization] - [file:line]
   - Type: [lazy loading/pooling/etc]
   - Benefit: [what it improves]

Total Patterns: [count]
Applicable to Current Problem: [count]
```

---

### T3.2: Learn from Optimizations

**Objective:** Understand why optimizations work

**Execute:** Analyze existing optimizations:
- Why does each optimization work?
- What patterns can be reused?
- What can be applied to bottleneck?
- What are the tradeoffs?

**Success Criteria:**
- Explains optimization rationale
- Identifies reusable patterns
- Plans application
- Understands tradeoffs

**Document:**
```
Optimization Analysis:

Pattern 1: [optimization type]

How It Works:
[explanation of the technique]

Why It's Effective:
[what problem it solves]

Tradeoffs:
- Pros: [benefits]
- Cons: [costs/complexity]

Applicable to Bottleneck:
- Directly: [yes/no]
- With Modification: [yes/no - how]
- Estimated Impact: [high/medium/low]

Pattern 2: [optimization type]
[Same analysis...]

Key Learnings:

1. [learning] - [how to apply]
2. [learning] - [how to apply]
3. [learning] - [how to apply]

Reusable Patterns:
- [pattern] - Application: [how to use in bottleneck]
- [pattern] - Application: [how to use in bottleneck]

Overall Applicability: [high/medium/low]
```

---

## Test 4: Check Configurations

**Scenario:** Find tuning knobs and configuration options

### T4.1: Configuration Discovery

**Objective:** Locate performance-related configuration

**Execute:** Search for config options:
- What performance configs exist?
- Where are they defined?
- What are current values?
- What are optimal values?

**Success Criteria:**
- Finds all performance configs
- Understands each option
- Knows current values
- Identifies tuning opportunities

**Document:**
```
Configuration Discovery:

Performance Configs Found:

Config 1: [name]
- Location: [file:line]
- Purpose: [what it controls]
- Current Value: [value]
- Default Value: [value]
- Valid Range: [min-max]
- Impact: [what it affects]

Config 2: [name]
[Same structure...]

[Continue for all configs]

Configuration Categories:

Resource Limits:
- [config] - Current: [value] - Tunable: [yes/no]
- [config] - Current: [value] - Tunable: [yes/no]

Batch Sizes:
- [config] - Current: [value] - Tunable: [yes/no]

Cache Sizes:
- [config] - Current: [value] - Tunable: [yes/no]

Timeouts:
- [config] - Current: [value] - Tunable: [yes/no]

Total Configs: [count]
Tunable Configs: [count]
Discovery Method: [how you found them]
```

---

### T4.2: Configuration Tuning Opportunities

**Objective:** Identify optimal configuration values

**Execute:** Analyze configurations:
- Are current values optimal?
- What should be changed?
- What's the expected impact?
- What are the risks?

**Success Criteria:**
- Evaluates current values
- Recommends changes
- Estimates impact
- Assesses risks

**Document:**
```
Configuration Tuning Analysis:

Tuning Opportunities:

Opportunity 1:
- Config: [name]
- Current: [value]
- Recommended: [value]
- Reasoning: [why this value]
- Expected Impact: [% improvement]
- Risk: [low/medium/high]
- Test Before Production: [yes/no]

Opportunity 2:
[Same structure...]

[Continue for all opportunities]

Priority Tuning:

High Impact, Low Risk:
1. [config] - [current] → [recommended]
2. [config] - [current] → [recommended]

Medium Impact, Low Risk:
1. [config] - [current] → [recommended]

High Impact, High Risk:
1. [config] - [current] → [recommended]
   - Requires Testing: [what to test]

Total Opportunities: [count]
Quick Wins: [count - high impact, low risk]
Estimated Total Impact: [%]
```

---

## Test 5: Identify Alternatives

**Scenario:** Find alternative approaches that might be faster

### T5.1: Alternative Algorithm Discovery

**Objective:** Find different ways to solve the problem

**Execute:** Search for alternatives:
- How else is this problem solved?
- What alternative algorithms exist?
- What alternative libraries exist?
- What different approaches work?

**Success Criteria:**
- Identifies 3-5 alternatives
- Understands tradeoffs
- Estimates benefits
- Assesses feasibility

**Document:**
```
Alternative Approach Discovery:

Current Approach:
- Algorithm: [description]
- Complexity: [O(?)]
- Strengths: [what it does well]
- Weaknesses: [what it does poorly]

Alternatives Found:

Alternative 1: [name/description]
- Where Found: [location or research]
- Algorithm: [description]
- Complexity: [O(?)]
- Strengths: [benefits]
- Weaknesses: [drawbacks]
- Estimated Speedup: [X times faster]
- Implementation Effort: [hours/days]
- Feasibility: [high/medium/low]

Alternative 2: [name/description]
[Same structure...]

Alternative 3: [name/description]
[Same structure...]

[Continue for 3-5 alternatives]

Comparison Matrix:

| Approach | Complexity | Speed | Memory | Effort | Feasibility |
|----------|-----------|-------|--------|--------|-------------|
| Current | [O(?)] | baseline | baseline | 0 | - |
| Alt 1 | [O(?)] | [Xx] | [more/less] | [days] | [high/low] |
| Alt 2 | [O(?)] | [Xx] | [more/less] | [days] | [high/low] |

Best Alternative: [which one]
Reasoning: [why best]
```

---

### T5.2: Library/Tool Alternatives

**Objective:** Identify alternative libraries or tools

**Execute:** Research alternatives:
- What libraries do this faster?
- What tools are optimized for this?
- What's the performance difference?
- What's the migration effort?

**Success Criteria:**
- Finds alternative libraries
- Compares performance
- Estimates migration effort
- Makes recommendation

**Document:**
```
Library/Tool Alternatives:

Current Library/Tool:
- Name: [name]
- Version: [version]
- Performance: [benchmark if available]
- Limitations: [issues]

Alternatives:

Alternative 1: [name]
- Description: [what it is]
- Performance: [benchmark if available]
- Speedup vs Current: [Xx faster]
- Features:
  - Gained: [new capabilities]
  - Lost: [missing features]
- Migration Effort: [hours/days]
- Compatibility: [drop-in/requires changes]
- Maturity: [production-ready/experimental]
- Recommendation: [yes/no/maybe]

Alternative 2: [name]
[Same structure...]

[Continue for alternatives]

Best Option: [which library/tool]
Reasoning: [why]
Migration Plan: [high-level steps]
Risk Assessment: [what could go wrong]
```

---

## Test 6: Estimate Impact

**Scenario:** Quantify expected performance improvements

### T6.1: Impact Estimation

**Objective:** Estimate improvement from each optimization

**Execute:** Calculate expected impact:
- What's the current baseline?
- What's the improvement per optimization?
- What's the combined effect?
- What's the best case?

**Success Criteria:**
- Quantifies each improvement
- Estimates combined impact
- Shows calculations
- Provides confidence ranges

**Document:**
```
Impact Estimation:

Current Baseline:
- Metric: [what you're measuring]
- Current Value: [measurement]
- Target Value: [goal]
- Gap: [how much improvement needed]

Optimization Impacts:

Optimization 1: [name]
- Type: [config/code/algorithm/library]
- Estimated Improvement: [%] or [Xx faster]
- Confidence: [high/medium/low]
- Calculation:
  [show work - how you estimated]

Optimization 2: [name]
[Same structure...]

[Continue for all optimizations]

Combined Impact:

Conservative Estimate:
- Optimization 1: [%]
- Optimization 2: [%]
- Optimization 3: [%]
- Combined: [%] (not simple sum if optimizations overlap)
- Final Performance: [value]

Realistic Estimate:
- Combined: [%]
- Final Performance: [value]

Optimistic Estimate:
- Combined: [%]
- Final Performance: [value]

Meets Target:
- Conservative: [yes/no]
- Realistic: [yes/no]
- Optimistic: [yes/no]

Recommendation: [which optimizations to pursue]
```

---

### T6.2: Implementation Priority

**Objective:** Prioritize optimizations by impact and effort

**Execute:** Create priority matrix:
- What's the effort for each?
- What's the impact of each?
- What's the priority?
- What's the implementation order?

**Success Criteria:**
- Effort estimated
- Impact quantified
- Priorities assigned
- Implementation plan created

**Document:**
```
Optimization Priority Matrix:

| Optimization | Impact | Effort | Risk | Priority | Order |
|--------------|--------|--------|------|----------|-------|
| [name] | [%] | [hours] | [L/M/H] | [High/Med/Low] | [1/2/3...] |
| [name] | [%] | [hours] | [L/M/H] | [High/Med/Low] | [1/2/3...] |
| [name] | [%] | [hours] | [L/M/H] | [High/Med/Low] | [1/2/3...] |

Quick Wins (High Impact, Low Effort):
1. [optimization] - Impact: [%] - Effort: [hours]
2. [optimization] - Impact: [%] - Effort: [hours]

Major Projects (High Impact, High Effort):
1. [optimization] - Impact: [%] - Effort: [days]

Nice-to-Haves (Low Impact, Low Effort):
1. [optimization] - Impact: [%] - Effort: [hours]

Not Worth It (Low Impact, High Effort):
1. [optimization] - Skip because: [reason]

Implementation Plan:

Phase 1: Quick Wins
- [optimization] - [timeline]
- [optimization] - [timeline]
- Expected Impact: [%]

Phase 2: Configuration Tuning
- [optimization] - [timeline]
- Expected Impact: [%]

Phase 3: Major Changes (if needed)
- [optimization] - [timeline]
- Expected Impact: [%]

Total Timeline: [weeks/months]
Total Impact: [%]
Confidence (1-10): [score]
```

---

## Final Evaluation

### Performance Investigation Metrics

**Time Metrics:**
```
Investigation Duration: [minutes]
Target: ≤45 minutes
Met Target: [yes/no]

Breakdown:
- Bottleneck Identification: [minutes]
- Data Flow Analysis: [minutes]
- Optimization Discovery: [minutes]
- Alternative Research: [minutes]
- Impact Estimation: [minutes]
```

**Discovery Metrics:**
```
Bottleneck Located: [yes/no]
Time to Locate: [minutes]
Target: ≤20 minutes
Met Target: [yes/no]

Root Cause Understood: [yes/no]
Confidence in Cause: [1-10]
```

**Optimization Metrics:**
```
Optimizations Identified: [count]
Target: ≥3
Met Target: [yes/no]

Quick Wins: [count]
Major Improvements: [count]
Total Expected Impact: [%]
```

**Confidence Metrics:**
```
Analysis Confidence: [1-10]
Target: ≥8
Met Target: [yes/no]

Recommendation Confidence: [1-10]
Would Implement: [yes/no]
Expected Success: [yes/no]
```

### Production Readiness

**Critical Checks:**
- [ ] Bottleneck identified within 20 minutes
- [ ] Root cause understood clearly
- [ ] Found ≥3 optimization opportunities
- [ ] Estimated impact for each
- [ ] Prioritized by effort/impact
- [ ] Created implementation plan
- [ ] Confidence ≥8/10

**Pass/Fail:** [PASS/FAIL]

---

## Summary & Recommendations

### What Worked Well
```
[3-5 things that helped performance investigation]
```

### What Was Challenging
```
[3-5 challenges in identifying optimizations]
```

### Investigation Effectiveness

**Answer: [Very Effective / Effective / Somewhat Effective / Not Effective]**

**Reasoning:**
```
[2-3 paragraphs on:]
- Speed of bottleneck discovery
- Quality of analysis
- Value of recommendations
- Confidence in improvements
- Comparison to manual profiling
```

### Recommendations

**Immediate Actions (Quick Wins):**
```
[Specific optimizations to implement first]
```

**Long-term Improvements:**
```
[Architectural or major changes to consider]
```

**Monitoring:**
```
[What metrics to track to verify improvements]
```

---

## Test Completion

**Test Metadata:**
```
Duration: [minutes]
Tester: [name/id]
Date: [YYYY-MM-DD]
Performance Issue: [description]
Bottleneck Found: [yes/no]
Optimizations Identified: [count]
Expected Improvement: [%]
Confidence Achieved: [score]/10
```

**Key Metrics:**
```
Bottleneck Discovery Time: [minutes]
Optimization Count: [count]
Quick Wins: [count]
Expected Impact: [%]
Implementation Effort: [hours/days]
Overall Success: [yes/no]
```

---

**Remember:** Performance investigation requires understanding both the problem and potential solutions. Good investigation finds quick wins AND identifies major improvements.
