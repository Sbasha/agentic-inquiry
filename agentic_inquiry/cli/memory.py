"""CLI commands for memory management.

Usage:
    ai memory save <summary> [--tags TAG1,TAG2] [--importance N]
    ai memory recall <query> [--limit N]
    ai memory list [--tier working|episodic|semantic]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any, Optional

from agentic_inquiry.cli.env_resolver import load_config_for_environment

logger = logging.getLogger(__name__)


def format_memory(memory: dict, index: int) -> str:
    """Format a memory for display.

    Args:
        memory: Memory dict
        index: Result index (1-based)

    Returns:
        Formatted string
    """
    lines = []

    tier = memory.get("tier", "unknown")
    importance = memory.get("importance", 0)
    created = memory.get("created_at", memory.get("timestamp", ""))

    # Header
    tier_icons = {"working": "W", "episodic": "E", "semantic": "S"}
    icon = tier_icons.get(tier, "?")
    lines.append(
        f"{index}. [{icon}] {memory.get('summary', memory.get('content', ''))[:60]}"
    )

    # Details
    lines.append(f"   Tier: {tier} | Importance: {importance}")

    if created:
        if isinstance(created, str):
            lines.append(f"   Created: {created[:19]}")
        else:
            lines.append(f"   Created: {created}")

    tags = memory.get("tags", [])
    if tags:
        lines.append(f"   Tags: {', '.join(tags)}")

    # Full content if different from summary
    content = memory.get("content", "")
    summary = memory.get("summary", "")
    if content and content != summary:
        lines.append(f"   Content: {content[:100]}...")

    return "\n".join(lines)


def _tier_name(item: object) -> str:
    tier = getattr(item, "tier", None)
    if tier is None:
        return "unknown"
    return getattr(tier, "value", str(tier))


def _item_project_id(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("project_id") or "")
    context = getattr(item, "context", None)
    return str(getattr(context, "project_id", None) or "")


async def _create_memory_system(config, project_id: str):
    """Create a properly initialized MemorySystem for CLI use.

    Args:
        config: Configuration object
        project_id: Project ID

    Returns:
        Initialized MemorySystem
    """
    from agentic_inquiry.embeddings.registry import embedding_registry
    from agentic_inquiry.embeddings.sentence_transformer import SentenceTransformerEmbedder
    from agentic_inquiry.embeddings.service import EmbeddingService
    from agentic_inquiry.memory.system import MemorySystem
    from agentic_inquiry.storage.facade import StorageFacade

    # Configure embedder if not already configured
    if not embedding_registry._default_configured:
        model_name = getattr(
            config.embeddings.sentence_transformer, "model_name", "all-MiniLM-L6-v2"
        )
        ndims = getattr(config.embeddings, "default_dimensions", 384)
        embedder = SentenceTransformerEmbedder(model_name=model_name)
        embedding_registry.configure_default_embedder(embedder, ndims=ndims)

    embedding_service = EmbeddingService(config=config)
    embedding_dims = getattr(config.embeddings, "default_dimensions", 384)
    episodic_table = config.memory.episodic_memory.table_name
    semantic_table = config.memory.semantic_memory.table_name
    episodic_storage: Any
    semantic_storage: Any

    # Create storage and detect backend type for adapter selection
    storage = await StorageFacade.from_config(config, project_id)
    backend_type = (
        storage.get_backend_type() if hasattr(storage, "get_backend_type") else None
    )

    if backend_type == "lancedb":
        # LanceDB backend - use LanceDBMemoryAdapter for persistence across invocations
        from agentic_inquiry.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter

        db_manager = storage.get_db_manager()
        episodic_storage = LanceDBMemoryAdapter(
            manager=db_manager,
            table_name=episodic_table,
            embedding_dims=embedding_dims,
        )
        semantic_storage = LanceDBMemoryAdapter(
            manager=db_manager,
            table_name=semantic_table,
            embedding_dims=embedding_dims,
        )
        await episodic_storage.initialize()
        await semantic_storage.initialize()
    else:
        # Unknown backend - use in-memory adapter as last resort
        from agentic_inquiry.memory.adapters.inmemory_adapter import InMemoryMemoryAdapter

        episodic_storage = InMemoryMemoryAdapter(embedding_dims=embedding_dims)
        semantic_storage = InMemoryMemoryAdapter(embedding_dims=embedding_dims)
        print(
            "Warning: Using in-memory storage - memories will not persist",
            file=sys.stderr,
        )

    memory_system = MemorySystem(
        config=config,
        embedding_service=embedding_service,
        episodic_storage=episodic_storage,
        semantic_storage=semantic_storage,
    )
    await memory_system.initialize()

    return memory_system, storage


async def save_command(args: argparse.Namespace) -> int:
    """Save a memory.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    config = load_config_for_environment()

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print(
            "Error: No project specified. Use --project or set in config.",
            file=sys.stderr,
        )
        return 1

    summary = " ".join(args.summary) if isinstance(args.summary, list) else args.summary
    if not summary:
        print("Error: Summary is required", file=sys.stderr)
        return 1

    try:
        memory_system, storage = await _create_memory_system(config, project_id)

        from agentic_inquiry.memory.adapters.inmemory_adapter import InMemoryMemoryAdapter
        from agentic_inquiry.memory.models import MemoryTier

        if isinstance(
            getattr(memory_system, "_episodic_storage", None), InMemoryMemoryAdapter
        ):
            return 1

        # Parse tags
        tags = []
        if args.tags:
            tags = [t.strip() for t in args.tags.split(",")]

        # Create context for memory storage
        context = memory_system.create_agent_context(
            agent_id="cli",
            session_id="cli_session",
            conversation_id="cli_conversation",
            project_id=project_id,
        )

        # Save memory (tags can be added to metadata)
        metadata = {"tags": tags} if tags else None
        memory_item = await memory_system.store(
            content=summary,
            context=context,
            importance=args.importance,
            metadata=metadata,
        )

        if memory_item.tier == MemoryTier.WORKING:
            print(
                "This write is session-only and not persisted (importance < 0.7).",
                file=sys.stderr,
            )
            return 1

        if memory_item.tier == MemoryTier.SEMANTIC:
            stored = await memory_system.semantic_memory.get_by_id(memory_item.id)
        else:
            stored = await memory_system.episodic_memory.get_by_id(memory_item.id)
        if stored is None:
            print(
                "Error: Memory was not readable after save.",
                file=sys.stderr,
            )
            return 1

        print(f"Memory saved: {memory_item.id}")
        print(f"  Summary: {summary[:60]}...")
        print(f"  Importance: {args.importance}")
        print(f"  Tier: {_tier_name(memory_item)}")
        if tags:
            print(f"  Tags: {', '.join(tags)}")

        return 0

    except Exception as e:
        logger.exception("Save failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def recall_command(args: argparse.Namespace) -> int:
    """Recall memories by query.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    config = load_config_for_environment()

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print(
            "Error: No project specified. Use --project or set in config.",
            file=sys.stderr,
        )
        return 1

    query = " ".join(args.query) if isinstance(args.query, list) else args.query
    if not query:
        print("Error: Query is required", file=sys.stderr)
        return 1

    try:
        memory_system, storage = await _create_memory_system(config, project_id)

        # Create context for retrieval
        context = memory_system.create_agent_context(
            agent_id="cli",
            session_id="cli_session",
            conversation_id="cli_conversation",
            project_id=project_id,
        )

        # Recall memories using retrieve method
        memories = await memory_system.retrieve(
            query=query,
            context=context,
            limit=args.limit,
        )

        # Convert MemoryItem or RetrievalResult objects to dicts for display.
        # memory_system.retrieve() returns List[RetrievalResult] where the
        # actual MemoryItem is in result.item, not on the result itself.
        def memory_to_dict(m):
            if isinstance(m, dict):
                return m
            # Unwrap RetrievalResult → MemoryItem
            item = getattr(m, "item", m)
            return {
                "id": getattr(item, "id", ""),
                "content": getattr(item, "content", ""),
                "summary": getattr(item, "summary", getattr(item, "content", "")[:100]),
                "importance": getattr(item, "importance", 0.5),
                "tier": getattr(item, "tier", "unknown"),
                "tags": getattr(item, "tags", []),
                "created_at": str(getattr(item, "created_at", "")),
                "project_id": _item_project_id(item),
            }

        memory_dicts = [memory_to_dict(m) for m in memories]
        memory_dicts = [m for m in memory_dicts if _item_project_id(m) == project_id]

        # Filter by tags if specified
        if hasattr(args, "tags") and args.tags:
            filter_tags = {t.strip().lower() for t in args.tags.split(",")}
            memory_dicts = [
                m
                for m in memory_dicts
                if filter_tags
                & {
                    t.lower()
                    for t in (m.get("tags") or m.get("metadata", {}).get("tags", []))
                }
            ]

        if args.json:
            output = {
                "query": query,
                "count": len(memory_dicts),
                "memories": memory_dicts,
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            if not memory_dicts:
                print(f"No memories found for: {query}")
            else:
                print(f"Recalled {len(memory_dicts)} memory(ies) for: {query}\n")
                for i, memory in enumerate(memory_dicts, 1):
                    print(format_memory(memory, i))
                    print()

        return 0

    except Exception as e:
        logger.exception("Recall failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def list_command(args: argparse.Namespace) -> int:
    """List memories.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    config = load_config_for_environment()

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print(
            "Error: No project specified. Use --project or set in config.",
            file=sys.stderr,
        )
        return 1

    try:
        memory_system, storage = await _create_memory_system(config, project_id)

        # Create context
        context = memory_system.create_agent_context(
            agent_id="cli",
            session_id="cli_session",
            conversation_id="cli_conversation",
            project_id=project_id,
        )

        # Helper to convert memory items to dicts
        def memory_to_dict(m, tier: str):
            return {
                "id": getattr(m, "id", ""),
                "content": getattr(m, "content", ""),
                "summary": getattr(m, "summary", getattr(m, "content", "")[:100]),
                "importance": getattr(m, "importance", 0.5),
                "tier": tier,
                "tags": getattr(m, "tags", []),
                "created_at": str(getattr(m, "created_at", "")),
                "project_id": _item_project_id(m),
            }

        # Get memories from different tiers
        all_memories = []

        # Get episodic memories
        if not args.tier or args.tier == "episodic":
            episodic = await memory_system.episodic_memory.get_all_items(context)
            for m in episodic[: args.limit]:
                all_memories.append(memory_to_dict(m, "episodic"))

        # Get semantic memories
        if not args.tier or args.tier == "semantic":
            semantic = await memory_system.semantic_memory.get_all_items(context)
            for m in semantic[: args.limit]:
                all_memories.append(memory_to_dict(m, "semantic"))

        # Get working memories
        if not args.tier or args.tier == "working":
            working = await memory_system.working_memory.get_all_items(context)
            for m in working[: args.limit]:
                all_memories.append(memory_to_dict(m, "working"))

        all_memories = [m for m in all_memories if _item_project_id(m) == project_id]

        if args.json:
            print(
                json.dumps(
                    {"count": len(all_memories), "memories": all_memories},
                    indent=2,
                    default=str,
                )
            )
        else:
            if not all_memories:
                print("No memories found")
            else:
                # Group by tier
                by_tier: dict[str, list] = {}
                for m in all_memories:
                    tier = m.get("tier", "unknown")
                    by_tier.setdefault(tier, []).append(m)

                print(f"Found {len(all_memories)} memory(ies):\n")

                for tier in ["semantic", "episodic", "working"]:
                    tier_memories = by_tier.get(tier, [])
                    if tier_memories:
                        print(f"=== {tier.upper()} ({len(tier_memories)}) ===")
                        for i, m in enumerate(tier_memories[:10], 1):
                            print(format_memory(m, i))
                            print()
                        if len(tier_memories) > 10:
                            print(f"  ... and {len(tier_memories) - 10} more\n")

        return 0

    except Exception as e:
        logger.exception("List failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for memory commands."""
    parser = argparse.ArgumentParser(
        prog="ai memory",
        description="Manage cognitive memories",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Memory commands")

    # Save subcommand
    save_parser = subparsers.add_parser(
        "save",
        help="Save a new memory",
    )
    save_parser.add_argument(
        "summary",
        nargs="+",
        help="Memory summary/content",
    )
    save_parser.add_argument(
        "--tags",
        "-t",
        help="Comma-separated tags",
    )
    save_parser.add_argument(
        "--importance",
        "-i",
        type=float,
        default=0.8,
        help="Importance (0-1, default: 0.8). Values >= 0.7 persist to database; lower values use volatile in-memory storage.",
    )
    save_parser.add_argument(
        "--project",
        "-p",
        help="Project ID",
    )
    save_parser.set_defaults(func=save_command)

    # Recall subcommand
    recall_parser = subparsers.add_parser(
        "recall",
        help="Recall memories by query",
    )
    recall_parser.add_argument(
        "query",
        nargs="+",
        help="Search query",
    )
    recall_parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=10,
        help="Maximum results (default: 10)",
    )
    recall_parser.add_argument(
        "--project",
        "-p",
        help="Project ID",
    )
    recall_parser.add_argument(
        "--tags",
        "-t",
        help="Filter by tags (comma-separated). Only return memories with matching tags.",
    )
    recall_parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output as JSON",
    )
    recall_parser.set_defaults(func=recall_command)

    # List subcommand
    list_parser = subparsers.add_parser(
        "list",
        help="List all memories",
    )
    list_parser.add_argument(
        "--tier",
        choices=["working", "episodic", "semantic"],
        help="Filter by memory tier",
    )
    list_parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=50,
        help="Maximum results (default: 50)",
    )
    list_parser.add_argument(
        "--project",
        "-p",
        help="Project ID",
    )
    list_parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output as JSON",
    )
    list_parser.set_defaults(func=list_command)

    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for memory CLI.

    Args:
        args: Command line arguments (uses sys.argv if None)

    Returns:
        Exit code
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    if not parsed.subcommand:
        parser.print_help()
        return 1

    return asyncio.run(parsed.func(parsed))


if __name__ == "__main__":
    sys.exit(main())
