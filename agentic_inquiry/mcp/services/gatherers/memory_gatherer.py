# agentic_inquiry/mcp/services/gatherers/memory_gatherer.py
"""Memory context gatherer implementation."""
import logging
from typing import Any, Dict, List

from agentic_inquiry.memory.system import MemorySystem
from agentic_inquiry.memory.models import MemoryContext, RetrievalResult
from agentic_inquiry.mcp.services.token_optimizer import TokenOptimizer
from .protocol import ContextGathererProtocol, GatherContext

logger = logging.getLogger(__name__)


class MemoryGatherer(ContextGathererProtocol):
    """Gathers context from the memory system.

    Retrieves relevant memories based on query and session context,
    converting them to standardized context items.
    """

    def __init__(
        self,
        memory_system: MemorySystem,
        token_optimizer: TokenOptimizer
    ) -> None:
        """Initialize memory gatherer.

        Args:
            memory_system: Memory system for retrieving memories
            token_optimizer: Token optimizer for creating snippets
        """
        self.memory = memory_system
        self.token_optimizer = token_optimizer

    @property
    def gatherer_type(self) -> str:
        """Return gatherer type."""
        return "memories"

    async def gather(self, context: GatherContext) -> List[Dict[str, Any]]:
        """Gather relevant memories.

        Args:
            context: Gather context with query, budget, depth, etc.

        Returns:
            List of memory context items
        """
        if not context.session_id:
            logger.warning("No session_id provided for memory gathering")
            return []

        # Determine limit based on depth
        limit_map = {"focused": 5, "broad": 8, "comprehensive": 15}
        limit = limit_map.get(context.depth, 8)

        logger.info(
            "Retrieving memories: query=%s, session_id=%s, limit=%s",
            context.query, context.session_id, limit
        )

        # Check memory system availability
        if self.memory is None:
            logger.warning("Memory system not available, skipping memory retrieval")
            return []

        try:
            # Create memory context for retrieval
            memory_context = MemoryContext(
                agent_id="mcp_user",  # Must match agent_id used in save_memory tool
                session_id=context.session_id,
                conversation_id=context.session_id,  # Use session_id as conversation_id
                project_id=context.project_id
            )

            # Retrieve memories using memory system
            retrieval_results = await self.memory.retrieve(
                query=context.query,
                context=memory_context,
                limit=limit,
                strategy="adaptive"
            )

            results_list = []
            if isinstance(retrieval_results, dict):
                results_list = retrieval_results.get("results", [])
            else:
                results_list = retrieval_results

            logger.info("Retrieved %s memories", len(results_list))

            # Convert retrieval results to dict format
            memories: List[Dict[str, Any]] = []
            for result in results_list:
                if not isinstance(result, RetrievalResult):
                    logger.warning("Skipping non-RetrievalResult item in memory gatherer: %s", result)
                    continue
                
                memory_dict = {
                    "id": result.item.id if hasattr(result.item, 'id') else "",
                    "summary": result.item.summary if hasattr(result.item, 'summary') else "",
                    "content": result.item.content if hasattr(result.item, 'content') else "",
                    "relevance_score": result.relevance_score if hasattr(result, 'relevance_score') else 0.0,
                    "importance": result.item.importance if hasattr(result.item, 'importance') else 0.5,
                    "created_at": result.item.created_at.isoformat() if hasattr(result.item, 'created_at') and result.item.created_at else "",
                    "tags": result.item.metadata.get('tags', []) if hasattr(result.item, 'metadata') else []
                }
                memories.append(memory_dict)

            # Convert to context items and fit into budget
            memory_items: List[Dict[str, Any]] = []
            for memory in memories:
                item = self._memory_to_context_item(memory, context.session_id)

                # Check if we can add this item
                item_text = f"{item['summary']} {item['snippet']}"
                if context.budget.can_add(item_text):
                    context.budget.add(item_text)
                    memory_items.append(item)
                else:
                    logger.debug("Skipping memory item %s - budget exceeded", item['id'])
                    break

            logger.info("Converted to %s memory context items", len(memory_items))
            return memory_items

        except Exception as e:
            logger.error("Error gathering memory context: %s", e, exc_info=True)
            return []

    def _memory_to_context_item(
        self,
        memory: Dict[str, Any],
        session_id: str
    ) -> Dict[str, Any]:
        """Convert memory to context item dictionary.

        Args:
            memory: Memory dictionary
            session_id: Session identifier

        Returns:
            Context item dictionary
        """
        # Convert importance float to string label
        importance_value = memory.get("importance", 0.5)
        if importance_value >= 0.9:
            importance_label = "critical"
        elif importance_value >= 0.7:
            importance_label = "high"
        elif importance_value >= 0.4:
            importance_label = "medium"
        else:
            importance_label = "low"

        # Create snippet from content
        content = memory.get("content", "")
        snippet = self.token_optimizer.create_snippet(content, max_tokens=125)

        relevance_score = memory.get("relevance_score", 0.0)

        return {
            "id": memory.get("id", ""),
            "type": "memory",
            "name": memory.get("summary", "Memory")[:100],
            "summary": memory.get("summary", ""),
            "relevance_score": relevance_score,
            "location": f"session:{session_id}",
            "snippet": snippet,
            "metadata": {
                "importance": importance_label,
                "created": memory.get("created_at", ""),
                "tags": memory.get("tags", [])
            },
            "why_relevant": f"Memory from session with relevance {relevance_score:.2f}"
        }
