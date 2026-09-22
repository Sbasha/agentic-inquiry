"""Unit tests for ``SentenceTransformerEmbedder`` device selection.

These tests exercise the device-autodetect + graceful CPU fallback
behaviour added to support Apple Silicon (MPS) users without making the
embedder brittle on systems where MPS reports availability but breaks
during model placement.

Pure-unit style — torch and sentence_transformers are mocked via
``monkeypatch.setitem(sys.modules, ...)`` so the fakes are torn down
automatically at the end of each test. That's important because the
module under test has module-level ``import torch`` behaviour (inside
``_select_device``) and leaked fakes between tests cause order-dependent
failures (e.g. a later test that wants the real torch gets the fake one
this test installed).
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_fake_torch(
    *,
    cuda_available: bool = False,
    mps_built: bool = False,
    mps_available: bool = False,
    mps_backend_exists: bool = True,
) -> types.ModuleType:
    """Build a minimal fake ``torch`` module.

    Returns the module object — callers install it via
    ``monkeypatch.setitem(sys.modules, "torch", fake_torch)`` so pytest
    restores state after the test (no cross-test leakage).
    """
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: cuda_available)

    if mps_backend_exists:
        mps = types.SimpleNamespace(
            is_built=lambda: mps_built,
            is_available=lambda: mps_available,
        )
        fake_torch.backends = types.SimpleNamespace(mps=mps)
    else:
        fake_torch.backends = types.SimpleNamespace()

    return fake_torch


def _install_fake_torch(monkeypatch, **kwargs) -> types.ModuleType:
    """Install a fake torch into sys.modules under monkeypatch control."""
    fake_torch = _make_fake_torch(**kwargs)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    return fake_torch


def _reimport_module(monkeypatch):
    """Drop the cached ``sentence_transformer`` module so the next import
    picks up the freshly-installed fake ``torch`` / ``sentence_transformers``
    modules. ``monkeypatch.delitem`` restores the original module at
    teardown, so this is leak-safe.
    """
    module_name = "agentic_inquiry.embeddings.sentence_transformer"
    if module_name in sys.modules:
        monkeypatch.delitem(sys.modules, module_name)


def _install_fake_sentence_transformers(monkeypatch, *, mps_raises: bool = False):
    """Install a fake ``sentence_transformers`` that can optionally raise
    when instantiated with ``device="mps"`` and succeed on CPU.

    Returns the mock SentenceTransformer class so tests can assert on
    how it was called.
    """
    fake_st_module = types.ModuleType("sentence_transformers")
    mock_class = MagicMock(name="SentenceTransformer")

    def _side_effect(model_name, device=None):
        if mps_raises and device == "mps":
            raise RuntimeError("MPS model placement failed")
        instance = MagicMock()
        instance.device = device
        instance.model_name = model_name
        return instance

    mock_class.side_effect = _side_effect
    fake_st_module.SentenceTransformer = mock_class
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_module)
    return mock_class


class TestSelectDevice:
    """Pure tests for ``_select_device`` — no embedder instantiation."""

    def test_prefers_cuda_when_available(self, monkeypatch):
        _install_fake_torch(
            monkeypatch, cuda_available=True, mps_built=True, mps_available=True
        )
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import _select_device

        assert _select_device() == "cuda"

    def test_selects_mps_when_apple_silicon(self, monkeypatch):
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=True, mps_available=True
        )
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import _select_device

        assert _select_device() == "mps"

    def test_cpu_fallback_when_mps_built_but_not_available(self, monkeypatch):
        """Non-Apple-Silicon Mac with an MPS-enabled torch wheel: ``is_built``
        is True but ``is_available`` is False. Must not claim MPS."""
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=True, mps_available=False
        )
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import _select_device

        assert _select_device() == "cpu"

    def test_cpu_fallback_when_mps_backend_missing(self, monkeypatch):
        """Older torch without an MPS backend at all — defensive guard."""
        _install_fake_torch(monkeypatch, cuda_available=False, mps_backend_exists=False)
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import _select_device

        assert _select_device() == "cpu"

    def test_cpu_when_nothing_available(self, monkeypatch):
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=False, mps_available=False
        )
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import _select_device

        assert _select_device() == "cpu"

    def test_preferred_overrides_autodetect(self, monkeypatch):
        """Explicit preferred device (the escape hatch) bypasses detection."""
        _install_fake_torch(monkeypatch, cuda_available=True)
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import _select_device

        assert _select_device(preferred="cpu") == "cpu"

    def test_preferred_is_normalised(self, monkeypatch):
        """Case / whitespace variants of known devices are accepted."""
        _install_fake_torch(monkeypatch, cuda_available=True)
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import _select_device

        assert _select_device(preferred="CPU") == "cpu"
        assert _select_device(preferred=" Mps ") == "mps"

    def test_preferred_unknown_value_falls_through_with_warning(
        self, monkeypatch, caplog
    ):
        """Unknown preferred value must not poison the return — we warn
        and let autodetect pick. Matches the docstring's "if usable"
        contract, and keeps ``SentenceTransformer(device=garbage)`` from
        raising a less-actionable error downstream.
        """
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=True, mps_available=True
        )
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import _select_device

        with caplog.at_level("WARNING"):
            result = _select_device(preferred="gpu")  # not a torch device name

        assert result == "mps", "Should fall through to autodetect on unknown preferred"
        assert any(
            "Ignoring unknown preferred device" in r.message for r in caplog.records
        )

    def test_cpu_when_torch_missing(self, monkeypatch):
        """No torch installed → CPU. Embedder will still fail later at
        actual model load, but device selection itself is safe."""
        monkeypatch.setitem(sys.modules, "torch", None)
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import _select_device

        assert _select_device() == "cpu"


class TestModelLoadFallback:
    """Tests for the graceful CPU fallback on accelerator load failure.

    The SentenceTransformer constructor sometimes raises on MPS-reporting
    systems where the device is "built and available" but actual model
    placement fails (seen on older macOS, torch nightlies, and certain
    model configurations). The embedder must not propagate that — it
    should log and retry on CPU so indexing still completes.
    """

    def test_falls_back_to_cpu_on_mps_load_failure(self, monkeypatch, caplog):
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=True, mps_available=True
        )
        mock_st = _install_fake_sentence_transformers(monkeypatch, mps_raises=True)
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import (
            SentenceTransformerEmbedder,
        )

        embedder = SentenceTransformerEmbedder()
        with caplog.at_level("WARNING"):
            embedder._ensure_model_loaded()

        # Two calls: once on mps (raised), then fallback on cpu (succeeded).
        assert mock_st.call_count == 2
        device_kwargs = [c.kwargs.get("device") for c in mock_st.call_args_list]
        assert device_kwargs == ["mps", "cpu"]
        assert embedder._model is not None
        assert embedder._model.device == "cpu"
        assert any(
            "falling back to CPU" in record.message for record in caplog.records
        ), "Expected a warning log when falling back from MPS to CPU"

    def test_no_fallback_when_cpu_is_already_the_target(self, monkeypatch):
        """If we're already on CPU and load fails, the error must propagate —
        there's nothing safer to try, and silently hiding it would mask real
        problems like missing model files or corrupt weights.
        """
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=False, mps_available=False
        )
        fake_st_module = types.ModuleType("sentence_transformers")
        mock_class = MagicMock(name="SentenceTransformer")
        mock_class.side_effect = RuntimeError("corrupt weights")
        fake_st_module.SentenceTransformer = mock_class
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_module)
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import (
            SentenceTransformerEmbedder,
        )

        embedder = SentenceTransformerEmbedder()
        with pytest.raises(RuntimeError, match="corrupt weights"):
            embedder._ensure_model_loaded()

    def test_no_fallback_on_successful_mps_load(self, monkeypatch):
        """Happy path on Apple Silicon — MPS load succeeds, no retry."""
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=True, mps_available=True
        )
        mock_st = _install_fake_sentence_transformers(monkeypatch, mps_raises=False)
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import (
            SentenceTransformerEmbedder,
        )

        embedder = SentenceTransformerEmbedder()
        embedder._ensure_model_loaded()

        assert mock_st.call_count == 1
        assert mock_st.call_args.kwargs["device"] == "mps"


class TestDeviceEnvVar:
    """``INQUIRY_EMBEDDING_DEVICE`` escape hatch — lets operators pin the
    device when autodetect picks something that misbehaves (e.g. MPS
    loads but hangs at inference time)."""

    def test_env_var_pins_cpu_even_when_mps_available(self, monkeypatch):
        """Operator has set the env var; autodetect must be bypassed."""
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=True, mps_available=True
        )
        mock_st = _install_fake_sentence_transformers(monkeypatch, mps_raises=False)
        monkeypatch.setenv("INQUIRY_EMBEDDING_DEVICE", "cpu")
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import (
            SentenceTransformerEmbedder,
        )

        embedder = SentenceTransformerEmbedder()
        embedder._ensure_model_loaded()

        assert mock_st.call_args.kwargs["device"] == "cpu"

    def test_empty_env_var_falls_through_to_autodetect(self, monkeypatch):
        """Unset or empty env var must not override autodetect — covers
        the ``os.environ.get(...) or None`` coalescing."""
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=True, mps_available=True
        )
        mock_st = _install_fake_sentence_transformers(monkeypatch, mps_raises=False)
        monkeypatch.setenv("INQUIRY_EMBEDDING_DEVICE", "")
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import (
            SentenceTransformerEmbedder,
        )

        embedder = SentenceTransformerEmbedder()
        embedder._ensure_model_loaded()

        assert mock_st.call_args.kwargs["device"] == "mps"

    def test_invalid_env_var_falls_through_and_loads_on_autodetected_device(
        self, monkeypatch, caplog
    ):
        """End-to-end: env var set to an invalid value → ``_select_device``
        warns and falls through → autodetect picks MPS → model loads on
        MPS. Exercises the full env-var → autodetect → load path in one
        test, covering the case operators most likely hit when they
        mistype the hatch (``gpu`` is a common wrong guess on Mac).
        """
        _install_fake_torch(
            monkeypatch, cuda_available=False, mps_built=True, mps_available=True
        )
        mock_st = _install_fake_sentence_transformers(monkeypatch, mps_raises=False)
        monkeypatch.setenv("INQUIRY_EMBEDDING_DEVICE", "gpu")  # not a torch name
        _reimport_module(monkeypatch)
        from agentic_inquiry.embeddings.sentence_transformer import (
            SentenceTransformerEmbedder,
        )

        embedder = SentenceTransformerEmbedder()
        with caplog.at_level("WARNING"):
            embedder._ensure_model_loaded()

        assert mock_st.call_args.kwargs["device"] == "mps", (
            "Invalid env var should trigger autodetect, not propagate 'gpu'"
        )
        assert embedder._model is not None
        assert embedder._model.device == "mps"
        assert any(
            "Ignoring unknown preferred device" in r.message for r in caplog.records
        ), "Expected the fall-through warning from _select_device"
