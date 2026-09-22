"""Framework recognizers — post-processing hooks that enrich parser
output with framework-specific semantics.

The base parsers (``unified_code``, document parsers) extract *generic*
code structure: classes, methods, function calls, imports. They have no
awareness of framework conventions like ``@RestController`` marking a
Spring HTTP route handler or ``@app.get("/path")`` marking a FastAPI
endpoint. Recognizers layer that awareness on top.

**How it works.** After ``ParserChain.parse`` returns a ``ParsedDocument``,
the chain calls :func:`apply_recognizers` which routes the document to
every registered recognizer whose ``file_extensions`` set matches the
file. Each recognizer mutates / replaces the document to add
framework-specific relationships and (optionally) metadata.

**Why separate from base parsers.** Frameworks evolve; decorator
signatures change; new frameworks appear. Isolating recognizers:
- keeps base parsers simple and framework-agnostic
- lets framework knowledge be added / removed / versioned independently
- allows users who don't care about framework semantics to opt out
- mirrors how CodeQL / Sourcegraph organise their precise intelligence

**When to add a new recognizer.** Roughly: you've identified a
framework that your users actually run, the framework uses dynamic
dispatch (decorators, reflection, runtime registration) that tree-sitter
can't resolve statically, and the hit rate justifies the per-file cost
of running the recognizer. See ``AGENTS.md`` for the design contract.

Example:

    >>> from agent_vault.parsers.recognizers import (
    ...     register_recognizer, apply_recognizers,
    ... )
    >>> from agent_vault.parsers.recognizers.java_spring import (
    ...     JavaSpringRecognizer,
    ... )
    >>> register_recognizer(JavaSpringRecognizer())
    >>> enriched = await apply_recognizers(parsed_document)
"""

from __future__ import annotations

from agent_vault.parsers.recognizers.base import (
    Recognizer,
    apply_recognizers,
    get_recognizers_for_path,
    list_recognizers,
    register_recognizer,
    unregister_recognizer,
)

__all__ = [
    "Recognizer",
    "apply_recognizers",
    "get_recognizers_for_path",
    "list_recognizers",
    "register_recognizer",
    "unregister_recognizer",
]


def _register_builtin_recognizers() -> None:
    """Register the recognizers shipped in-tree.

    Kept as an explicit function (not top-level imports) so merely
    importing this module does not populate the registry. Called from
    ``ParserChain.__init__`` so every production construction path
    (``__init__``, ``from_config``, ``create_parser_chain``) ends up
    with the built-ins registered.

    Safe to call repeatedly. The per-recognizer name-check avoids
    even constructing a recognizer instance on the second and later
    calls — otherwise every ``ParserChain()`` would pay the cost of
    instantiating (and discarding, via registry de-dup) a fresh
    ``JavaSpringRecognizer`` including its ``threading.Lock``. Tests
    that need a clean registry can achieve one via
    :func:`unregister_recognizer` (see the autouse ``_clean_registry``
    fixture in ``tests/parsers/recognizers/test_registry.py``).
    """
    registered = set(list_recognizers())

    if "java_spring" not in registered:
        from agent_vault.parsers.recognizers.java_spring import (
            JavaSpringRecognizer,
        )

        register_recognizer(JavaSpringRecognizer())

    if "typescript_nestjs" not in registered:
        from agent_vault.parsers.recognizers.typescript_nestjs import (
            TypeScriptNestJSRecognizer,
        )

        register_recognizer(TypeScriptNestJSRecognizer())

    if "typescript_express" not in registered:
        from agent_vault.parsers.recognizers.typescript_express import (
            TypeScriptExpressRecognizer,
        )

        register_recognizer(TypeScriptExpressRecognizer())

    if "java_spring_di" not in registered:
        from agent_vault.parsers.recognizers.java_spring_di import (
            JavaSpringDIRecognizer,
        )

        register_recognizer(JavaSpringDIRecognizer())

    if "python_fastapi" not in registered:
        from agent_vault.parsers.recognizers.python_fastapi import (
            PythonFastAPIRecognizer,
        )

        register_recognizer(PythonFastAPIRecognizer())

    if "apex_salesforce" not in registered:
        from agent_vault.parsers.recognizers.apex_salesforce import (
            ApexSalesforceRecognizer,
        )

        register_recognizer(ApexSalesforceRecognizer())

    if "lwc_salesforce" not in registered:
        from agent_vault.parsers.recognizers.lwc_salesforce import (
            LwcSalesforceRecognizer,
        )

        register_recognizer(LwcSalesforceRecognizer())
