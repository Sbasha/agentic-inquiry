"""CLI commands for lineage tracing and impact analysis.

Usage:
    agv lineage trace <entity> [--direction downstream|upstream] [--depth N]
    agv lineage impact <entity> [--depth N]
    agv lineage gaps <entity>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import TYPE_CHECKING, Optional

from agent_vault.cli.env_resolver import load_config_for_environment
from agent_vault.models.lineage import ArchitecturalLayer, LineagePath
from agent_vault.search.lineage_service import LineageService

if TYPE_CHECKING:
    from agent_vault.storage.facade import StorageFacade

logger = logging.getLogger(__name__)


def format_path(path: LineagePath, verbose: bool = False) -> str:
    """Format a lineage path for display.

    Args:
        path: LineagePath to format
        verbose: Include file paths and line numbers

    Returns:
        Formatted string representation
    """
    lines = []
    lines.append(f"Path: {path.source_id} → {path.sink_id}")
    lines.append(f"  Confidence: {path.min_confidence.value}")
    lines.append(f"  Complete: {'Yes' if path.is_complete else 'No'}")

    if path.gaps:
        lines.append(f"  Gaps: {', '.join(path.gaps)}")

    lines.append("  Steps:")
    for i, step in enumerate(path.steps):
        arrow = "→" if i < len(path.steps) - 1 else "⬤"
        layer_badge = f"[{step.layer.value}]"

        if verbose and step.file_path:
            location = f" ({step.file_path}:{step.line_number or '?'})"
        else:
            location = ""

        rel_info = f" --{step.relationship_type}-->" if step.relationship_type else ""
        lines.append(f"    {arrow} {step.entity_name} {layer_badge}{rel_info}{location}")

    return "\n".join(lines)


async def trace_command(args: argparse.Namespace) -> int:
    """Execute lineage trace command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    from agent_vault.storage.facade import StorageFacade

    config = load_config_for_environment()

    # Determine project_id from args or config
    project_id = args.project or config.storage.default_project_id
    if not project_id:
        print("Error: No project specified. Use --project or set in config.", file=sys.stderr)
        return 1

    print(f"Tracing lineage for '{args.entity}' (project: {project_id})...")

    try:
        storage = await StorageFacade.from_config(config, project_id)
        lineage = LineageService(storage, config)

        # Resolve entity by name if not an ID
        entity_id = await resolve_entity(storage, args.entity, project_id)
        if not entity_id:
            print(f"Error: Entity '{args.entity}' not found.", file=sys.stderr)
            return 1

        # Parse target layers
        target_layers = None
        if args.target_layer:
            try:
                target_layers = [ArchitecturalLayer(args.target_layer)]
            except ValueError:
                print(f"Error: Invalid layer '{args.target_layer}'", file=sys.stderr)
                print(f"Valid layers: {[l.value for l in ArchitecturalLayer]}", file=sys.stderr)
                return 1

        # Execute trace
        if args.direction == "downstream":
            paths = await lineage.trace_downstream(
                source_id=entity_id,
                max_depth=args.depth,
                target_layers=target_layers,
            )
        else:
            paths = await lineage.trace_upstream(
                sink_id=entity_id,
                max_depth=args.depth,
                target_layers=target_layers,
            )

        # Output results
        if args.json:
            output = {
                "entity": args.entity,
                "entity_id": entity_id,
                "direction": args.direction,
                "paths_found": len(paths),
                "paths": [
                    {
                        "path_id": p.path_id,
                        "source_id": p.source_id,
                        "sink_id": p.sink_id,
                        "depth": p.depth,
                        "is_complete": p.is_complete,
                        "min_confidence": p.min_confidence.value,
                        "gaps": p.gaps,
                        "steps": [
                            {
                                "entity_id": s.entity_id,
                                "entity_name": s.entity_name,
                                "entity_type": s.entity_type,
                                "layer": s.layer.value,
                                "file_path": s.file_path,
                                "line_number": s.line_number,
                                "relationship_type": s.relationship_type,
                                "confidence": s.confidence.value,
                            }
                            for s in p.steps
                        ],
                    }
                    for p in paths
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            if not paths:
                print(f"No {args.direction} paths found from '{args.entity}'")
            else:
                print(f"\nFound {len(paths)} path(s):\n")
                for i, path in enumerate(paths, 1):
                    print(f"--- Path {i} ---")
                    print(format_path(path, verbose=args.verbose))
                    print()

        return 0

    except Exception as e:
        logger.exception("Trace failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def impact_command(args: argparse.Namespace) -> int:
    """Execute impact analysis command.

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

    print(f"Analyzing impact for '{args.entity}' (project: {project_id})...")

    try:
        storage = await StorageFacade.from_config(config, project_id)
        lineage = LineageService(storage, config)

        entity_id = await resolve_entity(storage, args.entity, project_id)
        if not entity_id:
            print(f"Error: Entity '{args.entity}' not found.", file=sys.stderr)
            return 1

        impact = await lineage.analyze_impact(
            entity_id=entity_id,
            max_depth=args.depth,
        )

        if args.json:
            output = {
                "entity": args.entity,
                "entity_id": impact.entity_id,
                "entity_name": impact.entity_name,
                "risk_level": impact.risk_level,
                "is_pii": impact.is_pii,
                "affected_count": impact.affected_count,
                "affected_entities": impact.affected_entities[:50],  # Limit output
                "affected_files": impact.affected_files[:50],
            }
            print(json.dumps(output, indent=2))
        else:
            # Risk level coloring
            risk_colors = {
                "LOW": "\033[32m",      # Green
                "MEDIUM": "\033[33m",   # Yellow
                "HIGH": "\033[91m",     # Light red
                "CRITICAL": "\033[31m", # Red
            }
            reset = "\033[0m"
            color = risk_colors.get(impact.risk_level, "")

            print(f"\n{'='*50}")
            print(f"Impact Analysis: {impact.entity_name}")
            print(f"{'='*50}")
            print(f"Risk Level: {color}{impact.risk_level}{reset}")
            print(f"PII Field: {'Yes ⚠️' if impact.is_pii else 'No'}")
            print(f"Affected Entities: {impact.affected_count}")
            print(f"Affected Files: {len(impact.affected_files)}")

            if impact.affected_files:
                print(f"\nFiles that may need changes:")
                for f in impact.affected_files[:10]:
                    print(f"  • {f}")
                if len(impact.affected_files) > 10:
                    print(f"  ... and {len(impact.affected_files) - 10} more")

        return 0

    except Exception as e:
        logger.exception("Impact analysis failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def gaps_command(args: argparse.Namespace) -> int:
    """Execute gap detection command.

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

    print(f"Finding gaps for '{args.entity}' (project: {project_id})...")

    try:
        storage = await StorageFacade.from_config(config, project_id)
        lineage = LineageService(storage, config)

        entity_id = await resolve_entity(storage, args.entity, project_id)
        if not entity_id:
            print(f"Error: Entity '{args.entity}' not found.", file=sys.stderr)
            return 1

        gaps = await lineage.find_gaps(entity_id=entity_id)

        if args.json:
            print(json.dumps({"entity": args.entity, "gaps": gaps}, indent=2))
        else:
            if not gaps:
                print(f"✓ No gaps found for '{args.entity}'")
            else:
                print(f"\n⚠ Found {len(gaps)} gap(s):")
                for gap in gaps:
                    print(f"  • {gap}")

        return 0

    except Exception as e:
        logger.exception("Gap detection failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def resolve_entity(
    storage: "StorageFacade",
    entity_ref: str,
    project_id: Optional[str],
) -> Optional[str]:
    """Resolve entity name or ID to entity ID.

    Args:
        storage: Storage facade
        entity_ref: Entity name or ID
        project_id: Project ID

    Returns:
        Entity ID or None if not found
    """
    # First try as exact ID
    entities = await storage.query_raw(
        table_name="graph_entities",
        filters={"id": entity_ref},
        limit=1,
        project_id=project_id,
    )
    if entities:
        return entities[0]["id"]

    # Try as name
    entities = await storage.query_raw(
        table_name="graph_entities",
        filters={"name": entity_ref},
        limit=1,
        project_id=project_id,
    )
    if entities:
        return entities[0]["id"]

    return None


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for lineage commands."""
    parser = argparse.ArgumentParser(
        prog="agv lineage",
        description="Lineage tracing and impact analysis commands",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Lineage commands")

    # Trace command
    trace_parser = subparsers.add_parser(
        "trace",
        help="Trace data lineage paths",
        description="Trace lineage from UI to database (downstream) or reverse (upstream)",
    )
    trace_parser.add_argument("entity", help="Entity name or ID to trace from")
    trace_parser.add_argument(
        "--direction", "-d",
        choices=["downstream", "upstream"],
        default="downstream",
        help="Trace direction (default: downstream)",
    )
    trace_parser.add_argument(
        "--depth",
        type=int,
        default=10,
        help="Maximum traversal depth (default: 10)",
    )
    trace_parser.add_argument(
        "--target-layer", "-t",
        help="Stop at specific layer (ui, controller, service, repository, entity, database)",
    )
    trace_parser.add_argument(
        "--project", "-p",
        help="Project ID (uses config default if not specified)",
    )
    trace_parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    trace_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Include file paths and line numbers",
    )
    trace_parser.set_defaults(func=trace_command)

    # Impact command
    impact_parser = subparsers.add_parser(
        "impact",
        help="Analyze change impact",
        description="Analyze what would be affected by changing an entity",
    )
    impact_parser.add_argument("entity", help="Entity name or ID to analyze")
    impact_parser.add_argument(
        "--depth",
        type=int,
        default=5,
        help="Maximum traversal depth (default: 5)",
    )
    impact_parser.add_argument(
        "--project", "-p",
        help="Project ID",
    )
    impact_parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    impact_parser.set_defaults(func=impact_command)

    # Gaps command
    gaps_parser = subparsers.add_parser(
        "gaps",
        help="Find lineage gaps",
        description="Identify missing connections in lineage for an entity",
    )
    gaps_parser.add_argument("entity", help="Entity name or ID to check")
    gaps_parser.add_argument(
        "--project", "-p",
        help="Project ID",
    )
    gaps_parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    gaps_parser.set_defaults(func=gaps_command)

    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for lineage CLI.

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

    # Run async command
    return asyncio.run(parsed.func(parsed))


if __name__ == "__main__":
    sys.exit(main())
