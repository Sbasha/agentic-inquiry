"""Scoped static navigation with indexed citations and explicit resolution bounds."""

from __future__ import annotations

import ast
import json
import posixpath
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from . import store

JS_LANGUAGES = {"javascript", "typescript", "tsx"}
IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\Z")
MAX_BINDING_BYTES = 2 * 1024 * 1024
PROVENANCE = ("collection_id", "project_id", "source_id", "source_version", "source_hash", "path")


def _module_paths(path: str, target: str, language: str) -> list[str]:
    """Candidate local paths without assuming search paths or bundler options."""
    target = target.strip("\"'")
    if language == "python" and re.fullmatch(r"[.\w]+", target):
        dots = len(target) - len(target.lstrip("."))
        base = posixpath.dirname(path) if dots else ""
        for _ in range(max(0, dots - 1)):
            if not base:
                return []
            base = posixpath.dirname(base)
        stem = posixpath.join(base, target.lstrip(".").replace(".", "/"))
        candidates = [stem + ".py", posixpath.join(stem, "__init__.py")]
    elif language in JS_LANGUAGES and target.startswith("."):
        stem = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
        candidates = (
            [stem]
            if Path(stem).suffix
            else [
                stem,
                *(stem + ext for ext in (".js", ".jsx", ".mjs", ".ts", ".tsx")),
                *(stem + "/index" + ext for ext in (".js", ".jsx", ".ts", ".tsx")),
            ]
        )
    else:
        return []
    return [candidate for candidate in candidates if candidate and not candidate.startswith("../")]


def _target_module(info: dict, target: str, modules: dict) -> dict | None:
    matches = [
        modules[(info["collection_id"], path)]
        for path in _module_paths(info["path"], target, info["language"])
        if (info["collection_id"], path) in modules
        and modules[(info["collection_id"], path)]["freshness"] == "current"
    ]
    return matches[0] if len(matches) == 1 else None


def _evidence(item: dict, rows: list[dict]) -> None:
    location = item["location"]
    start, end = location.get("byte_start"), location.get("byte_end")
    matches = []
    for row in rows:
        span = json.loads(row["location_json"])
        if start is not None and span.get("byte_start") is not None:
            overlaps = span["byte_start"] < end and span["byte_end"] > start
        else:
            overlaps = (
                row["line_start"] <= item["line_end"] and row["line_end"] >= item["line_start"]
            )
        if overlaps:
            matches.append((row, span))
    matches.sort(key=lambda match: (match[1].get("byte_start", 0), match[0]["id"]))
    evidence = []
    for row, span in matches[:4]:
        citation = {key: row[key] for key in ("id",) + PROVENANCE}
        citation["location"] = span
        evidence.append({"citation": citation, "text": row["text"]})
    item.update(
        evidence=evidence,
        citation=evidence[0]["citation"] if evidence else None,
        evidence_truncated=len(matches) > len(evidence),
        evidence_chunks=len(matches),
    )


