"""Custom exceptions for Agentic Inquiry.

This module defines the exception hierarchy for the Agentic Inquiry system.
All custom exceptions inherit from AgenticInquiryError, which provides a
common base for error handling and allows callers to catch all
Agentic Inquiry-specific errors with a single except clause.

Exception Hierarchy:
    AgenticInquiryError (base)
    ├── ConfigurationError
    │   └── StoragePathError
    ├── StorageError
    ├── ParsingError
    └── ResolutionError

Usage:
    from agentic_inquiry.exceptions import ConfigurationError, ParsingError
    
    # Raise with context
    try:
        parse_file(path)
    except IOError as e:
        raise ParsingError(f"Failed to read file {path}") from e
    
    # Catch all Agentic Inquiry errors
    try:
        process_document(doc)
    except AgenticInquiryError as e:
        logger.error("Processing failed: %s", e)
"""

from typing import Any, Optional


class AgenticInquiryError(Exception):
    """Base exception for all Agentic Inquiry errors.
    
    All custom exceptions in the Agentic Inquiry system inherit from this class.
    This allows callers to catch all Agentic Inquiry-specific errors with a
    single except clause while still being able to catch specific error
    types when needed.
    
    Example:
        try:
            process_document(doc)
        except AgenticInquiryError as e:
            # Catches all Agentic Inquiry errors
            logger.error("Processing failed: %s", e)
    """
    pass


class ConfigurationError(AgenticInquiryError):
    """Raised when configuration is invalid or cannot be loaded.
    
    This exception is raised when:
    - Configuration files cannot be found or read
    - Configuration validation fails (schema or field-level)
    - Required configuration values are missing
    - Configuration values are invalid (e.g., weights don't sum to 1.0)
    
    Example:
        if abs(vector_weight + fts_weight - 1.0) > 0.001:
            raise ConfigurationError(
                f"Hybrid search weights must sum to 1.0, "
                f"got {vector_weight + fts_weight}"
            )
    """
    pass


class StoragePathError(ConfigurationError):
    """Raised when storage paths cannot be resolved or created.
    
    This exception is raised when:
    - Storage directories cannot be created (permissions, disk space)
    - Storage paths contain invalid characters (null bytes)
    - Storage paths are inaccessible
    
    Note: This is a subclass of ConfigurationError since storage path
    issues are typically configuration problems.
    
    Example:
        try:
            os.makedirs(storage_path, exist_ok=True)
        except PermissionError as e:
            raise StoragePathError(
                f"Cannot create storage directory: {storage_path}"
            ) from e
    """
    pass


class StorageError(AgenticInquiryError):
    """Raised when storage operations fail.
    
    This exception is raised when:
    - Database operations fail (connection, query, write)
    - Vector database operations fail
    - Cache operations fail
    - File system operations fail during indexing
    
    Example:
        try:
            await db_manager.add_document_chunks(chunks)
        except Exception as e:
            raise StorageError(
                f"Failed to store document chunks: {e}"
            ) from e
    """
    pass


class ParsingError(AgenticInquiryError):
    """Raised when document parsing fails.
    
    This exception is raised when:
    - No parser can handle a file
    - All parsers fail for a file
    - Parser output validation fails
    - File cannot be read or decoded
    
    Example:
        if not any(parser.can_parse(path) for parser in parsers):
            raise ParsingError(
                f"No parser available for file: {path}"
            )
    """
    pass


class DocumentParsingError(ParsingError):
    """Raised when document parsing fails for non-code documents.
    
    This exception is raised when:
    - Document parsing library (unstructured) fails
    - Document format is unsupported or corrupted
    - Document cannot be read or decoded
    - Element extraction fails
    
    Attributes:
        file_path: Path to the file that failed parsing (optional)
        parser_type: Type of parser that failed (e.g., "document", "pdf")
        original_error: The underlying exception that caused the failure
        
    Example:
        try:
            elements = partition(filename=file_path)
        except Exception as e:
            raise DocumentParsingError(
                f"Document parsing failed for {file_path}: {e}",
                file_path=file_path,
                parser_type="document",
                original_error=e
            ) from e
    """
    
    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        parser_type: Optional[str] = None,
        original_error: Optional[Exception] = None
    ):
        """Initialize DocumentParsingError.
        
        Args:
            message: Error message describing what went wrong
            file_path: Path to the file that failed parsing
            parser_type: Type of parser that failed
            original_error: The underlying exception
        """
        super().__init__(message)
        self.file_path = file_path
        self.parser_type = parser_type
        self.original_error = original_error


