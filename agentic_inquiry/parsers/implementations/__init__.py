"""Parser implementations with auto-registration.

This module contains concrete parser implementations that conform to ParserProtocol.
Parsers are automatically registered when this module is imported.
"""

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


def _register_parsers() -> List[str]:
    """Register all available parser implementations.

    Attempts to register each parser with graceful failure handling.
    If a parser fails to register due to missing dependencies, logs
    a warning with installation instructions but continues registering
    other parsers.

    Returns:
        List of successfully registered parser names.
    """
    from agentic_inquiry.parsers.executor import register_parser

    registered: List[str] = []
    failed: List[Tuple[str, str, str]] = []  # (name, error, install_cmd)

    # Try to register UnifiedCodeParser
    try:
        from agentic_inquiry.parsers.implementations.unified_code import (
            UnifiedCodeParser,
        )

        code_parser = UnifiedCodeParser()
        register_parser("unified_code", code_parser)
        registered.append("unified_code")
        logger.info("✓ Registered parser: unified_code")
    except ImportError as e:
        error_msg = str(e)
        install_cmd = "pip install tree-sitter tree-sitter-languages"
        failed.append(("unified_code", error_msg, install_cmd))
        logger.warning("✗ Failed to register unified_code: %s", error_msg)
        logger.warning("  Install dependencies: %s", install_cmd)
    except Exception as e:
        error_msg = str(e)
        failed.append(("unified_code", error_msg, ""))
        logger.warning("✗ Failed to register unified_code: %s", error_msg)

    # Try to register DocumentParser
    try:
        from agentic_inquiry.parsers.implementations.document import DocumentParser

        doc_parser = DocumentParser()
        register_parser("document", doc_parser)
        registered.append("document")
        logger.info("✓ Registered parser: document")
    except ImportError as e:
        error_msg = str(e)
        install_cmd = "pip install unstructured"
        failed.append(("document", error_msg, install_cmd))
        logger.warning("✗ Failed to register document: %s", error_msg)
        logger.warning("  Install dependencies: %s", install_cmd)
    except Exception as e:
        error_msg = str(e)
        failed.append(("document", error_msg, ""))
        logger.warning("✗ Failed to register document: %s", error_msg)

    try:
        from agentic_inquiry.parsers.implementations.salesforce_metadata import (
            SalesforceMetadataParser,
        )

        register_parser("salesforce_metadata", SalesforceMetadataParser())
        registered.append("salesforce_metadata")
        logger.info("✓ Registered parser: salesforce_metadata")
    except Exception as e:
        error_msg = str(e)
        failed.append(("salesforce_metadata", error_msg, ""))
        logger.warning("✗ Failed to register salesforce_metadata: %s", error_msg)

    # Try to register FallbackTextParser as "fallback_text" (no external dependencies)
    try:
        from agentic_inquiry.parsers.implementations.fallback_text import (
            FallbackTextParser,
        )

        text_parser = FallbackTextParser()
        register_parser("fallback_text", text_parser)
        registered.append("fallback_text")
        logger.info("✓ Registered parser: fallback_text")
    except Exception as e:
        error_msg = str(e)
        failed.append(("fallback_text", error_msg, ""))
        logger.warning("✗ Failed to register fallback_text: %s", error_msg)

    # Log summary
    if registered:
        logger.info(
            "Successfully registered %s parser(s): %s",
            len(registered),
            ", ".join(registered),
        )
    else:
        logger.error("No parsers were successfully registered!")

    if failed:
        logger.warning("Failed to register %s parser(s)", len(failed))
        for name, error, install_cmd in failed:
            if install_cmd:
                logger.warning("  %s: %s (install: %s)", name, error, install_cmd)

    return registered


# Auto-register parsers on module import
_registered_parsers = _register_parsers()


__all__ = [
    "_register_parsers",
    "_registered_parsers",
]
