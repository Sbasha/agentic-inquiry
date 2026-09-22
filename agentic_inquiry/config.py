"""Configuration management for Agentic Inquiry.

This module provides a comprehensive configuration system with:
- YAML configuration file loading
- JSON schema validation
- Environment variable overrides
- Configuration priority: env vars > project root > defaults
- Automatic detection of agentic-inquiry.yaml in project root
"""

from __future__ import annotations

import json
import logging
import os
import threading
import warnings
from dataclasses import dataclass, field
from importlib.resources import files as _resource_files
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore[assignment]

try:
    from dacite import from_dict as dacite_from_dict
    from dacite import Config as DaciteConfig
except ImportError:
    dacite_from_dict = None  # type: ignore[assignment,misc]
    DaciteConfig = None  # type: ignore[assignment,misc]


from agentic_inquiry.connectors.base import (
    DEFAULT_BINARY_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
)
from agentic_inquiry.exceptions import ConfigurationError, StoragePathError


logger = logging.getLogger(__name__)


# Module-level lock for thread-safe configuration loading
_config_load_lock = threading.Lock()


# Legacy constant for backward compatibility
VECTOR_DIMENSION = 128


@dataclass
class LanceDBConfig:
    """LanceDB-specific storage configuration."""
    path: str = "lancedb"


@dataclass
class FileTrackerConfig:
    """FileTracker-specific storage configuration."""
    path: str = "file_tracker.db"


@dataclass
class DocumentCacheStorageConfig:
    """DocumentCache disk persistence configuration."""
    enabled: bool = False
    path: str = "document_cache"


@dataclass
class EventStoreConfig:
    """Event store storage configuration."""
    path: str = "events.db"


@dataclass
class BackendTimeoutsConfig:
    """Timeout configuration for backend operations.

    These timeouts control how long various operations will wait before
    timing out. All values are in seconds.

    Attributes:
        transaction_timeout: Connection acquisition timeout for transactions.
            Used by StorageFacade.transaction() when acquiring connections
            from the pool (default: 30.0 seconds).
        migration_lock_timeout: Timeout for acquiring advisory locks during
            schema migrations. Used by SchemaTracker.acquire_migration_lock()
            (default: 30 seconds).
    """
    transaction_timeout: float = 30.0
    migration_lock_timeout: int = 30


@dataclass
class EventsConfig:
    """Event system configuration.

    ``sampling_enabled`` is False by default because the sampler runs
    *unconditionally* on PROGRESS events when enabled — it drops roughly
    (N-1)/N of them regardless of queue depth, not just under
    backpressure. That's the right choice if your diagnostic noise is
    dominated by PROGRESS pings, but it's not a replacement for
    backpressure handling: a full queue at ``queue_max_size`` still
    drops events with only a warning log. Size the queue (or migrate
    events to Postgres) if you need retention under load.
    """
    enabled: bool = True
    queue_max_size: int = 1000
    batch_size: int = 100
    flush_interval_seconds: float = 1.0
    retention_days: int = 30
    cleanup_interval_hours: float = 24
    sampling_enabled: bool = False
    sampling_ratio: int = 10
    retry_max_attempts: int = 5
    retry_base_delay_seconds: float = 0.1