class _PythonBindings(ast.NodeVisitor):
    """Lexical declarations; uncertain rebinding blocks a static match."""

    def __init__(self, data: bytes, symbols: list[dict]):
        self.symbols = {symbol["qualified_name"]: symbol for symbol in symbols}
        self.scopes, self.stack, self.unsafe_spans = [], [], []
        self.conditional, self.load_spans = 0, set()
        self.line_offsets = [0]
        for line in data.splitlines(keepends=True):
            self.line_offsets.append(self.line_offsets[-1] + len(line))
        self.visit(ast.parse(data))

    def _span(self, node) -> tuple[int, int]:
        return (
            self.line_offsets[node.lineno - 1] + node.col_offset,
            self.line_offsets[node.end_lineno - 1] + node.end_col_offset,
        )

    def _bind(self, name: str, binding: dict) -> None:
        self.stack[-1]["bindings"][name].append(
            binding if not self.conditional else {"kind": "unknown"}
        )

    def visit_Module(self, node):
        scope = {
            "name": "",
            "kind": "module",
            "span": (0, self.line_offsets[-1]),
            "parent": None,
            "bindings": defaultdict(list),
        }
        self.scopes.append(scope)
        self.stack.append(scope)
        self.generic_visit(node)
        self.stack.pop()

    def _definition(self, node, kind: str) -> None:
        parent = self.stack[-1]
        name = f"{parent['name']}.{node.name}" if parent["name"] else node.name
        symbol = self.symbols.get(name)
        self._bind(
            node.name,
            {"kind": "symbol", "symbol": symbol}
            if symbol and not node.decorator_list
            else {"kind": "unknown"},
        )
        scope = {
            "name": name,
            "kind": kind,
            "span": self._span(node),
            "parent": parent,
            "bindings": defaultdict(list),
        }
        self.scopes.append(scope)
        self.stack.append(scope)
        conditional, self.conditional = self.conditional, 0
        if kind == "function":
            for argument in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                self._bind(argument.arg, {"kind": "unknown"})
            for argument in (node.args.vararg, node.args.kwarg):
                if argument:
                    self._bind(argument.arg, {"kind": "unknown"})
        for child in node.body:
            self.visit(child)
        self.conditional = conditional
        self.stack.pop()

    def visit_FunctionDef(self, node):
        self._definition(node, "function")

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._definition(node, "class")

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._bind(node.id, {"kind": "unknown"})
        elif isinstance(node.ctx, ast.Load):
            self.load_spans.add(self._span(node))

    def visit_Import(self, node):
        for alias in node.names:
            self._bind(
                alias.asname or alias.name.split(".")[0],
                {"kind": "module", "module": alias.name, "prefix": alias.asname or alias.name},
            )

    def visit_ImportFrom(self, node):
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            if alias.name == "*":
                self.stack[-1]["wildcard"] = True
            else:
                self._bind(
                    alias.asname or alias.name,
                    {"kind": "member", "module": module, "member": alias.name},
                )

    def visit_Global(self, node):
        for name in node.names:
            self._bind(name, {"kind": "unknown"})

    visit_Nonlocal = visit_Global

    def visit_ExceptHandler(self, node):
        if node.name:
            self._bind(node.name, {"kind": "unknown"})
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name:
            self._bind(node.name, {"kind": "unknown"})
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node):
        if node.rest:
            self._bind(node.rest, {"kind": "unknown"})
        self.generic_visit(node)

    def visit_Lambda(self, node):
        self.unsafe_spans.append(self._span(node))

    visit_ListComp = visit_Lambda
    visit_SetComp = visit_Lambda
    visit_DictComp = visit_Lambda
    visit_GeneratorExp = visit_Lambda

    def generic_visit(self, node):
        conditional = isinstance(
            node,
            (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match),
        )
        self.conditional += int(conditional)
        super().generic_visit(node)
        self.conditional -= int(conditional)

    def lookup(self, edge: dict, name: str) -> dict | None:
        start, end = edge["location"]["byte_start"], edge["location"]["byte_end"]
        if any(a <= start < b for a, b in self.unsafe_spans):
            return None
        if edge["kind"] == "references" and (start, end) not in self.load_spans:
            return None
        scopes = [scope for scope in self.scopes if scope["span"][0] <= start < scope["span"][1]]
        if not scopes:
            return None
        scope = min(scopes, key=lambda scope: scope["span"][1] - scope["span"][0])
        if edge["kind"] == "inherits" and scope["kind"] == "class":
            scope = scope["parent"]
        inside_function = scope["kind"] == "function"
        while scope:
            if scope.get("wildcard"):
                return None
            bindings = scope["bindings"].get(name, [])
            if bindings:
                return bindings[0] if len(bindings) == 1 else None
            scope = scope["parent"]
            while scope and inside_function and scope["kind"] == "class":
                scope = scope["parent"]
        return None


