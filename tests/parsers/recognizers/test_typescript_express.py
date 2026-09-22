"""Tests for :class:`TypeScriptExpressRecognizer`.

Express is call-expression based rather than decorator based, so
the fixture shape is a bit different from the Spring / NestJS
tests. Most test cases build a single module-level chunk with
``symbol_metadata`` listing the handler functions, mirroring what
``unified_code`` produces for a typical ``routes.ts`` or
``app.ts`` file where all registration happens at module top level
or inside a ``setupRoutes()`` helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_vault.parsers.models import (
    ParsedDocument,
    ParserChunk,
    ParserRelationship,
)
from agent_vault.parsers.recognizers.typescript_express import (
    TypeScriptExpressRecognizer,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_ts(tmp_path: Path, source: str, name: str = "routes.ts") -> Path:
    file_path = tmp_path / name
    file_path.write_text(source)
    return file_path


def _module_doc(
    file_path: Path,
    source_text: str,
    handlers: dict[str, int],
) -> ParsedDocument:
    """Build a module-level chunk with handler functions in
    ``symbol_metadata``.

    Mirrors what ``unified_code`` produces for a small
    route-registration file: one chunk covering the file, all the
    top-level function declarations listed as sub-symbols.
    """
    symbol_metadata: dict[str, dict[str, int | str]] = {
        name: {"type": "function", "start_line": line, "end_line": line + 1}
        for name, line in handlers.items()
    }
    lines = source_text.count("\n") + 1
    chunk = ParserChunk(
        content=source_text,
        element_type="module",
        element_name="<module>",
        line_start=1,
        line_end=lines,
        symbols=list(handlers.keys()),
        symbol_metadata=symbol_metadata,
    )
    return ParsedDocument(
        doc_id=str(file_path),
        file_path=str(file_path),
        chunks=[chunk],
        metadata={},
    )


def _express_routes(chunk: ParserChunk) -> list[ParserRelationship]:
    return [r for r in chunk.relationships if r.type == "express_route"]


# ---------------------------------------------------------------------------
# Basic route extraction
# ---------------------------------------------------------------------------


class TestBasicRouteExtraction:
    """Golden path: ``app.<verb>('/path', handler)`` registration."""

    async def test_named_handler_attaches_to_handler_chunk(self, tmp_path):
        src = """import express from 'express';

const app = express();

app.get('/users/:id', getUser);
app.post('/users', createUser);

function getUser(req, res) {}
function createUser(req, res) {}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"getUser": 8, "createUser": 9})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        chunk = enriched.chunks[0]
        routes = _express_routes(chunk)

        by_source = {r.source_name: r for r in routes}
        assert set(by_source) == {"getUser", "createUser"}
        assert by_source["getUser"].metadata == {
            "http_method": "GET",
            "path": "/users/:id",
            "receiver": "app",
            "mount_prefix": "",
            "framework": "express",
        }
        assert by_source["getUser"].target_path == str(file_path)
        # TypeScript module-level handler functions are registered
        # as ``function`` entities by ``unified_code``; the route
        # edge's source_type must match so the graph layer's
        # entity-id join (source_type + file + name) resolves.
        assert by_source["getUser"].source_type == "function"
        assert by_source["createUser"].metadata["http_method"] == "POST"
        assert by_source["createUser"].metadata["path"] == "/users"

    async def test_all_http_verbs(self, tmp_path):
        """All eight Express verbs resolve to correct HTTP methods.
        ``app.all()`` emits ``ANY`` (mirrors Spring / NestJS).
        """
        src = """import express from 'express';
const app = express();

app.get('/g', hg);
app.post('/p', hp);
app.put('/u', hu);
app.delete('/d', hd);
app.patch('/a', ha);
app.options('/o', ho);
app.head('/h', hh);
app.all('/w', hw);

function hg(){} function hp(){} function hu(){} function hd(){}
function ha(){} function ho(){} function hh(){} function hw(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(
            file_path,
            src,
            {
                n: i + 14
                for i, n in enumerate(["hg", "hp", "hu", "hd", "ha", "ho", "hh", "hw"])
            },
        )

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        verbs = {r.source_name: r.metadata["http_method"] for r in routes}
        assert verbs == {
            "hg": "GET",
            "hp": "POST",
            "hu": "PUT",
            "hd": "DELETE",
            "ha": "PATCH",
            "ho": "OPTIONS",
            "hh": "HEAD",
            "hw": "ANY",
        }


# ---------------------------------------------------------------------------
# Handler forms
# ---------------------------------------------------------------------------


class TestHandlerForms:
    async def test_arrow_function_handler_falls_back_to_call_site(self, tmp_path):
        """Anonymous arrow handlers attach to the chunk containing
        the registration call (the ``setupRoutes``-style site), since
        the lambda has no name to match.
        """
        src = """import express from 'express';