@dataclass
class StorageConfig:
    """Storage configuration with unified root and project isolation.

    This configuration supports:
    - Unified storage root for all persistent data
    - Project isolation via project_id (specified at runtime)
    - Component-specific path configuration
    - Backend selection for database components

    Note: project_id should be specified at runtime when creating components
    (IndexingPipeline, SearchService, etc.). The default_project_id field is
    provided for backward compatibility with single-project workflows.

    For multi-project workflows, pass project_id explicitly to component constructors.

    Backend selection:
    - backend: Vector storage backend (lancedb, qdrant, pinecone)
    - event_store_backend: Event store backend (sqlite, postgresql)
    - file_tracker_backend: File tracker backend (sqlite, postgresql)
    """

    root: str = "./.agentic-inquiry"
    default_project_id: Optional[str] = None  # Optional default for backward compatibility
    # DEPRECATED: legacy single-backend selector. No longer honoured by
    # ``StorageFacade.from_config`` — use ``backends`` + ``vector_backend`` /
    # ``graph_backend`` instead. Still read by ``registry._resolve_legacy_backend``
    # for non-facade callers; removal tracked in
    # https://github.com/sbasha/agentic_inquiry/issues/132
    backend: str = ""
    event_store_backend: str = "sqlite"  # Event store backend selection
    file_tracker_backend: str = "sqlite"  # File tracker backend selection
    lancedb: LanceDBConfig = field(default_factory=LanceDBConfig)
    file_tracker: FileTrackerConfig = field(default_factory=FileTrackerConfig)
    document_cache: DocumentCacheStorageConfig = field(default_factory=DocumentCacheStorageConfig)
    event_store: EventStoreConfig = field(default_factory=EventStoreConfig)

    # Named backends configuration (optional - for new multi-backend setup)
    # Maps backend name -> backend config dict with keys:
    #   - type: lancedb, postgresql, sqlite, spanner, or memory
    #   - connection_string: str (for postgresql)
    #   - database_path: str (for lancedb, sqlite)
    #   - pool_size: int (default 5)
    #   - max_overflow: int (default 10)
    #   - project_id, instance_id, database_id: str (for spanner)
    backends: Optional[Dict[str, Dict[str, Any]]] = None

    # Role assignments - reference backend names from 'backends' dict
    # These are only used when 'backends' is configured
    vector_backend: str = "default"
    graph_backend: str = "default"
    events_backend: str = "sqlite"
    file_tracker_backend_v2: str = "sqlite"  # _v2 to avoid conflict with existing field

    # Schema isolation prefix
    table_prefix: str = "agv_"

    # Backend operation timeouts
    backend_timeouts: BackendTimeoutsConfig = field(default_factory=BackendTimeoutsConfig)

    # Bulk operation batch size (for entity/relationship upserts)
    batch_size: int = 1000

    # Maximum query limit for "get all" operations (counting, relationship enumeration)
    max_query_limit: int = 100000

    def _resolve_path(self, subpath: str) -> Path:
        """Resolve a subpath relative to storage root.

        Handles both local paths and remote URIs (containing "://").
        For local paths, expands user home (~) and resolves to absolute path.
        For remote URIs, constructs the full URI path.

        Args:
            subpath: The relative path to resolve

        Returns:
            Resolved Path object (may be a URI wrapped in Path for remote)
        """
        if "://" in self.root:
            uri = f"{self.root.rstrip('/')}/{subpath}"
            return Path(uri)
        root = Path(self.root).expanduser().resolve()
        return root / subpath

    def get_lancedb_path(self) -> Path:
        """Get resolved LanceDB path.

        For remote URIs (containing "://"), returns the URI unchanged.
        For local paths, resolves to absolute path.

        Returns:
            Absolute path to LanceDB storage directory, or remote URI as Path
        """
        return self._resolve_path(self.lancedb.path)
    
    def get_file_tracker_path(self) -> Path:
        """Get resolved FileTracker database path.

        For remote URIs (containing "://"), returns the URI unchanged.
        For local paths, resolves to absolute path.

        Returns:
            Absolute path to FileTracker database file, or remote URI as Path
        """
        return self._resolve_path(self.file_tracker.path)
    
    def get_document_cache_path(self) -> Path:
        """Get resolved DocumentCache path.

        Returns:
            Absolute path to DocumentCache directory
        """
        return self._resolve_path(self.document_cache.path)
    
    def get_event_store_path(self) -> Path:
        """Get resolved event store path.

        For remote URIs (containing "://"), returns the URI unchanged.
        For local paths, resolves to absolute path.

        Returns:
            Absolute path to event store database file, or remote URI as Path
        """
        return self._resolve_path(self.event_store.path)
    
    def ensure_storage_directories(self) -> None:
        """Create storage directories if they don't exist.

        .. deprecated::
            This method is deprecated. Storage backends now handle their own
            directory creation during initialize(). Each backend owns its
            resource setup following the BackendLifecycle protocol.

        Only creates directories for local paths. Remote URIs (containing "://")
        are skipped as they don't require local directory creation.

        Raises:
            StoragePathError: If directories cannot be created due to permissions or other errors
        """
        warnings.warn(
            "ensure_storage_directories() is deprecated. "
            "Storage backends now handle their own directory creation during initialize(). "
            "This method will be removed in a future version.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Check if root path is remote
        if "://" in self.root:
            logger.debug("Skipping directory creation for remote root: %s", self.root)
            return
        
        try:
            # Create root
            root = Path(self.root).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            
            # Create LanceDB directory
            lancedb_path = self.get_lancedb_path()
            lancedb_path.mkdir(parents=True, exist_ok=True)
            
            # Create FileTracker parent directory
            file_tracker_path = self.get_file_tracker_path()
            file_tracker_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create DocumentCache directory if enabled
            if self.document_cache.enabled:
                cache_path = self.get_document_cache_path()
                cache_path.mkdir(parents=True, exist_ok=True)
                (cache_path / "entries").mkdir(exist_ok=True)
                
        except PermissionError as e:
            raise StoragePathError(
                f"Cannot create storage directories: Permission denied for {self.root}"
            ) from e
        except OSError as e:
            raise StoragePathError(
                f"Cannot create storage directories at {self.root}: {e}"
            ) from e


@dataclass
class DocumentCacheConfig:
    """Document cache configuration."""
    
    max_size: int = 1000
    ttl_seconds: int = 3600
    eviction_policy: str = "lru"


@dataclass
class CacheConfig:
    """Cache configuration."""
    
    document_cache: DocumentCacheConfig = field(default_factory=DocumentCacheConfig)


@dataclass
class HybridSearchConfig:
    """Hybrid search configuration.

    Supports multiple reranking strategies for hybrid search:
    - rrf: Reciprocal Rank Fusion with configurable k constant (default)
    - linear_combination: Weighted combination of vector and FTS scores
    - cross_encoder: Local cross-encoder model reranking
    - colbert: ColBERT-based reranking
    """

    vector_weight: float = 0.7
    fts_weight: float = 0.3
    rerank_by_graph: bool = True

    # Reranking strategy configuration
    reranker_type: str = "linear_combination"
    reranker_params: Dict[str, Any] = field(default_factory=dict)

    # RRF (Reciprocal Rank Fusion) configuration
    # The RRF formula is: score = Σ 1/(k + rank) where k controls rank smoothing.
    # Higher k values give more weight to lower-ranked results.
    # Default k=60 is research-backed (Cormack et al., SIGIR 2009).
    rrf_k: int = 60

    # Fallback and diagnostic options
    fallback_to_vector: bool = True
    log_diagnostics: bool = False

    # Overview boosting
    overview_boost_factor: float = 1.5


@dataclass
class GraphTimeoutsConfig:
    """Timeout configuration for graph operations.

    All timeouts are in milliseconds. Set to 0 to disable timeout.
    These can be overridden per-call by passing timeout_ms parameter.

    The tiered timeouts (small/medium/large) are selected based on the
    requested limit: small for limit <= 10, medium for limit <= 50,
    large for limit > 50.
    """

    # find_similar timeouts (tiered by limit)
    # AlloyDB network latency is ~600-2200ms, so defaults must accommodate remote backends
    find_similar_small_ms: int = 3000   # limit <= 10
    find_similar_medium_ms: int = 5000  # limit <= 50
    find_similar_large_ms: int = 8000   # limit > 50

    # understand_entity timeout
    understand_entity_ms: int = 5000

    # analyze_impact timeout (30s to accommodate large graphs with 50K+ relationships)
    analyze_impact_ms: int = 30000

    # find_patterns timeout
    find_patterns_ms: int = 10000

    # graph_traverse timeout
    graph_traverse_ms: int = 5000

    def get_find_similar_timeout(self, limit: int) -> int:
        """Get timeout for find_similar based on limit."""
        if limit <= 10:
            return self.find_similar_small_ms
        elif limit <= 50:
            return self.find_similar_medium_ms
        else:
            return self.find_similar_large_ms


@dataclass
class GraphSearchConfig:
    """Graph search configuration."""

    max_depth: int = 3
    relationship_types: List[str] = field(default_factory=lambda: [
        "calls", "imports", "contains", "references"
    ])
    timeouts: GraphTimeoutsConfig = field(default_factory=GraphTimeoutsConfig)


@dataclass
class DeduplicationConfig:
    """Search result deduplication configuration."""
    
    enabled: bool = True
    max_results_per_file: int = 1
    min_diversity_ratio: float = 0.7


@dataclass
class QuerySanitizationConfig:
    """Query sanitization configuration for FTS."""

    enabled: bool = True
    escape_special_chars: bool = True
    preserve_wildcards: bool = False


@dataclass
class SparseIndexConfig:
    """Sparse index detection configuration.

    Helps identify when the index has too few documents for reliable search results.
    When the index is sparse, search behavior can be adjusted to provide better results.
    """

    # Minimum chunks for index to be considered "ready"
    # Below this threshold, searches may return limited or unreliable results
    threshold: int = 50

    # Enable fallback search behavior when index is sparse
    # When enabled, uses more lenient search parameters for sparse indexes
    enable_fallback: bool = True


@dataclass
class SearchConfig:
    """Search configuration."""

    default_limit: int = 10
    max_limit: int = 100
    deduplication: DeduplicationConfig = field(default_factory=DeduplicationConfig)
    hybrid_search: HybridSearchConfig = field(default_factory=HybridSearchConfig)
    graph_search: GraphSearchConfig = field(default_factory=GraphSearchConfig)
    query_sanitization: QuerySanitizationConfig = field(default_factory=QuerySanitizationConfig)
    sparse_index: SparseIndexConfig = field(default_factory=SparseIndexConfig)


@dataclass
class SentenceTransformerConfig:
    """Sentence transformer embedding configuration."""
    
    model_name: str = "all-MiniLM-L6-v2"
    ndims: int = 384


@dataclass
class HashingConfig:
    """Hashing-based embedding configuration."""
    
    ndims: int = 128


@dataclass
class LocalModelConfig:
    """Local model embedding configuration."""
    
    model_path: str = "models/default-embedding-model"
    normalize: bool = True
    batch_size: int = 32
    ndims: int | None = None  # Auto-detected if None


@dataclass
class FastEmbedConfig:
    """FastEmbed embedding configuration."""

    model_name: str = "BAAI/bge-small-en-v1.5"
    cache_dir: Optional[str] = None
    threads: Optional[int] = None
    batch_size: int = 32
    parallel: Optional[int] = None


@dataclass
class EmbeddingsCacheConfig:
    """Content-hash LRU cache for local embedders.

    Indexing workloads frequently see duplicate embedding text (generated
    files, vendored deps copied across monorepos, license-header chunks,
    near-identical chunks across branches). ``CachingEmbedder`` hashes
    each input with SHA256 and skips the model forward pass on hits.
    Win scales with duplication — 0% on cleanroom repos, commonly
    20-30% on monorepos, >50% on branch-indexing runs.

    Disabled automatically for server-side (``NoOpEmbedder``) paths —
    AlloyDB / RDS compute embeddings in-database, so there's nothing
    to cache here.
    """

    enabled: bool = True

    # Cache capacity in unique entries. Vectors are stored as numpy
    # float32 arrays — at 384 dims that's ~1.5 KB per entry plus the
    # 64-byte SHA256 hex key plus OrderedDict overhead, so 10k entries
    # ≈ 15 MB resident. (Python ``list[float]`` would be ~8× larger;
    # the cache stores float32 internally and converts back to lists
    # on retrieval to keep the embedder contract.) Operators on
    # memory-constrained hosts can lower; giant monorepos with high
    # duplication can raise.
    max_entries: int = 10_000

    def __post_init__(self) -> None:
        """Validate at construction so misconfigured YAML fails loudly
        at ``Config.load()`` rather than deep inside ``CachingEmbedder``.

        JSON-schema validation also enforces ``minimum: 0`` on this
        field, but the schema check can be skipped (jsonschema not
        installed, ``skip_schema_validation=True`` flag). Dataclass
        ``__post_init__`` runs unconditionally, so it's the load-time
        guarantee.
        """
        if self.max_entries < 0:
            raise ConfigurationError(
                f"embeddings.cache.max_entries must be >= 0, "
                f"got {self.max_entries}. Set to 0 to disable caching "
                f"(equivalent to embeddings.cache.enabled=false)."
            )


@dataclass
class EmbeddingsConfig:
    """Embeddings configuration."""

    default_provider: str = "sentence_transformer"

    # Default embedding dimensions for all components
    default_dimensions: int = 384

    # Provider-specific configurations
    sentence_transformer: SentenceTransformerConfig = field(default_factory=SentenceTransformerConfig)
    hashing: HashingConfig = field(default_factory=HashingConfig)
    local_model: LocalModelConfig = field(default_factory=LocalModelConfig)
    fastembed: FastEmbedConfig = field(default_factory=FastEmbedConfig)
    cache: EmbeddingsCacheConfig = field(default_factory=EmbeddingsCacheConfig)


@dataclass
class SchemaMappingConfig:
    """Schema mapping configuration for indexing."""
    
    enabled: bool = True
    field_mappings: Dict[str, str] = field(default_factory=dict)


@dataclass
class SchemaValidationConfig:
    """Schema validation configuration for indexing."""
    
    enabled: bool = True
    strict_mode: bool = False
    cache_schemas: bool = True
    cache_ttl_seconds: int = 300


@dataclass
class IndexingTimeoutsConfig:
    """Timeout configuration for indexing operations."""

    total: int = 300  # Fixed timeout in seconds
    per_file: int = 5  # Seconds per file for dynamic timeout
    base: int = 60  # Base seconds for setup/flush


@dataclass
class IndexingConfig:
    """Indexing pipeline configuration."""

    timeouts: IndexingTimeoutsConfig = field(default_factory=IndexingTimeoutsConfig)
    schema_mapping: SchemaMappingConfig = field(default_factory=SchemaMappingConfig)
    schema_validation: SchemaValidationConfig = field(default_factory=SchemaValidationConfig)

    # Impact analysis settings (flattened from ImpactAnalysisConfig)
    impact_default_depth: int = 2
    impact_max_depth: int = 5
    impact_include_indirect: bool = True

    # Concurrency control. Caps the number of documents being processed
    # in-flight simultaneously (via ``asyncio.Semaphore`` in the pipeline).
    # 20 is intentionally mid-range — the yaml-example guidance calls
    # out 5-10 for small dev projects, 10-20 for CI/CD, 20-50 for
    # production. Historically we defaulted to 10 because embedding
    # was serial per-chunk inside each file's task and raising the
    # semaphore just pushed more files onto the same starved executor.
    # Post-PR #134, embedding is batched per-file and MPS-aware, so
    # the executor releases much faster and the next file in queue
    # actually benefits. Keeping the ceiling conservative at 20 — users
    # on tiny projects can lower, production users raise to 50.
    processing_semaphore_limit: int = 20

    # Periodic maintenance during indexing to prevent LanceDB storage bloat.
    # Set to 0 to disable periodic maintenance (only run at end).
    maintenance_interval_files: int = 50

    # Maximum chunk content size in characters. Oversized chunks are split
    # into sub-chunks at paragraph/line boundaries. 0 = no limit.
    # Default 50,000 chars provides a 40x safety margin under AlloyDB's 4MB
    # Vertex AI embedding limit.
    max_chunk_content_size: int = 50_000

    # Branch indexing settings (WS4)
    branch_max_age_days: int = 30
    branch_discovery_enabled: bool = True
    branch_default_exempt: bool = True

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not 1 <= self.processing_semaphore_limit <= 100:
            raise ConfigurationError(
                f"processing_semaphore_limit must be between 1 and 100, got {self.processing_semaphore_limit}. "
                f"Lower values reduce concurrency and memory usage, higher values increase throughput. "
                f"Recommended: 5-10 for development, 10-20 for CI/CD, 20-50 for production."
            )
        if self.max_chunk_content_size < 0:
            raise ConfigurationError(
                f"max_chunk_content_size must be >= 0 (0 = no limit), "
                f"got {self.max_chunk_content_size}"
            )
        if 0 < self.max_chunk_content_size < 100:
            raise ConfigurationError(
                f"max_chunk_content_size must be >= 100 when enabled, "
                f"got {self.max_chunk_content_size}"
            )
        if self.maintenance_interval_files < 0:
            raise ConfigurationError(
                f"maintenance_interval_files must be >= 0, got {self.maintenance_interval_files}. "
                f"Set to 0 to disable periodic maintenance during indexing."
            )


@dataclass
class ParserConfig:
    """Individual parser configuration."""

    enabled: bool = True
    priority: int = 0


@dataclass
class UnifiedCodeParserConfig(ParserConfig):
    """Unified code parser configuration."""

    enabled: bool = True
    priority: int = 100
    max_file_size: int = 10485760  # 10MB
    chunk_size: int = 1000
    chunk_overlap: int = 200


@dataclass
class FallbackTextParserConfig(ParserConfig):
    """Fallback text parser configuration."""

    enabled: bool = True
    priority: int = 0
    max_chunk_size: int = 1000
    chunk_overlap: int = 100


@dataclass
class ParsersConfig:
    """Parsers configuration."""

    unified_code: UnifiedCodeParserConfig = field(default_factory=UnifiedCodeParserConfig)
    salesforce_metadata: ParserConfig = field(
        default_factory=lambda: ParserConfig(enabled=True, priority=75)
    )
    document: ParserConfig = field(default_factory=lambda: ParserConfig(enabled=True, priority=50))
    fallback_text: FallbackTextParserConfig = field(default_factory=FallbackTextParserConfig)


@dataclass
class WorkingMemoryConfig:
    """Working memory configuration."""
    
    capacity: int = 20
    eviction_policy: str = "lru"


@dataclass
class EpisodicMemoryConfig:
    """Episodic memory configuration."""
    
    capacity: int = 1000
    table_name: str = "memory_episodic_medium"


@dataclass
class SemanticMemoryConfig:
    """Semantic memory configuration."""
    
    capacity: int = 500
    table_name: str = "memory_semantic_high"


@dataclass
class ConsolidationConfig:
    """Consolidation configuration."""
    
    enabled: bool = True
    interval_seconds: int = 300
    episodic_threshold: float = 0.8
    semantic_threshold: float = 0.9


@dataclass
class RetrievalConfig:
    """Retrieval configuration."""
    
    default_strategy: str = "adaptive"
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    cache_size: int = 1000
    ranking_weights: Dict[str, float] = field(default_factory=lambda: {
        "relevance": 0.5,
        "recency": 0.3,
        "importance": 0.2
    })


@dataclass
class SummaryConfig:
    """Summary configuration."""
    
    auto_threshold: int = 150


@dataclass
class MemoryConfig:
    """Memory system configuration."""
    
    working_memory: WorkingMemoryConfig = field(default_factory=WorkingMemoryConfig)
    episodic_memory: EpisodicMemoryConfig = field(default_factory=EpisodicMemoryConfig)
    semantic_memory: SemanticMemoryConfig = field(default_factory=SemanticMemoryConfig)
    consolidation: ConsolidationConfig = field(default_factory=ConsolidationConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    summary: SummaryConfig = field(default_factory=SummaryConfig)
    
    def get_tier_density(self, tier: str) -> str:
        """Get density tier for a memory tier (working/episodic/semantic).
        
        Args:
            tier: Memory tier name ('working', 'episodic', 'semantic')
            
        Returns:
            Component density key for use with EmbeddingsConfig
        """
        tier_map = {
            "working": "working_memory",
            "episodic": "episodic_memory",
            "semantic": "semantic_memory"
        }
        return tier_map.get(tier, "medium")


@dataclass
class FuzzyMatchingConfig:
    """Fuzzy matching configuration for entity resolution."""
    
    enabled: bool = True
    threshold: float = 0.8


@dataclass
class EntityResolutionConfig:
    """Entity resolution configuration."""
    
    case_insensitive: bool = True
    fuzzy_matching: FuzzyMatchingConfig = field(default_factory=FuzzyMatchingConfig)
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600





@dataclass
class ProgressConfig:
    """Configuration for progress indicators during long-running operations."""
    
    # Enable progress event emission
    enabled: bool = True
    
    # Emit progress events every N files during indexing
    emit_interval: int = 10
    
    # Minimum operation duration (seconds) to emit progress events
    min_duration: float = 5.0


@dataclass
class LoggingConfig:
    """Configuration for file-based logging."""
    
    # Directory for log files (workspace-relative or absolute)
    directory: str = "logs"
    
    # Main log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    level: str = "INFO"
    
    # Maximum size per log file in bytes (default: 10MB)
    max_bytes: int = 10 * 1024 * 1024
    
    # Number of backup files to keep
    backup_count: int = 5
    
    # Retention period in hours (default: 24 hours)
    retention_hours: int = 24
    
    # Per-service log levels (overrides main level)
    service_levels: Dict[str, str] = field(default_factory=dict)
    
    # Log format string
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Date format string
    date_format: str = "%Y-%m-%d %H:%M:%S"


@dataclass
class TokenBudgetConfig:
    """Token budget configuration for context building."""
    
    default_budget: int = 50000
    min_budget: int = 10000
    max_budget: int = 100000
    focus_allocations: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "code": {"code_weight": 0.7, "docs_weight": 0.3},
        "docs": {"code_weight": 0.3, "docs_weight": 0.7},
        "balanced": {"code_weight": 0.5, "docs_weight": 0.5},
    })


