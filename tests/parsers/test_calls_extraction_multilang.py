"""Regression tests for language-aware ``calls`` relationship extraction.

Issue #179: method-to-method ``calls`` graph edges were never produced for
Java or Rust because ``_extract_call_info`` and ``_find_containing_definition``
were hardcoded to Python's tree-sitter grammar. Python is the passing
baseline (see ``test_relationship_extraction.py``); these fixtures cover the
grammars that regressed or never worked (Java, Rust, Go method calls), plus a
Ruby guard for the field-probing fallback, a C++ de-dup guard, and receiver
(``object``) metadata checks for the multi-candidate accessor fields.
"""

import pytest

from agentic_inquiry.parsers.implementations.unified_code import UnifiedCodeParser

pytestmark = pytest.mark.integration


@pytest.fixture
def parser():
    return UnifiedCodeParser()


async def _calls(parser, file_path):
    """Parse a file and return its ``calls`` relationships."""
    result = await parser.parse(str(file_path))
    calls = [
        rel
        for chunk in result.chunks
        for rel in chunk.relationships
        if rel.type == "calls"
    ]
    # No call target should be an empty string.
    assert all(rel.target_name for rel in calls), "call targets must be non-empty"
    return calls


async def _call_target_names(parser, file_path):
    """Parse a file and return the ``target_name``s of its ``calls`` edges."""
    return [rel.target_name for rel in await _calls(parser, file_path)]


@pytest.mark.asyncio
async def test_java_calls_extracted(parser, tmp_path):
    """Java method invocations become ``calls`` edges (issue #179 fixture)."""
    (tmp_path / "OrderService.java").write_text(
        """package demo;
public class OrderService {
    private final PriceCalculator calc = new PriceCalculator();
    public int total(int qty) {
        int unit = calc.unitPrice();   // cross-file, object=calc -> method
        return applyTax(unit * qty);    // intra-file, no object -> function
    }
    public int applyTax(int amount) { return amount + (amount / 10); }
}
"""
    )
    (tmp_path / "PriceCalculator.java").write_text(
        """package demo;
public class PriceCalculator {
    public int unitPrice() { return base() * 2; }  // intra-file call
    public int base() { return 50; }
}
"""
    )

    order_rels = await _calls(parser, tmp_path / "OrderService.java")
    price_calls = await _call_target_names(parser, tmp_path / "PriceCalculator.java")

    order_calls = [r.target_name for r in order_rels]
    assert "applyTax" in order_calls, order_calls
    assert "unitPrice" in order_calls, order_calls
    assert "base" in price_calls, price_calls

    # Container attribution (the _find_containing_definition_key half of the
    # fix): both calls in OrderService originate from `total`, not the class
    # or some wrong container.
    by_target = {r.target_name: r for r in order_rels}
    assert by_target["applyTax"].source_name == "total", order_rels
    assert by_target["unitPrice"].source_name == "total", order_rels


@pytest.mark.asyncio
async def test_rust_calls_extracted(parser, tmp_path):
    """Rust free-function and method calls become ``calls`` edges."""
    (tmp_path / "calc.rs").write_text(
        """struct PriceCalculator;

impl PriceCalculator {
    fn unit_price(&self) -> i32 { self.base() * 2 }  // method call
    fn base(&self) -> i32 { 50 }
}

fn total() -> i32 {
    let calc = PriceCalculator;
    calc.unit_price() + helper()                     // method + function call
}

fn helper() -> i32 { 1 }
"""
    )

    calls = await _call_target_names(parser, tmp_path / "calc.rs")

    assert "base" in calls, calls
    assert "unit_price" in calls, calls
    assert "helper" in calls, calls


@pytest.mark.asyncio
async def test_ruby_calls_not_regressed(parser, tmp_path):
    """Ruby ``call`` nodes (method/receiver fields, no ``function`` field)
    still extract via the field-probing fallback the fix introduces."""
    (tmp_path / "order.rb").write_text(
        """class OrderService
  def total(qty)
    unit = calc.unit_price
    apply_tax(unit * qty)
  end

  def apply_tax(amount)
    amount + amount / 10
  end
end
"""
    )

    calls = await _call_target_names(parser, tmp_path / "order.rb")

    assert "apply_tax" in calls, calls


@pytest.mark.asyncio
async def test_cpp_calls_not_duplicated(parser, tmp_path):
    """A single C++ method call yields exactly one ``calls`` edge.

    ``cpp.scm`` ships two byte-identical ``@call.method`` patterns, so the
    same call node is captured twice; the collection loop de-dups calls by
    node byte span so this does not become a double edge.
    """
    (tmp_path / "order.cpp").write_text(
        """class Order {
public:
    int total() { return calc.unitPrice(); }
};
"""
    )

    calls = await _calls(parser, tmp_path / "order.cpp")
    unit_price_edges = [r for r in calls if r.target_name == "unitPrice"]
    assert len(unit_price_edges) == 1, [(r.source_name, r.target_name) for r in calls]
    # C++'s field_expression names the receiver `argument` (not Rust's
    # `value`); the accessor map tries both, so the receiver is preserved.
    assert unit_price_edges[0].metadata.get("object") == "calc", unit_price_edges[
        0
    ].metadata


@pytest.mark.asyncio
async def test_go_method_calls_extracted(parser, tmp_path):
    """Go method calls (``selector_expression`` target) become ``calls`` edges.

    Go simple calls always worked (``identifier`` target); method calls hit
    the same failure class as Java/Rust until ``selector_expression`` was
    added to the accessor map.
    """
    (tmp_path / "order.go").write_text(
        """package demo

type Order struct{}

func (o Order) Total() int {
    return o.applyTax() + helper()  // method call + function call
}

func (o Order) applyTax() int { return 5 }

func helper() int { return 1 }
"""
    )

    calls = await _calls(parser, tmp_path / "order.go")
    names = [r.target_name for r in calls]
    assert "applyTax" in names, names  # method call via selector_expression
    assert "helper" in names, names  # simple function call

    method_edge = next(r for r in calls if r.target_name == "applyTax")
    assert method_edge.metadata.get("object") == "o", method_edge.metadata