def _js_bindings(data: bytes, language: str, symbols: list[dict]) -> dict:
    from tree_sitter_language_pack import get_parser

    tree = get_parser(language).parse(data)
    if tree.root_node.has_error:
        return {}
    top = {symbol["name"]: symbol for symbol in symbols if symbol["parent_id"] is None}
    bindings, exports, shadows = defaultdict(list), defaultdict(list), set()
    identifiers, excluded = set(), []

    def text(node):
        return data[node.start_byte : node.end_byte].decode() if node else ""

    def walk(node):
        yield node
        for child in node.named_children:
            yield from walk(child)

    def names(node):
        return (
            {text(child) for child in walk(node) if child.type == "identifier"} if node else set()
        )

    for node in tree.root_node.named_children:
        if node.type == "import_statement":
            excluded.append((node.start_byte, node.end_byte))
            target = text(node.child_by_field_name("source")).strip("\"'")
            clause = next(
                (child for child in node.named_children if child.type == "import_clause"), None
            )
            for child in clause.named_children if clause else []:
                if child.type == "identifier":
                    bindings[text(child)].append(
                        {"kind": "member", "module": target, "member": "default"}
                    )
                elif child.type == "namespace_import":
                    local = next(
                        (part for part in child.named_children if part.type == "identifier"), None
                    )
                    bindings[text(local)].append(
                        {"kind": "module", "module": target, "prefix": text(local)}
                    )
                elif child.type == "named_imports":
                    for specifier in child.named_children:
                        imported = specifier.child_by_field_name("name")
                        local = specifier.child_by_field_name("alias") or imported
                        bindings[text(local)].append(
                            {"kind": "member", "module": target, "member": text(imported)}
                        )
        elif node.type == "export_statement" and node.child_by_field_name("source") is None:
            declaration = node.child_by_field_name("declaration")
            if declaration is not None:
                name = text(declaration.child_by_field_name("name"))
                if name in top:
                    exported = (
                        "default"
                        if any(child.type == "default" for child in node.children)
                        else name
                    )
                    exports[exported].append(top[name])
            for clause in node.named_children:
                if clause.type == "export_clause":
                    for specifier in clause.named_children:
                        local = text(specifier.child_by_field_name("name"))
                        exported = text(specifier.child_by_field_name("alias")) or local
                        if local in top:
                            exports[exported].append(top[local])
    for node in walk(tree.root_node):
        if node.type == "identifier":
            identifiers.add((node.start_byte, node.end_byte))
        if node.type in {"formal_parameters", "catch_clause"}:
            shadows.update(names(node))
        elif node.type in {
            "variable_declarator",
            "assignment_expression",
            "augmented_assignment_expression",
        }:
            shadows.update(
                names(node.child_by_field_name("name") or node.child_by_field_name("left"))
            )
    for name, symbol in top.items():
        bindings[name].append({"kind": "symbol", "symbol": symbol})
    shadows.update(symbol["name"] for symbol in symbols if symbol["parent_id"] is not None)
    return {
        "bindings": bindings,
        "exports": exports,
        "shadows": shadows,
        "identifiers": identifiers,
        "excluded": excluded,
    }


def _export(info: dict, name: str) -> dict | None:
    analysis = info.get("bindings")
    if isinstance(analysis, _PythonBindings):
        bindings = analysis.scopes[0]["bindings"].get(name, [])
        if not analysis.scopes[0].get("wildcard") and len(bindings) == 1:
            return bindings[0].get("symbol") if bindings[0]["kind"] == "symbol" else None
    elif analysis:
        symbols = analysis.get("exports", {}).get(name, [])
        return (
            symbols[0]
            if len(symbols) == 1
            and name not in analysis["shadows"]
            and symbols[0]["name"] not in analysis["shadows"]
            else None
        )
    return None


