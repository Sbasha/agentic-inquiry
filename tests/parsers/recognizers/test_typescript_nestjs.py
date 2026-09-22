"""Tests for :class:`TypeScriptNestJSRecognizer`.

Same fixture pattern as the Spring recognizer tests: inline TypeScript
sources written to tmp files, hand-built :class:`ParsedDocument` /
:class:`ParserChunk` fixtures that mirror the real ``unified_code``
output shape (grouped chunks with ``symbol_metadata``), and one
end-to-end test that runs the actual ``ParserChain`` to guard
against drift between the recognizer's matching assumptions and
what the base parser actually emits.

AST line numbers in the fixtures reflect what tree-sitter reports
for ``method_definition.start_point``, which is the method name
line — not the decorator line. If you edit the source, re-run
``method_node.start_point[0] + 1`` to re-compute.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_vault.parsers.models import (
    ParsedDocument,
    ParserChunk,
    ParserRelationship,
)
from agent_vault.parsers.recognizers.typescript_nestjs import (
    TypeScriptNestJSRecognizer,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_ts(tmp_path: Path, source: str, name: str = "controller.ts") -> Path:
    file_path = tmp_path / name
    file_path.write_text(source)
    return file_path


def _grouped_doc(
    file_path: Path,
    class_name: str,
    methods: dict[str, int],
    class_line_start: int = 1,
) -> ParsedDocument:
    """Build a realistic grouped chunk: one ``class``-primary chunk
    with methods listed in ``symbol_metadata``.

    ``methods`` maps method-name → AST start_line. Mirrors the real
    shape ``unified_code`` produces for small TypeScript files.
    """
    symbol_metadata: dict[str, dict[str, int | str]] = {
        class_name: {"type": "class", "start_line": class_line_start, "end_line": 999},
    }
    for name, line in methods.items():
        symbol_metadata[name] = {
            "type": "method",
            "start_line": line,
            "end_line": line + 1,
        }
    chunk = ParserChunk(
        content=f"class {class_name} {{...}}",
        element_type="class",
        element_name=class_name,
        line_start=class_line_start,
        symbols=[class_name, *methods.keys()],
        symbol_metadata=symbol_metadata,
    )
    return ParsedDocument(
        doc_id=str(file_path),
        file_path=str(file_path),
        chunks=[chunk],
        metadata={},
    )


def _nestjs_routes(chunk: ParserChunk) -> list[ParserRelationship]:
    return [r for r in chunk.relationships if r.type == "nestjs_route"]


# ---------------------------------------------------------------------------
# Basic route extraction
# ---------------------------------------------------------------------------


class TestBasicRouteExtraction:
    """Golden path: ``@Controller`` + ``@Get``/``@Post`` handlers."""

    async def test_controller_with_get_and_post(self, tmp_path):
        src = """
import { Controller, Get, Post } from '@nestjs/common';

@Controller('users')
export class UsersController {
  @Get(':id')
  getUser() {}

