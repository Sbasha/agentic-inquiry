"""Cloud context detection via IMDS probes."""

from __future__ import annotations

import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("agv.cloud_detect")

_PROBE_TIMEOUT_SECONDS = 0.2

_UNSET = object()
_cloud_context_cache = _UNSET

GCP_METADATA_URL = "http://169.254.169.254/computeMetadata/v1/project/project-id"
GCP_METADATA_HEADERS = {"Metadata-Flavor": "Google"}

AWS_IMDS_TOKEN_URL = "http://169.254.169.254/latest/api/token"
AWS_IMDS_IDENTITY_URL = "http://169.254.169.254/latest/dynamic/instance-identity/document"

AZURE_IMDS_URL = "http://169.254.169.254/metadata/instance?api-version=2021-02-01"
AZURE_IMDS_HEADERS = {"Metadata": "true"}


@dataclass
class CloudContext:
    """Detected cloud execution environment."""
    provider: str
    project_id: str | None = None
    region: str | None = None
    metadata: dict = field(default_factory=dict)


def detect_cloud_context() -> Optional[CloudContext]:
    """Probe cloud metadata endpoints to detect execution environment.

    Probes are run sequentially (GCP -> AWS -> Azure) with short timeouts.
    First successful probe wins. Total worst-case latency: ~600ms (3 x 200ms).
    Result is cached for the lifetime of the process so probes only run once.

    Returns:
        CloudContext if running in a recognized cloud, None otherwise.
    """
    global _cloud_context_cache
    if _cloud_context_cache is not _UNSET:
        return _cloud_context_cache  # type: ignore[return-value]

    result: Optional[CloudContext] = None

    ctx = _probe_gcp()
    if ctx:
        result = ctx
    else:
        ctx = _probe_aws()
        if ctx:
            result = ctx
        else:
            ctx = _probe_azure()
            if ctx:
                result = ctx

    _cloud_context_cache = result
    return result


def _probe_gcp() -> Optional[CloudContext]:
    """Probe GCP metadata server."""
    try:
        req = urllib.request.Request(GCP_METADATA_URL, headers=GCP_METADATA_HEADERS)
        with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT_SECONDS) as resp:
            if resp.status == 200:
                project_id = resp.read().decode("utf-8").strip()
                region = _gcp_get_region()
                logger.info("Detected GCP context: project=%s, region=%s", project_id, region)
                return CloudContext(
                    provider="gcp",
                    project_id=project_id,
                    region=region,
                )
    except (urllib.error.URLError, OSError, TimeoutError):
        pass
    return None


def _gcp_get_region() -> str | None:
    """Get GCP region from zone metadata."""
    try:
        req = urllib.request.Request(
            "http://169.254.169.254/computeMetadata/v1/instance/zone",
            headers=GCP_METADATA_HEADERS,
        )
        with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT_SECONDS) as resp:
            zone = resp.read().decode("utf-8").strip()
            parts = zone.rsplit("/", 1)[-1].rsplit("-", 1)
            return parts[0] if len(parts) > 1 else zone
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def _probe_aws() -> Optional[CloudContext]:
    """Probe AWS IMDSv2."""
    try:
        token_req = urllib.request.Request(
            AWS_IMDS_TOKEN_URL,
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            method="PUT",
        )
        with urllib.request.urlopen(token_req, timeout=_PROBE_TIMEOUT_SECONDS) as resp:
            token = resp.read().decode("utf-8").strip()

        id_req = urllib.request.Request(
            AWS_IMDS_IDENTITY_URL,
            headers={"X-aws-ec2-metadata-token": token},
        )
        with urllib.request.urlopen(id_req, timeout=_PROBE_TIMEOUT_SECONDS) as resp:
            import json
            doc = json.loads(resp.read().decode("utf-8"))
            return CloudContext(
                provider="aws",
                project_id=doc.get("accountId"),
                region=doc.get("region"),
            )
    except (urllib.error.URLError, OSError, TimeoutError):
        pass
    return None


def _probe_azure() -> Optional[CloudContext]:
    """Probe Azure IMDS."""
    try:
        req = urllib.request.Request(AZURE_IMDS_URL, headers=AZURE_IMDS_HEADERS)
        with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT_SECONDS) as resp:
            import json
            doc = json.loads(resp.read().decode("utf-8"))
            compute = doc.get("compute", {})
            return CloudContext(
                provider="azure",
                project_id=compute.get("subscriptionId"),
                region=compute.get("location"),
            )
    except (urllib.error.URLError, OSError, TimeoutError):
        pass
    return None
