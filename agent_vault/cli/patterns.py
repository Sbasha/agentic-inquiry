"""CLI commands for pattern discovery.

Usage:
    agv patterns [--project PROJECT] [--json]
    agv patterns discover [--min-cluster N]
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


def format_pattern(pattern: dict, index: int) -> str:
    """Format a pattern for display.

    Args:
        pattern: Pattern dict
        index: Result index (1-based)

    Returns:
        Formatted string
    """
    lines = []

    name = pattern.get("name", pattern.get("pattern_name", f"Pattern {index}"))
    pattern_type = pattern.get("type", pattern.get("pattern_type", "unknown"))
    confidence = pattern.get("confidence", pattern.get("score", 0))
    count = pattern.get("count", pattern.get("member_count", 0))

    lines.append(f"{index}. {name}")
    lines.append(f"   Type: {pattern_type} | Confidence: {confidence:.2f} | Instances: {count}")

    # Description
    desc = pattern.get("description", "")
    if desc:
        lines.append(f"   {desc}")

    # Examples
    examples = pattern.get("examples", pattern.get("members", []))
    if examples:
        lines.append("   Examples:")
        for ex in examples[:3]:
            if isinstance(ex, dict):
                lines.append(f"     - {ex.get('name', ex.get('file_path', str(ex)))}")
            else:
                lines.append(f"     - {ex}")
        if len(examples) > 3:
            lines.append(f"     ... and {len(examples) - 3} more")

    return "\n".join(lines)


async def list_command(args: argparse.Namespace) -> int:
    """List discovered patterns.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    from agent_vault.storage.facade import StorageFacade

    config = load_config_for_environment()

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print("Error: No project specified. Use --project or set in config.", file=sys.stderr)
        return 1

    try:
        storage = await StorageFacade.from_config(config, project_id)

        # Try to get patterns from storage
        patterns = await storage.query_raw(
            table_name="patterns",
            filters={},
            limit=args.limit,
            project_id=project_id,
        )

        if args.json:
            print(json.dumps({"count": len(patterns), "patterns": patterns}, indent=2, default=str))
        else:
            if not patterns:
                print("No patterns discovered yet.")
                print("Run 'agv patterns discover' to analyze the codebase.")
            else:
                print(f"Found {len(patterns)} pattern(s):\n")
                for i, pattern in enumerate(patterns, 1):
                    print(format_pattern(pattern, i))
                    print()

        return 0

    except Exception as e:
        # Table might not exist
        if "patterns" in str(e).lower():
            print("No patterns discovered yet.")
            print("Run 'agv patterns discover' to analyze the codebase.")
            return 0
        logger.exception("Pattern list failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def discover_command(args: argparse.Namespace) -> int:
    """Discover patterns in the codebase.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    from agent_vault.storage.facade import StorageFacade

    config = load_config_for_environment()

    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print("Error: No project specified. Use --project or set in config.", file=sys.stderr)
        return 1

    print(f"Discovering patterns in project '{project_id}'...")
    print(f"Minimum cluster size: {args.min_cluster}")
    print("")

    try:
        storage = await StorageFacade.from_config(config, project_id)

        # Get all entities for clustering
        entities = await storage.query_raw(
            table_name="graph_entities",
            filters={},
            limit=10000,
            project_id=project_id,
        )

        if not entities:
            print("No entities found. Index the codebase first with 'agv index'.")
            return 1

        print(f"Analyzing {len(entities)} entities...")

        # Group by type for basic pattern detection
        by_type: dict[str, list] = {}
        for entity in entities:
            entity_type = entity.get("entity_type", "unknown")
            by_type.setdefault(entity_type, []).append(entity)

        # Discover patterns based on naming conventions and structure
        patterns = []

        # Type-based patterns
        for entity_type, members in by_type.items():
            if len(members) >= args.min_cluster:
                patterns.append({
                    "name": f"{entity_type.title()} Pattern",
                    "type": "structural",
                    "confidence": 0.8,
                    "count": len(members),
                    "description": f"Found {len(members)} {entity_type} entities",
                    "examples": [m.get("name", m.get("id")) for m in members[:5]],
                })

        # Naming convention patterns
        prefixes: dict[str, list] = {}
        suffixes: dict[str, list] = {}

        for entity in entities:
            name = entity.get("name", "")
            if not name:
                continue

            # Check common prefixes
            for prefix in ["get_", "set_", "is_", "has_", "create_", "delete_", "update_", "handle_", "on_", "test_"]:
                if name.lower().startswith(prefix):
                    prefixes.setdefault(prefix, []).append(entity)

            # Check common suffixes
            for suffix in ["_handler", "_service", "_controller", "_model", "_view", "_test", "_spec", "_factory"]:
                if name.lower().endswith(suffix):
                    suffixes.setdefault(suffix, []).append(entity)

        for prefix, members in prefixes.items():
            if len(members) >= args.min_cluster:
                patterns.append({
                    "name": f"{prefix}* Convention",
                    "type": "naming",
                    "confidence": 0.7,
                    "count": len(members),
                    "description": f"Functions/methods starting with '{prefix}'",
                    "examples": [m.get("name") for m in members[:5]],
                })

        for suffix, members in suffixes.items():
            if len(members) >= args.min_cluster:
                patterns.append({
                    "name": f"*{suffix} Convention",
                    "type": "naming",
                    "confidence": 0.7,
                    "count": len(members),
                    "description": f"Classes/functions ending with '{suffix}'",
                    "examples": [m.get("name") for m in members[:5]],
                })

        # Note: Patterns are displayed but not persisted to storage
        # (Pattern storage would require additional table schema)
        for pattern in patterns:
            pattern["project_id"] = project_id

        if args.json:
            print(json.dumps({"discovered": len(patterns), "patterns": patterns}, indent=2, default=str))
        else:
            print(f"\nDiscovered {len(patterns)} pattern(s):\n")
            for i, pattern in enumerate(patterns, 1):
                print(format_pattern(pattern, i))
                print()

        return 0

    except Exception as e:
        logger.exception("Pattern discovery failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for patterns commands."""
    parser = argparse.ArgumentParser(
        prog="agv patterns",
        description="Discover and view code patterns",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Pattern commands")

    # Default list
    parser.add_argument(
        "--project", "-p",
        help="Project ID",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=50,
        help="Maximum results (default: 50)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )

    # Discover subcommand
    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover patterns in codebase",
    )
    discover_parser.add_argument(
        "--min-cluster",
        type=int,
        default=3,
        help="Minimum cluster size (default: 3)",
    )
    discover_parser.add_argument(
        "--project", "-p",
        help="Project ID",
    )
    discover_parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    discover_parser.set_defaults(func=discover_command)

    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for patterns CLI.

    Args:
        args: Command line arguments (uses sys.argv if None)

    Returns:
        Exit code
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    if parsed.subcommand == "discover":
        return asyncio.run(parsed.func(parsed))
    else:
        return asyncio.run(list_command(parsed))


if __name__ == "__main__":
    sys.exit(main())