  @Post()
  createUser() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            "UsersController",
            {"getUser": 7, "createUser": 10},
            class_line_start=5,
        )

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        chunk = enriched.chunks[0]
        routes = _nestjs_routes(chunk)

        by_name = {r.source_name: r for r in routes}
        assert set(by_name) == {"getUser", "createUser"}

        assert by_name["getUser"].metadata == {
            "http_method": "GET",
            "path": "/users/:id",
            "controller_class": "UsersController",
            "framework": "nestjs",
        }
        # target_path lets downstream graph builders link routes back
        # to source without a separate join.
        assert by_name["getUser"].target_path == str(file_path)

        assert by_name["createUser"].metadata["http_method"] == "POST"
        assert by_name["createUser"].metadata["path"] == "/users"

    async def test_all_http_verb_decorators(self, tmp_path):
        """Every NestJS verb decorator (including ``@All`` → ``ANY``)
        must resolve to the correct HTTP method.
        """
        src = """
import { Controller, Get, Post, Put, Delete, Patch, Options, Head, All } from '@nestjs/common';

@Controller()
export class VerbController {
  @Get('/g')
  g() {}
  @Post('/p')
  p() {}
  @Put('/u')
  u() {}
  @Delete('/d')
  d() {}
  @Patch('/a')
  a() {}
  @Options('/o')
  o() {}
  @Head('/h')
  h() {}
  @All('/w')
  w() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            "VerbController",
            {
                "g": 7,
                "p": 9,
                "u": 11,
                "d": 13,
                "a": 15,
                "o": 17,
                "h": 19,
                "w": 21,
            },
            class_line_start=5,
        )

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])

        verbs = {r.source_name: r.metadata["http_method"] for r in routes}
        assert verbs == {
            "g": "GET",
            "p": "POST",
            "u": "PUT",
            "d": "DELETE",
            "a": "PATCH",
            "o": "OPTIONS",
            "h": "HEAD",
            "w": "ANY",
        }


# ---------------------------------------------------------------------------
# Path composition
# ---------------------------------------------------------------------------


class TestPathComposition:
    async def test_object_form_controller_path_is_extracted(self, tmp_path):
        """``@Controller({ path: 'items', version: '1' })`` — we
        extract only the ``path`` key; the version qualifier is out
        of scope.
        """
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller({ path: 'items', version: '1' })
export class ItemsController {
  @Get(':id')
  getItem() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            "ItemsController",
            {"getItem": 7},
            class_line_start=5,
        )

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])
        assert routes[0].metadata["path"] == "/items/:id"

    async def test_no_controller_args_gives_root_base(self, tmp_path):
        """``@Controller()`` + ``@Get('/ping')`` → ``/ping`` (no
        class-level base path to prepend).
        """
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller()
export class Api {
  @Get('/ping')
  ping() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "Api", {"ping": 7}, class_line_start=5)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        assert _nestjs_routes(enriched.chunks[0])[0].metadata["path"] == "/ping"

    async def test_root_handler_gets_slash_not_empty(self, tmp_path):
        """Empty base + empty method path → ``/``."""
        src = """
import { Controller, Post } from '@nestjs/common';

@Controller()
export class RootApi {
  @Post()
  root() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "RootApi", {"root": 7}, class_line_start=5)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])
        assert routes[0].metadata["path"] == "/"
        assert routes[0].target_name == "POST /"

    async def test_class_level_slash_does_not_double_up(self, tmp_path):
        """``@Controller('/')`` + ``@Get('/x')`` → ``/x`` (not
        ``//x``). Same normalisation as the Spring recognizer.
        """
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller('/')
export class Api {
  @Get('/x')
  x() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "Api", {"x": 7}, class_line_start=5)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        assert _nestjs_routes(enriched.chunks[0])[0].metadata["path"] == "/x"


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


class TestNegativeCases:
    async def test_plain_class_without_controller_ignored(self, tmp_path):
        """A class without any NestJS decorator must not gain route
        edges even if its methods have names that look like HTTP
        handlers.
        """
        src = """
export class UserService {
  getUser() { return null; }
  createUser() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            "UserService",
            {"getUser": 3, "createUser": 4},
            class_line_start=2,
        )

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        assert _nestjs_routes(enriched.chunks[0]) == []

    async def test_controller_methods_without_verb_decorators_ignored(self, tmp_path):
        """Helper methods inside a ``@Controller`` that don't carry
        a verb decorator must not become routes.
        """
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller('api')
export class Api {
  @Get('/x')
  handler() {}

  helper() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            "Api",
            {"handler": 7, "helper": 10},
            class_line_start=5,
        )

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])
        source_names = {r.source_name for r in routes}
        assert source_names == {"handler"}

    async def test_missing_file_returns_doc_unchanged(self, tmp_path):
        missing = tmp_path / "gone.ts"
        doc = _grouped_doc(missing, "Missing", {"foo": 1}, class_line_start=1)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        assert _nestjs_routes(enriched.chunks[0]) == []


# ---------------------------------------------------------------------------
# Class decorator shapes
# ---------------------------------------------------------------------------


class TestClassDecoratorShapes:
    async def test_non_exported_class_also_detected(self, tmp_path):
        """A non-exported ``@Controller class Foo {}`` is still a
        valid NestJS controller (unusual but legal). The decorator
        sits at the top level rather than inside an
        ``export_statement``; the recognizer has to handle both.
        """
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller('x')
class InternalController {
  @Get()
  go() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(
            file_path, "InternalController", {"go": 7}, class_line_start=5
        )

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])
        assert len(routes) == 1
        assert routes[0].metadata["path"] == "/x"

    async def test_qualified_decorator_names_resolve(self, tmp_path):
        """``@common.Controller('x')`` with a qualified member
        expression must resolve the same as bare ``@Controller``.
        """
        src = """
