"""Recognizer protocol + registry.

A recognizer is a post-processor keyed on file extension. Given a
:class:`ParsedDocument`, it returns an enriched version with
framework-specific relationships and (optionally) metadata added to
existing chunks.

Recognizers must be:
- **Idempotent.** Running the same recognizer twice on the same
  document must produce the same result. The chain calls each
  recognizer at most once per document today, but idempotence makes
  the behaviour robust to future re-plays (e.g. incremental indexing
  that re-runs the recognizer stage).
- **Additive.** Do not remove or overwrite chunks / relationships
  produced by the base parser; only add. This keeps recognizers
  composable — two recognizers for the same file (e.g. Spring +
  generic Java) don't step on each other.
- **Failure-safe.** A recognizer that raises should not prevent the
  document from being indexed with its base parse. :func:`apply_recognizers`
  catches exceptions per-recognizer and logs them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Protocol, Tuple, runtime_checkable

from agent_vault.parsers.models import ParsedDocument

logger = logging.getLogger(__name__)


@runtime_checkable
class Recognizer(Protocol):
    """Framework recognizer protocol.

    Implementations live next to this file (e.g. ``java_spring.py``)
    and are registered via :func:`register_recognizer`. The chain
    dispatches to recognizers by file extension — each recognizer
    declares which extensions it handles via :attr:`file_extensions`.
    """

    @property
    def name(self) -> str:
        """Short stable identifier, used in logs and registry lookups."""

    @property
    def file_extensions(self) -> frozenset[str]:
        """File extensions (including leading dot, lowercase) this
        recognizer can enrich. e.g. ``frozenset({".java"})``.

        Dispatch is O(1) — the chain only calls recognizers whose
        extension set contains the document's file extension. A
        recognizer that wanted to match multiple languages would
        return e.g. ``frozenset({".py", ".pyi"})``.
        """

    async def enrich(self, parsed: ParsedDocument) -> ParsedDocument:
        """Return an enriched copy (or the same instance mutated) of
        ``parsed``. Must be idempotent and additive — see module
        docstring.

        Raising from this method is caught and logged by
        :func:`apply_recognizers`; the base parse still reaches the
        indexing pipeline. A recognizer that cannot parse a specific
        file should return ``parsed`` unchanged rather than raise.
        """


# Module-level registry. Intentionally kept as a simple list — O(n) dispatch
# over a handful of recognizers is trivial, and avoiding a dict lets two
# recognizers share an extension (e.g. ``.py`` → FastAPI + Click).
_RECOGNIZERS: List[Recognizer] = []


def register_recognizer(recognizer: Recognizer) -> None:
    """Register a recognizer. Later additions take precedence in the
    log ordering only — recognizer effects are additive, so order
    doesn't change the final graph.

    Safe to call multiple times with the same recognizer; duplicates
    are filtered by name so accidental double-registration (common in
    test setup) doesn't double-process documents.
    """
    if any(r.name == recognizer.name for r in _RECOGNIZERS):
        logger.debug("Recognizer %r already registered; skipping", recognizer.name)
        return
    _RECOGNIZERS.append(recognizer)
    logger.debug(
        "Registered recognizer %r for extensions %s",
        recognizer.name,
        sorted(recognizer.file_extensions),
    )


def unregister_recognizer(name: str) -> None:
    """Remove a recognizer by name. No-op if not registered.

    Primarily useful for test teardown — production code normally
    registers once via ``_register_builtin_recognizers`` and lets the
    chain handle dispatch.
    """
    before = len(_RECOGNIZERS)
    _RECOGNIZERS[:] = [r for r in _RECOGNIZERS if r.name != name]
    if len(_RECOGNIZERS) != before:
        logger.debug("Unregistered recognizer %r", name)


def list_recognizers() -> Tuple[str, ...]:
    """Return registered recognizer names, in registration order."""
    return tuple(r.name for r in _RECOGNIZERS)


def get_recognizers_for_path(file_path: str) -> List[Recognizer]:
    """Return recognizers whose extension set matches ``file_path``.

    Matching is case-insensitive on the extension, so ``Foo.Java`` and
    ``foo.java`` route identically.
    """
    ext = Path(file_path).suffix.lower()
    if not ext:
        return []
    return [r for r in _RECOGNIZERS if ext in r.file_extensions]


async def apply_recognizers(
    parsed: ParsedDocument,
    recognizers: Iterable[Recognizer] | None = None,
) -> ParsedDocument:
    """Run every applicable recognizer on ``parsed``, returning the
    enriched document.

    If ``recognizers`` is supplied, use that iterable verbatim (useful
    for tests and explicit invocation). Otherwise, dispatch by file
    extension against the module-level registry.

    Recognizers run sequentially. Each one sees the output of the
    previous — so a document passing through Recognizer A then B sees
    A's enrichment when B runs. This lets recognizers compose
    naturally without needing to merge enriched documents.

    Exceptions from individual recognizers are caught and logged at
    WARNING — the document continues through the remaining recognizers
    and returns with whatever enrichment succeeded. This matches the
    "recognizer failure is never fatal" contract: a broken recognizer
    must never prevent indexing.
    """
    if recognizers is None:
        recognizers = get_recognizers_for_path(parsed.file_path)

    for recognizer in recognizers:
        try:
            parsed = await recognizer.enrich(parsed)
        except Exception as exc:
            logger.warning(
                "Recognizer %r failed for %s: %s",
                recognizer.name,
                parsed.file_path,
                exc,
                exc_info=True,
            )
            # Keep going — recognizer failure must never block indexing.

    return parsed
