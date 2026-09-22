"""Onboard gate for indexing operations.

Warns when onboard documentation is missing or stale. Indexing proceeds
either way so first index after setup is not a dead end.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from agentic_inquiry.onboard.staleness import StalenessResult, check_onboard_staleness

if TYPE_CHECKING:
    from agentic_inquiry.config import Config
    from agentic_inquiry.onboard.metadata_service import OnboardMetadataService

logger = logging.getLogger(__name__)


class OnboardGateError(Exception):
    """Legacy exception retained for callers that still catch it."""

    def __init__(
        self,
        message: str,
        staleness: Optional[StalenessResult] = None,
    ) -> None:
        super().__init__(message)
        self.staleness = staleness


async def check_onboard_gate(
    metadata_service: "OnboardMetadataService",
    workspace: Path,
    config: Optional["Config"] = None,
    skip_gate: bool = False,
) -> Optional[StalenessResult]:
    """Check onboard gate before indexing.

    Args:
        metadata_service: Service for onboard metadata.
        workspace: Project workspace path.
        config: Configuration (for thresholds).
        skip_gate: If True, skip the missing-onboard warning.

    Returns:
        StalenessResult if check completed, None if gate disabled.
    """
    # Check if gate is enabled
    gate_enabled = True
    if config is not None:
        onboard_cfg = getattr(config, "onboard", None)
        if onboard_cfg:
            gate_enabled = getattr(onboard_cfg, "gate_enabled", True)

    if not gate_enabled:
        logger.debug("Onboard gate disabled via configuration")
        return None

    staleness = await check_onboard_staleness(metadata_service, workspace, config)

    # No onboard exists - warning only. First index after setup must
    # proceed; /ai:onboard records a run so staleness tracking works later.
    if staleness.reason == "no_onboard":
        if skip_gate:
            logger.debug("Onboard gate skipped: no onboard documentation")
            return staleness
        logger.warning(
            "No onboard documentation exists for this project. "
            "Run /ai:onboard to capture architectural insights. "
            "Indexing continues."
        )
        return staleness

    # Stale onboard - warning only
    if staleness.is_stale:
        logger.warning("Onboard documentation is stale: %s", staleness.message)
    else:
        logger.info("Onboard gate passed: documentation is current")

    return staleness
