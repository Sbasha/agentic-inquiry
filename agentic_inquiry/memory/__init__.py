"""
Memory System for Agentic Inquiry.

Provides three-tier memory architecture for AI agents:
- Working Memory: High-speed session-specific cache
- Episodic Memory: Time-series event log
- Semantic Memory: Abstract knowledge graph

Example Usage:
    >>> from agentic_inquiry.memory import MemorySystem, MemoryContext, MemoryTier
    >>> from agentic_inquiry.config import Config
    >>> from agentic_inquiry.embeddings import EmbeddingService
    >>> 
    >>> # Initialize the memory system
    >>> config = Config.load()
    >>> embedding_service = EmbeddingService(config)
    >>> memory_system = MemorySystem(config=config, embedding_service=embedding_service)
    >>> await memory_system.initialize()
    >>> 
    >>> # Create a context for an agent
    >>> context = MemoryContext(
    ...     agent_id="assistant_001",
    ...     session_id="session_xyz",
    ...     conversation_id="conv_abc123"
    ... )
    >>> 
    >>> # Store a memory
    >>> memory_item = await memory_system.store(
    ...     content="User prefers Python for data analysis",
    ...     context=context,
    ...     importance=0.9
    ... )
    >>> 
    >>> # Retrieve memories
    >>> results = await memory_system.retrieve(
    ...     query="programming preferences",
    ...     context=context,
    ...     limit=10
    ... )
"""

from agentic_inquiry.memory.adapters import LanceDBMemoryAdapter
from agentic_inquiry.memory.consolidation import ConsolidationEngine
from agentic_inquiry.memory.context import ContextManager
from agentic_inquiry.memory.layers.episodic import EpisodicMemory
from agentic_inquiry.memory.layers.semantic import SemanticMemory
from agentic_inquiry.memory.layers.working import WorkingMemory
from agentic_inquiry.memory.models import (
    AgentProfile,
    ConsolidationResult,
    ConsolidationStrategy,
    MemoryContext,
    MemoryItem,
    MemoryTier,
    Priority,
    RecallStrategy,
    RetrievalResult,
)
from agentic_inquiry.memory.protocols import (
    MemoryBulkCapability,
    MemoryQueryCapability,
    MemoryStorageProtocol,
    has_bulk_capability,
    has_query_capability,
)
from agentic_inquiry.memory.retrieval import RetrievalEngine
from agentic_inquiry.memory.system import MemorySystem

__all__ = [
    # Core system
    "MemorySystem",
    # Protocols (for backend abstraction)
    "MemoryStorageProtocol",
    "MemoryBulkCapability",
    "MemoryQueryCapability",
    "has_bulk_capability",
    "has_query_capability",
    # Adapters
    "LanceDBMemoryAdapter",
    # Data models
    "MemoryContext",
    "MemoryItem",
    "MemoryTier",
    "RetrievalResult",
    "ConsolidationResult",
    "AgentProfile",
    # Enums
    "Priority",
    "ConsolidationStrategy",
    "RecallStrategy",
    # Components (for advanced usage)
    "WorkingMemory",
    "EpisodicMemory",
    "SemanticMemory",
    "ConsolidationEngine",
    "RetrievalEngine",
    "ContextManager",
]