import * as common from '@nestjs/common';

@common.Controller('api')
export class Api {
  @common.Get(':id')
  handle() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "Api", {"handle": 7}, class_line_start=5)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])
        assert len(routes) == 1
        assert routes[0].metadata["http_method"] == "GET"
        assert routes[0].metadata["path"] == "/api/:id"


# ---------------------------------------------------------------------------
# String literal shapes (quotes vs template strings)
# ---------------------------------------------------------------------------


class TestStringLiteralForms:
    """NestJS code in the wild uses single quotes, double quotes, and
    backtick template literals interchangeably for route paths. The
    recognizer must accept all three.
    """

    async def test_double_quoted_path(self, tmp_path):
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller("users")
export class Api {
  @Get(":id")
  getUser() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "Api", {"getUser": 7}, class_line_start=5)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])
        assert routes[0].metadata["path"] == "/users/:id"

    async def test_simple_template_literal_path(self, tmp_path):
        """``@Get(\\`:id\\`)`` with no interpolation resolves the same
        as the quoted form.
        """
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller(`users`)
export class Api {
  @Get(`:id`)
  getUser() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "Api", {"getUser": 7}, class_line_start=5)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])
        assert routes[0].metadata["path"] == "/users/:id"

    async def test_quoted_key_in_controller_options(self, tmp_path):
        """``@Controller({ 'path': 'items' })`` with a quoted key
        (single or double) must resolve the same as the bare-key
        form. Real codebases use quoted keys for consistency with
        JSON-like property styles, or when enforced by a linter
        rule.
        """
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller({ 'path': 'items', "version": '1' })
export class ItemsController {
  @Get(':id')
  getItem() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(
            file_path, "ItemsController", {"getItem": 7}, class_line_start=5
        )

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        assert _nestjs_routes(enriched.chunks[0])[0].metadata["path"] == "/items/:id"

    async def test_path_with_escape_sequence_preserves_content(self, tmp_path):
        """A string literal that contains an escape sequence
        (tree-sitter splits it across ``string_fragment`` +
        ``escape_sequence`` children) must still be read in full.
        Iterating ``string_fragment`` children alone truncates
        after the first fragment — for ``'path\\x2Fprefix'`` that
        would yield ``path`` (dropping the ``\\x2F`` and everything
        after). The implementation has to take the raw source span
        minus the surrounding quotes to survive the split.
        """
        # Raw Python string so the backslash reaches the .ts source
        # verbatim; TS parser sees the escape sequence.
        src = (
            "\n"
            "import { Controller, Get } from '@nestjs/common';\n"
            "\n"
            r"@Controller('path\x2Fprefix')"
            "\n"
            "export class Api {\n"
            "  @Get(':id')\n"
            "  getX() {}\n"
            "}\n"
        )
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "Api", {"getX": 7}, class_line_start=5)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        # Recorded path preserves the source form — the escape
        # sequence is kept verbatim (``\x2F``), not decoded to
        # ``/``. Downstream consumers see what the developer wrote.
        assert (
            _nestjs_routes(enriched.chunks[0])[0].metadata["path"]
            == r"/path\x2Fprefix/:id"
        )

    async def test_literal_in_second_position_still_extracted(self, tmp_path):
        """``@Get(someConst, '/fallback')`` — the literal is in the
        second argument slot, but the recogniser still picks it up.
        This matches the docstring's "any argument position" wording
        and the rationale: if the first arg is a non-literal we
        can't resolve, a literal in a later slot is still more
        useful than emitting a pathless edge.
        """
        src = """
import { Controller, Get } from '@nestjs/common';

const FLAG = Symbol();

@Controller('users')
export class Api {
  @Get(FLAG, '/by-id/:id')
  byId() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "Api", {"byId": 9}, class_line_start=7)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])
        assert routes[0].metadata["path"] == "/users/by-id/:id"

    async def test_interpolated_template_literal_yields_no_path(self, tmp_path):
        """A template with ``${...}`` interpolation is effectively a
        runtime-computed path. Emitting the first string fragment
        alone (``/users/``) would be a broken edge — drop the path
        component instead. The route still registers with an empty
        path so the handler isn't silently lost.
        """
        src = """
