---
title: "API Reference"
tier: 3
audience: developer
journey: ["integration-developer", "extension-developer"]
related: ["../guides/parsing.md", "../guides/indexing.md", "../guides/searching.md", "../customization/extending.md"]
last_updated: 2025-10-28
---

# API Reference

> Historical reference. This page describes PostgreSQL-family providers, cloud connectors or remote embedders that are not part of this local-only distribution. It is retained as design input for the external provider contract in [storage-backends.md](../storage-backends.md).

This document provides comprehensive API documentation for all major components in Agentic Inquiry.

## Recommended Patterns

Most applications should use these factory methods for automatic dependency injection:

```python
from agentic_inquiry.config import Config

# 1. Load configuration
config = Config.load()

# 2. Create storage facade
from agentic_inquiry.storage.facade import StorageFacade
storage = await StorageFacade.from_config(config, project_id="my-project")

# 3. Create search service
from agentic_inquiry.search.service import SearchService
search = await SearchService.from_config(config, project_id="my-project")

# 4. Create indexing pipeline
from agentic_inquiry.indexing.pipeline import IndexingPipeline
pipeline = await IndexingPipeline.from_config(config, project_id="my-project")

# 5. Use async context managers
async with pipeline:
    await pipeline.index_directory(path="/path/to/code", wait=True)

# 6. Perform searches
results = await search.hybrid_search(
    query_vector=embedding,
    query_fts="authentication",
    limit=10
)
```

**Key Points:**
- All I/O operations are async
- Use `Config.load()` to load configuration from `agentic-inquiry.yaml` or defaults
- Use factory methods (`from_config()`) instead of direct constructors
- EventSystem is managed automatically by factory methods
- StorageFacade is the primary interface for database operations

## Quick Links

