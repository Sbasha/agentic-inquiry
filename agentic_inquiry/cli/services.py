"""CLI commands for service map detection and visualization.

Usage:
    ai services detect [--path PATH] [--json]
    ai services show [--path PATH] [--format ascii|json|dot]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from agentic_inquiry.discovery import ServiceMapDetector, ServiceMap

logger = logging.getLogger(__name__)


def format_ascii_map(service_map: ServiceMap) -> str:
    """Format service map as ASCII art.

    Args:
        service_map: ServiceMap to format

    Returns:
        ASCII representation
    """
    lines = []
    lines.append("=" * 60)
    lines.append("SERVICE ARCHITECTURE")
    lines.append("=" * 60)
    lines.append(f"Workspace: {service_map.workspace_path}")
    lines.append(f"Detection sources: {', '.join(service_map.detection_sources) or 'none'}")
    lines.append("")

    # Group services by type
    services_by_type: dict[str, list] = {}
    for svc in service_map.services:
        services_by_type.setdefault(svc.service_type, []).append(svc)

    # Type order for display
    type_order = ["gateway", "application", "database", "cache", "queue", "external", "unknown"]

    for svc_type in type_order:
        services = services_by_type.get(svc_type, [])
        if not services:
            continue

        lines.append(f"┌─ {svc_type.upper()} ─" + "─" * (50 - len(svc_type)))
        for svc in services:
            conf_badge = {"high": "●", "medium": "◐", "low": "○"}.get(svc.confidence, "?")
            tech_info = f" ({svc.technology})" if svc.technology else ""
            ports_info = f" [{','.join(map(str, svc.ports))}]" if svc.ports else ""
            lines.append(f"│ {conf_badge} {svc.name}{tech_info}{ports_info}")
            lines.append(f"│   source: {svc.source}")
            if svc.file_path:
                lines.append(f"│   file: {svc.file_path}")
        lines.append("└" + "─" * 58)
        lines.append("")

    # Connections
    if service_map.connections:
        lines.append("┌─ CONNECTIONS ─" + "─" * 43)
        for conn in service_map.connections:
            port_info = f":{conn.port}" if conn.port else ""
            lines.append(f"│ {conn.source_id} ──[{conn.protocol}]{port_info}──> {conn.target_id}")
        lines.append("└" + "─" * 58)
        lines.append("")

    # Gaps
    if service_map.gaps:
        lines.append("⚠ GAPS DETECTED:")
        for gap in service_map.gaps:
            lines.append(f"  • {gap}")
        lines.append("")

    # Legend
    lines.append("Legend: ● high confidence  ◐ medium  ○ low")

    return "\n".join(lines)


def format_dot(service_map: ServiceMap) -> str:
    """Format service map as DOT (Graphviz) format.

    Args:
        service_map: ServiceMap to format

    Returns:
        DOT format string
    """
    lines = ["digraph ServiceMap {"]
    lines.append("  rankdir=TB;")
    lines.append("  node [shape=box, style=filled];")
    lines.append("")

    # Color mapping for service types
    colors = {
        "gateway": "#FFD700",
        "application": "#87CEEB",
        "database": "#90EE90",
        "cache": "#FFB6C1",
        "queue": "#DDA0DD",
        "external": "#D3D3D3",
        "unknown": "#FFFFFF",
    }

    # Add nodes
    for svc in service_map.services:
        color = colors.get(svc.service_type, "#FFFFFF")
        label = svc.name
        if svc.technology:
            label += f"\\n({svc.technology})"
        lines.append(f'  "{svc.id}" [label="{label}", fillcolor="{color}"];')

    lines.append("")

    # Add edges
    for conn in service_map.connections:
        label = conn.protocol
        if conn.port:
            label += f":{conn.port}"
        lines.append(f'  "{conn.source_id}" -> "{conn.target_id}" [label="{label}"];')

    lines.append("}")
    return "\n".join(lines)


async def detect_command(args: argparse.Namespace) -> int:
    """Execute service detection command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    workspace = Path(args.path).resolve()
    if not workspace.exists():
        print(f"Error: Path does not exist: {workspace}", file=sys.stderr)
        return 1

    print(f"Detecting services in {workspace}...")

    try:
        detector = ServiceMapDetector(workspace)
        service_map = await detector.detect()

        if args.json:
            print(json.dumps(service_map.to_dict(), indent=2))
        else:
            print(format_ascii_map(service_map))
            print(f"\nFound {len(service_map.services)} services, {len(service_map.connections)} connections")

        return 0

    except Exception as e:
        logger.exception("Detection failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def show_command(args: argparse.Namespace) -> int:
    """Execute service map display command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success)
    """
    workspace = Path(args.path).resolve()
    if not workspace.exists():
        print(f"Error: Path does not exist: {workspace}", file=sys.stderr)
        return 1

    try:
        detector = ServiceMapDetector(workspace)
        service_map = await detector.detect()

        if args.format == "json":
            print(json.dumps(service_map.to_dict(), indent=2))
        elif args.format == "dot":
            print(format_dot(service_map))
        else:  # ascii
            print(format_ascii_map(service_map))

        return 0

    except Exception as e:
        logger.exception("Show failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for services commands."""
    parser = argparse.ArgumentParser(
        prog="ai services",
        description="Service map detection and visualization commands",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Services commands")

    # Detect command
    detect_parser = subparsers.add_parser(
        "detect",
        help="Detect microservice architecture",
        description="Scan workspace and detect services using multiple strategies",
    )
    detect_parser.add_argument(
        "--path", "-p",
        default=".",
        help="Workspace path to scan (default: current directory)",
    )
    detect_parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON",
    )
    detect_parser.set_defaults(func=detect_command)

    # Show command
    show_parser = subparsers.add_parser(
        "show",
        help="Show service architecture",
        description="Display detected service architecture in various formats",
    )
    show_parser.add_argument(
        "--path", "-p",
        default=".",
        help="Workspace path (default: current directory)",
    )
    show_parser.add_argument(
        "--format", "-f",
        choices=["ascii", "json", "dot"],
        default="ascii",
        help="Output format (default: ascii)",
    )
    show_parser.set_defaults(func=show_command)

    return parser


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point for services CLI.

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
