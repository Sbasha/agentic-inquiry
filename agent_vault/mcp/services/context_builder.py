"""Context builder service for intelligent context assembly.

This module provides the ContextBuilder service that assembles comprehensive
context from multiple sources (code, documentation, memories) while managing
token budgets and relevance ranking.
"""

from typing import List, Dict, Any, Optional, Literal, Union, TYPE_CHECKING
from dataclasses import dataclass, field
import asyncio
import logging

from agent_vault.search.service import SearchService
from agent_vault.memory.system import MemorySystem
from agent_vault.config import Config
from agent_vault.events.models import EventStatus
from agent_vault.mcp.services.token_optimizer import TokenBudget, TokenOptimizer
from agent_vault.mcp.services.session_manager import SessionManager
from agent_vault.mcp.utils.project_state import check_project_state
from agent_vault.mcp.services.gatherers import (
    ContextGathererProtocol,
    GatherContext,
    CodeGatherer,
    DocsGatherer,
    MemoryGatherer,
    GraphGatherer,
)
from agent_vault.storage.facade import StorageFacade

if TYPE_CHECKING:
    from agent_vault.events.system import EventSystem

logger = logging.getLogger(__name__)


@dataclass
class ContextItem:
    """Represents a single context item.
    
    Attributes:
        id: Unique identifier
        type: Type of item (code, documentation, memory)
        name: Display name
        summary: Brief summary
        relevance_score: Relevance to query (0.0 to 1.0)
        location: File path or location
        snippet: Short excerpt
        content: Full content (optional, for token efficiency)
        metadata: Additional metadata
        why_relevant: Explanation of relevance
    """
    id: str
    type: str
    name: str
    summary: str
    relevance_score: float
    location: str
    snippet: str
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = field(default=None)
    why_relevant: str = ""
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ContextBuilder:
    """Builds comprehensive context for agent tasks.

    Assembles context from multiple sources (code, documentation, memories)
    while managing token budgets and relevance ranking. Supports progressive
    discovery for multi-turn refinement.
    """

    def __init__(
        self,
        search_service: SearchService,
        memory_system: MemorySystem,
        db_manager: StorageFacade,
        session_manager: SessionManager,
        config: Config,
        event_system: Optional["EventSystem"] = None
    ):
        """Initialize context builder.

        Args:
            search_service: Search service for finding relevant content
            memory_system: Memory system for retrieving memories
            db_manager: StorageFacade instance providing unified storage access
            session_manager: Session manager for session state
            config: Configuration object
            event_system: Optional event system for emitting context building events
        """
        # Use StorageFacade directly - it provides count_records method
        # that works across all backends (LanceDB, PostgreSQL, etc.)
        self.db = db_manager
        logger.debug("ContextBuilder initialized with StorageFacade")

        self.search = search_service
        self.memory = memory_system
        self.session_manager = session_manager
        self.config = config
        self.event_system = event_system
        self.token_optimizer = TokenOptimizer()

        # Initialize gatherers
        self._code_gatherer: ContextGathererProtocol = CodeGatherer(
            search_service, self.token_optimizer
        )
        self._docs_gatherer: ContextGathererProtocol = DocsGatherer(
            search_service, self.token_optimizer
        )
        self._memory_gatherer: ContextGathererProtocol = MemoryGatherer(
            memory_system, self.token_optimizer
        )
        self._graph_gatherer: ContextGathererProtocol = GraphGatherer(search_service)
    
    async def build_context(
        self,
        query: str,
        session_id: str,
        focus: Literal["code", "docs", "memories", "all"] = "all",
        depth: Literal["focused", "broad", "comprehensive"] = "broad",
        max_tokens: int = 4000,
        progressive: bool = False,
        include_overview: bool = False
    ) -> Dict[str, Any]:
        """Build comprehensive context for a query.
        
        Args:
            query: Query to build context for
            session_id: Session identifier
            focus: What to focus on (code, docs, memories, all)
            depth: How deep to go (focused, broad, comprehensive)
            max_tokens: Maximum tokens for context
            progressive: Whether to support progressive discovery
            include_overview: If True, prioritize overview content (README, docs, architecture)
            
        Returns:
            Dictionary containing:
                - context: Dict with code, documentation, memories, relationships
                - summary: Overall summary
                - suggestions: Suggestions for refinement
                - token_usage: Token usage statistics
        """
        # Get session for project_id first to include in logging
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        project_id = session.project_id

        # Check project state for staleness warnings (P0-1 fix)
        project_state = await check_project_state(self.db, project_id)

        # Diagnostic logging with all parameters
        logger.info(
            "Building context: query=%s, focus=%s, depth=%s, max_tokens=%s, project_id=%s, include_overview=%s",
            query, focus, depth, max_tokens, project_id, include_overview
        )
        
        # Emit context.building_started event
        if self.event_system:
            await self.event_system.emit(
                "context.building_started",
                source="ContextBuilder",
                status=EventStatus.PROGRESS,
                session_id=session_id,
                project_id=project_id,
                query=query[:100],  # Truncate long queries
                focus=focus,
                depth=depth,
                max_tokens=max_tokens
            )
        
        budget = TokenBudget(max_tokens=max_tokens)
        context: Dict[str, List[Any]] = {
            "code": [],
            "documentation": [],
            "memories": [],
            "relationships": []
        }

        # Pre-compute query vector once for all searches (ISS-W2-013 optimization)
        # For server-side embedding backends (AlloyDB, RDS), pass raw query text
        # so the database generates embeddings in the correct dimensions.
        query_vector: Optional[Union[List[float], str]] = None
        if focus in ["code", "docs", "all"]:
            from agent_vault.storage.capabilities import get_capabilities_for_backend
            _backend = self.db.get_backend_type() if hasattr(self.db, 'get_backend_type') else "lancedb"
            capabilities = get_capabilities_for_backend(_backend)
            if capabilities.uses_server_side_embedding:
                query_vector = query  # Pass raw text for server-side embedding
            else:
                query_vector_array = await self.search.embedding_service.embed_async(query)
                query_vector = query_vector_array.tolist()

        # Gather context in parallel using gatherers (ISS-W2-013 optimization)
        # Build list of coroutines to run in parallel
        gather_tasks: List[asyncio.Task[List[Dict[str, Any]]]] = []
        task_keys: List[str] = []

        # Create base gather context
        base_context = GatherContext(
            query=query,
            budget=budget,
            depth=depth,
            project_id=project_id,
            session_id=session_id,
            include_overview=include_overview,
            query_vector=query_vector
        )

        if focus in ["code", "all"]:
            gather_tasks.append(
                asyncio.create_task(self._code_gatherer.gather(base_context))
            )
            task_keys.append("code")

        if focus in ["docs", "all"]:
            gather_tasks.append(
                asyncio.create_task(self._docs_gatherer.gather(base_context))
            )
            task_keys.append("documentation")

        if focus in ["memories", "all"]:
            gather_tasks.append(
                asyncio.create_task(self._memory_gatherer.gather(base_context))
            )
            task_keys.append("memories")

        # Run all gather tasks in parallel
        if gather_tasks:
            results = await asyncio.gather(*gather_tasks, return_exceptions=True)
            for key, result in zip(task_keys, results):
                if isinstance(result, BaseException):
                    logger.error("Error gathering %s context: %s", key, result)
                    context[key] = []
                elif isinstance(result, list):
                    context[key] = result
                else:
                    # Should not happen, but handle gracefully
                    context[key] = []

        # Expand via relationships if depth allows and budget permits
        if depth in ["broad", "comprehensive"] and budget.remaining() > 500:
            graph_context = GatherContext(
                query=query,
                budget=budget,
                depth=depth,
                project_id=project_id,
                session_id=session_id,
                initial_context=context
            )
            context["relationships"] = await self._graph_gatherer.gather(graph_context)
        
        # Generate summary and suggestions
        summary = self._generate_summary(context, query)
        suggestions = self._generate_suggestions(context, query, budget)

        # Prepend project state warnings to suggestions (P0-1 fix)
        if project_state.get("warnings"):
            suggestions = project_state["warnings"] + suggestions
        
        # Count items
        items_included = self._count_items(context)
        items_available = items_included
        
        token_usage = {
            "estimated_tokens": budget.used_tokens,
            "max_tokens": budget.max_tokens,
            "remaining_tokens": budget.remaining(),
            "usage_percentage": budget.usage_percentage(),
            "items_included": items_included,
            "items_available": items_available
        }
        
        # Emit context.building_completed event
        if self.event_system:
            await self.event_system.emit(
                "context.building_completed",
                source="ContextBuilder",
                status=EventStatus.COMPLETED,
                session_id=session_id,
                project_id=project_id,
                query=query[:100],  # Truncate long queries
                focus=focus,
                depth=depth,
                items_included=items_included,
                estimated_tokens=budget.used_tokens,
                max_tokens=budget.max_tokens,
                usage_percentage=budget.usage_percentage()
            )
        
        return {
            "context": context,
            "summary": summary,
            "suggestions": suggestions,
            "token_usage": token_usage
        }

    async def build_context_overview(
        self,
        query: str,
        session_id: str,
        max_tokens: int = 2000
    ) -> Dict[str, Any]:
        """Build high-level context overview for progressive discovery.
        
        Returns summaries and counts by category without full content,
        allowing agents to decide what to explore in detail.
        
        Args:
            query: Query to build overview for
            session_id: Session identifier
            max_tokens: Maximum tokens for overview
            
        Returns:
            Dictionary containing:
                - categories: Dict with counts and top items per category
                - summary: Overall summary
                - suggestions: Suggestions for drilling down
                - token_usage: Token usage statistics
        """
        logger.info("Building context overview for query='%s'", query)
        
        budget = TokenBudget(max_tokens=max_tokens)
        
        # Get session for project_id
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        project_id = session.project_id
        
        # Get counts and top items for each category
        categories = {}
        
        # Code overview
        code_overview = await self._get_category_overview(
            query, project_id, "code", budget, top_n=3
        )
        categories["code"] = code_overview
        
        # Documentation overview
        doc_overview = await self._get_category_overview(
            query, project_id, "documentation", budget, top_n=3
        )
        categories["documentation"] = doc_overview
        
        # Memory overview
        memory_overview = await self._get_memory_overview(
            query, session_id, budget, top_n=3
        )
        categories["memories"] = memory_overview
        
        # Generate summary
        summary = self._generate_overview_summary(categories, query)
        
        # Generate drill-down suggestions
        suggestions = self._generate_drilldown_suggestions(categories)
        
        return {
            "categories": categories,
            "summary": summary,
            "suggestions": suggestions,
            "token_usage": {
                "estimated_tokens": budget.used_tokens,
                "max_tokens": budget.max_tokens,
                "remaining_tokens": budget.remaining()
            }
        }
    
    async def expand_category(
        self,
        query: str,
        session_id: str,
        category: Literal["code", "documentation", "memories"],
        max_tokens: int = 3000,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Expand a specific category with full details.
        
        Used for progressive discovery - agent first gets overview,
        then expands specific categories of interest.
        
        Args:
            query: Original query
            session_id: Session identifier
            category: Category to expand
            max_tokens: Maximum tokens for expansion
            filters: Optional filters (e.g., language, file_path)
            
        Returns:
            Dictionary containing:
                - items: Full items for the category
                - summary: Category summary
                - token_usage: Token usage statistics
        """
        logger.info("Expanding category '%s' for query='%s'", category, query)
        
        budget = TokenBudget(max_tokens=max_tokens)
        
        # Get session for project_id
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        project_id = session.project_id
        
        # Update session state to track exploration
        if "exploration_path" not in session.context_state:
            session.context_state["exploration_path"] = []
        session.context_state["exploration_path"].append({
            "query": query,
            "category": category,
            "filters": filters
        })
        
        # Create gather context for comprehensive expansion
        gather_context = GatherContext(
            query=query,
            budget=budget,
            depth="comprehensive",  # Always use comprehensive for expansion
            project_id=project_id,
            session_id=session_id,
            include_overview=False
        )
        
        # Gather items using appropriate gatherer
        items: List[Dict[str, Any]] = []
        if category == "code":
            items = await self._code_gatherer.gather(gather_context)
        elif category == "documentation":
            items = await self._docs_gatherer.gather(gather_context)
        elif category == "memories":
            items = await self._memory_gatherer.gather(gather_context)
        
        # Apply additional filters if provided
        if filters:
            items = self._apply_filters(items, filters)
        
        summary = f"Found {len(items)} {category} items for '{query}'"
        
        return {
            "items": items,
            "category": category,
            "summary": summary,
            "token_usage": {
                "estimated_tokens": budget.used_tokens,
                "max_tokens": budget.max_tokens,
                "items_included": len(items)
            }
        }
    
    async def get_relationship_preview(
        self,
        entity_id: str,
        session_id: str,
        max_depth: int = 1
    ) -> Dict[str, Any]:
        """Get relationship preview without full entity details.
        
        Returns relationship types and counts, allowing agent to decide
        which relationships to explore in detail.
        
        Args:
            entity_id: Entity to get relationships for
            session_id: Session identifier
            max_depth: Maximum depth to preview
            
        Returns:
            Dictionary containing:
                - entity: Basic entity info
                - relationship_summary: Counts by type and direction
                - suggestions: Suggestions for exploration
        """
        logger.info("Getting relationship preview for entity=%s", entity_id)
        
        # Get session for project_id
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        project_id = session.project_id
        
        try:
            # Traverse relationships
            result = await self.search.traverse_relationships(
                entity_id=entity_id,
                direction="both",
                max_depth=max_depth,
                project_id=project_id,
                include_metadata=False
            )
            
            if not result.get("entity"):
                return {
                    "entity": None,
                    "relationship_summary": {},
                    "error": f"Entity {entity_id} not found"
                }
            
            # Summarize relationships by type and direction
            relationship_summary = {}
            for rel in result.get("relationships", []):
                rel_type = rel.get("type", "unknown")
                direction = rel.get("direction", "unknown")
                key = f"{rel_type}_{direction}"
                
                if key not in relationship_summary:
                    relationship_summary[key] = {
                        "type": rel_type,
                        "direction": direction,
                        "count": 0,
                        "example_targets": []
                    }
                
                relationship_summary[key]["count"] += 1
                
                # Add example target (up to 3)
                if len(relationship_summary[key]["example_targets"]) < 3:
                    target_name = rel.get("target_name", rel.get("source_name", ""))
                    if target_name:
                        relationship_summary[key]["example_targets"].append(target_name)
            
            # Generate suggestions
            suggestions = []
            for key, info in relationship_summary.items():
                if info["count"] > 0:
                    suggestions.append(
                        f"Explore {info['count']} {info['type']} "
                        f"({info['direction']}) relationships"
                    )
            
            return {
                "entity": {
                    "id": result["entity"]["id"],
                    "name": result["entity"]["name"],
                    "type": result["entity"]["type"]
                },
                "relationship_summary": list(relationship_summary.values()),
                "total_relationships": len(result.get("relationships", [])),
                "suggestions": suggestions
            }
            
        except Exception as e:
            logger.error("Error getting relationship preview: %s", e)
            return {
                "entity": None,
                "relationship_summary": {},
                "error": str(e)
            }
    
    async def _get_category_overview(
        self,
        query: str,
        project_id: str,
        category: str,
        budget: TokenBudget,
        top_n: int = 3
    ) -> Dict[str, Any]:
        """Get overview for a category (code or documentation).
        
        Args:
            query: Search query
            project_id: Project identifier
            category: Category type (code or documentation)
            budget: Token budget
            top_n: Number of top items to include
            
        Returns:
            Dictionary with count and top items
        """
        try:
            # Get query vector
            query_vector = await self.search.embedding_service.embed_async(query)
            
            # Search with higher limit to get accurate count
            results = await self.search.hybrid_search(
                query_vector=query_vector,
                query_fts=query,
                limit=self.config.mcp.query.traversal_limit,
                filters={"type": category},
                project_id=project_id
            )
            
            total_count = len(results) if isinstance(results, list) else 0

            # Get top N items with minimal info
            top_items = []
            if isinstance(results, list):
                for result in results[:top_n]:
                    item = {
                        "id": result.id,
                        "name": result.data.get("name", result.data.get("title", "Unknown")),
                        "relevance_score": max(0.0, 1.0 - (result.distance if result.distance is not None else 1.0)),
                        "location": result.data.get("file_path", "")
                    }

                    # Add to budget
                    item_text = f"{item['name']} {item['location']}"
                    if budget.can_add(item_text):
                        budget.add(item_text)
                        top_items.append(item)
            
            return {
                "total_count": total_count,
                "top_items": top_items,
                "has_more": total_count > top_n
            }
            
        except Exception as e:
            logger.error("Error getting %s overview: %s", category, e)
            return {
                "total_count": 0,
                "top_items": [],
                "has_more": False
            }
    
    async def _get_memory_overview(
        self,
        query: str,
        session_id: str,
        budget: TokenBudget,
        top_n: int = 3
    ) -> Dict[str, Any]:
        """Get overview for memories.
        
        Args:
            query: Search query
            session_id: Session identifier
            budget: Token budget
            top_n: Number of top items to include
            
        Returns:
            Dictionary with count and top items
        """
        try:
            # Retrieve memories - create a context for the query
            from agent_vault.memory.models import MemoryContext
            mem_context = MemoryContext(
                agent_id="context_builder",
                session_id=session_id,
                conversation_id=session_id,
                project_id=None  # Not available in this method scope
            )
            memories = await self.memory.retrieve(
                query=query,
                context=mem_context,
                limit=self.config.mcp.query.tree_limit,
                strategy="adaptive"
            )

            results_list = memories.get("results", []) if isinstance(memories, dict) else memories
            total_count = len(results_list)

            # Get top N items with minimal info
            top_items = []
            for result in results_list[:top_n]:
                item = {
                    "id": result.item.id,
                    "summary": result.item.summary[:100] if result.item.summary else "",
                    "relevance_score": result.relevance_score,
                    "importance": result.item.importance
                }
                
                # Add to budget
                item_text = str(item["summary"])
                if budget.can_add(item_text):
                    budget.add(item_text)
                    top_items.append(item)
            
            return {
                "total_count": total_count,
                "top_items": top_items,
                "has_more": total_count > top_n
            }
            
        except Exception as e:
            logger.error("Error getting memory overview: %s", e)
            return {
                "total_count": 0,
                "top_items": [],
                "has_more": False
            }
    
    def _generate_overview_summary(
        self,
        categories: Dict[str, Any],
        query: str
    ) -> str:
        """Generate summary for context overview.
        
        Args:
            categories: Category overviews
            query: Original query
            
        Returns:
            Summary string
        """
        parts = []
        
        for cat_name, cat_data in categories.items():
            count = cat_data.get("total_count", 0)
            if count > 0:
                parts.append(f"{count} {cat_name}")
        
        if not parts:
            return f"No results found for '{query}'"
        
        return f"Found {', '.join(parts)} matching '{query}'. Use expand_category to see details."
    
    def _generate_drilldown_suggestions(
        self,
        categories: Dict[str, Any]
    ) -> List[str]:
        """Generate suggestions for drilling down into categories.
        
        Args:
            categories: Category overviews
            
        Returns:
            List of suggestion strings
        """
        suggestions = []
        
        for cat_name, cat_data in categories.items():
            count = cat_data.get("total_count", 0)
            if count > 0:
                suggestions.append(
                    f"Use expand_category(category='{cat_name}') to see all {count} {cat_name} items"
                )
        
        return suggestions
    
    def _apply_filters(
        self,
        items: List[Dict[str, Any]],
        filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Apply additional filters to items.
        
        Args:
            items: Items to filter
            filters: Filter criteria
            
        Returns:
            Filtered items
        """
        filtered = []
        
        for item in items:
            # Check each filter
            matches = True
            for key, value in filters.items():
                item_value = item.get(key) or item.get("metadata", {}).get(key)
                if item_value != value:
                    matches = False
                    break
            
            if matches:
                filtered.append(item)
        
        return filtered
    
    def _generate_summary(
        self,
        context: Dict[str, Any],
        query: str
    ) -> str:
        """Generate overall context summary.
        
        Args:
            context: Assembled context
            query: Original query
            
        Returns:
            Summary string
        """
        code_count = len(context.get("code", []))
        doc_count = len(context.get("documentation", []))
        memory_count = len(context.get("memories", []))
        relationship_count = len(context.get("relationships", []))
        
        parts = []
        if code_count > 0:
            parts.append(f"{code_count} code item{'s' if code_count != 1 else ''}")
        if doc_count > 0:
            parts.append(f"{doc_count} documentation item{'s' if doc_count != 1 else ''}")
        if memory_count > 0:
            parts.append(f"{memory_count} memor{'ies' if memory_count != 1 else 'y'}")
        if relationship_count > 0:
            parts.append(f"{relationship_count} relationship{'s' if relationship_count != 1 else ''}")
        
        if not parts:
            return f"No relevant context found for '{query}'"
        
        return f"Found {', '.join(parts)} relevant to '{query}'"
    
    def _generate_suggestions(
        self,
        context: Dict[str, Any],
        query: str,
        budget: TokenBudget
    ) -> List[str]:
        """Generate suggestions for refinement.
        
        Args:
            context: Assembled context
            query: Original query
            budget: Token budget
            
        Returns:
            List of suggestion strings
        """
        suggestions = []
        
        # Check if budget was exceeded
        if budget.usage_percentage() > 90:
            suggestions.append(
                "Context is near token limit. Consider using more focused query "
                "or increasing max_tokens."
            )
        
        # Check if any category is empty
        code_count = len(context.get("code", []))
        doc_count = len(context.get("documentation", []))
        memory_count = len(context.get("memories", []))
        
        if code_count == 0 and doc_count > 0:
            suggestions.append(
                "No code found. Try focus='code' to search only code."
            )
        
        if doc_count == 0 and code_count > 0:
            suggestions.append(
                "No documentation found. Try focus='docs' to search only documentation."
            )
        
        if memory_count == 0:
            suggestions.append(
                "No memories found. Save insights with 'save_memory' for future recall."
            )
        
        # Suggest deeper search if results are limited
        total_items = code_count + doc_count + memory_count
        if total_items < 5:
            suggestions.append(
                "Few results found. Try depth='comprehensive' for broader search."
            )
        
        return suggestions
    
    def _count_items(self, context: Dict[str, Any]) -> int:
        """Count total items in context.
        
        Args:
            context: Context dictionary
            
        Returns:
            Total number of items
        """
        return sum(
            len(context.get(key, []))
            for key in ["code", "documentation", "memories", "relationships"]
        )