- [Database Layer](#database-layer) - StorageFacade for unified storage access
- [Parsers](#parsers) - Parse files into structured documents
- [Indexing](#indexing) - Index documents into the database
- [Search](#search) - Search indexed documents
- [Protocols](#protocols) - Interface definitions (advanced usage)

---

## Database Layer

Agentic Inquiry uses concrete classes for database operations with clear interfaces.

**Location:** `agentic_inquiry.storage`

### StorageFacade

Provides unified storage operations across all backends (LanceDB, PostgreSQL, AlloyDB).

```python
from agentic_inquiry.config import Config
from agentic_inquiry.storage.facade import StorageFacade

# Create storage facade from config (recommended)
config = Config.load()
storage = await StorageFacade.from_config(config, project_id="my_project")

# Add chunks
await storage.upsert_chunks(chunks)

# Search
results = await storage.vector_search(
    query_vector=embedding,
    limit=10
)
```

**Key Methods:**
- `upsert_chunks()` - Add/update document chunks
- `upsert_entities()` - Add/update graph entities
- `upsert_relationships()` - Add/update relationships
- `vector_search()` - Semantic vector search
- `fts_search()` - Full-text search
- `hybrid_search()` - Combined vector + FTS search with IDF-weighted reranking

See [Database](#database) section below for complete API reference.

---

## Protocols

Protocol definitions provide interface contracts for custom implementations. Most users should use the concrete implementations (StorageFacade, SearchService, IndexingPipeline) instead of implementing these protocols directly.

### CacheProtocol

Defines the interface for caching operations (defined in `agentic_inquiry.cache`).

```python
from agentic_inquiry.cache import CacheProtocol, get_cache

async def example(file_path: str, document: object) -> None:
    cache = get_cache()                          # sync — returns the registered cache
    cached_doc = await cache.get(file_path)      # async
    await cache.put(file_path, document)         # async
```

**Implementations:**
- `DocumentCache` - LRU cache with optional disk persistence

**Usage:**
```python
from agentic_inquiry.cache import CacheProtocol

async def use_cache(cache: CacheProtocol, file_path: str):
    # Works with any CacheProtocol implementation
    cached = await cache.get(file_path)
    if not cached:
        cached = parse_file(file_path)
        await cache.put(file_path, cached)
    return cached
```

### EmbeddingProtocol

Defines the interface for embedding generation.

```python
class EmbeddingProtocol(Protocol):
    def embed(self, text: str) -> List[float]: ...
    def embed_batch(self, texts: List[str]) -> List[List[float]]: ...
```

**Implementations:**
- `SentenceTransformerEmbedder` - Sentence transformers
- `HashingEmbedder` - Fast hashing-based embeddings
- `OpenAIEmbedder` - OpenAI API embeddings (if configured)

**Usage:**
```python
from agentic_inquiry.protocols import EmbeddingProtocol

def generate_embeddings(embedder: EmbeddingProtocol, texts: List[str]):
    # Works with any embedding provider
    return embedder.embed_batch(texts)
```

### ParserProtocol

Defines the interface for document parsing.

```python
class ParserProtocol(Protocol):
    def can_parse(self, file_path: str) -> bool: ...
    def parse(self, file_path: str) -> ParsedDocument: ...
```

**Implementations:**
- `UnifiedCodeParser` - Code files
- `DocumentParser` - Document files
- `FallbackTextParser` - Plain text

**Usage:**
```python
from agentic_inquiry.protocols import ParserProtocol

def parse_with_any_parser(parser: ParserProtocol, file_path: str):
    # Works with any parser implementation
    if parser.can_parse(file_path):
        return parser.parse(file_path)
```

### SymbolRegistryProtocol

Defines the interface for symbol resolution.

```python
class SymbolRegistryProtocol(Protocol):
    def register_symbol(self, symbol_name: str, file_path: str, 
                       symbol_type: str, metadata: Dict | None = None) -> None: ...
    def lookup_symbol(self, symbol_name: str) -> List[Dict]: ...
    def remove_file_symbols(self, file_path: str) -> None: ...
```

**Implementations:**
- `SymbolRegistry` - In-memory symbol tracking

**Usage:**
```python
from agentic_inquiry.protocols import SymbolRegistryProtocol

def resolve_symbols(registry: SymbolRegistryProtocol, symbol_name: str):
    # Works with any symbol registry implementation
    return registry.lookup_symbol(symbol_name)
```

### Benefits of Protocol-Based Design

1. **Flexibility**: Swap implementations without changing code
2. **Testability**: Easy to create mock implementations for testing
3. **Type Safety**: Static type checking with mypy
4. **Clear Contracts**: Explicit interface definitions
5. **Duck Typing**: No inheritance required

**Example with Testing:**
```python
from agentic_inquiry.protocols import DatabaseProtocol

class MockDatabase:
    """Mock database for testing - no inheritance needed"""
    def __init__(self):
        self.chunks = []
    
    async def add_chunks(self, chunks: List[Dict], project_id: str) -> None:
        self.chunks.extend(chunks)
    
    async def search_chunks(self, query_embedding: List[float],
                           project_id: str, limit: int) -> List[Dict]:
        return self.chunks[:limit]

# Use in tests
mock_db: DatabaseProtocol = MockDatabase()
await process_data(mock_db, "test-project")
```

---

## Parsers

The parser system converts files into structured `ParsedDocument` objects containing chunks, symbols, and relationships. Parsers are organized in a chain with priority-based execution.

### Core Classes

#### ParserChain

The main entry point for parsing files. Manages a collection of parsers and executes them in priority order.

**Location:** `agentic_inquiry.parsers.chain`

##### Constructor

```python
ParserChain(
    parsers: list[BaseParser] | None = None,
    event_system: EventSystem | None = None,
    config: dict | None = None
)
```

**Parameters:**
- `parsers` (list[BaseParser], optional): List of parser instances to use. If None, uses all registered parsers.
- `event_system` (EventSystem, optional): Event system for tracking parsing operations. If provided, must be started before use.
- `config` (dict, optional): Configuration dictionary for parser behavior.

**Example:**
```python
from agentic_inquiry.config import Config
from agentic_inquiry.parsers import ParserChain
from agentic_inquiry.events import EventSystem

# Simple usage without event tracking
chain = ParserChain()
doc = chain.parse("/path/to/file.py")

# With event tracking
config = Config.load()
event_system = EventSystem.from_config(config, project_id="my-project")
await event_system.start()

try:
    chain = ParserChain(event_system=event_system)
    doc = chain.parse("/path/to/file.py")
finally:
    await event_system.stop()
```

##### Methods

###### parse()

Parse a file and return a structured document.

```python
def parse(self, file_path: str) -> ParsedDocument
```

**Parameters:**
- `file_path` (str): Absolute path to the file to parse.

**Returns:**
- `ParsedDocument`: Structured document with chunks, symbols, and relationships.

**Raises:**
- `ParsingError`: If all parsers fail to parse the file.
- `FileNotFoundError`: If the file doesn't exist.

**Example:**
```python
chain = ParserChain()
doc = chain.parse("/path/to/file.py")

print(f"Parsed {len(doc.chunks)} chunks")
print(f"Found {sum(len(c.symbols) for c in doc.chunks)} symbols")
```

###### from_config()

Create a ParserChain from configuration.

```python
@classmethod
def from_config(cls, config: dict) -> ParserChain
```

**Parameters:**
- `config` (dict): Configuration dictionary with parser settings.

**Returns:**
- `ParserChain`: Configured parser chain instance.

**Example:**
```python
config = {
    "parsers": {
        "unified_code": {"enabled": True, "priority": 100},
        "document": {"enabled": True, "priority": 50},
        "text": {"enabled": True, "priority": 0}
    }
}

chain = ParserChain.from_config(config)
```

#### ParsedDocument

Represents a parsed document with all extracted information.

**Location:** `agentic_inquiry.parsers.models`

##### Attributes

- `doc_id` (str): Unique identifier for the document.
- `file_path` (str): Absolute path to the source file.
- `chunks` (list[ParserChunk]): List of content chunks extracted from the document.
- `metadata` (dict): Document-level metadata (language, file type, etc.).

**Example:**
```python
doc = chain.parse("example.py")

# Access document properties
print(f"Document ID: {doc.doc_id}")
print(f"File: {doc.file_path}")
print(f"Language: {doc.metadata.get('language')}")

# Iterate through chunks
for chunk in doc.chunks:
    print(f"Chunk: {chunk.element_name} ({chunk.content_type})")
```

#### ParserChunk

Represents a single chunk of content from a parsed document.

**Location:** `agentic_inquiry.parsers.models`

##### Attributes

- `chunk_id` (str): Unique identifier for the chunk.
- `content` (str): The actual text content of the chunk.
- `content_type` (str): Type of content ("CODE", "PROSE", "MIXED").
- `language` (str | None): Programming language or document type.
- `element_type` (str | None): Type of element (function, class, heading, etc.).
- `element_name` (str | None): Name of the element (function name, heading text, etc.).
- `line_start` (int): Starting line number in the source file.
- `line_end` (int): Ending line number in the source file.
- `symbols` (list[str]): List of code symbols defined in this chunk.
- `symbol_metadata` (dict): Metadata for each symbol (type, scope, etc.).
- `relationships` (list[ParserRelationship]): Relationships to other symbols.
- `fts_text` (str | None): Full-text search optimized text.
- `page_number` (int | None): Page number for document files.

**Example:**
```python
for chunk in doc.chunks:
    print(f"\nChunk: {chunk.element_name}")
    print(f"  Type: {chunk.content_type}")
    print(f"  Lines: {chunk.line_start}-{chunk.line_end}")
    print(f"  Symbols: {len(chunk.symbols)}")
    
    # Access symbols and their metadata
    for symbol in chunk.symbols:
        metadata = chunk.symbol_metadata.get(symbol, {})
        print(f"    - {symbol} ({metadata.get('type', 'unknown')})")
```

#### ParserRelationship

Represents a relationship between symbols (imports, calls, references, etc.).

**Location:** `agentic_inquiry.parsers.models`

##### Attributes

- `source_symbol` (str): The symbol that has the relationship.
- `target_symbol` (str): The symbol being referenced.
- `relationship_type` (str): Type of relationship ("imports", "calls", "references", etc.).
- `metadata` (dict): Additional relationship metadata.

**Example:**
```python
for chunk in doc.chunks:
    for rel in chunk.relationships:
        print(f"{rel.source_symbol} {rel.relationship_type} {rel.target_symbol}")
```

### Parser Implementations

#### UnifiedCodeParser

Parses code files using tree-sitter for multiple programming languages.

**Location:** `agentic_inquiry.parsers.implementations.unified_code`

**Supported Languages:**
- Python (.py)
- JavaScript (.js, .jsx)
- TypeScript (.ts, .tsx)
- Java (.java)
- C/C++ (.c, .cpp, .h, .hpp)
- Go (.go)
- Rust (.rs)
- Ruby (.rb)
- PHP (.php)

**Features:**
- Extracts functions, classes, methods, and variables
- Captures import/export statements
- Identifies function calls and references
- Preserves docstrings and comments
- Generates symbol metadata (type, scope, parameters)

**Example:**
```python
from agentic_inquiry.parsers.implementations import UnifiedCodeParser

parser = UnifiedCodeParser()
doc = parser.parse("/path/to/code.py")

# Access code-specific features
for chunk in doc.chunks:
    if chunk.content_type == "CODE":
        print(f"Function: {chunk.element_name}")
        print(f"  Symbols: {chunk.symbols}")
        print(f"  Calls: {[r.target_symbol for r in chunk.relationships if r.relationship_type == 'calls']}")
```

#### DocumentParser

Parses document files (PDF, DOCX, PPTX, Markdown, etc.) using the unstructured library.

**Location:** `agentic_inquiry.parsers.implementations.document`

**Supported Formats:**
- Markdown (.md)
- PDF (.pdf)
- Word (.docx, .doc)
- PowerPoint (.pptx, .ppt)
- HTML (.html, .htm)
- Text (.txt)

**Features:**
- Extracts document structure (headings, paragraphs, lists)
- Preserves page numbers for paginated documents
- Identifies tables and figures
- Generates FTS-optimized text
- Captures document metadata

**Example:**
```python
from agentic_inquiry.parsers.implementations import DocumentParser

parser = DocumentParser()
doc = parser.parse("/path/to/document.pdf")

# Access document-specific features
for chunk in doc.chunks:
    print(f"Element: {chunk.element_type}")
    if chunk.page_number:
        print(f"  Page: {chunk.page_number}")
    print(f"  Content: {chunk.content[:100]}...")
```

#### FallbackTextParser

Fallback parser for plain text files and unsupported formats.

**Location:** `agentic_inquiry.parsers.implementations.fallback_text`

**Features:**
- Semantic chunking with overlap
- Encoding detection (UTF-8, Latin-1, etc.)
- Paragraph-based splitting
- FTS text generation

**Example:**
```python
from agentic_inquiry.parsers.implementations import FallbackTextParser

parser = FallbackTextParser()
doc = parser.parse("/path/to/file.txt")

# Simple text chunks
for chunk in doc.chunks:
    print(f"Chunk {chunk.chunk_id}:")
    print(f"  {chunk.content[:100]}...")
```

### Utility Functions

#### create_parser_chain()

Create a parser chain with all registered parsers.

```python
def create_parser_chain() -> ParserChain
```

**Returns:**
- `ParserChain`: Chain with all auto-registered parsers.

**Example:**
```python
from agentic_inquiry.parsers import create_parser_chain

chain = create_parser_chain()
doc = chain.parse("file.py")
```

#### available_parsers()

Get a list of all registered parser names.

```python
def available_parsers() -> list[str]
```

**Returns:**
- `list[str]`: List of registered parser names.

**Example:**
```python
from agentic_inquiry.parsers.executor import available_parsers

parsers = available_parsers()
print(f"Available parsers: {', '.join(parsers)}")
```

#### execute_parser()

Execute a specific parser on a file.

```python
def execute_parser(parser: BaseParser, file_path: str) -> ParsedDocument
```

**Parameters:**
- `parser` (BaseParser): Parser instance to use.
- `file_path` (str): Path to the file to parse.

**Returns:**
- `ParsedDocument`: Parsed document.

**Example:**
```python
from agentic_inquiry.parsers.executor import get_parser_instance, execute_parser

parser = get_parser_instance("unified_code")
doc = execute_parser(parser, "file.py")
```

### Parser Registration

Parsers are automatically registered using the `@register_parser` decorator.

#### Custom Parser Example

```python
from agentic_inquiry.parsers.models import BaseParser, ParsedDocument, ParserChunk
from agentic_inquiry.parsers.executor import register_parser

@register_parser(name="custom", priority=75)
class CustomParser(BaseParser):
    """Custom parser for specific file types."""
    
    def can_parse(self, file_path: str) -> bool:
        """Check if this parser can handle the file."""
        return file_path.endswith('.custom')
    
    def parse(self, file_path: str) -> ParsedDocument:
        """Parse the file and return a ParsedDocument."""
        # Read file
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Create chunks
        chunks = [
            ParserChunk(
                chunk_id=f"{file_path}:0",
                content=content,
                content_type="PROSE",
                line_start=1,
                line_end=len(content.split('\n')),
                fts_text=content
            )
        ]
        
        # Return parsed document
        return ParsedDocument(
            doc_id=file_path,
            file_path=file_path,
            chunks=chunks,
            metadata={"parser": "custom"}
        )
```

### Parser Configuration

Parser behavior can be configured through the configuration system:

```yaml
parsers:
  unified_code:
    enabled: true
    priority: 100
  document:
    enabled: true
    priority: 50
  text:
    enabled: true
    priority: 0
```

### Parser Best Practices

1. **Use ParserChain**: Always use `ParserChain` instead of calling parsers directly. It handles fallback logic and priority ordering.

2. **Check Symbols**: Not all chunks have symbols. Always check `chunk.symbols` before accessing.

3. **Handle Relationships**: Relationships may reference symbols in other files. Use the indexing pipeline to resolve cross-file references.

4. **FTS Text**: Use `chunk.fts_text` for full-text search, not `chunk.content`. FTS text is optimized for search.

5. **Content Types**: Filter chunks by `content_type` when you need specific types (CODE vs PROSE).

---

## Indexing

The indexing system processes parsed documents and stores them in the vector database. It handles document chunks, graph entities (symbols), and relationships between entities.

### Core Classes

#### IndexingPipeline

The main class for indexing documents into the database.

**Location:** `agentic_inquiry.indexing.pipeline`

##### Factory Method (Recommended)

```python
@classmethod
async def from_config(
    cls,
    config: Config,
    project_id: str,
    workspace: Path | None = None
) -> IndexingPipeline
```

**Parameters:**
- `config` (Config): Configuration instance
- `project_id` (str): Project identifier for data isolation
- `workspace` (Path, optional): Workspace directory path

**Example:**
```python
from agentic_inquiry.config import Config
from agentic_inquiry.indexing.pipeline import IndexingPipeline

# Recommended: Use factory method
config = Config.load()
pipeline = await IndexingPipeline.from_config(
    config=config,
    project_id="my-project"
)

# Index a directory
await pipeline.index_directory(
    path="/path/to/code",
    wait=True
)
```

##### Constructor

Direct construction requires all dependencies. Use `from_config()` instead for automatic dependency injection.

**Required Parameters:**
- `storage` (StorageFacade): Storage facade for database operations
- `config` (Config): Configuration instance
- `project_id` (str): Project identifier
- `event_system` (EventSystem): **Required.** Event system for tracking operations

**Optional Parameters:**
- `parser_chain` (ParserChain, optional): Custom parser chain
- `symbol_registry` (SymbolRegistry, optional): Symbol registry instance
- `document_cache` (DocumentCache, optional): Document cache instance
- `file_tracker` (FileTracker, optional): File change tracker
- `enable_watcher` (bool): Enable file watching. Default: False

**Manual Construction Example:**
```python
from agentic_inquiry.config import Config
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.events import EventSystem
from agentic_inquiry.indexing.pipeline import IndexingPipeline

config = Config.load()

# Create dependencies
storage = await StorageFacade.from_config(config, project_id="my-project")
event_system = EventSystem.from_config(config, project_id="my-project")
await event_system.start()

try:
    # Manual construction (not recommended)
    pipeline = IndexingPipeline(
        storage=storage,
        config=config,
        project_id="my-project",
        event_system=event_system
    )

    await pipeline.process_document(doc)
finally:
    await event_system.stop()
```

##### Methods

###### process_document()

Process a parsed document and index it into the database.

```python
async def process_document(self, parsed_doc: ParsedDocument) -> None
```

**Parameters:**
- `parsed_doc` (ParsedDocument): Parsed document from the parser system.

**Returns:**
- None

**Raises:**
- `ValueError`: If document validation fails.
- `DatabaseError`: If database operations fail.

**Example:**
```python
from agentic_inquiry.parsers import create_parser_chain

# Parse a file
chain = create_parser_chain()
doc = chain.parse("example.py")

# Index the document
await pipeline.process_document(doc)
```

**What it does:**
1. Validates the parsed document
2. Generates embeddings for each chunk
3. Stores document chunks in the database
4. Extracts and stores graph entities (symbols)
5. Queues relationships for later resolution
6. Updates the symbol registry

###### flush_pending_relationships()

Resolve and store all pending relationships between symbols.

```python
async def flush_pending_relationships(self) -> int
```

**Returns:**
- `int`: Number of relationships created.

**Raises:**
- `DatabaseError`: If database operations fail.

**Example:**
```python
# Index multiple files
for file_path in files:
    doc = chain.parse(file_path)
    await pipeline.process_document(doc)

# Resolve cross-file relationships
rel_count = await pipeline.flush_pending_relationships()
print(f"Created {rel_count} relationships")
```

**What it does:**
1. Resolves import targets across files
2. Matches function calls to definitions
3. Links references to their targets
4. Stores relationships in the database
5. Provides resolution statistics

###### remove_file_data()

Remove all data associated with a file from the database.

```python
async def remove_file_data(self, file_path: str) -> None
```

**Parameters:**
- `file_path` (str): Absolute path to the file to remove.

**Returns:**
- None

**Example:**
```python
# Remove a file from the index
await pipeline.remove_file_data("/path/to/file.py")
```

**What it does:**
1. Deletes document chunks for the file
2. Removes graph entities defined in the file
3. Removes relationships involving the file's symbols
4. Updates the symbol registry
5. Invalidates cache entries

###### reindex_document()

Reindex a file (remove old data and index new data).

```python
async def reindex_document(self, file_path: str) -> None
```

**Parameters:**
- `file_path` (str): Absolute path to the file to reindex.

**Returns:**
- None

**Example:**
```python
# Reindex a modified file
await pipeline.reindex_document("/path/to/modified_file.py")
```

**What it does:**
1. Removes existing data for the file
2. Parses the file again
3. Processes the new parsed document
4. Updates all related data

###### get_resolution_stats()

Get statistics about relationship resolution.

```python
def get_resolution_stats(self) -> dict
```

**Returns:**
- `dict`: Statistics about resolved, unresolved, and ambiguous relationships.

**Example:**
```python
stats = pipeline.get_resolution_stats()
print(f"Resolved: {stats['resolved']}")
print(f"Unresolved: {stats['unresolved']}")
print(f"Ambiguous: {stats['ambiguous']}")
```

###### validate_relationships()

Validate all relationships in the database for consistency.

```python
async def validate_relationships(self) -> dict
```

**Returns:**
- `dict`: Validation results with counts of valid, invalid, and orphaned relationships.

**Example:**
```python
results = await pipeline.validate_relationships()
print(f"Valid: {results['valid']}")
print(f"Invalid: {results['invalid']}")
print(f"Orphaned: {results['orphaned']}")
```

###### Cache Management Methods

```python
def get_cached_document(self, file_path: str) -> ParsedDocument | None
def cache_document(self, file_path: str, parsed_doc: ParsedDocument) -> None
def invalidate_cache(self, file_path: str | None = None) -> None
```

**Example:**
```python
# Check cache
cached = pipeline.get_cached_document("/path/to/file.py")
if cached:
    await pipeline.process_document(cached)
else:
    doc = chain.parse(file_path)
    pipeline.cache_document(file_path, doc)
    await pipeline.process_document(doc)

# Invalidate cache
pipeline.invalidate_cache("/path/to/file.py")  # Specific file
pipeline.invalidate_cache()  # All cache
```

###### stop_watching()

Stop the file watcher if enabled.

```python
def stop_watching(self) -> None
```

**Example:**
```python
pipeline.stop_watching()
```

### Symbol Registry

The symbol registry tracks all symbols in the codebase for efficient lookup and resolution.

**Location:** `agentic_inquiry.indexing.symbol_registry`

#### SymbolRegistry

Manages symbol definitions and lookups.

##### Methods

###### register_symbol()

Register a symbol definition.

```python
def register_symbol(
    self,
    symbol_name: str,
    file_path: str,
    symbol_type: str,
    metadata: dict | None = None
) -> None
```

**Parameters:**
- `symbol_name` (str): Name of the symbol.
- `file_path` (str): File where the symbol is defined.
- `symbol_type` (str): Type of symbol (function, class, variable, etc.).
- `metadata` (dict, optional): Additional symbol metadata.

**Example:**
```python
from agentic_inquiry.indexing.symbol_registry import SymbolRegistry

registry = SymbolRegistry()
registry.register_symbol(
    symbol_name="MyClass",
    file_path="/path/to/file.py",
    symbol_type="class",
    metadata={"line": 10}
)
```

###### lookup_symbol()

Look up a symbol by name.

```python
def lookup_symbol(self, symbol_name: str) -> list[dict]
```

**Parameters:**
- `symbol_name` (str): Name of the symbol to look up.

**Returns:**
- `list[dict]`: List of symbol definitions (may be multiple if symbol is defined in multiple files).

**Example:**
```python
definitions = registry.lookup_symbol("MyClass")
for defn in definitions:
    print(f"Found in: {defn['file_path']}")
```

###### remove_file_symbols()

Remove all symbols from a file.

```python
def remove_file_symbols(self, file_path: str) -> None
```

**Parameters:**
- `file_path` (str): File whose symbols should be removed.

**Example:**
```python
registry.remove_file_symbols("/path/to/file.py")
```

### Indexing Workflows

#### Basic Indexing

```python
import asyncio
from pathlib import Path
from agentic_inquiry.config import Config
from agentic_inquiry.mcp.factories import create_mcp_services
from agentic_inquiry.parsers import create_parser_chain

async def index_files(files: list[Path]):
    # Setup
    config = Config.load()
    services = await create_mcp_services(config, "my-project")
    pipeline = services["indexing_pipeline"]
    chain = create_parser_chain()
    
    # Index files
    for file_path in files:
        doc = chain.parse(str(file_path))
        await pipeline.process_document(doc)
    
    # Resolve relationships
    rel_count = await pipeline.flush_pending_relationships()
    print(f"Created {rel_count} relationships")

# Run
files = list(Path("src").rglob("*.py"))
asyncio.run(index_files(files))
```

#### Incremental Updates

```python
async def update_file(file_path: str):
    db_manager = LanceDBManager("./vector_db")
    pipeline = IndexingPipeline(db_manager, str(Path.cwd()))
    
    # Reindex the modified file
    await pipeline.reindex_document(file_path)
    
    # Resolve any new relationships
    await pipeline.flush_pending_relationships()
```

#### With File Watching

```python
async def index_with_watching():
    db_manager = LanceDBManager("./vector_db")
    pipeline = IndexingPipeline(
        db_manager,
        str(Path.cwd()),
        enable_watcher=True  # Enable automatic reindexing
    )
    
    # Initial indexing
    chain = create_parser_chain()
    for file_path in Path("src").rglob("*.py"):
        doc = chain.parse(str(file_path))
        await pipeline.process_document(doc)
    
    await pipeline.flush_pending_relationships()
    
    # File watcher will now automatically reindex changed files
    print("Watching for file changes...")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pipeline.stop_watching()
```

### Embedding Configuration

The indexing pipeline uses the embedding registry to generate vectors for chunks.

```python
from agentic_inquiry.embeddings.registry import embedding_registry
from agentic_inquiry.embeddings.sentence_transformer import SentenceTransformerEmbedder

# Configure embedder before indexing
embedder = SentenceTransformerEmbedder(model_name="all-MiniLM-L6-v2")
embedding_registry.configure_default_embedder(embedder, ndims=384)

# Now index documents
pipeline = IndexingPipeline(db_manager, project_root)
await pipeline.process_document(doc)
```

See [Custom Embeddings Guide](../customization/extending.md#custom-embeddings) for details.

### Performance Considerations

#### Batch Processing

For large codebases, process files in batches:

```python
async def index_in_batches(files: list[Path], batch_size: int = 100):
    db_manager = LanceDBManager("./vector_db")
    pipeline = IndexingPipeline(db_manager, str(Path.cwd()))
    chain = create_parser_chain()
    
    for i in range(0, len(files), batch_size):
        batch = files[i:i + batch_size]
        
        # Process batch
        for file_path in batch:
            doc = chain.parse(str(file_path))
            await pipeline.process_document(doc)
        
        # Flush relationships after each batch
        await pipeline.flush_pending_relationships()
        
        print(f"Processed {min(i + batch_size, len(files))}/{len(files)} files")
```

#### Memory Management

For very large codebases, invalidate cache periodically:

```python
for i, file_path in enumerate(files):
    doc = chain.parse(str(file_path))
    await pipeline.process_document(doc)
    
    # Clear cache every 1000 files
    if i % 1000 == 0:
        pipeline.invalidate_cache()
```

### Indexing Best Practices

1. **Always flush relationships**: Call `flush_pending_relationships()` after indexing files to resolve cross-file references.

2. **Use caching**: Enable caching for better performance, especially during development.

3. **Batch processing**: Process files in batches for large codebases to manage memory.

4. **Validate periodically**: Run `validate_relationships()` periodically to check data integrity.

5. **Handle errors**: Wrap indexing operations in try-except blocks to handle parsing failures gracefully.

6. **Configure embeddings first**: Always configure the embedding registry before creating the indexing pipeline.

---

## Search

The search system provides multiple search strategies: vector search (semantic similarity), full-text search (keyword matching), hybrid search (combining both), and graph-filtered search (using knowledge graph relationships).

### Core Classes

#### SearchService

The main class for performing searches across indexed documents.

**Location:** `agentic_inquiry.search.service`

##### Factory Method (Recommended)

```python
@classmethod
async def from_config(
    cls,
    config: Config | None = None,
    project_id: str | None = None
) -> SearchService
```

**Parameters:**
- `config` (Config, optional): Configuration instance. If None, loads default.
- `project_id` (str, optional): Project ID. If None, uses `config.storage.default_project_id`.

**Example:**
```python
from agentic_inquiry.config import Config
from agentic_inquiry.search.service import SearchService

# Recommended: Use factory method
config = Config.load()
search_service = await SearchService.from_config(
    config=config,
    project_id="my-project"
)

# Perform search
results = await search_service.hybrid_search(
    query_vector=embedding,
    query_fts="authentication",
    limit=10
)
```

##### Constructor

Direct construction requires all dependencies. Use `from_config()` instead for automatic dependency injection.

**Required Parameters:**
- `storage` (StorageFacade): Storage facade instance
- `config` (Config): Configuration instance

**Optional Parameters:**
- `event_system` (EventSystem, optional): Event system for tracking. If None, uses no-op event system.
- `project_id` (str, optional): Project ID. If None, uses storage's project_id.

**Manual Construction Example:**
```python
from agentic_inquiry.config import Config
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.search.service import SearchService
from agentic_inquiry.events import EventSystem

config = Config.load()

# Create dependencies
storage = await StorageFacade.from_config(config, project_id="my-project")
event_system = EventSystem.from_config(config, project_id="my-project")
await event_system.start()

try:
    # Manual construction (not recommended)
    search_service = SearchService(
        storage=storage,
        config=config,
        event_system=event_system
    )

    results = await search_service.vector_search(query_vector)
finally:
    await event_system.stop()
```

##### Methods

###### vector_search()

Perform semantic similarity search using vector embeddings.

```python
async def vector_search(
    self,
    query_vector: list[float],
    limit: int = 10,
    filters: dict | None = None,
    project_id: str | None = "current",
    project_ids: list[str] | None = None
) -> list[dict]
```

**Parameters:**
- `query_vector` (list[float]): Query embedding vector.
- `limit` (int, optional): Maximum number of results to return. Default: 10.
- `filters` (dict, optional): Metadata filters to apply (e.g., `{"language": "python"}`).
- `project_id` (str | None, optional): Project ID to search. "current" uses config project, None searches all. Default: "current".
- `project_ids` (list[str], optional): List of project IDs for multi-project search. Overrides `project_id`.

**Returns:**
- `list[dict]`: List of search results with metadata, scores, and `project_id`.

**Example:**
```python
from agentic_inquiry.embeddings.registry import embedding_registry

# Generate query vector
embedder = embedding_registry.get_default_embedder()
query_vector = embedder.generate(["database indexing"])[0]

# Search current project (default)
results = await search_service.vector_search(
    query_vector=query_vector,
    limit=5
)

# Search specific project
results = await search_service.vector_search(
    query_vector=query_vector,
    limit=5,
    project_id="proj_abc123"
)

# Search multiple projects
results = await search_service.vector_search(
    query_vector=query_vector,
    limit=5,
    project_ids=["proj_abc123", "proj_def456"]
)

# Search all projects
results = await search_service.vector_search(
    query_vector=query_vector,
    limit=5,
    project_id=None
)

for result in results:
    print(f"[{result['project_id']}] {result['file_path']}: {result['_distance']}")
```

**Result Format:**
```python
{
    "chunk_id": "file.py:10-20",
    "file_path": "/path/to/file.py",
    "content": "chunk content...",
    "content_type": "CODE",
    "language": "python",
    "element_type": "function",
    "element_name": "my_function",
    "line_start": 10,
    "line_end": 20,
    "_distance": 0.234,  # Lower is more similar
    "metadata": {...}
}
```

###### fts_search()

Perform full-text search using keyword matching.

```python
async def fts_search(
    self,
    query_fts: str,
    limit: int = 10,
    filters: dict | None = None
) -> list[dict]
```

**Parameters:**
- `query_fts` (str): Full-text search query string.
- `limit` (int, optional): Maximum number of results to return. Default: 10.
- `filters` (dict, optional): Metadata filters to apply.

**Returns:**
- `list[dict]`: List of search results with metadata and scores.

**Example:**
```python
# Search for specific keywords
results = await search_service.fts_search(
    query_fts="IndexingPipeline process_document",
    limit=5
)

for result in results:
    print(f"{result['file_path']}: {result['score']}")
```

**Query Syntax:**
- Simple terms: `"database indexing"`
- Phrase search: `"exact phrase"`
- Boolean operators: `"database AND indexing"`
- Wildcards: `"index*"`

###### hybrid_search()

Perform hybrid search combining vector and full-text search.

```python
async def hybrid_search(
    self,
    query_vector: list[float],
    query_fts: str,
    limit: int = 10,
    vector_weight: float = 0.7,
    fts_weight: float = 0.3,
    filters: dict | None = None
) -> list[dict]
```

**Parameters:**
- `query_vector` (list[float]): Query embedding vector.
- `query_fts` (str): Full-text search query string.
- `limit` (int, optional): Maximum number of results to return. Default: 10.
- `vector_weight` (float, optional): Weight for vector search results. Default: 0.7.
- `fts_weight` (float, optional): Weight for FTS results. Default: 0.3.
- `filters` (dict, optional): Metadata filters to apply.

**Returns:**
- `list[dict]`: List of search results with combined scores.

**Example:**
```python
# Generate query vector
query_vector = embedder.generate(["database operations"])[0]

# Hybrid search
results = await search_service.hybrid_search(
    query_vector=query_vector,
    query_fts="LanceDB database",
    limit=5,
    vector_weight=0.6,
    fts_weight=0.4
)

for result in results:
    print(f"{result['file_path']}: {result['score']}")
```

**How it works:**
1. Performs vector search and FTS separately
2. Combines results using Reciprocal Rank Fusion (RRF)
3. Applies weights to balance semantic vs keyword matching
4. Returns unified ranked results

###### graph_filtered_search()

Perform search with graph-based filtering and ranking.

```python
async def graph_filtered_search(
    self,
    query_vector: list[float],
    query_fts: str | None = None,
    limit: int = 10,
    relationship_types: list[str] | None = None,
    max_depth: int = 2,
    rerank_by_graph: bool = True
) -> list[dict]
```

**Parameters:**
- `query_vector` (list[float]): Query embedding vector.
- `query_fts` (str, optional): Full-text search query string.
- `limit` (int, optional): Maximum number of results to return. Default: 10.
- `relationship_types` (list[str], optional): Types of relationships to consider (e.g., `["imports", "calls"]`).
- `max_depth` (int, optional): Maximum graph traversal depth. Default: 2.
- `rerank_by_graph` (bool, optional): Whether to rerank results using graph metadata. Default: True.

**Returns:**
- `list[dict]`: List of search results with graph-enhanced ranking.

**Example:**
```python
# Search with graph context
results = await search_service.graph_filtered_search(
    query_vector=query_vector,
    query_fts="database operations",
    limit=5,
    relationship_types=["calls", "imports"],
    max_depth=2,
    rerank_by_graph=True
)

for result in results:
    print(f"{result['file_path']}: {result['score']}")
    if 'graph_context' in result:
        print(f"  Related symbols: {result['graph_context']['related_symbols']}")
```

**Graph Features:**
- Filters results based on graph relationships
- Boosts results with more connections (PageRank-style)
- Includes graph context in results
- Considers relationship types and depth

###### advanced_filter_search()

Perform search with advanced metadata filtering.

```python
async def advanced_filter_search(
    self,
    filters: dict,
    limit: int = 10
) -> list[dict]
```

**Parameters:**
- `filters` (dict): Complex filter expressions.
- `limit` (int, optional): Maximum number of results to return. Default: 10.

**Returns:**
- `list[dict]`: List of filtered results.

**Example:**
```python
# Complex filtering
results = await search_service.advanced_filter_search(
    filters={
        "language": "python",
        "content_type": "CODE",
        "element_type": {"in": ["function", "class"]},
        "line_start": {"gte": 100}
    },
    limit=10
)
```

**Filter Operators:**
- `"value"`: Exact match
- `{"in": [values]}`: Match any value in list
- `{"gte": value}`: Greater than or equal
- `{"lte": value}`: Less than or equal
- `{"gt": value}`: Greater than
- `{"lt": value}`: Less than

###### enrich_with_graph_context()

Enrich search results with graph context.

```python
async def enrich_with_graph_context(
    self,
    results: list[dict],
    max_depth: int = 2
) -> list[dict]
```

**Parameters:**
- `results` (list[dict]): Search results to enrich.
- `max_depth` (int, optional): Maximum graph traversal depth. Default: 2.

**Returns:**
- `list[dict]`: Results with added graph context.

**Example:**
```python
# Get basic search results
results = await search_service.vector_search(query_vector, limit=5)

# Enrich with graph context
enriched = await search_service.enrich_with_graph_context(results, max_depth=2)

for result in enriched:
    if 'graph_context' in result:
        print(f"Related symbols: {result['graph_context']['related_symbols']}")
        print(f"Relationships: {result['graph_context']['relationships']}")
```

###### from_config()

Create a SearchService from configuration.

```python
@classmethod
def from_config(cls, db_manager: LanceDBManager, config: dict) -> SearchService
```

**Parameters:**
- `db_manager` (LanceDBManager): Database manager instance.
- `config` (dict): Configuration dictionary.

**Returns:**
- `SearchService`: Configured search service instance.

**Example:**
```python
config = {
    "default_limit": 10,
    "max_limit": 100,
    "hybrid_search": {
        "vector_weight": 0.7,
        "fts_weight": 0.3
    },
    "graph_search": {
        "max_depth": 3,
        "rerank_by_graph": True
    }
}

search_service = SearchService.from_config(db_manager, config)
```

### Search Patterns

#### Basic Semantic Search

```python
from agentic_inquiry.embeddings.registry import embedding_registry

async def semantic_search(query: str, limit: int = 5):
    # Generate query vector
    embedder = embedding_registry.get_default_embedder()
    query_vector = embedder.generate([query])[0]
    
    # Search
    results = await search_service.vector_search(
        query_vector=query_vector,
        limit=limit
    )
    
    return results

# Use
results = await semantic_search("database indexing implementation")
```

#### Keyword Search

```python
async def keyword_search(query: str, limit: int = 5):
    results = await search_service.fts_search(
        query_fts=query,
        limit=limit
    )
    return results

# Use
results = await keyword_search("IndexingPipeline")
```

#### Combined Search

```python
async def combined_search(
    semantic_query: str,
    keyword_query: str,
    limit: int = 5
):
    # Generate query vector
    embedder = embedding_registry.get_default_embedder()
    query_vector = embedder.generate([semantic_query])[0]
    
    # Hybrid search
    results = await search_service.hybrid_search(
        query_vector=query_vector,
        query_fts=keyword_query,
        limit=limit
    )
    
    return results

# Use
results = await combined_search(
    semantic_query="database operations",
    keyword_query="LanceDB"
)
```

#### Filtered Search

```python
async def search_python_functions(query: str, limit: int = 5):
    embedder = embedding_registry.get_default_embedder()
    query_vector = embedder.generate([query])[0]
    
    results = await search_service.vector_search(
        query_vector=query_vector,
        limit=limit,
        filters={
            "language": "python",
            "content_type": "CODE",
            "element_type": "function"
        }
    )
    
    return results

# Use
results = await search_python_functions("async database operations")
```

#### Graph-Enhanced Search

```python
async def search_with_context(query: str, limit: int = 5):
    embedder = embedding_registry.get_default_embedder()
    query_vector = embedder.generate([query])[0]
    
    results = await search_service.graph_filtered_search(
        query_vector=query_vector,
        query_fts=query,
        limit=limit,
        relationship_types=["calls", "imports", "references"],
        max_depth=2,
        rerank_by_graph=True
    )
    
    return results

# Use
results = await search_with_context("database indexing")
```

### Result Processing

#### Extracting Information

```python
def process_results(results: list[dict]):
    for result in results:
        # File information
        file_path = result['file_path']
        line_range = f"{result['line_start']}-{result['line_end']}"
        
        # Content
        content = result['content']
        content_type = result['content_type']
        
        # Code-specific
        if content_type == "CODE":
            element_type = result.get('element_type')
            element_name = result.get('element_name')
            language = result.get('language')
            print(f"{language} {element_type}: {element_name}")
        
        # Score
        score = result.get('score', result.get('_distance', 0))
        print(f"Score: {score}")
        
        # Graph context (if available)
        if 'graph_context' in result:
            related = result['graph_context']['related_symbols']
            print(f"Related symbols: {', '.join(related[:5])}")
```

#### Grouping by File

```python
def group_by_file(results: list[dict]) -> dict:
    grouped = {}
    for result in results:
        file_path = result['file_path']
        if file_path not in grouped:
            grouped[file_path] = []
        grouped[file_path].append(result)
    return grouped

# Use
results = await search_service.vector_search(query_vector, limit=20)
by_file = group_by_file(results)

for file_path, chunks in by_file.items():
    print(f"\n{file_path}: {len(chunks)} matches")
```

#### Deduplication

```python
def deduplicate_results(results: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    
    for result in results:
        chunk_id = result['chunk_id']
        if chunk_id not in seen:
            seen.add(chunk_id)
            unique.append(result)
    
    return unique
```

### Search Configuration

Search behavior can be configured through the configuration system:

```yaml
search:
  default_limit: 10
  max_limit: 100
  
  hybrid_search:
    vector_weight: 0.7
    fts_weight: 0.3
    rerank_by_graph: true
  
  graph_search:
    max_depth: 3
    relationship_types:
      - calls
      - imports
      - contains
      - references
```

### Performance Optimization

#### Limit Results

```python
# Request only what you need
results = await search_service.vector_search(
    query_vector=query_vector,
    limit=5  # Don't request 100 if you only need 5
)
```

#### Use Filters

```python
# Filter early to reduce search space
results = await search_service.vector_search(
    query_vector=query_vector,
    limit=10,
    filters={"language": "python"}  # Reduces search space
)
```

#### Cache Query Vectors

```python
# Cache frequently used query vectors
query_cache = {}

def get_query_vector(query: str) -> list[float]:
    if query not in query_cache:
        embedder = embedding_registry.get_default_embedder()
        query_cache[query] = embedder.generate([query])[0]
    return query_cache[query]
```

#### Batch Queries

```python
async def batch_search(queries: list[str]) -> list[list[dict]]:
    # Generate all vectors at once
    embedder = embedding_registry.get_default_embedder()
    query_vectors = embedder.generate(queries)
    
    # Search in parallel
    tasks = [
        search_service.vector_search(vector, limit=5)
        for vector in query_vectors
    ]
    
    results = await asyncio.gather(*tasks)
    return results
```

### Search Best Practices

1. **Choose the right search type**: Use vector search for semantic queries, FTS for exact terms, and hybrid for balanced results.

2. **Apply filters**: Use metadata filters to narrow search space and improve performance.

3. **Limit results**: Request only the number of results you need.

4. **Use graph features**: Enable graph ranking for better relevance in code search.

5. **Cache query vectors**: Cache frequently used query vectors to avoid regeneration.

6. **Handle empty results**: Always check if results are empty before processing.

7. **Process scores correctly**: Lower `_distance` means more similar for vector search; higher `score` means better match for FTS.

---

## Database

The database system supports multiple backends (LanceDB, PostgreSQL, AlloyDB) through the StorageFacade, providing vector search, full-text search, graph storage, and transaction support.

### Core Classes

#### StorageFacade

The main class for storage operations across all backends.

**Location:** `agentic_inquiry.storage.facade`

##### Factory Method

```python
@classmethod
async def from_config(
    cls,
    config: Config,
    project_id: str,
    workspace: Optional[Path] = None
) -> StorageFacade
```

**Parameters:**
- `config` (Config): Configuration object containing backend settings
- `project_id` (str): Project identifier for data isolation
- `workspace` (Path, optional): Workspace directory for data storage

**Example:**
```python
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.config import Config

# From configuration (recommended)
config = Config.load()
storage = await StorageFacade.from_config(config, project_id="my-project")

# With custom workspace
storage = await StorageFacade.from_config(
    config,
    project_id="my-project",
    workspace=Path("/custom/workspace")
)
```

**Backend Configuration:**

StorageFacade automatically routes to the configured backend:

```python
# LanceDB (default)
config.storage.backend = "lancedb"

# PostgreSQL with local embedding
config.storage.backend = "postgresql"
config.storage.backends.postgresql.embedding_strategy = "local"

# AlloyDB with server-side embedding
config.storage.backend = "alloydb"
config.storage.backends.alloydb.embedding_strategy = "server_side"
config.storage.backends.alloydb.embedding_model = "text-embedding-005"
```

**Project Isolation:**

All storage operations automatically filter by the provided project_id:

```python
storage = await StorageFacade.from_config(config, project_id="my-project")

# All queries automatically filter by project_id
results = await storage.vector_search(query_vector=embedding, limit=10)
# Only returns results for "my-project"
```

##### Methods

###### initialize()

Initialize the storage facade and connect to backends.

```python
async def initialize(self) -> None
```

**Example:**
```python
storage = await StorageFacade.from_config(config, project_id="my-project")
# Already initialized by from_config()
```

###### upsert_chunks()

Add or update document chunks in storage.

```python
async def upsert_chunks(self, chunks: list[dict]) -> None
```

**Parameters:**
- `chunks` (list[dict]): List of document chunk dictionaries.

**Example:**
```python
chunks = [
    {
        "chunk_id": "file.py:1-10",
        "file_path": "/path/to/file.py",
        "content": "chunk content",
        "embedding": [0.1, 0.2, ...],  # For local embedding
        # OR
        # "embedding": None,  # For server-side embedding (AlloyDB)
        "content_type": "CODE",
        "language": "python",
        "line_start": 1,
        "line_end": 10,
        "metadata": {"element_type": "function"}
    }
]

await storage.upsert_chunks(chunks)
```

**Required Fields:**
- `chunk_id`: Unique identifier
- `file_path`: Source file path
- `content`: Chunk content
- `content_type`: "CODE", "PROSE", or "MIXED"

**Optional Fields:**
- `embedding`: Vector embedding (required for local embedding, NULL for server-side)
- `language`: Programming language or document type
- `metadata`: Additional metadata dictionary
- `line_start`, `line_end`: Line range
- `page_number`: Page number for documents
- `fts_text`: Full-text search optimized text
- `metadata`: Additional metadata

###### add_graph_entities()

Add graph entities (symbols) to the database.

```python
async def add_graph_entities(self, entities: list[dict]) -> None
```

**Parameters:**
- `entities` (list[dict]): List of entity dictionaries.

**Example:**
```python
entities = [
    {
        "entity_id": "file.py::MyClass",
        "entity_name": "MyClass",
        "entity_type": "class",
        "file_path": "/path/to/file.py",
        "chunk_id": "file.py:10-50",
        "line_number": 10,
        "metadata": {"docstring": "My class"}
    }
]

await db_manager.add_graph_entities(entities)
```

**Required Fields:**
- `entity_id`: Unique identifier
- `entity_name`: Symbol name
- `entity_type`: Type (function, class, variable, etc.)
- `file_path`: Source file path
- `chunk_id`: Associated chunk ID

**Optional Fields:**
- `line_number`: Definition line
- `metadata`: Additional metadata

###### add_graph_relationships()

Add relationships between entities to the database.

```python
async def add_graph_relationships(self, relationships: list[dict]) -> None
```

**Parameters:**
- `relationships` (list[dict]): List of relationship dictionaries.

**Example:**
```python
relationships = [
    {
        "id": "rel_1",
        "source_id": "file1.py::func1",  # Origin entity
        "target_id": "file2.py::func2",  # Destination entity
        "type": "calls",
        "source_file": "/path/to/file1.py",
        "target_file": "/path/to/file2.py",
        "confidence": 1.0,
        "metadata": {"line": 15}
    }
]

await db_manager.add_graph_relationships(relationships)
```

**Required Fields:**
- `id`: Unique identifier
- `source_id`: Source entity ID (origin of relationship)
- `target_id`: Target entity ID (destination of relationship)
- `type`: Relationship type (calls, imports, references, etc.)

**Optional Fields:**
- `source_file`: Source file path
- `target_file`: Target file path
- `confidence`: Resolution confidence (0.0-1.0, default: 1.0)
- `metadata`: Additional metadata

**Field Naming:**
The relationship schema uses `source_id` and `target_id` to represent directed edges:
- `source_id`: Where the relationship originates (e.g., the caller in a "calls" relationship)
- `target_id`: Where the relationship points to (e.g., the callee in a "calls" relationship)
- `source_file`: Source file path
- `target_file`: Target file path

**Optional Fields:**
- `metadata`: Additional metadata

###### delete_document_chunks()

Delete document chunks from the database.

```python
async def delete_document_chunks(self, filters: dict) -> None
```

**Parameters:**
- `filters` (dict): Filter criteria for deletion.

**Example:**
```python
# Delete all chunks from a file
await db_manager.delete_document_chunks(
    filters={"file_path": "/path/to/file.py"}
)

# Delete specific chunks
await db_manager.delete_document_chunks(
    filters={"chunk_id": {"in": ["chunk1", "chunk2"]}}
)
```

###### delete_graph_entities()

Delete graph entities from the database.

```python
async def delete_graph_entities(self, filters: dict) -> None
```

**Parameters:**
- `filters` (dict): Filter criteria for deletion.

**Example:**
```python
# Delete all entities from a file
await db_manager.delete_graph_entities(
    filters={"file_path": "/path/to/file.py"}
)
```

###### delete_graph_relationships()

Delete relationships from the database.

```python
async def delete_graph_relationships(self, filters: dict) -> None
```

**Parameters:**
- `filters` (dict): Filter criteria for deletion.

**Example:**
```python
# Delete relationships involving a file
await db_manager.delete_graph_relationships(
    filters={"source_file": "/path/to/file.py"}
)
```

###### vector_search()

Perform vector similarity search.

```python
async def vector_search(
    self,
    query_vector: list[float],
    limit: int = 10,
    filters: dict | None = None,
    metric: str = "cosine"
) -> list[dict]
```

**Parameters:**
- `query_vector` (list[float]): Query embedding vector.
- `limit` (int, optional): Maximum number of results. Default: 10.
- `filters` (dict, optional): Metadata filters.
- `metric` (str, optional): Distance metric ("cosine", "l2", "dot"). Default: "cosine".

**Returns:**
- `list[dict]`: Search results with `_distance` scores.

**Example:**
```python
results = await db_manager.vector_search(
    query_vector=[0.1, 0.2, ...],
    limit=5,
    filters={"language": "python"}
)

for result in results:
    print(f"{result['file_path']}: {result['_distance']}")
```

###### fts_search()

Perform full-text search.

```python
async def fts_search(
    self,
    query_fts: str,
    limit: int = 10,
    filters: dict | None = None
) -> list[dict]
```

**Parameters:**
- `query_fts` (str): Full-text search query.
- `limit` (int, optional): Maximum number of results. Default: 10.
- `filters` (dict, optional): Metadata filters.

**Returns:**
- `list[dict]`: Search results with `score` values.

**Example:**
```python
results = await db_manager.fts_search(
    query_fts="IndexingPipeline",
    limit=5
)

for result in results:
    print(f"{result['file_path']}: {result['score']}")
```

###### advanced_filter()

Perform advanced filtering on document chunks.

```python
async def advanced_filter(
    self,
    filters: dict,
    limit: int = 10
) -> list[dict]
```

**Parameters:**
- `filters` (dict): Complex filter expressions.
- `limit` (int, optional): Maximum number of results. Default: 10.

**Returns:**
- `list[dict]`: Filtered results.

**Example:**
```python
results = await db_manager.advanced_filter(
    filters={
        "language": "python",
        "content_type": "CODE",
        "line_start": {"gte": 100, "lte": 200}
    },
    limit=10
)
```

**Filter Operators:**
- Exact match: `{"field": "value"}`
- In list: `{"field": {"in": [values]}}`
- Comparison: `{"field": {"gte": value, "lte": value}}`
- Greater/less than: `{"field": {"gt": value, "lt": value}}`

###### query_entities()

Query graph entities with filters. Convenience method that wraps `advanced_filter()` for the `graph_entities` table.

```python
async def query_entities(
    self,
    filters: dict | None = None,
    limit: int = 100,
    project_id: str | None = None
) -> list[dict]
```

**Parameters:**
- `filters` (dict, optional): Filter criteria for entities. Default: None (no filters).
- `limit` (int, optional): Maximum number of results. Default: 100.
- `project_id` (str, optional): Project identifier to filter by. If None, uses current project from config.

**Returns:**
- `list[dict]`: List of entity dictionaries matching the filters.

**Example:**
```python
# Query all entities in a file
entities = await db_manager.query_entities(
    filters={"file_path": "/path/to/file.py"}
)

# Query entities by type
classes = await db_manager.query_entities(
    filters={"entity_type": "class"},
    limit=50
)

# Query entities by name pattern
entities = await db_manager.query_entities(
    filters={"entity_name": "MyClass"}
)

# Query with project isolation
entities = await db_manager.query_entities(
    filters={"entity_type": "function"},
    project_id="my-project"
)
```

**Common Use Cases:**
- Finding all symbols defined in a file
- Looking up entities by name or type
- Discovering available classes or functions
- Building symbol indexes for code navigation

###### query_relationships()

Query graph relationships with filters. Convenience method that wraps `advanced_filter()` for the `graph_relationships` table.

```python
async def query_relationships(
    self,
    filters: dict | None = None,
    limit: int = 100,
    project_id: str | None = None
) -> list[dict]
```

**Parameters:**
- `filters` (dict, optional): Filter criteria for relationships. Default: None (no filters).
- `limit` (int, optional): Maximum number of results. Default: 100.
- `project_id` (str, optional): Project identifier to filter by. If None, uses current project from config.

**Returns:**
- `list[dict]`: List of relationship dictionaries matching the filters.

**Example:**
```python
# Query relationships from a specific entity
outgoing = await db_manager.query_relationships(
    filters={"source_id": "file.py::MyClass"}
)

# Query relationships to a specific entity
incoming = await db_manager.query_relationships(
    filters={"target_id": "file.py::MyClass"}
)

# Query by relationship type
calls = await db_manager.query_relationships(
    filters={"type": "calls"},
    limit=50
)

# Query relationships involving a file
file_rels = await db_manager.query_relationships(
    filters={"source_file": "/path/to/file.py"}
)

# Query with project isolation
rels = await db_manager.query_relationships(
    filters={"type": "imports"},
    project_id="my-project"
)
```

**Common Use Cases:**
- Finding all functions called by a specific function
- Discovering what imports a module
- Building call graphs and dependency trees
- Analyzing code relationships for refactoring

**Field Naming:**
- `source_id`: Entity where the relationship originates (e.g., the caller)
- `target_id`: Entity where the relationship points to (e.g., the callee)
- Relationships are directional: source → target

###### upsert()

Insert new records or update existing records in a table. Checks for existing records by a key field and updates them if found, otherwise inserts new records.

```python
async def upsert(
    self,
    table_name: str,
    data: list[dict],
    key_field: str = "id"
) -> None
```

**Parameters:**
- `table_name` (str): Name of the table to upsert into ("document_chunks", "graph_entities", "graph_relationships", etc.).
- `data` (list[dict]): List of record dictionaries to upsert.
- `key_field` (str, optional): Field name to use for uniqueness check. Default: "id".

**Returns:**
- None

**Example:**
```python
# Upsert entities (insert new, update existing)
entities = [
    {
        "entity_id": "file.py::MyClass",
        "entity_name": "MyClass",
        "entity_type": "class",
        "file_path": "/path/to/file.py",
        "chunk_id": "file.py:10-50",
        "line_number": 10
    }
]

await db_manager.upsert(
    table_name="graph_entities",
    data=entities,
    key_field="entity_id"
)

# Upsert relationships
relationships = [
    {
        "id": "rel_1",
        "source_id": "file1.py::func1",
        "target_id": "file2.py::func2",
        "type": "calls"
    }
]

await db_manager.upsert(
    table_name="graph_relationships",
    data=relationships,
    key_field="id"
)

# Upsert document chunks
chunks = [
    {
        "chunk_id": "file.py:1-10",
        "file_path": "/path/to/file.py",
        "content": "updated content",
        "vector": [0.1, 0.2, ...],
        "content_type": "CODE"
    }
]

await db_manager.upsert(
    table_name="document_chunks",
    data=chunks,
    key_field="chunk_id"
)
```

**Common Use Cases:**
- Updating entity metadata without duplicating records
- Refreshing relationship confidence scores
- Incrementally updating indexed content
- Session persistence and state management

**Performance Notes:**
- For large datasets, consider batching upsert operations
- Upsert checks for existence before inserting, which adds overhead
- For bulk initial loading, use `add_*()` methods directly if you know records don't exist
- Empty data lists are handled gracefully (no-op)

**Behavior:**
1. For each record in `data`, checks if a record with the same `key_field` value exists
2. If exists: updates the existing record with new values
3. If not exists: inserts as a new record
4. Handles empty data lists gracefully (returns immediately)

###### graph_ranking_available()

Check if graph ranking data is available.

```python
async def graph_ranking_available(self) -> bool
```

**Returns:**
- `bool`: True if graph entities and relationships exist.

**Example:**
```python
if await db_manager.graph_ranking_available():
    print("Graph ranking is available")
else:
    print("No graph data yet")
```

###### create_tables_and_indexes()

Create tables and indexes asynchronously (for initialization).

```python
async def create_tables_and_indexes(self) -> None
```

**Example:**
```python
db_manager = LanceDBManager("./vector_db")
await db_manager.create_tables_and_indexes()
```

### Transaction Support

#### DatabaseTransaction

Context manager for ACID transactions.

**Location:** `agentic_inquiry.database.transaction`

##### Usage

```python
from agentic_inquiry.database.transaction import DatabaseTransaction

async with DatabaseTransaction(db_manager) as txn:
    # All operations within this block are transactional
    await txn.add_document_chunks(chunks)
    await txn.add_graph_entities(entities)
    await txn.add_graph_relationships(relationships)
    
    # Commit happens automatically on success
    # Rollback happens automatically on exception
```

##### Methods

The transaction object provides the same methods as LanceDBManager:
- `add_document_chunks()`
- `add_graph_entities()`
- `add_graph_relationships()`
- `delete_document_chunks()`
- `delete_graph_entities()`
- `delete_graph_relationships()`

**Example with Error Handling:**
```python
try:
    async with DatabaseTransaction(db_manager) as txn:
        await txn.add_document_chunks(chunks)
        await txn.add_graph_entities(entities)
        # If this fails, all changes are rolled back
        await txn.add_graph_relationships(relationships)
except Exception as e:
    print(f"Transaction failed: {e}")
    # All changes have been rolled back
```

### Data Models

#### DocumentChunk Schema

```python
{
    "chunk_id": str,           # Required: Unique identifier
    "file_path": str,          # Required: Source file path
    "content": str,            # Required: Chunk content
    "vector": list[float],     # Required: Embedding vector
    "content_type": str,       # Required: "CODE", "PROSE", "MIXED"
    "language": str,           # Optional: Language/type
    "element_type": str,       # Optional: Element type
    "element_name": str,       # Optional: Element name
    "line_start": int,         # Optional: Start line
    "line_end": int,           # Optional: End line
    "page_number": int,        # Optional: Page number
    "fts_text": str,           # Optional: FTS-optimized text
    "metadata": dict           # Optional: Additional metadata
}
```

#### GraphEntity Schema

```python
{
    "entity_id": str,          # Required: Unique identifier
    "entity_name": str,        # Required: Symbol name
    "entity_type": str,        # Required: Type (function, class, etc.)
    "file_path": str,          # Required: Source file
    "chunk_id": str,           # Required: Associated chunk
    "line_number": int,        # Optional: Definition line
    "metadata": dict           # Optional: Additional metadata
}
```

#### GraphRelationship Schema

```python
{
    "id": str,                 # Required: Unique identifier
    "source_id": str,          # Required: Source entity (origin)
    "target_id": str,          # Required: Target entity (destination)
    "type": str,               # Required: Type (calls, imports, etc.)
    "source_file": str,        # Optional: Source file path
    "target_file": str,        # Optional: Target file path
    "confidence": float,       # Optional: Resolution confidence (0.0-1.0)
    "metadata": dict           # Optional: Additional metadata
}
```

**Field Naming Convention:**
- `source_id`: Entity ID where the relationship originates
- `target_id`: Entity ID where the relationship points to
- Relationships are directional: source → target

### Common Patterns

#### Initialization

```python
from agentic_inquiry.database import LanceDBManager

# Create and initialize database
db_manager = LanceDBManager("./vector_db")
await db_manager.create_tables_and_indexes()

# Or use async connect
await db_manager.connect()
```

#### Batch Operations

```python
# Add multiple chunks at once
chunks = [chunk1, chunk2, chunk3, ...]
await db_manager.add_document_chunks(chunks)

# Add multiple entities at once
entities = [entity1, entity2, entity3, ...]
await db_manager.add_graph_entities(entities)
```

#### Transactional Updates

```python
async def update_file_data(file_path: str, new_chunks: list[dict]):
    async with DatabaseTransaction(db_manager) as txn:
        # Delete old data
        await txn.delete_document_chunks({"file_path": file_path})
        await txn.delete_graph_entities({"file_path": file_path})
        
        # Add new data
        await txn.add_document_chunks(new_chunks)
        await txn.add_graph_entities(new_entities)
```

#### Search with Filters

```python
# Vector search with language filter
results = await db_manager.vector_search(
    query_vector=vector,
    limit=10,
    filters={"language": "python"}
)

# FTS search with content type filter
results = await db_manager.fts_search(
    query_fts="database",
    limit=10,
    filters={"content_type": "CODE"}
)
```

#### Complex Filtering

```python
# Find Python functions between lines 100-200
results = await db_manager.advanced_filter(
    filters={
        "language": "python",
        "element_type": "function",
        "line_start": {"gte": 100},
        "line_end": {"lte": 200}
    },
    limit=20
)
```

### Database Configuration

Database behavior can be configured through the configuration system:

```yaml
storage:
  uri: "./vector_db"
  tables:
    document_chunks: "document_chunks"
    graph_entities: "graph_entities"
    graph_relationships: "graph_relationships"
```

### Performance Considerations

#### Batch Size

```python
# Process in batches for large datasets
batch_size = 1000
for i in range(0, len(all_chunks), batch_size):
    batch = all_chunks[i:i + batch_size]
    await db_manager.add_document_chunks(batch)
```

#### Index Creation

```python
# Create indexes after bulk loading
await db_manager.create_tables_and_indexes()
```

#### Connection Pooling

```python
# Reuse database manager instance
db_manager = LanceDBManager("./vector_db")

# Use for multiple operations
await db_manager.add_document_chunks(chunks1)
await db_manager.add_document_chunks(chunks2)
await db_manager.add_document_chunks(chunks3)
```

### Error Handling

```python
from agentic_inquiry.database.transaction import DatabaseTransaction

try:
    async with DatabaseTransaction(db_manager) as txn:
        await txn.add_document_chunks(chunks)
except ValueError as e:
    print(f"Invalid data: {e}")
except ConnectionError as e:
    print(f"Database connection failed: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

### Database Best Practices

1. **Use transactions**: Wrap related operations in transactions for consistency.

2. **Batch operations**: Add multiple items at once instead of one at a time.

3. **Create indexes**: Call `await create_tables_and_indexes()` after bulk loading.

4. **Reuse connections**: Create one LanceDBManager instance and reuse it.

5. **Filter early**: Use filters to reduce search space and improve performance.

6. **Handle errors**: Wrap database operations in try-except blocks.

7. **Validate data**: Ensure all required fields are present before adding data.

8. **Use configuration**: Initialize with `Config` object for proper storage paths and project isolation.

### FileTracker

The FileTracker tracks file content hashes to detect changes and avoid unnecessary re-parsing.

**Location:** `agentic_inquiry.watching.file_tracker`

#### Constructor

```python
FileTracker(
    db_path: str | Path | None = None,
    config: Config | None = None
)
```

**Parameters:**
- `db_path` (str | Path, optional): Path to SQLite database file. If None, uses config.
- `config` (Config, optional): Configuration object. If provided, uses `config.storage.get_file_tracker_path()`.

**Example:**
```python
from agentic_inquiry.watching import FileTracker
from agentic_inquiry.config import Config

# From configuration (recommended)
config = Config.load()
tracker = FileTracker(config=config)

# Explicit path (legacy)
tracker = FileTracker(db_path=".file_tracker.db")
```

#### Methods

##### has_changed()

Check if a file has changed since last tracking.

```python
def has_changed(self, file_path: str) -> bool
```

**Parameters:**
- `file_path` (str): Absolute path to the file.

**Returns:**
- `bool`: True if file has changed or is new, False if unchanged.

**Example:**
```python
if tracker.has_changed("/path/to/file.py"):
    print("File has changed, needs reindexing")
    # Reindex the file
    tracker.update_file_state("/path/to/file.py")
```

##### update_file_state()

Update the tracked state of a file.

```python
def update_file_state(self, file_path: str) -> None
```

**Parameters:**
- `file_path` (str): Absolute path to the file.

**Example:**
```python
# After successfully indexing a file
tracker.update_file_state("/path/to/file.py")
```

##### remove_file()

Remove a file from tracking.

```python
def remove_file(self, file_path: str) -> None
```

**Parameters:**
- `file_path` (str): Absolute path to the file.

**Example:**
```python
# When a file is deleted
tracker.remove_file("/path/to/deleted_file.py")
```

##### get_all_tracked_files()

Get all currently tracked files.

```python
def get_all_tracked_files(self) -> list[str]
```

**Returns:**
- `list[str]`: List of all tracked file paths.

**Example:**
```python
tracked_files = tracker.get_all_tracked_files()
print(f"Tracking {len(tracked_files)} files")
```

#### Project Isolation

FileTracker automatically isolates data by project:

```python
config = Config.load()
tracker = FileTracker(config=config)

# All operations automatically scoped to config.storage.get_project_id()
tracker.update_file_state("/path/to/file.py")
# Only affects current project
```

### DocumentCache

The DocumentCache provides LRU caching for parsed documents with optional disk persistence.

**Location:** `agentic_inquiry.cache.document_cache`

#### Constructor

```python
DocumentCache(
    max_size: int = 1000,
    config: Config | None = None
)
```

**Parameters:**
- `max_size` (int, optional): Maximum number of documents to cache. Default: 1000.
- `config` (Config, optional): Configuration object for disk persistence settings.

**Example:**
```python
from agentic_inquiry.cache import DocumentCache
from agentic_inquiry.config import Config

# Memory-only cache (default)
cache = DocumentCache(max_size=1000)

# With disk persistence
config = Config.load()
cache = DocumentCache(max_size=1000, config=config)
# Disk persistence enabled if config.storage.document_cache.enabled is True
```

#### Methods

##### get()

Retrieve a cached document.

```python
def get(self, file_path: str) -> ParsedDocument | None
```

**Parameters:**
- `file_path` (str): Absolute path to the file.

**Returns:**
- `ParsedDocument | None`: Cached document or None if not found.

**Example:**
```python
cached_doc = cache.get("/path/to/file.py")
if cached_doc:
    print("Using cached document")
else:
    print("Need to parse file")
```

##### put()

Store a document in the cache.

```python
def put(self, file_path: str, document: ParsedDocument) -> None
```

**Parameters:**
- `file_path` (str): Absolute path to the file.
- `document` (ParsedDocument): Parsed document to cache.

**Example:**
```python
from agentic_inquiry.parsers import create_parser_chain

chain = create_parser_chain()
doc = chain.parse("/path/to/file.py")
cache.put("/path/to/file.py", doc)
```

##### invalidate()

Remove a document from the cache.

```python
def invalidate(self, file_path: str | None = None) -> None
```

**Parameters:**
- `file_path` (str, optional): File to invalidate. If None, clears entire cache.

**Example:**
```python
# Invalidate specific file
cache.invalidate("/path/to/file.py")

# Clear entire cache
cache.invalidate()
```

##### clear()

Clear all cached documents.

```python
def clear(self) -> None
```

**Example:**
```python
cache.clear()
```

#### Disk Persistence

Enable disk persistence in configuration:

```yaml
storage:
  document_cache:
    enabled: true
    path: "document_cache"
```

**Features:**
- Automatic save to disk on cache updates
- Automatic load from disk on initialization
- Project-isolated cache keys
- Resilient error handling (falls back to memory-only)

**Example:**
```python
from agentic_inquiry.config import Config

# Load config with disk persistence enabled
config = Config.load()

# Cache automatically persists to disk
cache = DocumentCache(config=config)
cache.put("/path/to/file.py", doc)
# Saved to: {storage.root}/document_cache/entries/proj_abc123_hash.pkl

# On next initialization, cache is loaded from disk
cache2 = DocumentCache(config=config)
cached_doc = cache2.get("/path/to/file.py")
# Loaded from disk
```

#### Project Isolation

DocumentCache automatically isolates data by project:

```python
config = Config.load()
cache = DocumentCache(config=config)

# Cache keys automatically prefixed with project_id
cache.put("/path/to/file.py", doc)
# Stored as: "proj_abc123:/path/to/file.py"
```

---

## See Also

- [Customization Guide](../customization/extending.md) - Learn how to extend the system
- [Architecture Overview](../architecture/overview.md) - Understand the system architecture
