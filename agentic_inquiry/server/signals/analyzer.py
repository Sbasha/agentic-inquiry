"""Signal Analyzer - Prompt signal extraction and tier scoring.

Analyzes user prompts for context-relevant signals (entities,
file paths, intent, topic pivots) and determines injection tier.
"""

import logging
import re

logger = logging.getLogger("ai.server.signals")

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

# Command classification patterns
TEST_PATTERNS = re.compile(
    r"(pytest|unittest|jest|mocha|cargo test|go test|mvn test|gradle test)",
    re.IGNORECASE,
)
BUILD_PATTERNS = re.compile(
    r"(make|build|compile|cargo build|go build|mvn package|gradle build|npm run build|tsc)",
    re.IGNORECASE,
)
GIT_PATTERNS = re.compile(
    r"(git commit|git push|git merge|git rebase|git cherry-pick)",
    re.IGNORECASE,
)
DEPLOY_PATTERNS = re.compile(
    r"(deploy|kubectl|docker push|helm|terraform apply)",
    re.IGNORECASE,
)

# File importance patterns
CONFIG_PATTERNS = re.compile(
    r"(config|settings|\.env|\.yaml|\.yml|\.toml|\.json|Makefile|Dockerfile|docker-compose)",
    re.IGNORECASE,
)
ENTRY_PATTERNS = re.compile(
    r"(main\.|index\.|app\.|server\.|__main__|manage\.py|wsgi|asgi)",
    re.IGNORECASE,
)
TEST_FILE_PATTERNS = re.compile(
    r"(test_|_test\.|\.test\.|spec\.|\.spec\.)", re.IGNORECASE
)

STOP_WORDS = {
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


class SignalAnalyzer:
    """Prompt signal extraction and injection tier scoring."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        signals = config.get("signals", {})
        self._entity_weight = signals.get("entity_weight", 30)
        self._filepath_weight = signals.get("filepath_weight", 25)
        self._intent_weight = signals.get("intent_weight", 20)
        self._topic_pivot_weight = signals.get("topic_pivot_weight", 15)
        self._urgency_weight = signals.get("urgency_weight", 10)
        self._full_threshold = signals.get("full_packet_threshold", 70)
        self._related_threshold = signals.get("related_links_threshold", 40)
        self._memory_threshold = signals.get("memory_only_threshold", 20)

        self._last_keywords: set[str] = set()

    def analyze_signals(self, prompt: str) -> dict:
        """Analyze a prompt for context-relevant signals."""
        clean = re.sub(r"<[^>]+>.*?</[^>]+>", "", prompt, flags=re.DOTALL)
        clean = re.sub(r"<[^>]+/>", "", clean)

        entities = set()
        entities.update(CAMEL_CASE.findall(clean))
        entities.update(CONSTANT_CASE.findall(clean))
        entities.update(s for s in SNAKE_CASE.findall(clean) if len(s) > 4)
        entities.update(QUOTED_STRING.findall(clean))

        file_paths = set(FILE_PATH.findall(clean))

        intent = "GENERAL"
        if DEBUG_INTENT.search(clean):
            intent = "DEBUG"
        elif CODE_INTENT.search(clean):
            intent = "CODE"
        elif ARCH_INTENT.search(clean):
            intent = "ARCHITECTURAL"

        current_keywords = self._extract_keywords(clean)
        topic_pivot = False
        if self._last_keywords and current_keywords:
            overlap = len(self._last_keywords & current_keywords)
            total = len(self._last_keywords | current_keywords)
            jaccard = overlap / total if total > 0 else 0
            topic_pivot = jaccard < 0.3
        self._last_keywords = current_keywords

        has_urgency = bool(URGENCY.search(clean))
        has_recall = bool(RECALL_TRIGGERS.search(clean))

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
            score += 15

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

    @staticmethod
    def classify_bash_command(
        command: str, exit_code: int, output: str
    ) -> dict:
        """Classify a bash command for memory capture."""
        category = "general"
        should_capture = False
        prompt = None

        if TEST_PATTERNS.search(command):
            category = "test"
            if exit_code != 0:
                should_capture = True
                prompt = (
                    "[ai Memory] Tests failed. Store the failure context: "
                    "which tests, root cause, and fix approach."
                )
            else:
                should_capture = True
                prompt = (
                    "[ai Memory] Tests passed. If this validates a significant "
                    "change, store what was tested and why."
                )
        elif BUILD_PATTERNS.search(command):
            category = "build"
            if exit_code != 0:
                should_capture = True
                prompt = "[ai Memory] Build failed. Store the error and resolution."
        elif GIT_PATTERNS.search(command):
            category = "git"
            should_capture = True
            prompt = (
                "[ai Memory] Git operation completed. If this represents a "
                "significant milestone, store the context."
            )
        elif DEPLOY_PATTERNS.search(command):
            category = "deploy"
            should_capture = True
            prompt = (
                "[ai Memory] Deployment operation. Store the deployment "
                "context and any issues encountered."
            )

        return {
            "category": category,
            "exit_code": exit_code,
            "should_capture": should_capture,
            "prompt": prompt,
        }

    @staticmethod
    def classify_file_importance(file_path: str) -> str | None:
        """Classify a file's importance for memory suggestions."""
        if not file_path:
            return None
        if CONFIG_PATTERNS.search(file_path):
            return "config"
        if ENTRY_PATTERNS.search(file_path):
            return "entry_point"
        if TEST_FILE_PATTERNS.search(file_path):
            return "test"
        return None

    @staticmethod
    def get_task_transition_prompt(
        task_id: str, status: str, subject: str
    ) -> str | None:
        """Generate a memory prompt for task status transitions."""
        if status == "completed":
            return (
                f'[ai Memory] Task completed: "{subject}". '
                "REQUIRED: If this task produced a decision with rationale, "
                "a gotcha worth avoiding, or a reusable pattern — store it now "
                "via /ai:memory save."
            )
        elif status == "in_progress":
            return (
                f'[ai Memory] Starting task: "{subject}". '
                "Note your approach and key assumptions."
            )
        elif status == "pending":
            return (
                f'[ai Memory] Task moved to pending: "{subject}". '
                "Note why — blocked, deprioritized, or needs rework?"
            )
        return None

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extract meaningful keywords from text."""
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
        return set(list(w for w in words if w not in STOP_WORDS)[:20])
