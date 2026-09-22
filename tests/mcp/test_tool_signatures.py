"""Parameter validation tests for MCP tools.

This module tests that tool signatures match their service implementations
to prevent runtime parameter mismatch errors.
"""

import pytest

pytestmark = pytest.mark.unit
import inspect

from agentic_inquiry.mcp.tools.context import build_context
from agentic_inquiry.mcp.services.context_builder import ContextBuilder


class TestBuildContextSignature:
    """Test build_context tool signature matches ContextBuilder implementation."""
    
    def test_build_context_no_filters_parameter(self):
        """Verify build_context does not have filters parameter."""
        sig = inspect.signature(build_context)
        params = list(sig.parameters.keys())
        
        # Verify filters is NOT in parameters
        assert "filters" not in params, (
            "build_context should not have 'filters' parameter - "
            "it's not implemented in ContextBuilder.build_context"
        )
    
    def test_build_context_has_required_parameters(self):
        """Verify build_context has all required parameters."""
        sig = inspect.signature(build_context)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id", "query"]
        for param in required:
            assert param in params, f"build_context must have '{param}' parameter"
    
    def test_build_context_has_optional_parameters(self):
        """Verify build_context has expected optional parameters."""
        sig = inspect.signature(build_context)
        params = sig.parameters
        
        # Optional parameters with defaults
        optional = {
            "focus": "balanced",
            "depth": "focused",
            "max_tokens": 4000
        }
        
        for param_name, expected_default in optional.items():
            assert param_name in params, f"build_context should have '{param_name}' parameter"
            param = params[param_name]
            assert param.default == expected_default, (
                f"Parameter '{param_name}' should have default value {expected_default}, "
                f"got {param.default}"
            )
    
    def test_context_builder_signature_matches_tool(self):
        """Verify ContextBuilder.build_context accepts parameters passed by tool."""
        tool_sig = inspect.signature(build_context)
        service_sig = inspect.signature(ContextBuilder.build_context)
        
        # Get parameters that the tool passes to the service
        # (excluding 'services' which is not passed to the service)
        set(tool_sig.parameters.keys()) - {"services"}
        
        # Get parameters that the service accepts
        # (excluding 'self' which is implicit)
        service_params = set(service_sig.parameters.keys()) - {"self"}
        
        # Tool should only pass parameters that service accepts
        # Note: Tool passes session_id, query, focus, depth, max_tokens
        # Service accepts: query, session_id, focus, depth, max_tokens, progressive
        
        # Parameters the tool passes
        passed_params = {"session_id", "query", "focus", "depth", "max_tokens"}
        
        # Verify all passed parameters are accepted by service
        for param in passed_params:
            assert param in service_params, (
                f"Tool passes '{param}' but ContextBuilder.build_context doesn't accept it"
            )
    
    def test_context_builder_does_not_accept_filters(self):
        """Verify ContextBuilder.build_context does not accept filters parameter."""
        sig = inspect.signature(ContextBuilder.build_context)
        params = list(sig.parameters.keys())
        
        assert "filters" not in params, (
            "ContextBuilder.build_context should not have 'filters' parameter"
        )
    
    def test_context_builder_does_not_accept_project_id(self):
        """Verify ContextBuilder.build_context does not accept project_id parameter.
        
        The service gets project_id from the session internally, so it should not
        be passed as a parameter.
        """
        sig = inspect.signature(ContextBuilder.build_context)
        params = list(sig.parameters.keys())
        
        assert "project_id" not in params, (
            "ContextBuilder.build_context should not have 'project_id' parameter - "
            "it gets project_id from the session internally"
        )


