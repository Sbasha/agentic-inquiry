"""Component checks for grammar facts and exact, tokenizer-bounded source spans."""

import pytest
from tokenizers import Tokenizer, models, pre_tokenizers, processors, trainers

from agentic_inquiry.structure import analyze, chunk_segments


@pytest.mark.parametrize(
    ("suffix", "source", "definition", "callee"),
    [
        ("py", "def run():\n    return helper()\n", "run", "helper"),
        ("js", "function run() { return helper(); }", "run", "helper"),
        ("ts", "function run(): number { return helper(); }", "run", "helper"),
        ("tsx", "function run() { helper(); return <div/>; }", "run", "helper"),
        ("java", "class A { void run() { helper(); }}", "run", "helper"),
        ("go", "package a\nfunc run() { helper() }", "run", "helper"),
        ("rs", "fn run() { helper(); }", "run", "helper"),
        ("c", "void run() { helper(); }", "run", "helper"),
        ("cpp", "class A { void run() { helper(); }};", "run", "helper"),
        ("cs", "class A { void Run() { Helper(); }}", "Run", "Helper"),
        ("cls", "public class A { void run() { helper(); }}", "run", "helper"),
    ],
)
def test_required_grammars_expose_definitions_calls_and_exact_spans(
    suffix, source, definition, callee
):
    data = source.encode()
    result = analyze(f"example.{suffix}", data)
    assert result["coverage"]["structural"] == "parsed"
    symbol = next(symbol for symbol in result["symbols"] if symbol["name"] == definition)
    assert definition in data[symbol["byte_start"] : symbol["byte_end"]].decode()
    call = next(edge for edge in result["relations"] if edge["kind"] == "calls")
    assert call["target"] == callee
    assert call["source_symbol"] == symbol["id"]
    assert call["resolution"] == "unresolved"
    assert call["target_symbol"] is None
    for segment in result["segments"]:
        loc = segment["location"]
        assert data[loc["byte_start"] : loc["byte_end"]].decode() == segment["text"]


def test_invalid_code_retains_text_without_invented_symbols():
    data = b"def impossible(\n"
    result = analyze("broken.py", data)
    assert result["coverage"]["structural"] == "invalid"
    assert result["symbols"] == result["relations"] == []
    assert result["segments"][0]["text"] == data.decode()


def test_python_nested_symbols_imports_and_inheritance_are_attributed():
    source = "import a.b as module, other\nfrom .foo import Bar\nclass Child(Bar):\n    def run(self):\n        def inner():\n            return module.helper()\n        return inner()\n"
    result = analyze("sample.py", source.encode())
    assert [symbol["qualified_name"] for symbol in result["symbols"]] == [
        "Child",
        "Child.run",
        "Child.run.inner",
    ]
    assert {edge["target"] for edge in result["relations"] if edge["kind"] == "imports"} == {
        "a.b",
        "other",
        ".foo",
    }
    assert [edge["target"] for edge in result["relations"] if edge["kind"] == "inherits"] == ["Bar"]
    call = next(edge for edge in result["relations"] if edge["target"] == "module.helper")
    assert call["source"] == "Child.run.inner"
    assert call["line_start"] == 6


def test_cpp_header_override_is_explicit():
    result = analyze("widget.h", b"class Widget { public: void run() {} };", language="cpp")
    assert result["language"] == "cpp"
    assert result["coverage"]["structural"] == "parsed"


def test_chunking_keeps_unicode_source_spans_and_enclosing_signatures():
    source = (
        "class Ledger:\n    def calculate(self):\n"
        + "        résumé = 'café'\n" * 80
        + "        return résumé\n"
    )
    data = source.encode()
    tokenizer = Tokenizer(models.BPE(unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.train_from_iterator(
        [source], trainers.BpeTrainer(vocab_size=300, special_tokens=["[UNK]", "[CLS]", "[SEP]"])
    )
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 1), ("[SEP]", 2)]
    )
    segments = analyze("ledger.py", data)["segments"]
    chunks = chunk_segments(segments, tokenizer, max_tokens=30)
    assert len(chunks) > 3
    for chunk in chunks:
        location = chunk["location"]
        assert data[location["byte_start"] : location["byte_end"]].decode() == chunk["text"]
        assert len(tokenizer.encode(chunk["text"]).ids) <= 30
        assert chunk["line_start"] == data[: location["byte_start"]].count(b"\n") + 1
        assert location["enclosing"][0]["name"] == "Ledger"
    assert any(
        "def calculate(self):" in parent["signature"]
        for chunk in chunks
        for parent in chunk["location"]["enclosing"]
    )


def test_chunking_preserves_document_locations_without_fabricated_file_lines():
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    chunks = chunk_segments(
        [
            {
                "text": "One two three four five six",
                "location": {"kind": "pdf", "page": 3, "bbox": [1, 2, 30, 40]},
            }
        ],
        tokenizer,
        max_tokens=2,
    )
    assert len(chunks) >= 3
    for chunk in chunks:
        assert chunk["location"]["page"] == 3
        assert "line_start" not in chunk and "line_end" not in chunk
        assert "line_start" not in chunk["location"]


def test_syntax_node_budget_is_enforced():
    with pytest.raises(ValueError, match="syntax-node limit"):
        analyze("a.py", b"def run():\n    return thing()\n", max_nodes=2)
