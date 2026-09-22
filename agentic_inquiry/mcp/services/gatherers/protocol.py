# agentic_inquiry/mcp/services/gatherers/protocol.py
"""Protocol definition for context gatherers."""
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from agentic_inquiry.mcp.services.token_optimizer import TokenBudget


@dataclass
class GatherContext:
    """Context parameters for gathering operations.

    Encapsulates all parameters that different gatherer implementations
    might need, providing a unified interface.
    """
    query: str
    budget: TokenBudget
    depth: str  # "focused", "broad", "comprehensive"
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    include_overview: bool = False
    query_vector: Optional[List[float]] = None
    # For graph expansion - initial context to expand from
    initial_context: Dict[str, List[Any]] = field(default_factory=dict)


@runtime_checkable
class ContextGathererProtocol(Protocol):
    """Protocol for context gathering strategies.

    Each gatherer is responsible for collecting a specific type of context
    (code, documentation, memories, relationships) based on the GatherContext.

    Implementations should:
    - Respect token budget constraints
    - Return consistently structured dictionaries
    - Handle errors gracefully (return empty list, don't raise)
    - Log operations at appropriate levels
    """

    @abstractmethod
    async def gather(self, context: GatherContext) -> List[Dict[str, Any]]:
        """Gather context items based on the provided parameters.

        Args:
            context: GatherContext with query, budget, depth and other params

        Returns:
            List of context item dictionaries with standardized structure:
            - id: Unique identifier
            - type: Item type (code, documentation, memory, relationship)
            - name: Display name
            - summary: Brief summary
            - relevance_score: Float 0-1
            - location: File path or session reference
            - snippet: Content snippet
            - metadata: Additional type-specific data
            - why_relevant: Explanation of relevance
        """
        ...

    @property
    @abstractmethod
    def gatherer_type(self) -> str:
        """Return the type of context this gatherer provides.

        Returns:
            One of: "code", "documentation", "memories", "relationships"
        """
        ...