const app = express();

app.get('/ping', (req, res) => { res.json({ ok: true }); });
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, handlers={})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        assert len(routes) == 1
        # Anonymous handlers carry a call-site line suffix so distinct
        # inline handlers in the same file stay distinct downstream.
        assert routes[0].source_name.startswith("<anonymous>")
        assert routes[0].source_name.endswith("@L4")
        assert routes[0].metadata["path"] == "/ping"

    async def test_middleware_chain_uses_last_arg_as_handler(self, tmp_path):
        """``app.get('/x', middleware1, middleware2, handler)`` — the
        last identifier argument wins.
        """
        src = """import express from 'express';
const app = express();

app.get('/admin', authMiddleware, rateLimit, getAdmin);

function authMiddleware(){} function rateLimit(){} function getAdmin(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(
            file_path,
            src,
            {"authMiddleware": 6, "rateLimit": 6, "getAdmin": 6},
        )

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        assert len(routes) == 1
        assert routes[0].source_name == "getAdmin"

    async def test_member_expression_handler_uses_last_segment(self, tmp_path):
        """``app.get('/x', controllers.getUser)`` — member expression
        handler resolves to the last segment (``getUser``).
        """
        src = """import express from 'express';
import * as controllers from './controllers';

const app = express();

app.get('/users', controllers.getUser);
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"getUser": 99})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        assert len(routes) == 1
        assert routes[0].source_name == "getUser"

    async def test_deep_member_expression_handler_resolves_to_last_segment(
        self, tmp_path
    ):
        """``app.get('/x', controllers.users.getUser)`` — multi-level
        member expression still resolves to the terminal identifier.
        Less common than a single-level ``controllers.getUser`` but
        shows up in codebases that bucket handlers into namespaces.
        """
        src = """import express from 'express';
import * as controllers from './controllers';

const app = express();

app.get('/users', controllers.users.getUser);
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"getUser": 99})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        assert len(routes) == 1
        assert routes[0].source_name == "getUser"

    async def test_multiple_anonymous_handlers_get_distinct_names(self, tmp_path):
        """Two inline arrow handlers in the same file must end up with
        distinct ``source_name`` values. Without the line suffix
        they'd both be ``<anonymous>`` and any downstream graph layer
        that derives ``source_id`` from ``(type, file_path,
        source_name)`` would collapse them onto a single source node,
        losing the ability to distinguish them as separate handlers.
        """
        src = """import express from 'express';
const app = express();

