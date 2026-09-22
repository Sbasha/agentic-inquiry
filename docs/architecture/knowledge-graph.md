---
title: "Knowledge Graph Architecture"
tier: 3
audience: developer
journey: ["extension-developer"]
related: ["overview.md", "../guides/knowledge-graph.md", "search.md"]
last_updated: 2025-10-28
---

# Knowledge Graph Architecture

The knowledge graph tracks relationships between code symbols and document entities. This document explains the graph structure, relationship types, and how the graph is used for search and navigation.

## Overview

The knowledge graph is a directed graph where:
- **Nodes** are entities (functions, classes, headings, sections, etc.)
- **Edges** are relationships (calls, imports, contains, references, etc.)

The graph enables:
- Cross-file symbol resolution
- Code navigation (find callers, find callees)
- Document structure navigation
- Graph-aware search ranking

## Graph Schema

### Entities (Nodes)

Entities are stored in the `graph_entities` table:

```python
@dataclass
class GraphEntity:
    id: str                      # Unique identifier
    name: str                    # Entity name
    qualified_name: str          # Fully qualified name
    type: str                    # Entity type (function, class, etc.)
    file_path: str               # Source file
    start_line: int              # Start line number
    end_line: int                # End line number
    parent_id: Optional[str]     # Parent entity (for methods)
    metadata: Dict[str, Any]     # Additional metadata
```

**Entity Types:**

**Code Entities:**
- `function`: Function definitions
- `class`: Class definitions
- `method`: Class methods
- `variable`: Global/class variables
- `import`: Import statements
- `module`: Module/file

**Document Entities:**
- `heading`: Document headings (H1-H6)
- `section`: Document sections
- `figure`: Images and figures
- `table`: Tables
- `list`: Lists

### Relationships (Edges)

Relationships are stored in the `graph_relationships` table:

```python
@dataclass
class GraphRelationship:
    id: str                      # Unique identifier
    source_id: str               # Source entity ID (origin of relationship)
    target_id: str               # Target entity ID (destination of relationship)
    type: str                    # Relationship type
    source_file: str             # Source file path
    target_file: str             # Target file path
    confidence: float            # Resolution confidence (0.0-1.0)
    metadata: Dict[str, Any]     # Additional metadata
```

**Field Naming Convention:**

The relationship schema uses `source_id` and `target_id` to represent the directed edge between entities:
- **`source_id`**: The entity ID where the relationship originates (e.g., the caller in a "calls" relationship)
- **`target_id`**: The entity ID where the relationship points to (e.g., the callee in a "calls" relationship)

**Important:** Previous versions used `from_entity` and `to_entity` field names. These have been standardized to `source_id` and `target_id` throughout the codebase for consistency. All queries and relationship creation code should use the new field names.

**Relationship Types:**

**Code Relationships:**
- `calls`: Function/method calls another function/method
- `imports`: Module imports another module
- `contains`: Class contains method, module contains function
- `inherits`: Class inherits from another class
- `references`: Variable references another entity
- `defines`: File defines entity

**Document Relationships:**
- `contains`: Section contains subsection
- `references`: Cross-reference between sections
- `follows`: Sequential ordering
- `links_to`: Hyperlink to another document

## Resolution Strategies

The `RelationshipResolver` uses multiple strategies to resolve imported symbols to their definitions. Understanding these strategies helps optimize resolution success rates and debug failures.

### Strategy Overview

Strategies are tried in order of confidence, with earlier strategies preferred:

1. **Database Lookup** - Check existing relationships from previous indexing (confidence: 1.0)
2. **Improved Symbol Resolution** - Multi-strategy entity lookup (confidence: 0.9)
3. **Direct Import Path** - Convert import path to file path (confidence: 1.0)
4. **Exact Type Match** - Match by name and type (confidence: 0.7-1.0)
5. **Module Path Resolution** - Python module path index (confidence: 0.95)
6. **Proximity-Based** - Score by file proximity and patterns (confidence: 0.5-0.8)

### Resolution Process

```python
# Example resolution flow
async def resolve_import(target_name, source_file, import_path):
    # 1. Check cache first
    if cached_result := cache.get(target_name, source_file):
        return cached_result
    
    # 2. Try database lookup (re-indexing scenario)
    if db_result := await check_database(target_name, source_file):
        return db_result  # confidence: 1.0
    
    # 3. Try improved symbol resolution
    if entity_id := await resolve_symbol(target_name, import_path, source_file):
        return get_entity_details(entity_id)  # confidence: 0.9
    
    # 4. Try import path resolution
    if import_path and (result := resolve_by_import_path(import_path, target_name)):
        return result  # confidence: 1.0
    
    # 5. Try exact type match
    if target_type and (result := resolve_by_type(target_name, target_type)):
        return result  # confidence: 0.7-1.0
    
    # 6. Try module path (Python-specific)
    if is_python and import_path and (result := resolve_by_module(import_path, target_name)):
        return result  # confidence: 0.95
    
    # 7. Try proximity-based resolution
    if result := resolve_by_proximity(target_name, source_file):
        return result  # confidence: 0.5-0.8
    
    # 8. Resolution failed
    return None
```

