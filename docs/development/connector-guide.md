# Connector Development Guide

This guide explains how to implement a content source connector for Agentic Inquiry.

## Implementation Status

**Status: IMPLEMENTED (Optional Feature)**

The connector abstraction is **fully implemented** in the codebase with working implementations for filesystem, S3, and GCS sources. However, connectors are **optional** in the indexing pipeline — most operations use direct filesystem walking for simplicity. Connectors are primarily useful for:

- Remote content sources (S3, GCS, GitHub)
- Change detection and incremental indexing
- Content materialization and caching
- Future extensibility to SaaS APIs (Notion, Confluence, etc.)

**Active Implementations:**
- `FileSystemConnector` - Local filesystem with change detection and watching (✓ Production-ready)
- `S3Connector` - AWS S3 via fsspec (✓ Working, requires optional `s3fs` dependency; `s3://bucket/key`)
- `GCSConnector` - Google Cloud Storage via fsspec (✓ Working, requires optional `gcsfs` dependency; `gcs://bucket/object`)

**Planned/Example Implementations:**
- Notion connector (see example below - not yet implemented)
- GitHub and other remote sources

The indexing pipeline's `connector` parameter is optional. When `None`, the pipeline walks the filesystem directly without connector abstraction.

## Overview

Connectors abstract content sources (filesystem, S3, GitHub, SaaS APIs) into a consistent interface for enumeration and retrieval. The indexing pipeline can optionally use connectors to discover and fetch content without knowing the source details.

**Key files:**
- `agentic_inquiry/connectors/types.py` - SourceItem, SourceContent types
- `agentic_inquiry/connectors/protocols.py` - ConnectorProtocol, capabilities
- `agentic_inquiry/connectors/filesystem.py` - Reference implementation
- `agentic_inquiry/connectors/base.py` - FsspecConnector base class
- `agentic_inquiry/connectors/s3.py` - S3 implementation example
- `agentic_inquiry/connectors/gcs.py` - GCS implementation example

## When to Use Connectors

**Use connectors when:**
- Indexing remote content sources (S3, GCS, GitHub, SaaS APIs)
- Implementing change detection for incremental indexing
- Content requires authentication or special handling
- Building reusable content source integrations

**Skip connectors when:**
- Indexing local filesystem only (the default path)
- Simple one-time indexing operations
- Performance is critical (direct filesystem access is faster)

The `IndexingPipeline` constructor accepts an optional `connector` parameter. When `None` (the default), the pipeline uses direct filesystem walking via parser chain discovery.

---

## Core Types

### SourceItem

Represents discoverable content (metadata only, not content itself):

```python
@dataclass(frozen=True)
class SourceItem:
    uri: str                              # Stable identifier
    content_hash: Optional[str] = None    # For change detection
    modified_at: Optional[datetime] = None
    size: Optional[int] = None
    content_type: Optional[str] = None    # MIME type
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**URI Conventions:**
- Local paths: `/path/to/file.py` (absolute, no `file://` prefix)
- S3: `s3://bucket/key`
- GCS: `gcs://bucket/object`
- GitHub: `github://org/repo/path@sha`

**Properties:**
- `item.is_local` - True if local filesystem path
- `item.protocol` - Protocol string (`'file'`, `'s3'`, etc.)
- `item.path` - Path without protocol prefix

### SourceContent

Retrieved content with data:

```python
@dataclass(frozen=True)
class SourceContent:
    data: bytes                           # Raw content
    encoding: Optional[str] = None        # Text encoding (None = binary)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Properties:**
- `content.text` - Decoded text (raises if binary)
- `content.is_binary` - True if encoding is None
- `content.size` - Length in bytes

---

## ConnectorProtocol

The core protocol requires two methods:

```python
@runtime_checkable
class ConnectorProtocol(Protocol):

    def list(self, root: str) -> AsyncIterator[SourceItem]:
        """Enumerate content items under a root path.

        Yields SourceItem for each discoverable content unit.
        """
        ...

    async def open(self, item: SourceItem) -> SourceContent:
        """Retrieve content for a source item."""
        ...
