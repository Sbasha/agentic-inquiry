"""Tests for the recognizer Protocol + registry.

Covers the dispatch + failure-isolation contract described in
``agentic_inquiry/parsers/recognizers/base.py``:

- Extension-based dispatch routes only to recognizers that declare
  support for a file's extension.
- Duplicate registration by name is a no-op.
- A recognizer that raises does not prevent other recognizers from
  running or the document from being returned.
"""

from __future__ import annotations

from typing import FrozenSet

import pytest

from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk
from agentic_inquiry.parsers.recognizers import (
    apply_recognizers,
    get_recognizers_for_path,
    list_recognizers,
    register_recognizer,
    unregister_recognizer,
)

pytestmark = pytest.mark.unit


class _StubRecognizer:
    """Minimal recognizer that records calls and tags chunks.

    Tagging via ``metadata`` rather than a relationship keeps the
    assertions free of the :class:`ParserRelationship` dataclass
    machinery — we're testing dispatch, not enrichment shape.
    """

    def __init__(
        self,
        name: str,
        extensions: FrozenSet[str],
        raises: bool = False,
    ) -> None:
        self._name = name
        self._extensions = extensions
        self._raises = raises
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def file_extensions(self) -> FrozenSet[str]:
        return self._extensions

    async def enrich(self, parsed: ParsedDocument) -> ParsedDocument:
        self.call_count += 1
        if self._raises:
            raise RuntimeError(f"{self._name} exploded")
        for chunk in parsed.chunks:
            tags = (chunk.metadata or {}).get("recognizer_tags", [])
            chunk.metadata = {
                **(chunk.metadata or {}),
                "recognizer_tags": [*tags, self._name],
            }
        return parsed


@pytest.fixture(autouse=True)
def _clean_registry():
    """Drop every recognizer around each test so registrations don't
    leak between cases.
    """
    for name in list_recognizers():
        unregister_recognizer(name)
    yield
    for name in list_recognizers():
        unregister_recognizer(name)


def _doc(path: str) -> ParsedDocument:
    return ParsedDocument(
        doc_id=path,
        file_path=path,
        chunks=[ParserChunk(content="x", element_type="method", element_name="m")],
    )


class TestRegistrationAndDispatch:
    def test_dispatch_by_extension(self):
        py_rec = _StubRecognizer("py", frozenset({".py"}))
        java_rec = _StubRecognizer("java", frozenset({".java"}))
        register_recognizer(py_rec)
        register_recognizer(java_rec)

        assert [r.name for r in get_recognizers_for_path("/x/foo.py")] == ["py"]
        assert [r.name for r in get_recognizers_for_path("/x/foo.java")] == ["java"]
        assert get_recognizers_for_path("/x/foo.go") == []

    def test_extension_match_is_case_insensitive(self):
        rec = _StubRecognizer("java", frozenset({".java"}))
        register_recognizer(rec)
        # Upper-case extension still routes.
        assert [r.name for r in get_recognizers_for_path("/x/Foo.JAVA")] == ["java"]

    def test_multiple_recognizers_can_share_an_extension(self):
        """Two recognizers on ``.py`` is a supported case — e.g. FastAPI
        and Click both want to enrich Python files.
        """
        a = _StubRecognizer("fastapi", frozenset({".py"}))
        b = _StubRecognizer("click", frozenset({".py"}))
        register_recognizer(a)
        register_recognizer(b)

        names = [r.name for r in get_recognizers_for_path("/x/app.py")]
        assert set(names) == {"fastapi", "click"}

    def test_duplicate_registration_is_ignored(self):
        rec = _StubRecognizer("dupe", frozenset({".py"}))
        register_recognizer(rec)
        register_recognizer(rec)
        # Still only one — duplicates filtered by name.
        assert list_recognizers() == ("dupe",)


