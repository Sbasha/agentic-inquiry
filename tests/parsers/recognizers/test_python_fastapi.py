"""Tests for :class:`PythonFastAPIRecognizer`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_inquiry.parsers.models import (
    ParsedDocument,
    ParserChunk,
    ParserRelationship,
)
from agentic_inquiry.parsers.recognizers.python_fastapi import (
    PythonFastAPIRecognizer,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_py(tmp_path: Path, source: str, name: str = "routes.py") -> Path:
    file_path = tmp_path / name
    file_path.write_text(source)
    return file_path


def _module_doc(
    file_path: Path,
    source_text: str,
    handlers: dict[str, int],
) -> ParsedDocument:
    """Build a module-level chunk with handler functions in symbol_metadata.

    Mirrors what ``unified_code`` emits for a typical FastAPI file:
    one module chunk with top-level functions indexed in
    ``symbol_metadata``.
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


def _fastapi_routes(chunk: ParserChunk) -> list[ParserRelationship]:
    return [r for r in chunk.relationships if r.type == "fastapi_route"]


def _all_routes(doc: ParsedDocument) -> list[ParserRelationship]:
    return [
        rel
        for chunk in doc.chunks
        for rel in chunk.relationships
        if rel.type == "fastapi_route"
    ]


# ---------------------------------------------------------------------------
# Basic route extraction
# ---------------------------------------------------------------------------


class TestBasicRouteExtraction:
    """Golden path: ``@app.<verb>(path)`` on a def / async def."""

    async def test_app_get_and_post_handlers(self, tmp_path):
        src = """from fastapi import FastAPI

app = FastAPI()

@app.get("/users/{id}")
def get_user(id: int):
    return {}

@app.post("/users")
async def create_user(user):
    return {}
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"get_user": 6, "create_user": 10})

        await PythonFastAPIRecognizer().enrich(doc)
        routes = _all_routes(doc)

        by_source = {r.source_name: r for r in routes}
        assert set(by_source) == {"get_user", "create_user"}

        get = by_source["get_user"]
        assert get.metadata == {
            "http_method": "GET",
            "path": "/users/{id}",
            "receiver": "app",
            "mount_prefix": "",
            "framework": "fastapi",
        }
        assert get.target_path == str(file_path)
        # Top-level Python ``def`` handlers are registered by
        # ``unified_code`` as ``function`` symbols. Edge source_type
        # must match so downstream entity-id joins (which key on
        # source_type + file_path + source_name) actually resolve
        # to the handler's entity rather than dangling.
        assert get.source_type == "function"

        assert by_source["create_user"].metadata["http_method"] == "POST"
        assert by_source["create_user"].metadata["path"] == "/users"

    async def test_all_http_verbs(self, tmp_path):
        """All seven FastAPI verb decorators resolve to correct
        HTTP methods.
        """
        src = """from fastapi import FastAPI
app = FastAPI()

@app.get("/g")
def g(): return {}

@app.post("/p")
def p(): return {}

@app.put("/u")
def u(): return {}

@app.delete("/d")
def d(): return {}

@app.patch("/a")
def a(): return {}

@app.options("/o")
def o(): return {}

@app.head("/h")
def h(): return {}
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(
            file_path,
            src,
            {
                "g": 5,
                "p": 8,
                "u": 11,
                "d": 14,
                "a": 17,
                "o": 20,
                "h": 23,
            },
        )

        await PythonFastAPIRecognizer().enrich(doc)
        routes = _all_routes(doc)
        verbs = {r.source_name: r.metadata["http_method"] for r in routes}
        assert verbs == {
            "g": "GET",
            "p": "POST",
            "u": "PUT",
            "d": "DELETE",
            "a": "PATCH",
            "o": "OPTIONS",
            "h": "HEAD",
        }

    async def test_keyword_path_argument(self, tmp_path):
        """``@app.get(path="/x", include_in_schema=False)`` — path
        passed as a keyword argument. Valid FastAPI usage; we
        recognise it in addition to the positional form.
        """
        src = """from fastapi import FastAPI
app = FastAPI()

@app.get(path="/users/{id}", include_in_schema=False)
def get_user(id: int):
    return {}
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"get_user": 5})

        await PythonFastAPIRecognizer().enrich(doc)
        routes = _all_routes(doc)
        assert len(routes) == 1
        assert routes[0].metadata["path"] == "/users/{id}"
        assert routes[0].metadata["http_method"] == "GET"

    async def test_async_handler_same_as_sync(self, tmp_path):
        """``async def`` handlers produce identical edges to the sync
        form — FastAPI treats both interchangeably and tree-sitter
        parses ``async def`` as a ``function_definition`` with an
        ``async`` modifier child.
        """
        src = """from fastapi import FastAPI