class TestBuildContextExecution:
    """Test build_context tool execution without filters parameter."""
    
    @pytest.mark.asyncio
    async def test_build_context_executes_without_filters(self, mock_mcp_services):
        """Test that build_context executes successfully without filters parameter."""
        services = mock_mcp_services
        
        # Mock session validation
        services["session_manager"].validate_session.return_value = True
        
        # Mock context builder response
        services["context_builder"].build_context.return_value = {
            "context": {
                "code": [],
                "documentation": [],
                "memories": [],
                "relationships": []
            },
            "summary": "Test summary",
            "suggestions": [],
            "token_usage": {
                "estimated_tokens": 100,
                "max_tokens": 4000,
                "remaining_tokens": 3900,
                "usage_percentage": 2.5,
                "items_included": 0,
                "items_available": 0
            }
        }
        
        # Call tool without filters parameter
        result = await build_context(
            services=services,
            session_id="test-session",
            query="test query",
            focus="balanced",
            depth="focused",
            max_tokens=4000
        )
        
        # Verify successful execution
        assert "context" in result
        assert "summary" in result
        assert "token_usage" in result
    
    @pytest.mark.asyncio
    async def test_build_context_rejects_filters_parameter(self, mock_mcp_services):
        """Test that build_context raises TypeError if filters parameter is passed."""
        services = mock_mcp_services
        
        # Attempt to call with filters parameter should raise TypeError
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            await build_context(
                services=services,
                session_id="test-session",
                query="test query",
                filters={"language": "python"}  # This should cause TypeError
            )
    
    @pytest.mark.asyncio
    async def test_context_builder_called_with_correct_parameters(self, mock_mcp_services):
        """Test that context_builder.build_context is called with correct parameters."""
        services = mock_mcp_services
        
        # Mock session validation
        services["session_manager"].validate_session.return_value = True
        
        # Mock context builder response
        services["context_builder"].build_context.return_value = {
            "context": {"code": [], "documentation": [], "memories": [], "relationships": []},
            "summary": "Test",
            "suggestions": [],
            "token_usage": {
                "estimated_tokens": 100,
                "max_tokens": 4000,
                "remaining_tokens": 3900,
                "usage_percentage": 2.5,
                "items_included": 0,
                "items_available": 0
            }
        }
        
        # Call tool
        await build_context(
            services=services,
            session_id="test-session",
            query="test query",
            focus="code",
            depth="comprehensive",
            max_tokens=2000
        )
        
        # Verify context_builder was called with correct parameters
        services["context_builder"].build_context.assert_called_once()
        call_kwargs = services["context_builder"].build_context.call_args.kwargs
        
        # Verify expected parameters
        assert call_kwargs["session_id"] == "test-session"
        assert call_kwargs["query"] == "test query"
        assert call_kwargs["focus"] == "code"
        assert call_kwargs["depth"] == "comprehensive"
        assert call_kwargs["max_tokens"] == 2000
        
        # Verify filters and project_id are NOT passed
        assert "filters" not in call_kwargs, "filters should not be passed to context_builder"
        assert "project_id" not in call_kwargs, "project_id should not be passed to context_builder"