import { Controller, Get } from '@nestjs/common';

const prefix = 'users';

@Controller(`${prefix}`)
export class Api {
  @Get(`:id`)
  getUser() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "Api", {"getUser": 9}, class_line_start=7)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(enriched.chunks[0])
        # Base path interpolation → empty; method path is a simple
        # template so it resolves to ``:id``. Final path ``/:id``
        # preserves the handler while signalling the missing prefix.
        assert routes[0].metadata["path"] == "/:id"


# ---------------------------------------------------------------------------
# Fast pre-filter
# ---------------------------------------------------------------------------


class TestFastPreFilter:
    async def test_non_nestjs_file_skips_tree_sitter_parse(self, tmp_path, monkeypatch):
        """A plain TypeScript file with no NestJS markers must skip
        the tree-sitter parse. Pin via a sentinel parser that raises
        on ``.parse()``.
        """
        src = """
export class PlainClass {
  doThing() { return 42; }
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "PlainClass", {"doThing": 3}, class_line_start=2)

        recognizer = TypeScriptNestJSRecognizer()
        sentinel = type(
            "ExplodeOnParse",
            (),
            {
                "parse": lambda self, src: (_ for _ in ()).throw(
                    AssertionError("should not parse")
                )
            },
        )()
        monkeypatch.setattr(recognizer, "_parser", sentinel)

        enriched = await recognizer.enrich(doc)
        assert _nestjs_routes(enriched.chunks[0]) == []

    async def test_controller_suffix_class_without_nestjs_skips_parse(
        self, tmp_path, monkeypatch
    ):
        """A plain TypeScript file with a ``*Controller`` class name but
        no NestJS import must skip the tree-sitter parse. Pins the
        tighter ``@Controller`` (decorator form) marker — a looser
        ``Controller`` substring filter would false-positive on every
        file that conventionally names a controller class without
        actually using NestJS.
        """
        src = """
// A UI-side controller class that has nothing to do with NestJS.
export class DashboardController {
  constructor(private readonly view: View) {}
  render() { this.view.draw(); }
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(
            file_path,
            "DashboardController",
            {"render": 4},
            class_line_start=3,
        )

        recognizer = TypeScriptNestJSRecognizer()
        sentinel = type(
            "ExplodeOnParse",
            (),
            {
                "parse": lambda self, src: (_ for _ in ()).throw(
                    AssertionError("should not parse")
                )
            },
        )()
        monkeypatch.setattr(recognizer, "_parser", sentinel)

        enriched = await recognizer.enrich(doc)
        assert _nestjs_routes(enriched.chunks[0]) == []

    async def test_prefilter_false_positive_still_produces_no_routes(self, tmp_path):
        """A file containing ``@nestjs/`` in a comment but no actual
        decorator code must fall through the full parse and produce
        zero routes. Confirms the pre-filter is an optimization, not
        a correctness gate.
        """
        src = """
// Originally used @nestjs/common but now uses plain Express.
export class PlainService {
  handle() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(file_path, "PlainService", {"handle": 4}, class_line_start=3)

        enriched = await TypeScriptNestJSRecognizer().enrich(doc)
        assert _nestjs_routes(enriched.chunks[0]) == []


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


class TestFallbackMatching:
    """Pin the name-only fallback path. A per-method chunk lists the
    method both as its primary ``element_name`` and inside its own
    ``symbol_metadata``; a naive dedup bug would double-register the
    chunk and make the fallback's ``len(candidates) == 1`` check
    refuse to attach. The fallback fires when the strong
    ``(name, line_start)`` index misses — e.g. when the base
    parser's line numbers drift from the recognizer's tree-sitter
    reparse after whitespace changes, or when a chunk stores
    ``line_start`` in one field and the route computes it from a
    different source.
    """

    async def test_per_method_chunk_with_line_drift_still_resolves(self, tmp_path):
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller('users')
export class UsersController {
  @Get(':id')
  getUser() {}
}
"""
        file_path = _write_ts(tmp_path, src)

        # Per-method chunk: element_type="method" AND the same method
        # appears in symbol_metadata. Line numbers deliberately don't
        # match the AST's (recognizer reads line 7; chunk says 99)
        # to force the name-only fallback path.
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