app.get('/ping', (req, res) => { res.send('ok'); });
app.post('/shout', (req, res) => { res.send('hey'); });
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, handlers={})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        assert len(routes) == 2

        names = sorted(r.source_name for r in routes)
        # Both anonymous, but tagged with their own call-site lines.
        assert all(n.startswith("<anonymous>@L") for n in names)
        assert len(set(names)) == 2, (
            "two inline handlers collided on the same source_name — "
            "the line-suffix tagging is not disambiguating them"
        )

    async def test_async_arrow_handler_still_anonymous(self, tmp_path):
        """``async (req, res) => {...}`` parses as ``arrow_function``
        in tree-sitter (same node type as the sync form), so the
        recognizer treats it the same way — anonymous handler,
        attach to the call site chunk.
        """
        src = """import express from 'express';
const app = express();

app.get('/ping', async (req, res) => { await loadThing(); res.send('ok'); });
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, handlers={})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        assert len(routes) == 1
        assert routes[0].source_name.startswith("<anonymous>")
        assert routes[0].metadata["path"] == "/ping"


# ---------------------------------------------------------------------------
# Nested registration
# ---------------------------------------------------------------------------


class TestNestedRegistration:
    async def test_registration_inside_setup_function_still_found(self, tmp_path):
        """Express apps often wrap registrations in a
        ``setupRoutes(app)`` helper. The call-expression walker has
        to descend into function bodies, not just visit top-level
        statements, otherwise routes declared inside the helper
        would be silently dropped.
        """
        src = """import express from 'express';

function getUser(req, res) {}
function createUser(req, res) {}

function setupRoutes(app) {
  app.get('/users/:id', getUser);
  app.post('/users', createUser);
}

const app = express();
setupRoutes(app);
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(
            file_path,
            src,
            {"getUser": 3, "createUser": 4, "setupRoutes": 6},
        )

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        by_source = {r.source_name: r for r in routes}
        assert set(by_source) == {"getUser", "createUser"}
        assert by_source["getUser"].metadata["path"] == "/users/:id"


# ---------------------------------------------------------------------------
# Method chain — documented non-goal
# ---------------------------------------------------------------------------


class TestMethodChainSkipped:
    async def test_route_chain_is_silently_skipped(self, tmp_path):
        """``app.route('/x').get(handler)`` uses a chainable route
        object. The recognizer deliberately skips this form (the
        ``.get`` callee's receiver is a ``call_expression``, not an
        identifier). Test pins the documented non-goal — a future
        change that starts emitting edges for chained forms has to
        update this test too, which surfaces the behaviour shift.
        """
        src = """import express from 'express';
const app = express();

app.route('/users').get(getUser).post(createUser);

function getUser(){}
function createUser(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"getUser": 6, "createUser": 7})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        assert _express_routes(enriched.chunks[0]) == []


# ---------------------------------------------------------------------------
# Router mounting
# ---------------------------------------------------------------------------


class TestRouterMounting:
    async def test_router_routes_get_mount_prefix(self, tmp_path):
        """``app.use('/api/v1', router)`` + ``router.get('/:id', ...)``
        produces a route with path ``/api/v1/:id``.
        """
        src = """import express, { Router } from 'express';

const app = express();
const router = Router();

router.get('/users/:id', getUser);
router.post('/users', createUser);

app.use('/api/v1', router);

function getUser(){}
function createUser(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"getUser": 11, "createUser": 12})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        by_source = {r.source_name: r for r in routes}

        assert by_source["getUser"].metadata["path"] == "/api/v1/users/:id"
        assert by_source["getUser"].metadata["mount_prefix"] == "/api/v1"
        assert by_source["getUser"].metadata["receiver"] == "router"
        assert by_source["createUser"].metadata["path"] == "/api/v1/users"

    async def test_multiple_mounts_of_same_router_first_wins(self, tmp_path):
        """``app.use('/v1', router); app.use('/v2', router);`` — the
        recognizer's mount-table prepass uses ``setdefault``, so the
        first mount seen in source order wins. Documenting this
        behaviour rather than trying to be clever about multi-mounts
        (which would require emitting duplicate route edges, one per
        mount prefix — a different design).
        """
        src = """import express, { Router } from 'express';

const app = express();
const router = Router();

router.get('/users', listUsers);

app.use('/v1', router);
app.use('/v2', router);

function listUsers(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"listUsers": 11})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        assert len(routes) == 1
        # First mount seen (``/v1``) wins — not ``/v2``.
        assert routes[0].metadata["mount_prefix"] == "/v1"
        assert routes[0].metadata["path"] == "/v1/users"

    async def test_unmounted_router_stays_prefix_less(self, tmp_path):
        """A router that's defined but never mounted keeps its raw
        paths (no cross-file mounting resolution in MVP).
        """
        src = """import express, { Router } from 'express';

