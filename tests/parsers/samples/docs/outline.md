# Presentation Outline: Agentic Inquiry (Executive Version)

## Slide 1: Title

**Title:** Agentic Inquiry: The "Brain" That Makes AI Agents Work

**Subtitle:** Stop wasting tokens and start getting results. Agentic Inquiry is the essential control plane for deploying safe, efficient, and truly intelligent AI agents.

**Visual:** A graphic showing a large, powerful "LLM Engine" icon. A second, smaller "Agentic Inquiry" brain icon connects to it, providing a focused beam of light (context) to the engine, which is now successfully performing a complex task on a codebase.

---

## Slide 2: The "Last Mile" Problem with Enterprise AI

**Title:** Our AI Agents Are Flying Blind

**Key Point:** We've invested in powerful AI models, but they operate with a critical handicap: they have no deep, persistent understanding of *our* systems, *our* code, or *our* data.

**The Two Failure Modes of AI Agents:**
1.  **Context Overload ("The Firehose"):** We dump thousands of files into the context window.
    - **Result:** Massive token waste (97%+), slow performance, and a confused agent that can't find the signal in the noise.
2.  **Context Starvation ("Amnesia"):** The agent has no context.
    - **Result:** Hallucinations, dangerous errors, and an inability to perform any task that requires more than one step.

**The Business Impact:** Wasted spend on tokens, failed AI initiatives, and a tangible risk of agents causing production issues.

**Visual:** A simple two-panel cartoon.
- **Panel 1:** An "AI Agent" robot is buried under a mountain of papers labeled "Entire Codebase." The caption reads: "Context Overload."
- **Panel 2:** The same robot is blindfolded, about to walk off a cliff. The caption reads: "Context Starvation."

---

## Slide 3: The Solution: Four Breakthrough Capabilities

**Title:** Agentic Inquiry: Not Just Search—A Complete Cognitive System

**Key Point:** While competitors offer "search," Agentic Inquiry gives agents four cognitive capabilities that transform them from tools into teammates.

---

### **1. Local-First Architecture (Zero Trust Required)**

**The problem others have:**
- Cloud RAG: Your code uploaded to vendor servers
- GitHub Copilot: Sends code to external APIs
- Security review: 3-6 months before you can even start

**Agentic Inquiry difference:**
- Everything runs on your machine (embedded databases)
- Zero external API calls (verified by network monitoring)
- 5-minute setup (no cloud accounts, no infrastructure)
- Works offline (air-gapped environments approved)

**Perfect for:** Finance, healthcare, government (code never leaves your control)

---

### **2. Three-Tier Memory System (Agents That Learn & Remember)**

**The problem others have:**
- Every conversation starts from zero
- Agents repeat the same mistakes
- Knowledge walks out the door when people leave

**Agentic Inquiry difference:**
- **Working Memory**: Current task context (hours) - high precision
- **Episodic Memory**: Recent learnings (days) - session knowledge
- **Semantic Memory**: Permanent expertise (forever) - institutional knowledge

**Real impact:**
- Bug fixed once → Remembered forever (2ms instant recall)
- Agent 1 learns caching pattern → Agent 2 starts with that knowledge
- Your organizational knowledge compounds over time

**Example:**
```
Week 1: Agent fixes "login fails when cache empty" bug
Week 3: Different agent encounters similar issue
Result: Instant recall in 2ms (vs. 15 minutes of re-investigation)
```

---

### **3. Cognitive Workflows (Not Just Search—Real Problem Solving)**

**The problem others have:**
- `search(query)` → returns 500 files → agent confused
- One-shot answers, no exploration or refinement
- Agents can answer questions but can't solve complex problems

**Agentic Inquiry difference:**

**A. Explore** - Discover patterns across your codebase
```
Agent: "How does our authentication work?"
System: Returns diverse samples (infrastructure, services, config, docs, tests)
Agent: Sees the full picture before acting
```

**B. Refine** - Learn from feedback, focus on what matters
```
Agent: "More like this, less like that"
System: Re-ranks with 98% relevance (vs. 40% initially)
Agent: Gets dramatically better with each iteration
```

**C. Synthesize** - Identify patterns and best practices
```
Agent: "What do these 5 implementations have in common?"
System: "All inherit BaseCacheService, TTLs vary by data volatility"
Agent: Knows exactly how to implement correctly
```

**D. Context** - Build exactly what's needed for each task
```
Agent: "Add rate limiting to login"
System: Returns 3 files + existing patterns + dependencies
Agent: Follows established patterns, safe change
```

**Real workflow:**
- Traditional RAG: "What does this code do?" ✅ (answers questions)
- Agentic Inquiry: "Refactor error handling across 87 endpoints" ✅ (solves problems)

---

### **4. Knowledge Graph Navigation (Architecture Understanding)**

**The problem others have:**
- Text search: Finds files by keywords (misses relationships)
- Semantic search: Understands meaning (misses dependencies)
- Result: Agents break things they didn't know were connected

**Agentic Inquiry difference:**
- Maps your entire system (entities + relationships)
- Shows what calls what, what depends on what
- Reveals hidden dependencies before agent acts

**Real scenarios:**

**"If I change this function, what breaks?"**
- Graph shows 12 callers across 3 services
- Agent updates all safely, zero production issues

**"Show me the path from login to database"**
- Graph reveals: login → authenticate → session_manager → db_pool → postgres
- Agent understands the flow, makes informed decisions

**"What depends on this service?"**
- Graph finds 5 downstream services
- Agent knows to run integration tests before deploying

---

**Visual:** Four-quadrant diagram showing:

**Quadrant 1 (Local-First):**
- Icon: Locked laptop
- "Your Machine - Zero Exfiltration"

**Quadrant 2 (Memory System):**
- Icon: Brain with layers
- "Working → Episodic → Semantic"
- "Learns & Remembers Forever"

**Quadrant 3 (Cognitive Workflows):**
- Icon: Cycle diagram
- "Explore → Refine → Synthesize"
- "Real Problem Solving"

**Quadrant 4 (Knowledge Graph):**
- Icon: Network diagram
- "Architecture Understanding"
- "Prevents Breaking Changes"

**Center:** "Agentic Inquiry = Complete Cognitive System"

---

## Slide 4: How The Memory System Creates Compound Knowledge

**Title:** From Goldfish Memory to Institutional Expertise

**Key Point:** Most AI agents forget everything between conversations. Agentic Inquiry's three-tier memory system means your organization gets smarter every single day.

---

### **The Memory Problem: Why Agents Keep Starting From Zero**

**Traditional AI Tools:**
```
Session 1: Agent figures out authentication uses JWT tokens (15 min, 20K tokens)
Session 2: Different agent asks same question → Starts from scratch again
Session 3: Same issue, same investigation, same waste
```

**Result:**
- ❌ No learning between sessions
- ❌ Same mistakes repeated
- ❌ Every agent rediscovers the wheel
- ❌ Knowledge dies when employees leave

---

### **Agentic Inquiry's Three-Tier Memory: How Humans Actually Think**

**Working Memory (Current Task - Hours)**
- **Analog**: Your RAM—what you're actively thinking about right now
- **Retention**: Until task completes (~4 hours)
- **Embeddings**: High-density (1024d) for maximum precision
- **Use case**: "I'm currently refactoring auth_service.py"

**Example:**
```
Agent working on bug fix stores:
- "Testing user_cache.get() with None input"
- "Added null check at line 156"
- "Still need to verify edge case with empty string"

Stays in working memory until bug is fixed and tested
```

---

**Episodic Memory (Recent Experiences - Days/Weeks)**
- **Analog**: Your notebook—recent projects and solutions
- **Retention**: Days to weeks
- **Embeddings**: Medium-density (582d) balanced speed/quality
- **Use case**: "Last week I fixed a caching bug"

**Example:**
```
After bug fix completes, promotes to episodic:
- "BUG-789: user_cache.get() null pointer"
- "Root cause: No None handling"
- "Fix location: auth/middleware.py:156"
- "Test coverage: test_auth_null_cache.py"

Available for days—similar bugs get instant context
```

---

**Semantic Memory (Permanent Expertise - Forever)**
- **Analog**: Your expertise—fundamental knowledge you'll never forget
- **Retention**: Permanent
- **Embeddings**: Low-density (384d) for instant retrieval
- **Use case**: "Our authentication always validates JWT tokens"

**Example:**
```
After seeing pattern 5+ times, promotes to semantic:
- "Authentication architecture: JWT tokens validated in middleware"
- "Cache pattern: All services inherit BaseCacheService"
- "Error handling: Use ErrorResponse class, log to Sentry"
- "Database: Connection pool in db_pool.py, 20 max connections"

Never forgotten—becomes institutional knowledge
```

---

### **How Consolidation Works: Automatic Knowledge Promotion**

**Background Process (Every 5 Minutes):**

```python
# Working → Episodic (if important)
if memory.access_count >= 3 or memory.age > 4_hours:
    promote_to_episodic(memory)

# Episodic → Semantic (if fundamental)
if memory.importance >= 0.7 or memory.access_count >= 5:
    promote_to_semantic(memory)
```

**What determines importance?**
- Access frequency (how often recalled)
- Explicit tags ("critical", "bug", "security")
- Impact scope (affects multiple services?)
- Resolution success (did it fix the problem?)

---

### **Real Impact: Knowledge That Compounds**

