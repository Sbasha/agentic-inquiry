"""Live cloud smoke tests for the S3 and GCS connectors.

These hit real object storage and are skipped by default. Opt in with
``-m cloud_smoke`` and the appropriate credentials + bucket env vars:

- S3:  ``agv_SMOKE_S3_BUCKET`` (+ standard AWS credential resolution;
       optional ``agv_SMOKE_S3_PREFIX``, ``agv_SMOKE_S3_ENDPOINT_URL`` for
       MinIO / LocalStack).
- GCS: ``agv_SMOKE_GCS_BUCKET`` (+ ``GOOGLE_APPLICATION_CREDENTIALS`` or
       ambient GCP credentials; optional ``agv_SMOKE_GCS_PREFIX``).

Each test enumerates at least one object and round-trips its content,
exercising ``connector.list()`` and ``connector.open()`` end to end.
"""
from __future__ import annotations

import importlib.util
import os

import pytest

pytestmark = pytest.mark.cloud_smoke

HAS_S3FS = importlib.util.find_spec("s3fs") is not None
HAS_GCSFS = importlib.util.find_spec("gcsfs") is not None


async def _list_first(connector) -> object:
    """Return the first SourceItem the connector enumerates, or skip."""
    async for item in connector.list():
        return item
    pytest.skip("no objects enumerated from the configured bucket/prefix")
    raise AssertionError("unreachable")  # pytest.skip raises; explicit for analysis


@pytest.mark.skipif(not HAS_S3FS, reason="s3fs not installed")
async def test_s3_live_list_and_open() -> None:
    """List and read at least one object from a live S3 bucket."""
    bucket = os.environ.get("agv_SMOKE_S3_BUCKET")
    if not bucket:
        pytest.skip("agv_SMOKE_S3_BUCKET not set")

    from agent_vault.connectors.s3 import S3Connector

    connector = S3Connector(
        bucket=bucket,
        prefix=os.environ.get("agv_SMOKE_S3_PREFIX", ""),
        endpoint_url=os.environ.get("agv_SMOKE_S3_ENDPOINT_URL"),
    )

    item = await _list_first(connector)
    assert item.uri.startswith("s3://")
    assert item.protocol == "s3"

    content = await connector.open(item)
    assert content.data is not None
    # Empty objects are legal, so don't require size > 0; cross-check the
    # fetched payload against the listed metadata when it's available.
    if item.size is not None:
        assert content.size == item.size


@pytest.mark.skipif(not HAS_GCSFS, reason="gcsfs not installed")
async def test_gcs_live_list_and_open() -> None:
    """List and read at least one object from a live GCS bucket."""
    bucket = os.environ.get("agv_SMOKE_GCS_BUCKET")
    if not bucket:
        pytest.skip("agv_SMOKE_GCS_BUCKET not set")

    from agent_vault.connectors.gcs import GCSConnector

    connector = GCSConnector(
        bucket=bucket,
        prefix=os.environ.get("agv_SMOKE_GCS_PREFIX", ""),
    )

    item = await _list_first(connector)
    assert item.uri.startswith("gcs://")
    assert item.protocol == "gcs"

    content = await connector.open(item)
    assert content.data is not None
    # Empty objects are legal, so don't require size > 0; cross-check the
    # fetched payload against the listed metadata when it's available.
    if item.size is not None:
        assert content.size == item.size