const router = Router();

router.get('/standalone', handler);

function handler(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"handler": 8})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        assert routes[0].metadata["path"] == "/standalone"
        assert routes[0].metadata["mount_prefix"] == ""

    async def test_app_routes_and_mounted_router_routes_coexist(self, tmp_path):
        """Top-level ``app.get(...)`` routes and mounted router routes
        both appear, with their own prefixes.
        """
        src = """import express, { Router } from 'express';

const app = express();
const router = Router();

app.get('/health', health);
router.get('/:id', getOne);
app.use('/items', router);

function health(){}
function getOne(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"health": 11, "getOne": 12})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(enriched.chunks[0])
        by_source = {r.source_name: r for r in routes}

        assert by_source["health"].metadata["path"] == "/health"
        assert by_source["health"].metadata["mount_prefix"] == ""
        assert by_source["getOne"].metadata["path"] == "/items/:id"
        assert by_source["getOne"].metadata["mount_prefix"] == "/items"


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


class TestNegativeCases:
    async def test_non_verb_method_is_ignored(self, tmp_path):
        """``app.use(...)`` without a router second arg is just
        middleware. It mustn't produce a route edge — it's neither a
        mount nor a handler.
        """
        src = """import express from 'express';
const app = express();

app.use(someMiddleware);

function someMiddleware(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"someMiddleware": 6})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        assert _express_routes(enriched.chunks[0]) == []

    async def test_non_string_path_arg_is_ignored(self, tmp_path):
        """``app.get(PATH_CONST, handler)`` — we can't resolve the
        path statically, so no edge is emitted. Better to drop the
        route than publish one with a variable name as its path.
        """
        src = """import express from 'express';
const PATH = '/users';
const app = express();

app.get(PATH, handler);

function handler(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"handler": 7})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        assert _express_routes(enriched.chunks[0]) == []

    async def test_missing_file_returns_doc_unchanged(self, tmp_path):
        missing = tmp_path / "gone.ts"
        doc = _module_doc(missing, "", {})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        assert _express_routes(enriched.chunks[0]) == []


# ---------------------------------------------------------------------------
# Fast pre-filter
# ---------------------------------------------------------------------------


class TestFastPreFilter:
    async def test_non_express_file_skips_tree_sitter_parse(
        self, tmp_path, monkeypatch
    ):
        """A plain TypeScript file without the ``'express'`` import
        literal must skip the tree-sitter parse.
        """
        src = """export class UserService {
  getUsers() { return []; }
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"getUsers": 2})

        recognizer = TypeScriptExpressRecognizer()
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
        assert _express_routes(enriched.chunks[0]) == []

    async def test_prefilter_false_positive_still_produces_no_routes(self, tmp_path):
        """A file mentioning ``'express'`` in a comment but using no
        verb calls on any receiver falls through the full parse and
        produces zero routes.
        """
        src = """// migrated off 'express' to Fastify
export class Service {
  run() {}
}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"run": 3})

        enriched = await TypeScriptExpressRecognizer().enrich(doc)
        assert _express_routes(enriched.chunks[0]) == []


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


class TestCodeFullFallback:
    """When the base parser produces only a ``code_full`` whole-file
    chunk (e.g. it extracted no structural elements), the recognizer
    must still attach its routes rather than drop them silently.
    Keeping code_full out of the name indices prevents the
    primary/secondary ambiguity, but a final fallback preserves the
    edge.
    """

    async def test_only_code_full_chunk_still_attaches_routes(self, tmp_path):
        src = """import express from 'express';
const app = express();

app.get('/users/:id', getUser);