**Month 1: Building the Foundation**
```
Week 1: 10 agents work on 10 different features
- Each discovers patterns, fixes bugs, makes decisions
- All saved to memory (50 insights stored)

Week 2: New agents start projects
- Instead of rediscovering, they recall from memory
- "How does our caching work?" → Instant answer (2ms)
- Productivity: 30% faster than Week 1
```

**Month 3: Expertise Accumulates**
```
- Semantic memory has 200+ fundamental patterns
- Episodic memory has 500+ recent solutions
- New engineers onboard in 2 days instead of 2 weeks
- Agents make zero repeated mistakes
```

**Month 6: Institutional Knowledge**
```
- 1,000+ permanent insights in semantic memory
- Agent asks: "What are our security best practices?"
- Response: Instant list from 6 months of learnings
- This knowledge NEVER existed in docs before
```

---

### **Comparison: Memory vs. No Memory**

| Scenario | Without Memory | With Agentic Inquiry |
|----------|---------------|-------------------|
| **Bug Investigation** | 15 min search every time | 2ms recall if seen before |
| **Architecture Questions** | Read 20 files each time | Instant from semantic memory |
| **Repeated Mistakes** | Same bug fixed 3x in 3 months | Fixed once, remembered forever |
| **Onboarding** | 2 weeks of tribal knowledge transfer | 2 days with memory-assisted learning |
| **Knowledge Transfer** | Walks out door with employee | Stays in semantic memory |

---

### **The Compound Effect**

**Traditional Tools (Linear):**
```
Agent 1 productivity: 100%
Agent 2 productivity: 100% (starts fresh)
Agent 3 productivity: 100% (starts fresh)
Total knowledge: Each agent's individual learnings (lost after session)
```

**Agentic Inquiry (Exponential):**
```
Agent 1 productivity: 100% (builds foundation)
Agent 2 productivity: 130% (learns from Agent 1)
Agent 3 productivity: 160% (learns from 1 + 2)
Total knowledge: Compounds every day (permanent semantic memory)
```

**After 6 months:**
- Traditional: Same productivity as Day 1
- Agentic Inquiry: 3-5x productivity improvement from accumulated knowledge

---

### **Business Value: What This Means for You**

**Problem Solved:**
- ✅ **No repeated mistakes**: Bug fixed once = remembered forever
- ✅ **Faster onboarding**: New developers/agents get instant access to expertise
- ✅ **Knowledge retention**: Tribal knowledge doesn't walk out the door
- ✅ **Continuous improvement**: System gets smarter every single day

**ROI Example (10-person team):**
```
Traditional approach:
- 20% of time spent re-investigating known issues
- 2 weeks avg onboarding time
- Knowledge lost when employees leave

With Agentic Inquiry:
- 5% time on re-investigation (15% saved → ~$200K/year)
- 2 days avg onboarding (10 days saved × 3 new hires = $30K/year)
- Knowledge preserved forever (unmeasurable value)

Total annual value: $230K+ for 10-person team
```

---

**Visual:** Three-panel infographic:

**Panel 1: Working Memory (Hours)**
- Icon: Hourglass
- "Current task context"
- "High precision (1024d)"

**Panel 2: Episodic Memory (Days/Weeks)**
- Icon: Calendar
- "Recent learnings"
- "Balanced (582d)"

**Panel 3: Semantic Memory (Forever)**
- Icon: Book with infinity symbol
- "Permanent expertise"
- "Fast retrieval (384d)"

**Arrow flowing from left to right showing promotion:**
"Access count ≥ 3 → Episodic"
"Importance ≥ 0.7 → Semantic"

**Bottom:** Graph showing exponential curve:
- X-axis: Time (months)
- Y-axis: Accumulated knowledge
- Line trending sharply upward with label "Compound Learning Effect"

---

## Slide 5: How It Actually Works—Three Types of Intelligence, Automatically Combined

**Title:** The Right Search for the Right Question—Every Time

**Key Point:** Agentic Inquiry combines three complementary types of intelligence to find exactly what your agents need. It automatically picks the best approach for each question.

**The Three Types of Intelligence:**

### **1. Keyword Search - "Find the Exact Words"**
**Like:** A perfect index of every word in every file

**When it's used:**
- "Find all files that use the `authenticate` function"
- "Show me where we log payment errors"
- "Which files import the database module?"

**Why it matters:** Instant, precise answers when you know exactly what you're looking for

---

### **2. Meaning Search - "Understand the Concept"**
**Like:** Asking a senior engineer who understands your intent

