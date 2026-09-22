"""CLI commands for semantic search.

Usage:
    agv search <query> [--limit N] [--type code|doc|all] [--json]
    agv search similar <entity> [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Optional

from agent_vault.cli.env_resolver import load_config_for_environment

logger = logging.getLogger(__name__)


def format_result(result: dict, index: int, verbose: bool = False) -> str:
    """Format a search result for display.

    Args:
        result: Search result dict
        index: Result index (1-based)
        verbose: Include full content

    Returns:
        Formatted string
    """
    lines = []

    # Header with score
    score = result.get("score", result.get("similarity", 0))
    file_path = result.get("file_path", result.get("source", "unknown"))
    entity_type = result.get("entity_type", result.get("type", "chunk"))

    raw_vec = result.get("_raw_vector_score")
    confidence = ""
    if raw_vec is not None:
        confidence = f" | vec:{raw_vec:.2f}"
    lines.append(f"{index}. [{score:.3f}{confidence}] {file_path}")

    # Entity name if available
    name = result.get("name", result.get("entity_name"))
    if name:
        lines.append(f"   {entity_type}: {name}")

    # Line number if available
    line_num = result.get("line_number", result.get("start_line"))
    if line_num:
        lines.append(f"   Line: {line_num}")

    # Content preview
    content = result.get("content", result.get("text", ""))
    if content:
        if verbose:
            lines.append(f"   ---")
            for line in content.split("\n")[:10]:
                lines.append(f"   {line}")
            if content.count("\n") > 10:
                lines.append(f"   ... ({content.count(chr(10)) - 10} more lines)")
        else:
            # First line only
            first_line = content.split("\n")[0][:80]
            if len(first_line) == 80:
                first_line += "..."
            lines.append(f"   {first_line}")

    return "\n".join(lines)


async def search_command(args: argparse.Namespace) -> int:
    """Execute search command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    from agent_vault.storage.facade import StorageFacade
    from agent_vault.search.service import SearchService

    config = load_config_for_environment()

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print("Error: No project specified. Use --project or set in config.", file=sys.stderr)
        return 1

    query = " ".join(args.query) if isinstance(args.query, list) else args.query
    if not query:
        print("Error: Query is required", file=sys.stderr)
        return 1

    try:
        # Configure embedder based on storage backend capabilities
        from agent_vault.embeddings.factory import (
            configure_embedder_for_backend,
            resolve_backend_type,
        )
        from agent_vault.embeddings.service import EmbeddingService
        from agent_vault.storage.capabilities import get_capabilities_for_backend

        configure_embedder_for_backend(config, quiet=True)

        storage = await StorageFacade.from_config(config, project_id)
        search = SearchService(storage, config)
        caps = storage.get_capabilities()

        # Execute search based on type
        content_preference = None
        if args.type == "code":
            content_preference = "code"
        elif args.type == "doc":
            content_preference = "documentation"

        if caps.uses_server_side_embedding:
            # Server-side embedding: pass raw query text
            results = await search.hybrid_search(
                query_vector=query,  # type: ignore[arg-type]
                query_fts=query,
                project_id=project_id,
                limit=args.limit,
                content_preference=content_preference,
            )
        else:
            embedding_service = EmbeddingService(config=config)
            query_vector = await embedding_service.embed_async(query)
            results = await search.hybrid_search(
                query_vector=query_vector,
                query_fts=query,
                project_id=project_id,
                limit=args.limit,
                content_preference=content_preference,
            )

        # Convert SearchResult objects to dicts for formatting
        def to_dict(result):
            """Convert SearchResult or dict to standard format."""
            if isinstance(result, dict):
                return result
            # SearchResult has id, data, score, source, distance
            # data contains the actual document fields
            r = result.data.copy() if hasattr(result, 'data') else {}
            r['score'] = getattr(result, 'score', 0.0)
            r['source'] = getattr(result, 'source', 'unknown')
            return r

        if args.json:
            output = {
                "query": query,
                "project_id": project_id,
                "count": len(results),
                "results": [to_dict(r) for r in results],
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            if not results:
                print(f"No results found for: {query}")
            else:
                print(f"Found {len(results)} result(s) for: {query}\n")
                for i, result in enumerate(results, 1):
                    print(format_result(to_dict(result), i, verbose=args.verbose))
                    print()

        return 0

    except Exception as e:
        logger.exception("Search failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def similar_command(args: argparse.Namespace) -> int:
    """Find similar entities.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    from agent_vault.storage.facade import StorageFacade
    from agent_vault.search.service import SearchService
    from agent_vault.embeddings.registry import embedding_registry

    config = load_config_for_environment()

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print("Error: No project specified. Use --project or set in config.", file=sys.stderr)
        return 1

    try:
        # Configure embedder based on storage backend capabilities
        from agent_vault.embeddings.factory import configure_embedder_for_backend
        from agent_vault.embeddings.service import EmbeddingService

        configure_embedder_for_backend(config, quiet=True)

        storage = await StorageFacade.from_config(config, project_id)
        search = SearchService(storage, config)
        caps = storage.get_capabilities()

        if caps.uses_server_side_embedding:
            results = await search.hybrid_search(
                query_vector=args.entity,  # type: ignore[arg-type]
                query_fts=args.entity,
                project_id=project_id,
                limit=args.limit,
                content_preference="code",
            )
        else:
            embedding_service = EmbeddingService(config=config)
            query_vector = await embedding_service.embed_async(args.entity)
            results = await search.hybrid_search(
                query_vector=query_vector,
                query_fts=args.entity,
                project_id=project_id,
                limit=args.limit,
                content_preference="code",
            )

        # Convert SearchResult objects to dicts
        def to_dict(result):
            if isinstance(result, dict):
                return result
            r = result.data.copy() if hasattr(result, 'data') else {}
            r['score'] = getattr(result, 'score', 0.0)
            r['source'] = getattr(result, 'source', 'unknown')
            return r

        if args.json:
            output = {
                "entity": args.entity,
                "project_id": project_id,
                "count": len(results),
                "results": [to_dict(r) for r in results],
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            if not results:
                print(f"No similar content found for: {args.entity}")
            else:
                print(f"Found {len(results)} results similar to: {args.entity}\n")
                for i, result in enumerate(results, 1):
                    print(format_result(to_dict(result), i, verbose=args.verbose))
                    print()

        return 0

    except Exception as e:
        logger.exception("Similar search failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def create_search_parser() -> argparse.ArgumentParser:
    """Create argument parser for main search command."""
    parser = argparse.ArgumentParser(
        prog="agv search",
        description="Semantic search across code and documentation",
    )
    parser.add_argument(
        "query",
        nargs="+",
        help="Search query",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=10,
        help="Maximum results (default: 10)",
    )
    parser.add_argument(
        "--type", "-t",
        choices=["code", "doc", "all"],
        default="all",
        help="Search type (default: all)",
    )
    parser.add_argument(
        "--project", "-p",
        help="Project ID",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full content",
    )
    return parser


def create_similar_parser() -> argparse.ArgumentParser:
    """Create argument parser for similar subcommand."""
    similar_parser = argparse.ArgumentParser(
        prog="agv search similar",
        description="Find similar code/entities",
    )
    similar_parser.add_argument(
        "--limit", "-l",
        type=int,
        default=10,
        help="Maximum results (default: 10)",
    )
    similar_parser.add_argument(
        "--project", "-p",
        help="Project ID",
    )
    similar_parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    similar_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full content",
    )
    return similar_parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for search CLI.

    Args:
        args: Command line arguments (uses sys.argv if None)

    Returns:
        Exit code
    """
    if args is None:
        args = sys.argv[1:] if len(sys.argv) > 1 else []

    # Check for similar subcommand
    if args and args[0] == "similar":
        parser = create_similar_parser()
        parsed = parser.parse_args(args[1:])
        return asyncio.run(similar_command(parsed))

    # Default: search command
    parser = create_search_parser()
    parsed = parser.parse_args(args)
    return asyncio.run(search_command(parsed))


if __name__ == "__main__":
    sys.exit(main())
