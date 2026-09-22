"""CLI commands for entity understanding.

Usage:
    agv entity <name> [--project PROJECT] [--json]
    agv entity deps <name> [--depth N]
    agv entity refs <name>
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


def format_entity(entity: dict, verbose: bool = False) -> str:
    """Format an entity for display.

    Args:
        entity: Entity dict
        verbose: Include full details

    Returns:
        Formatted string
    """
    lines = []
    lines.append("=" * 60)
    lines.append(f"ENTITY: {entity.get('name', 'unknown')}")
    lines.append("=" * 60)

    lines.append(f"Type:       {entity.get('type', entity.get('entity_type', 'unknown'))}")
    lines.append(f"File:       {entity.get('file_path', 'unknown')}")

    line_num = entity.get('line_number', entity.get('start_line'))
    if line_num:
        lines.append(f"Line:       {line_num}")

    # Signature if available
    signature = entity.get('signature')
    if signature:
        lines.append(f"Signature:  {signature}")

    # Docstring if available
    docstring = entity.get('docstring', entity.get('description'))
    if docstring:
        lines.append("")
        lines.append("Documentation:")
        for line in docstring.split("\n")[:5]:
            lines.append(f"  {line}")
        if docstring.count("\n") > 5:
            lines.append(f"  ... ({docstring.count(chr(10)) - 5} more lines)")

    # Metadata
    metadata = entity.get('metadata', {})
    if metadata and verbose:
        lines.append("")
        lines.append("Metadata:")
        for k, v in metadata.items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


async def understand_command(args: argparse.Namespace) -> int:
    """Execute entity understanding command.

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

        # Find entity by name (exact match first)
        entities = await storage.query_raw(
            table_name="graph_entities",
            filters={"name": args.name},
            limit=10,
            project_id=project_id,
        )

        if not entities:
            print(f"Entity not found: {args.name}", file=sys.stderr)
            return 1

        if args.json:
            output = {
                "query": args.name,
                "count": len(entities),
                "entities": entities,
            }
            print(json.dumps(output, indent=2, default=str))
        else:
            if len(entities) > 1:
                print(f"Found {len(entities)} matching entities:\n")

            for entity in entities:
                print(format_entity(entity, verbose=args.verbose))
                print()

        return 0

    except Exception as e:
        logger.exception("Entity lookup failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def deps_command(args: argparse.Namespace) -> int:
    """Show entity dependencies.

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

        # Find entity
        entities = await storage.query_raw(
            table_name="graph_entities",
            filters={"name": args.name},
            limit=1,
            project_id=project_id,
        )

        if not entities:
            print(f"Entity not found: {args.name}", file=sys.stderr)
            return 1

        entity_id = entities[0]["id"]

        # Get outgoing relationships (dependencies)
        deps = await storage.query_raw(
            table_name="graph_relationships",
            filters={"source_id": entity_id},
            limit=100,
            project_id=project_id,
        )

        if args.json:
            print(json.dumps({"entity": args.name, "dependencies": deps}, indent=2, default=str))
        else:
            print(f"Dependencies of '{args.name}':\n")
            if not deps:
                print("  (no dependencies found)")
            else:
                # Group by relationship type
                by_type: dict[str, list] = {}
                for dep in deps:
                    rel_type = dep.get("relationship_type", "unknown")
                    by_type.setdefault(rel_type, []).append(dep)

                for rel_type, rels in by_type.items():
                    print(f"  {rel_type}:")
                    for rel in rels:
                        target = rel.get("target_id", "?")
                        print(f"    -> {target}")

        return 0

    except Exception as e:
        logger.exception("Deps lookup failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def refs_command(args: argparse.Namespace) -> int:
    """Show entity references (what uses this entity).

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

        # Find entity
        entities = await storage.query_raw(
            table_name="graph_entities",
            filters={"name": args.name},
            limit=1,
            project_id=project_id,
        )

        if not entities:
            print(f"Entity not found: {args.name}", file=sys.stderr)
            return 1

        entity_id = entities[0]["id"]

        # Get incoming relationships (references)
        refs = await storage.query_raw(
            table_name="graph_relationships",
            filters={"target_id": entity_id},
            limit=100,
            project_id=project_id,
        )

        if args.json:
            print(json.dumps({"entity": args.name, "references": refs}, indent=2, default=str))
        else:
            print(f"References to '{args.name}':\n")
            if not refs:
                print("  (no references found)")
            else:
                # Group by relationship type
                by_type: dict[str, list] = {}
                for ref in refs:
                    rel_type = ref.get("relationship_type", "unknown")
                    by_type.setdefault(rel_type, []).append(ref)

                for rel_type, rels in by_type.items():
                    print(f"  {rel_type}:")
                    for rel in rels:
                        source = rel.get("source_id", "?")
                        print(f"    <- {source}")

        return 0

    except Exception as e:
        logger.exception("Refs lookup failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def create_understand_parser() -> argparse.ArgumentParser:
    """Create argument parser for main entity understand command."""
    parser = argparse.ArgumentParser(
        prog="agv entity",
        description="Understand code entities (functions, classes, etc.)",
    )
    parser.add_argument(
        "name",
        help="Entity name to understand",
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
        help="Show full details",
    )
    return parser


def create_deps_parser() -> argparse.ArgumentParser:
    """Create argument parser for deps subcommand."""
    parser = argparse.ArgumentParser(
        prog="agv entity deps",
        description="Show entity dependencies",
    )
    parser.add_argument(
        "name",
        help="Entity name",
    )
    parser.add_argument(
        "--depth", "-d",
        type=int,
        default=1,
        help="Traversal depth (default: 1)",
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
    return parser


def create_refs_parser() -> argparse.ArgumentParser:
    """Create argument parser for refs subcommand."""
    parser = argparse.ArgumentParser(
        prog="agv entity refs",
        description="Show entity references",
    )
    parser.add_argument(
        "name",
        help="Entity name",
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
    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for entity CLI.

    Args:
        args: Command line arguments (uses sys.argv if None)

    Returns:
        Exit code
    """
    if args is None:
        args = sys.argv[1:] if len(sys.argv) > 1 else []

    # Check for subcommands
    if args and args[0] == "deps":
        parser = create_deps_parser()
        parsed = parser.parse_args(args[1:])
        return asyncio.run(deps_command(parsed))
    elif args and args[0] == "refs":
        parser = create_refs_parser()
        parsed = parser.parse_args(args[1:])
        return asyncio.run(refs_command(parsed))

    # Default: understand command
    if not args:
        print("Usage: agv entity <name> [--project PROJECT] [--json] [--verbose]")
        print("       agv entity deps <name> [--project PROJECT] [--json]")
        print("       agv entity refs <name> [--project PROJECT] [--json]")
        return 1

    parser = create_understand_parser()
    parsed = parser.parse_args(args)
    return asyncio.run(understand_command(parsed))


if __name__ == "__main__":
    sys.exit(main())