def _binding_target(edge: dict, info: dict, modules: dict) -> tuple[dict, dict | None] | None:
    target = edge["target"]
    if not IDENTIFIER.fullmatch(target):
        return None
    parts = target.split(".")
    analysis = info.get("bindings")
    if isinstance(analysis, _PythonBindings):
        binding = analysis.lookup(edge, parts[0])
    elif analysis:
        start, end = edge["location"]["byte_start"], edge["location"]["byte_end"]
        if parts[0] in analysis["shadows"] or any(a <= start < b for a, b in analysis["excluded"]):
            return None
        if edge["kind"] == "references" and (start, end) not in analysis["identifiers"]:
            return None
        bindings = analysis["bindings"].get(parts[0], [])
        binding = bindings[0] if len(bindings) == 1 else None
    else:
        return None
    if not binding or binding["kind"] == "unknown":
        return None
    if binding["kind"] == "symbol":
        return (info, binding["symbol"]) if len(parts) == 1 else None
    module = _target_module(info, binding["module"], modules)
    if binding["kind"] == "module":
        prefix = binding["prefix"].split(".")
        if parts[: len(prefix)] != prefix or not module:
            return None
        remainder = parts[len(prefix) :]
        if not remainder:
            return (module, None) if edge["kind"] == "references" else None
        symbol = _export(module, remainder[0]) if len(remainder) == 1 else None
        return (module, symbol) if symbol else None
    symbol = _export(module, binding["member"]) if module else None
    if symbol:
        return (module, symbol) if len(parts) == 1 else None
    if info["language"] == "python":
        if module:
            package_bindings = module.get("bindings")
            if not isinstance(package_bindings, _PythonBindings):
                return None
            package_scope = package_bindings.scopes[0]
            if package_scope.get("wildcard") or package_scope["bindings"].get(binding["member"]):
                return None
        child_target = (
            binding["module"] + ("" if binding["module"].endswith(".") else ".") + binding["member"]
        )
        child = _target_module(info, child_target, modules)
        if child:
            if len(parts) == 1:
                return (child, None) if edge["kind"] == "references" else None
            member = _export(child, parts[1]) if len(parts) == 2 else None
            return (child, member) if member else None
    return None


