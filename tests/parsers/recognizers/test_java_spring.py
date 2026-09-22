"""Tests for :class:`JavaSpringRecognizer`.

Fixtures are inline Java source strings written to tmp files — keeping
them inline makes the test + expectation pair readable on one screen
and avoids scattering tiny ``.java`` files across the repo. The base
parser output is built by hand as :class:`ParsedDocument` /
:class:`ParserChunk` instances so the tests exercise the recognizer
in isolation from the rest of the parsing pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_inquiry.parsers.models import (
    ParsedDocument,
    ParserChunk,
    ParserRelationship,
)
from agentic_inquiry.parsers.recognizers.java_spring import JavaSpringRecognizer

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_java(tmp_path: Path, source: str, name: str = "Controller.java") -> Path:
    file_path = tmp_path / name
    file_path.write_text(source)
    return file_path


def _doc_for(
    file_path: Path, method_names: list[str], class_name: str = "UserController"
) -> ParsedDocument:
    """Build a minimal ParsedDocument with method chunks for the given names.

    Mirrors the shape of ``unified_code``'s output but only includes
    the fields the recognizer actually reads (``element_type``,
    ``element_name``, ``relationships``). Keeps the fixture small.
    """
    chunks = [
        ParserChunk(
            content=f"class {class_name} {{...}}",
            element_type="class",
            element_name=class_name,
            relationships=[],
        ),
    ]
    for method_name in method_names:
        chunks.append(
            ParserChunk(
                content=f"{method_name}() {{...}}",
                element_type="method",
                element_name=method_name,
                relationships=[],
            )
        )
    return ParsedDocument(
        doc_id=str(file_path),
        file_path=str(file_path),
        chunks=chunks,
        metadata={},
    )


def _spring_routes(chunk: ParserChunk) -> list[ParserRelationship]:
    return [r for r in chunk.relationships if r.type == "spring_route"]


# ---------------------------------------------------------------------------
# Basic route extraction
# ---------------------------------------------------------------------------


class TestBasicRouteExtraction:
    """The golden path: ``@RestController`` + ``@GetMapping``."""

    async def test_rest_controller_with_get_mapping(self, tmp_path):
        src = """
        package com.example;
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/users")
        public class UserController {

            @GetMapping("/{id}")
            public User getUser(@PathVariable String id) {
                return null;
            }

            @PostMapping
            public User createUser(@RequestBody User u) {
                return u;
            }
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["getUser", "createUser"])

        enriched = await JavaSpringRecognizer().enrich(doc)

        get_chunk = next(c for c in enriched.chunks if c.element_name == "getUser")
        post_chunk = next(c for c in enriched.chunks if c.element_name == "createUser")

        get_routes = _spring_routes(get_chunk)
        post_routes = _spring_routes(post_chunk)

        assert len(get_routes) == 1
        assert get_routes[0].metadata["http_method"] == "GET"
        assert get_routes[0].metadata["path"] == "/users/{id}"
        assert get_routes[0].metadata["framework"] == "spring"
        assert get_routes[0].metadata["controller_class"] == "UserController"
        # ``target_path`` lets downstream graph builders link the
        # route entity back to its source file without a separate join.
        assert get_routes[0].target_path == str(file_path)
        # Java handlers are class methods — ``unified_code`` records
        # them as ``method`` symbols, and the edge source_type
        # mirrors that so the graph layer's entity-id join lands.
        assert get_routes[0].source_type == "method"

        assert len(post_routes) == 1
        assert post_routes[0].metadata["http_method"] == "POST"
        # ``@PostMapping`` with no args under ``/users``: final path is ``/users``.
        assert post_routes[0].metadata["path"] == "/users"

    async def test_controller_stereotype_is_recognised(self, tmp_path):
        """``@Controller`` (view-returning) also counts — it still routes HTTP."""
        src = """
        import org.springframework.stereotype.Controller;
        import org.springframework.web.bind.annotation.GetMapping;

        @Controller
        public class PageController {
            @GetMapping("/home")
            public String home() { return "home"; }
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["home"], class_name="PageController")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "home")

        routes = _spring_routes(chunk)
        assert len(routes) == 1
        assert routes[0].metadata["http_method"] == "GET"
        assert routes[0].metadata["path"] == "/home"

    async def test_all_http_verb_annotations(self, tmp_path):
        """PUT / DELETE / PATCH shortcuts must all resolve to their verbs."""
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class ItemController {
            @PutMapping("/items/{id}")
            public void update() {}

            @DeleteMapping("/items/{id}")
            public void delete() {}

            @PatchMapping("/items/{id}")
            public void patch() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(
            file_path, ["update", "delete", "patch"], class_name="ItemController"
        )

        enriched = await JavaSpringRecognizer().enrich(doc)

        verbs = {
            c.element_name: _spring_routes(c)[0].metadata["http_method"]
            for c in enriched.chunks
            if c.element_type == "method"
        }
        assert verbs == {"update": "PUT", "delete": "DELETE", "patch": "PATCH"}


# ---------------------------------------------------------------------------
# Path composition
# ---------------------------------------------------------------------------


class TestPathComposition:
    """Base path + method path handling — the trickiest part of the
    recognizer, and the most likely to regress.
    """

    async def test_no_base_path_uses_method_path(self, tmp_path):
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class Api {
            @GetMapping("/ping")
            public String ping() { return "pong"; }
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["ping"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "ping")
        assert _spring_routes(chunk)[0].metadata["path"] == "/ping"

    async def test_base_path_without_leading_slash_still_normalised(self, tmp_path):
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("api/v1")
        public class Api {
            @GetMapping("users")
            public void list() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["list"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "list")
        assert _spring_routes(chunk)[0].metadata["path"] == "/api/v1/users"

    async def test_class_level_slash_combines_without_double_slash(self, tmp_path):
        """``@RequestMapping("/")`` on the class combined with
        ``@GetMapping("/x")`` on the method must resolve to ``/x``,
        not the double-slashed ``//x``. Uncommon but valid Spring
        usage — some teams explicitly mark a controller as rooted at
        ``/`` for documentation purposes.
        """
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/")
        public class Api {
            @GetMapping("/x")
            public void x() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["x"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "x")
        assert _spring_routes(chunk)[0].metadata["path"] == "/x"

    async def test_root_handler_gets_slash_not_empty_string(self, tmp_path):
        """``@RestController`` with no class-level ``@RequestMapping``
        and ``@PostMapping`` with no args binds to the root ``/``. The
        route metadata must reflect that with an explicit ``/`` rather
        than an empty string — otherwise downstream consumers see a
        malformed ``"POST "`` target.
        """
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class Api {
            @PostMapping
            public void root() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["root"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "root")
        routes = _spring_routes(chunk)
        assert routes[0].metadata["http_method"] == "POST"
        assert routes[0].metadata["path"] == "/"
        assert routes[0].target_name == "POST /"

    async def test_base_path_with_trailing_slash_does_not_double_up(self, tmp_path):
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/api/")
        public class Api {
            @GetMapping("/users")
            public void list() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["list"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "list")
        # ``/api/`` + ``/users`` should collapse to a single slash.
        assert _spring_routes(chunk)[0].metadata["path"] == "/api/users"


# ---------------------------------------------------------------------------
# RequestMapping handling
# ---------------------------------------------------------------------------


class TestRequestMapping:
    """``@RequestMapping`` is the generic form — it has to pull the verb
    out of the ``method=`` argument rather than the annotation name.
    """

    async def test_request_mapping_with_method_arg(self, tmp_path):
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class Api {
            @RequestMapping(value = "/foo", method = RequestMethod.GET)
            public void foo() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["foo"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "foo")
        routes = _spring_routes(chunk)
        assert routes[0].metadata["http_method"] == "GET"
        assert routes[0].metadata["path"] == "/foo"

    async def test_request_mapping_without_method_yields_any(self, tmp_path):
        """A bare ``@RequestMapping("/x")`` matches any verb in Spring — we
        still emit an edge but tag it ``ANY`` so downstream consumers can
        distinguish from a specific verb.
        """
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class Api {
            @RequestMapping("/x")
            public void any() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["any"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "any")
        routes = _spring_routes(chunk)
        assert routes[0].metadata["http_method"] == "ANY"
        assert routes[0].metadata["path"] == "/x"


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


class TestNegativeCases:
    """Classes and methods that should NOT produce Spring edges."""

    async def test_non_spring_class_is_ignored(self, tmp_path):
        """A plain POJO with methods that happen to look like handlers
        (e.g. named ``getUser``) must not get Spring edges.
        """
        src = """
        public class UserService {
            public User getUser(String id) { return null; }
            public void createUser(User u) {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["getUser", "createUser"], class_name="UserService")

        enriched = await JavaSpringRecognizer().enrich(doc)
        for chunk in enriched.chunks:
            assert _spring_routes(chunk) == []

    async def test_controller_method_without_mapping_gets_no_edge(self, tmp_path):
        """Private helpers inside a ``@RestController`` must not be tagged
        as routes.
        """
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class Api {
            @GetMapping("/x")
            public void handler() {}

            private void helper() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["handler", "helper"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)

        handler = next(c for c in enriched.chunks if c.element_name == "handler")
        helper = next(c for c in enriched.chunks if c.element_name == "helper")

        assert len(_spring_routes(handler)) == 1
        assert _spring_routes(helper) == []

    async def test_file_that_does_not_exist_returns_document_unchanged(self, tmp_path):
        """The file_path on the ParsedDocument may point at something that
        has since been deleted (e.g. incremental reindex race). The
        recognizer must degrade gracefully.
        """
        missing = tmp_path / "does_not_exist.java"
        doc = _doc_for(missing, ["foo"], class_name="Missing")

        enriched = await JavaSpringRecognizer().enrich(doc)
        for chunk in enriched.chunks:
            assert _spring_routes(chunk) == []

    async def test_request_mapping_without_stereotype_is_ignored(self, tmp_path):
        """A class with only ``@RequestMapping`` and no
        ``@RestController`` / ``@Controller`` stereotype is not a
        Spring route container. Pins the implementation contract
        (and the module docstring) that class-level
        ``@RequestMapping`` only contributes a base path when
        combined with a stereotype.
        """
        src = """
        import org.springframework.web.bind.annotation.*;

        @RequestMapping("/users")
        public class NotAController {
            @GetMapping("/{id}")
            public void getUser() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["getUser"], class_name="NotAController")

        enriched = await JavaSpringRecognizer().enrich(doc)
        for chunk in enriched.chunks:
            assert _spring_routes(chunk) == []

    async def test_mixed_file_spring_and_pojo_only_enriches_spring(self, tmp_path):
        """A file containing one ``@RestController`` and one plain
        POJO must enrich only the controller's methods. Pins the
        ``iter_children_of_type`` loop behavior: non-Spring class
        declarations are skipped, not misattributed.
        """
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class Api {
            @GetMapping("/x")
            public void handle() {}
        }

        public class Helper {
            public void handle() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        # Two methods named ``handle`` at different lines — Api's at
        # line 6, Helper's at line 11 of the dedented source.
        chunks = [
            ParserChunk(
                content="class Api {...}",
                element_type="class",
                element_name="Api",
                line_start=4,
            ),
            ParserChunk(
                content="handle() {...}",
                element_type="method",
                element_name="handle",
                line_start=6,
            ),
            ParserChunk(
                content="class Helper {...}",
                element_type="class",
                element_name="Helper",
                line_start=10,
            ),
            ParserChunk(
                content="handle() {...}",
                element_type="method",
                element_name="handle",
                line_start=11,
            ),
        ]
        doc = ParsedDocument(
            doc_id=str(file_path),
            file_path=str(file_path),
            chunks=chunks,
            metadata={},
        )

        await JavaSpringRecognizer().enrich(doc)

        api_handle = next(
            c for c in doc.chunks if c.element_name == "handle" and c.line_start == 6
        )
        helper_handle = next(
            c for c in doc.chunks if c.element_name == "handle" and c.line_start == 11
        )

        assert len(_spring_routes(api_handle)) == 1
        assert _spring_routes(api_handle)[0].metadata["path"] == "/x"
        assert _spring_routes(helper_handle) == []


# ---------------------------------------------------------------------------
# Performance pre-filter
# ---------------------------------------------------------------------------


class TestFastPreFilter:
    """Non-Spring Java files must not incur a tree-sitter parse. The
    recognizer runs on every ``.java`` file in the repo, so the no-op
    path has to be cheap — a byte-substring scan is orders of
    magnitude faster than parsing.
    """

    async def test_prefilter_false_positive_still_produces_no_routes(self, tmp_path):
        """The byte-substring pre-filter intentionally triggers on any
        file containing ``springframework`` — including a comment
        mentioning Spring. That's a deliberate trade-off: the filter
        is a fast-path optimization, not a correctness gate. When it
        false-positives, the full tree-sitter parse runs but finds
        no Spring annotations, and the recognizer produces zero
        routes. This pins that contract so a future tightening of
        the filter can't silently flip to dropping edges.
        """
        src = """
        // Originally implemented using org.springframework but later
        // replaced with a plain HttpServlet.
        public class PlainPojo {
            public String getName() { return "pojo"; }
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["getName"], class_name="PlainPojo")

        enriched = await JavaSpringRecognizer().enrich(doc)
        for chunk in enriched.chunks:
            assert _spring_routes(chunk) == []

    async def test_non_spring_file_skips_tree_sitter_parse(self, tmp_path, monkeypatch):
        src = """
        public class PlainPojo {
            private final String name;
            public PlainPojo(String name) { this.name = name; }
            public String getName() { return name; }
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["getName"], class_name="PlainPojo")

        recognizer = JavaSpringRecognizer()
        # Force the parser to raise if called — the pre-filter should
        # make that impossible for a non-Spring file.
        sentinel_parser = type(
            "ExplodeOnParse",
            (),
            {
                "parse": lambda self, src: (_ for _ in ()).throw(
                    AssertionError("should not parse")
                )
            },
        )()
        monkeypatch.setattr(recognizer, "_parser", sentinel_parser)

        enriched = await recognizer.enrich(doc)
        for chunk in enriched.chunks:
            assert _spring_routes(chunk) == []


# ---------------------------------------------------------------------------
# Parser load caching
# ---------------------------------------------------------------------------


class TestParserLoadFailureCached:
    """If the Java grammar isn't installed, the recognizer must cache
    the failure and stop retrying on every call. Otherwise a
    mis-deployed environment gets log-spammed on every enrich.
    """

    async def test_failed_load_is_not_retried(self, tmp_path, monkeypatch):
        """Simulate ``get_parser`` raising, then verify a second
        ``enrich`` does not trigger another import attempt.
        """
        src = """
        import org.springframework.web.bind.annotation.*;
        @RestController
        public class Api {
            @GetMapping("/x")
            public void x() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc1 = _doc_for(file_path, ["x"], class_name="Api")
        doc2 = _doc_for(file_path, ["x"], class_name="Api")

        recognizer = JavaSpringRecognizer()

        call_count = {"n": 0}

        def fail_loader(lang):
            call_count["n"] += 1
            raise ImportError("simulated missing grammar")

        # Patch tree_sitter_language_pack.get_parser at the place the
        # recognizer imports it from — use ``monkeypatch.setitem`` on
        # the module-level cache so the import inside ``_get_parser``
        # resolves to our failing stub.
        import tree_sitter_language_pack

        monkeypatch.setattr(tree_sitter_language_pack, "get_parser", fail_loader)

        await recognizer.enrich(doc1)
        await recognizer.enrich(doc2)

        # Two enrich calls, but only one load attempt — the second
        # short-circuits on ``_parser_load_failed``.
        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Annotation parsing edge cases
# ---------------------------------------------------------------------------


class TestAnnotationEdgeCases:
    """Non-canonical annotation shapes that appear in real codebases."""

    async def test_qualified_annotation_names_resolve(self, tmp_path):
        """``@org.springframework.web.bind.annotation.GetMapping`` must
        resolve the same as ``@GetMapping``. Fully-qualified
        annotations are uncommon but legal Java and show up in code
        that deliberately avoids wildcard imports.
        """
        src = """
        @org.springframework.stereotype.Controller
        @org.springframework.web.bind.annotation.RequestMapping("/api")
        public class Api {
            @org.springframework.web.bind.annotation.GetMapping("/ping")
            public void ping() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["ping"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "ping")
        routes = _spring_routes(chunk)
        assert len(routes) == 1
        assert routes[0].metadata["http_method"] == "GET"
        assert routes[0].metadata["path"] == "/api/ping"

    async def test_named_value_arg_preferred_over_other_string_args(self, tmp_path):
        """``@GetMapping(headers = "X-Foo: 1", value = "/users")`` must
        resolve to ``/users``, not ``"X-Foo: 1"``. A naive
        first-string-literal scan picks the header value; the
        recognizer has to recognise ``value=`` / ``path=`` explicitly.
        """
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class Api {
            @GetMapping(headers = "X-Foo: 1", value = "/users")
            public void list() {}

            @PostMapping(consumes = "application/json", path = "/create")
            public void create() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["list", "create"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)

        list_chunk = next(c for c in enriched.chunks if c.element_name == "list")
        create_chunk = next(c for c in enriched.chunks if c.element_name == "create")

        assert _spring_routes(list_chunk)[0].metadata["path"] == "/users"
        assert _spring_routes(create_chunk)[0].metadata["path"] == "/create"

    async def test_value_array_takes_first_element(self, tmp_path):
        """``value = {"/a", "/b"}`` resolves to ``/a``. Multi-path
        mappings are rare; taking the first literal is a reasonable
        summary and matches Spring's own convention that ``value[0]``
        is the canonical path.
        """
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class Api {
            @GetMapping(value = {"/primary", "/legacy"})
            public void list() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["list"], class_name="Api")

        enriched = await JavaSpringRecognizer().enrich(doc)
        chunk = next(c for c in enriched.chunks if c.element_name == "list")
        assert _spring_routes(chunk)[0].metadata["path"] == "/primary"


# ---------------------------------------------------------------------------
# Multi-class + overload collision
# ---------------------------------------------------------------------------


class TestMethodCollisions:
    """Two classes in the same file can share a method name. Line-number
    matching is what keeps each class's route on its own chunk.
    """

    async def test_same_method_name_across_classes_resolves_by_line(self, tmp_path):
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/users")
        public class UserController {
            @GetMapping("/{id}")
            public void handle() {}
        }

        @RestController
        @RequestMapping("/items")
        public class ItemController {
            @GetMapping("/{id}")
            public void handle() {}
        }
        """
        file_path = _write_java(tmp_path, src)

        # Two chunks, both named ``handle``, at distinct lines. We pin
        # line_start to match the AST so the recognizer can
        # disambiguate. Source indented by 8 spaces, so the handle()
        # declarations sit on lines 7 and 13.
        chunks = [
            ParserChunk(
                content="class UserController {...}",
                element_type="class",
                element_name="UserController",
                line_start=5,
            ),
            ParserChunk(
                content="handle() {...}",
                element_type="method",
                element_name="handle",
                line_start=7,
            ),
            ParserChunk(
                content="class ItemController {...}",
                element_type="class",
                element_name="ItemController",
                line_start=11,
            ),
            ParserChunk(
                content="handle() {...}",
                element_type="method",
                element_name="handle",
                line_start=14,
            ),
        ]
        doc = ParsedDocument(
            doc_id=str(file_path),
            file_path=str(file_path),
            chunks=chunks,
            metadata={},
        )

        await JavaSpringRecognizer().enrich(doc)

        user_handle = next(
            c for c in doc.chunks if c.element_name == "handle" and c.line_start == 7
        )
        item_handle = next(
            c for c in doc.chunks if c.element_name == "handle" and c.line_start == 14
        )

        user_routes = _spring_routes(user_handle)
        item_routes = _spring_routes(item_handle)

        # Each handle() should carry exactly one route, scoped to its
        # own controller's base path.
        assert len(user_routes) == 1
        assert user_routes[0].metadata["path"] == "/users/{id}"
        assert user_routes[0].metadata["controller_class"] == "UserController"

        assert len(item_routes) == 1
        assert item_routes[0].metadata["path"] == "/items/{id}"
        assert item_routes[0].metadata["controller_class"] == "ItemController"


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    """Running the recognizer twice on the same document must not
    duplicate edges. Critical for incremental reindex where a file may
    be re-enriched after a superficial change.
    """

    async def test_second_run_does_not_duplicate_edges(self, tmp_path):
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/users")
        public class UserController {
            @GetMapping("/{id}")
            public void getUser() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        doc = _doc_for(file_path, ["getUser"], class_name="UserController")

        recognizer = JavaSpringRecognizer()
        await recognizer.enrich(doc)
        await recognizer.enrich(doc)  # Second pass — must be a no-op.

        chunk = next(c for c in doc.chunks if c.element_name == "getUser")
        assert len(_spring_routes(chunk)) == 1


# ---------------------------------------------------------------------------
# Grouped-chunk matching (the real unified_code shape)
# ---------------------------------------------------------------------------


class TestFallbackMatching:
    """Pin the name-only fallback path. A per-method chunk lists the
    method both as its primary ``element_name`` and inside its own
    ``symbol_metadata``; a naive dedup bug would double-register the
    chunk and make the fallback's ``len(candidates) == 1`` check
    refuse to attach. The fallback fires whenever the strong
    ``(name, line_start)`` index misses — e.g. line drift between
    the base parser's chunk and the recognizer's fresh tree-sitter
    parse.
    """

    async def test_per_method_chunk_with_line_drift_still_resolves(self, tmp_path):
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/users")
        public class UserController {
            @GetMapping("/{id}")
            public void getUser() {}
        }
        """
        file_path = _write_java(tmp_path, src)

        # Per-method chunk: element_type="method" AND same method in
        # symbol_metadata. Both line numbers deliberately mismatch
        # the AST's to force the name-only fallback.
        per_method = ParserChunk(
            content="getUser() {}",
            element_type="method",
            element_name="getUser",
            line_start=99,
            symbols=["getUser"],
            symbol_metadata={
                "getUser": {"type": "method", "start_line": 99, "end_line": 100},
            },
        )
        doc = ParsedDocument(
            doc_id=str(file_path),
            file_path=str(file_path),
            chunks=[per_method],
            metadata={},
        )

        await JavaSpringRecognizer().enrich(doc)
        routes = _spring_routes(per_method)
        assert len(routes) == 1, (
            "chunk was double-registered in the fallback index "
            "(via both element_name and symbol_metadata), making "
            "len(candidates)==1 false and refusing the attach"
        )
        assert routes[0].metadata["path"] == "/users/{id}"


class TestGroupedChunkMatching:
    """The base ``unified_code`` parser doesn't emit one chunk per
    method. It groups a class and its first N methods into a single
    semantic chunk whose ``element_name`` is typically the class, with
    individual handler names exposed via ``chunk.symbols`` /
    ``chunk.symbol_metadata``. The recognizer has to match on that
    shape too — otherwise it's a no-op on real-world Spring files.
    """

    async def test_grouped_chunk_with_methods_in_symbol_metadata(self, tmp_path):
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        @RequestMapping("/users")
        public class UserController {
            @GetMapping("/{id}")
            public void getUser() {}

            @PostMapping
            public void createUser() {}
        }
        """
        file_path = _write_java(tmp_path, src)

        # Mimic what unified_code actually produces: one class-primary
        # chunk that lists the methods in symbols + symbol_metadata.
        grouped_chunk = ParserChunk(
            content=src,
            element_type="class",
            element_name="UserController",
            line_start=4,
            symbols=["UserController", "getUser", "createUser"],
            symbol_metadata={
                "UserController": {"type": "class", "start_line": 4, "end_line": 11},
                "getUser": {
                    "type": "method",
                    "start_line": 6,
                    "end_line": 7,
                    "parent_class": "UserController",
                },
                "createUser": {
                    "type": "method",
                    "start_line": 9,
                    "end_line": 10,
                    "parent_class": "UserController",
                },
            },
        )
        doc = ParsedDocument(
            doc_id=str(file_path),
            file_path=str(file_path),
            chunks=[grouped_chunk],
            metadata={},
        )

        await JavaSpringRecognizer().enrich(doc)

        # Both handlers' route edges attach to the single grouped
        # chunk, distinguished by ``source_name``.
        routes = _spring_routes(grouped_chunk)
        assert len(routes) == 2
        by_name = {r.source_name: r for r in routes}
        assert by_name["getUser"].metadata == {
            "http_method": "GET",
            "path": "/users/{id}",
            "controller_class": "UserController",
            "framework": "spring",
        }
        assert by_name["createUser"].metadata["http_method"] == "POST"
        assert by_name["createUser"].metadata["path"] == "/users"

    async def test_grouped_chunk_idempotent_across_reruns(self, tmp_path):
        """Re-running the recognizer on the same grouped chunk must
        not double up. Equivalence is keyed on ``source_name`` too
        so two distinct handler edges don't collapse into each other.
        """
        src = """
        import org.springframework.web.bind.annotation.*;

        @RestController
        public class Api {
            @GetMapping("/a")
            public void a() {}

            @GetMapping("/b")
            public void b() {}
        }
        """
        file_path = _write_java(tmp_path, src)
        grouped_chunk = ParserChunk(
            content=src,
            element_type="class",
            element_name="Api",
            line_start=4,
            symbols=["Api", "a", "b"],
            symbol_metadata={
                "Api": {"type": "class", "start_line": 4, "end_line": 11},
                "a": {"type": "method", "start_line": 6, "end_line": 7},
                "b": {"type": "method", "start_line": 9, "end_line": 10},
            },
        )
        doc = ParsedDocument(
            doc_id=str(file_path),
            file_path=str(file_path),
            chunks=[grouped_chunk],
            metadata={},
        )

        recognizer = JavaSpringRecognizer()
        await recognizer.enrich(doc)
        await recognizer.enrich(doc)

        routes = _spring_routes(grouped_chunk)
        source_names = sorted(r.source_name for r in routes)
        assert source_names == ["a", "b"], (
            "Grouped chunk should carry one edge per handler, neither "
            "deduped away nor doubled by the re-run."
        )


# ---------------------------------------------------------------------------
# End-to-end: real ParserChain + unified_code producing real chunks
# ---------------------------------------------------------------------------


class TestEndToEndThroughParserChain:
    """Integration test: run the actual ``ParserChain`` on a Spring
    controller and verify that ``spring_route`` relationships are
    emitted on real-world chunks. The hand-built fixtures in the
    other tests mock the base parser's output shape; this test
    guards against drift between the recognizer's chunk-matching
    assumptions and what ``unified_code`` actually produces.
    """

    async def test_spring_controller_parsed_through_chain_gets_routes(self, tmp_path):
        src = """package com.example;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/users")
public class UserController {
    @GetMapping("/{id}")
    public User getUser(@PathVariable String id) {
        return null;
    }

    @PostMapping
    public User createUser(@RequestBody User u) {
        return u;
    }
}
"""
        file_path = _write_java(tmp_path, src, name="UserController.java")

        from agentic_inquiry.parsers.chain import ParserChain

        chain = ParserChain.from_config()
        parsed = await chain.parse(str(file_path))

        # Collect every spring_route edge across all chunks — don't
        # assume a particular chunk layout (grouped vs per-method).
        all_routes = [
            rel
            for chunk in parsed.chunks
            for rel in chunk.relationships
            if rel.type == "spring_route"
        ]

        # Two handlers → two edges, one per method.
        by_source = {r.source_name: r for r in all_routes}
        assert "getUser" in by_source, (
            "recognizer/base-parser drift: getUser handler has no "
            "spring_route edge after full chain parse"
        )
        assert "createUser" in by_source
        assert by_source["getUser"].metadata["http_method"] == "GET"
        assert by_source["getUser"].metadata["path"] == "/users/{id}"
        assert by_source["createUser"].metadata["http_method"] == "POST"
        assert by_source["createUser"].metadata["path"] == "/users"
        assert by_source["getUser"].target_path == str(file_path)