class TestApplyRecognizers:
    async def test_runs_all_matching_recognizers_in_order(self):
        first = _StubRecognizer("first", frozenset({".py"}))
        second = _StubRecognizer("second", frozenset({".py"}))
        register_recognizer(first)
        register_recognizer(second)

        doc = _doc("/x/foo.py")
        enriched = await apply_recognizers(doc)

        tags = enriched.chunks[0].metadata["recognizer_tags"]
        assert tags == ["first", "second"]

    async def test_does_not_call_non_matching_recognizers(self):
        py_rec = _StubRecognizer("py", frozenset({".py"}))
        java_rec = _StubRecognizer("java", frozenset({".java"}))
        register_recognizer(py_rec)
        register_recognizer(java_rec)

        await apply_recognizers(_doc("/x/foo.py"))

        assert py_rec.call_count == 1
        assert java_rec.call_count == 0

    async def test_recognizer_failure_does_not_block_others(self):
        """An exception from one recognizer must be logged and
        swallowed — the next recognizer still runs and the document
        comes back with partial enrichment.
        """
        broken = _StubRecognizer("broken", frozenset({".py"}), raises=True)
        good = _StubRecognizer("good", frozenset({".py"}))
        register_recognizer(broken)
        register_recognizer(good)

        doc = _doc("/x/foo.py")
        enriched = await apply_recognizers(doc)

        # Broken recognizer was invoked (and raised) but didn't kill
        # the chain.
        assert broken.call_count == 1
        assert good.call_count == 1
        # ``good`` still tagged the chunk.
        assert enriched.chunks[0].metadata["recognizer_tags"] == ["good"]

    def test_parser_chain_construction_registers_builtins(self):
        """Every ``ParserChain`` construction path — ``__init__``,
        ``from_config``, ``create_parser_chain`` — must end up with
        the built-in recognizers registered. Copilot's review flagged
        that ``create_parser_chain`` skipped the registration when it
        was only done in ``from_config``; pinning all three here
        prevents regressions.
        """
        from agentic_inquiry.parsers.chain import (
            ParserChain,
            create_parser_chain,
        )

        # Direct ``__init__``.
        ParserChain()
        assert "java_spring" in list_recognizers()

        # Reset and try ``from_config``.
        for name in list_recognizers():
            unregister_recognizer(name)
        ParserChain.from_config()
        assert "java_spring" in list_recognizers()

        # Reset and try ``create_parser_chain``.
        for name in list_recognizers():
            unregister_recognizer(name)
        create_parser_chain()
        assert "java_spring" in list_recognizers()

    def test_repeated_chain_construction_does_not_reinstantiate_recognizer(
        self, monkeypatch
    ):
        """``_register_builtin_recognizers`` must skip construction when
        the recognizer is already registered — otherwise every
        ``ParserChain()`` pays for a fresh ``JavaSpringRecognizer``
        (and its ``threading.Lock``) that the registry immediately
        discards via name-dedup.
        """
        from agentic_inquiry.parsers.chain import ParserChain
        from agentic_inquiry.parsers.recognizers import java_spring

        # Register the built-ins once.
        ParserChain()
        assert "java_spring" in list_recognizers()

        # Patch ``JavaSpringRecognizer`` to count instantiations.
        construction_count = {"n": 0}
        real_cls = java_spring.JavaSpringRecognizer

        class CountingRecognizer(real_cls):  # type: ignore[misc,valid-type]
            def __init__(self) -> None:
                construction_count["n"] += 1
                super().__init__()

        monkeypatch.setattr(java_spring, "JavaSpringRecognizer", CountingRecognizer)

        # Subsequent constructions must not re-instantiate: the
        # name-check short-circuits before the class is called.
        ParserChain()
        ParserChain()
        ParserChain()

        assert construction_count["n"] == 0, (
            "JavaSpringRecognizer was re-instantiated on a repeated "
            "ParserChain construction — the name-check short-circuit "
            "is not working"
        )

    async def test_explicit_recognizers_argument_bypasses_registry(self):
        """Passing ``recognizers=`` should run exactly that iterable,
        regardless of what's in the registry or what the file
        extension is.
        """
        registered = _StubRecognizer("registered", frozenset({".py"}))
        register_recognizer(registered)
        override = _StubRecognizer("override", frozenset({".py"}))

        doc = _doc("/x/foo.go")  # extension wouldn't match anything
        enriched = await apply_recognizers(doc, recognizers=[override])

        assert override.call_count == 1
        assert registered.call_count == 0
        assert enriched.chunks[0].metadata["recognizer_tags"] == ["override"]