app = FastAPI()

@app.get("/ping")
async def ping():
    return {"ok": True}
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"ping": 5})

        await PythonFastAPIRecognizer().enrich(doc)
        routes = _all_routes(doc)
        assert len(routes) == 1
        assert routes[0].source_name == "ping"
        assert routes[0].metadata["path"] == "/ping"


# ---------------------------------------------------------------------------
# Router prefix + include_router mounting
# ---------------------------------------------------------------------------


class TestRouterMounting:
    async def test_api_router_prefix_applied(self, tmp_path):
        """``APIRouter(prefix="/api/v1")`` means every route on that
        router gets the prefix prepended, whether or not it's later
        mounted via ``include_router``.
        """
        src = """from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

@router.get("/items")
def list_items():
    return []

@router.post("/items")
def create_item():
    return {}
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"list_items": 5, "create_item": 9})

        await PythonFastAPIRecognizer().enrich(doc)
        routes = _all_routes(doc)
        by_source = {r.source_name: r for r in routes}
        assert by_source["list_items"].metadata["path"] == "/api/v1/items"
        assert by_source["create_item"].metadata["path"] == "/api/v1/items"
        assert by_source["list_items"].metadata["mount_prefix"] == "/api/v1"

    async def test_include_router_prefix_prepends_router_prefix(self, tmp_path):
        """``app.include_router(router, prefix="/mount")`` combined
        with ``APIRouter(prefix="/api")`` yields
        ``"/mount" + "/api" + handler_path`` — matching FastAPI's
        runtime resolution.
        """
        src = """from fastapi import FastAPI, APIRouter

app = FastAPI()
router = APIRouter(prefix="/inner")

@router.get("/users")
def list_users():
    return []

app.include_router(router, prefix="/outer")
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"list_users": 6})

        await PythonFastAPIRecognizer().enrich(doc)
        routes = _all_routes(doc)
        assert len(routes) == 1
        assert routes[0].metadata["path"] == "/outer/inner/users"
        assert routes[0].metadata["mount_prefix"] == "/outer/inner"

    async def test_include_router_without_prefix_keeps_router_prefix(self, tmp_path):
        """``app.include_router(router)`` with no ``prefix=`` kwarg —
        the router keeps its own ``APIRouter(prefix=)`` value.
        """
        src = """from fastapi import FastAPI, APIRouter

app = FastAPI()
router = APIRouter(prefix="/api/v1")

@router.get("/users")
def list_users():
    return []

app.include_router(router)
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"list_users": 6})

        await PythonFastAPIRecognizer().enrich(doc)
        routes = _all_routes(doc)
        assert len(routes) == 1
        assert routes[0].metadata["path"] == "/api/v1/users"

    async def test_prefix_combination_normalises_trailing_slashes(self, tmp_path):
        """``include_router(prefix="/mount/")`` combined with
        ``APIRouter(prefix="/inner")`` must not produce ``/mount//inner``
        in the stored mount prefix. Plain string concat would have
        left a double slash; using ``join_paths`` for the intermediate
        composition normalises the boundary.
        """
        src = """from fastapi import FastAPI, APIRouter

app = FastAPI()
router = APIRouter(prefix="/inner")

@router.get("/x")
def handler():
    return {}