class TestFindPatternsSignature:
    """Test find_patterns tool signature matches PatternAnalyzer implementation."""
    
    def test_find_patterns_has_pattern_type_parameter(self):
        """Verify find_patterns has pattern_type parameter."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        sig = inspect.signature(find_patterns)
        params = list(sig.parameters.keys())
        
        # Verify pattern_type is in parameters
        assert "pattern_type" in params, (
            "find_patterns must have 'pattern_type' parameter"
        )
    
    def test_find_patterns_has_required_parameters(self):
        """Verify find_patterns has all required parameters."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        sig = inspect.signature(find_patterns)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id"]
        for param in required:
            assert param in params, f"find_patterns must have '{param}' parameter"
    
    def test_find_patterns_has_optional_parameters(self):
        """Verify find_patterns has expected optional parameters."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        sig = inspect.signature(find_patterns)
        params = sig.parameters
        
        # Optional parameters with defaults
        optional = {
            "pattern_type": "auto",
            "limit": 10
        }
        
        for param_name, expected_default in optional.items():
            assert param_name in params, f"find_patterns should have '{param_name}' parameter"
            param = params[param_name]
            assert param.default == expected_default, (
                f"Parameter '{param_name}' should have default value {expected_default}, "
                f"got {param.default}"
            )
    
    def test_pattern_analyzer_signature_matches_tool(self):
        """Verify PatternAnalyzer.find_patterns accepts parameters passed by tool."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        from agentic_inquiry.mcp.services.pattern_analyzer import PatternAnalyzer
        
        tool_sig = inspect.signature(find_patterns)
        service_sig = inspect.signature(PatternAnalyzer.find_patterns)
        
        # Get parameters that the tool passes to the service
        # (excluding 'services' and 'session_id' which are not passed to the service)
        set(tool_sig.parameters.keys()) - {"services", "session_id"}
        
        # Get parameters that the service accepts
        # (excluding 'self' which is implicit)
        service_params = set(service_sig.parameters.keys()) - {"self"}
        
        # Parameters the tool passes
        passed_params = {"pattern_type", "limit"}
        
        # Note: Tool also passes project_id which it extracts from session
        passed_params.add("project_id")
        
        # Verify all passed parameters are accepted by service
        for param in passed_params:
            assert param in service_params, (
                f"Tool passes '{param}' but PatternAnalyzer.find_patterns doesn't accept it"
            )
    
    def test_pattern_type_values(self):
        """Verify pattern_type accepts expected values."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        sig = inspect.signature(find_patterns)
        
        # pattern_type should have default "auto"
        assert sig.parameters["pattern_type"].default == "auto"
        
        # Valid values are documented in the docstring
        # We'll test execution with different values in the execution tests


class TestFindPatternsExecution:
    """Test find_patterns tool execution with different pattern types."""
    
    @pytest.mark.asyncio
    async def test_find_patterns_with_auto_type(self, mock_pattern_services):
        """Test find_patterns with pattern_type='auto'."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        services = mock_pattern_services
        
        # Call tool with auto pattern type
        result = await find_patterns(
            services=services,
            session_id="test-session",
            pattern_type="auto",
            limit=10
        )
        
        # Verify successful execution
        assert "patterns" in result
        assert "total" in result
        assert "pattern_type" in result
        assert result["pattern_type"] == "auto"
        
        # Verify service was called with correct parameters
        services["pattern_analyzer"].find_patterns.assert_called_once()
        call_kwargs = services["pattern_analyzer"].find_patterns.call_args.kwargs
        assert call_kwargs["pattern_type"] is None  # "auto" maps to None
        assert call_kwargs["limit"] == 10
    
    @pytest.mark.asyncio
    async def test_find_patterns_with_architectural_type(self, mock_pattern_services):
        """Test find_patterns with pattern_type='architectural'."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        services = mock_pattern_services
        
        # Call tool with architectural pattern type
        result = await find_patterns(
            services=services,
            session_id="test-session",
            pattern_type="architectural",
            limit=5
        )
        
        # Verify successful execution
        assert "patterns" in result
        assert result["pattern_type"] == "architectural"
        
        # Verify service was called with correct parameters
        call_kwargs = services["pattern_analyzer"].find_patterns.call_args.kwargs
        assert call_kwargs["pattern_type"] == "architectural"
        assert call_kwargs["limit"] == 5
    
    @pytest.mark.asyncio
    async def test_find_patterns_with_design_type(self, mock_pattern_services):
        """Test find_patterns with pattern_type='design'."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        services = mock_pattern_services
        
        result = await find_patterns(
            services=services,
            session_id="test-session",
            pattern_type="design",
            limit=10
        )
        
        assert result["pattern_type"] == "design"
        call_kwargs = services["pattern_analyzer"].find_patterns.call_args.kwargs
        assert call_kwargs["pattern_type"] == "design"
    
    @pytest.mark.asyncio
    async def test_find_patterns_with_naming_type(self, mock_pattern_services):
        """Test find_patterns with pattern_type='naming'."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        services = mock_pattern_services
        
        result = await find_patterns(
            services=services,
            session_id="test-session",
            pattern_type="naming",
            limit=10
        )
        
        assert result["pattern_type"] == "naming"
        call_kwargs = services["pattern_analyzer"].find_patterns.call_args.kwargs
        assert call_kwargs["pattern_type"] == "naming"
    
    @pytest.mark.asyncio
    async def test_find_patterns_with_antipattern_type(self, mock_pattern_services):
        """Test find_patterns with pattern_type='antipattern'."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        services = mock_pattern_services
        
        result = await find_patterns(
            services=services,
            session_id="test-session",
            pattern_type="antipattern",
            limit=10
        )
        
        assert result["pattern_type"] == "antipattern"
        call_kwargs = services["pattern_analyzer"].find_patterns.call_args.kwargs
        assert call_kwargs["pattern_type"] == "antipattern"
    
    @pytest.mark.asyncio
    async def test_find_patterns_filters_by_type(self, mock_pattern_services):
        """Test that pattern_type parameter filters results correctly."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        services = mock_pattern_services
        
        # Mock different patterns for different types
        architectural_patterns = [
            {"name": "MVC", "type": "architectural", "count": 5},
            {"name": "Factory", "type": "architectural", "count": 3}
        ]
        
        services["pattern_analyzer"].find_patterns.return_value = architectural_patterns
        
        result = await find_patterns(
            services=services,
            session_id="test-session",
            pattern_type="architectural",
            limit=10
        )
        
        # Verify patterns are returned
        assert len(result["patterns"]) == 2
        assert all(p["type"] == "architectural" for p in result["patterns"])
    
    @pytest.mark.asyncio
    async def test_find_patterns_default_parameters(self, mock_pattern_services):
        """Test find_patterns with default parameters."""
        from agentic_inquiry.mcp.tools.analysis import find_patterns
        
        services = mock_pattern_services
        
        # Call with only required parameters
        result = await find_patterns(
            services=services,
            session_id="test-session"
        )
        
        # Verify defaults were used
        assert result["pattern_type"] == "auto"
        call_kwargs = services["pattern_analyzer"].find_patterns.call_args.kwargs
        assert call_kwargs["pattern_type"] is None  # auto maps to None
        assert call_kwargs["limit"] == 10


@pytest.fixture
def mock_pattern_services():
    """Create mock MCP services for pattern testing."""
    from unittest.mock import AsyncMock, MagicMock
    from agentic_inquiry.mcp.models.session import Session
    from datetime import datetime
    
    session_manager = MagicMock()
    session_manager.validate_session = AsyncMock(return_value=True)
    
    # Mock session with project_id
    mock_session = Session(
        session_id="test-session",
        project_id="test-project",
        created_at=datetime.now(),
        last_active=datetime.now(),
        state="active",
        status="active",
        metadata={}
    )
    session_manager.get_session = AsyncMock(return_value=mock_session)
    
    pattern_analyzer = MagicMock()
    pattern_analyzer.find_patterns = AsyncMock(return_value=[
        {
            "name": "Test Pattern",
            "type": "architectural",
            "count": 5,
            "examples": [],
            "prevalence": 0.5
        }
    ])
    
    event_system = MagicMock()
    event_system.emit = AsyncMock()

    storage = MagicMock()
    storage.get_entity = AsyncMock(return_value=None)

    # Mock config with required attributes
    mock_config = MagicMock()
    mock_config.search.graph_search.timeouts.find_patterns_ms = 5000

    return {
        "session_manager": session_manager,
        "pattern_analyzer": pattern_analyzer,
        "event_system": event_system,
        "storage": storage,
        "config": mock_config
    }


class TestGetSessionSignature:
    """Test get_session tool signature matches Session model."""
    
    def test_get_session_has_required_parameters(self):
        """Verify get_session has all required parameters."""
        from agentic_inquiry.mcp.tools.session import get_session
        
        sig = inspect.signature(get_session)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id"]
        for param in required:
            assert param in params, f"get_session must have '{param}' parameter"
    
    def test_session_model_has_status_field(self):
        """Verify Session model has status field."""
        from agentic_inquiry.mcp.models.session import Session
        
        # Session is a Pydantic model, check its fields
        assert "status" in Session.model_fields, (
            "Session model must have 'status' field"
        )
        
        # Verify default value
        assert Session.model_fields["status"].default == "active", (
            "Session status field should default to 'active'"
        )


class TestUnderstandEntitySignature:
    """Test understand_entity tool signature matches EntityResolver implementation."""
    
    def test_understand_entity_has_required_parameters(self):
        """Verify understand_entity has all required parameters."""
        from agentic_inquiry.mcp.tools.analysis import understand_entity
        
        sig = inspect.signature(understand_entity)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id", "entity"]
        for param in required:
            assert param in params, f"understand_entity must have '{param}' parameter"
    
    def test_understand_entity_has_optional_parameters(self):
        """Verify understand_entity has expected optional parameters."""
        from agentic_inquiry.mcp.tools.analysis import understand_entity
        
        sig = inspect.signature(understand_entity)
        params = sig.parameters
        
        # Optional parameters
        optional = ["entity_type"]
        
        for param_name in optional:
            assert param_name in params, f"understand_entity should have '{param_name}' parameter"
    
    def test_entity_resolver_signature_matches_tool(self):
        """Verify EntityResolver.resolve_entity accepts parameters passed by tool."""
        from agentic_inquiry.mcp.tools.analysis import understand_entity
        from agentic_inquiry.mcp.services.entity_resolver import EntityResolver
        
        inspect.signature(understand_entity)
        service_sig = inspect.signature(EntityResolver.resolve_entity)
        
        # Get parameters that the service accepts
        service_params = set(service_sig.parameters.keys()) - {"self"}
        
        # Parameters the tool passes to resolve_entity
        passed_params = {"entity_name", "project_id", "entity_type"}
        
        # Verify all passed parameters are accepted by service
        for param in passed_params:
            assert param in service_params, (
                f"Tool passes '{param}' but EntityResolver.resolve_entity doesn't accept it"
            )


class TestAnalyzeImpactSignature:
    """Test analyze_impact tool signature matches ImpactAnalyzer implementation."""
    
    def test_analyze_impact_has_required_parameters(self):
        """Verify analyze_impact has all required parameters."""
        from agentic_inquiry.mcp.tools.analysis import analyze_impact
        
        sig = inspect.signature(analyze_impact)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id", "entity"]
        for param in required:
            assert param in params, f"analyze_impact must have '{param}' parameter"
    
    def test_analyze_impact_has_optional_parameters(self):
        """Verify analyze_impact has expected optional parameters."""
        from agentic_inquiry.mcp.tools.analysis import analyze_impact
        
        sig = inspect.signature(analyze_impact)
        params = sig.parameters
        
        # Optional parameters with defaults
        # Note: Tool uses max_depth (not depth) to match ImpactAnalyzer
        optional = {
            "max_depth": 2
        }
        
        for param_name, expected_default in optional.items():
            assert param_name in params, f"analyze_impact should have '{param_name}' parameter"
            param = params[param_name]
            assert param.default == expected_default, (
                f"Parameter '{param_name}' should have default value {expected_default}, "
                f"got {param.default}"
            )
    
    def test_impact_analyzer_signature_matches_tool(self):
        """Verify ImpactAnalyzer.analyze_impact accepts parameters passed by tool."""
        from agentic_inquiry.mcp.tools.analysis import analyze_impact
        from agentic_inquiry.mcp.services.impact_analyzer import ImpactAnalyzer
        
        inspect.signature(analyze_impact)
        service_sig = inspect.signature(ImpactAnalyzer.analyze_impact)
        
        # Get parameters that the service accepts
        service_params = set(service_sig.parameters.keys()) - {"self"}
        
        # Parameters the tool passes to analyze_impact
        # Note: Tool passes max_depth as depth parameter to service
        passed_params = {"entity_name", "project_id", "depth", "include_indirect"}
        
        # Verify all passed parameters are accepted by service
        for param in passed_params:
            assert param in service_params, (
                f"Tool passes '{param}' but ImpactAnalyzer.analyze_impact doesn't accept it"
            )


class TestSearchKnowledgeSignature:
    """Test search_knowledge tool signature matches SearchService implementation."""
    
    def test_search_knowledge_has_required_parameters(self):
        """Verify search_knowledge has all required parameters."""
        from agentic_inquiry.mcp.tools.search import search_knowledge
        
        sig = inspect.signature(search_knowledge)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id", "query"]
        for param in required:
            assert param in params, f"search_knowledge must have '{param}' parameter"
    
    def test_search_knowledge_has_optional_parameters(self):
        """Verify search_knowledge has expected optional parameters."""
        from agentic_inquiry.mcp.tools.search import search_knowledge
        
        sig = inspect.signature(search_knowledge)
        params = sig.parameters
        
        # Optional parameters
        optional = ["limit", "search_type"]
        
        for param_name in optional:
            assert param_name in params, f"search_knowledge should have '{param_name}' parameter"


class TestMemoryToolsSignature:
    """Test memory tools signatures."""
    
    def test_save_memory_has_required_parameters(self):
        """Verify save_memory has all required parameters."""
        from agentic_inquiry.mcp.tools.memory import save_memory
        
        sig = inspect.signature(save_memory)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id", "content"]
        for param in required:
            assert param in params, f"save_memory must have '{param}' parameter"
    
    def test_recall_memories_has_required_parameters(self):
        """Verify recall_memories has all required parameters."""
        from agentic_inquiry.mcp.tools.memory import recall_memories
        
        sig = inspect.signature(recall_memories)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id", "query"]
        for param in required:
            assert param in params, f"recall_memories must have '{param}' parameter"


class TestSessionToolsSignature:
    """Test session tools signatures."""
    
    def test_create_session_has_required_parameters(self):
        """Verify create_session has all required parameters."""
        from agentic_inquiry.mcp.tools.session import create_session
        
        sig = inspect.signature(create_session)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services"]
        for param in required:
            assert param in params, f"create_session must have '{param}' parameter"
    
    def test_list_sessions_has_required_parameters(self):
        """Verify list_sessions has all required parameters."""
        from agentic_inquiry.mcp.tools.session import list_sessions
        
        sig = inspect.signature(list_sessions)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services"]
        for param in required:
            assert param in params, f"list_sessions must have '{param}' parameter"
    
    def test_resume_session_has_required_parameters(self):
        """Verify resume_session has all required parameters."""
        from agentic_inquiry.mcp.tools.session import resume_session
        
        sig = inspect.signature(resume_session)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id"]
        for param in required:
            assert param in params, f"resume_session must have '{param}' parameter"


class TestKnowledgeToolsSignature:
    """Test knowledge tools signatures."""
    
    def test_add_knowledge_has_required_parameters(self):
        """Verify add_knowledge has all required parameters."""
        from agentic_inquiry.mcp.tools.knowledge import add_knowledge
        
        sig = inspect.signature(add_knowledge)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id", "source"]
        for param in required:
            assert param in params, f"add_knowledge must have '{param}' parameter"


class TestInfoToolsSignature:
    """Test info tools signatures."""
    
    def test_get_events_has_required_parameters(self):
        """Verify get_events has all required parameters."""
        from agentic_inquiry.mcp.tools.info import get_events
        
        sig = inspect.signature(get_events)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id"]
        for param in required:
            assert param in params, f"get_events must have '{param}' parameter"
    
    def test_get_project_info_has_required_parameters(self):
        """Verify get_project_info has all required parameters."""
        from agentic_inquiry.mcp.tools.info import get_project_info
        
        sig = inspect.signature(get_project_info)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services", "session_id"]
        for param in required:
            assert param in params, f"get_project_info must have '{param}' parameter"
    
    def test_get_server_info_has_required_parameters(self):
        """Verify get_server_info has all required parameters."""
        from agentic_inquiry.mcp.tools.info import get_server_info
        
        sig = inspect.signature(get_server_info)
        params = list(sig.parameters.keys())
        
        # Required parameters
        required = ["services"]
        for param in required:
            assert param in params, f"get_server_info must have '{param}' parameter"


class TestAutomatedToolValidation:
    """Automated validation of all MCP tools.
    
    This test class provides comprehensive validation that can be run in CI
    to prevent parameter mismatch errors.
    """
    
    def test_all_tools_have_services_parameter(self):
        """Verify all MCP tools have 'services' parameter."""
        from agentic_inquiry.mcp.tools import (
            analysis, context, session, memory, search, knowledge, info
        )
        
        # Get all tool functions
        tools = [
            # Analysis tools
            (analysis.understand_entity, "understand_entity"),
            (analysis.analyze_impact, "analyze_impact"),
            (analysis.find_patterns, "find_patterns"),
            # Context tools
            (context.build_context, "build_context"),
            # Session tools
            (session.create_session, "create_session"),
            (session.get_session, "get_session"),
            (session.list_sessions, "list_sessions"),
            (session.resume_session, "resume_session"),
            # Memory tools
            (memory.save_memory, "save_memory"),
            (memory.recall_memories, "recall_memories"),
            # Search tools
            (search.search_knowledge, "search_knowledge"),
            # Knowledge tools
            (knowledge.add_knowledge, "add_knowledge"),
            # Info tools
            (info.get_events, "get_events"),
            (info.get_project_info, "get_project_info"),
            (info.get_server_info, "get_server_info"),
        ]
        
        for tool_func, tool_name in tools:
            sig = inspect.signature(tool_func)
            params = list(sig.parameters.keys())
            assert "services" in params, (
                f"Tool '{tool_name}' must have 'services' parameter"
            )
    
    def test_all_tools_except_create_and_list_have_session_id(self):
        """Verify all MCP tools (except create_session, list_sessions, get_server_info) have 'session_id' parameter."""
        from agentic_inquiry.mcp.tools import (
            analysis, context, session, memory, search, knowledge, info
        )
        
        # Tools that should have session_id
        tools_with_session = [
            (analysis.understand_entity, "understand_entity"),
            (analysis.analyze_impact, "analyze_impact"),
            (analysis.find_patterns, "find_patterns"),
            (context.build_context, "build_context"),
            (session.get_session, "get_session"),
            (session.resume_session, "resume_session"),
            (memory.save_memory, "save_memory"),
            (memory.recall_memories, "recall_memories"),
            (search.search_knowledge, "search_knowledge"),
            (knowledge.add_knowledge, "add_knowledge"),
            (info.get_events, "get_events"),
            (info.get_project_info, "get_project_info"),
        ]
        
        for tool_func, tool_name in tools_with_session:
            sig = inspect.signature(tool_func)
            params = list(sig.parameters.keys())
            assert "session_id" in params, (
                f"Tool '{tool_name}' must have 'session_id' parameter"
            )
    
    def test_no_tools_have_unexpected_parameters(self):
        """Verify tools don't have project_id parameter (except where needed)."""
        from agentic_inquiry.mcp.tools import (
            analysis, context, session, memory, search, knowledge, info
        )
        
        # All tools to check
        all_tools = [
            (analysis.understand_entity, "understand_entity"),
            (analysis.analyze_impact, "analyze_impact"),
            (analysis.find_patterns, "find_patterns"),
            (context.build_context, "build_context"),
            (session.get_session, "get_session"),
            (session.list_sessions, "list_sessions"),
            (session.create_session, "create_session"),
            (session.resume_session, "resume_session"),
            (memory.save_memory, "save_memory"),
            (memory.recall_memories, "recall_memories"),
            (search.search_knowledge, "search_knowledge"),
            (knowledge.add_knowledge, "add_knowledge"),
            (info.get_events, "get_events"),
            (info.get_project_info, "get_project_info"),
            (info.get_server_info, "get_server_info"),
        ]
        
        for tool_func, tool_name in all_tools:
            sig = inspect.signature(tool_func)
            params = list(sig.parameters.keys())
            
            # Most tools should not have project_id (except create_session and list_sessions)
            # create_session needs it to create a new session
            # list_sessions needs it to filter sessions by project
            if tool_name not in ["create_session", "list_sessions"]:
                assert "project_id" not in params, (
                    f"Tool '{tool_name}' should not have 'project_id' parameter - "
                    f"it should be extracted from session internally"
                )
    
    def test_search_knowledge_has_filters_parameter(self):
        """Verify search_knowledge has filters parameter (it IS implemented)."""
        from agentic_inquiry.mcp.tools.search import search_knowledge
        
        sig = inspect.signature(search_knowledge)
        params = list(sig.parameters.keys())
        
        assert "filters" in params, (
            "search_knowledge should have 'filters' parameter - it's implemented and passed to search service"
        )
    
    def test_create_session_has_project_id_parameter(self):
        """Verify create_session has project_id parameter (it's required to create a session)."""
        from agentic_inquiry.mcp.tools.session import create_session
        
        sig = inspect.signature(create_session)
        params = list(sig.parameters.keys())
        
        assert "project_id" in params, (
            "create_session must have 'project_id' parameter to create a new session"
        )
    
    def test_all_tool_parameters_have_type_hints(self):
        """Verify all tool parameters have type hints."""
        from agentic_inquiry.mcp.tools import (
            analysis, context, session, memory, search, knowledge, info
        )
        
        tools = [
            (analysis.understand_entity, "understand_entity"),
            (analysis.analyze_impact, "analyze_impact"),
            (analysis.find_patterns, "find_patterns"),
            (context.build_context, "build_context"),
            (session.create_session, "create_session"),
            (session.get_session, "get_session"),
            (session.list_sessions, "list_sessions"),
            (session.resume_session, "resume_session"),
            (memory.save_memory, "save_memory"),
            (memory.recall_memories, "recall_memories"),
            (search.search_knowledge, "search_knowledge"),
            (knowledge.add_knowledge, "add_knowledge"),
            (info.get_events, "get_events"),
            (info.get_project_info, "get_project_info"),
            (info.get_server_info, "get_server_info"),
        ]
        
        for tool_func, tool_name in tools:
            sig = inspect.signature(tool_func)
            
            for param_name, param in sig.parameters.items():
                assert param.annotation != inspect.Parameter.empty, (
                    f"Tool '{tool_name}' parameter '{param_name}' must have type hint"
                )
    
    def test_all_tools_have_return_type_hints(self):
        """Verify all tools have return type hints."""
        from agentic_inquiry.mcp.tools import (
            analysis, context, session, memory, search, knowledge, info
        )
        
        tools = [
            (analysis.understand_entity, "understand_entity"),
            (analysis.analyze_impact, "analyze_impact"),
            (analysis.find_patterns, "find_patterns"),
            (context.build_context, "build_context"),
            (session.create_session, "create_session"),
            (session.get_session, "get_session"),
            (session.list_sessions, "list_sessions"),
            (session.resume_session, "resume_session"),
            (memory.save_memory, "save_memory"),
            (memory.recall_memories, "recall_memories"),
            (search.search_knowledge, "search_knowledge"),
            (knowledge.add_knowledge, "add_knowledge"),
            (info.get_events, "get_events"),
            (info.get_project_info, "get_project_info"),
            (info.get_server_info, "get_server_info"),
        ]
        
        for tool_func, tool_name in tools:
            sig = inspect.signature(tool_func)
            assert sig.return_annotation != inspect.Signature.empty, (
                f"Tool '{tool_name}' must have return type hint"
            )


@pytest.fixture
def mock_mcp_services():
    """Create mock MCP services for testing."""
    from unittest.mock import AsyncMock, MagicMock
    
    session_manager = MagicMock()
    session_manager.validate_session = AsyncMock(return_value=True)
    session_manager.get_session = AsyncMock(return_value=MagicMock(session_id="test-session"))
    
    context_builder = MagicMock()
    context_builder.build_context = AsyncMock()
    
    event_system = MagicMock()
    event_system.emit = AsyncMock()
    
    search_service = MagicMock()
    search_service.hybrid_search = AsyncMock(return_value=[])
    
    return {
        "session_manager": session_manager,
        "context_builder": context_builder,
        "event_system": event_system,
        "search_service": search_service
    }
