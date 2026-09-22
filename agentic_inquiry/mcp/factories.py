"""Service factory for creating MCP services with dependencies.

This module provides factory functions for creating MCP services with proper
dependency injection. It integrates with existing Agentic Inquiry services and
creates MCP-specific orchestration services.
"""

import asyncio
import logging
from typing import Dict, Any

from agentic_inquiry.config import Config
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.search.service import SearchService
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.memory.system import MemorySystem
from agentic_inquiry.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter
from agentic_inquiry.memory.adapters.inmemory_adapter import InMemoryMemoryAdapter
from agentic_inquiry.embeddings.registry import embedding_registry
from agentic_inquiry.embeddings.sentence_transformer import SentenceTransformerEmbedder

from agentic_inquiry.mcp.services.session_manager import SessionManager
from agentic_inquiry.mcp.services.context_builder import ContextBuilder
from agentic_inquiry.mcp.services.pattern_analyzer import PatternAnalyzer
from agentic_inquiry.mcp.services.temporal_analyzer import TemporalAnalyzer
from agentic_inquiry.mcp.services.token_optimizer import TokenOptimizer
from agentic_inquiry.mcp.services.entity_resolver import EntityResolver
from agentic_inquiry.mcp.services.impact_analyzer import ImpactAnalyzer
from agentic_inquiry.mcp.utils.cache import MCPCacheManager


logger = logging.getLogger(__name__)


