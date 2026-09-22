# Use Case 5: Knowledge Building & Learning

**Purpose:** Validate agent's ability to accumulate and leverage knowledge over time
**Output Path:** test_results/knowledge_building/{YYYYMMDD}_{HHMMSS}.md
**Philosophy:** "Am I getting smarter about this codebase over time?"

---

## Test Suite Overview

This test evaluates how effectively an agent can build and leverage knowledge using Agentic Inquiry to:
- Store meaningful insights and patterns
- Recall previous learnings accurately
- Track decisions and rationale
- Build expertise over multiple sessions
- Improve efficiency through accumulated knowledge
- Avoid repeating mistakes

### Success Criteria

Knowledge building is successful if the agent can:
- Store insights that are retrievable later
- Recall relevant knowledge when needed
- Build on previous learnings
- Demonstrate improved efficiency over time
- Avoid making the same mistakes twice

**Time Limit:** N/A (evaluated over multiple sessions)
**Confidence Threshold:** 8/10 or higher on "knowledge is useful" scale

---

## Pre-Test Setup

### Prerequisites

> **CRITICAL: You MUST index the codebase yourself.** Do NOT assume pre-existing data is valid.
> See USE_CASES.md "Ensure Fresh Index" for detailed instructions.

**Step 1: Create Session with Unique Project ID**
```python
project_id = "ai_test06_knowledge_{YYYYMMDD_HHMMSS}"
session = create_session(project_id=project_id, description="Knowledge building test")
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

1. **Clean Session:** Start with fresh session (no prior memories for this test)
2. **Multiple Sessions Planned:** Plan to work across 3-5 sessions
3. **Tasks Defined:** Choose tasks that build on each other

### Knowledge Building Approach

This test runs across **multiple sessions** to validate knowledge persistence:

**Session 1: Initial Discovery**
- Learn about codebase
- Store initial insights
- Document patterns found

**Session 2: Building on Knowledge**
- Resume from Session 1
- Recall previous insights
- Add new learnings

**Session 3: Expertise Demonstration**
- Apply accumulated knowledge
- Show improved efficiency
- Demonstrate pattern recognition

**Session 4-5: Validation**
- Test knowledge recall accuracy
- Verify decision tracking
- Assess expertise growth

---

## Test 1: Store Insights

**Scenario:** Capture meaningful insights about the codebase

### T1.1: Pattern Recognition and Storage

**Objective:** Identify patterns and store them as memories

**Execute:** During initial codebase exploration:
- What patterns do you notice?
- What design decisions stand out?
- What conventions are used?
- What would be useful to remember?

Store 5-10 pattern insights.

**Success Criteria:**
- Identifies meaningful patterns
- Stores with clear descriptions
- Tags appropriately
- Sets importance levels correctly

**Document:**
```
Session: [session ID]
Date: [YYYY-MM-DD]

Patterns Discovered:

Pattern 1: [name/description]
- Observation: [what you noticed]
- Where: [locations]
- Why Important: [significance]
- Memory Stored:
  - Summary: [brief]
  - Tags: [tags]
  - Importance: [0.0-1.0]
  - ID: [memory ID if returned]

Pattern 2: [name/description]
- Observation: [what you noticed]
- Where: [locations]
- Why Important: [significance]
- Memory Stored:
  - Summary: [brief]
  - Tags: [tags]
  - Importance: [0.0-1.0]
  - ID: [memory ID if returned]

[Continue for 5-10 patterns]

Storage Success Rate: [%]
Total Patterns Stored: [count]
```

---

### T1.2: Decision Documentation

**Objective:** Store rationale for code decisions

**Execute:** When you learn why code is designed a certain way:
- Why was X implemented this way?
- What alternatives were considered?
- What constraints influenced the decision?
- What would be useful context later?

Store 3-5 decision rationales.

**Success Criteria:**
- Captures decision context
- Documents alternatives
- Records constraints
- Links to relevant code

**Document:**
```
Decisions Documented:

Decision 1: [what was decided]
- Context: [situation requiring decision]
- Decision: [what was chosen]
- Rationale: [why this choice]
- Alternatives: [what else was considered]
- Tradeoffs: [pros/cons]
- Memory Stored:
  - Summary: [brief]
  - Tags: [tags]
  - Importance: [0.0-1.0]
  - ID: [memory ID]