def snapshot(db_path: Path, *, max_records: int = 20000, timeout: float = 5, **filters) -> dict:
    if not 1 <= max_records <= 100000 or not 0 < timeout <= 30:
        raise ValueError("Snapshot requires records 1-100000 and timeout 0-30 seconds")
    started = time.monotonic()
    lib = store._library(db_path)
    with lib.connection() as conn:
        conn.execute("BEGIN")
        pairs, coverage = store._eligible_rows(lib, conn, **filters)
        versions, sources = defaultdict(list), {}
        for row, source in pairs:
            versions[row["source_version"]].append(row)
            sources[row["source_version"]] = source
        symbols, relations, modules, limitations = [], [], {}, []
        for version, rows in versions.items():
            if time.monotonic() - started >= timeout:
                limitations.append("snapshot_time_bound")
                break
            row, source = rows[0], sources[version]
            info = {key: row[key] for key in PROVENANCE}
            info.update(
                language=row["language"],
                symbols=[],
                freshness=store._freshness(Path(source["root"]), row),
                citation={
                    **{key: row[key] for key in ("id",) + PROVENANCE},
                    "location": json.loads(row["location_json"]),
                },
            )
            if info["freshness"] != "current" and not filters.get("include_stale"):
                coverage["retrieval_complete"] = False
                coverage["stale_sources"].append(
                    {
                        "collection_id": info["collection_id"],
                        "path": info["path"],
                        "freshness": info["freshness"],
                    }
                )
                continue
            modules[(row["collection_id"], row["path"])] = info
            for kind, destination in (("symbols", symbols), ("relations", relations)):
                for record in conn.execute(
                    f"SELECT id,data FROM {kind} WHERE version_id=? ORDER BY id", (version,)
                ):
                    if len(symbols) + len(relations) >= max_records:
                        limitations.append("snapshot_record_bound")
                        break
                    item = json.loads(record["data"])
                    item.update({key: row[key] for key in PROVENANCE})
                    item["freshness"] = info["freshness"]
                    item["record_id"] = record["id"]
                    _evidence(item, rows)
                    destination.append(item)
                    if kind == "symbols":
                        info["symbols"].append(item)
            if info["language"] in JS_LANGUAGES | {"python"}:
                try:
                    data = store._bytes(Path(source["root"]), info["path"])
                    if store._hash(data) != info["source_hash"]:
                        raise ValueError("Source differs from pinned publication")
                    if len(data) > MAX_BINDING_BYTES:
                        raise ValueError("Source exceeds binding analysis byte limit")
                    info["bindings"] = (
                        _PythonBindings(data, info["symbols"])
                        if info["language"] == "python"
                        else _js_bindings(data, info["language"], info["symbols"])
                    )
                except (OSError, ValueError, SyntaxError, RecursionError) as error:
                    info["binding_limitation"] = str(error)
        symbol_records = {(symbol["source_version"], symbol["id"]): symbol for symbol in symbols}
        for edge in relations:
            source_symbol = symbol_records.get((edge["source_version"], edge.get("source_symbol")))
            edge["source_symbol_record_id"] = source_symbol["record_id"] if source_symbol else None
            info = modules[(edge["collection_id"], edge["path"])]
            if time.monotonic() - started >= timeout:
                limitations.append("snapshot_time_bound")
                break
            target = None
            if info["freshness"] != "current":
                edge["resolution_reason"] = "Source differs from the current pinned publication"
                continue
            if edge["kind"] in {"imports", "dependencies"}:
                module = _target_module(info, edge["target"], modules)
                if module:
                    target = module, None
            else:
                target = _binding_target(edge, info, modules)
            if target:
                module, symbol = target
                edge.update(
                    target_source_id=module["source_id"],
                    target_path=module["path"],
                    target_source_version=module["source_version"],
                    target_source_hash=module["source_hash"],
                    target_freshness=module["freshness"],
                    target_symbol=symbol["id"] if symbol else None,
                    target_symbol_record_id=symbol["record_id"] if symbol else None,
                    target_qualified_name=symbol["qualified_name"] if symbol else None,
                    target_citation=symbol["citation"] if symbol else module["citation"],
                    resolution="statically_matched",
                    resolution_reason="Literal local module path and unambiguous lexical declaration match; runtime loading, mutation and dispatch are not proven",
                )
            elif info.get("binding_limitation"):
                edge["resolution_reason"] = info["binding_limitation"]
        coverage["relationship_resolution"] = {
            "statically_matched": sum(
                edge["resolution"] == "statically_matched" for edge in relations
            ),
            "unresolved": sum(edge["resolution"] == "unresolved" for edge in relations),
            "binding_languages": ["python", "javascript", "typescript", "tsx"],
            "limitations": [
                "Other grammars retain syntax evidence with unresolved bindings.",
                "Local static matches do not establish runtime loading or dynamic dispatch.",
                "Relative and repository-root literal modules are considered; runtime search paths, aliases and reexports are not inferred.",
            ],
        }
        return {
            "schema_version": 1,
            "symbols": symbols,
            "relations": relations,
            "sources": [{key: info[key] for key in PROVENANCE} for info in modules.values()],
            "coverage": coverage,
            "truncated": bool(limitations),
            "limitations": sorted(set(limitations)),
            "bounds": {
                "records": max_records,
                "seconds": timeout,
                "binding_bytes_per_source": MAX_BINDING_BYTES,
            },
        }


def _bounded(items: list[dict], limit: int, max_output_chars: int) -> tuple[list[dict], bool]:
    if not 1 <= limit <= 1000 or not 1000 <= max_output_chars <= 2000000:
        raise ValueError("Output requires limit 1-1000 and characters 1000-2000000")
    selected, size = [], 0
    for item in items:
        size += len(json.dumps(item))
        if len(selected) >= limit or size > max_output_chars:
            break
        selected.append(item)
    return selected, len(selected) < len(items)