async def create_mcp_services(config: Config, project_id: str) -> Dict[str, Any]:
    """Create all MCP services with dependencies.
    
    This factory function creates both core Agentic Inquiry services and
    MCP-specific orchestration services. It handles dependency injection
    and ensures all services are properly configured.
    
    Args:
        config: Configuration object
        project_id: Project identifier for service initialization
        
    Returns:
        Dictionary of service instances with keys:
        - config: Configuration object
        - server_config: Server configuration dictionary with:
            - default_project_id: Project ID used at server startup
            - server_name: Server name from configuration
            - server_version: Server version from configuration
            - server_description: Server description from configuration
        - Core services:
            - storage: StorageFacade instance
            - search_service: SearchService instance
            - indexing_pipeline: IndexingPipeline instance
            - memory_system: MemorySystem instance
            - event_system: EventSystem instance
            - embedding_service: EmbeddingService instance
        - MCP services:
            - session_manager: SessionManager instance
            - context_builder: ContextBuilder instance
            - pattern_analyzer: PatternAnalyzer instance
            - temporal_analyzer: TemporalAnalyzer instance
            - token_optimizer: TokenOptimizer instance
    
    Example:
        >>> from agentic_inquiry.config import Config
        >>> from agentic_inquiry.mcp.factories import create_mcp_services
        >>> 
        >>> config = Config.load()
        >>> services = create_mcp_services(config, "my_project")
        >>> 
        >>> # Access services
        >>> config = services["config"]
        >>> session_manager = services["session_manager"]
        >>> search_service = services["search_service"]
    
    Raises:
        Exception: If service creation fails
    """
    logger.info("Creating MCP services for project: %s", project_id)

    # Configure default embedder if not already configured
    if not embedding_registry._default_configured:
        # Use SentenceTransformerEmbedder with config settings for semantic search
        model_name = getattr(config.embeddings.sentence_transformer, 'model_name', 'all-MiniLM-L6-v2')
        ndims = getattr(config.embeddings, 'default_dimensions', 384)
        embedder = SentenceTransformerEmbedder(model_name=model_name)
        embedding_registry.configure_default_embedder(embedder, ndims=ndims)
        logger.info("Configured default SentenceTransformerEmbedder (model=%s, ndims=%d) for MCP services", model_name, ndims)

    # Initialize service references for cleanup on failure
    storage: StorageFacade | None = None
    event_system = None
    memory_system: MemorySystem | None = None
    maintenance_task: "asyncio.Task[None] | None" = None

    async def cleanup_on_failure() -> None:
        """Clean up all services that were successfully created."""
        if maintenance_task is not None:
            maintenance_task.cancel()
            try:
                await maintenance_task
            except asyncio.CancelledError:
                pass  # Expected: we just cancelled it.
            except Exception as cleanup_err:
                logger.debug(
                    "Maintenance task raised during shutdown: %s", cleanup_err
                )
        if memory_system is not None:
            try:
                await memory_system.shutdown()
            except Exception as cleanup_err:
                logger.debug("Error during memory_system cleanup: %s", cleanup_err)
        if event_system is not None:
            try:
                await event_system.stop()
            except Exception as cleanup_err:
                logger.debug("Error during event_system cleanup: %s", cleanup_err)
        if storage is not None:
            try:
                await storage.close()
            except Exception as cleanup_err:
                logger.debug("Error during storage cleanup: %s", cleanup_err)

    try:
        # Create core services (existing Agentic Inquiry components)
        logger.debug("Creating core services")

        # Create StorageFacade - unified storage interface
        # This creates and initializes LanceDB provider internally
        storage = await StorageFacade.from_config(config, project_id)
        backend_type = storage.get_backend_type()
        logger.debug("StorageFacade created and initialized for project %s (backend: %s)", project_id, backend_type)

        # Resolve provider capabilities once at startup.
        # All downstream consumers query this object instead of
        # checking embedding_strategy / backend_type strings.
        from agentic_inquiry.storage.capabilities import (
            get_capabilities_for_backend,
            ProviderCapabilities,
            EmbeddingStrategy,
        )
        capabilities = get_capabilities_for_backend(backend_type)

        # Override from explicit config if the user set embedding_strategy
        if config.storage.backends:
            for _name, backend_cfg in config.storage.backends.items():
                if backend_cfg.get("type") == backend_type:
                    explicit_strategy = backend_cfg.get("embedding_strategy")
                    explicit_model = backend_cfg.get("embedding_model")
                    explicit_dim = backend_cfg.get("embedding_dim")
                    if explicit_strategy or explicit_model or explicit_dim:
                        from dataclasses import replace as dc_replace
                        overrides: dict = {}
                        if explicit_strategy:
                            overrides["embedding_strategy"] = EmbeddingStrategy(explicit_strategy)
                        if explicit_model:
                            overrides["embedding_model"] = explicit_model
                        if explicit_dim:
                            overrides["embedding_dimensions"] = int(explicit_dim)
                        if overrides:
                            capabilities = dc_replace(capabilities, **overrides)
                            logger.info(
                                "Capabilities overridden from config: %s",
                                overrides,
                            )
                    break
        logger.info(
            "Resolved capabilities for %s: strategy=%s, dims=%d, model=%s",
            backend_type,
            capabilities.embedding_strategy.value,
            capabilities.embedding_dimensions,
            capabilities.embedding_model,
        )

        # Create event system with config and project_id
        from agentic_inquiry.events.system import EventSystem
        event_system = await EventSystem.from_config(config, project_id)
        # Initialize EventSystem (required before use)
        await event_system.start()
        logger.debug("EventSystem initialized successfully")

        # SearchService requires StorageFacade
        search_service = SearchService(
            storage=storage,
            config=config,
            event_system=event_system,
            project_id=project_id
        )
        
        # IndexingPipeline works with any backend via StorageFacade
        indexing_pipeline = IndexingPipeline(
            db_manager=storage,
            config=config,
            project_id=project_id,
            event_system=event_system,
            capabilities=capabilities,
        )

        # Configure global embedder based on storage backend capabilities
        # For server-side embedding backends (AlloyDB, CloudSQL), this registers
        # a NoOpEmbedder so tools pass raw query strings instead of local vectors.
        # Without this, find_similar/find_patterns generate 384-dim local vectors
        # that mismatch AlloyDB's 768-dim server-side embeddings.
        from agentic_inquiry.embeddings.factory import configure_embedder_for_backend
        configure_embedder_for_backend(config, quiet=True)

        # Create embedding service for memory system
        from agentic_inquiry.embeddings.service import EmbeddingService
        embedding_service = EmbeddingService(config=config)

        # Start loading embedding model in background (non-blocking)
        # Model will be ready by the time first query needs it
        embedding_service.start_background_warmup()

        # Create memory adapters based on storage backend type
        # LanceDB uses LanceDBMemoryAdapter, PostgreSQL uses PostgresMemoryAdapter,
        # other backends fall back to InMemoryMemoryAdapter.
        #
        # For backends with server-side embeddings (AlloyDB, RDS), the embedding
        # dimensions may differ from the default (384). Check the backend config
        # for an explicit embedding_dim before falling back to the default.
        # Use capabilities as the single source of truth for embedding dimensions
        embedding_dims = capabilities.embedding_dimensions
        logger.info(
            "Using embedding_dims=%d from capabilities (backend=%s)",
            embedding_dims, backend_type,
        )

        from agentic_inquiry.memory.protocols import MemoryStorageProtocol
        episodic_storage: MemoryStorageProtocol
        semantic_storage: MemoryStorageProtocol
        if backend_type == "lancedb":
            # LanceDB backend - use native adapter
            db_manager = storage.get_db_manager()
            episodic_storage = LanceDBMemoryAdapter(
                manager=db_manager,
                table_name="memory_episodic",
                embedding_dims=embedding_dims,
            )
            semantic_storage = LanceDBMemoryAdapter(
                manager=db_manager,
                table_name="memory_semantic",
                embedding_dims=embedding_dims,
            )
            logger.debug("Using LanceDBMemoryAdapter for memory storage")
        else:
            # Unknown backend - use in-memory adapter (no persistence)
            logger.warning(
                "Backend '%s' does not have a native memory adapter. "
                "Using InMemoryMemoryAdapter - memories will NOT be persisted!",
                backend_type,
            )
            episodic_storage = InMemoryMemoryAdapter(embedding_dims=embedding_dims)
            semantic_storage = InMemoryMemoryAdapter(embedding_dims=embedding_dims)

        memory_system = MemorySystem(
            config=config,
            embedding_service=embedding_service,
            event_system=event_system,
            episodic_storage=episodic_storage,
            semantic_storage=semantic_storage,
        )
        # Initialize memory system (required before use)
        await memory_system.initialize()
        
        logger.debug("Core services created successfully")
        
        # Create MCP-specific orchestration services
        logger.debug("Creating MCP orchestration services")

        # MCP services accept StorageFacade and internally extract LanceDBManager
        # for database operations via get_db_manager() (deprecated but functional).
        session_manager = SessionManager(
            db_manager=storage,
            config=config,
            event_system=event_system
        )

        entity_resolver = EntityResolver(
            db_manager=storage,
            config=config
        )

        impact_analyzer = ImpactAnalyzer(
            db_manager=storage,
            entity_resolver=entity_resolver,
            config=config
        )

        context_builder = ContextBuilder(
            search_service=search_service,
            memory_system=memory_system,
            db_manager=storage,
            session_manager=session_manager,
            config=config,
            event_system=event_system
        )

        pattern_analyzer = PatternAnalyzer(
            search_service=search_service,
            db_manager=storage,
            embedding_service=embedding_service
        )

        temporal_analyzer = TemporalAnalyzer(
            db_manager=storage,
            config=config
        )
        
        # Create token optimizer without config parameter
        token_optimizer = TokenOptimizer()
        
        # Create cache manager with 5 minute TTL (300 seconds)
        cache_manager = MCPCacheManager(ttl_seconds=300)
        
        # Health and performance tracking (kept; not part of the deleted executive package).
        from agentic_inquiry.metrics.health import HealthTracker
        from agentic_inquiry.metrics import get_metrics_tracker
        from agentic_inquiry.mcp.utils.performance import PerformanceMonitor

        metrics_tracker = get_metrics_tracker()
        health_tracker = HealthTracker(metrics_tracker=metrics_tracker)
        perf_monitor = PerformanceMonitor()

        # Background maintenance: periodically consolidate memory and run
        # storage compaction. Replaces the deleted executive/ "volition + loop"
        # vocabulary with a plain interval task.
        # Interval is hard-coded; if a future use case needs it tunable, add a
        # real config field rather than a getattr-with-default that silently
        # ignores typos.
        maintenance_interval = 60.0

        async def _periodic_maintenance() -> None:
            # Work first, then sleep — so a server restarted faster than the
            # interval still gets a maintenance pass.
            while True:
                if memory_system is not None:
                    try:
                        await memory_system.consolidate()
                    except Exception:
                        logger.exception("Periodic memory consolidation failed")
                if storage is not None and hasattr(storage, "run_maintenance"):
                    try:
                        await storage.run_maintenance()
                    except Exception:
                        logger.exception("Periodic storage maintenance failed")
                await asyncio.sleep(maintenance_interval)

        maintenance_task = asyncio.create_task(_periodic_maintenance())
        logger.info("Background maintenance task started (interval=%.0fs)", maintenance_interval)

        logger.debug("MCP orchestration services created successfully")

        # Assemble service dictionary
        services = {
            # Configuration
            "config": config,
            
            # Server configuration
            "server_config": {
                "default_project_id": project_id,
                "server_name": config.mcp.server.name,
                "server_version": config.mcp.server.version,
                "server_description": config.mcp.server.description,
            },
            
            # Provider capabilities (single source of truth)
            "capabilities": capabilities,

            # Core services
            "storage": storage,
            "search_service": search_service,
            "indexing_pipeline": indexing_pipeline,
            "memory_system": memory_system,
            "event_system": event_system,
            "embedding_service": embedding_service,
            
            # MCP services
            "session_manager": session_manager,
            "entity_resolver": entity_resolver,
            "impact_analyzer": impact_analyzer,
            "context_builder": context_builder,
            "pattern_analyzer": pattern_analyzer,
            "temporal_analyzer": temporal_analyzer,
            "token_optimizer": token_optimizer,
            "cache_manager": cache_manager,

            # Health and maintenance
            "health_tracker": health_tracker,
            "perf_monitor": perf_monitor,
            "maintenance_task": maintenance_task,
        }
        
        logger.info(
            "MCP services created successfully",
            extra={"service_count": len(services), "project_id": project_id}
        )
        
        return services
        
    except TypeError as e:
        # Clean up any services that were created before the failure
        await cleanup_on_failure()

        # Catch parameter mismatch errors and provide helpful information
        import inspect
        import traceback

        # Try to identify which service failed
        tb = traceback.extract_tb(e.__traceback__)
        failed_service = "unknown"
        failed_function = None
        
        for frame in reversed(tb):
            if "create_" in frame.name or frame.name in ["__init__", "SessionManager", "ContextBuilder", "PatternAnalyzer", "TemporalAnalyzer", "TokenOptimizer"]:
                failed_service = frame.name
                failed_function = frame.name
                break
        
        # Get signature information if possible
        signature_info = ""
        if failed_function:
            try:
                # Try to get the function/class that failed
                if failed_function == "SessionManager":
                    sig = inspect.signature(SessionManager.__init__)
                elif failed_function == "ContextBuilder":
                    sig = inspect.signature(ContextBuilder.__init__)
                elif failed_function == "PatternAnalyzer":
                    sig = inspect.signature(PatternAnalyzer.__init__)
                elif failed_function == "TemporalAnalyzer":
                    sig = inspect.signature(TemporalAnalyzer.__init__)
                elif failed_function == "TokenOptimizer":
                    sig = inspect.signature(TokenOptimizer.__init__)
                else:
                    sig = None
                
                if sig:
                    params = [p for p in sig.parameters.keys() if p != 'self']
                    signature_info = f"\nExpected parameters: {', '.join(params)}"
            except Exception as sig_err:
                # S5-002: Log signature inspection failure (non-critical)
                logger.debug("Could not inspect signature of %s: %s", failed_service, sig_err)
        
        logger.error(
            "Failed to create MCP services due to parameter mismatch in %s: %s%s",
            failed_service,
            str(e),
            signature_info,
            exc_info=True,
            extra={
                "failed_service": failed_service,
                "error_type": "TypeError",
                "error_message": str(e)
            }
        )
        
        raise TypeError(
            f"Service initialization failed for {failed_service}: {str(e)}{signature_info}\n\n"
            f"This usually indicates a parameter mismatch. Check that:\n"
            f"1. All required parameters are provided\n"
            f"2. Parameter names match the constructor signature\n"
            f"3. Parameter types are correct\n\n"
            f"See the service class definition for the correct signature."
        ) from e
        
    except Exception as e:
        # Clean up any services that were created before the failure
        await cleanup_on_failure()

        logger.error(
            "Failed to create MCP services: %s",
            str(e),
            exc_info=True,
            extra={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "project_id": project_id
            }
        )
        raise


__all__ = ["create_mcp_services"]
