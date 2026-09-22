"""Unit tests for signal analysis, injection tiers, and classifiers.

Covers TS-1.1 through TS-1.6 from test strategy.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
        )
    ),
)

from extensions.claude.agentic-inquiry.servers.daemon.managers.context import ContextManager
from extensions.claude.agentic-inquiry.servers.daemon.orchestrator import ServiceOrchestrator


class FakeMemoryManager:
    turn_count = 0

    async def recall(self, query, limit=5, include_global=False):
        return []


class FakeCacheManager:
    def get_context(self, key):
        return None

    def put_context(self, key, value):
        pass

    def is_duplicate_content(self, session_id, content, turn):
        return False

    @staticmethod
    def hash_key(*parts):
        return "|".join(parts)


@pytest.fixture
def context_manager():
    return ContextManager(
        workspace="/test/project",
        project_id="test123",
        config={},
        memory_manager=FakeMemoryManager(),
        cache_manager=FakeCacheManager(),
    )


@pytest.fixture
def orchestrator():
    return ServiceOrchestrator(
        workspace="/test/project",
        project_id="test123",
        config={},
    )


# --- TS-1.1: Entity Extraction ---


class TestEntityExtraction:
    def test_camelcase_entities(self, context_manager):
        signals = context_manager.analyze_signals(
            "Check StorageFacade and SearchService"
        )
        entities = signals["entities"]
        assert "StorageFacade" in entities
        assert "SearchService" in entities

    def test_constant_case_entities(self, context_manager):
        signals = context_manager.analyze_signals(
            "The EMBEDDING_DIM constant is important"
        )
        assert "EMBEDDING_DIM" in signals["entities"]

    def test_file_path_entities(self, context_manager):
        signals = context_manager.analyze_signals(
            "Look at storage/config.py"
        )
        assert any("config.py" in p for p in signals["file_paths"])

    def test_quoted_string_entities(self, context_manager):
        signals = context_manager.analyze_signals(
            "What is the 'hybrid_search' method?"
        )
        assert "hybrid_search" in signals["entities"]

    def test_no_entities(self, context_manager):
        signals = context_manager.analyze_signals("Hello there")
        # May have some short words but no CamelCase/CONSTANT
        assert len([e for e in signals["entities"] if e[0].isupper()]) == 0
        assert len(signals["file_paths"]) == 0


# --- TS-1.2: Intent Classification ---


class TestIntentClassification:
    def test_architectural_intent(self, context_manager):
        signals = context_manager.analyze_signals(
            "How does the search pipeline design work?"
        )
        assert signals["intent"] == "ARCHITECTURAL"

    def test_code_intent(self, context_manager):
        signals = context_manager.analyze_signals(
            "Where is the function implementation for search?"
        )
        assert signals["intent"] == "CODE"

    def test_debug_intent(self, context_manager):
        signals = context_manager.analyze_signals(
            "Tests are failing with ConnectionError"
        )
        assert signals["intent"] == "DEBUG"

    def test_general_intent(self, context_manager):
        signals = context_manager.analyze_signals("Hello, can you help me?")
        assert signals["intent"] == "GENERAL"


# --- TS-1.3: Injection Tier Scoring ---


class TestInjectionTierScoring:
    def test_full_packet_tier(self, context_manager):
        # Set previous keywords to trigger topic pivot
        context_manager._last_keywords = {"database", "config", "setup"}
        # Multiple entities + architectural intent + file path + topic pivot → high score
        signals = context_manager.analyze_signals(
            "URGENT: How does the SearchService pipeline design work in storage/vector.py with PostgresVectorProvider?"
        )
        assert signals["tier"] == "FULL_PACKET"
        assert signals["score"] >= 70

    def test_none_tier_simple_message(self, context_manager):
        # Simple message, no entities, no intent
        signals = context_manager.analyze_signals("Thanks, looks good")
        assert signals["tier"] == "NONE"
        assert signals["score"] < 20

    def test_memory_only_recall_trigger(self, context_manager):
        # First set some keywords to make pivot possible
        context_manager.analyze_signals("Working on database configuration")
        # Now a recall-type question with topic pivot
        signals = context_manager.analyze_signals(
            "Why did we make that decision?"
        )
        assert signals["has_recall"]
        assert signals["score"] >= 20

    def test_urgency_bonus(self, context_manager):
        signals = context_manager.analyze_signals(
            "URGENT: Production is down, critical error in search service"
        )
        assert signals["has_urgency"]
        assert signals["score"] >= 40


# --- TS-1.4: Topic Pivot Detection ---


class TestTopicPivot:
    def test_detects_topic_pivot(self, context_manager):
        # First prompt establishes baseline
        context_manager.analyze_signals(
            "How does the authentication system handle JWT tokens?"
        )
        # Second prompt is completely different topic
        signals = context_manager.analyze_signals(
            "What database backend do we use for storage?"
        )
        assert signals["topic_pivot"] is True

    def test_detects_continuation(self, context_manager):
        # First prompt
        context_manager.analyze_signals(
            "How does AlloyDB embedding work?"
        )
        # Second prompt is related
        signals = context_manager.analyze_signals(
            "Show me the AlloyDB embedding configuration code"
        )
        assert signals["topic_pivot"] is False

    def test_first_prompt_no_pivot(self, context_manager):
        # Very first prompt has no previous keywords to compare
        signals = context_manager.analyze_signals("First prompt ever")
        assert signals["topic_pivot"] is False


# --- TS-1.5: File Importance Classification ---


class TestFileClassification:
    def test_config_file(self, orchestrator):
        assert orchestrator.classify_file_importance("config.py") == "config"
        assert orchestrator.classify_file_importance("settings.yaml") == "config"
        assert orchestrator.classify_file_importance(".env") == "config"
        assert orchestrator.classify_file_importance("Dockerfile") == "config"

    def test_entry_point(self, orchestrator):
        assert orchestrator.classify_file_importance("main.py") == "entry_point"
        assert orchestrator.classify_file_importance("__main__.py") == "entry_point"
        assert orchestrator.classify_file_importance("index.js") == "entry_point"
        assert orchestrator.classify_file_importance("app.py") == "entry_point"

    def test_test_file(self, orchestrator):
        assert orchestrator.classify_file_importance("test_vector.py") == "test"
        assert orchestrator.classify_file_importance("vector.spec.js") == "test"

    def test_regular_file(self, orchestrator):
        assert orchestrator.classify_file_importance("utils.py") is None
        assert orchestrator.classify_file_importance("vector.py") is None

    def test_empty_path(self, orchestrator):
        assert orchestrator.classify_file_importance("") is None


# --- TS-1.6: Bash Command Classification ---


class TestBashClassification:
    def test_test_command_pass(self, orchestrator):
        result = orchestrator.classify_bash_command(
            "uv run pytest tests/", 0, "5 passed"
        )
        assert result["category"] == "test"
        assert result["should_capture"] is True

    def test_test_command_fail(self, orchestrator):
        result = orchestrator.classify_bash_command(
            "pytest tests/ -v", 1, "FAILED test_search.py"
        )
        assert result["category"] == "test"
        assert result["should_capture"] is True
        assert "failed" in result["prompt"].lower()

    def test_git_command(self, orchestrator):
        result = orchestrator.classify_bash_command(
            "git commit -m 'fix bug'", 0, ""
        )
        assert result["category"] == "git"
        assert result["should_capture"] is True

    def test_build_command_fail(self, orchestrator):
        result = orchestrator.classify_bash_command(
            "npm run build", 1, "Error: Module not found"
        )
        assert result["category"] == "build"
        assert result["should_capture"] is True

    def test_deploy_command(self, orchestrator):
        result = orchestrator.classify_bash_command(
            "kubectl apply -f deploy.yaml", 0, ""
        )
        assert result["category"] == "deploy"
        assert result["should_capture"] is True

    def test_general_command(self, orchestrator):
        result = orchestrator.classify_bash_command("ls -la", 0, "")
        assert result["category"] == "general"
        assert result["should_capture"] is False


# --- Task Transition Prompts ---


class TestTaskTransitions:
    def test_completed_prompt(self, orchestrator):
        prompt = orchestrator.get_task_transition_prompt(
            "1", "completed", "Fix search bug"
        )
        assert prompt is not None
        assert "REQUIRED" in prompt
        assert "Fix search bug" in prompt

    def test_in_progress_prompt(self, orchestrator):
        prompt = orchestrator.get_task_transition_prompt(
            "2", "in_progress", "Add caching"
        )
        assert prompt is not None
        assert "Add caching" in prompt

    def test_no_prompt_for_unknown_status(self, orchestrator):
        prompt = orchestrator.get_task_transition_prompt(
            "3", "deleted", "Old task"
        )
        assert prompt is None