def symbols(
    db_path: Path, query: str = "", *, limit: int = 100, max_output_chars: int = 200000, **filters
) -> dict:
    snap = snapshot(db_path, **filters)
    matches = [
        symbol
        for symbol in snap["symbols"]
        if not query
        or query.lower() in symbol["qualified_name"].lower()
        or query
        in {symbol["id"], symbol["record_id"], f"{symbol['path']}::{symbol['qualified_name']}"}
    ]
    selected, truncated = _bounded(matches, limit, max_output_chars)
    return {
        "schema_version": 1,
        "symbols": selected,
        "truncated": truncated or snap["truncated"],
        "coverage": snap["coverage"],
        "limitations": snap["limitations"],
    }


def relations(
    db_path: Path,
    query: str = "",
    *,
    kind: str | None = None,
    limit: int = 100,
    max_output_chars: int = 200000,
    **filters,
) -> dict:
    aliases = {"callers": "calls", "callees": "calls", "inheritance": "inherits"}
    if kind == "definitions":
        return symbols(db_path, query, limit=limit, max_output_chars=max_output_chars, **filters)
    if kind not in {None, "calls", "references", "imports", "dependencies", "inherits", *aliases}:
        raise ValueError("Unknown relationship kind")
    snap = snapshot(db_path, **filters)
    selected = []
    for edge in snap["relations"]:
        if kind and edge["kind"] != aliases.get(kind, kind):
            continue
        target_fields = [
            edge["target"],
            edge.get("target_qualified_name"),
            edge.get("target_symbol"),
            edge.get("target_symbol_record_id"),
            f"{edge.get('target_path')}::{edge.get('target_qualified_name')}",
        ]
        source_fields = [
            edge["source"],
            edge.get("source_symbol"),
            edge.get("source_symbol_record_id"),
            f"{edge['path']}::{edge['source']}",
        ]
        fields = (
            target_fields
            if kind in {"callers", "references"}
            else source_fields
            if kind == "callees"
            else target_fields + source_fields + [edge["path"], edge.get("target_path")]
        )
        if not query or any(field is not None and query in str(field) for field in fields):
            selected.append(edge)
    bounded, truncated = _bounded(selected, limit, max_output_chars)
    return {
        "schema_version": 1,
        "relations": bounded,
        "truncated": truncated or snap["truncated"],
        "coverage": snap["coverage"],
        "limitations": snap["limitations"],
    }


