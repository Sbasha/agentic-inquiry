"""Onboard documentation lifecycle management.

Provides tracking, storage, and freshness detection for onboard documentation.
"""

from agentic_inquiry.onboard.models import OnboardRun
from agentic_inquiry.onboard.metadata_service import OnboardMetadataService
from agentic_inquiry.onboard.staleness import StalenessResult, check_onboard_staleness
from agentic_inquiry.onboard.artifact_storage import (
    OnboardArtifactStorage,
    LocalOnboardArtifactStorage,
    create_onboard_artifact_storage,
)
from agentic_inquiry.onboard.gate import OnboardGateError, check_onboard_gate

__all__ = [
    "OnboardRun",
    "OnboardMetadataService",
    "StalenessResult",
    "check_onboard_staleness",
    "OnboardArtifactStorage",
    "LocalOnboardArtifactStorage",
    "create_onboard_artifact_storage",
    "OnboardGateError",
    "check_onboard_gate",
]