app.include_router(router, prefix="/mount/")
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"handler": 6})

        await PythonFastAPIRecognizer().enrich(doc)
        routes = _all_routes(doc)
        assert len(routes) == 1
        # No ``//`` anywhere — the final path and the stored
        # ``mount_prefix`` metadata are both well-formed.
        assert "//" not in routes[0].metadata["path"]
        assert "//" not in routes[0].metadata["mount_prefix"]
        assert routes[0].metadata["path"] == "/mount/inner/x"
        assert routes[0].metadata["mount_prefix"] == "/mount/inner"

    async def test_app_and_router_routes_coexist(self, tmp_path):
        """Top-level ``@app.get`` routes and router-mounted routes
        both appear with their own prefixes.
        """
        src = """from fastapi import FastAPI, APIRouter

app = FastAPI()
router = APIRouter(prefix="/items")

@app.get("/health")
def health():
    return {"ok": True}

@router.get("/{id}")
def get_item(id: int):
    return {}

app.include_router(router)
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"health": 6, "get_item": 10})

        await PythonFastAPIRecognizer().enrich(doc)
        routes = _all_routes(doc)
        by_source = {r.source_name: r for r in routes}
        assert by_source["health"].metadata["path"] == "/health"
        assert by_source["health"].metadata["receiver"] == "app"
        assert by_source["get_item"].metadata["path"] == "/items/{id}"
        assert by_source["get_item"].metadata["receiver"] == "router"


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


class TestNegativeCases:
    async def test_non_fastapi_file_produces_no_edges(self, tmp_path):
        """Regular Python file with no FastAPI imports or decorators.
        No edges, even if method names look HTTP-ish.
        """
        src = """class UserService:
    def get_user(self, id):
        return None

    def create_user(self, user):
        pass
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"get_user": 2, "create_user": 5})

        await PythonFastAPIRecognizer().enrich(doc)
        assert _all_routes(doc) == []

    async def test_non_string_path_arg_ignored(self, tmp_path):
        """``@app.get(PATH_CONSTANT)`` — we can't resolve the path at
        parse time. Drop the route rather than emit a handler with
        a non-path identifier as its target.
        """
        src = """from fastapi import FastAPI
app = FastAPI()

USERS_PATH = "/users"

@app.get(USERS_PATH)
def list_users():
    return []
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"list_users": 7})

        await PythonFastAPIRecognizer().enrich(doc)
        assert _all_routes(doc) == []

    async def test_fstring_path_produces_no_route(self, tmp_path):
        """f-strings are runtime-composed. Emitting a path based on
        one fragment would be silently wrong; drop the route.
        """
        src = """from fastapi import FastAPI
app = FastAPI()

prefix = "users"

@app.get(f"/{prefix}/{{id}}")
def get_user(id: int):
    return {}
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"get_user": 7})

        await PythonFastAPIRecognizer().enrich(doc)
        assert _all_routes(doc) == []

    async def test_non_verb_decorator_ignored(self, tmp_path):
        """``@app.on_event("startup")`` and similar non-routing
        decorators must not emit route edges.
        """
        src = """from fastapi import FastAPI
app = FastAPI()

@app.on_event("startup")
async def startup():
    pass

@app.middleware("http")
async def add_header(request, call_next):
    return None
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"startup": 5, "add_header": 9})

        await PythonFastAPIRecognizer().enrich(doc)
        assert _all_routes(doc) == []

    async def test_missing_file_returns_doc_unchanged(self, tmp_path):
        missing = tmp_path / "gone.py"
        doc = _module_doc(missing, "", {})

        await PythonFastAPIRecognizer().enrich(doc)
        assert _all_routes(doc) == []


# ---------------------------------------------------------------------------
# Fast pre-filter
# ---------------------------------------------------------------------------


class TestFastPreFilter:
    async def test_non_fastapi_file_skips_parse(self, tmp_path, monkeypatch):
        """A plain Python file without any FastAPI markers skips the
        tree-sitter parse entirely.
        """
        src = """def hello():
    return "world"
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"hello": 1})

        recognizer = PythonFastAPIRecognizer()
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

        await recognizer.enrich(doc)
        assert _all_routes(doc) == []


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


class TestIdempotence:
    async def test_second_enrich_does_not_duplicate(self, tmp_path):
        src = """from fastapi import FastAPI
app = FastAPI()

@app.get("/ping")
def ping():
    return {}
"""
        file_path = _write_py(tmp_path, src)
        doc = _module_doc(file_path, src, {"ping": 5})

        recognizer = PythonFastAPIRecognizer()
        await recognizer.enrich(doc)
        await recognizer.enrich(doc)

        assert len(_all_routes(doc)) == 1


# ---------------------------------------------------------------------------
# End-to-end through real ParserChain
# ---------------------------------------------------------------------------


class TestEndToEndThroughParserChain:
    async def test_fastapi_file_parsed_through_chain_gets_routes(self, tmp_path):
        src = """from fastapi import FastAPI, APIRouter

app = FastAPI()
router = APIRouter(prefix="/api/v1")


@router.delete("/{user_id}")
def remove_user(user_id: int):
    return None


app.include_router(router, prefix="/users")


@app.get("/health")
def health():
    return {"ok": True}
"""
        file_path = _write_py(tmp_path, src, name="app.py")

        from agentic_inquiry.parsers.chain import ParserChain

        chain = ParserChain.from_config()
        parsed = await chain.parse(str(file_path))

        all_routes = [
            rel
            for chunk in parsed.chunks
            for rel in chunk.relationships
            if rel.type == "fastapi_route"
        ]
        by_source = {r.source_name: r for r in all_routes}

        assert "health" in by_source
        assert "remove_user" in by_source
        assert by_source["health"].metadata["path"] == "/health"
        assert by_source["remove_user"].metadata["path"] == "/users/api/v1/{user_id}"
        assert by_source["health"].target_path == str(file_path)