def traverse(
    db_path: Path,
    query: str,
    *,
    direction: str = "impact",
    depth: int = 3,
    max_nodes: int = 100,
    max_edges: int = 300,
    timeout: float = 2,
    max_output_chars: int = 200000,
    **filters,
) -> dict:
    if direction not in {"impact", "lineage"}:
        raise ValueError("Traversal direction must be impact or lineage")
    if (
        not 1 <= depth <= 10
        or not 1 <= max_nodes <= 1000
        or not 1 <= max_edges <= 1000
        or not 0 < timeout <= 30
    ):
        raise ValueError("Traversal requires depth 1-10, nodes/edges 1-1000, timeout 0-30 seconds")
    _bounded([], max_edges, max_output_chars)
    if max_output_chars < 5000:
        raise ValueError("Traversal output budget must be at least 5000 characters")
    started = time.monotonic()
    snap = snapshot(db_path, timeout=timeout, **filters)
    files = {source["source_id"]: source for source in snap["sources"]}
    file_roots = {
        source_id for source_id, source in files.items() if query in {source_id, source["path"]}
    }
    symbol_roots = {
        symbol["record_id"]
        for symbol in snap["symbols"]
        if query
        in {
            symbol["id"],
            symbol["record_id"],
            symbol["name"],
            symbol["qualified_name"],
            f"{symbol['path']}::{symbol['qualified_name']}",
        }
    }
    mode = "file" if file_roots else "symbol"
    roots = file_roots if file_roots else symbol_roots
    adjacency, unresolved_by_source = defaultdict(list), defaultdict(list)
    for edge in snap["relations"]:
        source = (
            edge["source_id"]
            if mode == "file"
            else edge.get("source_symbol_record_id") or edge["source_id"]
        )
        target = (
            edge.get("target_source_id")
            if mode == "file"
            else edge.get("target_symbol_record_id") or edge.get("target_source_id")
        )
        if not target:
            unresolved_by_source[source].append(edge)
            continue
        if mode == "file" and source == target:
            continue
        a, b = (target, source) if direction == "impact" else (source, target)
        adjacency[a].append((b, edge))
    queue = deque((root, 0) for root in sorted(roots))
    visited, emitted, found, cycles, revisited, unresolved = set(), set(), [], [], [], []
    reasons, size = list(snap["limitations"]), 0
    while queue:
        node, level = queue.popleft()
        if node in visited:
            continue
        if len(visited) >= max_nodes or time.monotonic() - started >= timeout:
            reasons.append("node_bound" if len(visited) >= max_nodes else "time_bound")
            break
        visited.add(node)
        unresolved.extend(unresolved_by_source.get(node, []))
        if level == depth:
            if adjacency.get(node):
                reasons.append("depth_bound")
            continue
        for target, edge in adjacency.get(node, []):
            if edge["record_id"] not in emitted:
                edge_size = len(json.dumps(edge))
                if len(found) >= max_edges or size + edge_size > max_output_chars:
                    reasons.append("edge_bound" if len(found) >= max_edges else "output_bound")
                    queue.clear()
                    break
                size += edge_size
                found.append(edge)
                emitted.add(edge["record_id"])
            if target in visited:
                revisited.append({"from": node, "to": target})
            else:
                queue.append((target, level + 1))
    # DFS colors distinguish an actual directed cycle from a shared dependency.
    colors = {}
    for root in sorted(visited):
        if colors.get(root):
            continue
        colors[root] = 1
        stack = [(root, iter(adjacency.get(root, [])))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                colors[node] = 2
                stack.pop()
                continue
            target, edge = child
            if target not in visited or edge["record_id"] not in emitted:
                continue
            if colors.get(target) == 1:
                cycles.append({"from": node, "to": target, "via": edge["record_id"]})
            elif not colors.get(target):
                colors[target] = 1
                stack.append((target, iter(adjacency.get(target, []))))
    bounded_unresolved, omitted = _bounded(
        unresolved, max_edges, max(1000, max_output_chars - size)
    )
    if omitted:
        reasons.append("unresolved_output_bound")
    result = {
        "schema_version": 1,
        "direction": direction,
        "mode": mode,
        "roots": sorted(roots),
        "matched_roots": len(roots),
        "ambiguous_roots": len(roots) > 1,
        "nodes": sorted(visited),
        "visited_nodes": len(visited),
        "relations": found,
        "unresolved": bounded_unresolved,
        "cycles": cycles[:max_edges],
        "revisited_nodes": revisited[:max_edges],
        "truncated": bool(reasons),
        "truncation_reasons": sorted(set(reasons)),
        "bounds": {
            "depth": depth,
            "nodes": max_nodes,
            "edges": max_edges,
            "seconds": timeout,
            "output_characters": max_output_chars,
        },
        "coverage": snap["coverage"],
        "limitations": [
            "Static declarations and literal local imports are matched without executing source. Dynamic dispatch, monkeypatching, reexports, configured search paths and unsupported language bindings remain unresolved.",
            "Elapsed-time bounds are checked between source reads and parsing operations; an in-flight local read or parser operation is not forcibly interrupted.",
        ],
    }
    # Drop whole records, never pieces of a source citation, to bound serialized output.
    lists = [
        result[key]
        for key in ("unresolved", "relations", "cycles", "revisited_nodes", "nodes", "roots")
    ]
    lists.extend(value for value in result["coverage"].values() if isinstance(value, list))
    while len(json.dumps(result)) > max_output_chars:
        remaining = next((items for items in lists if items), None)
        if remaining is None:
            raise ValueError("Output budget is smaller than the required response metadata")
        remaining.pop()
        result["truncated"] = True
        if "output_bound" not in result["truncation_reasons"]:
            result["truncation_reasons"].append("output_bound")
    return result
