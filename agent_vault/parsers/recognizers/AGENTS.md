# Framework Recognizers

Recognizers are post-processors that enrich ``ParsedDocument`` output
with **framework-specific** semantics the base parsers can't see.
Base parsers (``unified_code``, the document parsers) extract generic
code structure — functions, classes, calls, imports. They deliberately
know nothing about ``@RestController`` or ``@app.get("/x")``. That
knowledge lives here.

## When to add a new recognizer

All four should be true:

1. **Your users actually run the framework.** Not a hypothetical or
   long-tail framework — something that shows up in real onboarded
   codebases.
2. **The framework uses dynamic dispatch** that tree-sitter can't
   resolve statically: decorator-driven route registration,
   reflection-based handler lookup, runtime DI wiring, etc.
3. **The hit rate justifies the cost.** Every applicable recognizer
   runs on every matching file. A recognizer that enriches 2% of
   ``.py`` files across the whole index is a bad trade.
4. **The graph edge has consumer value.** If no downstream skill /
   query uses the new relationship type, don't emit it.

## Design contract

Every recognizer must be:

- **Idempotent.** Running the same recognizer twice on the same
  document must produce identical output. Enforce by deduping in the
  recognizer itself — do not assume the caller runs you once.
- **Additive.** Do not remove, reorder, or overwrite chunks or
  relationships produced by the base parser. Append only. Two
  recognizers for the same file (e.g. Spring + generic Java) must
  never step on each other.
- **Failure-safe.** Exceptions are caught by ``apply_recognizers`` and
  logged at WARNING — the base parse still reaches the indexing
  pipeline. A recognizer that can't handle a file must return the
  document unchanged, not raise.
- **Cheap on the no-op path.** A Python recognizer for
  ``.py`` sees every Python file in the repo. If the file doesn't use
  the framework, bail out fast — ideally before any secondary parse.

## File layout

```
recognizers/
    __init__.py            # exposes the protocol + registry API;
                           #   ``_register_builtin_recognizers`` lists
                           #   what ships in-tree.
    base.py                # Recognizer Protocol + module-level
                           #   registry + ``apply_recognizers``
                           #   dispatcher.
    _tree_sitter_utils.py  # Language-agnostic AST helpers
                           #   (iter_children_of_type,
                           #   identifier_text, last_name_segment,
                           #   ...). Reuse these instead of
                           #   copy-pasting from a recognizer.
    _http_route.py         # ``HTTPRouteRecognizer`` base class for
                           #   every HTTP-route recognizer. Subclass
                           #   and implement ``_extract_routes``;
                           #   base owns pre-filter, parser loading,
                           #   tiered chunk matching, and dedup.
    java_spring.py         # Spring MVC / WebFlux HTTP route edges
                           #   (Java). Subclasses HTTPRouteRecognizer.
    typescript_nestjs.py   # NestJS HTTP route edges (TypeScript).
                           #   Subclasses HTTPRouteRecognizer.
    typescript_express.py  # Express HTTP route edges (TypeScript).
                           #   Subclasses HTTPRouteRecognizer.
    python_fastapi.py      # FastAPI HTTP route edges (Python).
                           #   Subclasses HTTPRouteRecognizer.
    java_spring_di.py      # Spring dependency-injection edges
                           #   (Java) - beans + depends_on. Doesn't
                           #   subclass HTTPRouteRecognizer because
                           #   the edge kinds are different.
    apex_salesforce.py     # Apex trigger / SOQL / Aura / REST edges.
                           #   Standalone (not HTTPRouteRecognizer):
                           #   triggers and SOQL are not HTTP.
    lwc_salesforce.py      # LWC ``@salesforce/apex/Class.method``
                           #   imports as ``salesforce_invokes``.
    {next}.py              # Your new recognizer.
```

One file per recognizer. For HTTP-route recognizers, subclass
``HTTPRouteRecognizer`` and implement ``_extract_routes`` plus a
handful of class attributes (see ``_http_route.py`` docstring for
the full contract). For non-HTTP edge kinds (like DI), write a
standalone recognizer — the shape may not map cleanly onto the
HTTP base.

**Before copying from another recognizer**, check whether the helper
you want belongs in ``_tree_sitter_utils.py``. If it's
language-agnostic (any tree-sitter grammar could need it), push it
there. If it's framework-specific (Spring annotation argument
parsing), keep it in the recognizer's own module.

## Relationship naming

Recognizer-emitted relationships should be **framework-prefixed** so
that graph consumers can filter / weight them without needing to know
about the recognizer:

- ``spring_route`` — Spring HTTP route (Java)
- ``spring_di_bean`` — Spring bean provider (class stereotype or
  ``@Bean`` method) (Java)
- ``spring_di_depends_on`` — Spring consumer → dependency type
  (Java)
- ``nestjs_route`` — NestJS HTTP route (TypeScript)
- ``express_route`` — Express HTTP route (TypeScript)
- ``fastapi_route`` — FastAPI HTTP route (Python)
- ``django_url`` — Django URL dispatch (Python)
- ``click_command`` — Click CLI command (Python)

Use one relationship type per semantic edge kind, not one per
annotation. ``@GetMapping`` and ``@PostMapping`` both produce
``spring_route`` — the verb goes in ``metadata.http_method``.

## Testing

At minimum, the recognizer test file must cover:

1. **Golden path** — the framework's canonical shape (e.g. controller
   class + handler methods) produces the expected relationships.
2. **Negative case** — a file using the same language but NOT the
   framework (e.g. a POJO next to a Spring controller) produces no
   framework edges.
3. **Idempotence** — running the recognizer twice on the same
   document produces the same set of relationships, not a doubled
   set.
4. **Graceful degradation** — missing file, malformed source, or
   tree-sitter unavailable returns the document unchanged.

See ``tests/parsers/recognizers/test_java_spring.py`` for a worked
example. Fixtures are inline Java source written to ``tmp_path`` —
keep them small and self-contained.

## Why a separate tree-sitter parse

Most recognizers will want framework-specific AST queries that the
base parser's query file does not capture (annotations, decorators,
metaclass registration). Two options:

1. **Extend the base query file** — couples the core parser to every
   framework we ever support, and forces framework-agnostic consumers
   to pay the extraction cost.
2. **Re-parse inside the recognizer** — a few-millisecond cost on
   files that actually trigger the recognizer, zero cost on
   non-matching files.

Option 2 is the default. Only push into the base query if the
information is genuinely generic (e.g. "captures on an annotation" is
generic; "captures on a ``@RestController``" is not).
