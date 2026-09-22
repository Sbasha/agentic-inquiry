"""Context Manager - Signal analysis and context assembly.

The brain of the daemon: analyzes user prompts for signals,
decides injection tier, assembles context from multiple gatherers
in parallel, and formats for injection.
"""

import asyncio
import logging
import re
import time

logger = logging.getLogger("agv.daemon.context")

# Signal extraction patterns
CAMEL_CASE = re.compile(r"[A-Z][a-z]+(?:[A-Z][a-z]+)+")
CONSTANT_CASE = re.compile(r"[A-Z][A-Z_]{2,}")
SNAKE_CASE = re.compile(r"[a-z]+_[a-z_]+")
QUOTED_STRING = re.compile(r'["\']([^"\']{2,})["\']')
FILE_PATH = re.compile(r"[\w/.-]+\.\w{1,8}")

# Intent classification patterns
CODE_INTENT = re.compile(
    r"(implement|function|class|method|code|refactor|fix|bug|error|trace|debug"
    r"|import|module|package|variable|parameter|return|exception|type|interface"
    r"|constructor|inherit|override|abstract)",
    re.IGNORECASE,
)
ARCH_INTENT = re.compile(
    r"(architect|design|pattern|service|component|layer|module|depend"
    r"|structure|flow|pipeline|system|integration|boundary|interface|api"
    r"|microservice|monolith|coupling|cohesion)",
    re.IGNORECASE,
)
DEBUG_INTENT = re.compile(
    r"(debug|error|fail|crash|exception|stack|trace|log|issue|problem"
    r"|broken|wrong|unexpected|timeout|memory leak|performance)",
    re.IGNORECASE,
)
URGENCY = re.compile(
    r"(urgent|critical|blocking|asap|immediately|production|outage|down)",
    re.IGNORECASE,
)

# Context recall triggers (from wicked-mem patterns)
RECALL_TRIGGERS = re.compile(
    r"(why did we|remind me|last time|previously|earlier|before|"
    r"what was|how did|remember when|we decided|the decision|"
    r"the pattern|the approach|what about|recap|context|background)",
    re.IGNORECASE,
)

# Injection tiers
TIER_FULL_PACKET = "FULL_PACKET"
TIER_RELATED_LINKS = "RELATED_LINKS"
TIER_MEMORY_ONLY = "MEMORY_ONLY"
TIER_NONE = "NONE"