### Strategy Details

#### Database Lookup Strategy

Queries existing relationships from previous indexing runs. This is the fastest and most reliable strategy when re-indexing files.

**Advantages:**
- Highest confidence (1.0)
- Preserves previous resolutions
- Fast (single database query)

**Limitations:**
- Only works for re-indexing
- Requires previous successful resolution
- Fails if database is cleared

**When to use:**
- Incremental updates
- Re-indexing after code changes
- Maintaining consistency

#### Improved Symbol Resolution Strategy

Uses multiple sub-strategies to find symbols in the entity registry:

1. **Exact match** - Name + file path from import path
2. **Fuzzy match** - Name only, returns multiple candidates
3. **Project-aware** - Prefers symbols from same project

**Advantages:**
- High confidence (0.9)
- Handles various import patterns
- Project-aware matching

**Limitations:**
- Requires symbols to be indexed
- File path must match
- May return multiple candidates

**When to use:**
- First-time indexing
- Cross-file imports
- Project-local symbols

#### Direct Import Path Strategy

Converts Python import paths to file paths and looks up symbols.

**Example:**
```python
# Import: from agent_vault.indexing.pipeline import IndexingPipeline
# Converts to: agent_vault/indexing/pipeline.py
# Looks up: IndexingPipeline in that file
```

**Advantages:**
- Highest confidence (1.0) when successful
- Explicit file path
- Fast lookup

**Limitations:**
- Requires import path
- Python-specific
- File structure must match imports

**When to use:**
- Explicit imports with full paths
- Standard Python project structure
- Known file locations

#### Exact Type Match Strategy

Matches symbols by name and type (e.g., "IndexingPipeline" + "class").

**Advantages:**
- Reduces ambiguity
- Works across languages
- Type-safe resolution

**Limitations:**
- Requires type information
- May have multiple matches
- Type must be correct

**When to use:**
- Type information available
- Unique symbol names
- Type-safe imports

#### Module Path Resolution Strategy

Uses symbol registry's module path index for Python imports.

**Advantages:**
- High confidence (0.95)
- Fast index lookup
- Python-optimized

**Limitations:**
- Python-specific
- Requires module path indexing
- May miss complex packages

**When to use:**
- Python codebases
- Standard module structure
- Package imports

#### Proximity-Based Strategy

Scores candidates by multiple factors:
- File proximity (same directory, nearby directories)
- Naming patterns (file name matches symbol)
- Directory structure (conventional locations)
- Co-occurrence (files often imported together)
- Import frequency (commonly used symbols)

**Advantages:**
- Works without explicit paths
- Handles ambiguous cases
- Uses multiple signals

**Limitations:**
- Lower confidence (0.5-0.8)
- May select wrong symbol
- Requires minimum confidence threshold

**When to use:**
- Fallback strategy
- Ambiguous imports
- Common symbol names

### Resolution Statistics

Track resolution performance:

```python
# Get resolution statistics
stats = resolver.get_resolution_stats()

print(f"Resolution rate: {stats['resolution_rate']:.1f}%")
print(f"Total attempts: {stats['total_attempts']}")
print(f"Resolved: {stats['resolved']}")
print(f"Unresolved: {stats['unresolved']}")

print(f"\nBy strategy:")
for strategy, count in stats['by_strategy'].items():
    percentage = (count / stats['total_attempts'] * 100) if stats['total_attempts'] > 0 else 0
    print(f"  {strategy}: {count} ({percentage:.1f}%)")

print(f"\nCache performance:")
print(f"  Hit rate: {stats['cache_hit_rate']:.1f}%")
print(f"  Cache size: {stats['cache_size']}")
```

### Optimizing Resolution Success

**Best practices for high resolution rates (>50%):**

1. **Index in dependency order** - Index base modules before dependent modules
2. **Provide import paths** - Include full import paths in relationship metadata
3. **Use consistent file paths** - Normalize paths to project-relative format
4. **Enable debug logging** - Monitor which strategies succeed/fail
5. **Clear cache when needed** - Clear after re-indexing or registry updates

**Target metrics:**
- Resolution rate: >50% (good), >70% (excellent)
- Cache hit rate: >80%
- Database lookup: >30% for re-indexing
- Improved resolution: >40% for first-time indexing

## Graph Construction

### Entity Extraction

Entities are extracted during parsing:

