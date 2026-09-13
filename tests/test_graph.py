"""Component graph contracts with actual grammars and local embedding substitutes."""

import json

import pytest
from test_store import Embeddings

from agentic_inquiry import graph, store


@pytest.fixture
def indexed(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_embedding_model", lambda *args, **kwargs: Embeddings())
    root, db = tmp_path / "source", tmp_path / "index"
    root.mkdir()

    def prepare(files):
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        result = store.index(root, db)
        assert result["complete"], result
        return root, db

    return prepare


def python_sources():
    return {
        "pkg/__init__.py": '"""Component package."""\n',
        "pkg/ledger.py": "def refund():\n    return 1\n\nclass Account:\n    pass\n",
        "pkg/app.py": "from .ledger import refund as pay, Account\nimport pkg.ledger as ledger\n\ndef process():\n    return pay() + ledger.refund()\n\nclass Customer(Account):\n    pass\n",
        "unrelated.py": "def pay():\n    return 9\n\ndef unrelated():\n    return refund()\n",
    }


def test_python_aliases_cross_file_callers_references_inheritance_and_citations(indexed):
    root, db = indexed(python_sources())
    calls = graph.relations(db, "process", kind="callees")["relations"]
    assert {edge["target"] for edge in calls} == {"pay", "ledger.refund"}
    assert all(edge["resolution"] == "statically_matched" for edge in calls)
    assert all(edge["target_path"] == "pkg/ledger.py" for edge in calls)
    assert all(edge["target_qualified_name"] == "refund" for edge in calls)
    definition = graph.symbols(db, "refund")["symbols"][0]
    callers = graph.relations(db, definition["record_id"], kind="callers")["relations"]
    assert len(callers) == 2
    assert all(edge["source"] == "process" for edge in callers)
    inheritance = graph.relations(db, "Customer", kind="inheritance")["relations"]
    assert inheritance[0]["target_qualified_name"] == "Account"
    references = graph.relations(db, "pay", kind="references")["relations"]
    assert any(edge.get("target_qualified_name") == "refund" for edge in references)
    references_to_definition = graph.relations(db, definition["record_id"], kind="references")[
        "relations"
    ]
    assert len(references_to_definition) == 1
    assert references_to_definition[0]["source"] == "process"
    assert references_to_definition[0]["target"] == "pay"
    assert references_to_definition[0]["target_symbol_record_id"] == definition["record_id"]
    for item in [definition, *calls, *inheritance]:
        assert item["citation"]["id"]
        for evidence in item["evidence"]:
            citation = evidence["citation"]
            result = store.read(db, citation["id"])
            assert result["text"] == evidence["text"]
            assert result["location"] == citation["location"]
            assert result["source_hash"] == citation["source_hash"]
            assert evidence["text"] in (root / item["path"]).read_text()
    assert store.read(db, calls[0]["target_citation"]["id"])["path"] == "pkg/ledger.py"
    unknown = graph.relations(db, "unrelated", kind="callees")["relations"]
    assert unknown[0]["resolution"] == "unresolved"


def test_shadowing_ambiguous_imports_dynamic_receivers_and_decorators_remain_unresolved(indexed):
    files = python_sources()
    files.update(
        {
            "shadow.py": "from pkg.ledger import refund\ndef parameter(refund):\n    return refund()\n\ndef assignment():\n    refund = lambda: 5\n    return refund()\n\ndef receiver(obj):\n    return obj.refund()\n\ndef comprehension(values):\n    return [refund() for refund in values]\n",
            "ambiguous.py": "from pkg.ledger import refund\nfrom unrelated import pay as refund\ndef run():\n    return refund()\n",
            "decorated.py": "def decorator(fn):\n    return fn\n@decorator\ndef decorated():\n    return 1\ndef run():\n    return decorated()\n",
        }
    )
    _, db = indexed(files)
    for path in ("shadow.py", "ambiguous.py", "decorated.py"):
        calls = graph.relations(db, kind="calls", path=path)["relations"]
        assert calls and all(edge["resolution"] == "unresolved" for edge in calls)
    # Scope filters remove target evidence before static matching.
    assert all(
        edge["resolution"] == "unresolved"
        for edge in graph.relations(db, kind="calls", path="pkg/app.py")["relations"]
    )


def test_python_lexical_nested_functions_and_module_import_from_package(indexed):
    _, db = indexed(
        {
            "pkg/__init__.py": '"""Package."""\n',
            "pkg/lib.py": "def work():\n    return 1\n",
            "pkg/main.py": "from . import lib\ndef outer():\n    def inner():\n        return lib.work()\n    return inner()\n",
        }
    )
    calls = graph.relations(db, kind="calls")["relations"]
    assert {edge.get("target_qualified_name") for edge in calls} == {"outer.inner", "work"}
    assert all(edge["resolution"] == "statically_matched" for edge in calls)


def test_javascript_named_namespace_default_exports_and_hidden_exports(indexed):
    _, db = indexed(
        {
            "lib.ts": "export function refund() { return 1; }\nexport class Account {}\nfunction hidden() { return 2; }\nexport default function fallback() { return 3; }\n",
            "app.ts": 'import backup, { refund as pay, Account, hidden } from "./lib";\nimport * as ledger from "./lib";\nexport function run() { return pay() + ledger.refund() + backup() + hidden(); }\nexport class Customer extends Account {}\n',
        }
    )
    calls = {
        edge["target"]: edge for edge in graph.relations(db, "run", kind="callees")["relations"]
    }
    for target, expected in (
        ("pay", "refund"),
        ("ledger.refund", "refund"),
        ("backup", "fallback"),
    ):
        assert calls[target]["resolution"] == "statically_matched", calls[target]
        assert calls[target]["target_qualified_name"] == expected
    assert calls["hidden"]["resolution"] == "unresolved"
    inherited = graph.relations(db, "Customer", kind="inheritance")["relations"]
    assert inherited[0]["target_qualified_name"] == "Account"


def test_javascript_ambiguous_extensions_and_shadowed_names_remain_unresolved(indexed):
    _, db = indexed(
        {
            "lib.js": "export function work() { return 1; }\n",
            "lib.ts": "export function work() { return 2; }\n",
            "main.ts": 'import { work } from "./lib";\nfunction run() { return work(); }\n',
            "shadow.ts": 'import { work } from "./lib.js";\nfunction run(work: () => number) { return work(); }\n',
        }
    )
    assert all(
        edge["resolution"] == "unresolved"
        for edge in graph.relations(db, kind="calls")["relations"]
    )


def test_symbol_and_file_traversals_report_real_cycles_and_bounds(indexed):
    _, db = indexed(
        {
            "a.py": "from b import second\ndef first():\n    return second()\n",
            "b.py": "from a import first\ndef second():\n    return first()\n",
        }
    )
    lineage = graph.traverse(db, "a.py::first", direction="lineage", depth=4)
    assert lineage["mode"] == "symbol" and len(lineage["nodes"]) == 2
    assert lineage["cycles"] and not lineage["truncated"]
    impact = graph.traverse(db, "a.py::first", direction="impact", depth=4)
    assert any(edge["source"] == "second" for edge in impact["relations"])
    files = graph.traverse(db, "a.py", direction="lineage", depth=4)
    assert files["mode"] == "file" and len(files["nodes"]) == 2 and files["cycles"]
    assert graph.traverse(db, "first", max_nodes=1)["truncated"]
    assert graph.traverse(db, "first", max_edges=1)["truncated"]
    assert "depth_bound" in graph.traverse(db, "first", depth=1)["truncation_reasons"]


def test_diamond_dependency_is_not_reported_as_cycle(indexed):
    _, db = indexed(
        {
            "a.py": "import b\nimport c\n",
            "b.py": "import d\n",
            "c.py": "import d\n",
            "d.py": "value = 1\n",
        }
    )
    result = graph.traverse(db, "a.py", direction="lineage", depth=4)
    assert len(result["nodes"]) == 4 and not result["cycles"]


def test_cycle_between_siblings_and_total_output_bound(indexed):
    _, db = indexed(
        {
            "root.py": "import left\nimport right\n",
            "left.py": "import right\n",
            "right.py": "import left\n",
        }
    )
    result = graph.traverse(db, "root.py", direction="lineage", depth=4)
    assert result["cycles"]
    bounded = graph.traverse(db, "root.py", direction="lineage", depth=4, max_output_chars=5000)
    assert len(json.dumps(bounded)) <= 5000
    assert bounded["truncated"] and "output_bound" in bounded["truncation_reasons"]


def test_package_attributes_and_nested_javascript_declarations_block_false_matches(indexed):
    _, db = indexed(
        {
            "pkg/__init__.py": "lib = None\n",
            "pkg/lib.py": "def work():\n    return 1\n",
            "main.py": "from pkg import lib\ndef run():\n    return lib.work()\n",
            "lib.ts": "export function work() { return 1; }\n",
            "main.ts": 'import { work } from "./lib";\nfunction outer() { function work() { return 2; } return work(); }\n',
        }
    )
    calls = graph.relations(db, kind="calls")["relations"]
    assert calls and all(edge["resolution"] == "unresolved" for edge in calls)


def test_stale_sources_keep_indexed_citations_without_current_binding_claims(indexed):
    root, db = indexed(python_sources())
    before = graph.relations(db, "process", kind="callees")["relations"][0]
    (root / "pkg/app.py").write_text("def different():\n    return 4\n")
    assert not graph.relations(db, "process", kind="callees")["relations"]
    historical = graph.relations(db, "process", kind="callees", include_stale=True)
    assert historical["coverage"]["stale_sources"]
    assert all(edge["resolution"] == "unresolved" for edge in historical["relations"])
    assert store.read(db, before["citation"]["id"])["freshness"] == "changed"


def test_detached_or_other_project_sources_cannot_bind(indexed, tmp_path):
    root, db = indexed({"app.py": "from secret import work\ndef run():\n    return work()\n"})
    other = tmp_path / "other"
    other.mkdir()
    (other / "secret.py").write_text("def work():\n    return 9\n")
    lib = store._library(db)
    collection = lib.register(other, name="other", project_id="other-project")
    assert store.index(None, db, collection=collection["id"])["complete"]
    edge = graph.relations(db, "run", kind="callees")["relations"][0]
    assert edge["resolution"] == "unresolved"
    original = next(c for c in lib.collections() if c["root"] == str(root))
    scoped = graph.symbols(db, project=original["project_id"])
    assert all(symbol["project_id"] == original["project_id"] for symbol in scoped["symbols"])


def test_bounds_invalid_inputs_and_empty_navigation(indexed):
    _, db = indexed(python_sources())
    for options in (
        {"direction": "wrong"},
        {"max_nodes": 0},
        {"max_edges": 0},
        {"depth": 11},
        {"timeout": 0},
    ):
        with pytest.raises(ValueError):
            graph.traverse(db, "process", **options)
    with pytest.raises(ValueError):
        graph.relations(db, kind="fictional")
    result = graph.symbols(db, limit=1)
    assert len(result["symbols"]) == 1 and result["truncated"]
    assert graph.symbols(db, max_output_chars=1000)["truncated"]
    snap = graph.snapshot(db, max_records=1)
    assert snap["truncated"] and "snapshot_record_bound" in snap["limitations"]
    empty = graph.traverse(db, "does-not-exist")
    assert not empty["nodes"] and not empty["roots"]
    assert len(json.dumps(empty)) < 5000
