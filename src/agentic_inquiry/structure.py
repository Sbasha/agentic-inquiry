"""Grammar-backed source structure and tokenizer-bounded, original-text chunks."""

from __future__ import annotations

import hashlib
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path

LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".cls": "apex",
    ".trigger": "apex",
}
DEFINITIONS = {
    "python": {"function_definition", "class_definition"},
    "javascript": {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "function_expression",
    },
    "typescript": {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "function_expression",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
    },
    "tsx": {
        "function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "function_expression",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
    },
    "java": {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "method_declaration",
        "constructor_declaration",
    },
    "go": {"function_declaration", "method_declaration", "type_spec"},
    "rust": {
        "function_item",
        "struct_item",
        "enum_item",
        "trait_item",
        "impl_item",
        "type_item",
        "mod_item",
    },
    "c": {
        "function_definition",
        "struct_specifier",
        "enum_specifier",
        "union_specifier",
        "type_definition",
    },
    "cpp": {
        "function_definition",
        "class_specifier",
        "struct_specifier",
        "enum_specifier",
        "namespace_definition",
        "type_definition",
        "alias_declaration",
    },
    "csharp": {
        "class_declaration",
        "interface_declaration",
        "struct_declaration",
        "enum_declaration",
        "record_declaration",
        "method_declaration",
        "constructor_declaration",
        "namespace_declaration",
        "local_function_statement",
    },
    "apex": {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "method_declaration",
        "constructor_declaration",
        "trigger_declaration",
    },
}
CALLS = {
    "call",
    "call_expression",
    "invocation_expression",
    "method_invocation",
    "object_creation_expression",
    "new_expression",
}
IMPORTS = {
    "import_statement",
    "import_from_statement",
    "import_declaration",
    "import_spec",
    "use_declaration",
    "using_directive",
    "preproc_include",
    "extern_crate_declaration",
}
BASES = {
    "superclasses",
    "superclass",
    "super_interfaces",
    "extends_clause",
    "implements_clause",
    "class_heritage",
    "base_class_clause",
    "base_list",
    "trait_bounds",
    "interfaces",
}
IDENTIFIERS = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "namespace_identifier",
}


class StructuralLimitError(ValueError):
    """A source exceeds the configured syntax traversal budget."""


def _text(node, data: bytes) -> str:
    return data[node.start_byte : node.end_byte].decode("utf-8")


def _walk(root, limit: int):
    stack, count = [root], 0
    while stack:
        node = stack.pop()
        count += 1
        if count > limit:
            raise StructuralLimitError("Source exceeds the syntax-node limit")
        yield node
        stack.extend(reversed(node.named_children))


def _name(node):
    named = node.child_by_field_name("name")
    if named is not None:
        return named
    if node.type == "impl_item":
        return node.child_by_field_name("type")
    declarator = node.child_by_field_name("declarator")
    while declarator is not None:
        if declarator.type in IDENTIFIERS:
            return declarator
        nested = declarator.child_by_field_name("declarator")
        if nested is None:
            return next((c for c in declarator.named_children if c.type in IDENTIFIERS), None)
        declarator = nested
    if node.type in {"arrow_function", "function_expression"} and node.parent:
        return node.parent.child_by_field_name("name") or node.parent.child_by_field_name("left")
    return None


def _location(node) -> dict:
    return {
        "kind": "code",
        "byte_start": node.start_byte,
        "byte_end": node.end_byte,
        "line_start": node.start_point.row + 1,
        "line_end": max(
            node.start_point.row + 1, node.end_point.row + int(node.end_point.column > 0)
        ),
        "column_start": node.start_point.column,
        "column_end": node.end_point.column,
    }


def _imports(node, language: str, data: bytes) -> list[str]:
    if language == "go" and node.type == "import_declaration":
        return []  # Each import_spec carries its own exact source path.
    if language == "python" and node.type == "import_statement":
        return [
            _text(child.child_by_field_name("name") or child, data) for child in node.named_children
        ]
    target = (
        node.child_by_field_name("source")
        or node.child_by_field_name("module_name")
        or node.child_by_field_name("path")
        or node.child_by_field_name("argument")
    )
    if target is None:
        target = next(
            (child for child in node.named_children if child.type not in {"modifiers", "alias"}),
            node,
        )
    return [_text(target, data).strip("\"'")]