```

### list()

Enumerates content under a root path:

```python
async def list(self, root: str) -> AsyncIterator[SourceItem]:
    # Discover files/objects under root
    for path in discover_paths(root):
        yield SourceItem(
            uri=path,
            content_hash=compute_hash(path),
            modified_at=get_mtime(path),
            size=get_size(path),
            content_type=guess_mime_type(path),
        )
```

Requirements:
- Must be async generator
- Should handle ignore patterns internally
- Should compute content_hash for change detection
- Must raise `FileNotFoundError` if root doesn't exist

### open()

Retrieves content for a specific item:

```python
async def open(self, item: SourceItem) -> SourceContent:
    data = await fetch_content(item.uri)
    encoding = detect_encoding(data, item.uri)

    return SourceContent(
        data=data,
        encoding=encoding,
        metadata={"uri": item.uri, "size": len(data)},
    )
```

Requirements:
- Must be async
- Must set encoding correctly (None for binary)
- Must include `uri` in metadata for provenance
- Must raise `FileNotFoundError` if item doesn't exist

---

## Optional Capabilities

### WatchCapability

Real-time change monitoring:

```python
@runtime_checkable
class WatchCapability(Protocol):

    def watch(self, root: str) -> AsyncIterator[tuple[WatchEventType, SourceItem]]:
        """Watch for changes under a root path."""
        ...
```

Event types: `CREATED`, `MODIFIED`, `DELETED`, `MOVED`

Detection: `isinstance(connector, WatchCapability)`

### ChangeDetectionCapability

Efficient incremental processing:

```python
@runtime_checkable
class ChangeDetectionCapability(Protocol):

    async def has_changed(self, item: SourceItem) -> bool:
        """Check if item has changed since last processing."""
        ...

    async def mark_processed(self, item: SourceItem) -> None:
        """Mark item as processed."""
        ...
```

Detection: `has_change_detection(connector)`

### AuthCapability

For protected resources:

```python
@runtime_checkable
class AuthCapability(Protocol):

    async def authenticate(self) -> None:
        """Perform initial authentication."""
        ...

    async def refresh_auth(self) -> None:
        """Refresh credentials."""
        ...

    @property
    def is_authenticated(self) -> bool:
        """Check auth status."""
        ...
```

Detection: `has_auth_capability(connector)`

---

## fsspec Integration

The `FsspecConnector` base class provides fsspec integration:

```python
from agentic_inquiry.connectors.base import FsspecConnector

class S3Connector(FsspecConnector):
    def __init__(self, bucket: str, prefix: str = "", **storage_options):
        super().__init__(
            protocol="s3",
            storage_options=storage_options,  # AWS credentials, etc.
            ignore_patterns=["*.tmp", ".git/**"],
        )
        self._bucket = bucket
        self._prefix = prefix
```

fsspec handles:
- Protocol-specific file operations
- Credential management via `storage_options`
- Async I/O patterns

### storage_options

Pass backend-specific options:

```python
# S3
storage_options = {
    "key": "AKIAIOSFODNN7EXAMPLE",
    "secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "client_kwargs": {"region_name": "us-east-1"},
}

# GCS
storage_options = {
    "token": "/path/to/service-account.json",
}

# GitHub (via HTTP)
storage_options = {
    "headers": {"Authorization": f"token {github_token}"},
}
```

---

## Async I/O Requirements

fsspec is largely synchronous. Use `asyncio.to_thread()` for blocking operations:

```python
import asyncio

async def open(self, item: SourceItem) -> SourceContent:
    # Run blocking fsspec operation in thread pool
    data = await asyncio.to_thread(self._fs.cat_file, item.uri)

    return SourceContent(
        data=data,
        encoding=self._detect_encoding(item.uri),
        metadata={"uri": item.uri},
    )