class ContextManager:
    """Signal analysis and context assembly pipeline."""

    def __init__(
        self,
        workspace: str,
        project_id: str,
        config: dict,
        memory_manager,
        cache_manager,
    ) -> None:
        self.workspace = workspace
        self.project_id = project_id
        self.config = config
        self._memory_manager = memory_manager
        self._cache_manager = cache_manager

        signals = config.get("signals", {})
        self._entity_weight = signals.get("entity_weight", 30)
        self._filepath_weight = signals.get("filepath_weight", 25)
        self._intent_weight = signals.get("intent_weight", 20)
        self._topic_pivot_weight = signals.get("topic_pivot_weight", 15)
        self._urgency_weight = signals.get("urgency_weight", 10)
        self._full_threshold = signals.get("full_packet_threshold", 70)
        self._related_threshold = signals.get("related_links_threshold", 40)
        self._memory_threshold = signals.get("memory_only_threshold", 20)

        ctx = config.get("context", {})
        self._token_budget = ctx.get("token_budget", 2048)
        self._confidence_gate = ctx.get("confidence_gate", 0.7)
        self._dedup_ttl = ctx.get("dedup_ttl_turns", 10)

        # State
        self._last_keywords: set[str] = set()
        self._agv_search = None
        self._agv_context = None
        self._initialized = False
        self._current_turn = 0

    async def initialize(self) -> None:
        """Initialize agv search and context services."""
        if self._initialized:
            return

        try:
            from agent_vault.config import Config
            from agent_vault.search.service import SearchService

            config = Config.load()
            self._agv_search = await SearchService.from_config(
                config=config, project_id=self.project_id
            )
            self._initialized = True
            logger.info("Context manager initialized with agv search")
        except Exception:
            logger.warning(
                "agv search not available - context assembly will use memories only"
            )
            self._initialized = True  # Still initialized, just limited

    async def shutdown(self) -> None:
        """Cleanup resources."""
        pass

    def analyze_signals(self, prompt: str) -> dict:
        """Analyze a prompt for context-relevant signals.

        Returns signal analysis with score, tier, entities, etc.
        """
        # Strip system tags
        clean = re.sub(r"<[^>]+>.*?</[^>]+>", "", prompt, flags=re.DOTALL)
        clean = re.sub(r"<[^>]+/>", "", clean)

        # Extract entities
        entities = set()
        entities.update(CAMEL_CASE.findall(clean))
        entities.update(CONSTANT_CASE.findall(clean))
        entities.update(
            s for s in SNAKE_CASE.findall(clean) if len(s) > 4
        )
        entities.update(QUOTED_STRING.findall(clean))

        # Extract file paths
        file_paths = set(FILE_PATH.findall(clean))

        # Classify intent (check DEBUG first - more specific patterns)
        intent = "GENERAL"
        if DEBUG_INTENT.search(clean):
            intent = "DEBUG"
        elif CODE_INTENT.search(clean):
            intent = "CODE"
        elif ARCH_INTENT.search(clean):
            intent = "ARCHITECTURAL"

        # Detect topic pivot
        current_keywords = self._extract_keywords(clean)
        topic_pivot = False
        if self._last_keywords and current_keywords:
            overlap = len(self._last_keywords & current_keywords)
            total = len(self._last_keywords | current_keywords)
            jaccard = overlap / total if total > 0 else 0
            topic_pivot = jaccard < 0.3
        self._last_keywords = current_keywords

        # Check urgency
        has_urgency = bool(URGENCY.search(clean))

        # Check for recall triggers
        has_recall = bool(RECALL_TRIGGERS.search(clean))

        # Calculate score
        score = 0
        if entities:
            score += self._entity_weight
        if file_paths:
            score += self._filepath_weight
        if intent in ("CODE", "ARCHITECTURAL"):
            score += self._intent_weight
        if topic_pivot:
            score += self._topic_pivot_weight
        if has_urgency:
            score += self._urgency_weight
        if has_recall:
            score += 15  # Bonus for explicit recall

        # Determine tier
        if score >= self._full_threshold:
            tier = TIER_FULL_PACKET
        elif score >= self._related_threshold:
            tier = TIER_RELATED_LINKS
        elif score >= self._memory_threshold:
            tier = TIER_MEMORY_ONLY
        else:
            tier = TIER_NONE

        return {
            "score": score,
            "tier": tier,
            "entities": list(entities),
            "file_paths": list(file_paths),
            "intent": intent,
            "topic_pivot": topic_pivot,
            "has_urgency": has_urgency,
            "has_recall": has_recall,
            "keywords": list(current_keywords),
        }

    async def assemble(self, prompt: str, session_id: str) -> dict:
        """Full context assembly pipeline.

        1. Check cache
        2. Analyze signals
        3. Gather context (parallel)
        4. Format and deduplicate
        5. Cache result
        """
        start = time.monotonic()

        # Check cache
        cache_key = self._cache_manager.hash_key(prompt[:200], session_id)
        cached = self._cache_manager.get_context(cache_key)
        if cached is not None:
            logger.debug("Context cache hit")
            return cached

        # Analyze signals
        signals = self.analyze_signals(prompt)

        if signals["tier"] == TIER_NONE:
            result = {"context": "", "tier": TIER_NONE, "score": signals["score"]}
            self._cache_manager.put_context(cache_key, result)
            return result

        # Gather context based on tier
        context_parts = []

        if signals["tier"] == TIER_FULL_PACKET:
            # Parallel gather: memories + search + graph
            tasks = [
                self._gather_memories(prompt, signals),
                self._gather_search(prompt, signals),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    context_parts.extend(r)
        elif signals["tier"] == TIER_RELATED_LINKS:
            # Memories + search links (no full content)
            tasks = [
                self._gather_memories(prompt, signals),
                self._gather_search_links(prompt, signals),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    context_parts.extend(r)
        elif signals["tier"] == TIER_MEMORY_ONLY:
            memories = await self._gather_memories(prompt, signals)
            context_parts.extend(memories)

        # Deduplicate
        turn = getattr(self, "_current_turn", 0)
        deduped = []
        for part in context_parts:
            content = part.get("content", "")
            if not self._cache_manager.is_duplicate_content(
                session_id, content, turn
            ):
                deduped.append(part)

        # Format within token budget
        formatted = self._format_context(deduped, signals)

        elapsed = (time.monotonic() - start) * 1000
        logger.debug(
            "Context assembled: tier=%s score=%d parts=%d %.1fms",
            signals["tier"],
            signals["score"],
            len(deduped),
            elapsed,
        )

        result = {
            "context": formatted,
            "tier": signals["tier"],
            "score": signals["score"],
        }
        self._cache_manager.put_context(cache_key, result)

        return result

    async def _gather_memories(
        self, prompt: str, signals: dict
    ) -> list[dict]:
        """Gather relevant memories."""
        try:
            memories = await self._memory_manager.recall(
                query=prompt, limit=5, include_global=False
            )
            result = []
            for m in memories:
                confidence = m.get("confidence", 1.0)
                stale_tag = " [STALE]" if confidence < self._confidence_gate else ""
                result.append(
                    {
                        "source": "memory",
                        "content": m.get("content", ""),
                        "tag": f"[agv Memory: {m.get('created', 'unknown')}{stale_tag}]",
                        "priority": 1,  # Highest priority
                    }
                )
            return result
        except Exception:
            logger.debug("Memory gather failed", exc_info=True)
            return []

    async def _gather_search(
        self, prompt: str, signals: dict
    ) -> list[dict]:
        """Gather code/docs search results."""
        if not self._agv_search:
            return []

        try:
            # Build search query from entities + keywords
            query = prompt[:200]

            # Determine content preference from intent
            preference = None
            if signals["intent"] == "CODE":
                preference = "code"
            elif signals["intent"] in ("ARCHITECTURAL", "GENERAL"):
                preference = None  # Both

            results = await self._agv_search.hybrid_search(
                query_vector=query,  # Will auto-embed or use server-side
                query_fts=query,
                limit=5,
                content_preference=preference,
            )

            output = []
            for r in results:
                data = r.data if hasattr(r, "data") else {}
                file_path = data.get("file_path", "unknown")
                content = data.get("content", "")
                chunk_type = data.get("chunk_type", "code")

                source = "search"
                if chunk_type == "documentation":
                    tag = f"[agv Docs: {file_path}]"
                    priority = 4
                else:
                    line = data.get("start_line", "")
                    tag = f"[agv Search: {file_path}:{line}]"
                    priority = 2

                output.append(
                    {
                        "source": source,
                        "content": content[:500],  # Truncate for budget
                        "tag": tag,
                        "priority": priority,
                        "file_path": file_path,
                    }
                )
            return output
        except Exception:
            logger.debug("Search gather failed", exc_info=True)
            return []

    async def _gather_search_links(
        self, prompt: str, signals: dict
    ) -> list[dict]:
        """Gather search result links (no full content)."""
        if not self._agv_search:
            return []

        try:
            results = await self._agv_search.hybrid_search(
                query_vector=prompt[:200],
                query_fts=prompt[:200],
                limit=8,
            )

            output = []
            for r in results:
                data = r.data if hasattr(r, "data") else {}
                file_path = data.get("file_path", "unknown")
                summary = data.get("content", "")[:100]

                output.append(
                    {
                        "source": "link",
                        "content": f"{file_path}: {summary}",
                        "tag": "[agv Related]",
                        "priority": 3,
                    }
                )
            return output
        except Exception:
            logger.debug("Search links gather failed", exc_info=True)
            return []

    def _format_context(self, parts: list[dict], signals: dict) -> str:
        """Format context parts into injection string within token budget."""
        if not parts:
            return ""

        # Sort by priority (lower = higher priority: Memory > Code > Graph > Docs)
        parts.sort(key=lambda p: p.get("priority", 5))

        # Build output within budget (rough: 4 chars per token)
        char_budget = self._token_budget * 4
        lines = []
        used = 0

        for part in parts:
            tag = part.get("tag", "")
            content = part.get("content", "")
            line = f"{tag}\n{content}"

            if used + len(line) > char_budget:
                # Truncate this part to fit
                remaining = char_budget - used - len(tag) - 10
                if remaining > 50:
                    line = f"{tag}\n{content[:remaining]}..."
                else:
                    break

            lines.append(line)
            used += len(line)

        if not lines:
            return ""

        header = f"[agv Context: {signals['tier']}, score={signals['score']}]"
        return header + "\n\n" + "\n\n".join(lines)

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extract meaningful keywords from text."""
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "above",
            "below", "between", "and", "but", "or", "not", "no", "so",
            "if", "then", "than", "too", "very", "just", "about", "up",
            "out", "all", "also", "how", "what", "when", "where", "why",
            "which", "who", "this", "that", "these", "those", "it", "its",
            "i", "me", "my", "we", "our", "you", "your", "he", "she",
            "they", "them", "their", "some", "any", "each", "every",
        }
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
        return set(list(w for w in words if w not in stop_words)[:20])
