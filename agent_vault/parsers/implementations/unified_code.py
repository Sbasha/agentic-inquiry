"""Unified code parser that orchestrates multiple parsing strategies.

Migrated from akb_iq and adapted to work with the new ParserProtocol interface.
Uses tree-sitter with custom query files for language-specific parsing.
"""

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from agent_vault.exceptions import ParsingError

if TYPE_CHECKING:
    from agent_vault.database.lancedb_manager import LanceDBManager
    from agent_vault.embeddings.service import EmbeddingService
    from agent_vault.models.graph_entity import GraphEntity
from ...parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from .utils.languages import LanguageRegistry
from .utils.query_loader import QueryLoader

logger = logging.getLogger(__name__)

# Import tree-sitter libraries (required dependency)
try:
    import tree_sitter as ts
    from tree_sitter_language_pack import get_language, get_parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    logger.warning("tree-sitter not available - UnifiedCodeParser will not function")

# Import standalone C# support
try:
    import tree_sitter_c_sharp
    from tree_sitter import Language, Parser
    CSHARP_AVAILABLE = True
except ImportError:
    CSHARP_AVAILABLE = False
    logger.debug("tree-sitter-c-sharp not available")


# Configuration defaults
DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200


# Tree-sitter node types that introduce a callable/definition scope, across
# every grammar we ship a query for. A call is attributed to the nearest
# enclosing one; the matched node's (start_byte, end_byte) must line up with a
# `@code_*.def` capture so `calls_by_container` keys resolve to real elements.
# Only node types captured as processable `.def` elements belong here —
# notably NOT `arrow_function` (`@code_function.arrow`) or Rust `mod_item`
# (`@code_module`), which are not emitted as elements and would silently
# swallow the calls attributed to them. Node type names are unique per grammar,
# so a flat set needs no per-language dispatch.
_DEFINITION_NODE_TYPES = frozenset({
    # Python
    "function_definition", "class_definition",
    # JavaScript / TypeScript / TSX / JSX (class/interface_declaration shared
    # with Java)
    "function_declaration", "method_definition", "class_declaration",
    "interface_declaration",
    # Java / Apex
    "method_declaration", "constructor_declaration",
    "trigger_declaration", "enum_declaration",
    # Rust
    "function_item", "struct_item", "enum_item", "trait_item", "impl_item",
    # Ruby
    "method", "singleton_method", "class", "singleton_class", "module",
})

# For calls whose target sits in the `function` field (Python `call`; C-family
# / Go / Rust / TS / C# `call_expression`/`invocation_expression`), the func
# node may itself be a member/attribute accessor. Maps that accessor node type
# to the (object field(s), method-name field) pair to read from it. The object
# slot may be a tuple of candidate field names tried in order, because grammars
# that share an accessor node type name can name the receiver field differently
# (Rust `field_expression` uses `value`, C++'s uses `argument`).
_METHOD_ACCESSOR_FIELDS: Dict[str, tuple] = {
    "attribute": ("object", "attribute"),                  # Python
    "member_expression": ("object", "property"),           # JavaScript / TypeScript
    "field_expression": (("value", "argument"), "field"),  # Rust (value) / C++ (argument)
    "selector_expression": ("operand", "field"),           # Go
}


class CodeElement:
    """Represents a code element extracted from source."""

    def __init__(self, element_type: str, name: str, start_line: int, end_line: int, content: str, **metadata: Any) -> None:
        self.element_type = element_type
        self.name = name
        self.start_line = start_line
        self.end_line = end_line
        self.content = content
        self.metadata = metadata

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "element_type": self.element_type,
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
        }
        result.update(self.metadata)
        return result


class CodeUtilities:
    """Common utilities for code parsing."""

    @staticmethod
    def estimate_complexity(content: str) -> int:
        """Estimate code complexity (returns 1-10)."""
        complexity = 1
        # Count control structures
        complexity += content.count("if ")
        complexity += content.count("for ")
        complexity += content.count("while ")
        complexity += content.count("switch ")
        complexity += content.count("case ")
        return min(complexity, 10)

    @staticmethod
    def extract_name_from_line(line: str, patterns: List[str]) -> Optional[str]:
        """Extract name from a line using patterns."""
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                return match.group(1) if match.groups() else None
        return None

    @staticmethod
    def truncate_content(content: str, max_length: int = 500) -> str:
        """Truncate content to maximum length."""
        if len(content) > max_length:
            return content[:max_length] + "..."
        return content

    @staticmethod
    def get_element_type_mapping() -> Dict[str, str]:
        """Get standard element type mappings.

        Maps tree-sitter capture names to plain structural types.
        Domain context (e.g., "code") is stored separately in GraphEntity.domain.
        """
        return {
            "function": "function",
            "method": "method",  # Methods are within classes
            "class": "class",
            "struct": "struct",
            "interface": "interface",
            "trait": "interface",  # Traits are similar to interfaces
            "enum": "enum",
            "type": "type",
            "module": "module",
            "namespace": "namespace",
            "import": "import",  # Not an entity type, used for relationships
            "from_import": "from_import",  # Not an entity type, used for relationships
            "export": "export",  # Not an entity type, used for relationships
            "variable": "variable",
            "const": "variable",  # Constants are variables
            "constant": "variable",
            "field": "property",  # Fields are properties
            "property": "property",
            "constructor": "method",  # Constructors are methods within classes
            "decorator": "decorator",
            "annotation": "decorator",  # Annotations are decorators
            "parameter": "parameter",
            # Non-entity types (not stored as separate entities)
            "comment": "comment",
            "docstring": "docstring",
            "lambda": "function",  # Lambdas are anonymous functions
            "closure": "function",  # Closures are functions
        }