def _bases(node, data: bytes) -> list[str]:
    if node.type == "argument_list" and node.parent and node.parent.type == "class_definition":
        return [
            _text(child, data) for child in node.named_children if child.type != "keyword_argument"
        ]
    if node.type == "impl_item":
        trait = node.child_by_field_name("trait")
        return [_text(trait, data)] if trait else []
    if node.type not in BASES:
        return []
    children = node.named_children
    if any(child.type in BASES for child in children):
        return []
    if len(children) == 1 and children[0].type == "type_list":
        children = children[0].named_children
    return [
        _text(child, data)
        for child in children
        if child.type not in {"access_specifier", "modifiers"}
    ]


def analyze(
    path: str | Path, data: bytes, *, max_nodes: int = 200000, language: str | None = None
) -> dict:
    """Extract syntax facts; potential runtime bindings stay explicitly unresolved."""
    language = language or LANGUAGES.get(Path(path).suffix.lower())
    if language is not None and language not in DEFINITIONS:
        raise ValueError("Unsupported structural language override")
    text = data.decode("utf-8")
    fallback = {
        "text": text,
        "location": {"kind": "text", "byte_start": 0, "byte_end": len(data)},
        "line_start": 1,
        "line_end": max(1, len(text.splitlines())),
    }
    result = {
        "language": language,
        "symbols": [],
        "relations": [],
        "segments": [fallback],
        "coverage": {"structural": "unsupported", "limitations": []},
    }
    if not language:
        return result
    try:
        from tree_sitter_language_pack import get_parser

        parser = get_parser(language)
        tree = parser.parse(data)
    except (ImportError, LookupError, RuntimeError) as error:
        result["coverage"] = {"structural": "unavailable", "limitations": [type(error).__name__]}
        return result
    result["parser"] = {
        "name": "tree-sitter-language-pack",
        "version": version("tree-sitter-language-pack"),
        "grammar": language,
        "analysis_version": 1,
    }
    if tree.root_node.has_error:
        result["coverage"] = {
            "structural": "invalid",
            "limitations": [
                "Syntax errors; searchable original text retained without relationship claims"
            ],
        }
        return result
    nodes = list(_walk(tree.root_node, max_nodes))
    symbols, by_node, name_spans = [], {}, set()
    for node in nodes:
        if node.type not in DEFINITIONS[language]:
            continue
        name_node = _name(node)
        if name_node is None:
            continue
        name = _text(name_node, data)
        parent = node.parent
        enclosing = None
        while parent:
            if parent.id in by_node:
                enclosing = by_node[parent.id]
                break
            parent = parent.parent
        qualified = f"{enclosing['qualified_name']}.{name}" if enclosing else name
        symbol_id = hashlib.sha256(f"{path}:{node.start_byte}:{qualified}".encode()).hexdigest()[
            :24
        ]
        body = node.child_by_field_name("body")
        signature_end = (
            body.start_byte
            if body
            else min(
                node.end_byte,
                data.find(b"\n", node.start_byte)
                if b"\n" in data[node.start_byte : node.end_byte]
                else node.end_byte,
            )
        )
        symbol = {
            "id": symbol_id,
            "name": name,
            "qualified_name": qualified,
            "kind": node.type,
            "language": language,
            "location": _location(node),
            "signature": data[node.start_byte : signature_end].decode("utf-8").rstrip(),
            "parent_id": enclosing["id"] if enclosing else None,
        }
        symbol.update(
            {
                key: symbol["location"][key]
                for key in ("line_start", "line_end", "byte_start", "byte_end")
            }
        )
        symbols.append(symbol)
        by_node[node.id] = symbol
        name_spans.add((name_node.start_byte, name_node.end_byte))
    relations = []
    for node in nodes:
        kind, target_node = None, None
        targets = []
        if node.type in CALLS:
            kind = "calls"
            target_node = (
                node.child_by_field_name("function")
                or node.child_by_field_name("name")
                or node.child_by_field_name("type")
            )
            if target_node is None and node.named_children:
                target_node = node.named_children[0]
            receiver = node.child_by_field_name("object")
            target = ((_text(receiver, data) + ".") if receiver else "") + (
                _text(target_node, data) if target_node else "<dynamic>"
            )
            targets = [target]
        elif node.type in IMPORTS:
            kind, targets = "imports", _imports(node, language, data)
        elif bases := _bases(node, data):
            kind, targets = "inherits", bases
        elif node.type in IDENTIFIERS and (node.start_byte, node.end_byte) not in name_spans:
            kind, targets = "references", [_text(node, data)]
        if kind is None:
            continue
        parent, enclosing = node, None
        while parent:
            if parent.id in by_node:
                enclosing = by_node[parent.id]
                break
            parent = parent.parent
        for target in targets:
            relation = {
                "kind": kind,
                "source": enclosing["qualified_name"] if enclosing else "<module>",
                "source_symbol": enclosing["id"] if enclosing else None,
                "target": target,
                "target_symbol": None,
                "resolution": "unresolved",
                "resolution_reason": "Static syntax does not establish a unique runtime binding",
                "language": language,
                "location": _location(node),
            }
            relation["line_start"] = relation["location"]["line_start"]
            relation["line_end"] = relation["location"]["line_end"]
            relations.append(relation)
            if kind == "imports":
                relations.append({**relation, "kind": "dependencies"})
    boundaries = sorted(
        {0, len(data), *(s["byte_start"] for s in symbols), *(s["byte_end"] for s in symbols)}
    )
    segments = []
    for start, end in pairwise(boundaries):
        content = data[start:end].decode("utf-8")
        if not content.strip():
            continue
        enclosing = [s for s in symbols if s["byte_start"] <= start and s["byte_end"] >= end]
        enclosing.sort(key=lambda s: (s["byte_start"], -s["byte_end"]))
        line = data[:start].count(b"\n") + 1
        location = {
            "kind": "code",
            "byte_start": start,
            "byte_end": end,
            "line_start": line,
            "line_end": line + content.count("\n") - int(content.endswith("\n")),
            "symbol_id": enclosing[-1]["id"] if enclosing else None,
            "enclosing": [
                {
                    "id": s["id"],
                    "name": s["qualified_name"],
                    "signature": s["signature"],
                    "location": s["location"],
                }
                for s in enclosing
            ],
        }
        segments.append(
            {
                "text": content,
                "location": location,
                "line_start": location["line_start"],
                "line_end": max(line, location["line_end"]),
            }
        )
    result.update(
        symbols=symbols,
        relations=relations,
        segments=segments,
        coverage={
            "structural": "parsed",
            "resolution": "syntax_only",
            "limitations": [
                "References, dispatch and imports remain unresolved until independently matched to source evidence"
            ],
        },
    )
    return result


