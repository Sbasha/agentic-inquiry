"""
Memory System for Agent-Vault.

Provides three-tier memory architecture for AI agents:
- Working Memory: High-speed session-specific cache
- Episodic Memory: Time-series event log
- Semantic Memory: Abstract knowledge graph

Example Usage:
    >>> from agent_vault.memory import MemorySystem, MemoryContext, MemoryTier
    >>> from agent_vault.config import Config
    >>> from agent_vault.embeddings import EmbeddingService
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

from agent_vault.memory.adapters import LanceDBMemoryAdapter
from agent_vault.memory.consolidation import ConsolidationEngine
from agent_vault.memory.context import ContextManager
from agent_vault.memory.layers.episodic import EpisodicMemory
from agent_vault.memory.layers.semantic import SemanticMemory
from agent_vault.memory.layers.working import WorkingMemory
from agent_vault.memory.models import (
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
from agent_vault.memory.protocols import (
    MemoryBulkCapability,
    MemoryQueryCapability,
    MemoryStorageProtocol,
    has_bulk_capability,
    has_query_capability,
)
from agent_vault.memory.retrieval import RetrievalEngine
from agent_vault.memory.system import MemorySystem

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
