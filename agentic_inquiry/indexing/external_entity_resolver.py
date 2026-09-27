"""Resolver for external/unresolved entity references.

This module handles categorization and ID generation for symbols that
cannot be resolved to entities within the indexed codebase.

Design principles:
- Language-agnostic by default
- Full context passed for future language-specific handlers
- IDs include language to prevent cross-language collisions
- Metadata validated to LanceDB-compatible primitives only
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ExternalCategory(str, Enum):
    """Categories for external/unresolved entities.

    Simplified to two categories to avoid incorrect heuristic-based
    distinctions between stdlib and third-party libraries.
    """

    BUILTIN = "builtin"  # Likely language built-in (print, len, console.log)
    EXTERNAL = "external"  # Everything else (stdlib, libraries, unknown)


@dataclass
class ExternalEntityInfo:
    """Information about an external/unresolved entity.

    Attributes:
        entity_id: Unique identifier (includes language to prevent collisions)
        name: Original symbol name
        name_normalized: Sanitized name used in ID generation
        entity_type: Type of entity (external_function, external_class, etc.)
        category: Category (builtin or external)
        language: Source language
        virtual_path: Virtual file path for the entity
        confidence: Confidence in the categorization (0.0-1.0)
        metadata: Flattened metadata (primitives only)
    """

    entity_id: str
    name: str
    name_normalized: str
    entity_type: str
    category: ExternalCategory
    language: str
    virtual_path: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CategorizationResult:
    """Result from a language-specific categorization."""

    category: ExternalCategory
    confidence: float


class LanguageHandler:
    """Base class for language-specific categorization handlers.

    Subclass this to add language-specific knowledge about builtins
    and common patterns.

    Example for Python:
        class PythonHandler(LanguageHandler):
            BUILTINS = {"print", "len", "str", "int", ...}

            def categorize(self, target_name, ...):
                if target_name in self.BUILTINS:
                    return CategorizationResult(ExternalCategory.BUILTIN, 0.95)
                return None  # Fall back to heuristics
    """

    def categorize(
        self,
        target_name: str,
        target_type: str,
        source_file: str,
        metadata: Dict[str, Any],
    ) -> Optional[CategorizationResult]:
        """Categorize an external reference.

        Args:
            target_name: Symbol name
            target_type: Symbol type
            source_file: Source file path
            metadata: Additional metadata

        Returns:
            CategorizationResult if handled, None to fall back to heuristics
        """
        return None  # Default: fall back to heuristics


class ExternalEntityResolver:
    """Resolves external/unresolved entity references.

    This resolver determines how to categorize and identify external
    symbols that are referenced but not defined in the indexed codebase.

    Args:
        project_hash: Hash of the project for ID generation

    Example:
        resolver = ExternalEntityResolver(project_hash="abc123")
        info = resolver.resolve(
            target_name="json.loads",
            target_type="function",
            language="python",
            source_file="config.py",
        )
        # info.entity_id = "external::abc123::python::json_loads"
    """

    # Characters that need normalization in entity IDs
    _NORMALIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_]")

    def __init__(self, project_hash: str):
        self.project_hash = project_hash
        self._language_handlers: Dict[str, LanguageHandler] = {}

    def register_language_handler(
        self, language: str, handler: LanguageHandler
    ) -> None:
        """Register a language-specific handler for categorization.

        Args:
            language: Language identifier (e.g., "python", "typescript")
            handler: Handler instance for language-specific logic
        """
        self._language_handlers[language.lower()] = handler
        logger.debug("Registered language handler for %s", language)

    def resolve(
        self,
        target_name: str,
        target_type: str,
        language: str = "",
        source_file: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExternalEntityInfo:
        """Resolve an external entity reference.

        Args:
            target_name: Name of the unresolved symbol (e.g., "json.loads", "print")
            target_type: Type from parser (e.g., "function", "class", "module")
            language: Source language (e.g., "python", "typescript", "go")
            source_file: Path to the source file containing the reference
            metadata: Additional metadata from the parser/relationship

        Returns:
            ExternalEntityInfo with ID, category, and other details
        """
        metadata = metadata or {}

        # Normalize language to lowercase, default to "unknown"
        language = (language or "").lower() or "unknown"

        # Check for language-specific handler first
        handler = self._language_handlers.get(language)
        if handler:
            result = handler.categorize(target_name, target_type, source_file, metadata)
            if result is not None:
                return self._build_entity_info(
                    target_name=target_name,
                    target_type=target_type,
                    language=language,
                    category=result.category,
                    confidence=result.confidence,
                    metadata=metadata,
                )

        # Fall back to language-agnostic heuristics
        category, confidence = self._categorize_heuristic(target_name, target_type)

        return self._build_entity_info(
            target_name=target_name,
            target_type=target_type,
            language=language,
            category=category,
            confidence=confidence,
            metadata=metadata,
        )

    def _categorize_heuristic(
        self,
        target_name: str,
        target_type: str,
    ) -> Tuple[ExternalCategory, float]:
        """Apply language-agnostic heuristics for categorization.

        Simple heuristic: single lowercase word < 15 chars is likely a builtin.
        Everything else is categorized as external.

        We intentionally avoid trying to distinguish stdlib from third-party
        libraries without language-specific knowledge, as heuristics are
        unreliable across 40+ languages.

        Args:
            target_name: Symbol name
            target_type: Symbol type

        Returns:
            Tuple of (category, confidence)
        """
        # Check for namespace separators (indicates module/package, not builtin)
        has_namespace = any(sep in target_name for sep in [".", "::", "/", "\\"])

        # Simple lowercase word without namespace - likely a builtin
        if not has_namespace and target_name.islower() and len(target_name) < 15:
            return ExternalCategory.BUILTIN, 0.6

        # Everything else is external (we don't try to distinguish stdlib vs library)
        return ExternalCategory.EXTERNAL, 0.4

    def _build_entity_info(
        self,
        target_name: str,
        target_type: str,
        language: str,
        category: ExternalCategory,
        confidence: float,
        metadata: Dict[str, Any],
    ) -> ExternalEntityInfo:
        """Build the ExternalEntityInfo object.

        Args:
            target_name: Original symbol name
            target_type: Symbol type from parser
            language: Source language
            category: Determined category
            confidence: Confidence in categorization
            metadata: Additional metadata (will be flattened)

        Returns:
            ExternalEntityInfo instance
        """
        # Normalize name for stable ID generation
        name_normalized = self._normalize_name(target_name)

        # Generate entity ID with language to prevent cross-language collisions
        entity_id = f"external::{self.project_hash}::{language}::{name_normalized}"

        # Map parser types to external entity types
        entity_type = self._map_entity_type(target_type)

        # Generate virtual path
        virtual_path = f"{category.value}://{language}/{name_normalized}"

        # Flatten metadata to primitives only (LanceDB constraint)
        flat_metadata = self._flatten_metadata(
            {
                "original_name": target_name,
                "category": category.value,
                "confidence": confidence,
                "language": language,
                **metadata,
            }
        )

        return ExternalEntityInfo(
            entity_id=entity_id,
            name=target_name,
            name_normalized=name_normalized,
            entity_type=entity_type,
            category=category,
            language=language,
            virtual_path=virtual_path,
            confidence=confidence,
            metadata=flat_metadata,
        )

    def _normalize_name(self, name: str) -> str:
        """Normalize a symbol name for use in entity IDs.

        Handles special characters like generics, operators, namespaces.

        Args:
            name: Original symbol name (e.g., "List<String>", "operator<<")

        Returns:
            Normalized name safe for IDs (e.g., "List_String_", "operator__")
        """
        # Replace common namespace separators with underscore
        normalized = (
            name.replace("::", "_")
            .replace(".", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )

        # Replace other special characters
        normalized = self._NORMALIZE_PATTERN.sub("_", normalized)

        # Collapse multiple underscores
        normalized = re.sub(r"_+", "_", normalized)

        # Remove leading/trailing underscores
        normalized = normalized.strip("_")

        # If name is too long, hash it
        if len(normalized) > 100:
            name_hash = hashlib.md5(name.encode()).hexdigest()[:16]
            normalized = f"{normalized[:50]}_{name_hash}"

        # Ensure non-empty
        return normalized or "unnamed"

    def _map_entity_type(self, target_type: str) -> str:
        """Map parser target type to external entity type.

        Args:
            target_type: Type from parser (function, class, module, etc.)

        Returns:
            External entity type string
        """
        if not target_type:
            return "external_symbol"

        target_type_lower = target_type.lower()

        type_mapping = {
            # Functions
            "function": "external_function",
            "method": "external_function",
            "procedure": "external_function",
            "subroutine": "external_function",
            # Classes/Types
            "class": "external_class",
            "interface": "external_class",
            "struct": "external_class",
            "type": "external_class",
            "trait": "external_class",
            "protocol": "external_class",
            "enum": "external_class",
            # Modules
            "module": "external_module",
            "package": "external_module",
            "namespace": "external_module",
            "crate": "external_module",
            # Values
            "variable": "external_value",
            "constant": "external_value",
            "const": "external_value",
            "val": "external_value",
        }
        return type_mapping.get(target_type_lower, "external_symbol")

    def _flatten_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten metadata to LanceDB-compatible primitives only.

        LanceDB metadata constraints: str, int, float, bool, None only.
        No lists, dicts, or complex objects.

        Args:
            metadata: Input metadata (may contain nested structures)

        Returns:
            Flattened metadata with primitives only
        """
        result: Dict[str, Any] = {}

        for key, value in metadata.items():
            if value is None:
                result[key] = None
            elif isinstance(value, (str, int, float, bool)):
                result[key] = value
            elif isinstance(value, (list, tuple)):
                # Convert lists to comma-separated string
                if all(isinstance(v, (str, int, float, bool)) for v in value):
                    result[key] = ",".join(str(v) for v in value)
                else:
                    result[key] = str(value)
            elif isinstance(value, dict):
                # Flatten nested dict with prefix
                for nested_key, nested_value in value.items():
                    flat_key = f"{key}_{nested_key}"
                    if isinstance(nested_value, (str, int, float, bool, type(None))):
                        result[flat_key] = nested_value
                    else:
                        result[flat_key] = str(nested_value)
            else:
                # Convert anything else to string
                result[key] = str(value)

        return result
