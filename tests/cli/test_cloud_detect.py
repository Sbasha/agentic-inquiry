"""Tests for cloud IMDS detection (T41).

Covers:
- GCP probe returns CloudContext on 200
- GCP probe returns None on timeout / error
- GCP probe sends Metadata-Flavor header
- AWS probe returns CloudContext on 200 (IMDSv2 two-step)
- AWS probe returns None on timeout / error
- Azure probe returns CloudContext on 200
- Azure probe returns None on timeout / error
- All probes fail → detect_cloud_context returns None
- detect_cloud_context returns first successful result
- Probe timeout stays within budget
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch


from agent_vault.cli.cloud_detect import (
    CloudContext,
    _probe_aws,
    _probe_azure,
    _probe_gcp,
    detect_cloud_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status: int, body: bytes) -> MagicMock:
    """Return a mock urllib response with .status and .read()."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _make_timeout_side_effect():
    """Side effect that raises URLError simulating a connection timeout."""
    raise urllib.error.URLError("timed out")


# ---------------------------------------------------------------------------
# T41-1: GCP probe — success
# ---------------------------------------------------------------------------

class TestProbeGCP:
    """Tests for _probe_gcp()."""

    def test_returns_cloud_context_on_200(self):
        """A 200 from the GCP IMDS must yield CloudContext(provider='gcp')."""
        gcp_resp = _make_response(200, b"my-gcp-project")
        zone_resp = _make_response(200, b"projects/123/zones/us-central1-a")

        with patch(
            "urllib.request.urlopen",
            side_effect=[gcp_resp, zone_resp],
        ):
            ctx = _probe_gcp()

        assert ctx is not None
        assert ctx.provider == "gcp"

    def test_project_id_extracted(self):
        """Project ID in body is set on CloudContext."""
        gcp_resp = _make_response(200, b"my-project-id")
        zone_resp = _make_response(200, b"projects/123/zones/us-central1-a")

        with patch(
            "urllib.request.urlopen",
            side_effect=[gcp_resp, zone_resp],
        ):
            ctx = _probe_gcp()

        assert ctx is not None
        assert ctx.project_id == "my-project-id"

    def test_region_extracted_from_zone(self):
        """Region is derived by stripping the zone suffix from the zone string."""
        gcp_resp = _make_response(200, b"my-project")
        # Zone format: projects/{num}/zones/{region}-{zone-id}
        zone_resp = _make_response(200, b"projects/123/zones/europe-west1-b")

        with patch(
            "urllib.request.urlopen",
            side_effect=[gcp_resp, zone_resp],
        ):
            ctx = _probe_gcp()

        assert ctx is not None
        assert ctx.region == "europe-west1"

    def test_returns_none_on_url_error(self):
        """URLError (timeout / unreachable) must cause the probe to return None."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("timed out"),
        ):
            ctx = _probe_gcp()

        assert ctx is None

    def test_returns_none_on_os_error(self):
        """OSError must also cause the probe to return None gracefully."""
        with patch(
            "urllib.request.urlopen",
            side_effect=OSError("network down"),
        ):
            ctx = _probe_gcp()

        assert ctx is None

    def test_metadata_flavor_header_sent(self):
        """The GCP IMDS requires Metadata-Flavor: Google — verify the header."""
        captured_requests = []

        def _capturing_urlopen(req, timeout=None):
            captured_requests.append(req)
            raise urllib.error.URLError("stop after capture")

        with patch("urllib.request.urlopen", side_effect=_capturing_urlopen):
            _probe_gcp()

        assert captured_requests, "urlopen should have been called at least once"
        first_req = captured_requests[0]
        assert first_req.get_header("Metadata-flavor") == "Google"


# ---------------------------------------------------------------------------
# T41-2: AWS probe — success
# ---------------------------------------------------------------------------

class TestProbeAWS:
    """Tests for _probe_aws()."""

    def test_returns_cloud_context_on_200(self):
        """A successful IMDSv2 two-step exchange must yield CloudContext(provider='aws')."""
        import json

        token_resp = _make_response(200, b"TOKEN-abc123")
        identity_doc = json.dumps({
            "accountId": "123456789012",
            "region": "us-east-1",
        }).encode()
        id_resp = _make_response(200, identity_doc)

        with patch(
            "urllib.request.urlopen",
            side_effect=[token_resp, id_resp],
        ):
            ctx = _probe_aws()

        assert ctx is not None
        assert ctx.provider == "aws"

    def test_account_id_as_project_id(self):
        """AWS accountId must be stored as project_id."""
        import json

        token_resp = _make_response(200, b"TOKEN-abc123")
        identity_doc = json.dumps({"accountId": "999000111222", "region": "eu-west-1"}).encode()
        id_resp = _make_response(200, identity_doc)

        with patch(
            "urllib.request.urlopen",
            side_effect=[token_resp, id_resp],
        ):
            ctx = _probe_aws()

        assert ctx is not None
        assert ctx.project_id == "999000111222"

    def test_region_extracted(self):
        """AWS region must appear in CloudContext.region."""
        import json

        token_resp = _make_response(200, b"TOKEN-abc123")
        identity_doc = json.dumps({"accountId": "111", "region": "ap-southeast-2"}).encode()
        id_resp = _make_response(200, identity_doc)

        with patch(
            "urllib.request.urlopen",
            side_effect=[token_resp, id_resp],
        ):
            ctx = _probe_aws()

        assert ctx is not None
        assert ctx.region == "ap-southeast-2"

    def test_returns_none_on_url_error(self):
        """URLError on the token request must cause the probe to return None."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ):
            ctx = _probe_aws()

        assert ctx is None

    def test_returns_none_on_os_error(self):
        """OSError on the token request must cause the probe to return None."""
        with patch(
            "urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ):
            ctx = _probe_aws()

        assert ctx is None


# ---------------------------------------------------------------------------
# T41-3: Azure probe — success
# ---------------------------------------------------------------------------

class TestProbeAzure:
    """Tests for _probe_azure()."""

    def test_returns_cloud_context_on_200(self):
        """A 200 from Azure IMDS must yield CloudContext(provider='azure')."""
        import json

        body = json.dumps({
            "compute": {
                "subscriptionId": "sub-abc-123",
                "location": "eastus",
            }
        }).encode()
        resp = _make_response(200, body)

        with patch("urllib.request.urlopen", return_value=resp):
            ctx = _probe_azure()

        assert ctx is not None
        assert ctx.provider == "azure"

    def test_subscription_id_as_project_id(self):
        """Azure subscriptionId must be stored as project_id."""
        import json

        body = json.dumps({
            "compute": {
                "subscriptionId": "my-subscription-id",
                "location": "westeurope",
            }
        }).encode()
        resp = _make_response(200, body)

        with patch("urllib.request.urlopen", return_value=resp):
            ctx = _probe_azure()

        assert ctx is not None
        assert ctx.project_id == "my-subscription-id"

    def test_location_as_region(self):
        """Azure location must be stored as region."""
        import json

        body = json.dumps({
            "compute": {"subscriptionId": "sub", "location": "australiaeast"}
        }).encode()
        resp = _make_response(200, body)

        with patch("urllib.request.urlopen", return_value=resp):
            ctx = _probe_azure()

        assert ctx is not None
        assert ctx.region == "australiaeast"

    def test_returns_none_on_url_error(self):
        """URLError must cause the probe to return None."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ):
            ctx = _probe_azure()

        assert ctx is None

    def test_returns_none_on_os_error(self):
        """OSError must cause the probe to return None."""
        with patch(
            "urllib.request.urlopen",
            side_effect=OSError("network unreachable"),
        ):
            ctx = _probe_azure()

        assert ctx is None


# ---------------------------------------------------------------------------
# T41-4: detect_cloud_context — orchestration
# ---------------------------------------------------------------------------

class TestDetectCloudContext:
    """Tests for detect_cloud_context() orchestration."""

    def test_returns_none_when_all_probes_fail(self):
        """When no IMDS is reachable, the function must return None."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("timeout"),
        ):
            result = detect_cloud_context()

        assert result is None

    def test_returns_gcp_when_gcp_probe_succeeds(self):
        """GCP probe succeeding means GCP context is returned (first wins)."""
        gcp_resp = _make_response(200, b"my-project")
        zone_resp = _make_response(200, b"projects/123/zones/us-central1-a")

        with patch(
            "urllib.request.urlopen",
            side_effect=[gcp_resp, zone_resp],
        ):
            result = detect_cloud_context()

        assert result is not None
        assert result.provider == "gcp"

    def test_falls_through_to_aws_when_gcp_fails(self):
        """When GCP times out, AWS probe should be tried."""
        import json

        aws_token = _make_response(200, b"TOKEN")
        aws_id = _make_response(
            200,
            json.dumps({"accountId": "123", "region": "us-east-1"}).encode(),
        )

        # First call (GCP) raises; second and third calls (AWS token, identity) succeed
        with patch(
            "urllib.request.urlopen",
            side_effect=[urllib.error.URLError("gcp timeout"), aws_token, aws_id],
        ):
            result = detect_cloud_context()

        assert result is not None
        assert result.provider == "aws"

    def test_falls_through_to_azure_when_gcp_and_aws_fail(self):
        """When GCP and AWS time out, Azure probe should be tried."""
        import json

        azure_resp = _make_response(
            200,
            json.dumps({
                "compute": {"subscriptionId": "sub123", "location": "eastus"}
            }).encode(),
        )

        # GCP: 2 calls can fail (project-id probe + zone probe fallback)
        # AWS: 1 call fails (token request)
        # Azure: 1 call succeeds
        with patch(
            "urllib.request.urlopen",
            side_effect=[
                urllib.error.URLError("gcp"),    # GCP project-id probe
                urllib.error.URLError("aws"),    # AWS token request
                azure_resp,                       # Azure IMDS
            ],
        ):
            result = detect_cloud_context()

        assert result is not None
        assert result.provider == "azure"

    def test_returns_cloud_context_instance(self):
        """detect_cloud_context must return a CloudContext when successful."""
        gcp_resp = _make_response(200, b"test-project")
        zone_resp = _make_response(200, b"projects/123/zones/us-central1-a")

        with patch(
            "urllib.request.urlopen",
            side_effect=[gcp_resp, zone_resp],
        ):
            result = detect_cloud_context()

        assert isinstance(result, CloudContext)