```

**Never block the event loop** with synchronous file operations.

---

## Path Materialization

Parsers are currently path-based. Remote content must be materialized to local paths:

```python
from agentic_inquiry.connectors.cache import ContentMaterializer

class RemoteConnector:
    def __init__(self, cache_dir: str):
        self._materializer = ContentMaterializer(cache_dir)

    async def materialize(self, item: SourceItem) -> Path:
        """Materialize remote content to local path for parsing."""
        content = await self.open(item)
        return await self._materializer.materialize(item, content)
```

The `ContentMaterializer`:
- Uses hash-based cache paths to avoid collisions
- Performs atomic writes (temp file + rename)
- Is async-safe with double-checked locking

---

## Path Security

For filesystem connectors, prevent directory traversal attacks:

```python
from pathlib import Path

def _validate_path(self, path: str) -> Path:
    """Validate path stays within root directory."""
    resolved = Path(path).resolve()

    # Check if path is under root
    try:
        resolved.relative_to(self._root)
    except ValueError:
        raise ValueError(f"Path escapes root directory: {path}")

    return resolved
```

Apply validation to:
- All paths from `list()`
- All paths before `open()`
- Any user-provided paths

---

## Example: Custom SaaS Connector

Here's a skeleton for a Notion connector:

```python
"""Notion connector for indexing Notion workspaces."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from agentic_inquiry.connectors.protocols import AuthCapability, ConnectorProtocol
from agentic_inquiry.connectors.types import SourceContent, SourceItem


class NotionConnector(ConnectorProtocol, AuthCapability):
    """Connector for Notion workspaces.

    Requires a Notion integration token with appropriate permissions.

    Example:
        >>> connector = NotionConnector(integration_token="secret_xxx")
        >>> await connector.authenticate()
        >>> async for item in connector.list("workspace_id"):
        ...     content = await connector.open(item)
        ...     process(content.text)
    """

    NOTION_API_BASE = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(self, integration_token: str) -> None:
        self._token = integration_token
        self._client: Optional[httpx.AsyncClient] = None
        self._authenticated = False

    # =========================================================================
    # AuthCapability
    # =========================================================================

    async def authenticate(self) -> None:
        """Initialize HTTP client and verify token."""
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._token}",
                "Notion-Version": self.NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

        # Verify token by fetching user info
        response = await self._client.get(f"{self.NOTION_API_BASE}/users/me")
        if response.status_code != 200:
            raise PermissionError("Notion authentication failed")

        self._authenticated = True

    async def refresh_auth(self) -> None:
        """Re-authenticate (Notion tokens don't expire, so just verify)."""
        await self.authenticate()

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    # =========================================================================
    # ConnectorProtocol
    # =========================================================================

    async def list(self, root: str) -> AsyncIterator[SourceItem]:
        """Enumerate pages in a Notion database or workspace.

        Args:
            root: Database ID or workspace ID to enumerate.

        Yields:
            SourceItem for each page.
        """
        if not self._authenticated:
            raise RuntimeError("Call authenticate() before list()")

        # Query database for pages
        cursor = None
        while True:
            payload: Dict[str, Any] = {}
            if cursor:
                payload["start_cursor"] = cursor

            response = await self._client.post(
                f"{self.NOTION_API_BASE}/databases/{root}/query",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            for page in data.get("results", []):
                yield SourceItem(
                    uri=f"notion://{page['id']}",
                    content_hash=page.get("last_edited_time"),  # Use as hash
                    modified_at=datetime.fromisoformat(
                        page["last_edited_time"].replace("Z", "+00:00")
                    ),
                    content_type="text/markdown",
                    metadata={
                        "title": self._extract_title(page),
                        "database_id": root,
                    },
                )

            # Pagination
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    async def open(self, item: SourceItem) -> SourceContent:
        """Retrieve page content as Markdown.

        Args:
            item: SourceItem from list().

        Returns:
            SourceContent with Markdown text.
        """
        if not self._authenticated:
            raise RuntimeError("Call authenticate() before open()")

        # Extract page ID from URI
        page_id = item.uri.replace("notion://", "")

        # Fetch page blocks
        blocks = await self._fetch_all_blocks(page_id)

        # Convert to Markdown
        markdown = self._blocks_to_markdown(blocks)

        return SourceContent(
            data=markdown.encode("utf-8"),
            encoding="utf-8",
            metadata={
                "uri": item.uri,
                "title": item.metadata.get("title", ""),
            },
        )

    # =========================================================================
    # Private Helpers
    # =========================================================================

    async def _fetch_all_blocks(self, page_id: str) -> list:
        """Fetch all blocks from a page (handling pagination)."""
        blocks = []
        cursor = None

        while True:
            url = f"{self.NOTION_API_BASE}/blocks/{page_id}/children"
            if cursor:
                url += f"?start_cursor={cursor}"

            response = await self._client.get(url)
            response.raise_for_status()
            data = response.json()

            blocks.extend(data.get("results", []))

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return blocks

    def _blocks_to_markdown(self, blocks: list) -> str:
        """Convert Notion blocks to Markdown."""
        lines = []
        for block in blocks:
            block_type = block.get("type")
            if block_type == "paragraph":
                text = self._rich_text_to_plain(block["paragraph"]["rich_text"])
                lines.append(text)
            elif block_type == "heading_1":
                text = self._rich_text_to_plain(block["heading_1"]["rich_text"])
                lines.append(f"# {text}")
            elif block_type == "heading_2":
                text = self._rich_text_to_plain(block["heading_2"]["rich_text"])
                lines.append(f"## {text}")
            elif block_type == "code":
                code = self._rich_text_to_plain(block["code"]["rich_text"])
                lang = block["code"].get("language", "")
                lines.append(f"```{lang}\n{code}\n```")
            # ... handle other block types

        return "\n\n".join(lines)

    def _rich_text_to_plain(self, rich_text: list) -> str:
        """Extract plain text from Notion rich text array."""
        return "".join(item.get("plain_text", "") for item in rich_text)

    def _extract_title(self, page: dict) -> str:
        """Extract page title from properties."""
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                return self._rich_text_to_plain(prop.get("title", []))
        return "Untitled"
```

---

## Implementation Checklist

### Required

- [ ] Implement `ConnectorProtocol.list()` as async generator
- [ ] Implement `ConnectorProtocol.open()` as async method
- [ ] Provide stable URIs in `SourceItem`
- [ ] Compute `content_hash` for change detection
- [ ] Set `encoding` correctly (None for binary)
- [ ] Include `uri` in `SourceContent.metadata`
- [ ] Ensure metadata is JSON-serializable

### Optional Capabilities

- [ ] `WatchCapability` if real-time monitoring is supported
- [ ] `ChangeDetectionCapability` if tracking processed items
- [ ] `AuthCapability` if authentication is required

### Configuration

- [ ] Add connector config to `config/default.yaml`
- [ ] Add schema validation to `config/config.schema.json`
- [ ] Register in connector registry

### Tests

- [ ] Test `list()` returns valid SourceItems
- [ ] Test `open()` returns valid SourceContent
- [ ] Test path validation (for filesystem connectors)
- [ ] Test change detection if supported
- [ ] Test authentication lifecycle if supported

---

## See Also

- `agentic_inquiry/connectors/filesystem.py` - Production FileSystemConnector implementation
- `agentic_inquiry/connectors/s3.py` - S3 connector example
- `agentic_inquiry/connectors/protocols.py` - Protocol definitions and capabilities
- `agentic_inquiry/connectors/base.py` - FsspecConnector base class
- `docs/design/ownership-and-extension-points.md` - Ownership boundaries
- `tests/connectors/` - Test patterns