class TreeSitterCodeParser:
    """Tree-sitter parsing strategy using custom query files."""

    def __init__(self) -> None:
        """Initialize the parser."""
        self.query_loader = QueryLoader()
        self._parsers: Dict[str, Any] = {}
        logger.info("Initialized TreeSitterCodeParser with custom query extraction")

    def can_parse(self, language: str) -> bool:
        """Check if we have a query file for this language."""
        return self.query_loader.has_query(language)

    def parse_content(self, content: str, language: str, file_path: Path) -> List[Dict[str, Any]]:
        """Parse content using custom tree-sitter queries."""
        logger.debug("Using custom query extractor for %s file: %s", language, file_path)
        return self._parse_with_custom_logic(content, language, file_path)

    def _parse_with_custom_logic(self, content: str, language: str, file_path: Path) -> List[Dict[str, Any]]:
        """Parse using tree-sitter with custom queries."""
        parser = self._get_parser(language)
        if not parser:
            return []
        try:
            content_bytes = content.encode("utf-8")
            tree = parser.parse(content_bytes)
            return self._extract_with_query(tree, content, content_bytes, language)
        except Exception as e:
            logger.debug("Custom tree-sitter parsing failed for %s: %s", language, e, exc_info=True)
            return []

    def _get_parser(self, language: str) -> Optional[Any]:
        """Get or create a parser for the language."""
        if language in self._parsers:
            return self._parsers[language]

        try:
            # Special handling for C# using standalone package
            if language == "c_sharp" and CSHARP_AVAILABLE:
                parser = Parser(Language(tree_sitter_c_sharp.language()))
                self._parsers[language] = parser
                return parser

            # Map JSX/TSX to their base languages for parser
            parser_lang = language
            if language == "jsx":
                parser_lang = "javascript"
            elif language == "tsx":
                parser_lang = "typescript"

            # Use tree-sitter-language-pack for other languages
            parser = get_parser(parser_lang)  # type: ignore[arg-type]
            self._parsers[language] = parser
            return parser
        except Exception as e:
            logger.debug("Could not get parser for %s: %s", language, e, exc_info=True)
            return None

    def _extract_with_query(self, tree: Any, content: str, content_bytes: bytes, language: str) -> List[Dict[str, Any]]:
        """Extract elements using tree-sitter queries."""
        if not self.query_loader:
            logger.debug("No query loader available for %s", language)
            return []

        query_text = self.query_loader.load_query(language)
        if not query_text:
            logger.debug("No query text found for %s", language)
            return []

        try:
            # Special handling for C# language object
            if language == "c_sharp" and CSHARP_AVAILABLE:
                ts_language = Language(tree_sitter_c_sharp.language())
            else:
                # Map JSX/TSX to their base languages for queries
                query_lang = language
                if language == "jsx":
                    query_lang = "javascript"
                elif language == "tsx":
                    query_lang = "typescript"
                ts_language = get_language(query_lang)  # type: ignore[arg-type]

            if not ts_language:
                logger.debug("Could not get language object for %s", language)
                return []

            query = ts.Query(ts_language, query_text)

            # Use tree-sitter API
            cursor = ts.QueryCursor(query)
            matches = cursor.matches(tree.root_node)

            elements = []
            seen_nodes = set()
            # Track name captures to associate with their parent definitions
            name_captures = {}
            # Track calls by containing function/class for relationship extraction
            # Use byte positions as key for stability (Python id() changes between node references)
            calls_by_container: Dict[tuple, List[Dict[str, Any]]] = {}
            # De-dup calls by call-node byte span: a single call site must yield
            # one edge even when the query captures it under more than one pattern
            # (e.g. cpp.scm has two identical @call.method patterns, and a node may
            # be captured as both @call and @call.method). Definitions are de-duped
            # via seen_nodes below; calls need the same guard.
            seen_call_nodes: Set[tuple] = set()
            # Track class bases for inheritance relationships
            class_bases: Dict[tuple, List[str]] = {}

            # Convert matches to list so we can iterate multiple times
            matches_list = list(matches)

            # First pass: collect all name captures, calls, and bases across ALL matches
            for _pattern_index, captures_dict in matches_list:
                for capture_name, nodes in captures_dict.items():
                    # Collect name captures
                    if '.name' in capture_name:
                        for node in nodes:
                            name_text = content_bytes[node.start_byte : node.end_byte].decode("utf-8")
                            # Store name for parent and all ancestors up to 3 levels
                            # Use position-based keys since Python id() changes between node references
                            # This handles cases like Go where type_identifier's parent is type_spec
                            # but the captured definition is type_declaration (grandparent)
                            current = node.parent
                            for _ in range(3):  # Check up to 3 levels of ancestry
                                if current:
                                    # Use byte positions as stable key
                                    pos_key = (current.start_byte, current.end_byte)
                                    # Don't overwrite existing names - the first name stored is
                                    # the most specific (e.g., class name before method names)
                                    if pos_key not in name_captures:
                                        name_captures[pos_key] = name_text
                                    current = current.parent
                                else:
                                    break

                    # Collect call captures for relationship extraction
                    if capture_name in ('call', 'call.method'):
                        for node in nodes:
                            call_node_key = (node.start_byte, node.end_byte)
                            if call_node_key in seen_call_nodes:
                                continue
                            call_info = self._extract_call_info(node, content_bytes)
                            if call_info:
                                seen_call_nodes.add(call_node_key)
                                container_key = self._find_containing_definition_key(node)
                                if container_key not in calls_by_container:
                                    calls_by_container[container_key] = []
                                calls_by_container[container_key].append(call_info)

                    # Collect class bases for inheritance
                    if capture_name == 'code_class.bases':
                        for node in nodes:
                            bases = self._extract_class_bases(node, content_bytes)
                            if bases:
                                class_node = node.parent
                                if class_node:
                                    class_key = (class_node.start_byte, class_node.end_byte)
                                    class_bases.setdefault(class_key, []).extend(bases)

            # Second pass: process definition captures using collected data
            for _pattern_index, captures_dict in matches_list:
                for capture_name, nodes in captures_dict.items():
                    # Only process definition captures (e.g., function.def, class.def)
                    if not ('.def' in capture_name or capture_name in ['import', 'import.from', 'call', 'assignment']):
                        continue

                    for node in nodes:
                        node_id = (node.start_byte, node.end_byte)
                        if node_id in seen_nodes:
                            continue
                        seen_nodes.add(node_id)

                        # Look up the name from our name_captures dict using position-based key
                        node_pos_key = (node.start_byte, node.end_byte)
                        actual_name = name_captures.get(node_pos_key)

                        element = self._process_capture(node, capture_name, content, content_bytes, language, actual_name)
                        if element:
                            # Use byte positions as key for lookups
                            node_key = (node.start_byte, node.end_byte)

                            # Add calls made by this element
                            if node_key in calls_by_container:
                                element["calls"] = calls_by_container[node_key]

                            # Add base classes for class definitions
                            if node_key in class_bases:
                                element["bases"] = class_bases[node_key]

                            elements.append(element)

            return sorted(elements, key=lambda x: x.get("start_line", 0))

        except Exception as e:
            logger.warning("Query extraction failed for %s: %s", language, e, exc_info=True)
            return []

    def _process_capture(
        self, node: Any, capture_name: str, content: str, content_bytes: bytes, language: str, actual_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Process a captured node from a query."""
        try:
            # Extract text using byte offsets
            text = content_bytes[node.start_byte : node.end_byte].decode("utf-8")

            start_line = content[: node.start_byte].count("\n") + 1
            end_line = content[: node.end_byte].count("\n") + 1

            # Determine element type from capture name
            element_type = self._get_element_type(capture_name)

            # Detect Python Enum classes
            if element_type == "class" and language == "python":
                superclasses_node = node.child_by_field_name("superclasses")
                if superclasses_node:
                    bases_text = content_bytes[superclasses_node.start_byte : superclasses_node.end_byte].decode("utf-8")
                    if "Enum" in bases_text:
                        element_type = "enum"

            if not element_type:
                return None

            # Use the actual name if provided, otherwise try to extract it
            name: Optional[str]
            if actual_name:
                name = actual_name
            else:
                name = self._extract_node_name(node, capture_name, content_bytes)

            element = CodeElement(
                element_type=element_type,
                name=name or f"{element_type}_{start_line}",
                start_line=start_line,
                end_line=end_line,
                content=CodeUtilities.truncate_content(text),
                capture=capture_name,
            )

            # Calculate complexity for any code element with actual content
            # Store as top-level field (not in metadata) to be moved to ranking_signals later
            complexity_value = None
            if text and len(text.strip()) > 0:
                raw_complexity = CodeUtilities.estimate_complexity(text)
                complexity_value = raw_complexity / 10.0

            # For imports, extract all import names and store as comma-separated string
            if element_type in ["import", "from_import"]:
                import_names = self._extract_all_import_names(text, language)
                if import_names:
                    # Store as comma-separated string to comply with LanceDB schema
                    element.metadata["import_names_str"] = ",".join(import_names)

            # Convert to dict and add complexity as top-level field (not in metadata)
            result = element.to_dict()
            if complexity_value is not None:
                result["complexity"] = complexity_value
            return result

        except Exception:
            logger.debug("Error processing capture: %s", exc_info=True)
            return None

    def _get_element_type(self, capture_name: str) -> Optional[str]:
        """Get element type from capture name.

        Query files use standardized capture names with code_* prefix:
        - @code_function.def -> code_function
        - @code_class.name -> code_class
        - @import.from -> from_import (special case for relationships)
        """
        # Handle special relationship capture names
        if capture_name == "import.from":
            return "from_import"

        parts = capture_name.split(".")
        first_part = parts[0]

        # If capture name already uses code_* prefix, return it directly
        # This is the primary path for standardized query files
        if first_part.startswith("code_"):
            return first_part

        # For non-entity patterns (import, call, comment, etc.), return as-is
        # These are relationship/auxiliary patterns, not entity types
        non_entity_patterns = {"import", "call", "comment", "doc", "docstring", "export"}
        if first_part in non_entity_patterns:
            return first_part

        # Fallback for any legacy patterns - use the mapping
        type_map = CodeUtilities.get_element_type_mapping()
        for part in parts:
            if part in type_map:
                return type_map[part]

        return None

    def _extract_all_import_names(self, import_text: str, language: str) -> List[str]:
        """Extract all import names from an import statement."""
        imports = []

        if language == "python":
            # Python: from X import Y, Z
            from_match = re.match(r"from\s+([\w.]+)\s+import\s+(.+)", import_text)
            if from_match:
                module = from_match.group(1)
                imported = from_match.group(2)
                imports.append(module)
                # Handle multiple imports
                for name in re.findall(r"(\w+)(?:\s+as\s+\w+)?", imported):
                    imports.append(name)
                return imports

            # Python: import X, Y
            import_match = re.match(r"import\s+(.+)", import_text)
            if import_match:
                imported = import_match.group(1)
                for name in re.findall(r"([\w.]+)(?:\s+as\s+\w+)?", imported):
                    imports.append(name)
                return imports

        elif language == "java":
            # Java: import java.util.Arrays;
            import_match = re.match(r"import\s+(static\s+)?([\w.]+);?", import_text)
            if import_match:
                full_path = import_match.group(2)
                imports.append(full_path)
                # Also add the class name (last part)
                if "." in full_path:
                    imports.append(full_path.split(".")[-1])
                return imports

        elif language in ["javascript", "typescript", "tsx", "jsx"]:
            # JS/TS: import { X, Y } from "module"
            from_match = re.search(r"from\s+['\"]([^'\"]+)['\"]", import_text)
            if from_match:
                module_path = from_match.group(1)
                imports.append(module_path)
                # Extract imported names
                named_match = re.search(r"\{\s*([^}]+)\s*\}", import_text)
                if named_match:
                    for name in re.findall(r"(\w+)(?:\s+as\s+\w+)?", named_match.group(1)):
                        imports.append(name)
                # Default import
                default_match = re.match(r"import\s+(\w+)\s+from", import_text)
                if default_match:
                    imports.append(default_match.group(1))
                return imports

        elif language == "go":
            # Go: import "path/to/package"
            import_match = re.search(r'"([^"]+)"', import_text)
            if import_match:
                module_path = import_match.group(1)
                imports.append(module_path)
                # Also add package name (last part of path)
                if "/" in module_path:
                    imports.append(module_path.split("/")[-1])
                return imports

        return imports

    def _extract_node_name(self, node: Any, capture_name: str, content_bytes: bytes) -> Optional[str]:
        """Extract name from a tree-sitter node."""
        # Handle string literals captured as imports
        if "import" in capture_name and node.type in ["interpreted_string_literal", "string", "string_literal"]:
            text = content_bytes[node.start_byte : node.end_byte].decode("utf-8").strip('"')
            return text.split("/")[-1] if "/" in text else text

        # Handle scoped identifiers
        if "import" in capture_name and node.type == "scoped_identifier":
            text = content_bytes[node.start_byte : node.end_byte].decode("utf-8")
            if "::" in text:
                return text.split("::")[-1]
            elif "." in text:
                return text.split(".")[-1]
            return text

        # Try to find a name child node
        # Include type_identifier and field_identifier for Go, type_identifier for TS
        for child in node.children:
            if child.type in ["identifier", "name", "property_identifier", "type_identifier", "field_identifier"]:
                return content_bytes[child.start_byte : child.end_byte].decode("utf-8")

        # Try to extract from first line using patterns
        first_line = content_bytes[node.start_byte :].decode("utf-8").split("\n")[0]
        patterns = [
            r"(?:def|function|func)\s+(\w+)",
            r"(?:class|struct|interface)\s+(\w+)",
            r"(?:const|let|var)\s+(\w+)",
        ]

        return CodeUtilities.extract_name_from_line(first_line, patterns)

    def _extract_call_info(self, node: Any, content_bytes: bytes) -> Optional[Dict[str, Any]]:
        """Extract information about a function/method call.

        Language-aware by structural probing rather than hardcoded to one
        grammar (issue #179). Two call shapes are handled:

        1. **Target in the ``function`` field** — Python ``call``; C-family /
           Go / Rust / TypeScript / C# ``call_expression`` /
           ``invocation_expression``. An ``identifier`` there is a simple call;
           an accessor node (``attribute`` [Py], ``member_expression`` [JS/TS],
           ``field_expression`` [Rust/C++], ``selector_expression`` [Go]) is a
           method call, with the object/method-name fields read per
           :data:`_METHOD_ACCESSOR_FIELDS`.
        2. **Target in the ``name``/``method`` field** — Java ``method_invocation``,
           Ruby ``call``. These carry no ``function`` field; the receiver, if
           any, is in ``object``/``receiver``.

        Nodes with none of these fields (e.g. Java's bare ``@call.method`` name
        identifier, which the collection loop also passes alongside the whole
        ``@call`` node) return ``None`` — so each invocation yields exactly one
        ``call_info`` and is never double-counted.

        Args:
            node: The call node from tree-sitter
            content_bytes: The source code as bytes

        Returns:
            Dictionary with call information or None
        """
        try:
            line = content_bytes[: node.start_byte].count(b"\n") + 1

            # Shape 1: target in the `function` field.
            func_node = node.child_by_field_name("function")
            if func_node is not None:
                if func_node.type == "identifier":
                    # Simple call: foo()
                    call_name = content_bytes[func_node.start_byte : func_node.end_byte].decode("utf-8")
                    return {"name": call_name, "type": "function", "line": line}

                accessor = _METHOD_ACCESSOR_FIELDS.get(func_node.type)
                if accessor is not None:
                    # Method call: obj.method() — object/method-name fields vary
                    # by grammar. The object slot may list several candidate
                    # field names; take the first that resolves.
                    obj_field, name_field = accessor
                    obj_fields = (obj_field,) if isinstance(obj_field, str) else obj_field
                    name_node = func_node.child_by_field_name(name_field)
                    if name_node is not None:
                        method_name = content_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")
                        obj_node = None
                        for candidate in obj_fields:
                            obj_node = func_node.child_by_field_name(candidate)
                            if obj_node is not None:
                                break
                        obj_name = (
                            content_bytes[obj_node.start_byte : obj_node.end_byte].decode("utf-8")
                            if obj_node is not None
                            else ""
                        )
                        return {"name": method_name, "object": obj_name, "type": "method", "line": line}
                return None

            # Shape 2: target in the `name`/`method` field (Java, Ruby).
            name_node = node.child_by_field_name("name") or node.child_by_field_name("method")
            if name_node is not None:
                call_name = content_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")
                obj_node = node.child_by_field_name("object") or node.child_by_field_name("receiver")
                if obj_node is not None:
                    obj_name = content_bytes[obj_node.start_byte : obj_node.end_byte].decode("utf-8")
                    return {"name": call_name, "object": obj_name, "type": "method", "line": line}
                return {"name": call_name, "type": "function", "line": line}

            return None
        except Exception:
            logger.debug("Failed to extract call info", exc_info=True)
            return None

    def _find_containing_definition(self, node: Any) -> int:
        """Find the containing function/method/class definition for a node.

        Args:
            node: The tree-sitter node to find the container for

        Returns:
            The id() of the containing definition node, or 0 if at module level
        """
        current = node.parent
        while current:
            if current.type in _DEFINITION_NODE_TYPES:
                return id(current)
            current = current.parent
        return 0  # Module level

    def _find_containing_definition_key(self, node: Any) -> tuple:
        """Find the containing function/method/class definition for a node.

        Args:
            node: The tree-sitter node to find the container for

        Returns:
            Tuple of (start_byte, end_byte) for the containing definition, or (0, 0) if at module level
        """
        current = node.parent
        while current:
            if current.type in _DEFINITION_NODE_TYPES:
                return (current.start_byte, current.end_byte)
            current = current.parent
        return (0, 0)  # Module level

    def _extract_class_bases(self, node: Any, content_bytes: bytes) -> List[str]:
        """Extract base class names from a class definition's superclasses node.

        Args:
            node: The superclasses/argument_list node (Python) or an Apex
                ``superclass`` / ``interfaces`` / ``type_identifier`` node
            content_bytes: The source code as bytes

        Returns:
            List of base class names
        """
        bases = []
        try:
            if node.type in ("identifier", "type_identifier"):
                bases.append(
                    content_bytes[node.start_byte : node.end_byte].decode("utf-8")
                )
                return bases

            # argument_list (Python) or superclass/interfaces (Apex)
            for child in node.children:
                if child.type in ("identifier", "type_identifier"):
                    base_name = content_bytes[child.start_byte : child.end_byte].decode("utf-8")
                    bases.append(base_name)
                elif child.type == "type_list":
                    for grandchild in child.children:
                        if grandchild.type in ("identifier", "type_identifier"):
                            bases.append(
                                content_bytes[grandchild.start_byte : grandchild.end_byte].decode("utf-8")
                            )
                elif child.type == "attribute":
                    # Qualified base class: class Foo(module.Base)
                    base_text = content_bytes[child.start_byte : child.end_byte].decode("utf-8")
                    bases.append(base_text)
                elif child.type == "subscript":
                    # Generic base: class Foo(List[str])
                    # Extract just the base class name (e.g., "List" from "List[str]")
                    value_node = child.child_by_field_name("value")
                    if value_node:
                        base_text = content_bytes[value_node.start_byte : value_node.end_byte].decode("utf-8")
                        bases.append(base_text)
                elif child.type == "call":
                    # Generic with call: class Foo(Generic[T])
                    func_node = child.child_by_field_name("function")
                    if func_node:
                        base_text = content_bytes[func_node.start_byte : func_node.end_byte].decode("utf-8")
                        bases.append(base_text)
        except Exception:
            logger.debug("Failed to extract class bases", exc_info=True)

        return bases


class UnifiedCodeParser:
    """Main code parser that coordinates tree-sitter parsing strategy.
    
    Adapted from akb_iq to work with the new ParserProtocol interface.
    """

    def __init__(self, max_file_size: int = DEFAULT_MAX_FILE_SIZE):
        """Initialize the unified parser with tree-sitter strategy."""
        if not TREE_SITTER_AVAILABLE:
            raise ImportError("tree-sitter is required for UnifiedCodeParser")
        
        self.max_file_size = max_file_size
        self.tree_sitter_parser = TreeSitterCodeParser()
        self.supported_languages = self._detect_supported_languages()
        self.supported_extensions = self._compute_supported_extensions()

    async def can_parse(self, path: str) -> bool:
        """Check if this parser can handle the given file.
        
        Performs O(1) extension check for efficient parser selection.
        """
        file_path = Path(path)
        ext = file_path.suffix.lower()
        return ext in self.supported_extensions

    async def parse(
        self,
        path: str,
        db_manager: Optional["LanceDBManager"] = None,
        embedding_service: Optional["EmbeddingService"] = None,
        project_id: Optional[str] = None
    ) -> ParsedDocument:
        """Parse a complete file and return structured document.
        
        Args:
            path: Path to the file to parse
            db_manager: Optional database manager for entity registration
            embedding_service: Optional embedding service for entity embeddings
            project_id: Optional project ID for entity isolation
        
        Returns:
            ParsedDocument with code symbols and relationships
        """
        import asyncio
        import aiofiles
        
        file_path = Path(path)
        
        # Validate file
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Check file size
        file_stat = file_path.stat()
        if file_stat.st_size > self.max_file_size:
            raise ParsingError(f"File too large: {file_path} ({file_stat.st_size} bytes)")

        # Get language
        language = LanguageRegistry.get_language(file_path)
        if not language:
            raise ParsingError(f"Unsupported file type: {file_path.suffix}")

        # Read content asynchronously
        try:
            async with aiofiles.open(file_path, mode='r', encoding="utf-8") as f:
                content = await f.read()
        except UnicodeDecodeError:
            try:
                async with aiofiles.open(file_path, mode='r', encoding="latin-1") as f:
                    content = await f.read()
            except Exception as e:
                raise ParsingError(f"Failed to read file: {e}") from e

        # Parse content in executor (CPU-bound tree-sitter parsing)
        try:
            loop = asyncio.get_running_loop()
            elements = await loop.run_in_executor(
                None,
                self.tree_sitter_parser.parse_content,
                content,
                language,
                file_path
            )
        except Exception as e:
            logger.warning("Parsing failed for %s, falling back to simple chunking: %s", exc_info=True)
            # Return partial result with simple chunking
            return self._create_fallback_document(file_path, content, language, error=str(e))

        # Create chunks (synchronous - fast, in-memory symbol extraction)
        chunks = self._create_semantic_chunks(elements, content, language, file_path)

        # Create metadata (synchronous - fast, in-memory)
        metadata = self._create_metadata(file_path, content, language, elements)

        # Generate doc_id
        doc_id = str(file_path.resolve())

        # NEW: Extract and register granular entities if db_manager is provided
        if db_manager is not None and embedding_service is not None and project_id is not None:
            try:
                entities = await self._extract_entities(
                    elements=elements,
                    file_path=file_path,
                    project_id=project_id,
                    doc_id=doc_id
                )
                
                if entities:
                    await self._register_entities(
                        entities=entities,
                        db_manager=db_manager,
                        embedding_service=embedding_service
                    )
            except Exception as e:
                # Log error but don't fail the entire parse operation
                logger.error(
                    "Failed to extract/register entities for %s: %s",
                    file_path,
                    e,
                    exc_info=True
                )

        return ParsedDocument(
            doc_id=doc_id,
            file_path=str(file_path),
            chunks=chunks,
            metadata=metadata,
        )

    async def _extract_entities(
        self,
        elements: List[Dict[str, Any]],
        file_path: Path,
        project_id: str,
        doc_id: str
    ) -> List["GraphEntity"]:
        """Extract granular entities (functions, classes, methods) from parsed elements.

        Args:
            elements: Already-parsed code elements from tree-sitter
            file_path: Path to the source file
            project_id: Project identifier for entity isolation
            doc_id: Document identifier

        Returns:
            List of GraphEntity objects for functions, classes, and methods
        """
        from agent_vault.models.graph_entity import GraphEntity

        entities = []
        
        # Filter for granular entity types (functions, classes, methods)
        # These use 'code_*' prefix as returned by TreeSitterCodeParser.parse_content()
        granular_types = {
            "code_function",   # Standalone functions
            "code_method",     # Methods within classes
            "code_class",      # Classes
            "code_struct",     # Structs (C, Go, Rust)
            "code_interface",  # Interfaces
            "code_enum",       # Enums
        }
        
        for element in elements:
            element_type = element.get("element_type", "")

            # Skip non-granular types (imports, comments, etc.)
            if element_type not in granular_types:
                continue

            element_name = element.get("name", "")
            if not element_name:
                continue

            line_start = element.get("start_line", -1)
            line_end = element.get("end_line", -1)

            # Transform element_type to match EntityType enum values
            # TreeSitterCodeParser returns "code_class", "code_method", etc.
            # but EntityType uses "class", "method", etc.
            entity_type = element_type.removeprefix("code_") if element_type.startswith("code_") else element_type

            # Generate entity ID: {entity_type}::{project_id}::{file_path}::{element_name}
            # This matches the source_id/target_id format used by relationship_resolver
            # Format: "{source_type}::{project_hash}::{source_file}::{source_name}"
            # Use plain type (e.g., "class" not "code_class") for ontology compatibility
            entity_id = f"{entity_type}::{project_id}::{file_path}::{element_name}"

            # Create GraphEntity with placeholder vector (will be filled by _register_entities)
            # We use a zero vector as placeholder - it will be replaced with actual embedding
            entity = GraphEntity(
                id=entity_id,
                name=element_name,
                type=entity_type,  # Use plain type (e.g., "class") for EntityType compatibility
                file_path=str(file_path),
                doc_id=doc_id,
                project_id=project_id,
                vector=[],  # Placeholder - will be filled by _register_entities
                line_start=line_start,
                line_end=line_end,
            )

            entities.append(entity)

        # Create a module entity for this file to match relationship source_ids
        # Import relationships use source_type="module" and source_name=file_stem
        # Format: module::{project_id}::{file_path}::{file_stem}
        file_stem = file_path.stem
        module_entity_id = f"module::{project_id}::{file_path}::{file_stem}"
        module_entity = GraphEntity(
            id=module_entity_id,
            name=file_stem,
            type="module",
            file_path=str(file_path),
            doc_id=doc_id,
            project_id=project_id,
            vector=[],  # Placeholder - will be filled by _register_entities
            line_start=-1,
            line_end=-1,
        )
        entities.append(module_entity)

        # Log entity counts by type (using plain types stored in entities)
        stored_types = {t.removeprefix("code_") for t in granular_types}
        stored_types.add("module")  # Include module in logging
        logger.info(
            "Extracted %d granular entities from %s (%s)",
            len(entities),
            file_path,
            ", ".join(f"{sum(1 for e in entities if e.type == t)} {t}" for t in stored_types if any(e.type == t for e in entities))
        )

        return entities

    async def _register_entities(
        self,
        entities: List["GraphEntity"],
        db_manager: "LanceDBManager",
        embedding_service: "EmbeddingService"
    ) -> None:
        """Register entities in the graph_entities table with embeddings.
        
        Args:
            entities: List of GraphEntity objects to register
            db_manager: Database manager for storage
            embedding_service: Service for generating embeddings
            
        Note:
            This method generates embeddings separately from chunks; the
            entity write is committed and queryable when it returns.
        """
        if not entities:
            return

        # Generate embeddings for all entities in batch
        # Use entity name as the text to embed (as per GraphEntity.get_source_column)
        entity_names = [entity.name for entity in entities]

        # Get embedder from the indexing EmbeddingService
        # The EmbeddingService from agent_vault.indexing uses registry-based embedder lookup
        embedder, _ = embedding_service.get_embedder_configuration("graph_entities", "vector")
        vectors = await embedding_service.generate_embeddings_batch(
            entity_names, embedder, "entity registration"
        )
        
        # Assign vectors to entities (convert ndarray to list)
        for entity, vector in zip(entities, vectors):
            entity.vector = vector.tolist() if hasattr(vector, 'tolist') else list(vector)
        
        await db_manager.add_graph_entities(entities)
        
        logger.info(
            "Registered %d entities in graph_entities table",
            len(entities)
        )

    def _detect_supported_languages(self) -> Set[str]:
        """Detect which languages are supported by tree-sitter.
        
        We assume tree-sitter-language-pack supports all languages we have queries for,
        since it's a comprehensive package with 50+ languages.
        """
        supported = set()

        # Get all unique languages from the language map
        all_languages = set(LanguageRegistry.LANGUAGE_MAP.values())
        
        # Check which ones have query files
        for lang in all_languages:
            if self.tree_sitter_parser.can_parse(lang):
                supported.add(lang)

        return supported

    def _compute_supported_extensions(self) -> Set[str]:
        """Pre-compute supported file extensions for O(1) lookup."""
        extensions = set()
        for ext, lang in LanguageRegistry.LANGUAGE_MAP.items():
            if lang in self.supported_languages:
                extensions.add(ext)
        return extensions

    def _create_semantic_chunks(self, elements: List[Dict], content: str, language: str, file_path: Path) -> List[ParserChunk]:
        """Create semantically meaningful chunks based on code structure."""
        if not elements:
            # If no elements, create a single chunk
            return [
                ParserChunk(
                    content=content,
                    content_type="CODE",
                    language=language,
                    element_type="code_full",
                    element_name="",  # Use empty string instead of None
                    parent_id="",  # Use empty string instead of None
                    page_number=-1,  # Use -1 instead of None
                    line_start=-1,  # Use -1 instead of None
                    line_end=-1,  # Use -1 instead of None
                    fts_text="",  # Use empty string instead of None
                    metadata={},
                )
            ]

        chunks = []

        # Sort elements by their position in the file
        sorted_elements = sorted(elements, key=lambda x: x.get("start_line", 0))

        # Group related elements
        element_groups = self._group_related_elements(sorted_elements)

        for group in element_groups:
            chunk_content = self._extract_group_content(group, content)
            # Extract import names from import elements and create relationships
            group_imports = []
            group_relationships = []
            for elem in group:
                if elem.get("element_type") in ["import", "from_import"]:
                    # Parse comma-separated import_names_str back to list
                    import_names_str = elem.get("import_names_str", "")
                    import_names = [name.strip() for name in import_names_str.split(",") if name.strip()] if import_names_str else []
                    # Extract the raw import statement text for import_path
                    import_text = elem.get("content", "").strip()
                    
                    if import_names:
                        group_imports.extend(import_names)
                        
                        # For from_import, extract module path and skip it in iteration
                        # _extract_all_import_names returns [module, name1, name2, ...]
                        module_path = None
                        if elem.get("element_type") == "from_import":
                            from_match = re.match(r"from\s+([\w.]+)\s+import", import_text)
                            if from_match:
                                module_path = from_match.group(1)
                        
                        # Create import relationships
                        # Use the import name as target - pipeline will resolve to actual entity
                        for import_name in import_names:
                            # Skip the module path entry for from_imports (it's not an imported symbol)
                            if module_path and import_name == module_path:
                                continue
                            
                            # Build metadata with import_path for direct module resolution
                            metadata = {
                                "import_type": elem.get("element_type"),
                                "import_path": import_name,  # Direct import path for O(1) resolution
                            }
                            
                            # For Python "from X import Y", include the module path
                            if module_path:
                                metadata["import_path"] = f"{module_path}.{import_name}"
                            
                            relationship = ParserRelationship(
                                source_type="file",
                                source_name=str(file_path),  # Full file path for resolution
                                target_type="module",  # Could be class, function, or module
                                target_name=import_name,  # The imported symbol name
                                type="imports",
                                metadata=metadata,
                            )
                            group_relationships.append(relationship)
                    else:
                        fallback_name = elem.get("name", "")
                        if fallback_name:
                            group_imports.append(fallback_name)
                            # Create import relationship
                            metadata = {
                                "import_type": elem.get("element_type"),
                                "import_path": fallback_name,  # Direct import path
                            }
                            
                            relationship = ParserRelationship(
                                source_type="file",
                                source_name=str(file_path),  # Full file path for resolution
                                target_type="module",
                                target_name=fallback_name,
                                type="imports",
                                metadata=metadata,
                            )
                            group_relationships.append(relationship)

                # Extract CALLS relationships from element
                calls = elem.get("calls", [])
                if calls:
                    elem_name = elem.get("name", "")
                    elem_type = elem.get("element_type", "")
                    # Normalize type by stripping code_ prefix for ontology compatibility
                    normalized_elem_type = elem_type.removeprefix("code_") if elem_type.startswith("code_") else elem_type
                    for call_info in calls:
                        call_name = call_info.get("name", "")
                        if not call_name:
                            continue

                        # Build metadata with call details
                        call_metadata = {
                            "call_type": call_info.get("type", "function"),
                            "line": call_info.get("line", 0),
                        }
                        if call_info.get("object"):
                            call_metadata["object"] = call_info["object"]

                        relationship = ParserRelationship(
                            source_type=normalized_elem_type if normalized_elem_type else "function",
                            source_name=elem_name if elem_name else str(file_path),
                            target_type="function" if call_info.get("type") == "function" else "method",
                            target_name=call_name,
                            type="calls",
                            metadata=call_metadata,
                        )
                        group_relationships.append(relationship)

                # Extract INHERITS relationships from class bases
                bases = elem.get("bases", [])
                if bases:
                    elem_name = elem.get("name", "")
                    for base_name in bases:
                        if not base_name:
                            continue

                        relationship = ParserRelationship(
                            source_type="class",
                            source_name=elem_name,
                            target_type="class",
                            target_name=base_name,
                            type="inherits",
                            metadata={},
                        )
                        group_relationships.append(relationship)

                # Extract DEFINES relationships for functions/methods within classes
                elem_type = elem.get("element_type", "")
                elem_name = elem.get("name", "")
                # Normalize element type by stripping code_ prefix (e.g., code_method -> method)
                normalized_elem_type = elem_type.removeprefix("code_") if elem_type.startswith("code_") else elem_type
                # "function" covers standalone functions, lambdas, closures; "method" for class methods
                if normalized_elem_type in ("function", "method") and elem_name:
                    elem_start = elem.get("start_line", 0)
                    elem_end = elem.get("end_line", 0)
                    elem_content = elem.get("content", "")
                    # Find the containing class by checking line ranges
                    # Search ALL elements, not just the current group, to handle
                    # cases where methods are grouped separately from their class
                    containing_class = None

                    # First try line-range based containment (Java, Python, etc.)
                    for other_elem in sorted_elements:
                        # class, struct, interface, type are class-like containers
                        # Normalize by stripping code_ prefix (e.g., code_class -> class)
                        other_type = other_elem.get("element_type", "")
                        normalized_other_type = other_type.removeprefix("code_") if other_type.startswith("code_") else other_type
                        if normalized_other_type in ["class", "struct", "interface", "type"]:
                            class_start = other_elem.get("start_line", 0)
                            class_end = other_elem.get("end_line", 0)
                            # Check if the method is within the class line range
                            if class_start <= elem_start and elem_end <= class_end:
                                containing_class = other_elem.get("name", "")
                                break

                    # If not found by line range, try receiver-based (Go methods)
                    # Go methods: func (c ComplexMetrics) Distance(...)
                    if not containing_class and language == "go":
                        # Extract receiver type from Go method signature
                        receiver_match = re.match(r'func\s*\([^)]*\s+\*?(\w+)\)', elem_content)
                        if receiver_match:
                            receiver_type = receiver_match.group(1)
                            # Find the matching struct/type in elements
                            for other_elem in sorted_elements:
                                go_other_type = other_elem.get("element_type", "")
                                normalized_go_type = go_other_type.removeprefix("code_") if go_other_type.startswith("code_") else go_other_type
                                if normalized_go_type in ["type", "struct", "interface"]:
                                    if other_elem.get("name") == receiver_type:
                                        containing_class = receiver_type
                                        break

                    if containing_class:
                        # Store parent_class in the element for later use in symbol_metadata
                        elem["parent_class"] = containing_class
                        relationship = ParserRelationship(
                            source_type="class",
                            source_name=containing_class,
                            target_type=normalized_elem_type,
                            target_name=elem_name,
                            type="defines",
                            metadata={
                                "start_line": elem_start,
                                "end_line": elem_end,
                            },
                        )
                        group_relationships.append(relationship)

            # Extract symbols as plain names and build symbol_metadata
            group_symbols = []
            symbol_metadata = {}
            # Valid code entity types (plain structural types)
            valid_entity_types = {"class", "function", "method", "enum", "variable", "type", "struct", "interface", "module", "namespace", "property", "decorator", "parameter"}
            for elem in group:
                elem_type = elem.get("element_type", "")
                elem_name = elem.get("name", "")
                # Normalize type by stripping code_ prefix if present
                normalized_type = elem_type.removeprefix("code_") if elem_type.startswith("code_") else elem_type
                # Check for code entity types (plain structural types from get_element_type_mapping)
                if normalized_type in valid_entity_types:
                    group_symbols.append(elem_name)
                    # Store type information for each symbol (use normalized type for consistency)
                    symbol_info = {
                        "type": normalized_type,
                        "start_line": elem.get("start_line"),
                        "end_line": elem.get("end_line"),
                    }
                    # Add parent_class for methods
                    if elem_type == "method":
                        parent_class = elem.get("parent_class")
                        if parent_class:
                            symbol_info["parent_class"] = parent_class
                    symbol_metadata[elem_name] = symbol_info

            trimmed_content = chunk_content.strip()
            if not trimmed_content:
                continue

            if len(trimmed_content) < 50:
                has_structural_signals = bool(group_symbols or group_imports)
                spans_multiple_lines = "\n" in trimmed_content
                if not (has_structural_signals or spans_multiple_lines):
                    continue

            # Aggregate complexity
            complexities: list[float] = [elem["complexity"] for elem in group if elem.get("complexity") is not None]
            avg_complexity = sum(complexities) / len(complexities) if complexities else 0

            # Generate FTS text for code
            code_fts_text = self._generate_code_fts_text(group_symbols, group_imports, chunk_content)

            # Create chunk with sentinel values instead of None
            # Set element_name and element_type from the primary symbol
            primary_symbol = group_symbols[0] if group_symbols else ""
            primary_element_type = symbol_metadata.get(primary_symbol, {}).get("type", "code_semantic") if primary_symbol else "code_semantic"

            # Extract parent_class from any element in the group (for methods within classes)
            # This enables proper resolution of self.method() calls
            parent_class = ""
            for elem in group:
                if elem.get("parent_class"):
                    parent_class = elem["parent_class"]
                    break

            chunk = ParserChunk(
                content=chunk_content,
                symbols=group_symbols,
                symbol_metadata=symbol_metadata,  # Add symbol metadata with types
                relationships=group_relationships,  # Add import relationships
                content_type="CODE",  # Set as top-level field
                language=language,
                line_start=min(elem.get("start_line", 1) for elem in group),
                line_end=max(elem.get("end_line", 1) for elem in group),
                element_type=primary_element_type,  # Use actual element type (class, function, etc.)
                element_name=primary_symbol,  # Use primary symbol as element name
                parent_id=parent_class,  # Pass containing class for methods (enables self.method() resolution)
                page_number=-1,  # Use -1 instead of None
                fts_text=code_fts_text,
                metadata={},  # Keep metadata minimal
                ranking_signals={
                    "complexity": avg_complexity,
                    "importance": 0.0,
                },
            )
            chunks.append(chunk)

        # Add full file chunk if we have few semantic chunks
        if len(chunks) < 3:
            all_imports = []
            all_relationships = []
            for elem in elements:
                if elem.get("element_type") in ["import", "from_import"]:
                    # Parse comma-separated import_names_str back to list
                    import_names_str = elem.get("import_names_str", "")
                    import_names = [name.strip() for name in import_names_str.split(",") if name.strip()] if import_names_str else []
                    import_text = elem.get("content", "").strip()
                    
                    if import_names:
                        all_imports.extend(import_names)
                        
                        # For from_import, extract module path and skip it in iteration
                        # _extract_all_import_names returns [module, name1, name2, ...]
                        module_path = None
                        if elem.get("element_type") == "from_import":
                            from_match = re.match(r"from\s+([\w.]+)\s+import", import_text)
                            if from_match:
                                module_path = from_match.group(1)
                        
                        # Create import relationships
                        for import_name in import_names:
                            # Skip the module path entry for from_imports (it's not an imported symbol)
                            if module_path and import_name == module_path:
                                continue
                            
                            # Build metadata with import_path
                            metadata = {
                                "import_type": elem.get("element_type"),
                                "import_path": import_name,
                            }
                            
                            # For Python "from X import Y", include the module path
                            if module_path:
                                metadata["import_path"] = f"{module_path}.{import_name}"
                            
                            relationship = ParserRelationship(
                                source_type="module",
                                source_name=file_path.stem,
                                target_type="module",
                                target_name=import_name,
                                type="imports",
                                metadata=metadata,
                            )
                            all_relationships.append(relationship)
                    else:
                        fallback_name = elem.get("name", "")
                        if fallback_name:
                            all_imports.append(fallback_name)
                            # Create import relationship with import_path
                            metadata = {
                                "import_type": elem.get("element_type"),
                                "import_path": fallback_name,
                            }
                            relationship = ParserRelationship(
                                source_type="module",
                                source_name=file_path.stem,
                                target_type="module",
                                target_name=fallback_name,
                                type="imports",
                                metadata=metadata,
                            )
                            all_relationships.append(relationship)
                            # Create import relationship
                            relationship = ParserRelationship(
                                source_type="module",
                                source_name=file_path.stem,
                                target_type="module",
                                target_name=fallback_name,
                                type="imports",
                            )
                            all_relationships.append(relationship)

            all_symbols = []
            all_symbol_metadata = {}
            # Valid code entity types (plain structural types)
            valid_entity_types = {"class", "function", "method", "enum", "variable", "type", "struct", "interface", "module", "namespace", "property", "decorator", "parameter"}
            for elem in elements:
                elem_type = elem.get("element_type", "")
                elem_name = elem.get("name", "")
                # Normalize type by stripping code_ prefix if present
                normalized_type = elem_type.removeprefix("code_") if elem_type.startswith("code_") else elem_type
                # Check for code entity types (plain structural types from get_element_type_mapping)
                if normalized_type in valid_entity_types:
                    all_symbols.append(elem_name)
                    # Store type information for each symbol (use normalized type for consistency)
                    all_symbol_metadata[elem_name] = {
                        "type": normalized_type,
                        "start_line": elem.get("start_line"),
                        "end_line": elem.get("end_line"),
                    }

            all_complexities: list[float] = [elem["complexity"] for elem in elements if elem.get("complexity") is not None]
            file_avg_complexity = sum(all_complexities) / len(all_complexities) if all_complexities else 0

            code_fts_text = self._generate_code_fts_text(all_symbols, all_imports, content)

            chunks.append(
                ParserChunk(
                    content=content,
                    symbols=all_symbols,
                    symbol_metadata=all_symbol_metadata,  # Add symbol metadata with types
                    relationships=all_relationships,  # Add import relationships
                    content_type="CODE",  # Set as top-level field
                    language=language,
                    element_type="code_full",
                    element_name="",  # Use empty string instead of None
                    parent_id="",  # Use empty string instead of None
                    page_number=-1,  # Use -1 instead of None
                    line_start=-1,  # Use -1 instead of None
                    line_end=-1,  # Use -1 instead of None
                    fts_text=code_fts_text,
                    metadata={},  # Keep metadata minimal
                    ranking_signals={
                        "complexity": file_avg_complexity,
                        "importance": 0.0,
                    },
                )
            )

        return chunks

    @staticmethod
    def _split_compound_identifier(name: str) -> str:
        """Split CamelCase, PascalCase, and snake_case identifiers into words.

        Examples:
            HttpConnectionManager → Http Connection Manager
            getHTTPResponse → get HTTP Response
            http_connection_manager → http connection manager
            XMLParser → XML Parser

        Args:
            name: Identifier string to split

        Returns:
            Space-separated words from the identifier
        """
        # Split on underscores first
        parts = name.replace('_', ' ').replace('-', ' ')
        # Split CamelCase: insert space before uppercase that follows lowercase,
        # or before uppercase followed by uppercase+lowercase (e.g., HTTPResponse → HTTP Response)
        parts = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', parts)
        parts = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', parts)
        return parts

    def _generate_code_fts_text(self, symbols: List[str], imports: List[str], content: str) -> str:
        """Generate FTS-optimized text for code chunks.

        Extracts identifiers and symbol names while removing syntax.
        Splits CamelCase/snake_case names so FTS can match individual words.
        """
        fts_parts = []

        # Add symbols with both original and split forms
        if symbols:
            for sym in symbols:
                fts_parts.append(sym)
                split = self._split_compound_identifier(sym)
                if split != sym:
                    fts_parts.append(split)

        # Add import names with both original and split forms
        # Also split dotted paths (e.g., java.lang.String → java lang String)
        if imports:
            for imp in imports:
                fts_parts.append(imp)
                # Split dotted package paths
                if '.' in imp:
                    for part in imp.split('.'):
                        if part and len(part) > 1:
                            fts_parts.append(part)
                            split = self._split_compound_identifier(part)
                            if split != part:
                                fts_parts.append(split)
                else:
                    split = self._split_compound_identifier(imp)
                    if split != imp:
                        fts_parts.append(split)

        # Extract additional identifiers from content
        # Remove common syntax characters and extract words
        cleaned = re.sub(r'[(){}\[\];,.<>:=+\-*/&|!~%^]', ' ', content)
        words = cleaned.split()

        # Filter to meaningful identifiers (not language keywords, not numbers)
        # Note: 'string' removed - it's a Java class (String), not a keyword
        # 'override' removed - it's an annotation, not a keyword
        keywords = {'if', 'else', 'for', 'while', 'return', 'def', 'class', 'import', 'from', 'as',
                   'function', 'const', 'let', 'var', 'public', 'private', 'protected', 'static',
                   'void', 'int', 'boolean', 'new', 'this', 'null', 'true', 'false',
                   'try', 'catch', 'finally', 'throw', 'throws', 'extends', 'implements',
                   'interface', 'abstract', 'final', 'synchronized', 'volatile', 'transient',
                   'native', 'package', 'instanceof', 'super', 'switch', 'case', 'default',
                   'break', 'continue', 'do', 'goto', 'enum', 'assert',
                   'byte', 'short', 'long', 'char', 'double', 'float'}
        identifiers = [w for w in words if w and not w.isdigit() and w.lower() not in keywords and len(w) > 1]

        # Add unique identifiers with CamelCase/snake_case splitting
        seen = set()
        for ident in identifiers:
            if ident not in seen:
                seen.add(ident)
                fts_parts.append(ident)
                split = self._split_compound_identifier(ident)
                if split != ident:
                    fts_parts.append(split)

        # Cap by actual word count, not list entries (split forms have spaces)
        result = ' '.join(fts_parts)
        words_out = result.split()
        return ' '.join(words_out[:1000])

    def _group_related_elements(self, elements: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Group related elements together for chunking."""
        if not elements:
            return []

        groups = []
        current_group = [elements[0]]

        for i in range(1, len(elements)):
            current_elem = elements[i]
            prev_elem = elements[i - 1]

            # Group elements that are close together or related
            should_group = (
                # Close line proximity
                current_elem.get("start_line", 0) - prev_elem.get("end_line", 0) < 5
                or
                # Same class
                (current_elem.get("class_name") and current_elem.get("class_name") == prev_elem.get("class_name"))
                or
                # Related types (class and its methods)
                (
                    prev_elem.get("element_type") == "class"
                    and current_elem.get("element_type") in ["method", "function"]
                )
            )

            if should_group and len(current_group) < 5:
                current_group.append(current_elem)
            else:
                groups.append(current_group)
                current_group = [current_elem]

        if current_group:
            groups.append(current_group)

        return groups

    def _extract_group_content(self, group: List[Dict[str, Any]], content: str) -> str:
        """Extract content for a group of elements."""
        if not group:
            return ""

        lines = content.split("\n")
        start_line = min(elem.get("start_line", 1) for elem in group) - 1
        end_line = max(elem.get("end_line", 1) for elem in group)

        # Add some context
        context_start = max(0, start_line - 2)
        context_end = min(len(lines), end_line + 2)

        return "\n".join(lines[context_start:context_end])

    def _create_metadata(self, file_path: Path, content: str, language: str, elements: List[Dict]) -> Dict[str, Any]:
        """Create document metadata."""
        file_stat = file_path.stat()

        element_summary: Dict[str, int] = {}
        for element in elements:
            element_type = element.get("element_type", "unknown")
            element_summary[element_type] = element_summary.get(element_type, 0) + 1

        return {
            "file_path": str(file_path.resolve()),
            "file_name": file_path.name,
            "file_extension": file_path.suffix,
            "file_size": file_stat.st_size,
            "file_hash": hashlib.md5(content.encode()).hexdigest(),
            "mime_type": f"text/x-{language}",
            "created_at": datetime.fromtimestamp(file_stat.st_ctime).isoformat(),
            "modified_at": datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
            "file_type": "code",
            "element_count": len(elements),
            "lines_of_code": content.count("\n") + 1,
            "content_type": "CODE",
        }

    def _create_fallback_document(self, file_path: Path, content: str, language: str, error: str) -> ParsedDocument:
        """Create a fallback document when parsing fails."""
        # Create a single chunk with the content
        chunk = ParserChunk(
            content=content[:10000],  # Limit size
            content_type="CODE",
            language=language,
            element_type="code_full",
            element_name="",  # Use empty string instead of None
            parent_id="",  # Use empty string instead of None
            page_number=-1,  # Use -1 instead of None
            line_start=-1,  # Use -1 instead of None
            line_end=-1,  # Use -1 instead of None
            fts_text="",  # Use empty string instead of None
            metadata={
                "partial_parse": True,
                "parse_error": error,
            },
        )

        metadata = {
            "file_path": str(file_path.resolve()),
            "file_name": file_path.name,
            "file_extension": file_path.suffix,
            "partial_parse": True,
            "parse_error": error,
            "content_type": "CODE",
        }

        return ParsedDocument(
            doc_id=str(file_path.resolve()),
            file_path=str(file_path),
            chunks=[chunk],
            metadata=metadata,
        )
