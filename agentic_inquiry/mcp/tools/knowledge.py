"""Knowledge management tools for MCP server.

These tools handle indexing code and documentation into the knowledge base.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any

from agentic_inquiry.parsers import create_parser_chain
from agentic_inquiry.utils.ignore_handler import get_ignore_handler
from agentic_inquiry.mcp.utils.validation import validate_file_path, PathValidationError

logger = logging.getLogger(__name__)


async def _index_directory_async(
    services: dict,
    session_id: str,
    operation_id: str,
    directory_path: Path,
    timeout: int = 300,
    timeout_per_file: int = 5,
    base_timeout: int = 60
) -> Dict[str, Any]:
    """Index directory with progress tracking and dynamic timeout.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        operation_id: Unique operation identifier
        directory_path: Path to directory to index
        timeout: Fixed timeout in seconds (used if > 0, otherwise dynamic)
        timeout_per_file: Seconds allowed per file for dynamic timeout (default 5)
        base_timeout: Base seconds for setup/flush in dynamic timeout (default 60)

    Returns:
        Indexing results with status and counts

    Note:
        Dynamic timeout = base_timeout + (file_count * timeout_per_file)
        Example: 100 files = 60 + (100 * 5) = 560 seconds
    """
    import asyncio

    session_manager = services["session_manager"]
    event_system = services["event_system"]
    config = services["config"]
    db_manager = services["storage"]

    # Initialize progress tracking
    progress = {
        "files_processed": 0,
        "chunks_created": 0,
        "entities_created": 0,
        "errors": []
    }

    # Discover all files (parsers will skip unsupported types via can_parse)
    # Exclude obvious binary files that no parser can handle
    binary_extensions = {
                         '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv',
                         '.zip', '.tar', '.gz', '.rar', '.7z',
                         '.exe', '.dll', '.so', '.dylib', '.bin',
                         '.pyc', '.pyo', '.class', '.o', '.obj',
                         '.woff', '.woff2', '.ttf', '.otf', '.eot'
                        }
    ignore_handler = get_ignore_handler(str(directory_path))
    files = [
        f for f in directory_path.rglob("*")
        if f.is_file()
        and not ignore_handler.is_ignored(str(f))
        and f.suffix.lower() not in binary_extensions
    ]

    # Calculate dynamic timeout based on file count
    # Use provided timeout if explicitly set, otherwise calculate dynamically
    if timeout <= 0 or timeout == 300:  # 300 is the old default, switch to dynamic
        dynamic_timeout = base_timeout + (len(files) * timeout_per_file)
        effective_timeout = max(dynamic_timeout, 120)  # Minimum 2 minutes
    else:
        effective_timeout = timeout

    logger.info(
        "Starting async directory indexing: operation_id=%s, path=%s, files=%d, timeout=%ds",
        operation_id,
        directory_path,
        len(files),
        effective_timeout
    )

    try:
        # Wrap indexing in timeout
        async def _do_indexing(
            event_system=event_system,
            config=config,
            db_manager=db_manager,
            session_manager=session_manager,
        ):
            # Get session to extract project_id
            session = await session_manager.get_session(session_id, include_history=False)
            project_id = session.project_id

            # Create IndexingPipeline with session's project_id
            from agentic_inquiry.indexing.pipeline import IndexingPipeline

            # Use embedding registry from db_manager if available (for testing)
            pipeline_kwargs = {
                "db_manager": db_manager,
                "config": config,
                "project_id": project_id,
                "event_system": event_system  # Pass the event system from services
            }
            if hasattr(db_manager, "embedding_registry"):
                pipeline_kwargs["registry"] = db_manager.embedding_registry

            indexing_pipeline = IndexingPipeline(**pipeline_kwargs)

            if not files:
                # Emit completion event with zero files
                await session_manager.add_event(
                    session_id=session_id,
                    event_type="indexing_completed",
                    data={
                        "operation_id": operation_id,
                        "status": "completed",
                        "items_processed": 0,
                        "chunks_created": 0,
                        "files": [],
                        "message": f"No files found in {directory_path}"
                    }
                )
                logger.info(
                    "Directory indexing completed with no files: operation_id=%s",
                    operation_id
                )
                return {
                    "status": "completed",
                    "items_processed": 0,
                    "chunks_created": 0
                }
            
            # Index each file with progress tracking
            chain = create_parser_chain()
            indexed_files = []
            
            for file_path in files:
                try:
                    # Pass db_manager, embedding_service, and project_id to parser for granular entity extraction
                    parsed_doc = await chain.parse(
                        str(file_path),
                        db_manager=db_manager,
                        embedding_service=indexing_pipeline.embedding_service,
                        project_id=project_id
                    )
                    # Process document but defer relationship flush until all files are indexed
                    # This ensures cross-file symbols are registered before resolution
                    await indexing_pipeline.process_document(parsed_doc, flush_relationships=False)
                    
                    # Update progress
                    progress["files_processed"] += 1
                    progress["chunks_created"] += len(parsed_doc.chunks)
                    progress["entities_created"] += sum(len(chunk.symbols or []) for chunk in parsed_doc.chunks)
                    indexed_files.append(str(file_path.relative_to(directory_path)))
                    
                    # Emit progress event
                    await event_system.emit(
                        "indexing_progress",
                        source="mcp_tool",
                        operation_id=operation_id,
                        files_processed=progress["files_processed"],
                        chunks_created=progress["chunks_created"],
                        total_files=len(files)
                    )
                    
                except Exception as e:
                    from agentic_inquiry.indexing.models import IndexingError
                    from agentic_inquiry.exceptions import ParsingError, SchemaValidationError
                    
                    logger.error(
                        "Failed to index file %s in async operation: %s",
                        file_path,
                        e
                    )
                    
                    # Create IndexingError with helpful suggestion based on error type
                    error_type = type(e).__name__
                    suggestion = "Check file format and content"
                    
                    if isinstance(e, ParsingError):
                        suggestion = "Verify file is valid and supported format (.py, .js, .ts, .md, etc.)"
                    elif isinstance(e, SchemaValidationError):
                        suggestion = "File structure may not match expected schema. Check parser output."
                    elif "permission" in str(e).lower():
                        suggestion = "Check file permissions and ensure file is accessible"
                    elif "encoding" in str(e).lower():
                        suggestion = "File may have encoding issues. Ensure file is UTF-8 encoded"
                    
                    indexing_error = IndexingError(
                        file_path=str(file_path),
                        error_type=error_type,
                        error_message=str(e),
                        suggestion=suggestion
                    )
                    progress["errors"].append(indexing_error.to_dict())
                    # Continue with other files

            # Flush pending relationships after all files are indexed
            # This is critical for graph-based features (impact analysis, pattern detection)
            pending_count = indexing_pipeline.graph_builder.get_pending_relationship_count()
            logger.info(
                "Pre-flush diagnostic: %d pending relationships queued from %d files",
                pending_count,
                progress["files_processed"],
            )
            relationships_created = await indexing_pipeline.flush_pending_relationships()

            # Rebuild FTS indexes after all data has been added
            # LanceDB FTS indexes don't auto-update when new data is added
            fts_rebuilt = 0
            try:
                if hasattr(db_manager, 'rebuild_fts_indexes'):
                    fts_rebuilt = await db_manager.rebuild_fts_indexes("document_chunks")
                    if fts_rebuilt > 0:
                        logger.info(
                            "Rebuilt %d FTS indexes for document_chunks: operation_id=%s",
                            fts_rebuilt,
                            operation_id
                        )
            except Exception as e:
                logger.warning(
                    "Failed to rebuild FTS indexes after indexing: %s",
                    e
                )

            # Get resolution statistics for debugging/visibility
            resolution_stats = indexing_pipeline.get_resolution_stats() or {}

            logger.info(
                "Flushed %d relationships for directory indexing: operation_id=%s",
                relationships_created,
                operation_id
            )

            logger.info(
                "Directory indexing completed: operation_id=%s, items=%d, chunks=%d, relationships=%d",
                operation_id,
                progress["files_processed"],
                progress["chunks_created"],
                relationships_created
            )

            # Emit indexing.stored — chunks + relationships are written to storage
            if event_system:
                from agentic_inquiry.events.types import EventTypes
                capabilities = services.get("capabilities")
                embedding_strategy = (
                    "server_side" if capabilities and capabilities.needs_embedding_polling
                    else "local"
                )
                await event_system.emit(
                    EventTypes.Indexing.STORED,
                    source="add_knowledge",
                    operation_id=operation_id,
                    files_processed=progress["files_processed"],
                    chunks_created=progress["chunks_created"],
                    entities_created=progress["entities_created"],
                    relationships_created=relationships_created,
                    embedding_strategy=embedding_strategy,
                )

            # Event 1: chunking_completed — chunks, entities, and relationships stored.
            # Index is queryable via FTS and graph traversal. Embeddings not yet ready.
            await session_manager.add_event(
                session_id=session_id,
                event_type="chunking_completed",
                data={
                    "operation_id": operation_id,
                    "status": "completed",
                    "items_processed": progress["files_processed"],
                    "chunks_created": progress["chunks_created"],
                    "relationships_created": relationships_created,
                    "files": indexed_files,
                    "errors": progress["errors"],
                    "message": f"Chunking complete: {progress['files_processed']} files, {relationships_created} relationships. Embeddings generating..."
                }
            )

            # Generate server-side embeddings (can take minutes for large codebases)
            capabilities = services.get("capabilities")
            if capabilities and capabilities.needs_embedding_polling:
                try:
                    # Generate chunk + entity embeddings via StorageFacade
                    logger.info("Generating server-side embeddings for operation %s...", operation_id)
                    embed_results = await db_manager.generate_embeddings()
                    logger.info(
                        "Server-side embedding generation complete for operation %s: %s",
                        operation_id, embed_results,
                    )

                    # Poll until all embeddings are populated (no NULL embeddings remain)
                    # Uses pipeline's polling with exponential backoff (5s initial, 900s timeout)
                    logger.info("Polling for embedding completion (operation %s)...", operation_id)
                    await indexing_pipeline._poll_embedding_completion()
                    logger.info("All embeddings ready for operation %s", operation_id)
                except TimeoutError as timeout_err:
                    logger.warning(
                        "Embedding generation timed out for operation %s: %s",
                        operation_id, timeout_err,
                    )
                except Exception as poll_err:
                    logger.error(
                        "Embedding generation/poll failed for operation %s: %s",
                        operation_id, poll_err,
                        exc_info=True,
                    )

            # Event 2: indexing_completed — everything is done (chunks + embeddings).
            # This is the definitive "ready" signal: FTS, vector search, and graph
            # traversal all work at this point.
            await session_manager.add_event(
                session_id=session_id,
                event_type="indexing_completed",
                data={
                    "operation_id": operation_id,
                    "status": "completed",
                    "items_processed": progress["files_processed"],
                    "chunks_created": progress["chunks_created"],
                    "relationships_created": relationships_created,
                    "files": indexed_files,
                    "errors": progress["errors"],
                    "message": f"Indexing complete: {progress['files_processed']} files, {relationships_created} relationships, embeddings ready"
                }
            )

            if event_system:
                # Emit indexing.ready — index is now fully searchable with embeddings
                await event_system.emit(
                    EventTypes.Indexing.READY,
                    source="add_knowledge",
                    operation_id=operation_id,
                    files_processed=progress["files_processed"],
                    chunks_created=progress["chunks_created"],
                    entities_created=progress["entities_created"],
                    relationships_created=relationships_created,
                )

            # Build summary stats for response
            relationship_summary = {}
            if resolution_stats:
                relationship_summary = {
                    "total_pending": resolution_stats.get("total", 0),
                    "resolved_cross_file": resolution_stats.get("resolved_cross_file", 0),
                    "unresolved_external": resolution_stats.get("unresolved_external", 0),
                    "same_file_fallback": resolution_stats.get("same_file_fallback", 0),
                    "by_strategy": resolution_stats.get("by_strategy", {}),
                    "average_confidence": resolution_stats.get("average_confidence", 0.0),
                }

            return {
                "status": "completed",
                "items_processed": progress["files_processed"],
                "files_processed": progress["files_processed"],  # Alias for clarity
                "chunks_created": progress["chunks_created"],
                "relationships_created": relationships_created,
                "relationship_stats": relationship_summary,
                "errors": progress["errors"]
            }
        
        # Execute with dynamic timeout
        result = await asyncio.wait_for(_do_indexing(), timeout=effective_timeout)
        return result
        
    except asyncio.TimeoutError:
        # Handle timeout
        logger.warning(
            "Directory indexing timed out: operation_id=%s, timeout=%d, processed=%d",
            operation_id,
            effective_timeout,
            progress["files_processed"]
        )

        # Note: We cannot flush pending relationships on timeout because
        # the graph_builder state is in-memory per pipeline instance.
        # The original pipeline inside _do_indexing is no longer accessible.
        relationships_created = 0
        logger.warning(
            "Timeout occurred before relationship flush. "
            "Pending relationships from processed files were not saved. "
            "Consider increasing timeout_per_file or base_timeout."
        )

        # Emit timeout event with partial results
        await session_manager.add_event(
            session_id=session_id,
            event_type="indexing_timeout",
            data={
                "operation_id": operation_id,
                "status": "timeout",
                "items_processed": progress["files_processed"],
                "chunks_created": progress["chunks_created"],
                "relationships_created": relationships_created,
                "timeout_seconds": effective_timeout,
                "message": f"Indexing timed out after {effective_timeout}s. Processed {progress['files_processed']} files. Relationships may be incomplete."
            }
        )

        return {
            "status": "timeout",
            "error": f"Indexing timed out after {effective_timeout} seconds",
            "items_processed": progress["files_processed"],
            "files_processed": progress["files_processed"],  # Alias for clarity
            "chunks_created": progress["chunks_created"],
            "relationships_created": relationships_created,
            "warning": "Pending relationships may not have been flushed due to timeout"
        }
        
    except Exception as e:
        # Distinguish async generator cleanup errors from genuine failures.
        # Python 3.13 raises "generator didn't stop after athrow()" during
        # async generator teardown — this is a cleanup issue, not data loss.
        is_cleanup_error = "generator didn't stop" in str(e) or "athrow" in str(e)
        data_was_created = progress["chunks_created"] > 0

        if is_cleanup_error and data_was_created:
            logger.warning(
                "Async cleanup error during indexing (non-fatal, %d chunks created): %s",
                progress["chunks_created"], e,
            )
            return {
                "status": "completed",
                "warning": f"Async cleanup error (non-fatal): {e}",
                "operation_id": operation_id,
                "items_processed": progress["files_processed"],
                "files_processed": progress["files_processed"],
                "chunks_created": progress["chunks_created"],
                "relationships_created": relationships_created,
            }

        logger.error(
            "Directory indexing failed: operation_id=%s, error=%s",
            operation_id,
            e,
            exc_info=True
        )

        await session_manager.add_event(
            session_id=session_id,
            event_type="indexing_failed",
            data={
                "operation_id": operation_id,
                "status": "failed",
                "error": str(e),
                "items_processed": progress["files_processed"],
                "chunks_created": progress["chunks_created"],
                "message": f"Directory indexing failed: {str(e)}"
            }
        )

        return {
            "status": "failed",
            "error": str(e),
            "items_processed": progress["files_processed"],
            "files_processed": progress["files_processed"],
            "chunks_created": progress["chunks_created"]
        }


async def add_knowledge(
    services: dict,
    session_id: str,
    content_type: str,
    source: str,
    watch: bool = False,
    filters: Optional[Dict[str, Any]] = None,
    wait_for_completion: bool = False,
    wait_timeout: int = 1800,
) -> dict:
    """Add content to the knowledge base by indexing files or text.

    Indexes code and documentation to enable semantic search and analysis.
    Supports files, directories (respects .gitignore), and direct text input.

    Args:
        services: Service dependency dict
        session_id: Session identifier
        content_type: Content type: "file", "directory", or "text"
        source: Source path (for file/directory) or text content
        watch: Enable file watching for automatic reindexing
        filters: Optional filters (extensions, paths to include/exclude)
        wait_for_completion: If True, block until directory indexing finishes
            instead of returning immediately. Default False for backward compat.
        wait_timeout: Max seconds to wait when wait_for_completion=True (default 1800).
            Full codebase indexing with server-side embeddings (AlloyDB) can take 10-20 min.

    Returns:
        Indexing results with counts and status

    Example:
        >>> # Index a directory
        >>> result = await add_knowledge(
        ...     services, "sess_123",
        ...     content_type="directory",
        ...     source="agentic_inquiry/mcp/tools"
        ... )
        >>> print(f"Indexed {result['items_processed']} files")

        >>> # Index a single file
        >>> result = await add_knowledge(
        ...     services, "sess_123",
        ...     content_type="file",
        ...     source="agentic_inquiry/search/service.py"
        ... )

        >>> # Index a directory and wait for it to finish
        >>> result = await add_knowledge(
        ...     services, "sess_123",
        ...     content_type="directory",
        ...     source=".",
        ...     wait_for_completion=True,
        ...     wait_timeout=1800
        ... )
    """
    from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
    from agentic_inquiry.mcp.utils.validation import (
        validate_content_type,
        create_validation_error_response
    )
    from agentic_inquiry.exceptions import SchemaValidationError
    from agentic_inquiry.correlation import get_correlation_id
    
    session_manager = services["session_manager"]
    event_system = services["event_system"]
    config = services["config"]
    db_manager = services["storage"]

    # Validate parameters
    try:
        content_type = validate_content_type(content_type)
    except Exception as e:
        # Import ValidationError to check exception type
        from agentic_inquiry.exceptions import ValidationError as AGVValidationError
        
        # If it's our ValidationError, return detailed response
        if isinstance(e, AGVValidationError):
            return {
                "status": "failed",
                "error": str(e),
                "error_type": "validation_error",
                "field": e.param_name,
                "invalid_value": str(e.invalid_value),
                "valid_values": e.valid_values,
                "example": e.example,
                "context": {
                    "session_id": session_id,
                    "content_type": content_type,
                    "source": source
                }
            }
        # Fall back to generic validation error response for other exceptions
        return create_validation_error_response(
            field="content_type",
            error=e,
            context={
                "session_id": session_id,
                "content_type": content_type,
                "source": source
            },
            provided_value=content_type,
            expected_type="string",
            expected_values=["file", "directory", "text"],
            example="content_type='file'"
        )

    # Validate session
    if not await session_manager.validate_session(session_id):
        return await MCPErrorHandler.handle(
            error=Exception(f"Session '{session_id}' not found or expired"),
            context={"session_id": session_id},
            services=services
        )

    # Get session to extract project_id
    session = await session_manager.get_session(session_id, include_history=False)
    project_id = session.project_id
    
    # Create IndexingPipeline with session's project_id
    from agentic_inquiry.indexing.pipeline import IndexingPipeline
    
    # Use embedding registry from db_manager if available (for testing)
    pipeline_kwargs = {
        "db_manager": db_manager,
        "config": config,
        "project_id": project_id,
        "event_system": event_system  # Pass the event system from services
    }
    if hasattr(db_manager, "embedding_registry"):
        pipeline_kwargs["registry"] = db_manager.embedding_registry
    
    indexing_pipeline = IndexingPipeline(**pipeline_kwargs)

    # Track start
    await event_system.emit(
        "mcp.tool.started",
        source="mcp_tool",
        tool_name="add_knowledge",
        session_id=session_id,
        content_type=content_type,
        file_source=source
    )

    try:
        # Get project root (current working directory)
        import os
        project_root = Path(os.getcwd())

        # Handle different content types
        if content_type == "file":
            # Index a single file - validate path for security
            try:
                file_path = validate_file_path(source, project_root, must_exist=False)
            except PathValidationError as e:
                from agentic_inquiry.correlation import get_correlation_id
                correlation_id = get_correlation_id()
                
                return {
                    "status": "failed",
                    "error": str(e),
                    "error_type": "path_validation",
                    "correlation_id": correlation_id,
                    "troubleshooting": {
                        "possible_causes": [
                            "Attempting to access files outside project directory",
                            "Using directory traversal sequences (..)",
                            "Absolute path outside project"
                        ],
                        "next_steps": [
                            "Use relative paths from project root",
                            "Ensure path is within project directory",
                            "Check for typos in path"
                        ]
                    }
                }

            if not file_path.exists():
                # Enhanced error with troubleshooting
                from agentic_inquiry.correlation import get_correlation_id
                correlation_id = get_correlation_id()
                
                return {
                    "status": "failed",
                    "error": f"File not found: {source}",
                    "error_type": "file_not_found",
                    "correlation_id": correlation_id,
                    "troubleshooting": {
                        "possible_causes": [
                            "File path is incorrect or contains typos",
                            "File was moved or deleted",
                            "Using absolute path instead of relative path",
                            "File is in a different directory than expected"
                        ],
                        "next_steps": [
                            f"Verify the file exists at: {file_path}",
                            "Check for typos in the file path",
                            "Use a relative path from the project root",
                            "List directory contents to find the correct path",
                            "Ensure the file hasn't been moved or deleted"
                        ]
                    },
                    "suggestions": [
                        "Try: Using a relative path from project root (e.g., 'src/main.py')",
                        "Try: Listing directory contents to verify file location",
                        "Try: Checking for typos in the file name or path"
                    ]
                }

            # Parse and index
            # Pass db_manager, embedding_service, and project_id to parser for granular entity extraction
            chain = create_parser_chain()
            parsed_doc = await chain.parse(
                str(file_path),
                db_manager=db_manager,
                embedding_service=indexing_pipeline.embedding_service,
                project_id=project_id
            )
            
            try:
                await indexing_pipeline.process_document(parsed_doc)
            except SchemaValidationError as e:
                # Handle schema validation errors with detailed information
                correlation_id = get_correlation_id()
                
                error_details: Dict[str, Any] = {
                    "error": "Schema validation failed",
                    "file": source,
                    "table": e.table_name,
                    "correlation_id": correlation_id,
                }
                
                # Add field mapping hints
                if e.missing_fields:
                    error_details["missing_fields"] = e.missing_fields
                    error_details["hint"] = (
                        "The parser output is missing required database fields. "
                        "This may indicate a schema mismatch between ParserChunk and the database."
                    )
                
                if e.type_mismatches:
                    error_details["type_mismatches"] = [
                        {"field": field, "expected": expected, "actual": actual}
                        for field, expected, actual in e.type_mismatches
                    ]
                    error_details["hint"] = (
                        "Field types don't match database schema. "
                        "Check that field values are compatible with database types."
                    )
                
                logger.error(
                    "Schema validation failed for file %s: %s (correlation_id: %s)",
                    source,
                    str(e),
                    correlation_id,
                    extra=error_details
                )
                
                return {
                    "status": "failed",
                    "error": str(e),
                    "error_type": "schema_validation",
                    "details": error_details
                }

            # Flush pending relationships for single file indexing
            # This enables graph-based features for the indexed file
            relationships_created = await indexing_pipeline.flush_pending_relationships()

            # Rebuild FTS indexes after data has been added
            # LanceDB FTS indexes don't auto-update when new data is added
            try:
                if hasattr(db_manager, 'rebuild_fts_indexes'):
                    await db_manager.rebuild_fts_indexes("document_chunks")
            except Exception as e:
                logger.warning(
                    "Failed to rebuild FTS indexes after indexing: %s",
                    e
                )

            # Get resolution statistics for debugging/visibility
            resolution_stats = indexing_pipeline.get_resolution_stats() or {}

            logger.info(
                "Flushed %d relationships for single file: %s",
                relationships_created,
                source
            )

            # Emit indexing.stored and indexing.ready for single-file indexing
            from agentic_inquiry.events.types import EventTypes
            capabilities = services.get("capabilities")
            embedding_strategy = (
                "server_side" if capabilities and capabilities.needs_embedding_polling
                else "local"
            )
            chunks_created = len(parsed_doc.chunks)
            entities_created = sum(len(chunk.symbols or []) for chunk in parsed_doc.chunks)

            await event_system.emit(
                EventTypes.Indexing.STORED,
                source="add_knowledge",
                operation_id=f"file_{project_id}",
                files_processed=1,
                chunks_created=chunks_created,
                entities_created=entities_created,
                relationships_created=relationships_created,
                embedding_strategy=embedding_strategy,
            )

            # Generate server-side embeddings if needed
            if capabilities and capabilities.needs_embedding_polling:
                try:
                    if hasattr(db_manager, 'generate_embeddings'):
                        await db_manager.generate_embeddings()
                    await indexing_pipeline._poll_embedding_completion(
                        f"file_{project_id}"
                    )
                except Exception as poll_err:
                    logger.warning(
                        "Embedding poll error after single-file indexing: %s",
                        poll_err,
                    )

            await event_system.emit(
                EventTypes.Indexing.READY,
                source="add_knowledge",
                operation_id=f"file_{project_id}",
                files_processed=1,
                chunks_created=chunks_created,
                entities_created=entities_created,
                relationships_created=relationships_created,
            )

            # Track success
            await event_system.emit(
                "mcp.tool.completed",
                source="mcp_tool",
                tool_name="add_knowledge",
                session_id=session_id,
                items_processed=1
            )

            # Build summary stats for response
            relationship_summary = {}
            if resolution_stats:
                relationship_summary = {
                    "total_pending": resolution_stats.get("total", 0),
                    "resolved_cross_file": resolution_stats.get("resolved_cross_file", 0),
                    "unresolved_external": resolution_stats.get("unresolved_external", 0),
                    "same_file_fallback": resolution_stats.get("same_file_fallback", 0),
                    "by_strategy": resolution_stats.get("by_strategy", {}),
                    "average_confidence": resolution_stats.get("average_confidence", 0.0),
                }

            return {
                "status": "completed",
                "items_processed": 1,
                "chunks_created": len(parsed_doc.chunks),
                "entities_created": sum(len(chunk.symbols or []) for chunk in parsed_doc.chunks),
                "relationships_created": relationships_created,
                "relationship_stats": relationship_summary
            }

        elif content_type == "directory":
            # Index all files in directory asynchronously
            import uuid
            import asyncio
            
            # Validate directory path for security
            try:
                dir_path = validate_file_path(source, project_root, must_exist=False)
            except PathValidationError as e:
                from agentic_inquiry.correlation import get_correlation_id
                correlation_id = get_correlation_id()
                
                return {
                    "status": "failed",
                    "error": str(e),
                    "error_type": "path_validation",
                    "correlation_id": correlation_id,
                    "troubleshooting": {
                        "possible_causes": [
                            "Attempting to access directories outside project directory",
                            "Using directory traversal sequences (..)",
                            "Absolute path outside project"
                        ],
                        "next_steps": [
                            "Use relative paths from project root",
                            "Ensure path is within project directory",
                            "Check for typos in path"
                        ]
                    }
                }

            if not dir_path.exists():
                # Enhanced error with troubleshooting
                from agentic_inquiry.correlation import get_correlation_id
                correlation_id = get_correlation_id()
                
                return {
                    "status": "failed",
                    "error": f"Directory not found: {source}",
                    "error_type": "directory_not_found",
                    "correlation_id": correlation_id,
                    "troubleshooting": {
                        "possible_causes": [
                            "Directory path is incorrect or contains typos",
                            "Directory was moved or deleted",
                            "Using absolute path instead of relative path",
                            "Directory is in a different location than expected"
                        ],
                        "next_steps": [
                            f"Verify the directory exists at: {dir_path}",
                            "Check for typos in the directory path",
                            "Use a relative path from the project root",
                            "List parent directory contents to find the correct path",
                            "Ensure the directory hasn't been moved or deleted"
                        ]
                    },
                    "suggestions": [
                        "Try: Using a relative path from project root (e.g., 'src/')",
                        "Try: Using '.' to index the entire project directory",
                        "Try: Checking for typos in the directory name or path"
                    ]
                }

            # Generate operation ID for tracking
            operation_id = str(uuid.uuid4())
            
            # Emit indexing_started event
            await session_manager.add_event(
                session_id=session_id,
                event_type="indexing_started",
                data={
                    "operation_id": operation_id,
                    "source": str(dir_path),
                    "content_type": "directory"
                }
            )
            
            # Start directory indexing
            # Dynamic timeout: base_timeout + (file_count * timeout_per_file)
            # Default 300 triggers dynamic calculation; explicit timeout overrides
            indexing_coro = _index_directory_async(
                services=services,
                session_id=session_id,
                operation_id=operation_id,
                directory_path=dir_path,
                timeout=filters.get("timeout", 300) if filters else 300,
                timeout_per_file=filters.get("timeout_per_file", 5) if filters else 5,
                base_timeout=filters.get("base_timeout", 60) if filters else 60
            )

            if wait_for_completion:
                # Blocking mode: await the indexing task directly
                try:
                    result = await asyncio.wait_for(indexing_coro, timeout=wait_timeout)
                    # Merge operation_id into result for callers that need it
                    if isinstance(result, dict):
                        result.setdefault("operation_id", operation_id)
                    return result or {
                        "status": "completed",
                        "operation_id": operation_id,
                        "message": f"Directory indexing completed for {dir_path}.",
                    }
                except asyncio.TimeoutError:
                    return {
                        "status": "timeout",
                        "operation_id": operation_id,
                        "message": f"Directory indexing timed out after {wait_timeout}s for {dir_path}.",
                        "how_to_check": "Use get_events(session_id, event_types=['indexing_completed', 'indexing_failed']) to check final status.",
                    }
            else:
                # Fire-and-forget mode (default): return immediately
                asyncio.create_task(indexing_coro)
                return {
                    "status": "started",
                    "operation_id": operation_id,
                    "message": f"Directory indexing started for {dir_path}.",
                    "important": "Directory indexing runs in the background. Wait for completion before using search, find_similar, analyze_impact, or other analysis tools. Entities and relationships are only available after indexing completes.",
                    "how_to_check": "Use get_events(session_id, event_types=['indexing_completed', 'indexing_failed']) to check if indexing finished. Look for an event with operation_id matching this response.",
                    "estimated_time": "Depends on directory size. Small directories: seconds. Large codebases: minutes."
                }

        elif content_type == "text":
            # Index raw text content
            # For text, we create a synthetic parsed document
            from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk

            parsed_doc = ParsedDocument(
                doc_id=f"text_input_{project_id}",
                file_path="<text_input>",
                chunks=[
                    ParserChunk(
                        content=source,
                        line_start=1,
                        line_end=source.count("\n") + 1,
                        symbols=[],
                        relationships=[],
                        metadata={}
                    )
                ]
            )

            try:
                await indexing_pipeline.process_document(parsed_doc)
            except SchemaValidationError as e:
                # Handle schema validation errors with detailed information
                correlation_id = get_correlation_id()

                text_error_details: Dict[str, Any] = {
                    "error": "Schema validation failed",
                    "content_type": "text",
                    "table": e.table_name,
                    "correlation_id": correlation_id,
                }

                # Add field mapping hints
                if e.missing_fields:
                    text_error_details["missing_fields"] = e.missing_fields
                    text_error_details["hint"] = (
                        "The text input is missing required database fields. "
                        "This may indicate a schema mismatch."
                    )

                if e.type_mismatches:
                    text_error_details["type_mismatches"] = [
                        {"field": field, "expected": expected, "actual": actual}
                        for field, expected, actual in e.type_mismatches
                    ]

                logger.error(
                    "Schema validation failed for text input: %s (correlation_id: %s)",
                    str(e),
                    correlation_id,
                    extra=text_error_details
                )

                return {
                    "status": "failed",
                    "error": str(e),
                    "error_type": "schema_validation",
                    "details": text_error_details
                }

            # Track success
            await event_system.emit(
                "mcp.tool.completed",
                source="mcp_tool",
                tool_name="add_knowledge",
                session_id=session_id,
                items_processed=1
            )

            return {
                "status": "completed",
                "items_processed": 1,
                "chunks_created": 1,
                "content_type": "text"
            }

        else:
            return await MCPErrorHandler.handle(
                error=Exception(f"Invalid content_type: {content_type}"),
                context={
                    "session_id": session_id,
                    "content_type": content_type,
                    "source": source
                },
                services=services
            )

    except Exception as e:
        # Track failure
        await event_system.emit(
            "mcp.tool.failed",
            source="mcp_tool",
            tool_name="add_knowledge",
            error=str(e)
        )
        logger.error("Failed to add knowledge: %s", e, exc_info=True)
        
        # Enhanced error response with troubleshooting
        from agentic_inquiry.correlation import get_correlation_id
        from agentic_inquiry.exceptions import ParsingError
        
        correlation_id = get_correlation_id()
        error_type = type(e).__name__
        
        # Build detailed error response
        error_response: Dict[str, Any] = {
            "status": "failed",
            "error": str(e),
            "error_type": error_type,
            "correlation_id": correlation_id,
            "context": {
                "session_id": session_id,
                "content_type": content_type,
                "source": source
            }
        }
        
        # Add specific troubleshooting based on error type
        if isinstance(e, ParsingError):
            error_response["troubleshooting"] = {
                "possible_causes": [
                    "File format is not supported by available parsers",
                    "File contains syntax errors or invalid structure",
                    "File encoding is not UTF-8 or is corrupted",
                    "Parser failed to handle specific language constructs"
                ],
                "next_steps": [
                    "Check if the file extension is supported (.py, .js, .ts, .md, etc.)",
                    "Verify the file is valid and can be opened in an editor",
                    "Check file encoding (should be UTF-8)",
                    "Try indexing a simpler file to isolate the issue",
                    f"Review logs with correlation_id: {correlation_id}"
                ],
                "supported_formats": [
                    "Code: .py, .js, .ts, .jsx, .tsx, .java, .cpp, .c, .h, .cs, .go, .rs, .rb, .php",
                    "Documentation: .md, .rst, .txt",
                    "Documents: .pdf, .docx, .html"
                ]
            }
        elif "permission" in str(e).lower():
            error_response["troubleshooting"] = {
                "possible_causes": [
                    "Insufficient file system permissions",
                    "File is locked by another process",
                    "Directory permissions prevent access"
                ],
                "next_steps": [
                    "Check file permissions with 'ls -la' (Unix) or file properties (Windows)",
                    "Ensure the file is not open in another application",
                    "Verify you have read access to the file and parent directories",
                    "Try running with appropriate permissions"
                ]
            }
        else:
            error_response["troubleshooting"] = {
                "possible_causes": [
                    "Unexpected error during indexing",
                    "Database connection issue",
                    "Memory or resource constraint",
                    "Internal processing error"
                ],
                "next_steps": [
                    "Check system resources (memory, disk space)",
                    "Review detailed logs for more information",
                    "Try indexing a smaller file or directory",
                    "Restart the service if the issue persists",
                    f"Report issue with correlation_id: {correlation_id}"
                ]
            }
        
        error_response["suggestions"] = [
            "Try: Verifying the file or directory exists and is accessible",
            "Try: Checking file format is supported",
            "Try: Reviewing logs for detailed error information",
            f"Try: Using correlation_id {correlation_id} when reporting issues"
        ]
        
        return error_response


__all__ = ["add_knowledge"]
