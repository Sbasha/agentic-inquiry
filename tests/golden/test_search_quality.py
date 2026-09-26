"""Pytest wrapper around the golden bench script.

The real bench logic lives in ``tests/golden/bench.py`` so it can also run
from ``make bench`` without pulling in pytest. This wrapper is a thin
regression test that fails when recall drops or p95 latency exceeds the
budget defined in ``bench.py``.

Marked ``slow`` because it indexes a non-trivial corpus and downloads the
embedding model on a cold cache. Skip with ``-m 'not slow'``.
"""

from __future__ import annotations

import pytest

from tests.golden import bench

pytestmark = [pytest.mark.golden, pytest.mark.slow, pytest.mark.timeout(600)]


@pytest.mark.asyncio
async def test_recall_and_latency_within_budget() -> None:
    """Run the bench and assert no regression vs. tests/golden/baseline.json."""
    if not bench.BASELINE_FILE.exists():
        pytest.skip(
            f"No baseline at {bench.BASELINE_FILE}. "
            "Run `make bench-pin` (or `python tests/golden/bench.py --pin`) first."
        )

    passed, messages, _ = await bench.run_bench()
    assert passed, "Golden bench regressed:\n" + "\n".join(messages)