```python
# Code entity extraction (Python example)
def parse_function(node):
    return ParserEntity(
        name=node.name,
        type="function",
        file_path=current_file,
        start_line=node.start_line,
        end_line=node.end_line,
        metadata={
            "parameters": extract_parameters(node),
            "return_type": extract_return_type(node),
            "docstring": extract_docstring(node)
        }
    )

# Document entity extraction (Markdown example)
def parse_heading(node):
    return ParserEntity(
        name=node.text,
        type="heading",
        file_path=current_file,
        start_line=node.start_line,
        metadata={
            "level": node.level,  # H1, H2, etc.
            "anchor": generate_anchor(node.text)
        }
    )
```

### Relationship Extraction

Relationships are extracted during parsing and resolved during indexing:

**Extraction:**
```python
# Extract function call relationship
def parse_call(node):
    return ParserRelationship(
        source=current_function,
        target=node.function_name,
        type="calls",
        metadata={
            "line": node.line,
            "arguments": extract_arguments(node)
        }
    )
```

**Resolution:**
```python
# Resolve target entity
async def resolve_relationship(relationship):
    # Find target entity in symbol registry
    target_entity = symbol_registry.resolve(
        name=relationship.target,
        context=relationship.source_file
    )
    
    if target_entity:
        return GraphRelationship(
            source_id=relationship.source_id,
            target_id=target_entity.id,
            type=relationship.type,
            confidence=target_entity.confidence
        )
    else:
        # Target not found
        return None
```

## Graph Queries

### Find Entity

Find entity by name:

```python
# Find function by name
entity = await db_manager.find_entity(
    name="parse_document",
    type="function"
)
```

### Find Relationships

Find relationships for an entity using `source_id` and `target_id`:

```python
# Find all functions called by parse_document (outgoing relationships)
# Query by source_id to find where relationships originate
relationships = await db_manager.find_relationships(
    source_id=entity.id,
    type="calls"
)

# Find all callers of parse_document (incoming relationships)
# Query by target_id to find where relationships point to
relationships = await db_manager.find_relationships(
    target_id=entity.id,
    type="calls"
)
```

**Querying Relationships:**

When querying relationships, use the appropriate field based on the direction:
- **Query by `source_id`**: Find outgoing relationships (what this entity calls, imports, contains, etc.)
- **Query by `target_id`**: Find incoming relationships (what calls this entity, imports this module, etc.)

Example with filters:

```python
# Find all "calls" relationships originating from a specific function
outgoing_calls = await db_manager.query_relationships(
    filters={"source_id": function_id, "type": "calls"}
)

# Find all "calls" relationships pointing to a specific function
incoming_calls = await db_manager.query_relationships(
    filters={"target_id": function_id, "type": "calls"}
)
```

### Graph Traversal

Traverse relationships to find connected entities:

```python
# Find all entities reachable from parse_document
visited = set()
queue = [entity.id]

while queue:
    current_id = queue.pop(0)
    if current_id in visited:
        continue
    
    visited.add(current_id)
    
    # Get outgoing relationships
    relationships = await db_manager.find_relationships(
        source_id=current_id
    )
    
    # Add targets to queue
    for rel in relationships:
        if rel.target_id not in visited:
            queue.append(rel.target_id)

# visited now contains all reachable entity IDs
```

### Multi-Hop Queries

Find entities N hops away:

```python
# Find all entities 2 hops from parse_document
async def find_n_hops(entity_id, n, relationship_types=None):
    current_level = {entity_id}
    visited = {entity_id}
    
    for _ in range(n):
        next_level = set()
        
        for eid in current_level:
            relationships = await db_manager.find_relationships(
                source_id=eid,
                types=relationship_types
            )
            
            for rel in relationships:
                if rel.target_id not in visited:
                    next_level.add(rel.target_id)
                    visited.add(rel.target_id)
        
        current_level = next_level
    
    return current_level
```

## Graph-Aware Search

### PageRank Computation

Compute importance scores for entities:

```python
def compute_pagerank(entities, relationships, damping=0.85, iterations=20):
    # Initialize PageRank scores
    pr = {e.id: 1.0 / len(entities) for e in entities}
    
    # Build adjacency list
    outgoing = defaultdict(list)
    for rel in relationships:
        outgoing[rel.source_id].append(rel.target_id)
    
    # Iterate
    for _ in range(iterations):
        new_pr = {}
        
        for entity_id in pr:
            # Base score
            score = (1 - damping) / len(entities)
            
            # Add contributions from incoming edges
            for source_id, targets in outgoing.items():
                if entity_id in targets:
                    score += damping * pr[source_id] / len(targets)
            
            new_pr[entity_id] = score
        
        pr = new_pr
    
    return pr
```

### Reranking with PageRank

Boost search results based on PageRank:

```python
async def rerank_by_graph(results, alpha=0.2):
    # Compute PageRank for all entities
    entities = await db_manager.get_all_entities()
    relationships = await db_manager.get_all_relationships()
    pagerank = compute_pagerank(entities, relationships)
    
    # Rerank results
    for result in results:
        # Get entity for this result
        entity = await db_manager.find_entity_by_chunk(result.id)
        
        if entity and entity.id in pagerank:
            # Boost score by PageRank
            result.score *= (1 + alpha * pagerank[entity.id])
    
    # Re-sort by new scores
    results.sort(key=lambda r: r.score, reverse=True)
    
    return results
```

## Graph Visualization

### Export to GraphML

Export graph for visualization:

```python
async def export_graphml(output_path):
    entities = await db_manager.get_all_entities()
    relationships = await db_manager.get_all_relationships()
    
    with open(output_path, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<graphml>\n')
        f.write('  <graph edgedefault="directed">\n')
        
        # Write nodes
        for entity in entities:
            f.write(f'    <node id="{entity.id}">\n')
            f.write(f'      <data key="name">{entity.name}</data>\n')
            f.write(f'      <data key="type">{entity.type}</data>\n')
            f.write(f'    </node>\n')
        
        # Write edges
        for rel in relationships:
            f.write(f'    <edge source="{rel.source_id}" target="{rel.target_id}">\n')
            f.write(f'      <data key="type">{rel.type}</data>\n')
            f.write(f'    </edge>\n')
        
        f.write('  </graph>\n')
        f.write('</graphml>\n')
```

### Visualization Tools

**Recommended Tools:**
- **Gephi**: Interactive graph visualization
- **Cytoscape**: Network analysis and visualization
- **NetworkX**: Python library for graph analysis
- **D3.js**: Web-based interactive visualization

## Graph Statistics

### Compute Statistics

```python
async def compute_graph_stats():
    entities = await db_manager.get_all_entities()
    relationships = await db_manager.get_all_relationships()
    
    # Basic stats
    num_entities = len(entities)
    num_relationships = len(relationships)
    
    # Entity type distribution
    entity_types = Counter(e.type for e in entities)
    
    # Relationship type distribution
    relationship_types = Counter(r.type for r in relationships)
    
    # Degree distribution
    in_degree = Counter(r.target_id for r in relationships)
    out_degree = Counter(r.source_id for r in relationships)
    
    # Connected components
    components = find_connected_components(entities, relationships)
    
    return {
        "num_entities": num_entities,
        "num_relationships": num_relationships,
        "entity_types": dict(entity_types),
        "relationship_types": dict(relationship_types),
        "avg_in_degree": sum(in_degree.values()) / num_entities,
        "avg_out_degree": sum(out_degree.values()) / num_entities,
        "num_components": len(components)
    }
```

## Graph Maintenance

### Incremental Updates

Update graph when files change:

```python
async def update_file(file_path):
    # Remove old entities and relationships
    old_entities = await db_manager.find_entities(file_path=file_path)
    for entity in old_entities:
        await db_manager.delete_entity(entity.id)
        await db_manager.delete_relationships(source_id=entity.id)
        await db_manager.delete_relationships(target_id=entity.id)
    
    # Re-index file
    parsed_doc = parser_chain.parse(file_path)
    await pipeline.index_document(parsed_doc)
```

### Garbage Collection

Remove orphaned entities:

```python
async def garbage_collect():
    entities = await db_manager.get_all_entities()
    relationships = await db_manager.get_all_relationships()
    
    # Find entities with no relationships
    connected_ids = set()
    for rel in relationships:
        connected_ids.add(rel.source_id)
        connected_ids.add(rel.target_id)
    
    # Delete orphaned entities
    for entity in entities:
        if entity.id not in connected_ids:
            await db_manager.delete_entity(entity.id)
```

## Performance Optimization

### Indexing

Create indexes for fast queries:

```python
# Index on entity name
await db_manager.create_index("graph_entities", "name")

# Index on relationship source/target
await db_manager.create_index("graph_relationships", "source_id")
await db_manager.create_index("graph_relationships", "target_id")
```

### Caching

Cache frequently accessed entities:

```python
# Entity cache
entity_cache = {}

async def get_entity(entity_id):
    if entity_id in entity_cache:
        return entity_cache[entity_id]
    
    entity = await db_manager.get_entity(entity_id)
    entity_cache[entity_id] = entity
    return entity
```

### Batch Queries

Fetch multiple entities in one query:

```python
# Instead of N queries
entities = []
for entity_id in entity_ids:
    entity = await db_manager.get_entity(entity_id)
    entities.append(entity)

# Use batch query
entities = await db_manager.get_entities(entity_ids)
```

## Next Steps

- Learn about [Architecture Overview](overview.md) for system architecture
- Review [API Reference](../api-reference/api.md#database) for graph query APIs