Decision 2: [what was decided]
[same structure...]

[Continue for 3-5 decisions]

Total Decisions Stored: [count]
Completeness: [comprehensive/adequate/minimal]
```

---

### T1.3: Gotchas and Pitfalls

**Objective:** Document things that could cause problems

**Execute:** Record potential issues:
- What edge cases exist?
- What mistakes are easy to make?
- What breaks easily?
- What should future developers know?

Store 3-5 gotchas/warnings.

**Success Criteria:**
- Identifies real pitfalls
- Explains why they matter
- Provides prevention advice
- Stores for retrieval

**Document:**
```
Gotchas Documented:

Gotcha 1: [what to watch out for]
- Problem: [what can go wrong]
- Why: [root cause]
- Symptoms: [how you'd notice]
- Prevention: [how to avoid]
- Memory Stored:
  - Summary: [brief]
  - Tags: [tags]
  - Importance: [0.0-1.0]
  - ID: [memory ID]

[Continue for 3-5 gotchas]

Total Warnings Stored: [count]
Could Save Future Time: [yes/no - estimate]
```

---

## Test 2: Recall Patterns

**Scenario:** Retrieve stored knowledge when needed (New Session)

### T2.1: Pattern Recall by Topic

**Objective:** Query for patterns on specific topics

**Execute:** In a new session, query for patterns:
- Query: "design patterns"
- Query: "error handling"
- Query: "configuration"
- Query: specific component name

**Success Criteria:**
- Retrieves relevant patterns
- Results are accurate
- Ranking makes sense
- Recall is fast (< 3 seconds)

**Document:**
```
Session: [new session ID]
Date: [YYYY-MM-DD]

Pattern Recall Tests:

Query 1: "design patterns"
- Memories Retrieved: [count]
- Relevant: [count]
- Precision: [%]
- Top Result: [summary]
- Correct: [yes/no]
- Time: [seconds]

Query 2: "error handling"
- Memories Retrieved: [count]
- Relevant: [count]
- Precision: [%]
- Top Result: [summary]
- Correct: [yes/no]
- Time: [seconds]

Query 3: [specific topic]
- Memories Retrieved: [count]
- Relevant: [count]
- Precision: [%]
- Top Result: [summary]
- Correct: [yes/no]
- Time: [seconds]

Average Precision: [%]
Average Recall Time: [seconds]
Overall Recall Quality: [excellent/good/fair/poor]
```

---

### T2.2: Contextual Recall

**Objective:** Recall relevant knowledge in context of a task

**Execute:** When starting a new task, query for related knowledge:
- "How did we handle similar feature before?"
- "What patterns should I follow for X?"
- "What warnings exist for component Y?"

**Success Criteria:**
- Retrieves applicable knowledge
- Context helps with task
- Saves time vs. re-discovery
- Knowledge is current

**Document:**
```
Task: [description of new task]

Contextual Knowledge Queries:

Query: [what you need to know]
- Retrieved: [count] memories
- Relevant Memories:
  1. [summary] - Usefulness: [high/medium/low]
  2. [summary] - Usefulness: [high/medium/low]
  3. [summary] - Usefulness: [high/medium/low]

Applied Knowledge:
- Used: [which memories]
- How: [how they helped]
- Time Saved: [estimate]

Without Memory Would Have:
[what you would have had to do]

Knowledge Value: [invaluable/very useful/somewhat useful/not useful]
```

---

### T2.3: Decision History Recall

**Objective:** Recall why decisions were made

**Execute:** When encountering design choices, query for rationale:
- "Why is X implemented this way?"
- "What alternatives were considered for Y?"
- "What constraints led to Z?"

**Success Criteria:**
- Retrieves decision context
- Explains rationale clearly
- Prevents redesigning solved problems
- Provides historical context

**Document:**
```
Decision Queries:

Query: "Why is [X] implemented this way?"
- Memory Found: [yes/no]
- Rationale Retrieved: [summary]
- Alternatives Documented: [yes/no]
- Constraints Explained: [yes/no]
- Completeness: [complete/partial/missing]

Query: "What alternatives were considered for [Y]?"
- Memory Found: [yes/no]
- Alternatives: [list]
- Tradeoffs: [documented yes/no]
- Useful: [yes/no]

Historical Context Value:
- Prevented Rework: [yes/no - example]
- Explained Constraints: [yes/no - example]
- Informed New Decisions: [yes/no - example]

Decision History Quality: [excellent/good/fair/poor]
```

---

## Test 3: Track Decisions

**Scenario:** Maintain audit trail of work and decisions

### T3.1: Session Event Tracking

**Objective:** Track what was done in each session

**Execute:** Review session events:
- What files were indexed?
- What searches were performed?
- What entities were analyzed?
- What patterns were found?

**Success Criteria:**
- Events are logged automatically
- Event history is queryable
- Provides useful audit trail
- Can reconstruct session work

**Document:**
```
Session Review:

Session ID: [ID]
Date: [YYYY-MM-DD]
Duration: [minutes]

Events Retrieved:
- Total Events: [count]
- Event Types: [list types]

Key Activities:
1. [event type] - [count] times - [files/entities]
2. [event type] - [count] times - [files/entities]
3. [event type] - [count] times - [files/entities]

Session Summary from Events:
[what the agent worked on based on event log]

Event Tracking Quality:
- Complete: [yes/no]
- Useful: [yes/no]
- Queryable: [yes/no]

Could Reconstruct Work: [yes/no]
```

---

### T3.2: Work Continuity

**Objective:** Resume work from previous session seamlessly

**Execute:** Start new session and resume:
- Query: "What was I working on last session?"
- Review recent events
- Recall relevant context
- Continue where left off

**Success Criteria:**
- Can determine previous work
- Retrieves relevant context
- Resumes without rework
- Builds on prior progress

**Document:**
```
Resuming Work:

Previous Session: [ID]
Time Since Last Session: [hours/days]

Resume Query: "What was I working on?"
- Events Found: [count]
- Context Retrieved: [summary]
- Last Activity: [description]

Relevant Memories:
- Retrieved: [count]
- Useful: [count]
- Context: [what they provided]

Able to Resume:
- Without Rework: [yes/no]
- With Full Context: [yes/no]
- Quickly (< 5 min): [yes/no]

Continuity Quality: [excellent/good/fair/poor]
Time Saved vs. Starting Fresh: [estimate]
```

---

## Test 4: Build Expertise Over Time

**Scenario:** Demonstrate improving efficiency across sessions

### T4.1: Efficiency Metrics

**Objective:** Show work gets faster with accumulated knowledge

**Execute:** Compare metrics across sessions:
- Session 1: Time to understand component
- Session 2: Time to understand related component
- Session 3: Time to understand another component

**Success Criteria:**
- Time decreases across sessions
- Fewer queries needed
- Higher confidence
- Less redundant discovery

**Document:**
```
Efficiency Progression:

Session 1 (Initial):
- Task: [what was done]
- Time: [minutes]
- Queries: [count]
- Confidence: [1-10]
- New Learnings: [count]

Session 2 (Building):
- Task: [what was done]
- Time: [minutes]
- Queries: [count]
- Confidence: [1-10]
- New Learnings: [count]
- Applied Previous Knowledge: [yes/no - examples]

Session 3 (Experienced):
- Task: [what was done]
- Time: [minutes]
- Queries: [count]
- Confidence: [1-10]
- New Learnings: [count]
- Applied Previous Knowledge: [yes/no - examples]

Efficiency Trend:
- Time: [Session 1] → [Session 2] → [Session 3]
- Change: [improving/stable/degrading]
- Queries: [Session 1] → [Session 2] → [Session 3]
- Change: [improving/stable/degrading]

Demonstrable Improvement: [yes/no]
Learning Curve: [steep/moderate/flat]
```

---

### T4.2: Pattern Recognition Speed

**Objective:** Show faster pattern recognition over time

**Execute:** Measure pattern recognition:
- Session 1: Time to identify first pattern
- Session 2: Time to identify pattern in new area
- Session 3: Time to identify pattern in another area

**Success Criteria:**
- Recognition time decreases
- More patterns identified
- Deeper understanding
- Connects patterns across codebase

**Document:**
```
Pattern Recognition Evolution:

Session 1:
- First Pattern Identified: [minutes]
- Total Patterns Found: [count]
- Depth: [surface/moderate/deep]

Session 2:
- First Pattern Identified: [minutes]
- Total Patterns Found: [count]
- Depth: [surface/moderate/deep]
- Connected to Previous: [yes/no - how]

Session 3:
- First Pattern Identified: [minutes]
- Total Patterns Found: [count]
- Depth: [surface/moderate/deep]
- Cross-codebase Connections: [count]

Recognition Speed Trend:
- Improving: [yes/no]
- Pattern Quality: [improving/stable/degrading]
- Understanding Depth: [increasing/stable/decreasing]

Expertise Indicators:
- Sees patterns faster: [yes/no]
- Finds deeper patterns: [yes/no]
- Makes connections: [yes/no]
```

---

### T4.3: Reduced Mistakes

**Objective:** Show fewer repeated mistakes over time

**Execute:** Track mistake patterns:
- Session 1: Document any mistakes or inefficiencies
- Session 2: Check if same mistakes repeated
- Session 3: Verify learning from mistakes

**Success Criteria:**
- Mistakes are documented
- Previous mistakes avoided
- Warnings are heeded
- Improvement is measurable

**Document:**
```
Mistake Tracking:

Session 1 Mistakes:
1. [mistake] - [why it happened]
2. [mistake] - [why it happened]
3. [mistake] - [why it happened]

Lessons Stored:
- [lesson] - Importance: [0.0-1.0]
- [lesson] - Importance: [0.0-1.0]

Session 2:
- Previous Mistakes Repeated: [count]
- New Mistakes: [count]
- Warnings Heeded: [count]

Session 3:
- Previous Mistakes Repeated: [count]
- New Mistakes: [count]
- Warnings Heeded: [count]

Learning Indicators:
- Avoids Documented Pitfalls: [yes/no]
- Applies Lessons: [yes/no]
- Shares Warnings: [yes/no]

Mistake Reduction: [significant/moderate/minimal/none]
```

---

## Test 5: Knowledge Quality Assessment

**Scenario:** Evaluate the quality and usefulness of accumulated knowledge

### T5.1: Knowledge Coverage

**Objective:** Assess breadth and depth of knowledge

**Execute:** Evaluate knowledge base:
- How many distinct topics covered?
- What areas have deep knowledge?
- What areas have gaps?
- Is knowledge balanced?

**Success Criteria:**
- Broad topic coverage
- Deep understanding in key areas
- Gaps identified
- Knowledge is organized

**Document:**
```
Knowledge Coverage Analysis:

Topics Covered:
1. [topic] - Memories: [count] - Depth: [deep/moderate/shallow]
2. [topic] - Memories: [count] - Depth: [deep/moderate/shallow]
3. [topic] - Memories: [count] - Depth: [deep/moderate/shallow]
[continue...]

Coverage Statistics:
- Total Topics: [count]
- Deep Understanding: [count] topics
- Moderate Understanding: [count] topics
- Shallow Understanding: [count] topics

Knowledge Gaps:
1. [gap area] - Why Missing: [reason]
2. [gap area] - Why Missing: [reason]

Coverage Quality:
- Breadth: [wide/moderate/narrow]
- Depth: [deep/moderate/shallow]
- Balance: [good/uneven]

Overall Coverage: [excellent/good/adequate/poor]
```

---

### T5.2: Knowledge Utility

**Objective:** Measure how useful stored knowledge actually is

**Execute:** Assess practical value:
- How often is knowledge recalled?
- Does recalled knowledge help?
- What knowledge is never used?
- What's missing that would help?

**Success Criteria:**
- High-value knowledge recalled frequently
- Recalled knowledge proves useful
- Low-value knowledge identified
- Needs are identified

**Document:**
```
Knowledge Utility Assessment:

Recall Frequency (across all sessions):
- High (>5 recalls): [count] memories
- Medium (2-5 recalls): [count] memories
- Low (1 recall): [count] memories
- Never recalled: [count] memories

Most Useful Memories:
1. [summary] - Recalls: [count] - Value: [why useful]
2. [summary] - Recalls: [count] - Value: [why useful]
3. [summary] - Recalls: [count] - Value: [why useful]

Never Used But Stored:
- Count: [count]
- Examples: [list a few]
- Why Not Used: [analysis]

Missing Knowledge:
- [what would be helpful]
- [what would be helpful]

Utility Metrics:
- Useful Recall Rate: [%]
- Average Value Rating: [1-10]
- Knowledge ROI: [high/medium/low]

Overall Utility: [excellent/good/fair/poor]
```

---

### T5.3: Knowledge Maintenance

**Objective:** Evaluate if knowledge stays current and accurate

**Execute:** Check knowledge freshness:
- Is stored knowledge still accurate?
- Has code changed making knowledge stale?
- Is outdated knowledge updated?
- How is knowledge validated?

**Success Criteria:**
- Knowledge is current
- Stale knowledge identified
- Update mechanisms exist
- Validation occurs

**Document:**
```
Knowledge Maintenance Review:

Accuracy Check:
- Memories Sampled: [count]
- Still Accurate: [count]
- Outdated: [count]
- Unknown: [count]
- Accuracy Rate: [%]

Outdated Knowledge Examples:
1. [memory] - Why Outdated: [reason]
2. [memory] - Why Outdated: [reason]

Update Mechanisms:
- Automatic Detection: [yes/no]
- Manual Review: [yes/no]
- Validation Process: [yes/no]

Knowledge Freshness:
- Current: [%]
- Needs Update: [%]
- Obsolete: [%]

Maintenance Quality: [excellent/good/fair/poor]
Recommendation: [keep as-is/improve validation/add updates]
```

---

## Final Evaluation

### Knowledge Building Effectiveness

**Storage Metrics:**
```
Total Memories Stored: [count]
Topics Covered: [count]
Average Importance: [0.0-1.0]

Storage Distribution:
- Patterns: [count]
- Decisions: [count]
- Warnings: [count]
- Other: [count]

Storage Success Rate: [%]
```

**Retrieval Metrics:**
```
Total Retrievals: [count]
Average Precision: [%]
Average Recall Time: [seconds]

Useful Retrievals: [count]
Useful Rate: [%]
Target: ≥90%
Met Target: [yes/no]
```

**Learning Metrics:**
```
Efficiency Improvement: [%]
Pattern Recognition Speed: [improved/stable/declined]
Mistake Reduction: [significant/moderate/minimal]

Expertise Indicators:
- Faster over time: [yes/no]
- Deeper understanding: [yes/no]
- Makes connections: [yes/no]
- Avoids mistakes: [yes/no]
```

**Quality Metrics:**
```
Knowledge Coverage: [excellent/good/adequate/poor]
Knowledge Utility: [%] useful recalls
Knowledge Accuracy: [%] current and correct
Knowledge Maintenance: [good/needs improvement]

Overall Quality: [excellent/good/fair/poor]
Confidence in Knowledge (1-10): [score]
Target: ≥8
Met Target: [yes/no]
```

### Production Readiness

**Critical Checks:**
- [ ] Stores meaningful knowledge reliably
- [ ] Retrieves relevant knowledge accurately (≥90% precision)
- [ ] Demonstrates learning over time
- [ ] Shows efficiency improvements
- [ ] Avoids repeating mistakes
- [ ] Knowledge remains current and useful
- [ ] Confidence ≥8/10

**Pass/Fail:** [PASS/FAIL]

---

## Summary & Recommendations

### What Worked Well
```
[3-5 things that enabled effective knowledge building]
```

### What Was Challenging
```
[3-5 challenges in building and using knowledge]
```

### Knowledge System Effectiveness

**Answer: [Very Effective / Effective / Somewhat Effective / Not Effective]**

**Reasoning:**
```
[2-3 paragraphs on:]
- Quality of knowledge storage and retrieval
- Demonstrated learning and improvement
- Practical value in real work
- Long-term sustainability
- Comparison to human learning
```

### Recommendations

**For Knowledge System Improvement:**
```
[Suggestions to improve knowledge building features]
```

**For Best Practices:**
```
[How to get most value from knowledge system]
```

---

## Test Completion

**Test Metadata:**
```
Test Duration: [days/weeks]
Sessions: [count]
Tester: [name/id]
Start Date: [YYYY-MM-DD]
End Date: [YYYY-MM-DD]
Memories Created: [count]
Recalls Performed: [count]
Efficiency Gain: [%]
Knowledge Quality: [score]/10
```

**Key Metrics:**
```
Storage Success: [%]
Retrieval Precision: [%]
Learning Demonstrated: [yes/no]
Expertise Growth: [yes/no]
Overall Success: [yes/no]
```

---

**Remember:** Effective knowledge building means getting smarter over time, not just storing data. The system should help you work faster and make fewer mistakes as sessions progress.