def chunk_segments(segments: list[dict], tokenizer, max_tokens: int = 480) -> list[dict]:
    """Preserve source slices and locations when splitting by the selected tokenizer."""
    if max_tokens < 1:
        raise ValueError("Token budget must be positive")
    chunks = []
    for segment in segments:
        text, offset = segment["text"], 0
        while offset < len(text):
            end = min(len(text), offset + max_tokens * 12)
            while len(tokenizer.encode(text[offset:end]).ids) > max_tokens:
                end = offset + (end - offset) // 2
                if end == offset:
                    raise ValueError("Tokenizer cannot encode one character within the budget")
            if end < len(text):
                newline = text.rfind("\n", offset, end)
                if newline > offset:
                    end = newline + 1
            content = text[offset:end]
            if content.strip():
                chunk = {
                    **segment,
                    "text": content,
                    "location": dict(segment["location"]),
                    "tokens": len(tokenizer.encode(content).ids),
                }
                location = chunk["location"]
                location["segment_char_start"], location["segment_char_end"] = offset, end
                if "byte_start" in location:
                    start = location["byte_start"] + len(text[:offset].encode("utf-8"))
                    location.update(byte_start=start, byte_end=start + len(content.encode("utf-8")))
                if "line_start" in segment:
                    line = segment["line_start"] + text[:offset].count("\n")
                    chunk.update(
                        line_start=line,
                        line_end=max(
                            line, line + content.count("\n") - int(content.endswith("\n"))
                        ),
                    )
                    if location["kind"] in {"code", "text"}:
                        location.update(line_start=chunk["line_start"], line_end=chunk["line_end"])
                chunks.append(chunk)
            offset = end
    return chunks