function getUser(req, res) {}
"""
        file_path = _write_ts(tmp_path, src)
        # Mimic "base parser could not extract structure" — only the
        # code_full sentinel, with ``line_start=-1`` and no real
        # symbols beyond what the whole-file dump contains.
        code_full = ParserChunk(
            content=src,
            element_type="code_full",
            element_name="",
            line_start=-1,
            line_end=-1,
            symbols=["getUser"],
            symbol_metadata={
                "getUser": {"type": "function", "start_line": 6, "end_line": 6},
            },
        )
        doc = ParsedDocument(
            doc_id=str(file_path),
            file_path=str(file_path),
            chunks=[code_full],
            metadata={},
        )

        await TypeScriptExpressRecognizer().enrich(doc)
        routes = _express_routes(code_full)
        assert len(routes) == 1, (
            "only a code_full chunk was available; the recognizer must "
            "attach to it rather than drop the route"
        )
        assert routes[0].source_name == "getUser"
        assert routes[0].metadata["path"] == "/users/:id"


class TestReceiverInDedupKey:
    """Same handler + same path + same verb but different receivers
    are distinct Express routes. Idempotence equivalence has to
    include ``receiver`` so the edges don't collapse across re-runs.
    """

    async def test_same_handler_on_app_and_router_preserves_both_edges(self, tmp_path):
        src = """import express, { Router } from 'express';

const app = express();
const router = Router();

app.get('/users', listUsers);
router.get('/users', listUsers);

function listUsers(req, res) {}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"listUsers": 9})

        recognizer = TypeScriptExpressRecognizer()
        await recognizer.enrich(doc)
        await recognizer.enrich(doc)  # Second pass to exercise dedup.

        routes = _express_routes(doc.chunks[0])
        receivers = sorted(r.metadata["receiver"] for r in routes)
        assert receivers == ["app", "router"], (
            "same handler registered on two different receivers — both "
            "edges must be preserved; dedup keyed on receiver prevents "
            "collapse across re-runs"
        )


class TestIdempotence:
    async def test_second_enrich_does_not_duplicate_edges(self, tmp_path):
        src = """import express from 'express';
const app = express();

app.get('/users/:id', getUser);

function getUser(){}
"""
        file_path = _write_ts(tmp_path, src)
        doc = _module_doc(file_path, src, {"getUser": 6})

        recognizer = TypeScriptExpressRecognizer()
        await recognizer.enrich(doc)
        await recognizer.enrich(doc)

        routes = _express_routes(doc.chunks[0])
        assert len(routes) == 1


# ---------------------------------------------------------------------------
# End-to-end via real ParserChain
# ---------------------------------------------------------------------------


class TestEndToEndThroughParserChain:
    async def test_express_file_parsed_through_chain_gets_routes(self, tmp_path):
        src = """import express, { Router } from 'express';

const app = express();
const router = Router();

function getUser(req: any, res: any) { return null; }
function createUser(req: any, res: any) { return null; }
function removeUser(req: any, res: any) { return null; }

router.delete('/:id', removeUser);
app.use('/api/v1', router);

app.get('/users/:id', getUser);
app.post('/users', createUser);
"""
        file_path = _write_ts(tmp_path, src, name="app.ts")

        from agent_vault.parsers.chain import ParserChain

        chain = ParserChain.from_config()
        parsed = await chain.parse(str(file_path))

        all_routes = [
            rel
            for chunk in parsed.chunks
            for rel in chunk.relationships
            if rel.type == "express_route"
        ]
        by_source = {r.source_name: r for r in all_routes}

        assert "getUser" in by_source
        assert "createUser" in by_source
        assert "removeUser" in by_source
        assert by_source["getUser"].metadata["path"] == "/users/:id"
        assert by_source["createUser"].metadata["path"] == "/users"
        assert by_source["removeUser"].metadata["path"] == "/api/v1/:id"
        assert by_source["removeUser"].metadata["mount_prefix"] == "/api/v1"
        assert by_source["getUser"].target_path == str(file_path)
