# Error Message Security Guidelines

## What Must NOT Appear in Error Messages
- Absolute file paths (e.g., `/Users/name/project/...`)
- Internal database IDs (e.g., `entity_id: abc123-def456`)
- Stack traces or internal function names
- API keys, tokens, credentials
- Internal IP addresses or hostnames
- Session IDs or user identifiers

## What CAN Appear
- Generic error descriptions
- Error codes for debugging (e.g., `GRAPH_EMPTY_001`)
- User action suggestions
- Relative paths or file names without full path
- Public documentation links

## Examples

### DON'T
```python
raise MCPError(f"Failed to read /Users/dev/project/data/entity_{id}.json")
```

### DO
```python
return {"error_code": "ENTITY_READ_001", "message": "Entity not found", "suggestion": "Verify entity exists with list_entities"}
```

## Verification Method
- Grep error messages for path patterns: `/Users`, `/home`, `/var`
- Check for UUID patterns in user-facing strings
- Review all f-strings in error handling code
