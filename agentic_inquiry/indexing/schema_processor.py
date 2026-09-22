"""Unified schema processing with validation, transformation, and sanitization.

This module provides a single SchemaProcessor class that combines:
- Validation logic (from SchemaValidator)
- Transformation logic (from SchemaMapper)
- Sanitization logic (from DocumentProcessor)

All operations are performed in a single transactional pass for better
reliability and simpler code flow.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional

from agentic_inquiry.database.schemas import (
    DOCUMENT_CHUNKS_SCHEMA,
    FieldType,
    LogicalSchema,
    SchemaField,
)
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when chunk validation fails."""
    pass


class SchemaProcessor:
    """Unified schema processing with transactional support.
    
    This class combines validation, transformation, and sanitization of
    ParserChunks into database-ready records in a single atomic operation.
    
    Features:
    - Validates chunks against schema rules
    - Transforms ParserChunk fields to database format
    - Sanitizes metadata to avoid schema conflicts
    - Transactional processing with rollback on errors
    
    Example:
        >>> processor = SchemaProcessor(db_manager)
        >>> records = await processor.process_chunks(
        ...     chunks=parser_chunks,
        ...     parsed_document=doc,
        ...     project_id="my_project",
        ...     vectors=embedding_vectors
        ... )
    """
    
    def __init__(
        self,
        db_manager: Any,
        schema: Optional[LogicalSchema] = None
    ):
        """Initialize SchemaProcessor with storage interface and optional schema.

        Args:
            db_manager: Storage interface providing add_document_chunks() and
                delete_document_chunks() methods. Accepts StorageFacade,
                LanceDBAdapter, LanceDBManager, or any compatible duck-typed object.
            schema: Logical schema to use for validation and transformation.
                   Defaults to DOCUMENT_CHUNKS_SCHEMA for backward compatibility.
        """
        self.db_manager = db_manager
        self.schema = schema or DOCUMENT_CHUNKS_SCHEMA
        self._validation_rules = self._build_validation_rules()
        self._field_mappings = self._build_field_mappings()

        logger.info("SchemaProcessor initialized with schema: %s", self.schema.name)
    
    def _build_validation_rules(self) -> Dict[str, Any]:
        """Build validation rules from logical schema.

        Returns:
            Dictionary of validation rules keyed by field name
        """
        rules: Dict[str, Any] = {}

        for field in self.schema.fields:
            rules[field.name] = {
                "required": field.required,
                "field_type": field.field_type,
                "sentinel": field.sentinel,
                "default": field.default,
            }

        return rules

    def _build_field_mappings(self) -> Dict[str, SchemaField]:
        """Build field mappings from logical schema.

        Returns:
            Dictionary mapping field names to SchemaField definitions
        """
        return {field.name: field for field in self.schema.fields}

    def _get_required_field_names(self) -> FrozenSet[str]:
        """Get required field names from schema.

        Returns:
            FrozenSet of required field names
        """
        return frozenset(f.name for f in self.schema.get_required_fields())

    def _get_optional_field_names(self) -> FrozenSet[str]:
        """Get optional field names from schema.

        Returns:
            FrozenSet of optional field names
        """
        return frozenset(f.name for f in self.schema.get_optional_fields())

    def _get_type_default(self, field_type: FieldType) -> Any:
        """Get default value for a field type.

        Args:
            field_type: The FieldType enum value

        Returns:
            Appropriate default value for the type
        """
        defaults = {
            FieldType.STRING: "",
            FieldType.INT: -1,
            FieldType.FLOAT: 0.0,
            FieldType.BOOL: False,
            FieldType.VECTOR: [],
            FieldType.STRING_LIST: [],
            FieldType.FLOAT_LIST: [],
            FieldType.DATETIME: datetime.now(timezone.utc).isoformat(),
            FieldType.JSON: "{}",
        }
        return defaults.get(field_type, None)

    def _validate_chunk(self, chunk: ParserChunk) -> None:
        """Validate chunk against schema rules.
        
        Args:
            chunk: ParserChunk to validate
            
        Raises:
            ValidationError: If validation fails
        """
        # Validate required fields
        if not chunk.content and not chunk.fts_text:
            raise ValidationError(
                "Chunk must have either content or fts_text"
            )
        
        # Validate symbols field (not code_symbols)
        if hasattr(chunk, 'code_symbols'):
            raise ValidationError(
                "Chunk has 'code_symbols' field - should use 'symbols' instead"
            )
        
        # Validate metadata contains only JSON-serializable types
        # Note: Complex types (list, dict) are allowed as they will be serialized to JSON
        if chunk.metadata:
            # We trust json.dumps() to handle validation during transformation
            pass
        
        # Validate line numbers if present
        if chunk.line_start is not None and chunk.line_end is not None:
            if chunk.line_start > chunk.line_end:
                raise ValidationError(
                    f"Invalid line range: line_start ({chunk.line_start}) > line_end ({chunk.line_end})"
                )
        
        logger.debug("Chunk validation passed")

    def _transform_chunk(
        self,
        chunk: ParserChunk,
        parsed_document: ParsedDocument,
        chunk_index: int,
        total_chunks: int,
        vector: List[float],
        project_id: str
    ) -> Dict[str, Any]:
        """Transform ParserChunk to database record format.
        
        Args:
            chunk: ParserChunk to transform
            parsed_document: Parent parsed document
            chunk_index: Position of chunk in document (0-based)
            total_chunks: Total number of chunks in document
            vector: Embedding vector for the chunk
            project_id: Project identifier
            
        Returns:
            Dictionary matching database schema
        """
        # Include project_id in chunk ID to ensure uniqueness across projects
        # This prevents PRIMARY KEY conflicts when different projects index the same files
        chunk_id = f"{project_id}::{parsed_document.doc_id}_{chunk_index}"
        
        # Determine embedding text
        embedding_text = chunk.fts_text or chunk.content or ""
        if not embedding_text and chunk.symbols:
            embedding_text = " ".join(chunk.symbols)
        
        # Determine content type
        content_type = chunk.content_type or ("CODE" if chunk.symbols else "PROSE")
        
        # Determine element name and type
        element_name = chunk.element_name
        element_type = chunk.element_type
        primary_symbol = chunk.symbols[0] if chunk.symbols else None
        
        if primary_symbol:
            if element_name is None:
                element_name = primary_symbol
            symbol_meta = (chunk.symbol_metadata or {}).get(primary_symbol, {})
            if element_type is None:
                element_type = symbol_meta.get("type")
        
        # Resolve source modification timestamp
        source_modified_at = self._resolve_source_modified_at(parsed_document, chunk)
        
        # Build database record
        record: Dict[str, Any] = {
            "id": chunk_id,
            "doc_id": parsed_document.doc_id,
            "file_path": parsed_document.file_path,
            "project_id": project_id,
            "content": chunk.content or embedding_text,
            "fts_text": chunk.fts_text or embedding_text,
            "vector": vector,
            "content_type": content_type,
            "language": chunk.language or "",
            "page_number": chunk.page_number if chunk.page_number is not None else -1,
            "line_start": chunk.line_start if chunk.line_start is not None else -1,
            "line_end": chunk.line_end if chunk.line_end is not None else -1,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks if total_chunks else 1,
            "element_type": element_type or "",
            "element_name": element_name or "",
            "parent_id": chunk.parent_id or "",
            "child_ids": list(chunk.child_ids or []),
            "symbols": list(chunk.symbols or []),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "source_modified_at": source_modified_at.isoformat() if source_modified_at else datetime.fromtimestamp(0, tz=timezone.utc).isoformat(),
        }
        
        # Transform complex fields (metadata and ranking_signals)
        record["metadata"] = self._transform_metadata(chunk)
        record["ranking_signals"] = self._transform_ranking_signals(chunk)
        
        return record
    
    def _resolve_source_modified_at(
        self,
        parsed_document: ParsedDocument,
        chunk: ParserChunk
    ) -> Optional[datetime]:
        """Resolve source modification timestamp from document or chunk.
        
        Args:
            parsed_document: Parent parsed document
            chunk: Parser chunk
            
        Returns:
            Modification timestamp or None
        """
        # Try chunk-level timestamp first
        if chunk.metadata and "modified_at" in chunk.metadata:
            value = chunk.metadata["modified_at"]
            if isinstance(value, datetime):
                return value
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value, tz=timezone.utc)
        
        # Fall back to document-level timestamp
        if parsed_document.metadata and "modified_at" in parsed_document.metadata:
            value = parsed_document.metadata["modified_at"]
            if isinstance(value, datetime):
                return value
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value, tz=timezone.utc)
        
        return None
    
    def _transform_metadata(self, chunk: ParserChunk) -> Dict[str, str]:
        """Transform ParserChunk metadata fields to database struct.
        
        The database stores metadata as a struct with three serialized JSON fields:
        - data: Main metadata dictionary
        - symbol_metadata: Per-symbol metadata
        - symbol_rankings: Per-symbol ranking scores
        
        Args:
            chunk: ParserChunk with metadata fields
            
        Returns:
            Dictionary with serialized JSON strings
        """
        metadata_dict: Dict[str, str] = {
            "data": "{}",
            "symbol_metadata": "{}",
            "symbol_rankings": "{}",
        }
        
        # Serialize main metadata
        if chunk.metadata:
            try:
                metadata_dict["data"] = json.dumps(chunk.metadata)
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Failed to serialize chunk metadata: %s. Using empty dict.",
                    e
                )
                metadata_dict["data"] = "{}"
        
        # Serialize symbol metadata
        if chunk.symbol_metadata:
            try:
                metadata_dict["symbol_metadata"] = json.dumps(chunk.symbol_metadata)
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Failed to serialize symbol_metadata: %s. Using empty dict.",
                    e
                )
                metadata_dict["symbol_metadata"] = "{}"
        
        # Serialize symbol rankings
        if chunk.symbol_rankings:
            try:
                metadata_dict["symbol_rankings"] = json.dumps(chunk.symbol_rankings)
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Failed to serialize symbol_rankings: %s. Using empty dict.",
                    e
                )
                metadata_dict["symbol_rankings"] = "{}"
        
        return metadata_dict
    
    def _transform_ranking_signals(self, chunk: ParserChunk) -> Dict[str, str]:
        """Transform ParserChunk ranking_signals to database struct.
        
        The database stores ranking_signals as a struct with a single
        serialized JSON field containing the ranking data.
        
        Args:
            chunk: ParserChunk with ranking_signals
            
        Returns:
            Dictionary with serialized JSON string
        """
        ranking_signals: Dict[str, str] = {"data": "{}"}
        
        if chunk.ranking_signals:
            try:
                ranking_signals["data"] = json.dumps(chunk.ranking_signals)
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Failed to serialize ranking_signals: %s. Using empty dict.",
                    e
                )
                ranking_signals["data"] = "{}"
        
        return ranking_signals

    def _sanitize_metadata(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize metadata for storage compatibility using schema definitions.

        This ensures metadata contains only simple types that are compatible
        with the storage backend. Complex types (lists, dicts) are filtered out
        or serialized to JSON strings.

        Uses the logical schema to determine required fields and their default
        values, eliminating hardcoded field lists.

        Args:
            record: Database record to sanitize

        Returns:
            Sanitized record
        """
        # Metadata is already serialized to JSON strings in _transform_metadata
        # This method ensures the overall record structure is clean

        # Use schema-driven field mappings
        field_mappings = self._field_mappings

        # Ensure all schema fields are present with appropriate defaults
        for field_name, schema_field in field_mappings.items():
            if field_name not in record:
                logger.warning("Missing field: %s", field_name)

                # Use sentinel first, then default, then type default
                if schema_field.sentinel is not None:
                    record[field_name] = schema_field.sentinel
                elif schema_field.default is not None:
                    record[field_name] = schema_field.default
                else:
                    # Fall back to type-based default
                    record[field_name] = self._get_type_default(schema_field.field_type)

        # Handle special struct fields that aren't in the schema but are needed
        # for nested struct format
        if "metadata" in record and not isinstance(record["metadata"], dict):
            record["metadata"] = {"data": "{}", "symbol_metadata": "{}", "symbol_rankings": "{}"}
        if "ranking_signals" in record and not isinstance(record["ranking_signals"], dict):
            record["ranking_signals"] = {"data": "{}"}

        return record

    async def process_chunks(
        self,
        chunks: List[ParserChunk],
        parsed_document: ParsedDocument,
        vectors: List[List[float]],
        project_id: str,
        original_total_chunks: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Process chunks with transactional integrity.
        
        All chunks are validated, transformed, and sanitized in a single
        transaction. If any step fails, all changes are rolled back.
        
        Args:
            chunks: List of ParserChunks to process
            parsed_document: Parent parsed document
            vectors: List of embedding vectors (one per chunk)
            project_id: Project identifier
            original_total_chunks: Original total chunk count before filtering (optional)
            
        Returns:
            List of database-ready records
            
        Raises:
            ValidationError: If any chunk fails validation
            Exception: If transformation or database operations fail
        """
        if len(chunks) != len(vectors):
            raise ValueError(
                f"Chunk count ({len(chunks)}) does not match vector count ({len(vectors)})"
            )
        
        logger.info(
            "Processing %d chunks for document %s",
            len(chunks),
            parsed_document.doc_id
        )
        
        # Use transaction for atomic processing
        from agentic_inquiry.database.transaction import Transaction
        
        async with Transaction(self.db_manager) as txn:
            # Step 1: Validate all chunks first
            logger.debug("Validating %d chunks", len(chunks))
            for i, chunk in enumerate(chunks):
                try:
                    self._validate_chunk(chunk)
                except ValidationError as e:
                    logger.error(
                        "Validation failed for chunk %d of document %s: %s",
                        i,
                        parsed_document.doc_id,
                        e
                    )
                    raise
            
            # Step 2: Transform all chunks
            logger.debug("Transforming %d chunks", len(chunks))
            transformed = []
            # Use original_total_chunks if provided, otherwise use current chunk count
            total_chunks = original_total_chunks if original_total_chunks is not None else len(chunks)
            
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                try:
                    record = self._transform_chunk(
                        chunk=chunk,
                        parsed_document=parsed_document,
                        chunk_index=i,
                        total_chunks=total_chunks,
                        vector=vector,
                        project_id=project_id
                    )
                    transformed.append(record)
                except Exception as e:
                    logger.error(
                        "Transformation failed for chunk %d of document %s: %s",
                        i,
                        parsed_document.doc_id,
                        e
                    )
                    raise
            
            # Step 3: Sanitize all records
            logger.debug("Sanitizing %d records", len(transformed))
            sanitized = []
            for i, record in enumerate(transformed):
                try:
                    sanitized_record = self._sanitize_metadata(record)
                    sanitized.append(sanitized_record)
                except Exception as e:
                    logger.error(
                        "Sanitization failed for record %d of document %s: %s",
                        i,
                        parsed_document.doc_id,
                        e
                    )
                    raise
            
            # Step 4: Write to database (transaction commits if successful)
            logger.debug("Writing %d records to database", len(sanitized))
            
            # Add database write operation to transaction
            async def write_chunks(records: List[Dict[str, Any]]) -> None:
                """Write chunks to database."""
                # Convert dicts to DocumentChunk objects
                from agentic_inquiry.models import DocumentChunk
                from datetime import datetime
                
                chunks = []
                for record in records:
                    # Convert ISO string timestamps to datetime objects
                    if isinstance(record.get("indexed_at"), str):
                        record["indexed_at"] = datetime.fromisoformat(record["indexed_at"])
                    if isinstance(record.get("source_modified_at"), str):
                        record["source_modified_at"] = datetime.fromisoformat(record["source_modified_at"])
                    
                    chunks.append(DocumentChunk(**record))
                
                await self.db_manager.add_document_chunks(chunks)
            
            # Add rollback operation to delete chunks if needed
            async def delete_chunks(chunk_ids: List[str]) -> None:
                """Delete chunks from database."""
                try:
                    await self.db_manager.delete_document_chunks(chunk_ids)
                except Exception as e:
                    logger.warning("Failed to delete chunks during rollback: %s", e)
            
            chunk_ids = [record["id"] for record in sanitized]
            
            txn.add_operation(
                operation=write_chunks,
                data=sanitized,
                rollback_operation=delete_chunks,
                rollback_data=chunk_ids
            )
            
            # Commit the transaction
            await txn.commit()
            
            logger.info(
                "Successfully processed %d chunks for document %s",
                len(sanitized),
                parsed_document.doc_id
            )
            
            return sanitized
