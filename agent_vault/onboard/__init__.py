"""Onboard documentation lifecycle management.

Provides tracking, storage, and freshness detection for onboard documentation.
"""

from agent_vault.onboard.models import OnboardRun
from agent_vault.onboard.metadata_service import OnboardMetadataService
from agent_vault.onboard.staleness import StalenessResult, check_onboard_staleness
from agent_vault.onboard.artifact_storage import (
    OnboardArtifactStorage,
    LocalOnboardArtifactStorage,
    create_onboard_artifact_storage,
)
from agent_vault.onboard.gate import OnboardGateError, check_onboard_gate

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