@dataclass
class ContextConfig:
    """Context building configuration."""
    
    token_budget: TokenBudgetConfig = field(default_factory=TokenBudgetConfig)


@dataclass
class MCPToolsConfig:
    """MCP tools configuration."""
    
    cognitive: Dict[str, bool] = field(default_factory=lambda: {"enabled": True})
    direct_access: Dict[str, bool] = field(default_factory=lambda: {"enabled": True})


@dataclass
class MCPServerConfig:
    """MCP server configuration."""
    
    name: str = "Agentic Inquiry"
    version: str = "1.0.0"
    description: str = "AI-powered code and knowledge search"


@dataclass
class MCPAPIConfig:
    """MCP API configuration."""
    
    enabled: bool = True
    host: str = "localhost"
    port: int = 8765
    cors: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "origins": ["*"]
    })
    auth: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": False,
        "api_key": None
    })


@dataclass
class MCPSessionConfig:
    """MCP session configuration."""
    
    ttl_hours: int = 48
    cleanup_interval_hours: int = 24


@dataclass
class MCPQueryConfig:
    """MCP query configuration."""

    default_limit: int = 1000
    max_limit: int = 10000
    # Categorized limits for different operation types
    batch_limit: int = 10000  # Large batch operations (temporal analysis, etc.)
    traversal_limit: int = 500  # Relationship traversal, entity queries (range: 100-2000)
    tree_limit: int = 50  # Tree building, clustering, analysis results
    batch_size: int = 100  # Batch size for query operations (range: 10-500)

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not 100 <= self.traversal_limit <= 2000:
            raise ConfigurationError(
                f"traversal_limit must be between 100 and 2000, got {self.traversal_limit}. "
                f"This controls the maximum number of entities traversed in relationship queries. "
                f"Lower values reduce memory usage and query time, higher values allow deeper exploration."
            )
        if not 10 <= self.batch_size <= 500:
            raise ConfigurationError(
                f"batch_size must be between 10 and 500, got {self.batch_size}. "
                f"This controls the number of items processed in each batch during query operations. "
                f"Lower values reduce memory usage, higher values may improve throughput."
            )


@dataclass
class MCPRelationshipsConfig:
    """MCP relationships configuration."""
    
    max_depth: int = 3
    max_per_node: int = 10000


@dataclass
class MCPTokensConfig:
    """MCP tokens configuration."""
    
    estimation_model: str = "cl100k_base"
    default_budget: int = 4000


@dataclass
class MCPDefaultsConfig:
    """MCP default behavior configuration."""
    
    search: Dict[str, Any] = field(default_factory=lambda: {
        "limit": 20,
        "hybrid_weight": 0.7,
        "min_relevance": 0.3
    })
    context: Dict[str, Any] = field(default_factory=lambda: {
        "max_tokens": 4000,
        "depth": "broad",
        "include_relationships": True
    })
    impact: Dict[str, Any] = field(default_factory=lambda: {
        "max_depth": 2,
        "include_tests": True
    })
    memory: Dict[str, Any] = field(default_factory=lambda: {
        "default_importance": "medium",
        "auto_tag": True
    })
    events: Dict[str, Any] = field(default_factory=lambda: {
        "retention_days": 7,
        "max_per_query": 50
    })
    patterns: Dict[str, Any] = field(default_factory=lambda: {
        "max_clusters": 5,
        "examples_per_cluster": 3
    })
    temporal: Dict[str, Any] = field(default_factory=lambda: {
        "default_time_range_days": 7
    })
    session_ttl_hours: int = 48  # Deprecated: use session.ttl_hours instead


