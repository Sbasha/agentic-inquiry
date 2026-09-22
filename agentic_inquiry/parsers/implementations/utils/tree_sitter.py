"""Tree-sitter integration for parsing source code files."""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TreeSitterNode:
    """Represents a node in the tree-sitter AST."""
    type: str
    text: str
    start_byte: int
    end_byte: int
    start_point: tuple[int, int]  # (row, column)
    end_point: tuple[int, int]  # (row, column)
    children: List['TreeSitterNode']
    
    @property
    def start_line(self) -> int:
        """Get the starting line number (1-indexed)."""
        return self.start_point[0] + 1
    
    @property
    def end_line(self) -> int:
        """Get the ending line number (1-indexed)."""
        return self.end_point[0] + 1


class TreeSitterParser:
    """Wrapper for tree-sitter parsing functionality."""
    
    def __init__(self) -> None:
        """Initialize tree-sitter parser with language support."""
        self._parsers: Dict[str, Any] = {}
        self._languages: Dict[str, Any] = {}
        self._initialized = False
        self._init_tree_sitter()
    
    def _init_tree_sitter(self) -> None:
        """Initialize tree-sitter library and load language parsers."""
        try:
            import tree_sitter
            from tree_sitter import Language, Parser
            
            self._tree_sitter = tree_sitter
            self._Parser = Parser
            self._Language = Language
            self._initialized = True
            logger.info("Tree-sitter initialized successfully")
        except ImportError as e:
            logger.warning("Tree-sitter not available: %s", e)
            self._initialized = False
    
    def is_available(self) -> bool:
        """Check if tree-sitter is available."""
        return self._initialized
    
    def _load_language(self, language: str) -> Optional[Any]:
        """Load a tree-sitter language parser.
        
        Args:
            language: Language name (e.g., 'python', 'javascript')
        
        Returns:
            Language object or None if not available
        """
        if not self._initialized:
            return None
        
        if language in self._languages:
            return self._languages[language]
        
        try:
            # Try to import the language-specific module
            # This assumes tree-sitter-{language} packages are installed
            if language == 'python':
                from tree_sitter_python import language as py_lang
                lang = py_lang()
            elif language == 'javascript':
                from tree_sitter_javascript import language as js_lang
                lang = js_lang()
            elif language == 'typescript':
                from tree_sitter_typescript import language_typescript as ts_lang
                lang = ts_lang()
            elif language == 'java':
                from tree_sitter_java import language as java_lang
                lang = java_lang()
            elif language == 'cpp' or language == 'c++':
                from tree_sitter_cpp import language as cpp_lang
                lang = cpp_lang()
            elif language == 'c':
                from tree_sitter_c import language as c_lang
                lang = c_lang()
            elif language == 'go':
                from tree_sitter_go import language as go_lang
                lang = go_lang()
            elif language == 'rust':
                from tree_sitter_rust import language as rust_lang
                lang = rust_lang()
            elif language == 'ruby':
                from tree_sitter_ruby import language as ruby_lang
                lang = ruby_lang()
            else:
                logger.debug("No tree-sitter support for language: %s", language)
                return None
            
            self._languages[language] = lang
            logger.debug("Loaded tree-sitter language: %s", language)
            return lang
        
        except ImportError as e:
            logger.debug("Tree-sitter language '%s' not available: %s", language, e)
            return None
        except Exception as e:
            logger.warning("Failed to load tree-sitter language '%s': %s", language, e)
            return None
    
    def _get_parser(self, language: str) -> Optional[Any]:
        """Get or create a parser for the specified language.
        
        Args:
            language: Language name
        
        Returns:
            Parser object or None if not available
        """
        if not self._initialized:
            return None
        
        if language in self._parsers:
            return self._parsers[language]
        
        lang = self._load_language(language)
        if lang is None:
            return None
        
        try:
            parser = self._Parser()
            parser.set_language(lang)  # type: ignore
            self._parsers[language] = parser
            return parser
        except Exception as e:
            logger.warning("Failed to create parser for '%s': %s", language, e)
            return None

    def parse(self, content: str, language: str) -> Optional[Any]:
        """Parse source code content using tree-sitter.
        
        Args:
            content: Source code content to parse
            language: Programming language name
        
        Returns:
            Tree object or None if parsing fails
        """
        if not self._initialized:
            logger.warning("Tree-sitter not initialized")
            return None
        
        parser = self._get_parser(language)
        if parser is None:
            logger.debug("No parser available for language: %s", language)
            return None
        
        try:
            tree = parser.parse(bytes(content, 'utf-8'))
            return tree
        except Exception as e:
            logger.error("Failed to parse content with tree-sitter: %s", e)
            return None
    
    def query(self, tree: Any, query_string: str, language: str) -> List[tuple]:
        """Execute a tree-sitter query on a parsed tree.
        
        Args:
            tree: Parsed tree object
            query_string: Tree-sitter query string
            language: Programming language name
        
        Returns:
            List of (node, capture_name) tuples
        """
        if not self._initialized or tree is None:
            return []
        
        lang = self._load_language(language)
        if lang is None:
            return []
        
        try:
            query = lang.query(query_string)
            captures = query.captures(tree.root_node)
            return captures
        except Exception as e:
            logger.error("Failed to execute query: %s", e)
            return []
    
    def get_node_text(self, node: Any, content: bytes) -> str:
        """Extract text content from a tree-sitter node.
        
        Args:
            node: Tree-sitter node
            content: Original source code as bytes
        
        Returns:
            Text content of the node
        """
        try:
            return content[node.start_byte:node.end_byte].decode('utf-8')
        except Exception as e:
            logger.error("Failed to extract node text: %s", e)
            return ""
    
    def convert_node(self, node: Any, content: bytes) -> TreeSitterNode:
        """Convert a tree-sitter node to our TreeSitterNode dataclass.
        
        Args:
            node: Tree-sitter node
            content: Original source code as bytes
        
        Returns:
            TreeSitterNode object
        """
        text = self.get_node_text(node, content)
        children = [self.convert_node(child, content) for child in node.children]
        
        return TreeSitterNode(
            type=node.type,
            text=text,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_point=(node.start_point[0], node.start_point[1]),
            end_point=(node.end_point[0], node.end_point[1]),
            children=children
        )


