"""Tests for agentic_inquiry.server.signals.analyzer - Signal analysis engine."""

import pytest

from agentic_inquiry.server.signals.analyzer import (
    TIER_FULL_PACKET,
    TIER_MEMORY_ONLY,
    TIER_NONE,
    TIER_RELATED_LINKS,
    SignalAnalyzer,
)


@pytest.fixture
def analyzer():
    return SignalAnalyzer()


@pytest.fixture
def analyzer_custom():
    config = {
        "signals": {
            "entity_weight": 20,
            "intent_weight": 15,
            "file_path_weight": 10,
        }
    }
    return SignalAnalyzer(config)


class TestSignalAnalysis:
    """Test signal extraction and tier scoring."""

    def test_empty_prompt_returns_none_tier(self, analyzer):
        result = analyzer.analyze_signals("")
        assert result["tier"] == TIER_NONE
        assert result["score"] == 0

    def test_simple_greeting_low_score(self, analyzer):
        result = analyzer.analyze_signals("hello how are you")
        assert result["score"] < 40

    def test_code_entity_detection(self, analyzer):
        result = analyzer.analyze_signals("How does AuthenticationService work?")
        assert "AuthenticationService" in result.get("entities", [])
        assert result["score"] > 0

    def test_file_path_detection(self, analyzer):
        result = analyzer.analyze_signals("Check the file src/auth/login.py please")
        assert len(result.get("file_paths", [])) > 0

    def test_code_intent(self, analyzer):
        result = analyzer.analyze_signals("implement the UserController class with REST endpoints")
        assert result["intent"] in ("CODE", "DEBUG", "ARCHITECTURAL")

    def test_architecture_intent(self, analyzer):
        result = analyzer.analyze_signals("describe the overall architecture and design patterns used")
        assert result["intent"] in ("ARCHITECTURAL", "CODE")

    def test_debug_intent(self, analyzer):
        result = analyzer.analyze_signals("debug the error in the authentication flow")
        assert result["intent"] == "DEBUG"

    def test_full_packet_tier(self, analyzer):
        # A prompt with entities + intent should score high enough for full packet
        result = analyzer.analyze_signals(
            "implement the UserAuthenticationService.authenticate() method "
            "following the pattern in auth_helper.py"
        )
        assert result["tier"] in (TIER_FULL_PACKET, TIER_RELATED_LINKS)
        assert result["score"] >= 40

    def test_tier_scoring_thresholds(self, analyzer):
        # Very code-heavy prompt should get FULL_PACKET
        result = analyzer.analyze_signals(
            "Refactor the IndexingPipeline class in agentic_inquiry/indexing/pipeline.py "
            "to support batch processing of DocumentChunk entities"
        )
        assert result["tier"] == TIER_FULL_PACKET

    def test_memory_only_tier(self, analyzer):
        result = analyzer.analyze_signals("what was the decision about caching?")
        # With recall trigger "what was" it should get some score
        assert result["tier"] in (TIER_MEMORY_ONLY, TIER_RELATED_LINKS, TIER_NONE)

    def test_custom_config_weights(self, analyzer_custom):
        result = analyzer_custom.analyze_signals("Check AuthService")
        assert "tier" in result
        assert "score" in result

    def test_camel_case_extraction(self, analyzer):
        result = analyzer.analyze_signals("The UserAccountManager handles it")
        assert "UserAccountManager" in result.get("entities", [])

    def test_snake_case_extraction(self, analyzer):
        result = analyzer.analyze_signals("call process_payment_request to handle it")
        entities = result.get("entities", [])
        assert any("process_payment_request" in str(e) for e in entities)

    def test_returns_keywords(self, analyzer):
        result = analyzer.analyze_signals("authentication service handles login flow")
        assert "keywords" in result
        assert isinstance(result["keywords"], list)

    def test_topic_pivot_detection(self, analyzer):
        # First prompt sets baseline
        analyzer.analyze_signals("authentication service login")
        # Completely different topic
        result = analyzer.analyze_signals("database migration performance tuning")
        assert "topic_pivot" in result


class TestBashClassification:
    """Test bash command classification."""

    def test_test_command(self, analyzer):
        result = SignalAnalyzer.classify_bash_command("pytest tests/", 0, "")
        assert result["category"] == "test"

    def test_test_failure(self, analyzer):
        result = SignalAnalyzer.classify_bash_command("pytest tests/", 1, "FAILED 3")
        assert result["prompt"] is not None
        assert result["should_capture"]

    def test_build_command(self, analyzer):
        result = SignalAnalyzer.classify_bash_command("npm run build", 0, "")
        assert result["category"] == "build"

    def test_git_command(self, analyzer):
        result = SignalAnalyzer.classify_bash_command("git commit -m 'fix'", 0, "")
        assert result["category"] == "git"

    def test_deploy_command(self, analyzer):
        result = SignalAnalyzer.classify_bash_command("kubectl apply -f deploy.yaml", 0, "")
        assert result["category"] == "deploy"

    def test_general_command(self, analyzer):
        result = SignalAnalyzer.classify_bash_command("ls -la", 0, "")
        assert result["category"] == "general"
        assert not result["should_capture"]


class TestFileClassification:
    """Test file importance classification."""

    def test_config_file(self, analyzer):
        result = SignalAnalyzer.classify_file_importance("pyproject.toml")
        assert result == "config"

    def test_entry_point(self, analyzer):
        result = SignalAnalyzer.classify_file_importance("src/__main__.py")
        assert result == "entry_point"

    def test_regular_file(self, analyzer):
        result = SignalAnalyzer.classify_file_importance("src/utils/helpers.py")
        assert result is None  # Regular files return None

    def test_test_file(self, analyzer):
        result = SignalAnalyzer.classify_file_importance("tests/test_auth.py")
        assert result == "test"

    def test_empty_path(self, analyzer):
        result = SignalAnalyzer.classify_file_importance("")
        assert result is None


class TestTaskTransition:
    """Test task update prompt generation."""

    def test_completed_task(self, analyzer):
        prompt = SignalAnalyzer.get_task_transition_prompt("1", "completed", "Build auth module")
        assert prompt is not None
        assert "completed" in prompt.lower() or "memory" in prompt.lower()

    def test_in_progress_task(self, analyzer):
        prompt = SignalAnalyzer.get_task_transition_prompt("1", "in_progress", "Build auth module")
        assert prompt is not None
        assert "starting" in prompt.lower() or "approach" in prompt.lower()

    def test_pending_task(self, analyzer):
        prompt = SignalAnalyzer.get_task_transition_prompt("1", "pending", "Build auth module")
        assert prompt is not None

    def test_unknown_status(self, analyzer):
        prompt = SignalAnalyzer.get_task_transition_prompt("1", "deleted", "Old task")
        assert prompt is None
