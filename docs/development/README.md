# Development Documentation

**Navigation hub for contributors and maintainers.**

## Development Guides

- **[Async Best Practices](async-best-practices.md)** - Async patterns, error handling, and performance optimization
- **[Parser Development Guidelines](parser-guidelines.md)** - Creating custom parsers for new file types
- **[Security Guidelines](security.md)** - Security best practices for path validation, API keys, and input sanitization
- **[Adapter Implementation Guide](adapter-implementation-guide.md)** - How to build database adapters and pass compliance tests
- **[Release & Deprecation Policy](release-policy.md)** - Rules for breaking changes and migrations

## Utility Scripts

Development and debugging scripts in `/scripts/`:

| Script | Purpose |
|--------|---------|
| `debug_graph_functionality.py` | Debug graph functionality at scale - indexes full codebase and analyzes relationships |
| `validate_examples.py` | Validates example files for common issues before CI |
| `convert_model.py` | Downloads and converts embedding models to ONNX format |

**Usage:**
```bash
# Debug graph relationships
uv run python scripts/debug_graph_functionality.py --verbose

# Validate examples
uv run python scripts/validate_examples.py

# Convert models
uv run python scripts/convert_model.py --model sentence-transformers/all-MiniLM-L6-v2
```

## Related Documentation

- **[Contributing Guide](../CONTRIBUTING.md)** - Main contribution guidelines
- **[Architecture Overview](../architecture/overview.md)** - System architecture
- **[Extending Guide](../customization/extending.md)** - Custom components

## Next Steps

- **Want to contribute?** → Start with [Contributing Guide](../CONTRIBUTING.md)
- **Building custom components?** → See [Extending Guide](../customization/extending.md)
- **Understanding the architecture?** → Read [Architecture Overview](../architecture/overview.md)
