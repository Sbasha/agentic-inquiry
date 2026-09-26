"""Concurrent model loads must not corrupt the process.

Overlapping sentence-transformers loads leave every later load in the process
failing with "Cannot copy out of meta tensor". The check runs in a subprocess
so a regression cannot poison the model loads of the rest of the suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.model

_SCRIPT = textwrap.dedent(
    """
    from concurrent.futures import ThreadPoolExecutor

    from agentic_inquiry.embeddings.sentence_transformer import SentenceTransformerEmbedder

    def embed(_):
        return len(SentenceTransformerEmbedder().generate(["hello"])[0])

    for _ in range(2):
        with ThreadPoolExecutor(8) as pool:
            print(sorted(set(pool.map(embed, range(8)))))
    print(embed(0))
    """
)


@pytest.mark.timeout(420)
def test_concurrent_embedder_loads_all_succeed() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        timeout=300,  # fails this test with its stderr before pytest-timeout fires
        env={**os.environ, "INQUIRY_EMBEDDING_DEVICE": "cpu"},
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.split() == ["[384]", "[384]", "384"]