# Query templates for common code structures
FUNCTION_QUERY_TEMPLATES = {
    'python': """
        (function_definition
            name: (identifier) @function.name
        ) @function.def
    """,
    'javascript': """
        (function_declaration
            name: (identifier) @function.name
        ) @function.def
        (arrow_function) @function.def
    """,
    'typescript': """
        (function_declaration
            name: (identifier) @function.name
        ) @function.def
        (arrow_function) @function.def
        (method_definition
            name: (property_identifier) @function.name
        ) @function.def
    """,
    'java': """
        (method_declaration
            name: (identifier) @function.name
        ) @function.def
    """,
    'cpp': """
        (function_definition
            declarator: (function_declarator
                declarator: (identifier) @function.name
            )
        ) @function.def
    """,
    'c': """
        (function_definition
            declarator: (function_declarator
                declarator: (identifier) @function.name
            )
        ) @function.def
    """,
    'go': """
        (function_declaration
            name: (identifier) @function.name
        ) @function.def
    """,
    'rust': """
        (function_item
            name: (identifier) @function.name
        ) @function.def
    """,
    'ruby': """
        (method
            name: (identifier) @function.name
        ) @function.def
    """,
}

CLASS_QUERY_TEMPLATES = {
    'python': """
        (class_definition
            name: (identifier) @class.name
        ) @class.def
    """,
    'javascript': """
        (class_declaration
            name: (identifier) @class.name
        ) @class.def
    """,
    'typescript': """
        (class_declaration
            name: (type_identifier) @class.name
        ) @class.def
    """,
    'java': """
        (class_declaration
            name: (identifier) @class.name
        ) @class.def
    """,
    'cpp': """
        (class_specifier
            name: (type_identifier) @class.name
        ) @class.def
    """,
    'rust': """
        (struct_item
            name: (type_identifier) @class.name
        ) @class.def
        (impl_item
            type: (type_identifier) @class.name
        ) @class.def
    """,
    'ruby': """
        (class
            name: (constant) @class.name
        ) @class.def
    """,
}

IMPORT_QUERY_TEMPLATES = {
    'python': """
        (import_statement) @import
        (import_from_statement) @import
    """,
    'javascript': """
        (import_statement) @import
    """,
    'typescript': """
        (import_statement) @import
    """,
    'java': """
        (import_declaration) @import
    """,
    'cpp': """
        (preproc_include) @import
    """,
    'c': """
        (preproc_include) @import
    """,
    'go': """
        (import_declaration) @import
    """,
    'rust': """
        (use_declaration) @import
    """,
    'ruby': """
        (call
            method: (identifier) @method
            (#eq? @method "require")
        ) @import
    """,
}