        await TypeScriptNestJSRecognizer().enrich(doc)
        routes = _nestjs_routes(per_method)
        assert len(routes) == 1, (
            "chunk was double-registered in the fallback index "
            "(via both element_name and symbol_metadata), making "
            "len(candidates)==1 false and refusing the attach"
        )
        assert routes[0].metadata["path"] == "/users/:id"


class TestIdempotence:
    async def test_second_enrich_does_not_duplicate_edges(self, tmp_path):
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller('users')
export class UsersController {
  @Get(':id')
  getUser() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _grouped_doc(
            file_path, "UsersController", {"getUser": 7}, class_line_start=5
        )

        recognizer = TypeScriptNestJSRecognizer()
        await recognizer.enrich(doc)
        await recognizer.enrich(doc)

        routes = _nestjs_routes(doc.chunks[0])
        assert len(routes) == 1


# ---------------------------------------------------------------------------
# Mixed-file: NestJS + plain class
# ---------------------------------------------------------------------------


class TestMixedFile:
    async def test_nestjs_and_plain_class_only_enriches_controller(self, tmp_path):
        """A file with one ``@Controller`` and one plain class must
        only enrich the controller's methods, even when both classes
        advertise the same method name.
        """
        src = """
import { Controller, Get } from '@nestjs/common';

@Controller('api')
export class Api {
  @Get('/x')
  handle() {}
}

export class PlainService {
  handle() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        # Two grouped chunks — one per class.
        api_chunk = ParserChunk(
            content="class Api {...}",
            element_type="class",
            element_name="Api",
            line_start=5,
            symbols=["Api", "handle"],
            symbol_metadata={
                "Api": {"type": "class", "start_line": 5, "end_line": 8},
                "handle": {"type": "method", "start_line": 7, "end_line": 7},
            },
        )
        plain_chunk = ParserChunk(
            content="class PlainService {...}",
            element_type="class",
            element_name="PlainService",
            line_start=10,
            symbols=["PlainService", "handle"],
            symbol_metadata={
                "PlainService": {"type": "class", "start_line": 10, "end_line": 12},
                "handle": {"type": "method", "start_line": 11, "end_line": 11},
            },
        )
        doc = ParsedDocument(
            doc_id=str(file_path),
            file_path=str(file_path),
            chunks=[api_chunk, plain_chunk],
            metadata={},
        )

        await TypeScriptNestJSRecognizer().enrich(doc)

        # Route lands on the Api chunk only, disambiguated by the
        # ``(handle, line=7)`` key that only matches Api's
        # symbol_metadata entry.
        assert len(_nestjs_routes(api_chunk)) == 1
        assert _nestjs_routes(api_chunk)[0].metadata["path"] == "/api/x"
        assert _nestjs_routes(plain_chunk) == []


# ---------------------------------------------------------------------------
# End-to-end through the real ParserChain
# ---------------------------------------------------------------------------


class TestEndToEndThroughParserChain:
    """Run the actual ``ParserChain`` on a real ``.ts`` file and
    assert ``nestjs_route`` edges appear. Guards against drift
    between the recognizer's chunk-matching assumptions and what
    ``unified_code`` actually emits for TypeScript.
    """

    async def test_nestjs_controller_parsed_through_chain_gets_routes(self, tmp_path):
        src = """import { Controller, Get, Post } from '@nestjs/common';

@Controller('users')
export class UsersController {
  @Get(':id')
  getUser(id: string) {
    return null;
  }

  @Post()
  createUser() {
    return {};
  }
}
"""
        file_path = _write_ts(tmp_path, src, name="users.controller.ts")

        from agent_vault.parsers.chain import ParserChain

        chain = ParserChain.from_config()
        parsed = await chain.parse(str(file_path))

        all_routes = [
            rel
            for chunk in parsed.chunks
            for rel in chunk.relationships
            if rel.type == "nestjs_route"
        ]

        by_source = {r.source_name: r for r in all_routes}
        assert "getUser" in by_source, (
            "recognizer/base-parser drift: getUser handler has no "
            "nestjs_route edge after full chain parse"
        )
        assert "createUser" in by_source
        assert by_source["getUser"].metadata["http_method"] == "GET"
        assert by_source["getUser"].metadata["path"] == "/users/:id"
        assert by_source["createUser"].metadata["http_method"] == "POST"
        assert by_source["createUser"].metadata["path"] == "/users"
        assert by_source["getUser"].target_path == str(file_path)