@dataclass
class MCPBehaviorConfig:
    """MCP behavior flags configuration."""
    
    suggest_on_empty: bool = True
    include_alternatives: bool = True
    log_all_requests: bool = True
    track_performance: bool = True
    cache_responses: bool = True
    cache_ttl_seconds: int = 300


@dataclass
class MCPConfig:
    """MCP (Model Context Protocol) server configuration."""
    
    enabled: bool = True
    server: MCPServerConfig = field(default_factory=MCPServerConfig)
    tools: MCPToolsConfig = field(default_factory=MCPToolsConfig)
    api: MCPAPIConfig = field(default_factory=MCPAPIConfig)
    session: MCPSessionConfig = field(default_factory=MCPSessionConfig)
    query: MCPQueryConfig = field(default_factory=MCPQueryConfig)
    relationships: MCPRelationshipsConfig = field(default_factory=MCPRelationshipsConfig)
    tokens: MCPTokensConfig = field(default_factory=MCPTokensConfig)
    defaults: MCPDefaultsConfig = field(default_factory=MCPDefaultsConfig)
    behavior: MCPBehaviorConfig = field(default_factory=MCPBehaviorConfig)
    logging: Dict[str, Any] = field(default_factory=lambda: {
        "level": "INFO",
        "format": "json",
        "log_dir": "${HOME}/.agentic-inquiry/logs",
        "max_size_mb": 100,
        "retention_days": 30
    })


# DEFAULT_IGNORE_PATTERNS and DEFAULT_BINARY_EXTENSIONS are imported from
# agentic_inquiry.connectors.base - the canonical source for file discovery constants.
# They are re-exported here for backward compatibility.


@dataclass
class FileSystemConnectorConfig:
    """Local filesystem connector configuration."""

    enabled: bool = True
    root: Optional[str] = None  # Default to cwd if None
    ignore_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS))
    binary_extensions: Set[str] = field(default_factory=lambda: set(DEFAULT_BINARY_EXTENSIONS))
    change_detection_enabled: bool = True  # Enable FileTracker integration
    watch_enabled: bool = False  # Real-time file monitoring


@dataclass
class RemoteConnectorCacheConfig:
    """Content caching for remote connectors (S3, GCS, etc.)."""

    enabled: bool = True
    path: str = "connector_cache"  # Relative to storage.root
    max_size: int = 0  # Maximum cache size in bytes (0 = unlimited)


@dataclass
class ConnectorsConfig:
    """Connectors configuration for content source abstraction.

    Connectors provide a unified interface for accessing content from
    various sources (filesystem, S3, GCS, GitHub, etc.).
    """

    default_connector: str = "filesystem"  # Default connector type
    filesystem: FileSystemConnectorConfig = field(default_factory=FileSystemConnectorConfig)
    remote_cache: RemoteConnectorCacheConfig = field(default_factory=RemoteConnectorCacheConfig)
    # Future: s3, gcs, github, etc.


@dataclass
class MaintenanceConfig:
    """Automatic maintenance configuration for LanceDB storage optimization.

    Controls when and how database maintenance (compaction, version cleanup) is triggered.
    Maintenance reduces disk usage by removing old MVCC versions and compacting storage files.

    Trigger options:
    - "project.closed": Run maintenance when project session ends (default)
    - "indexing.completed": Run maintenance after indexing operations complete
    - "disabled": Never run automatic maintenance

    Cleanup retention controls how long to keep old versions (in minutes).
    Range: 5-1440 minutes (5 minutes to 24 hours)
    """

    trigger: str = "project.closed"  # Options: "project.closed", "indexing.completed", "disabled"
    cleanup_retention_minutes: int = 60  # Range: 5-1440
    enabled: bool = True

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Validate trigger enum
        valid_triggers = {"project.closed", "indexing.completed", "disabled"}
        if self.trigger not in valid_triggers:
            raise ConfigurationError(
                f"Invalid maintenance trigger: {self.trigger}. "
                f"Must be one of: {', '.join(sorted(valid_triggers))}"
            )

        # Validate retention range (5-1440 minutes)
        if not 5 <= self.cleanup_retention_minutes <= 1440:
            raise ConfigurationError(
                f"Invalid cleanup_retention_minutes: {self.cleanup_retention_minutes}. "
                f"Must be between 5 and 1440 (5 minutes to 24 hours). "
                f"Lower values reduce disk usage but may impact concurrent operations, "
                f"higher values provide more safety for rollback but use more disk space."
            )



@dataclass
class OnboardStalenessConfig:
    """Staleness detection thresholds for onboard documentation."""

    days_threshold: int = 7
    files_threshold: int = 10
    commits_threshold: int = 5


@dataclass
class OnboardArtifactStorageConfig:
    """Artifact storage configuration for onboard reports."""

    type: str = "local"  # "local" or "gcs"
    gcs_bucket: Optional[str] = None
    gcs_prefix: str = "onboard/"
    local_path: str = "test_results/onboard"

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        valid_types = {"local", "gcs"}
        if self.type not in valid_types:
            raise ConfigurationError(
                f"Invalid artifact storage type: {self.type}. "
                f"Must be one of: {', '.join(sorted(valid_types))}"
            )
        if self.type == "gcs" and not self.gcs_bucket:
            raise ConfigurationError(
                "gcs_bucket is required when artifact_storage.type is 'gcs'"
            )


@dataclass
class OnboardConfig:
    """Onboard documentation lifecycle configuration."""

    gate_enabled: bool = True
    staleness: OnboardStalenessConfig = field(default_factory=OnboardStalenessConfig)
    artifact_storage: OnboardArtifactStorageConfig = field(
        default_factory=OnboardArtifactStorageConfig
    )


@dataclass
class OverlayConfig:
    """Local change overlay configuration (WS3)."""

    enabled: bool = True
    max_lines_per_file: int = 100
    max_lines_total: int = 500