class ResolutionError(AgenticInquiryError):
    """Raised when symbol or import resolution fails.
    
    This exception is raised when:
    - Import targets cannot be resolved
    - Symbol lookup fails
    - Relationship resolution fails
    - Cross-file references cannot be established
    
    Example:
        if not resolved_target:
            raise ResolutionError(
                f"Cannot resolve import '{target_name}' from {source_file}"
            )
    """
    pass


class SchemaValidationError(StorageError):
    """Raised when data doesn't match database schema.
    
    This exception is raised when:
    - Required fields are missing from records
    - Field types don't match expected types
    - Schema validation fails before database write
    
    Attributes:
        table_name: Name of the table being validated against
        missing_fields: List of missing required fields
        type_mismatches: List of (field, expected, actual) tuples
        
    Example:
        if missing_fields:
            raise SchemaValidationError(
                table_name="document_chunks",
                missing_fields=["id", "content"],
                type_mismatches=[]
            )
    """
    
    def __init__(
        self,
        table_name: str,
        missing_fields: Optional[list] = None,
        type_mismatches: Optional[list] = None,
        message: Optional[str] = None
    ):
        self.table_name = table_name
        self.missing_fields = missing_fields or []
        self.type_mismatches = type_mismatches or []
        
        if message is None:
            # Build default message
            parts = [f"Schema validation failed for table '{table_name}'"]
            
            if self.missing_fields:
                parts.append(f"Missing fields: {', '.join(self.missing_fields)}")
            
            if self.type_mismatches:
                mismatch_strs = [
                    f"{field} (expected {expected}, got {actual})"
                    for field, expected, actual in self.type_mismatches
                ]
                parts.append(f"Type mismatches: {', '.join(mismatch_strs)}")
            
            message = ". ".join(parts)
        
        super().__init__(message)


class ValidationError(AgenticInquiryError):
    """Raised when parameter validation fails with helpful context.
    
    This exception provides detailed information about validation failures,
    including the invalid value, valid options, and usage examples to help
    users quickly correct their input.
    
    Attributes:
        param_name: Name of the parameter that failed validation
        invalid_value: The value that was provided
        valid_values: List of valid values for the parameter
        example: Example of correct usage
        
    Example:
        raise ValidationError(
            param_name="content_type",
            invalid_value="code",
            valid_values=["file", "directory", "text"],
            example="content_type='file'"
        )
    """
    
    def __init__(
        self,
        param_name: str,
        invalid_value: Any,
        valid_values: list[str],
        example: Optional[str] = None
    ):
        """Initialize ValidationError with helpful context.
        
        Args:
            param_name: Name of the parameter that failed validation
            invalid_value: The value that was provided
            valid_values: List of valid values for the parameter
            example: Optional example of correct usage
        """
        self.param_name = param_name
        self.invalid_value = invalid_value
        self.valid_values = valid_values
        self.example = example
        
        # Build detailed error message
        message = (
            f"Invalid {param_name}: '{invalid_value}'. "
            f"Valid values: {', '.join(valid_values)}."
        )
        if example:
            message += f" Example: {example}"
        
        super().__init__(message)


# Export all exception classes
__all__ = [
    "AgenticInquiryError",
    "ConfigurationError",
    "StoragePathError",
    "StorageError",
    "ParsingError",
    "DocumentParsingError",
    "ResolutionError",
    "SchemaValidationError",
    "ValidationError",
]
