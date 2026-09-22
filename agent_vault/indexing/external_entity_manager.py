"""External entity management for graph construction.

This module handles the creation and management of external entities
(entities that cannot be resolved within the project, such as stdlib
imports and third-party library references).
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from agent_vault.executors import get_embedding_executor
from agent_vault.models.graph_entity import GraphEntity

if TYPE_CHECKING:
    from agent_vault.database.adapters.lancedb_adapter import LanceDBAdapter
    from agent_vault.database.lancedb_manager import LanceDBManager
    from agent_vault.indexing.external_entity_resolver import (
        ExternalEntityResolver,
        ExternalEntityInfo,
    )

logger = logging.getLogger(__name__)


class ExternalEntityManager:
    """Manages external entity creation and batch processing.

    This class handles entities that cannot be resolved within the project,
    such as standard library imports and third-party dependencies.

    Responsibilities:
    - Queue external entities for batch creation
    - Generate embeddings for external entities
    - Flush entities to database when threshold is reached
    - Detect programming language from file paths

    Args:
        project_id: Project identifier for entity ownership
        project_hash: Project hash for entity ID generation
        db_manager: Database manager for storing entities
        embedding_service: Service for generating embeddings
        external_resolver: Resolver for categorizing external entities
        embedding_dimensions: Vector dimensions (default: 384)
    """

    def __init__(
        self,
        project_id: str,
        project_hash: str,
        db_manager: Union["LanceDBManager", "LanceDBAdapter"],
        embedding_service: Any,
        external_resolver: Optional["ExternalEntityResolver"] = None,
        embedding_dimensions: int = 384,
        backend_type: str = "lancedb",
        capabilities: Optional[Any] = None,
    ):
        self.project_id = project_id
        self.project_hash = project_hash
        self.db_manager = db_manager
        self.embedding_service = embedding_service
        self._embedding_dimensions = embedding_dimensions
        # Resolve capabilities: prefer injected, fall back to derivation
        if capabilities is not None:
            _caps = capabilities
        else:
            from agent_vault.storage.capabilities import get_capabilities_for_backend
            _caps = get_capabilities_for_backend(backend_type)
        self._capabilities = _caps
        self._skip_local_embedding = _caps.uses_server_side_embedding

        # Use injected resolver or create default
        if external_resolver is not None:
            self._external_resolver = external_resolver
        else:
            from agent_vault.indexing.external_entity_resolver import ExternalEntityResolver
            self._external_resolver = ExternalEntityResolver(project_hash)

        # Track pending external entities for batch processing
        self._pending_external_entities: Dict[str, "ExternalEntityInfo"] = {}

    @property
    def pending_count(self) -> int:
        """Return the number of pending external entities."""
        return len(self._pending_external_entities)

    def queue_external_entity(
        self,
        target_name: str,
        target_type: str,
        language: str = "",
        source_file: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ExternalEntityInfo":
        """Queue an external entity for creation.

        Args:
            target_name: The external symbol name
            target_type: The entity type (function, class, module)
            language: Source language for categorization
            source_file: Source file path
            metadata: Additional metadata from parser

        Returns:
            ExternalEntityInfo with entity_id and other details
        """
        info = self._external_resolver.resolve(
            target_name=target_name,
            target_type=target_type,
            language=language,
            source_file=source_file,
            metadata=metadata,
        )

        # Queue for batch creation (deduplicated by entity_id)
        if info.entity_id not in self._pending_external_entities:
            self._pending_external_entities[info.entity_id] = info
            logger.debug(
                "Queued external entity: %s -> %s (lang=%s, category=%s)",
                target_name, info.entity_id, language, info.category.value
            )

        return info

    def clear_pending(self) -> None:
        """Clear all pending external entities."""
        self._pending_external_entities.clear()

    def get_pending_entities(self) -> Dict[str, "ExternalEntityInfo"]:
        """Get a copy of pending external entities."""
        return dict(self._pending_external_entities)

    async def flush_if_needed(
        self,
        threshold: int = 10000,
        batch_size: int = 100,
        event_system: Optional[Any] = None,
    ) -> int:
        """Flush external entities if threshold is exceeded.

        Performs an incremental flush of external entities when the queue
        exceeds the configured threshold. Generates embeddings in batches
        and logs counts by category (builtin vs external).

        Args:
            threshold: Minimum pending count to trigger flush
            batch_size: Maximum entities per embedding batch
            event_system: Optional event system for emitting flush events

        Returns:
            Number of external entities flushed (0 if threshold not exceeded)
        """
        if len(self._pending_external_entities) < threshold:
            return 0

        flushed_count = len(self._pending_external_entities)
        external_entities_to_flush = list(self._pending_external_entities.values())

        # Log external entity counts by category
        category_counts = self._count_entities_by_category(external_entities_to_flush)
        logger.info(
            "Flushing %d external entities (threshold: %d) - builtin: %d, external: %d",
            flushed_count,
            threshold,
            category_counts.get("builtin", 0),
            category_counts.get("external", 0),
        )

        try:
            # Generate embeddings in batches (max 100 per batch)
            all_vectors = await self._generate_embeddings_batched(
                external_entities_to_flush, batch_size
            )

            # Create GraphEntity objects with embeddings
            graph_entities = []
            for i, ext_info in enumerate(external_entities_to_flush):
                entity = GraphEntity(
                    id=ext_info.entity_id,
                    name=ext_info.name,
                    type="external",
                    file_path=ext_info.virtual_path or "external",
                    doc_id=f"external::{ext_info.entity_id}",
                    project_id=self.project_id,
                    vector=all_vectors[i] if i < len(all_vectors) else [0.0] * self._embedding_dimensions,
                )
                graph_entities.append(entity)

            if graph_entities:
                await self.db_manager.add_graph_entities(graph_entities)

            # Clear the flushed entities
            self._pending_external_entities.clear()

            logger.info(
                "Successfully flushed %d external entities (batches: %d)",
                flushed_count,
                (flushed_count + batch_size - 1) // batch_size,
            )

            # Emit external_entities.flushed event
            if event_system is not None:
                try:
                    await event_system.emit(
                        "external_entities.flushed",
                        source="external_entity_manager",
                        entities_flushed=flushed_count,
                        threshold=threshold,
                        builtin_count=category_counts.get("builtin", 0),
                        external_count=category_counts.get("external", 0),
                    )
                except Exception as emit_err:
                    logger.error("Failed to emit external_entities.flushed event: %s", emit_err)

        except Exception as e:
            logger.error("Failed to flush external entities: %s", e)
            # Don't clear on failure to allow retry
            return 0

        return flushed_count

    async def flush_all(
        self,
        document_processor: Any,
    ) -> List[GraphEntity]:
        """Create and return all queued external entities.

        Args:
            document_processor: Document processor for validation

        Returns:
            List of created GraphEntity objects
        """
        from agent_vault.indexing.external_entity_resolver import ExternalCategory

        if not self._pending_external_entities:
            return []

        if self._skip_local_embedding:
            entity_embedder, entity_dims = None, 768
        else:
            entity_embedder, entity_dims = self.embedding_service.get_embedder_configuration(
                "graph_entities", "vector"
            )

        external_entities = []
        builtin_count = 0
        external_count = 0

        loop = asyncio.get_running_loop()
        for entity_id, info in self._pending_external_entities.items():
            if self._skip_local_embedding:
                vector = [0.0] * entity_dims
            else:
                # Generate embedding for the entity name (in executor to avoid blocking)
                vectors = await loop.run_in_executor(
                    get_embedding_executor(),
                    entity_embedder.generate,
                    [info.name]
                )
                vector = vectors[0]
                document_processor._validate_vector(
                    "graph_entities", "vector", vector, entity_dims
                )

            entity = GraphEntity(
                id=entity_id,
                name=info.name,
                type=info.entity_type,
                file_path=info.virtual_path,
                doc_id=f"external_{info.language}",
                project_id=self.project_id,
                vector=vector,
                line_start=-1,
                line_end=-1,
                pagerank=0.0,
                betweenness=None,
                community_id=None,
                has_ranking_signals=False,
            )
            external_entities.append(entity)

            if info.category == ExternalCategory.BUILTIN:
                builtin_count += 1
            else:
                external_count += 1

        logger.info(
            "Created %d external entities (builtin: %d, external: %d)",
            len(external_entities), builtin_count, external_count
        )

        # Clear the queue
        self._pending_external_entities.clear()

        return external_entities

    def _count_entities_by_category(
        self,
        entities: List["ExternalEntityInfo"],
    ) -> Dict[str, int]:
        """Count external entities by category.

        Args:
            entities: List of external entity info objects

        Returns:
            Dictionary mapping category names to counts
        """
        counts: Dict[str, int] = {}
        for entity in entities:
            category = entity.category.value if hasattr(entity.category, "value") else str(entity.category)
            counts[category] = counts.get(category, 0) + 1
        return counts

    async def _generate_embeddings_batched(
        self,
        entities: List["ExternalEntityInfo"],
        batch_size: int,
    ) -> List[List[float]]:
        """Generate embeddings for external entities in batches.

        Args:
            entities: List of external entity info objects
            batch_size: Maximum entities per embedding batch

        Returns:
            List of embedding vectors (as lists of floats)
        """
        if not entities:
            return []

        all_vectors: List[List[float]] = []

        # Process in batches
        for i in range(0, len(entities), batch_size):
            batch = entities[i : i + batch_size]
            # Create text representations for embedding
            texts = [
                f"{entity.entity_type}: {entity.name} ({entity.language})"
                for entity in batch
            ]

            try:
                # Generate embeddings using the embedding service
                embeddings = await self.embedding_service.embed_batch_async(texts)
                for emb in embeddings:
                    # Convert numpy array to list if needed
                    if hasattr(emb, "tolist"):
                        all_vectors.append(emb.tolist())
                    else:
                        all_vectors.append(list(emb))
            except Exception as e:
                logger.warning(
                    "Failed to generate embeddings for batch %d-%d, using zeros: %s",
                    i,
                    i + len(batch),
                    e,
                )
                # Fall back to zero vectors on error
                for _ in batch:
                    all_vectors.append([0.0] * self._embedding_dimensions)

        return all_vectors

    @staticmethod
    def detect_language(
        file_path: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Detect programming language from metadata or file extension.

        Args:
            file_path: Path to source file
            metadata: Optional metadata that may contain language info

        Returns:
            Language identifier string (lowercase) or empty string
        """
        # Check metadata first (parser may have provided language)
        if metadata:
            if "language" in metadata:
                return str(metadata["language"]).lower()
            if "lang" in metadata:
                return str(metadata["lang"]).lower()

        # Fall back to extension-based detection
        ext = Path(file_path).suffix.lower()

        ext_to_lang = {
            # Python
            ".py": "python", ".pyi": "python", ".pyw": "python",
            # JavaScript/TypeScript
            ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript",
            # JVM
            ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
            ".scala": "scala", ".sc": "scala",
            ".groovy": "groovy", ".gradle": "groovy",
            ".clj": "clojure", ".cljs": "clojure", ".cljc": "clojure",
            # Systems
            ".go": "go",
            ".rs": "rust",
            ".c": "c", ".h": "c",
            ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
            ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
            ".m": "objc", ".mm": "objcpp",
            ".swift": "swift",
            ".zig": "zig",
            ".nim": "nim",
            ".v": "v", ".vv": "v",
            # .NET
            ".cs": "csharp", ".csx": "csharp",
            ".fs": "fsharp", ".fsx": "fsharp",
            ".vb": "vb",
            # Scripting
            ".rb": "ruby", ".rake": "ruby",
            ".php": "php",
            ".pl": "perl", ".pm": "perl",
            ".lua": "lua",
            ".r": "r", ".R": "r",
            ".jl": "julia",
            # Shell
            ".sh": "bash", ".bash": "bash",
            ".zsh": "zsh", ".fish": "fish",
            ".ps1": "powershell", ".psm1": "powershell",
            # Functional
            ".hs": "haskell", ".lhs": "haskell",
            ".ml": "ocaml", ".mli": "ocaml",
            ".ex": "elixir", ".exs": "elixir",
            ".erl": "erlang", ".hrl": "erlang",
            # Other
            ".dart": "dart",
            ".cr": "crystal",
            ".elm": "elm",
            ".purs": "purescript",
            ".rkt": "racket",
            ".d": "d",
            ".ada": "ada", ".adb": "ada", ".ads": "ada",
            ".pas": "pascal", ".pp": "pascal",
            ".f90": "fortran", ".f95": "fortran", ".f03": "fortran",
            ".cob": "cobol", ".cbl": "cobol",
        }

        return ext_to_lang.get(ext, "")