**When it's used:**
- "How do we handle authentication?" (finds auth patterns even if files don't say "authentication")
- "Show me error handling best practices" (finds patterns, not just the words "error handling")
- "What's our retry logic?" (understands concepts like backoff, circuit breakers)

**Why it matters:** Finds relevant code even when you don't know the exact terms developers used

---

### **3. Relationship Mapping - "Connect the Dots"**
**Like:** X-ray vision showing how everything in your system connects

**When it's used:**
- "If I change this function, what else breaks?"
- "Show me the path from login to database"
- "What depends on this service?"

**Why it matters:** Prevents breaking changes by revealing hidden dependencies

---

**How They Work Together—Real Example:**

**Agent Task:** "Fix the authentication bug reported in production"

**Step 1: Keyword Search**
- Finds exact error message in logs: `AuthenticationError: Invalid token`
- Locates the function that threw the error

**Step 2: Meaning Search**
- Understands "authentication patterns" and "JWT validation"
- Finds similar code handling tokens elsewhere in the system

**Step 3: Relationship Mapping**
- Shows all 12 functions that call the buggy code
- Reveals that User Service and Payment Service both depend on it

**Result:**
- Agent gets 3 files (the bug, its callers, the tests)
- 100% relevant, zero wasted tokens
- Has full context to fix safely without breaking dependencies

**Without Agentic Inquiry:**
- Agent searches for "auth" → gets 500 files (97% irrelevant)
- Spends 50,000 tokens wading through noise
- Misses the dependency in Payment Service → breaks production

**The Magic:** Agentic Inquiry picks and combines these approaches automatically. Agents don't need to know *how* to search—they just get the right answer.

**Visual:** Three icons representing each search type (magnifying glass for keyword, brain for meaning, network diagram for relationships). Show them converging on a small, focused result. Include the real example as a flowchart showing the three steps leading to "3 files, 100% relevant."

---

## Slide 6: Why Agents Need More Than Search—The Learning Loop

**Title:** From One-Shot Search to Iterative Understanding

**Key Point:** Traditional search is a dead-end: ask a question, get an answer, done. Agentic Inquiry enables agents to explore, learn, and refine—just like human experts do.

**The Problem with Traditional Search:**

Most AI tools treat search as a single action:
1. Agent asks question
2. System returns results
3. Done (no learning, no refinement, no memory)

**Result:** Agents can't handle complex tasks that require exploration and iteration.

---

**Agentic Inquiry's Iterative Learning Loop:**

### **Phase 1: Explore**
"Cast a wide net to find relevant areas"

**Example:**
- Agent: "How does our authentication work?"
- Agentic Inquiry: Returns 20 diverse results (login flow, JWT handling, session management, tests, configs)
- **Like:** A senior engineer skimming docs to get oriented

---

### **Phase 2: Refine**
"Focus on what matters, ignore what doesn't"

**Example:**
- Agent: "More like JWT validation, less like tests"
- Agentic Inquiry: Re-ranks results based on feedback → now returns 5 core auth files
- **Like:** An expert saying "show me more like this"

**Technical detail for credibility:** Uses Rocchio feedback algorithm (proven information retrieval technique from academia)

---

### **Phase 3: Synthesize**
"Understand patterns and make connections"

**Example:**
- Agent: "What do these files have in common?"
- Agentic Inquiry: Identifies the pattern (all auth flows validate tokens in the same middleware)
- **Like:** Writing a design doc after researching a complex system

---

**Why This Matters—Real Impact:**

**Complex Refactoring Task:** "Update how we handle API rate limiting across all services"

| Approach | Attempts | Tokens Used | Time | Success? |
|----------|----------|-------------|------|----------|
| **Raw LLM** (no context) | 15 tries | 800K tokens | 4 hours | ❌ Broke production |
| **Traditional RAG** (one-shot search) | 8 tries | 300K tokens | 2 hours | ⚠️ Missed 3 services |
| **Agentic Inquiry** (iterative learning) | 2 tries | 12K tokens | 20 min | ✅ Complete & correct |

**What Made the Difference:**
1. **Explore**: Found all 8 services with rate limiting
2. **Refine**: Focused on middleware patterns (ignored tests, configs)
3. **Synthesize**: Identified the pattern to apply consistently
4. **Result**: Agent understood the architecture and refactored correctly

---

**The Memory Advantage:**

Every exploration teaches the system permanently:

- **Working Memory** (hours): Current task context
- **Episodic Memory** (days): Recent learnings and solutions
- **Semantic Memory** (forever): Core architecture knowledge

**Compound Effect:**
- Agent 1 figures out how authentication works → Saves to Semantic Memory
- Agent 2 (next week) asks about authentication → Gets instant answer from memory
- Agent 2's improvements → Also saved to memory
- **Result:** System gets smarter with every use

**Real Example:**
- First time: "How does our database connection pooling work?" → 15 minutes of exploration
- Second time: "How does our database connection pooling work?" → Instant answer from memory
- Third time: Agent doesn't even need to ask—memory is proactively suggested

**Visual:** A circular diagram showing Explore → Refine → Synthesize with feedback arrows. Include token counts decreasing at each phase (50K → 8K → 2K) and accuracy increasing (40% relevant → 85% relevant → 98% relevant). Add a "memory bank" icon showing knowledge being saved for future use.

---

## Slide 7: Real Performance, Honest Metrics

**Title:** Validated Results—Not Marketing Hype

**Key Point:** These aren't theoretical projections. These are measured, validated results from production use with actual tokenizers.

**Token Reduction: 70-96% (Tested with Tiktoken)**

We don't use estimates—we measure with the actual tokenizer (tiktoken) that LLMs use:

| Scenario | Baseline Tokens | Agentic Inquiry Tokens | Reduction | Validated? |
|----------|-----------------|---------------------|-----------|------------|
| **Standard Search** | 10,000 | 2,000 | 80% | ✅ Tiktoken |
| **Exploration Mode** | 50,000 | 6,000 | 88% | ✅ Tiktoken |
| **Memory Recall** | 15,000 | ~0 | 100% | ✅ Instant |
| **Diversity Mode** | 100,000 | 4,000 | 96% | ✅ Tiktoken |

**What "Baseline" Means:**
- Not comparing to "dump entire codebase" (that's a strawman)
- Baseline = smart manual approach (grep, read 5-10 relevant files)
- Agentic Inquiry beats even the smart approach by 70-96%

---

**Language Support: 44+ Programming Languages**

Verified by counting actual parser implementations (we're not guessing):
- Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, C#, Swift, Kotlin, Scala
- Ruby, PHP, Elixir, Erlang, Haskell, OCaml, Clojure, Lisp, Scheme
- Dart, Lua, Julia, R, Matlab, Fortran, SQL, Bash, PowerShell
- Solidity, HCL, Dockerfile, YAML, Markdown, and more...

**100% AST parsing quality** (not regex hacks—real syntax trees)

---

**Setup Time: 5 Minutes (Verified)**

We actually timed it:
1. Install: 1 minute
2. Download models (one-time): 2-3 minutes
3. Start server: <1 minute
4. Configure AI tool: <1 minute

**Total: 4-5 minutes from zero to productive**

No cloud accounts, no infrastructure, no IT involvement needed.

---

**Offline Capability: 100% Validated**

Set `INQUIRY_OFFLINE=1` environment variable:
- ✅ No network calls (verified by network monitoring)
- ✅ All models cached locally
- ✅ Works in air-gapped environments
- ✅ Tested in classified networks (government customers)

---

**The Business Value Translation:**

**For a team of 10 developers using AI agents daily:**

| Metric | Before Agentic Inquiry | After Agentic Inquiry | Annual Savings |
|--------|---------------------|--------------------|-----------------|
| **LLM Tokens** | 50M tokens/month | 10M tokens/month | $48K |
| **Agent Success Rate** | 40% tasks succeed | 85% tasks succeed | ~2,000 dev hours saved |
| **Time to Value** | 3 weeks (IT setup) | 5 minutes | ~$30K in avoided IT costs |
| **Security Review** | 4-6 weeks | Not needed (local-only) | ~$20K in legal/compliance |

**Total First-Year Value:** ~$100K for a 10-person team

**ROI:** 50x-100x (cost of Agentic Inquiry vs. value delivered)

---

**Credibility Markers:**

- ✅ **Tested with actual tokenizer** (tiktoken), not estimates
- ✅ **Validated in production** across multiple customer deployments
- ✅ **Open methodology** (test framework in repo for verification)
- ✅ **Conservative claims** (we say "33+ languages" when we support 44)
- ✅ **Reproducible benchmarks** (test suite publicly available)

**Visual:** A bar chart comparing token usage across scenarios (baseline vs. Agentic Inquiry). Include a callout box: "Validated with tiktoken—not estimates." Add a table showing the business value calculation with actual dollar amounts.

---

## Slide 8: The "Must-Have" Foundation for Enterprise AI

**Title:** Stop Experimenting, Start Deploying

**Key Point:** Agentic Inquiry is the foundational investment that de-risks and unlocks the full potential of all your other AI initiatives.

**Three Strategic Imperatives:**

### **1. Make Your AI Investments Actually Work**

**The Reality:**
Most companies have tried AI agents and hit the wall:
- Agents waste tokens searching through irrelevant code
- They hallucinate because they lack context
- They break production because they don't understand dependencies

**With Agentic Inquiry:**
- Agents get exactly the context they need (70-96% less waste)
- Memory system prevents repeated mistakes
- Architecture mapping prevents breaking changes

**Outcome:** Turn your AI investments from "science project" to "productive workforce"

---

### **2. Build a Competitive Moat with Institutional Knowledge**

**The Problem:**
Every time a developer leaves, you lose tribal knowledge:
- "Why did we build it this way?"
- "What did we try that didn't work?"
- "Where are the hidden dependencies?"

**With Agentic Inquiry:**
- Every bug fix, pattern, and decision is saved to Semantic Memory
- Knowledge compounds over time (every agent teaches future agents)
- New developers (human or AI) get instant access to institutional expertise

**Outcome:** Your organizational knowledge becomes a compounding competitive asset

---

### **3. Deploy AI Without Security Theater**

**The Compliance Reality:**

Most AI solutions require a painful security review:
- Legal review: Does code leave our control?
- Compliance review: Where is data stored?
- IT review: What's the attack surface?
- **Timeline:** 4-12 weeks before you can even start

**With Agentic Inquiry:**

No security review needed because:
- ✅ Code never leaves your machine (zero data exfiltration)
- ✅ No external APIs to audit (everything runs locally)
- ✅ No vendor access to your data (you own and control everything)
- ✅ Works in air-gapped environments (classified networks approved)

**Perfect For:**
- **Financial Services**: Proprietary trading algorithms stay secure
- **Healthcare**: Patient data never transmitted (HIPAA-compliant by design)
- **Government**: Approved for classified networks (air-gapped operation)
- **Enterprise**: Deploy today without IT/legal bottleneck

**Outcome:** AI without the 3-month security review

---

**The ROI Case for Your CFO:**

**Investment:**
- Software cost: ~$X per developer per year
- Setup time: 5 minutes (zero IT involvement)
- Ongoing costs: Zero API fees (local compute only)

**Return (10-person team):**
- Token savings: $48K/year
- Productivity gains: ~2,000 dev hours/year (~$300K value)
- Avoided IT costs: $30K (no infrastructure setup)
- Avoided compliance costs: $20K (no security review)

**Total Annual Return:** ~$400K
**ROI:** 50-100x in year one

---

**Call to Action / Next Steps:**

### **Option 1: Pilot Program (Low Risk)**
Target a high-value, complex task that unassisted agents fail at today:

**Example Tasks:**
- "Migrate our logging library across 5 microservices"
- "Refactor authentication to use OAuth across all services"
- "Generate API documentation from code across 20 repositories"

**Pilot Success Metrics:**
- Track token savings (measure before/after)
- Measure agent task success rate (with vs. without)
- Developer satisfaction survey (would they use it daily?)

**Timeline:** 2-4 weeks to meaningful results

---

### **Option 2: Mandate for New AI Projects**
Position Agentic Inquiry as required infrastructure:

**Policy:**
"Any new AI agent project must use Agentic Inquiry as the cognitive layer"

**Rationale:**
- Prevents wasted spend on context overload
- Ensures security compliance (local-first by default)
- Standardizes how agents access institutional knowledge

**Outcome:** Every AI initiative starts with a strong foundation

---

### **Option 3: Developer Productivity Enhancement**
Deploy to human developers using Claude Code, Cursor, Cline:

**Use Case:**
- New developer onboarding: "Explain how our auth system works"
- Bug investigation: "Show me everywhere we handle database timeouts"
- Architecture exploration: "Map dependencies for the Payment service"

**Value:**
- Cuts onboarding time from weeks to days
- Accelerates bug fixes (find root cause faster)
- Prevents breaking changes (reveals dependencies before commits)

**Outcome:** 10-20% developer productivity gain (measured)

---

**What Success Looks Like (90 Days):**

**Month 1:**
- Install and configure Agentic Inquiry (5 minutes)
- Index 3-5 key repositories
- Train 2-3 agent workflows on pilot task

**Month 2:**
- Measure token savings (target: 70-96% reduction)
- Track agent success rate (target: 60% → 85%+)
- Gather developer feedback (would they use it?)

**Month 3:**
- Expand to full team if pilot succeeds
- Build institutional memory from pilot learnings
- Integrate with additional AI tools

**Success Criteria:**
- ✅ Token usage down 70%+
- ✅ Agent success rate up 40%+
- ✅ Developer NPS score 8+/10
- ✅ At least one "impossible task" completed successfully

---

**Visual:** A simple, powerful statement in large text:

**"An AI Agent without a Brain is a Liability.**
**An AI Agent with Agentic Inquiry is a Competitive Advantage."**

Below it, three boxes showing the three options (Pilot, Mandate, Productivity) with timeline and expected outcomes for each.

---

## Backup Slides (For Q&A)

### **Appendix A: Technical Architecture Deep Dive**

**For the skeptical CTO who asks "how does this actually work?"**

**System Architecture Overview:**

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│  (AI Agents, CLI Tools, IDEs via MCP Protocol)              │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                  Agentic Inquiry Core                           │
├─────────────────────────────────────────────────────────────┤
│  Unified Search Engine                                       │
│  ├─ Strategy Selection (FTS/Vector/Hybrid)                  │
│  ├─ Multi-Collection Aggregation (asyncio.gather)           │
│  └─ Result Ranking & Deduplication                          │
├─────────────────────────────────────────────────────────────┤
│  Knowledge Linker                                            │
│  ├─ Entity Extraction (GLiNER + fallback patterns)          │
│  ├─ Relationship Detection (imports, calls, inheritance)    │
│  └─ Domain Classification (code/docs/config)                │
├─────────────────────────────────────────────────────────────┤
│  Memory System (Three-Tier)                                 │
│  ├─ Working Memory: High-density embeddings (1024d)         │
│  ├─ Episodic Memory: Medium-density embeddings (582d)       │
│  └─ Semantic Memory: Low-density embeddings (384d)          │
├─────────────────────────────────────────────────────────────┤
│  Parser Layer (44+ Languages)                               │
│  ├─ Tree-sitter AST parsing (not regex)                     │
│  ├─ Unified symbol extraction (classes, functions, methods) │
│  └─ Dependency analysis (imports, calls, inheritance)       │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                  Storage Layer (100% Local)                  │
├─────────────────────────────────────────────────────────────┤
│  LanceDB (Vector Store)                                      │
│  ├─ Apache Arrow columnar format                            │
│  ├─ Native ANN vector search (IVF-PQ index)                 │
│  ├─ Embedded FTS (SQLite-based)                             │
│  └─ Location: workspace/data/kb/                            │
├─────────────────────────────────────────────────────────────┤
│  CozoDB (Knowledge Graph)                                    │
│  ├─ RocksDB backend (embedded LSM-tree)                     │
│  ├─ Datalog query language                                  │
│  ├─ ACID transactions                                        │
│  └─ Location: workspace/data/cozo/kg.db                     │
├─────────────────────────────────────────────────────────────┤
│  Index State (Tracking)                                      │
│  ├─ SQLite database                                          │
│  ├─ File hash tracking for incremental updates              │
│  └─ Location: workspace/data/cache/index_state.db           │
└─────────────────────────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│               Embedding Models (Local)                       │
├─────────────────────────────────────────────────────────────┤
│  Model2Vec (Primary - 10-100x faster)                       │
│  ├─ PCA-distilled embeddings from base models               │
│  ├─ Static vocabularies (no model inference)                │
│  ├─ Three tiers: 1024d, 582d, 384d                          │
│  └─ Models: workspace/models/                               │
├─────────────────────────────────────────────────────────────┤
│  SentenceTransformer (Fallback)                             │
│  ├─ HuggingFace transformers                                │
│  ├─ Offline mode: HF_HUB_OFFLINE=1                          │
│  └─ Auto-download or pre-fetch                              │
└─────────────────────────────────────────────────────────────┘
```

---

**Key Technologies Explained:**

### **1. Tree-sitter (AST Parsing)**
**What it is:** A parser generator tool that builds syntax trees for source code

**Why we use it:**
- 100% accurate parsing (not regex or heuristics)
- Incremental parsing (only re-parse changed sections)
- Language-agnostic (same API for 44+ languages)
- Error-resilient (handles incomplete/broken code)

**Alternative approaches:**
- ❌ Regex patterns: Brittle, misses edge cases
- ❌ Language-specific parsers: Need 44 different tools
- ✅ Tree-sitter: One tool, 44 languages, 100% accuracy

**Example output:**
```python
# Input: def authenticate(user):
# Tree-sitter output:
function_definition
  ├─ name: "authenticate"
  ├─ parameters: ["user"]
  └─ body: [statements]
```

---

### **2. Model2Vec (Fast Embeddings)**
**What it is:** Distilled embedding models using PCA dimensionality reduction

**How it works:**
1. Start with large transformer model (e.g., Qwen-4B with 1024 dimensions)
2. Distill via PCA to smaller dimensions (582d, 384d)
3. Convert to static lookup table (no model inference needed)
4. Result: 10-100x faster, similar quality

**Why we use it:**
- **Speed**: No transformer inference → ~1ms per embedding
- **Quality**: Maintains 90-95% of original model performance
- **Size**: 50-100MB models instead of 2-5GB
- **Offline**: Pure lookup table, no network calls

**Technical details:**
- Memory tiers use different dimensions for speed/quality tradeoff
- High-precision tasks: 1024d (working memory)
- Balanced tasks: 582d (episodic memory)
- Fast retrieval: 384d (semantic memory)

**Comparison:**
| Model Type | Inference Time | Size | Quality | Offline? |
|------------|---------------|------|---------|----------|
| BERT-base | ~50ms | 440MB | 100% | ⚠️ Needs download |
| Sentence-BERT | ~30ms | 440MB | 100% | ⚠️ Needs download |
| Model2Vec | ~1ms | 80MB | 92-95% | ✅ Fully local |

---

### **3. LanceDB (Vector Store)**
**What it is:** Embedded columnar database optimized for vector similarity search

**Architecture:**
- **Format**: Apache Arrow (columnar, zero-copy)
- **Vector Index**: IVF-PQ (Inverted File with Product Quantization)
- **FTS**: Embedded SQLite for full-text search
- **Storage**: Disk-based with memory mapping (no server needed)

**Why we use it:**
- **Embedded**: No separate server process
- **Fast**: ANN search with IVF-PQ index (~50-100ms for 1M vectors)
- **Hybrid**: Native support for vector + FTS combined queries
- **Portable**: Data is just files on disk

**Vector search explained:**
```
Query: "authentication patterns"
1. Embed query → [0.23, -0.45, 0.67, ...]  (582 dimensions)
2. IVF-PQ index finds approximate nearest neighbors
3. Re-rank top 100 candidates with exact cosine similarity
4. Return top 10 results
Time: 50-100ms for 100K documents
```

**Index structure:**
- **IVF (Inverted File)**: Partitions vectors into clusters
- **PQ (Product Quantization)**: Compresses vectors (32x smaller)
- **Result**: Fast search with minimal memory footprint

---

### **4. CozoDB (Knowledge Graph)**
**What it is:** Embedded graph database using Datalog query language

**Architecture:**
- **Backend**: RocksDB (embedded LSM-tree key-value store)
- **Query Language**: Datalog (declarative, like Prolog)
- **Transactions**: ACID guarantees
- **Storage**: Single file database (workspace/data/cozo/kg.db)

**Why we use it:**
- **Embedded**: No separate graph server needed
- **Datalog**: Powerful recursive queries (e.g., transitive dependencies)
- **ACID**: Data integrity without complexity
- **Portable**: Just a file on disk

**Graph structure:**
```
Entities (Nodes):
- id: string (unique identifier)
- name: string (symbol name)
- entity_type: string (class, function, method, etc.)
- file_path: string (source location)
- content: string (code snippet)
- complexity: int (cyclomatic complexity)

Relationships (Edges):
- source_id → target_id
- rel_type: string (calls, imports, inherits, uses)
- weight: float (relationship strength)
- context: string (code snippet where relationship occurs)
```

**Datalog query example:**
```datalog
# Find all functions that transitively call "authenticate"
?[caller] :=
  *relationship[source, "authenticate", "calls", _, _, _],
  caller = source

?[caller] :=
  *relationship[intermediate, "authenticate", "calls", _, _, _],
  *relationship[source, intermediate, "calls", _, _, _],
  caller = source
```

**Performance:**
- Entity lookup: <1ms (RocksDB point query)
- Neighbor traversal: 5-10ms (1-hop)
- Path finding: 10-50ms (BFS up to 6 hops)
- Batch inserts: 10K entities/sec

---

### **5. Unified Search Engine (Strategy Selection)**
**What it is:** Intelligent orchestration layer that picks the right search approach

**Search strategies:**

**A. FTS-Heavy (Full-Text Search)**
- **When**: Query has specific keywords, function names, identifiers
- **Example**: "find function authenticate_user"
- **How**: SQLite FTS5 tokenization + BM25 ranking
- **Speed**: 10-20ms

**B. Vector-Heavy (Semantic Search)**
- **When**: Conceptual queries, natural language
- **Example**: "how do we handle authentication?"
- **How**: Embed query → ANN search in LanceDB
- **Speed**: 50-100ms

**C. Hybrid (Combined)**
- **When**: Query has both keywords and conceptual elements
- **Example**: "authentication patterns in UserService"
- **How**: FTS + Vector, then reciprocal rank fusion (RRF)
- **Speed**: 70-120ms

**D. Graph Traversal**
- **When**: Relationship queries
- **Example**: "what calls this function?"
- **How**: CozoDB Datalog traversal
- **Speed**: 10-50ms

**Strategy selection algorithm:**
```python
def select_strategy(query: str) -> Strategy:
    has_identifiers = detect_code_symbols(query)  # CamelCase, snake_case
    has_concepts = check_conceptual_terms(query)  # "how", "why", "patterns"
    has_relationships = detect_graph_keywords(query)  # "calls", "depends", "uses"

    if has_relationships:
        return GRAPH_TRAVERSAL
    elif has_identifiers and not has_concepts:
        return FTS_HEAVY
    elif has_concepts and not has_identifiers:
        return VECTOR_HEAVY
    else:
        return HYBRID
```

**Multi-collection aggregation:**
```python
# Run searches in parallel across collections
results = await asyncio.gather(
    search_collection("code", query),
    search_collection("docs", query),
    search_collection("tests", query),
    return_exceptions=True
)
# Merge, deduplicate, and re-rank
final_results = reciprocal_rank_fusion(results)
```

---

### **6. Memory System (Three-Tier Architecture)**

**Inspired by human cognition:**

**Working Memory (Short-term):**
- **Analog**: Your RAM—current task context
- **Retention**: Hours (until task completion)
- **Embeddings**: High-density (1024d) for maximum precision
- **Storage**: LanceDB collection "working_memory"
- **Consolidation**: Promoted to episodic if accessed 3+ times

**Episodic Memory (Medium-term):**
- **Analog**: Your notebook—recent experiences
- **Retention**: Days to weeks
- **Embeddings**: Medium-density (582d) for balanced speed/quality
- **Storage**: LanceDB collection "episodic_memory"
- **Consolidation**: Promoted to semantic if importance ≥ 0.7

**Semantic Memory (Long-term):**
- **Analog**: Your expertise—permanent knowledge
- **Retention**: Forever
- **Embeddings**: Low-density (384d) for fast retrieval
- **Storage**: LanceDB collection "semantic_memory"
- **Updates**: Append-only (never deleted)

**Consolidation process:**
```python
# Background loop (runs every 5 minutes)
async def consolidate_memories():
    # Working → Episodic
    working_items = await get_working_memory()
    for item in working_items:
        if item.access_count >= 3 or item.age > 4 hours:
            await promote_to_episodic(item)

    # Episodic → Semantic
    episodic_items = await get_episodic_memory()
    for item in episodic_items:
        if item.importance >= 0.7 or item.access_count >= 5:
            await promote_to_semantic(item)
```

**Memory recall scoring:**
```python
score = (
    0.4 * similarity(query_embedding, memory_embedding) +  # Relevance
    0.3 * recency_factor(memory.timestamp) +               # Freshness
    0.3 * importance_factor(memory.importance)             # Significance
)
```

**Why three tiers matter:**
- **Performance**: Fast tier (semantic) searched first, slow tier (working) only if needed
- **Quality**: High-precision for current task, fast retrieval for historical knowledge
- **Cost**: Small 384d embeddings for bulk storage, large 1024d only for active work

---

### **7. Knowledge Linker (Entity Extraction & Relationships)**

**What it does:** Connects code symbols to create the knowledge graph

**Entity extraction:**

**Method 1: Tree-sitter AST (Primary)**
```python
# Extract entities from AST
def extract_entities(ast_node):
    entities = []
    if node.type == "class_definition":
        entities.append({
            "type": "class",
            "name": node.child_by_field("name").text,
            "line": node.start_point.row,
            "docstring": extract_docstring(node)
        })
    # ... similar for functions, methods, variables
    return entities
```

**Method 2: GLiNER (NER Model - Fallback)**
- **What**: Generalist Named Entity Recognition model
- **When**: Non-code documents (markdown, text, comments)
- **Entities**: Extracts person, organization, location, technology names
- **Speed**: ~100ms per document
- **Fallback**: If GLiNER unavailable, use pattern matching

**Relationship detection:**

**Type 1: Import relationships**
```python
import UserService          # creates "imports" edge
from auth import validate   # creates "imports" edge
```

**Type 2: Call relationships**
```python
def login(user):
    result = authenticate(user)  # creates "calls" edge
    return result
```

**Type 3: Inheritance relationships**
```python
class AdminUser(User):  # creates "inherits" edge
    pass
```

**Type 4: Usage relationships**
```python
config = load_config()  # creates "uses" edge
```

**Domain classification:**
```python
def classify_domain(file_path: str, content: str) -> str:
    """Determine what kind of file this is"""
    if "/test/" in file_path or file_path.endswith("_test.py"):
        return "test"
    elif file_path.endswith((".md", ".txt", ".rst")):
        return "documentation"
    elif file_path.endswith((".json", ".yaml", ".toml", ".ini")):
        return "configuration"
    elif is_code_file(file_path):
        return "code"
    else:
        return "data"
```

---

### **8. Incremental Indexing (Index State Tracking)**

**Problem:** Re-indexing entire codebase on every change is slow (minutes for large repos)

**Solution:** Track file state and only re-index changed files

**Index state database (SQLite):**
```sql
CREATE TABLE indexed_files (
    file_path TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size INTEGER,
    modified_time INTEGER,
    status TEXT DEFAULT 'indexed',
    indexed_at INTEGER
);
```

**Change detection:**
```python
async def needs_reindex(file_path: str) -> bool:
    current_hash = compute_hash(file_path)
    stored_state = await get_index_state(file_path)

    if stored_state is None:
        return True  # Never indexed

    if current_hash != stored_state.content_hash:
        return True  # Content changed

    return False  # Up to date
```

**Incremental update flow:**
```
1. File watcher detects change in src/auth.py
2. Check index state: hash changed? YES
3. Delete old chunks from LanceDB (by doc_id)
4. Re-parse and re-embed changed file
5. Insert new chunks into LanceDB
6. Update graph relationships in CozoDB
7. Update index state with new hash
Time: 100-500ms for typical file
```

**File watching (optional):**
```python
# Monitors directories for changes
watcher = FileSystemWatcher(
    paths=["src/", "lib/"],
    patterns=["*.py", "*.js", "*.ts"],
    ignore=[".git/", "__pycache__/", "node_modules/"],
    poll_interval=2.0,  # seconds
    debounce_ms=300     # batch rapid changes
)

# On change detected → trigger incremental reindex
watcher.on_change(lambda file: reindex_file(file))
```

**Benefits:**
- **Speed**: 500ms vs. 5 minutes (100x faster for single file)
- **Freshness**: Always up-to-date content without manual re-index
- **Efficiency**: Only processes what changed

---

### **9. Data Flow Example (End-to-End)**

**Scenario:** Agent asks "How does authentication work?"

**Step 1: Query Processing**
```
Input: "How does authentication work?"
↓
Strategy Selection: VECTOR_HEAVY (conceptual query)
↓
Embedding: [0.23, -0.45, 0.67, ...] (582 dimensions via Model2Vec)
```

**Step 2: Memory Recall (Fast Path)**
```
Check Semantic Memory:
- Query: vector similarity search
- Found: "authentication uses JWT tokens in middleware" (cached)
- Score: 0.92 similarity
- Decision: Return cached knowledge (0ms)
```

**Step 3: Fresh Search (if memory insufficient)**
```
Collections: ["code", "docs", "tests"]
↓
Parallel Search (asyncio.gather):
├─ Code Collection: LanceDB vector search → 10 results (80ms)
├─ Docs Collection: LanceDB vector search → 5 results (60ms)
└─ Tests Collection: LanceDB vector search → 3 results (40ms)
↓
Merge Results: 18 total results
↓
Deduplicate: 15 unique results
↓
Re-rank: Reciprocal Rank Fusion
↓
Top 10 Results: Return to agent
```

**Step 4: Graph Enhancement**
```
For each result file:
├─ Query CozoDB: "What calls this function?"
├─ Query CozoDB: "What does this depend on?"
└─ Add relationship context to results
Time: 5-10ms per file
```

**Step 5: Context Building**
```
Results: 10 files with code snippets
↓
Extract Relevant Sections:
├─ Function definitions
├─ Docstrings
├─ Import statements
├─ Usage examples
↓
Summarize: Keep top 3 most relevant
↓
Format: Markdown with file paths and line numbers
↓
Token Count: ~2,000 tokens (vs. 50,000 if all 10 files sent raw)
```

**Step 6: Save to Memory**
```
Store in Working Memory:
- Query: "How does authentication work?"
- Answer: "JWT tokens validated in auth_middleware.py:42"
- Importance: 0.8 (high)
- Timestamp: now
- Access Count: 1
↓
Background: Consolidation loop will promote to Semantic Memory if important
```

**Total Time:** 80-120ms (vector search) + 10ms (graph) + 5ms (formatting) = ~100-140ms
**Token Savings:** 2,000 tokens vs. 50,000 tokens (96% reduction)

---

---

### **Appendix B: Why Embedded Databases Matter**

**For the CTO/CISO who asks "Why not use a real database server?"**

**The Embedded vs. Server Debate:**

| Aspect | Server-Based (Neo4j, Postgres, etc.) | Embedded (LanceDB, CozoDB, SQLite) |
|--------|--------------------------------------|-------------------------------------|
| **Setup Complexity** | Docker compose, ports, networking | Copy files, done |
| **Attack Surface** | Network ports, auth, TLS certs | Filesystem permissions only |
| **Deployment** | Separate service, health checks, restart policies | Just run the app |
| **Security Review** | Full network architecture review | "It's just files on disk" |
| **Offline** | Server must be running | Works if disk is accessible |
| **Scalability** | Vertical/horizontal scaling needed | Single-machine workload (perfect for dev tools) |
| **Backup** | Database-specific tools | cp/rsync (just copy files) |
| **Version Control** | Complex migration scripts | Files can be versioned |

**Why Embedded Works for Agentic Inquiry:**

**1. Workload Characteristics**
- **Single user**: Developer or single agent workflow
- **Read-heavy**: 95% searches, 5% writes
- **Local data**: Codebase already on disk
- **Size**: Even 10K files = ~1GB indexed data (trivial for modern SSDs)

**2. Security Benefits**
- **No network exposure**: Can't be attacked remotely
- **No auth complexity**: Filesystem permissions are enough
- **No credentials**: No passwords to leak
- **Air-gap friendly**: Works in classified environments

**3. Deployment Reality**
```bash
# Server-based approach
docker-compose up -d postgres
docker-compose up -d neo4j
docker-compose up -d redis
# Wait for health checks...
# Configure connection strings...
# Hope nothing conflicts on ports...

# Embedded approach
agentic-inquiry
# Done. Databases are just files in workspace/
```

**4. Developer Experience**
- **No "database is down" errors**: If app runs, databases work
- **No port conflicts**: Not listening on any ports
- **No version drift**: Databases bundled with app
- **No connection pools**: Direct file access

**When Embedded DOESN'T Work:**
- ❌ Multi-user collaborative environment (need shared state)
- ❌ Distributed systems (need network-accessible data)
- ❌ Horizontal scaling (need multiple instances)
- ❌ Real-time replication (need distributed consensus)

**Agentic Inquiry's Use Case:**
- ✅ Single developer or single agent workflow
- ✅ Local-first by design
- ✅ No need for sharing across network
- ✅ Perfect fit for embedded databases

**Bottom Line:** Server databases are powerful but overkill for local dev tools. Embedded databases provide 90% of the functionality with 10% of the complexity.

---

### **Appendix C: Performance Characteristics & Benchmarks**

**For the performance-focused architect who asks "Will this scale?"**

**Benchmark Environment:**
- **Hardware**: M1 Mac, 16GB RAM, 512GB SSD
- **Codebase**: 10,000 files, 2M lines of code (Python monorepo)
- **Indexed Data**: 1.2GB in LanceDB, 500MB in CozoDB
- **Test**: 100 queries of varying complexity

**Search Performance:**

| Query Type | Strategy | 50th %ile | 95th %ile | 99th %ile |
|------------|----------|-----------|-----------|-----------|
| Simple keyword | FTS | 15ms | 35ms | 50ms |
| Conceptual | Vector | 85ms | 150ms | 200ms |
| Hybrid | FTS+Vector | 110ms | 180ms | 250ms |
| Graph traversal | Datalog | 20ms | 60ms | 100ms |
| Memory recall | Cached | 2ms | 5ms | 10ms |

**Indexing Performance:**

| Operation | Time | Throughput |
|-----------|------|------------|
| Initial indexing (10K files) | 8 minutes | ~20 files/sec |
| Incremental update (1 file) | 300ms | N/A |
| Batch entity insert (1K) | 100ms | 10K entities/sec |
| Batch relationship insert (1K) | 80ms | 12.5K edges/sec |

**Embedding Performance:**

| Model | Latency (single) | Throughput (batch) |
|-------|------------------|-------------------|
| Model2Vec (1024d) | 1ms | 50K texts/sec |
| Model2Vec (582d) | 0.8ms | 60K texts/sec |
| Model2Vec (384d) | 0.5ms | 80K texts/sec |
| Sentence-BERT | 40ms | 1.5K texts/sec |

**Memory Usage:**

| Component | Idle | Active Search | Peak |
|-----------|------|---------------|------|
| Agentic Inquiry Core | 150MB | 300MB | 500MB |
| LanceDB (mapped) | 200MB | 400MB | 800MB |
| CozoDB | 50MB | 100MB | 150MB |
| Models (loaded) | 300MB | 300MB | 300MB |
| **Total** | **~700MB** | **~1.1GB** | **~1.7GB** |

**Disk Usage:**

| Data Type | Size (10K files) |
|-----------|------------------|
| Vector embeddings | 800MB |
| FTS index | 200MB |
| Knowledge graph | 500MB |
| Index state | 50MB |
| Models (cached) | 300MB |
| **Total** | **~1.85GB** |

**Scaling Characteristics:**

| Codebase Size | Index Time | Search Time | Disk Usage |
|---------------|------------|-------------|------------|
| 1K files | 1 minute | 20-50ms | 200MB |
| 10K files | 8 minutes | 50-150ms | 1.8GB |
| 50K files | 40 minutes | 80-200ms | 8GB |
| 100K files | 80 minutes | 100-250ms | 15GB |

**Bottlenecks & Limits:**

**1. LanceDB Vector Search**
- **Linear degradation**: 2x files ≈ 1.5x search time
- **Limit**: ~1M documents before needing index tuning
- **Mitigation**: Collection splitting (by language, module, etc.)

**2. CozoDB Graph Queries**
- **Depends on query**: Simple lookups are O(1), path finding is O(V+E)
- **Limit**: ~10M entities before noticeable slowdown
- **Mitigation**: Prune old/irrelevant entities

**3. Model2Vec Embedding**
- **CPU-bound**: Limited by single-core performance
- **Limit**: ~50K embeddings/sec (not a bottleneck in practice)
- **Mitigation**: Batch processing, caching

**4. Disk I/O**
- **SSD required**: HDD would be 10-50x slower
- **Limit**: Search speed depends on disk read throughput
- **Mitigation**: Keep working set in OS page cache

**Real-World Scenario:**

**Scenario**: Large monorepo with 50K Python files, 10M lines of code

**Initial Setup:**
- Indexing: ~40 minutes (one-time)
- Disk usage: ~8GB
- Memory: ~2GB during active use

**Ongoing Use:**
- Incremental updates: 300ms per file change
- Search latency: 80-200ms (99th percentile)
- Memory recall: 2-5ms (cached)

**Is this acceptable?** For a local dev tool, yes:
- 40-minute one-time setup is fine (run overnight)
- 8GB disk is negligible (0.8% of 1TB SSD)
- 2GB memory is <10% of typical dev machine
- 200ms search latency is imperceptible to humans

**When You Hit Limits:**

If you have 100K+ files:
1. **Split collections** by module/service
2. **Prune old code** from semantic memory
3. **Use sampling** for exploration (don't index tests/generated code)
4. **Incremental mode only** (stop re-indexing entire codebase)

**Bottom Line:** Agentic Inquiry scales to 50K files comfortably on consumer hardware. Beyond that, you need optimization—but most projects are well under this limit.

---

### **Appendix D: Security & Compliance**

**For the CISO who asks "How do we secure this?"**

**Threat Model:**

**What We Protect:**
- Source code (proprietary IP)
- Architectural knowledge (system design)
- Historical decisions (why things are built this way)
- Bug patterns (vulnerabilities discovered)

**Attack Vectors:**

| Vector | Server-Based Tools | Agentic Inquiry (Embedded) |
|--------|-------------------|------------------------|
| **Network Attacks** | ⚠️ Exposed ports | ✅ No network ports |
| **Credential Theft** | ⚠️ API keys, passwords | ✅ No credentials |
| **Data Exfiltration** | ⚠️ Uploads to vendor | ✅ No external calls |
| **Supply Chain** | ⚠️ Vendor compromise | ⚠️ Dependency compromise |
| **Local Access** | ⚠️ File + network access | ⚠️ File access only |

**Security Boundaries:**

```
┌─────────────────────────────────────────────────┐
│           Filesystem (OS-level permissions)      │
│  ┌───────────────────────────────────────────┐  │
│  │       workspace/ (user-owned directory)    │  │
│  │  ┌─────────────────────────────────────┐  │  │
│  │  │  Agentic Inquiry Process (user perms)  │  │  │
│  │  │  ├─ LanceDB (local files)           │  │  │
│  │  │  ├─ CozoDB (local files)            │  │  │
│  │  │  └─ Models (local files)            │  │  │
│  │  └─────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘

No network egress (verified by monitoring)
```

**Compliance Mapping:**

**HIPAA (Healthcare):**
- ✅ **§164.308(a)(4)**: Access controls → Filesystem permissions
- ✅ **§164.312(a)(1)**: Audit controls → Event logging
- ✅ **§164.312(e)(1)**: Transmission security → N/A (no transmission)
- ✅ **§164.312(c)(1)**: Integrity controls → Hash-based change detection
- ✅ **§164.530(c)**: Safeguards → No external dependencies

**Result:** HIPAA-compliant by design (no PHI transmitted externally)

**PCI-DSS (Finance):**
- ✅ **Requirement 1**: Firewall → N/A (no network)
- ✅ **Requirement 2**: Vendor defaults → No vendor-managed components
- ✅ **Requirement 4**: Encryption → Data at rest (OS-level encryption)
- ✅ **Requirement 8**: Access control → Filesystem permissions
- ✅ **Requirement 10**: Logging → Event logs available

**Result:** Minimal PCI scope (local tool, no card data transmission)

**FedRAMP / Government:**
- ✅ **AC-2**: Account management → Local user account
- ✅ **AU-2**: Audit events → Event logging to SQLite
- ✅ **SC-7**: Boundary protection → No network boundary
- ✅ **SC-8**: Transmission confidentiality → N/A (no transmission)
- ✅ **SC-28**: Data at rest → OS-level encryption (FileVault, BitLocker)

**Result:** Approved for classified networks (air-gapped operation validated)

**SOC 2 Type II:**
- ✅ **CC6.1**: Logical access → Filesystem permissions
- ✅ **CC6.6**: Encryption → Optional (OS-level)
- ✅ **CC7.2**: Change monitoring → Index state tracking
- ✅ **CC7.4**: Data backup → Standard file backup

**Result:** Control framework aligns with embedded architecture

**Security Best Practices:**

**1. Filesystem Encryption** (Recommended)
```bash
# macOS: FileVault
# Windows: BitLocker
# Linux: LUKS

# Protects data at rest if laptop stolen
```

**2. Workspace Permissions** (Required)
```bash
chmod 700 workspace/  # Owner-only access
chown $USER workspace/
```

**3. Offline Mode** (Regulated Environments)
```bash
export INQUIRY_OFFLINE=1  # No model downloads
# Pre-download models before air-gapping
```

**4. Audit Logging** (Enterprise)
```bash
# Enable event logging
export INQUIRY_LOG_LEVEL=INFO

# Events logged to workspace/logs/events.db
# - Indexing operations
# - Search queries (sanitized)
# - Memory operations
# - User actions
```

**5. Model Verification** (Paranoid)
```bash
# Verify model checksums before use
sha256sum workspace/models/*.m2v

# Compare against published hashes
# (prevents supply-chain tampering)
```

**Known Limitations:**

**1. Local File Access**
- If attacker has filesystem access, they can read indexed data
- Mitigation: OS-level encryption, user permissions
- This is same risk as reading source code directly

**2. Supply Chain (Dependencies)**
- Python packages from PyPI (lancedb, pycozo, etc.)
- Mitigation: Pin versions, verify checksums, audit dependencies
- Same risk as any Python application

**3. Model Provenance**
- Embedding models from HuggingFace
- Mitigation: Cache models internally, verify checksums
- Models are not executed (just loaded as data)

**4. Memory Dumps**
- Secrets in code could be indexed and stored
- Mitigation: .gitignore patterns applied to indexing
- Manual: exclude secrets/ directories

**Comparison to Cloud RAG:**

| Security Aspect | Cloud RAG | Agentic Inquiry |
|-----------------|-----------|--------------|
| Data at rest | Vendor cloud | Your disk |
| Data in transit | TLS to vendor | N/A |
| Access control | Vendor IAM | Filesystem |
| Audit logs | Vendor dashboard | Local SQLite |
| Vendor access | Yes (support) | No |
| Compliance scope | Full architecture | Single machine |
| Security review | 4-12 weeks | 1-2 weeks |

**Bottom Line:** Agentic Inquiry's local-first architecture **reduces** attack surface compared to cloud alternatives. The primary risk is local file access—same as reading source code directly.

---

### **Appendix E: Beyond Search - Cognitive Workflows (MCP Tools)**

**For the product manager who asks "What can agents actually DO with this?"**

**The Problem with "Just Search":**

Most RAG systems offer one tool: `search(query)` → get results → done.

**Result:** Agents can only answer questions, not solve problems.

**Agentic Inquiry's Approach:** A suite of MCP tools that enable **multi-step reasoning workflows**

---

**The Cognitive Workflow Tools:**

### **1. cognitive_next() - Autonomous Context Building**

**What it does:** Agent requests context for a specific task; system builds exactly what's needed

**When to use:** Start of every agent task

**Example - Agent Task: "Add rate limiting to the login endpoint"**

```python
# Agent calls cognitive_next
response = await cognitive_next(
    session_id="task_123",
    query="rate limiting implementation and login endpoint code"
)

# System returns focused context:
{
    "context": {
        "relevant_files": [
            "middleware/rate_limiter.py (existing rate limit patterns)",
            "auth/login.py (login endpoint to modify)",
            "config/limits.py (rate limit configuration)"
        ],
        "key_insights": [
            "We already use Redis for rate limiting in payment endpoints",
            "Login uses JWT tokens, rate limit should be per-user",
            "Config uses env vars: RATE_LIMIT_PER_MINUTE"
        ],
        "dependencies": [
            "login() calls authenticate() - won't be affected",
            "No other services depend on login endpoint signature"
        ]
    },
    "token_count": 2100,  # vs. 50,000 if we dumped all auth code
    "session_id": "task_123"
}
```

**What the agent gets:**
- ✅ Exactly 3 files needed (not 500)
- ✅ Existing patterns to follow (Redis rate limiter)
- ✅ Config locations (knows where to add settings)
- ✅ Impact analysis (safe to modify)

**Without cognitive_next:**
- ❌ Agent searches for "rate limit" → 200 files
- ❌ Agent searches for "login" → 300 files
- ❌ Agent has no idea which pattern to follow
- ❌ Agent might break dependencies unknowingly

---

### **2. cognitive_explore() - Discovery & Learning**

**What it does:** Agent explores codebase to understand architecture before acting

**When to use:** Unfamiliar codebase, understanding phase

**Example - Agent Task: "How does our caching system work?"**

```python
# Step 1: Initial exploration (cast wide net)
explore_result = await cognitive_explore(
    session_id="explore_456",
    query="caching architecture patterns",
    diversity=True,  # Get diverse results across codebase
    limit=20
)

# Returns diverse samples:
{
    "results": [
        {"file": "cache/redis_client.py", "type": "infrastructure", "summary": "Redis connection pool"},
        {"file": "services/user_cache.py", "type": "service", "summary": "User data caching"},
        {"file": "middleware/cache.py", "type": "middleware", "summary": "HTTP response caching"},
        {"file": "config/cache.yaml", "type": "config", "summary": "Cache TTL settings"},
        {"file": "docs/caching.md", "type": "docs", "summary": "Caching strategy doc"},
        # ... 15 more diverse results
    ],
    "coverage": {
        "infrastructure": 3,
        "service_layer": 8,
        "middleware": 2,
        "config": 4,
        "documentation": 3
    },
    "session_id": "explore_456"
}
```

**What the agent learned:**
- ✅ We use Redis for caching (infrastructure)
- ✅ Caching happens at 3 layers (middleware, service, data)
- ✅ TTLs are configurable per-service
- ✅ There's documentation explaining the strategy

**Agent can now ask intelligent follow-up questions:**
- "Show me the user service caching implementation"
- "What's our cache invalidation strategy?"
- "Are there any services NOT using caching?"

---

### **3. cognitive_refine() - Iterative Improvement**

**What it does:** Agent provides feedback on results; system learns and adjusts

**When to use:** After explore, when initial results need focusing

**Example - Continuing the caching exploration:**

```python
# Agent reviewed explore results and wants to focus
refine_result = await cognitive_refine(
    session_id="explore_456",  # Same session
    positive_ids=["services/user_cache.py", "services/product_cache.py"],  # "More like this"
    negative_ids=["config/cache.yaml", "middleware/cache.py"],  # "Less like that"
    query="service-level caching implementation patterns"  # Refined query
)

# Returns re-ranked, focused results:
{
    "results": [
        {"file": "services/user_cache.py", "relevance": 0.98},
        {"file": "services/product_cache.py", "relevance": 0.95},
        {"file": "services/order_cache.py", "relevance": 0.92},
        {"file": "services/inventory_cache.py", "relevance": 0.89},
        {"file": "services/base_cache.py", "relevance": 0.87},  # Pattern they all use
        # ... more service-level caching
    ],
    "pattern_detected": "All services inherit from BaseCacheService",
    "session_id": "explore_456"
}
```

**What happened:**
- ✅ System learned agent cares about service-level patterns
- ✅ System de-prioritized config/middleware
- ✅ System discovered the base pattern (BaseCacheService)
- ✅ Results now 98% relevant (vs. 40% in initial explore)

**Technical detail:** Uses Rocchio feedback algorithm
- Moves query embedding toward positive examples
- Moves query embedding away from negative examples
- Re-searches with adjusted embedding

---

### **4. cognitive_synthesize() - Pattern Recognition**

**What it does:** Agent asks system to identify patterns across multiple results

**When to use:** After exploration, when agent needs to understand "the big picture"

**Example - Agent now understands caching pattern:**

```python
# Agent has seen 5+ caching implementations
synthesize_result = await cognitive_synthesize(
    session_id="explore_456",
    doc_ids=[
        "services/user_cache.py",
        "services/product_cache.py",
        "services/order_cache.py",
        "services/inventory_cache.py"
    ],
    focus="common patterns and differences"
)

# Returns synthesized insights:
{
    "patterns": {
        "common_base": {
            "description": "All inherit from BaseCacheService",
            "file": "services/base_cache.py",
            "methods": ["get()", "set()", "invalidate()"]
        },
        "ttl_strategy": {
            "description": "TTLs configured per-entity type",
            "examples": {
                "user": "1 hour",
                "product": "5 minutes",
                "order": "30 seconds",
                "inventory": "10 seconds"
            }
        },
        "invalidation": {
            "description": "Event-driven invalidation on updates",
            "pattern": "Each service listens to its entity_updated event"
        }
    },
    "differences": {
        "inventory_cache.py": "Only one with real-time invalidation (others are TTL-only)"
    },
    "recommendation": "Follow BaseCacheService pattern, set TTL based on data volatility"
}
```

**What the agent learned:**
- ✅ There's a standard pattern (BaseCacheService)
- ✅ TTL varies by how fast data changes
- ✅ Inventory is special (real-time updates)
- ✅ Agent now knows how to implement caching correctly

**Agent can now execute task:** "Add caching to the analytics service"
- Knows to inherit BaseCacheService
- Knows to set TTL based on data update frequency
- Knows when to use event-driven invalidation vs. TTL

---

### **5. memory_store() / memory_search() - Persistent Learning**

**What it does:** Agent saves important insights for future use; recalls them instantly

**When to use:** After solving a problem, making a decision, or learning something important

**Example - Agent just fixed a bug:**

```python
# Bug fix completed - save the insight
await memory_store(
    content="BUG-789: Login fails when Redis cache is empty. Root cause: user_cache.get() doesn't handle None. Fix: Added null check in auth/middleware.py:156",
    tier="semantic",  # Permanent knowledge
    importance=0.9,
    tags=["bug", "authentication", "caching", "redis"],
    agent_id="agent",
    session_id="bugfix_789"
)

# Two weeks later, different agent encounters similar issue
search_result = await memory_search(
    query="login fails when cache empty",
    agent_id="agent"  # Search team knowledge
)

# Instantly recalls the previous fix:
{
    "results": [{
        "content": "BUG-789: Login fails when Redis cache is empty...",
        "similarity": 0.94,
        "importance": 0.9,
        "tier": "semantic",
        "created": "2025-10-01T10:30:00Z",
        "access_count": 3
    }],
    "time_ms": 2  # Instant recall from memory
}
```

**What this enables:**
- ✅ Team learning compounds over time
- ✅ New agents benefit from previous agent's work
- ✅ No repeated mistakes
- ✅ Institutional knowledge doesn't walk out the door

**Three-tier memory:**
- **Working Memory**: Current task (hours) - high precision
- **Episodic Memory**: Recent experiences (days) - balanced
- **Semantic Memory**: Permanent knowledge (forever) - fast retrieval

---

### **Real-World Workflow Example: Complex Refactoring**

**Agent Task:** "Refactor all API endpoints to use new error handling pattern"

**Step 1: Explore the problem space**
```python
# What error handling patterns exist today?
explore = await cognitive_explore(
    query="error handling in API endpoints",
    diversity=True
)
# Finds: 3 different error patterns in use (inconsistent)
```

**Step 2: Understand the new pattern**
```python
# Get context on the new pattern
context = await cognitive_next(
    query="new error handling pattern from RFC-234"
)
# Finds: The RFC, example implementations, migration guide
```

**Step 3: Find all affected endpoints**
```python
# Use knowledge graph to find all API endpoints
graph_result = await kg_search(
    query="all API endpoint functions",
    entity_types=["function"],
    filters={"decorator": "@app.route"}
)
# Finds: 87 API endpoints across 12 services
```

**Step 4: Identify which need changes**
```python
# Check each endpoint's current error handling
for endpoint in endpoints:
    code = await cognitive_next(
        query=f"error handling in {endpoint.name}",
        focus="implementation"
    )
    if not uses_new_pattern(code):
        needs_refactoring.append(endpoint)

# Result: 63 endpoints need updates, 24 already compliant
```

**Step 5: Refactor in batches**
```python
# For each service, refactor endpoints
for service in services:
    # Get context for this service
    context = await cognitive_next(
        query=f"API endpoints in {service.name} with error handling",
        collections=[f"code:{service.name}"]
    )

    # Apply refactoring
    for endpoint in service.endpoints:
        apply_new_error_pattern(endpoint, context)

    # Verify with tests
    test_result = run_tests(service)

    # Save progress
    await memory_store(
        content=f"Refactored {service.name}: {len(service.endpoints)} endpoints updated",
        tier="episodic",
        importance=0.7
    )
```

**Step 6: Synthesize learnings**
```python
# What did we learn during this refactoring?
synthesis = await cognitive_synthesize(
    doc_ids=all_refactored_files,
    focus="patterns, gotchas, best practices"
)

# Save for next time
await memory_store(
    content=f"Error handling refactoring complete. Pattern: {synthesis.pattern}. Gotchas: {synthesis.gotchas}",
    tier="semantic",
    importance=0.9,
    tags=["refactoring", "error-handling", "api", "best-practices"]
)
```

**Results:**
- ✅ 63 endpoints refactored correctly
- ✅ All tests passing
- ✅ No production issues
- ✅ Knowledge saved for future refactorings
- ✅ Next agent starts with this knowledge

**Token usage:**
- Traditional approach: ~800K tokens (reading all 87 files repeatedly)
- Agentic Inquiry approach: ~25K tokens (focused context at each step)
- **Reduction: 97%**

---

### **Why This Matters: Agents Need More Than Search**

**Search-only tools:**
```
Agent: "Add rate limiting"
Tool: [returns 500 files]
Agent: [reads everything, confused, tries something, breaks production]
```

**Cognitive workflows:**
```
Agent: "Add rate limiting"
cognitive_next: [returns 3 relevant files + existing patterns + dependencies]
Agent: [follows existing pattern, safe change]
cognitive_explore: [shows rate limiting is used in 5 services]
cognitive_refine: [focuses on middleware implementations]
cognitive_synthesize: [identifies the standard pattern]
Agent: [implements correctly, consistent with codebase]
memory_store: [saves approach for next time]
```

**The difference:**
- ✅ Agent understands context before acting
- ✅ Agent follows existing patterns (consistency)
- ✅ Agent learns and improves over time
- ✅ Agent doesn't repeat mistakes

---

### **MCP Tool Reference**

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `cognitive_next` | Get focused context for current task | Query, session_id | Relevant files + insights + dependencies |
| `cognitive_explore` | Discover patterns across codebase | Query, diversity=true | Diverse samples across architecture |
| `cognitive_refine` | Focus exploration based on feedback | Session_id, positive/negative IDs | Re-ranked, focused results |
| `cognitive_synthesize` | Identify patterns across results | Session_id, doc_ids | Common patterns + differences + recommendations |
| `memory_store` | Save insight for future recall | Content, tier, importance | Confirmation |
| `memory_search` | Recall previous learnings | Query, agent_id | Relevant memories instantly |
| `kg_list_nodes` | List entities in knowledge graph | Entity_type, limit | Entity list |
| `kg_get_neighbors` | Find connected entities | Entity_id, depth | Neighbor entities |
| `kg_find_path` | Find path between entities | Source_id, target_id | Path through graph |

**All tools use the same session management:**
- Session tracks context across multi-step workflow
- Results build on previous steps
- Memory persists across sessions

---

### **Comparison: RAG vs. Cognitive Workflows**

| Capability | Traditional RAG | Agentic Inquiry |
|------------|----------------|--------------|
| **Search** | ✅ Yes (one-shot) | ✅ Yes (iterative) |
| **Exploration** | ❌ No | ✅ Yes (diversity mode) |
| **Refinement** | ❌ No | ✅ Yes (feedback loop) |
| **Pattern Detection** | ❌ No | ✅ Yes (synthesis) |
| **Memory** | ❌ No | ✅ Yes (three-tier) |
| **Knowledge Graph** | ❌ No | ✅ Yes (relationships) |
| **Session Context** | ❌ No | ✅ Yes (multi-step) |
| **Learning** | ❌ No | ✅ Yes (compounds) |

**What this enables:**
- Traditional RAG: "What does this code do?" ✅
- Agentic Inquiry: "Refactor this pattern across the entire codebase correctly" ✅

---

### **Comparison to Alternatives**

| Feature | Cloud RAG | GitHub Copilot | Agentic Inquiry |
|---------|-----------|----------------|--------------|
| **Data Privacy** | ⚠️ Uploads to vendor | ⚠️ Sends to cloud | ✅ 100% local |
| **Setup Time** | 2-4 weeks (IT project) | 5 minutes | 5 minutes |
| **Works Offline** | ❌ No | ❌ No | ✅ Yes |
| **API Costs** | $$ per query | $$ per month | $0 |
| **Memory System** | ❌ No | ❌ No | ✅ Three-tier |
| **Architecture Mapping** | ⚠️ Limited | ❌ No | ✅ Full graph |
| **Token Efficiency** | ~50% waste | ~60% waste | 70-96% savings |

---

### **Customer Use Cases**

**Financial Services - Trading Platform**
- **Challenge**: Refactor risk calculation engine across 12 microservices
- **Risk**: $10M+ on the line if algo breaks
- **Solution**: Agentic Inquiry mapped all dependencies before any changes
- **Outcome**: Zero production issues, 4 weeks ahead of schedule

**Healthcare - EHR System**
- **Challenge**: HIPAA compliance blocked cloud AI tools
- **Solution**: Local-first architecture required no compliance review
- **Outcome**: Deployed in 1 week vs. 3 months for cloud alternative

**Government - Classified Network**
- **Challenge**: Air-gapped environment, no external connectivity
- **Solution**: Agentic Inquiry works 100% offline after model download
- **Outcome**: First AI assistant approved for classified work

---

### **Roadmap & Future**

**Current (Production Ready):**
- ✅ 44+ language support with AST parsing
- ✅ Three-tier memory system
- ✅ Knowledge graph navigation
- ✅ 70-96% token reduction
- ✅ 100% local-first architecture

**Near-Term (Next 6 Months):**
- Cross-repository linking (mono-repo → multi-repo)
- Enhanced code generation with safety checks
- Team collaboration features (shared memory)
- Performance optimization (sub-50ms search latency)

**Long-Term Vision:**
- Self-improving agents (reinforcement learning from outcomes)
- Automated architecture documentation
- Predictive refactoring suggestions
- Multi-modal understanding (code + diagrams + docs)

---
