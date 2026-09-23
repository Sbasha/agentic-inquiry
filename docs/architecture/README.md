# Architecture Documentation

**Navigation hub for system architecture and design documentation.**

---

## Quick Start by Role

### 🚀 Backend Engineers
**Understanding the system's core architecture:**
1. [Architecture Overview](overview.md) - Complete system architecture
2. [Design Decisions](design-decisions.md) - Why these architectural choices
3. [Async Architecture](async-architecture.md) - Async-first implementation
4. [API Reference](../api-reference/api.md) - Complete API documentation

### 🔌 Integration Engineers
**Integrating and extending the system:**
1. [Architecture Overview](overview.md#extension-points) - Extension mechanisms
2. [Parsers](parsers.md) - Parser system and custom parsers
3. [Search](search.md) - Search strategies and configuration
4. [Integration](integration.md) - AFP lifecycle contract and the ledger
5. [Development Guides](../development/README.md) - Contributing and extending

### ⚡ Performance Engineers
**Optimizing performance and concurrency:**
1. [Async Architecture](async-architecture.md) - Async patterns and best practices
2. [Architecture Overview](overview.md#async-first-design-philosophy) - Concurrency model
3. [Design Decisions](design-decisions.md) - Performance trade-offs
4. [Indexing](indexing.md) - Pipeline optimization

### 🔍 Extension Developers
**Building custom components:**
1. [Architecture Overview](overview.md#extension-points) - Where to extend
2. [Parsers](parsers.md) - Custom parser implementation
3. [Search](search.md) - Custom search strategies
4. [Development Guides](../development/README.md) - Development guidelines

---

## Core Architecture

### Essential Reading

→ **[Architecture Overview](overview.md)** - Start here for complete system architecture and design philosophy

This comprehensive document covers:
- System architecture and component relationships
- Async-first design philosophy and concurrency model
- Core components (parsers, indexing, search, database)
- Data flow (indexing and search pipelines)
- Extension points and customization
- Performance characteristics

---

## Component Deep Dives

### Data Processing
- **[Parsers](parsers.md)** - Parser system architecture and chain-of-responsibility pattern
- **[Indexing](indexing.md)** - Indexing pipeline architecture and data flow

### Search & Retrieval
- **[Search](search.md)** - Search strategies (vector, FTS, hybrid, graph) and ranking
- **[Embeddings](embeddings.md)** - How vectors are generated at ingestion + retrieval, providers, registry, dim propagation
- **[Knowledge Graph](knowledge-graph.md)** - Graph structure, relationships, and traversal

### System Design
- **[Async Architecture](async-architecture.md)** - Async-first design patterns and implementation
- **[Event System](event-system.md)** - Event tracking and lifecycle management
- **[Design Decisions](design-decisions.md)** - Key architectural choices and rationale

---

## Documentation by Topic

### Understanding the System
- **System Architecture** → [Architecture Overview](overview.md#system-architecture)
- **Data Flow** → [Architecture Overview](overview.md#data-flow)
- **Concurrency Model** → [Architecture Overview](overview.md#concurrency-model)
- **Component Interactions** → [Architecture Overview](overview.md#core-components)

### Working with Components
- **Parsing Files** → [Parsers](parsers.md)
- **Indexing Content** → [Indexing](indexing.md)
- **Searching** → [Search](search.md)
- **Graph Queries** → [Knowledge Graph](knowledge-graph.md)

### Extending the System
- **Custom Parsers** → [Parsers](parsers.md#parser-registration) and [Extending Guide](../customization/extending.md#custom-parsers)
- **Custom Embeddings** → [Architecture Overview](overview.md#custom-embeddings)
- **Custom Search** → [Search](search.md) and [Extending Guide](../customization/extending.md)
- **Event Integration** → [Event System](event-system.md) and [Architecture Overview](overview.md#event-tracking-integration)

### Performance & Optimization
- **Async Patterns** → [Async Architecture](async-architecture.md)
- **Concurrency Control** → [Architecture Overview](overview.md#concurrency-model)
- **Search Optimization** → [Search](search.md#performance-optimization)
- **Indexing Performance** → [Indexing](indexing.md) and [Architecture Overview](overview.md#performance-characteristics)

---

## Related Documentation

### Development & Extension
- **[Development Guides](../development/README.md)** - Contributing and extending
  - [Contributing Guide](../CONTRIBUTING.md)
  - [Style Guide](../STYLE_GUIDE.md)
  - [Parser Guidelines](../development/parser-guidelines.md)
  - [Security Best Practices](../development/security.md)

### Reference
- **[API Reference](../api-reference/api.md)** - Complete API documentation
- **[FAQ](../FAQ.md)** - Frequently asked questions

---

## Next Steps

### Getting Started
- **New to the architecture?** → Start with [Architecture Overview](overview.md)
- **Need API details?** → See [API Reference](../api-reference/api.md)

### Deep Dives
- **Understanding async patterns?** → Read [Async Architecture](async-architecture.md)
- **Curious about design choices?** → Explore [Design Decisions](design-decisions.md)
- **How does parsing work?** → Study [Parsers](parsers.md)
- **How does search work?** → Review [Search](search.md)

### Building & Extending
- **Building custom components?** → Follow [Development Guides](../development/README.md)
- **Adding custom parsers?** → See [Parsers](parsers.md#parser-registration)
- **Integrating events?** → Check [Event System](event-system.md)
- **Contributing code?** → Read [Contributing Guide](../CONTRIBUTING.md)