# ---------------------------------------------------------------------------
# T41-5: Timeout behavior
# ---------------------------------------------------------------------------

class TestTimeoutBehavior:
    """Verify that probes complete quickly when endpoints are unreachable."""

    def test_gcp_probe_returns_quickly_on_timeout(self):
        """_probe_gcp must complete in well under 1 second when mocked to fail."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("instant fail"),
        ):
            start = time.monotonic()
            _probe_gcp()
            elapsed = time.monotonic() - start

        # With mocked instant failure, should complete in milliseconds
        assert elapsed < 1.0, f"Probe took {elapsed:.3f}s — suspiciously slow"

    def test_detect_cloud_context_completes_quickly_when_all_fail(self):
        """detect_cloud_context must finish quickly when all probes fail instantly."""
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("instant fail"),
        ):
            start = time.monotonic()
            detect_cloud_context()
            elapsed = time.monotonic() - start

        # Mocked — should complete in well under 500ms
        assert elapsed < 0.5, f"detect_cloud_context took {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# T41-6: CloudContext dataclass
# ---------------------------------------------------------------------------

class TestCloudContextDataclass:
    """Sanity checks on the CloudContext dataclass."""

    def test_required_provider_field(self):
        ctx = CloudContext(provider="gcp")
        assert ctx.provider == "gcp"

    def test_optional_fields_default_to_none(self):
        ctx = CloudContext(provider="aws")
        assert ctx.project_id is None
        assert ctx.region is None

    def test_metadata_defaults_to_empty_dict(self):
        ctx = CloudContext(provider="azure")
        assert ctx.metadata == {}

    def test_full_construction(self):
        ctx = CloudContext(
            provider="gcp",
            project_id="proj-1",
            region="us-central1",
            metadata={"key": "value"},
        )
        assert ctx.provider == "gcp"
        assert ctx.project_id == "proj-1"
        assert ctx.region == "us-central1"
        assert ctx.metadata == {"key": "value"}