@dataclass
class Config:
    """Main configuration class for Agentic Inquiry.

    Configuration is loaded with the following priority (highest to lowest):
    1. Environment variables (AI_*)
    2. Project root configuration (agentic-inquiry.yaml)
    3. Default configuration (config/default.yaml)

    Example:
        >>> config = Config.load()
        >>> print(config.storage.root)
        './.agentic-inquiry'

        >>> # Load from custom path
        >>> config = Config.load("path/to/custom.yaml")

        >>> # Access configuration
        >>> lancedb_path = config.storage.get_lancedb_path()
        >>> cache_size = config.cache.document_cache.max_size
    """

    storage: StorageConfig = field(default_factory=StorageConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    indexing: IndexingConfig = field(default_factory=IndexingConfig)
    parsers: ParsersConfig = field(default_factory=ParsersConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    events: EventsConfig = field(default_factory=EventsConfig)
    entity_resolution: EntityResolutionConfig = field(default_factory=EntityResolutionConfig)
    progress: ProgressConfig = field(default_factory=ProgressConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    connectors: ConnectorsConfig = field(default_factory=ConnectorsConfig)
    maintenance: MaintenanceConfig = field(default_factory=MaintenanceConfig)
    onboard: OnboardConfig = field(default_factory=OnboardConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)

    @classmethod
    def load(
        cls,
        config_path: Optional[str] = None,
        skip_schema_validation: bool = False
    ) -> "Config":
        """Load configuration from file with environment variable overrides.

        Configuration loading priority:
        1. Environment variables (AI_*)
        2. Specified config_path or auto-detected agentic-inquiry.yaml
        3. Default configuration (config/default.yaml)

        Args:
            config_path: Optional path to configuration file. If None, automatically
                searches for agentic-inquiry.yaml in project root, then falls back to
                config/default.yaml.
            skip_schema_validation: If True, skip JSON schema validation. Useful for
                loading partial/overlay configs from environment directories.

        Returns:
            Config instance with loaded configuration

        Raises:
            ConfigurationError: If configuration is invalid or cannot be loaded
        """
        with _config_load_lock:
            if yaml is None:
                raise ConfigurationError(
                    "PyYAML is required for configuration loading. "
                    "Install it with: pip install pyyaml"
                )
            
            # Determine configuration file to load
            config_file = cls._find_config_file(config_path)
            logger.debug("Loading configuration from: %s", config_file)
            
            # Load configuration data
            try:
                with open(config_file, 'r') as f:
                    config_data = yaml.safe_load(f) or {}
            except Exception as e:
                raise ConfigurationError(f"Failed to load configuration from {config_file}: {e}")
            
            # Validate against schema if jsonschema is available
            if skip_schema_validation:
                logger.debug("Skipping schema validation (overlay config)")
            elif jsonschema is not None:
                cls._validate_config(config_data)
            else:
                logger.warning(
                    "jsonschema not installed, skipping configuration validation. "
                    "Install it with: pip install jsonschema"
                )
            
            # Expand environment variables in configuration data
            config_data = cls._expand_env_vars(config_data)
            
            # Apply environment variable overrides
            config_data = cls._apply_env_overrides(config_data)
            
            # Build Config instance from data
            try:
                config = cls._from_dict(config_data)
                
                # Validate configuration consistency
                config.validate()
                
                logger.info("Configuration loaded successfully from %s", config_file)
                return config
            except Exception as e:
                raise ConfigurationError(f"Failed to parse configuration: {e}")

    @classmethod
    def load_with_overlay(
        cls,
        overlay_path: str,
        base_config_path: Optional[str] = None,
    ) -> "Config":
        """Load configuration by merging an overlay on top of a base config.

        This method is designed for environment-specific configurations that only
        override certain settings while inheriting defaults for everything else.

        Args:
            overlay_path: Path to overlay configuration file (e.g., environment config)
            base_config_path: Path to base configuration. If None, uses the default
                configuration (config/default.yaml).

        Returns:
            Config instance with merged configuration

        Raises:
            ConfigurationError: If configuration is invalid or cannot be loaded

        Example:
            >>> # Load gcp-prod overlay on top of defaults
            >>> config = Config.load_with_overlay(
            ...     "~/.agentic-inquiry/envs/gcp-prod/config.yaml"
            ... )
        """
        with _config_load_lock:
            if yaml is None:
                raise ConfigurationError(
                    "PyYAML is required for configuration loading. "
                    "Install it with: pip install pyyaml"
                )

            # Load base configuration
            base_file = cls._find_config_file(base_config_path)
            logger.debug("Loading base configuration from: %s", base_file)

            try:
                with open(base_file, 'r') as f:
                    base_data = yaml.safe_load(f) or {}
            except Exception as e:
                raise ConfigurationError(f"Failed to load base configuration: {e}")

            # Load overlay configuration
            overlay_file = Path(overlay_path)
            if not overlay_file.exists():
                raise ConfigurationError(f"Overlay configuration not found: {overlay_path}")

            logger.debug("Loading overlay configuration from: %s", overlay_file)

            try:
                with open(overlay_file, 'r') as f:
                    overlay_data = yaml.safe_load(f) or {}
            except Exception as e:
                raise ConfigurationError(f"Failed to load overlay configuration: {e}")

            # Deep merge overlay onto base
            merged_data = cls._deep_merge(base_data, overlay_data)

            # Validate merged configuration
            if jsonschema is not None:
                cls._validate_config(merged_data)

            # Expand environment variables
            merged_data = cls._expand_env_vars(merged_data)

            # Apply environment variable overrides
            merged_data = cls._apply_env_overrides(merged_data)

            # Build Config instance
            try:
                config = cls._from_dict(merged_data)
                config.validate()
                logger.info(
                    "Configuration loaded with overlay: base=%s, overlay=%s",
                    base_file,
                    overlay_file
                )
                return config
            except Exception as e:
                raise ConfigurationError(f"Failed to parse merged configuration: {e}")

    @staticmethod
    def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries, with overlay values taking precedence.

        This performs a recursive merge where:
        - Dictionary values are merged recursively
        - List values from overlay replace base values
        - Scalar values from overlay replace base values
        - Keys only in base are preserved
        - Keys only in overlay are added

        Args:
            base: Base dictionary
            overlay: Overlay dictionary (values take precedence)

        Returns:
            New dictionary with merged values
        """
        result = base.copy()

        for key, overlay_value in overlay.items():
            if key in result and isinstance(result[key], dict) and isinstance(overlay_value, dict):
                # Recursively merge nested dictionaries
                result[key] = Config._deep_merge(result[key], overlay_value)
            else:
                # Overlay value replaces base value
                result[key] = overlay_value

        return result

    def validate_embedding_consistency(self) -> None:
        """Validate embedding dimension consistency across configuration.

        Checks that:
        1. The *active* provider's declared dimension matches
           ``default_dimensions``. Provider-specific so that one provider's
           dimension does not force users to also bump
           ``sentence_transformer.ndims`` to silence a check that
           doesn't apply to their deployment.
        2. Database dimensions match configuration (if database exists)

        Raises:
            ValueError: If embedding dimensions are inconsistent
        """
        default_dims = self.embeddings.default_dimensions
        provider = self.embeddings.default_provider

        # Skip dimension check for server-side embeddings (sentinel) —
        # the database supplies the dim, not any client-side config.
        if provider == "none":
            return

        # Resolve the *active* provider's declared dim. Providers that
        # auto-detect (fastembed reads model_out_channels at load time;
        # local_model reads metadata.dimensions when ``ndims`` is None)
        # report ``None`` here and the dim-check is skipped — there's
        # no static value to compare against until the model loads.
        #
        # Table-driven so this validator doesn't add another provider
        # equality-check literal to the codebase — RFC 0003's ship gate
        # keeps the dispatcher grep at exactly two hits (factory +
        # EmbeddingService); a validator counting as a third hit would
        # be misleading.
        provider_dim_map: dict[str, tuple[Optional[int], str]] = {
            "sentence_transformer": (
                self.embeddings.sentence_transformer.ndims,
                "sentence_transformer.ndims",
            ),
            "sentence_transformers": (
                self.embeddings.sentence_transformer.ndims,
                "sentence_transformer.ndims",
            ),
            "hashing": (self.embeddings.hashing.ndims, "hashing.ndims"),
            "local": (self.embeddings.local_model.ndims, "local_model.ndims"),
            "local_model": (
                self.embeddings.local_model.ndims,
                "local_model.ndims",
            ),
            "fastembed": (None, "default_provider"),
        }
        active_dim, provider_field = provider_dim_map.get(
            provider, (None, "default_provider")
        )

        if active_dim is not None and active_dim != default_dims:
            raise ValueError(
                f"Embedding dimension mismatch: "
                f"default_dimensions={default_dims}, "
                f"{provider_field}={active_dim} "
                f"(default_provider={provider!r}). "
                f"Update {provider_field} or default_dimensions so they "
                f"agree."
            )
        
        # Check database dimensions if database exists
        db_path = Path(self.storage.root) / self.storage.lancedb.path
        if db_path.exists():
            try:
                import lancedb
                db = lancedb.connect(str(db_path))
                
                # Check document_chunks table if it exists
                table_name = "document_chunks"  # Standard table name
                if table_name in db.table_names():
                    table = db.open_table(table_name)
                    schema = table.schema
                    
                    # Check if embedding field exists and get its dimension
                    if "embedding" in schema.names:
                        embedding_field = schema.field("embedding")
                        # LanceDB stores vectors as FixedSizeList
                        if hasattr(embedding_field.type, "list_size"):
                            db_dims = embedding_field.type.list_size
                            if db_dims != default_dims:
                                raise ValueError(
                                    f"Embedding dimensions changed. "
                                    f"Database: {db_dims}, Config: {default_dims}. "
                                    f"You need to re-index your data or use a different database. "
                                    f"To re-index, delete {db_path} and run indexing again."
                                )
            except ImportError:
                # LanceDB not installed, skip database validation
                pass
            except Exception as e:
                # Log warning but don't fail - database might be in use or corrupted
                logger.warning("Could not validate database dimensions: %s", e)

    def validate(self) -> None:
        """Validate configuration consistency and settings.
        
        Performs comprehensive validation including:
        - Embedding dimension consistency
        - Storage path validity
        - Cache configuration
        
        Raises:
            ConfigurationError: If any validation check fails
        """
        self.validate_embedding_consistency()
        self.validate_storage_paths()
        self.validate_cache_settings()
    
    def validate_storage_paths(self) -> None:
        """Validate storage paths are valid and accessible.
        
        Raises:
            ConfigurationError: If storage paths are invalid
        """
        from pathlib import Path
        
        # Validate storage root
        storage_root = Path(self.storage.root)
        
        # Skip validation for remote URIs
        if "://" in self.storage.root:
            logger.debug("Skipping path validation for remote storage root: %s", self.storage.root)
            return
        
        if not storage_root.is_absolute():
            # Make it absolute relative to current directory
            storage_root = Path.cwd() / storage_root
        
        # Check if parent directory exists (storage root will be created if needed)
        if not storage_root.parent.exists():
            raise ConfigurationError(
                f"Storage root parent directory does not exist: {storage_root.parent}. "
                f"Please create the parent directory or update storage.root in configuration."
            )
    
    def validate_cache_settings(self) -> None:
        """Validate cache configuration settings.
        
        Raises:
            ConfigurationError: If cache settings are invalid
        """
        # Validate document cache max_size
        if self.cache.document_cache.max_size <= 0:
            raise ConfigurationError(
                f"Invalid document cache max_size: {self.cache.document_cache.max_size}. "
                f"Must be greater than 0."
            )
        
        # Validate document cache ttl_seconds
        if self.cache.document_cache.ttl_seconds < 0:
            raise ConfigurationError(
                f"Invalid document cache TTL: {self.cache.document_cache.ttl_seconds}. "
                f"Must be greater than or equal to 0 (0 = no expiration)."
            )
        
        # Validate event store batch_size if events are enabled
        if self.events.enabled and self.events.batch_size <= 0:
            raise ConfigurationError(
                f"Invalid event store batch_size: {self.events.batch_size}. "
                f"Must be greater than 0."
            )

    

    
    @staticmethod
    def _packaged_config_file(filename: str) -> Optional[Path]:
        """Resolve a runtime config data file that ships with the package.

        Two layouts must both work:

        - **Installed wheel** - the file was mapped into the package namespace
          at build time (agentic_inquiry/config_defaults/<filename>) and is found
          via importlib.resources.
        - **Source checkout** (`uv run` from the clone) - that packaged copy
          does not exist, so fall back to the top-level config/ directory,
          resolved relative to this module.

        Returns the resolved path, or None if neither location has the file.
        """
        try:
            resource = (
                _resource_files("agentic_inquiry")
                .joinpath("config_defaults")
                .joinpath(filename)
            )
            if resource.is_file():
                return Path(str(resource))
        except (ModuleNotFoundError, FileNotFoundError, OSError):
            pass

        source_tree = Path(__file__).parent.parent / "config" / filename
        if source_tree.exists():
            return source_tree

        return None

    @classmethod
    def _find_config_file(cls, config_path: Optional[str] = None) -> Path:
        """Find configuration file to load.

        Priority:
        1. Specified config_path
        2. INQUIRY_CONFIG environment variable
        3. agentic-inquiry.yaml in project root
        4. config/default.yaml (package default)
        """
        if config_path is not None:
            path = Path(config_path)
            if not path.exists():
                raise ConfigurationError(f"Configuration file not found: {config_path}")
            return path

        # Check INQUIRY_CONFIG environment variable
        if ai_config := os.environ.get("INQUIRY_CONFIG"):
            path = Path(ai_config)
            if path.exists():
                logger.debug("Using configuration from INQUIRY_CONFIG: %s", path)
                return path
            else:
                logger.warning("INQUIRY_CONFIG points to non-existent file: %s", ai_config)

        # Try project root agentic-inquiry.yaml
        project_config = Path.cwd() / "agentic-inquiry.yaml"
        if project_config.exists():
            logger.debug("Found project configuration: %s", project_config)
            return project_config
        
        # Try global configuration (~/.agentic-inquiry/config.yaml)
        global_config = Path.home() / ".agentic-inquiry" / "config.yaml"
        if global_config.exists():
            logger.debug("Found global configuration: %s", global_config)
            return global_config
        
        # Fall back to the package default config. In an installed wheel this
        # ships inside the package (agentic_inquiry/config_defaults/) and is found
        # via importlib.resources; in a source checkout it lives in the
        # top-level config/ dir, which the resolver falls back to.
        default_config = cls._packaged_config_file("default.yaml")

        if default_config is None or not default_config.exists():
            searched = default_config or (
                Path(__file__).parent.parent / "config" / "default.yaml"
            )
            raise ConfigurationError(
                f"Default configuration not found (looked for {searched}). "
                "Package installation may be corrupted."
            )

        logger.debug("Using default configuration: %s", default_config)
        return default_config
    
    @classmethod
    def _validate_config(cls, config_data: Dict[str, Any]) -> None:
        """Validate configuration against JSON schema and business rules."""
        # Field-level validation for hybrid search weights (done first, before schema validation)
        search_config = config_data.get('search', {})
        hybrid_config = search_config.get('hybrid_search', {})
        vector_weight = hybrid_config.get('vector_weight', HybridSearchConfig().vector_weight)
        fts_weight = hybrid_config.get('fts_weight', HybridSearchConfig().fts_weight)
        
        # Validate that weights sum to 1.0 (within tolerance)
        weight_sum = vector_weight + fts_weight
        if abs(weight_sum - 1.0) > 0.001:
            raise ConfigurationError(
                f"Hybrid search weights must sum to 1.0 (within 0.001 tolerance), "
                f"got vector_weight={vector_weight} + fts_weight={fts_weight} = {weight_sum}"
            )
        
        # Storage configuration validation
        storage_config = config_data.get('storage', {})
        
        # Validate that paths don't contain null bytes
        root_path = storage_config.get('root', './.agentic-inquiry')
        if '\x00' in root_path:
            raise ConfigurationError(
                "storage.root contains null bytes, which are not allowed in file paths"
            )
        
        # Schema validation (if jsonschema is available). Resolved the same way
        # as the default config: packaged copy first, source checkout as fallback.
        schema_path = cls._packaged_config_file("config.schema.json")

        if schema_path is None or not schema_path.exists():
            logger.warning("Configuration schema not found, skipping schema validation")
            return

        try:
            import jsonschema
        except ImportError:
            logger.warning("jsonschema package not installed, skipping schema validation")
            return

        try:
            with open(schema_path, 'r') as f:
                base_schema = json.load(f)

            # Merge backend schemas into the base schema for extensible validation
            try:
                from agentic_inquiry.storage.schema_registry import get_merged_storage_schema
                schema = get_merged_storage_schema(base_schema)
                logger.debug("Using merged schema with backend extensions")
            except ImportError:
                # Fall back to base schema if schema_registry not available
                logger.debug("Schema registry not available, using base schema")
                schema = base_schema
            except Exception as e:
                # Log warning but continue with base schema
                logger.warning("Failed to merge backend schemas, using base schema: %s", e)
                schema = base_schema

            jsonschema.validate(config_data, schema)
            logger.debug("Configuration validated successfully against schema")
        except jsonschema.ValidationError as e:
            raise ConfigurationError(f"Configuration validation failed: {e.message}") from e
        except Exception as e:
            # For other exceptions (e.g., file read errors), raise ConfigurationError
            raise ConfigurationError(f"Failed to validate configuration: {e}") from e
    
    @classmethod
    def _build_valid_config_paths(cls) -> Dict[str, List[str]]:
        """Build a comprehensive map of valid configuration paths.
        
        This method is deprecated and kept for backward compatibility.
        The new convention-based approach in _apply_env_overrides handles
        environment variables automatically without requiring explicit mapping.
        
        Returns:
            Empty dictionary (no longer used)
        """
        # Convention-based approach no longer requires explicit mapping
        return {}


    @classmethod
    def _expand_env_vars(cls, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively expand environment variables in configuration data.

        Supports ${VAR_NAME} and ${VAR_NAME:-default_value} syntax.
        """
        import re

        # Regex for ${VAR_NAME} or ${VAR_NAME:-default}
        env_pattern = re.compile(r"\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")

        def _expand_value(value: Any) -> Any:
            if isinstance(value, str):
                def _replace(match):
                    var_name = match.group("var")
                    default = match.group("default")
                    return os.environ.get(var_name, default if default is not None else match.group(0))

                return env_pattern.sub(_replace, value)
            elif isinstance(value, dict):
                return {k: _expand_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [_expand_value(v) for v in value]
            return value

        return _expand_value(config_data)

    @classmethod
    def _apply_env_overrides(cls, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply environment variable overrides to configuration using convention-based lookup.

        Environment variables use the format: INQUIRY_SECTION_SUBSECTION_KEY
        The convention automatically maps AI_* variables to configuration paths:
        - INQUIRY_STORAGE_ROOT → config_data['storage']['root']
        - INQUIRY_CACHE_DOCUMENT_CACHE_MAX_SIZE → config_data['cache']['document_cache']['max_size']
        - INQUIRY_SEARCH_DEFAULT_LIMIT → config_data['search']['default_limit']
        - INQUIRY_STORAGE_DEFAULT_PROJECT_ID → config_data['storage']['default_project_id']
        - INQUIRY_STORAGE_FILE_TRACKER_PATH → config_data['storage']['file_tracker']['path']

        Examples:
            INQUIRY_STORAGE_ROOT=./.agentic-inquiry
            INQUIRY_STORAGE_DEFAULT_PROJECT_ID=my_project
            INQUIRY_STORAGE_LANCEDB_PATH=lancedb
            INQUIRY_CACHE_DOCUMENT_CACHE_MAX_SIZE=2000
            INQUIRY_SEARCH_DEFAULT_LIMIT=20
            INQUIRY_EMBEDDINGS_DEFAULT_DIMENSIONS=384

        Special cases:
            - INQUIRY_LOGGING_SERVICE_LEVELS_<SERVICE>=<LEVEL> for per-service log levels
            - INQUIRY_MAINTENANCE_RETENTION_MINUTES → maintenance.cleanup_retention_minutes
            - INQUIRY_TRAVERSAL_LIMIT → mcp.query.traversal_limit
            - INQUIRY_BATCH_SIZE → mcp.query.batch_size

        Note: For multi-project workflows, pass project_id explicitly to component
        constructors rather than using default_project_id in configuration.
        """
        env_prefix = "INQUIRY_"

        # Special mappings for env vars that don't follow the standard convention
        special_mappings = {
            'INQUIRY_MAINTENANCE_RETENTION_MINUTES': ['maintenance', 'cleanup_retention_minutes'],
            'INQUIRY_TRAVERSAL_LIMIT': ['mcp', 'query', 'traversal_limit'],
            'INQUIRY_BATCH_SIZE': ['mcp', 'query', 'batch_size'],
        }

        applied_count = 0
        ignored_count = 0
        
        # Define valid sections
        valid_sections = {
            'storage', 'cache', 'search', 'embeddings', 'parsers', 'memory',
            'events', 'logging', 'indexing', 'mcp', 'context', 'entity_resolution',
            'progress', 'connectors', 'maintenance', 'onboard'
        }
        
        # Handle service_levels separately (INQUIRY_LOGGING_SERVICE_LEVELS_<SERVICE>=<LEVEL>)
        service_levels_prefix = "INQUIRY_LOGGING_SERVICE_LEVELS_"
        
        for env_key, env_value in os.environ.items():
            if not env_key.startswith(env_prefix):
                continue

            # Handle service levels special case
            if env_key.startswith(service_levels_prefix):
                service_name = env_key[len(service_levels_prefix):].lower()

                # Ensure logging section exists
                if 'logging' not in config_data:
                    config_data['logging'] = {}
                if 'service_levels' not in config_data['logging']:
                    config_data['logging']['service_levels'] = {}

                # Set the service level
                config_data['logging']['service_levels'][service_name] = env_value
                applied_count += 1
                logger.debug("Applied environment override: %s=%s", env_key, env_value)
                continue

            # Handle special mappings that don't follow standard convention
            if env_key in special_mappings:
                try:
                    converted_value = cls._convert_env_value(env_value)
                    cls._set_nested(config_data, special_mappings[env_key], converted_value)
                    applied_count += 1
                    logger.debug("Applied environment override (special mapping): %s=%s", env_key, env_value)
                except Exception as e:
                    logger.warning("Failed to apply environment variable %s: %s", env_key, e)
                    ignored_count += 1
                continue

            # Convention-based lookup: INQUIRY_SECTION_SUBSECTION_KEY → ["section", "subsection", "key"]
            # Get the key without prefix and convert to lowercase
            key_without_prefix = env_key[len(env_prefix):].lower()
            
            # Split on underscore to get path components
            key_parts = key_without_prefix.split('_')
            
            # Validate that we have at least a section and key
            if len(key_parts) < 2:
                logger.warning(
                    "Ignoring invalid environment variable %s: "
                    "must have at least section and key (e.g., INQUIRY_STORAGE_ROOT)",
                    env_key
                )
                ignored_count += 1
                continue
            
            # Check if section is valid
            section = key_parts[0]
            
            if section not in valid_sections:
                logger.warning(
                    "Ignoring unknown environment variable %s: "
                    "'%s' is not a valid config section. "
                    "Valid sections: %s",
                    env_key, section, sorted(valid_sections)
                )
                ignored_count += 1
                continue
            
            # Convert the value (handle booleans, numbers, strings)
            try:
                converted_value = cls._convert_env_value(env_value)
            except Exception as e:
                logger.warning("Failed to convert value for %s: %s", env_key, e)
                ignored_count += 1
                continue
            
            # Use _set_nested to intelligently navigate the config structure
            try:
                cls._set_nested(config_data, key_parts, converted_value)
                applied_count += 1
                logger.debug("Applied environment override: %s=%s", env_key, env_value)
            except Exception as e:
                logger.warning("Failed to apply environment variable %s: %s", env_key, e)
                ignored_count += 1
        
        if applied_count > 0:
            logger.info("Applied %s environment variable override(s)", applied_count)
        if ignored_count > 0:
            logger.warning("Ignored %s invalid environment variable(s)", ignored_count)
        
        return config_data
    
    @staticmethod
    def _convert_env_value(value: str) -> Any:
        """Convert environment variable string to appropriate type."""
        # Try boolean
        if value.lower() in ('true', 'yes', '1'):
            return True
        if value.lower() in ('false', 'no', '0'):
            return False
        
        # Try integer
        try:
            return int(value)
        except ValueError:
            pass
        
        # Try float
        try:
            return float(value)
        except ValueError:
            pass
        
        # Return as string
        return value

    @staticmethod
    def _set_nested(config_dict: dict, path: list[str], value: Any) -> None:
        """Set a value in a nested dictionary using a path, handling underscore ambiguity.
        
        This method intelligently handles cases where underscores in environment variable
        names could represent either:
        1. Part of a field name (e.g., 'default_project_id')
        2. Nesting levels (e.g., 'file_tracker' -> 'path')
        
        Args:
            config_dict: The configuration dictionary
            path: List of keys from splitting on underscores (e.g., ["storage", "file", "tracker", "path"])
            value: The value to set
        
        Examples:
            _set_nested(config, ["storage", "default", "project", "id"], "val")
            # Tries: storage.default_project_id (success)
            
            _set_nested(config, ["storage", "file", "tracker", "path"], "val")
            # Tries: storage.file_tracker.path (success)
        """
        if not path:
            raise ValueError("Path cannot be empty")
        
        # Try to find the best way to navigate the path by trying different combinations
        # of joining underscore-separated parts
        def try_set_value(current: dict, remaining_path: list[str], depth: int = 0) -> bool:
            """Recursively try to set the value by testing different underscore combinations."""
            if not remaining_path:
                return False
            
            # Base case: if we're at the last part, try to set it
            if len(remaining_path) == 1:
                current[remaining_path[0]] = value
                return True
            
            # Try progressively longer combinations of parts joined with underscores
            for i in range(1, len(remaining_path) + 1):
                # Join the first i parts with underscores
                key = "_".join(remaining_path[:i])

                # Check if this key exists in current dict
                if key in current:
                    if isinstance(current[key], dict):
                        # It's a nested dict, recurse into it
                        if try_set_value(current[key], remaining_path[i:], depth + 1):
                            return True
                    elif i == len(remaining_path):
                        # We've consumed all parts and found the key
                        current[key] = value
                        return True

            # Try creating intermediate dicts first
            # Use the first part as key and recurse
            if remaining_path[0] not in current:
                current[remaining_path[0]] = {}

            if isinstance(current[remaining_path[0]], dict):
                if try_set_value(current[remaining_path[0]], remaining_path[1:], depth + 1):
                    return True

            # If we're at depth > 0 (inside a section), try setting as joined key as fallback
            # This handles fields like "cleanup_retention_minutes" within a section
            if depth > 0 and len(remaining_path) > 1:
                # Try the full joined key (all parts with underscores)
                joined_key = "_".join(remaining_path)
                current[joined_key] = value
                return True
            
            return False
        
        # Start the recursive search
        if not try_set_value(config_dict, path):
            # Fallback: just set it using the full path with underscores
            current = config_dict
            for part in path[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[path[-1]] = value
    
    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Build Config instance from dictionary using dacite for automatic dataclass conversion.

        This method uses dacite.from_dict() for automatic nested dataclass instantiation,
        significantly reducing boilerplate code. Custom preprocessing handles:
        - Backward compatibility for impact_analysis migration to indexing config
        - Type casting for Set[str] fields (YAML lists -> Python sets)
        - Validation of ranking weights and threshold values

        Args:
            data: Dictionary of configuration values from YAML file

        Returns:
            Config instance with all nested dataclasses properly instantiated

        Raises:
            ConfigurationError: If dacite is not installed or validation fails
        """
        if dacite_from_dict is None or DaciteConfig is None:
            raise ConfigurationError(
                "dacite is required for configuration loading. "
                "Install it with: pip install dacite"
            )

        # Preprocess data for backward compatibility and special handling
        data = cls._preprocess_config_data(data)

        # Configure dacite for automatic dataclass conversion
        dacite_config = DaciteConfig(
            # Cast types for Set fields (YAML lists -> Python sets)
            cast=[set],
            # Allow extra keys in data (for forward compatibility)
            strict=False,
        )

        # Use dacite for automatic nested dataclass instantiation
        config = dacite_from_dict(
            data_class=cls,
            data=data,
            config=dacite_config,
        )

        # Post-processing validation
        cls._validate_config_values(config)

        return config

    @classmethod
    def _preprocess_config_data(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Preprocess configuration data for backward compatibility and special handling.

        Handles:
        - Impact analysis migration: old 'impact_analysis' section -> new 'indexing.impact_*' fields
        - Ensures nested sections exist with empty dicts for dacite

        Args:
            data: Raw configuration dictionary from YAML

        Returns:
            Preprocessed configuration dictionary
        """
        import copy
        data = copy.deepcopy(data)

        # Handle impact_analysis backward compatibility migration
        # Support both old structure (impact_analysis section) and new structure (indexing.impact_* fields)
        if 'impact_analysis' in data:
            impact_data = data.pop('impact_analysis')
            indexing_data = data.setdefault('indexing', {})

            # Only migrate if new fields don't already exist
            if 'impact_default_depth' not in indexing_data:
                indexing_data['impact_default_depth'] = impact_data.get('default_depth', 2)
            if 'impact_max_depth' not in indexing_data:
                indexing_data['impact_max_depth'] = impact_data.get('max_depth', 5)
            if 'impact_include_indirect' not in indexing_data:
                indexing_data['impact_include_indirect'] = impact_data.get('include_indirect', True)

        return data

    @classmethod
    def _validate_config_values(cls, config: "Config") -> None:
        """Validate configuration values after dacite instantiation.

        Performs validation that cannot be done via dataclass __post_init__:
        - Ranking weights must sum to 1.0
        - Consolidation thresholds must be in range 0.0-1.0

        Args:
            config: Config instance to validate

        Raises:
            ConfigurationError: If ranking weights don't sum to 1.0
            ValueError: If threshold values are out of range
        """
        # Validate ranking weights sum to 1.0
        ranking_weights = config.memory.retrieval.ranking_weights
        if ranking_weights:
            weight_sum = sum(ranking_weights.values())
            if not (0.99 <= weight_sum <= 1.01):  # Allow small floating point errors
                raise ConfigurationError(
                    f"Memory retrieval ranking weights must sum to 1.0 (+-0.01), "
                    f"got {weight_sum:.3f}. "
                    f"Current weights: {ranking_weights}. "
                    f"Please adjust your configuration so weights sum to 1.0."
                )

        # Validate consolidation threshold values (0.0-1.0)
        consolidation = config.memory.consolidation
        if not (0.0 <= consolidation.episodic_threshold <= 1.0):
            raise ValueError(
                f"consolidation.episodic_threshold must be between 0.0 and 1.0, "
                f"got {consolidation.episodic_threshold}"
            )
        if not (0.0 <= consolidation.semantic_threshold <= 1.0):
            raise ValueError(
                f"consolidation.semantic_threshold must be between 0.0 and 1.0, "
                f"got {consolidation.semantic_threshold}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        storage_dict = {
            'root': self.storage.root,
            'default_project_id': self.storage.default_project_id,
            'backend': self.storage.backend,
            'event_store_backend': self.storage.event_store_backend,
            'file_tracker_backend': self.storage.file_tracker_backend,
            'lancedb': {
                'path': self.storage.lancedb.path,
            },
            'file_tracker': {
                'path': self.storage.file_tracker.path,
            },
            'document_cache': {
                'enabled': self.storage.document_cache.enabled,
                'path': self.storage.document_cache.path,
            },
            'event_store': {
                'path': self.storage.event_store.path,
            },
        }
        
        return {
            'storage': storage_dict,
            'cache': {
                'document_cache': {
                    'max_size': self.cache.document_cache.max_size,
                    'ttl_seconds': self.cache.document_cache.ttl_seconds,
                    'eviction_policy': self.cache.document_cache.eviction_policy,
                },
            },
            'search': {
                'default_limit': self.search.default_limit,
                'max_limit': self.search.max_limit,
                'hybrid_search': {
                    'vector_weight': self.search.hybrid_search.vector_weight,
                    'fts_weight': self.search.hybrid_search.fts_weight,
                    'rerank_by_graph': self.search.hybrid_search.rerank_by_graph,
                },
                'graph_search': {
                    'max_depth': self.search.graph_search.max_depth,
                    'relationship_types': self.search.graph_search.relationship_types,
                },
            },
            'embeddings': {
                'default_provider': self.embeddings.default_provider,
                'sentence_transformer': {
                    'model_name': self.embeddings.sentence_transformer.model_name,
                    'ndims': self.embeddings.sentence_transformer.ndims,
                },
                'hashing': {
                    'ndims': self.embeddings.hashing.ndims,
                },
                'local_model': {
                    'model_path': self.embeddings.local_model.model_path,
                    'normalize': self.embeddings.local_model.normalize,
                    'batch_size': self.embeddings.local_model.batch_size,
                    'ndims': self.embeddings.local_model.ndims,
                },
            },
            'parsers': {
                'unified_code': {
                    'enabled': self.parsers.unified_code.enabled,
                    'priority': self.parsers.unified_code.priority,
                },
                'salesforce_metadata': {
                    'enabled': self.parsers.salesforce_metadata.enabled,
                    'priority': self.parsers.salesforce_metadata.priority,
                },
                'document': {
                    'enabled': self.parsers.document.enabled,
                    'priority': self.parsers.document.priority,
                },
                'fallback_text': {
                    'enabled': self.parsers.fallback_text.enabled,
                    'priority': self.parsers.fallback_text.priority,
                },
            },
            'memory': {
                'working_memory': {
                    'capacity': self.memory.working_memory.capacity,
                    'eviction_policy': self.memory.working_memory.eviction_policy,
                },
                'episodic_memory': {
                    'capacity': self.memory.episodic_memory.capacity,
                    'table_name': self.memory.episodic_memory.table_name,
                },
                'semantic_memory': {
                    'capacity': self.memory.semantic_memory.capacity,
                    'table_name': self.memory.semantic_memory.table_name,
                },
                'consolidation': {
                    'enabled': self.memory.consolidation.enabled,
                    'interval_seconds': self.memory.consolidation.interval_seconds,
                    'episodic_threshold': self.memory.consolidation.episodic_threshold,
                    'semantic_threshold': self.memory.consolidation.semantic_threshold,
                },
                'retrieval': {
                    'default_strategy': self.memory.retrieval.default_strategy,
                    'cache_enabled': self.memory.retrieval.cache_enabled,
                    'cache_ttl_seconds': self.memory.retrieval.cache_ttl_seconds,
                    'cache_size': self.memory.retrieval.cache_size,
                    'ranking_weights': self.memory.retrieval.ranking_weights,
                },
                'summary': {
                    'auto_threshold': self.memory.summary.auto_threshold,
                },
            },
            'events': {
                'enabled': self.events.enabled,
                'queue_max_size': self.events.queue_max_size,
                'batch_size': self.events.batch_size,
                'flush_interval_seconds': self.events.flush_interval_seconds,
                'retention_days': self.events.retention_days,
                'sampling_enabled': self.events.sampling_enabled,
                'sampling_ratio': self.events.sampling_ratio,
            },
            'entity_resolution': {
                'case_insensitive': self.entity_resolution.case_insensitive,
                'fuzzy_matching': {
                    'enabled': self.entity_resolution.fuzzy_matching.enabled,
                    'threshold': self.entity_resolution.fuzzy_matching.threshold,
                },
                'cache_enabled': self.entity_resolution.cache_enabled,
                'cache_ttl_seconds': self.entity_resolution.cache_ttl_seconds,
            },
            'impact_analysis': {
                'default_depth': self.indexing.impact_default_depth,
                'max_depth': self.indexing.impact_max_depth,
                'include_indirect': self.indexing.impact_include_indirect,
            },
            'progress': {
                'enabled': self.progress.enabled,
                'emit_interval': self.progress.emit_interval,
                'min_duration': self.progress.min_duration,
            },
            'logging': {
                'directory': self.logging.directory,
                'level': self.logging.level,
                'max_bytes': self.logging.max_bytes,
                'backup_count': self.logging.backup_count,
                'retention_hours': self.logging.retention_hours,
                'service_levels': self.logging.service_levels,
                'format': self.logging.format,
                'date_format': self.logging.date_format,
            },
            'context': {
                'token_budget': {
                    'default_budget': self.context.token_budget.default_budget,
                    'min_budget': self.context.token_budget.min_budget,
                    'max_budget': self.context.token_budget.max_budget,
                    'focus_allocations': self.context.token_budget.focus_allocations,
                },
            },
            'mcp': {
                'enabled': self.mcp.enabled,
                'server': {
                    'name': self.mcp.server.name,
                    'version': self.mcp.server.version,
                    'description': self.mcp.server.description,
                },
                'tools': {
                    'cognitive': self.mcp.tools.cognitive,
                    'direct_access': self.mcp.tools.direct_access,
                },
                'api': {
                    'enabled': self.mcp.api.enabled,
                    'host': self.mcp.api.host,
                    'port': self.mcp.api.port,
                    'cors': self.mcp.api.cors,
                    'auth': self.mcp.api.auth,
                },
                'session': {
                    'ttl_hours': self.mcp.session.ttl_hours,
                    'cleanup_interval_hours': self.mcp.session.cleanup_interval_hours,
                },
                'query': {
                    'default_limit': self.mcp.query.default_limit,
                    'max_limit': self.mcp.query.max_limit,
                },
                'relationships': {
                    'max_depth': self.mcp.relationships.max_depth,
                    'max_per_node': self.mcp.relationships.max_per_node,
                },
                'tokens': {
                    'estimation_model': self.mcp.tokens.estimation_model,
                    'default_budget': self.mcp.tokens.default_budget,
                },
                'defaults': {
                    'search': self.mcp.defaults.search,
                    'context': self.mcp.defaults.context,
                    'impact': self.mcp.defaults.impact,
                    'memory': self.mcp.defaults.memory,
                    'events': self.mcp.defaults.events,
                    'patterns': self.mcp.defaults.patterns,
                    'temporal': self.mcp.defaults.temporal,
                    'session_ttl_hours': self.mcp.defaults.session_ttl_hours,
                },
                'behavior': {
                    'suggest_on_empty': self.mcp.behavior.suggest_on_empty,
                    'include_alternatives': self.mcp.behavior.include_alternatives,
                    'log_all_requests': self.mcp.behavior.log_all_requests,
                    'track_performance': self.mcp.behavior.track_performance,
                    'cache_responses': self.mcp.behavior.cache_responses,
                    'cache_ttl_seconds': self.mcp.behavior.cache_ttl_seconds,
                },
                'logging': self.mcp.logging,
            },
            'connectors': {
                'default_connector': self.connectors.default_connector,
                'filesystem': {
                    'enabled': self.connectors.filesystem.enabled,
                    'root': self.connectors.filesystem.root,
                    'ignore_patterns': self.connectors.filesystem.ignore_patterns,
                    'binary_extensions': list(self.connectors.filesystem.binary_extensions),
                    'change_detection_enabled': self.connectors.filesystem.change_detection_enabled,
                    'watch_enabled': self.connectors.filesystem.watch_enabled,
                },
                'remote_cache': {
                    'enabled': self.connectors.remote_cache.enabled,
                    'path': self.connectors.remote_cache.path,
                    'max_size': self.connectors.remote_cache.max_size,
                },
            },
            'maintenance': {
                'trigger': self.maintenance.trigger,
                'cleanup_retention_minutes': self.maintenance.cleanup_retention_minutes,
                'enabled': self.maintenance.enabled,
            },
        }


__all__ = [
    "Config",
    "ConfigurationError",
    "StoragePathError",
    "StorageConfig",
    "LanceDBConfig",
    "FileTrackerConfig",
    "DocumentCacheStorageConfig",
    "EventStoreConfig",
    "BackendTimeoutsConfig",
    "CacheConfig",
    "DocumentCacheConfig",
    "SearchConfig",
    "HybridSearchConfig",
    "GraphSearchConfig",
    "SparseIndexConfig",
    "EmbeddingsConfig",
    "SentenceTransformerConfig",
    "HashingConfig",
    "LocalModelConfig",
    "ParsersConfig",
    "MCPConfig",
    "MCPServerConfig",
    "MCPToolsConfig",
    "MCPAPIConfig",
    "MCPSessionConfig",
    "MCPQueryConfig",
    "MCPRelationshipsConfig",
    "MCPTokensConfig",
    "MCPDefaultsConfig",
    "MCPBehaviorConfig",
    "ParserConfig",
    "EventsConfig",
    "MemoryConfig",
    "WorkingMemoryConfig",
    "EpisodicMemoryConfig",
    "SemanticMemoryConfig",
    "ConsolidationConfig",
    "RetrievalConfig",
    "SummaryConfig",
    "ConnectorsConfig",
    "FileSystemConnectorConfig",
    "RemoteConnectorCacheConfig",
    "MaintenanceConfig",
    "DEFAULT_IGNORE_PATTERNS",
    "DEFAULT_BINARY_EXTENSIONS",
    "VECTOR_DIMENSION",  # Legacy constant
]
