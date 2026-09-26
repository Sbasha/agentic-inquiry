"""Parser chain implementation for trying multiple parsers in priority order.

This module provides a ParserChain class that attempts to parse files using
multiple parsers in a specified priority order. The chain tries each parser
sequentially until one succeeds, with support for efficient parser selection
via the optional can_parse method.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from agentic_inquiry.config import Config

if TYPE_CHECKING:
    from agentic_inquiry.events.system import EventSystem
from agentic_inquiry.exceptions import ParsingError
from .executor import (
    ParserProtocol,
    ParsedDocument,
    execute_parser,
    get_parser_instance,
)
from .recognizers import apply_recognizers

# Import implementations to trigger parser registration
from . import implementations  # noqa: F401
from .implementations.fallback_text import FallbackTextParser


logger = logging.getLogger(__name__)


class NoOpEventSystem:
    """Minimal event system that does nothing, for standalone usage."""

    async def emit(self, *args: object, **kwargs: object) -> None:
        """No-op emit method."""
        pass


# Default priority order for parser chain
DEFAULT_PARSER_PRIORITY = [
    "unified_code",  # Try code parser first (handles most source files)
    "salesforce_metadata",  # Salesforce source-format metadata allowlist
    "document",  # Then structured documents (PDF, Office, etc.)
    "fallback_text",  # Finally fallback to text (handles anything)
]


class ParserChain:
    """Chain of parsers that try in sequence until one succeeds.

    The ParserChain attempts to parse files using multiple parsers in a
    specified priority order. It supports efficient parser selection by
    checking the optional can_parse method before attempting to parse.

    Example:
        >>> import asyncio
        >>> from agentic_inquiry.config import Config
        >>> config = Config.load()
        >>> chain = ParserChain(["unified_code", "fallback_text"], config=config)
        >>> doc = asyncio.run(chain.parse("/path/to/file.py"))

        >>> # Use default priority with default config
        >>> chain = create_parser_chain()
        >>> doc = asyncio.run(chain.parse("/path/to/file.py"))
    """

    def __init__(
        self,
        parser_names: Optional[List[str]] = None,
        config: Optional[Config] = None,
        event_system: Optional["EventSystem"] = None,
    ):
        """Initialize parser chain with ordered list of parser names.

        Args:
            parser_names: Ordered list of parser names to try. If None,
                uses configuration or DEFAULT_PARSER_PRIORITY.
            config: Optional Config instance. If None, loads default configuration.
                For backward compatibility, config is optional.
            event_system: EventSystem instance for event emission. If None,
                creates a no-op event system for standalone usage.
        """
        if config is None:
            config = Config.load()
        self.config = config
        self.event_system: "EventSystem" | NoOpEventSystem = (
            event_system if event_system is not None else NoOpEventSystem()
        )

        # Register the in-tree recognizers at construction time. This
        # covers every production path (``__init__``, ``from_config``,
        # ``create_parser_chain``). Importing ``ParserChain`` itself is
        # still side-effect-free — only constructing one populates the
        # registry — so tests that need a clean registry can still
        # unregister recognizers explicitly (see the ``_clean_registry``
        # fixture in test_registry.py). ``register_recognizer`` de-dupes
        # by name, so repeated construction is a no-op after the first.
        from .recognizers import _register_builtin_recognizers

        _register_builtin_recognizers()

        if parser_names is None:
            # Build parser list from configuration based on enabled status and priority
            parser_configs = [
                ("unified_code", config.parsers.unified_code),
                ("salesforce_metadata", config.parsers.salesforce_metadata),
                ("document", config.parsers.document),
                ("fallback_text", config.parsers.fallback_text),
            ]
            # Filter enabled parsers and sort by priority (highest first)
            enabled_parsers = [
                (name, cfg) for name, cfg in parser_configs if cfg.enabled
            ]
            enabled_parsers.sort(key=lambda x: x[1].priority, reverse=True)
            parser_names = [name for name, _ in enabled_parsers]

            # Fall back to default if no parsers enabled
            if not parser_names:
                parser_names = DEFAULT_PARSER_PRIORITY.copy()

        self.parser_names = parser_names
        # Bind fallback_text to this chain's config so YAML/overlay chunk
        # settings are used. Other registered parsers stay on the global registry.
        self._bound_parsers: dict[str, ParserProtocol] = {}
        self._bind_fallback_text_parser()

        logger.debug("Initialized ParserChain with priority: %s", self.parser_names)

    def _bind_fallback_text_parser(self) -> None:
        """Construct FallbackTextParser from config without mutating the registry."""
        if "fallback_text" not in self.parser_names:
            return
        try:
            registered = get_parser_instance("fallback_text")
        except KeyError:
            return
        if not isinstance(registered, FallbackTextParser):
            return
        cfg = self.config.parsers.fallback_text
        self._bound_parsers["fallback_text"] = FallbackTextParser(
            max_chunk_size=cfg.max_chunk_size,
            chunk_overlap=cfg.chunk_overlap,
            whole_file_max_chars=cfg.whole_file_max_chars,
        )

    @classmethod
    def from_config(cls, config: Optional[Config] = None) -> "ParserChain":
        """Create ParserChain from configuration.

        Args:
            config: Optional Config instance. If None, loads default configuration.

        Returns:
            ParserChain instance configured from settings

        Example:
            >>> from agentic_inquiry.config import Config
            >>> config = Config.load()
            >>> chain = ParserChain.from_config(config)

            >>> # Or load default config
            >>> chain = ParserChain.from_config()
        """
        if config is None:
            config = Config.load()

        return cls(parser_names=None, config=config)

    async def parse(self, path: str, **kwargs) -> ParsedDocument:
        """Try each parser in order until one succeeds.

        For each parser in the chain:
        1. Check if parser is registered
        2. If parser has can_parse method, check if it can handle the file
        3. If can_parse returns False, skip to next parser
        4. Attempt to parse the file
        5. If parsing succeeds, return the result
        6. If parsing fails, log error and try next parser

        Args:
            path: Path to the file to parse
            **kwargs: Additional parameters to pass to parsers (e.g., db_manager, embedding_service, project_id)

        Returns:
            ParsedDocument from the first successful parser

        Raises:
            ParsingError: If all parsers fail or no parsers are available
        """
        from agentic_inquiry.events.context_managers import track_operation
        from agentic_inquiry.events.models import EventStatus
        from agentic_inquiry.events.types import EventTypes

        errors = []

        # Track the entire parsing operation
        # Pass None if using NoOpEventSystem to match track_operation's expected type
        event_sys: Optional["EventSystem"] = (
            None
            if isinstance(self.event_system, NoOpEventSystem)
            else self.event_system
        )
        async with track_operation(
            event_sys,
            "parsing",
            source="ParserChain",
            file_path=path,
        ) as op:
            try:
                for name in self.parser_names:
                    try:
                        # Get the full parser instance from registry
                        parser_instance = self._bound_parsers.get(
                            name
                        ) or get_parser_instance(name)

                        # Check if parser can handle this file (if can_parse is implemented)
                        if isinstance(parser_instance, ParserProtocol):
                            # ParserProtocol has can_parse with default True
                            if hasattr(parser_instance, "can_parse") and callable(
                                parser_instance.can_parse
                            ):
                                can_handle = await parser_instance.can_parse(path)
                                if not can_handle:
                                    logger.debug(
                                        "Parser '%s' cannot handle %s, skipping",
                                        name,
                                        path,
                                    )
                                    continue

                        # Emit parser selected event
                        await self.event_system.emit(
                            EventTypes.Parsing.PARSER_SELECTED,
                            source="ParserChain",
                            status=EventStatus.PROGRESS,
                            parser_name=name,
                            file_path=path,
                        )

                        # Attempt to parse (async) with additional kwargs
                        logger.debug(
                            "Attempting to parse %s with parser '%s'", path, name
                        )
                        result = await execute_parser(parser_instance, path, **kwargs)

                        # Emit chunk created events for each chunk
                        for idx, chunk in enumerate(result.chunks):
                            await self.event_system.emit(
                                EventTypes.Parsing.CHUNK_CREATED,
                                source="ParserChain",
                                status=EventStatus.PROGRESS,
                                file_path=path,
                                parser_name=name,
                                chunk_index=idx,
                                content_type=chunk.content_type,
                                content_length=len(chunk.content)
                                if chunk.content
                                else 0,
                            )

                        logger.info(
                            "Successfully parsed %s with parser '%s'", path, name
                        )

                        # Framework recognizers run after a successful base
                        # parse. They enrich the document with
                        # framework-specific relationships (e.g. Spring
                        # HTTP routes) that tree-sitter cannot resolve
                        # statically. Failures are swallowed inside
                        # ``apply_recognizers`` so the base parse still
                        # reaches the indexing pipeline.
                        result = await apply_recognizers(result)

                        # Emit progress with parsing stats
                        await op.progress(
                            parser_name=name,
                            chunks_created=len(result.chunks),
                        )

                        return result

                    except KeyboardInterrupt:
                        # Never catch KeyboardInterrupt - let it propagate
                        raise

                    except SystemExit:
                        # Never catch SystemExit - let it propagate
                        raise

                    except KeyError:
                        # Parser not registered
                        logger.debug("Parser '%s' not registered, skipping", name)
                        errors.append(f"{name}: not registered")
                        continue

                    except Exception as e:
                        # Parser failed - log at WARNING level with stack trace
                        logger.warning(
                            "Parser '%s' failed for %s: %s",
                            name,
                            path,
                            str(e),
                            exc_info=True,
                            extra={"file_path": path, "parser_name": name},
                        )
                        errors.append(f"{name}: {str(e)}")
                        continue

                # All parsers failed - log at ERROR level with structured data
                if not errors:
                    error_msg = f"No parsers available to parse {path}"
                else:
                    error_details = "; ".join(errors)
                    error_msg = f"All parsers failed for {path}: {error_details}"

                logger.error(
                    error_msg, extra={"file_path": path, "parser_errors": errors}
                )
                raise ParsingError(error_msg)

            except ParsingError:
                # Re-raise ParsingError (track_operation will emit failed event)
                raise
            except Exception as e:
                # Unexpected error - wrap in ParsingError
                error_msg = f"Unexpected error parsing {path}: {e}"
                logger.error(error_msg, exc_info=True)
                raise ParsingError(error_msg) from e


def create_parser_chain(
    priority: Optional[List[str]] = None,
    event_system: Optional["EventSystem"] = None,
    config: Optional[Config] = None,
) -> ParserChain:
    """Create a parser chain with specified priority order.

    Factory function for convenient ParserChain creation.

    Args:
        priority: Ordered list of parser names. If None, uses default priority.
        event_system: EventSystem instance for event emission. If None, creates
            a no-op event system for standalone usage.
        config: Optional Config instance. When provided, fallback text chunk
            settings come from this config instead of a fresh Config.load().

    Returns:
        ParserChain instance

    Example:
        >>> # Use default priority
        >>> chain = create_parser_chain()

        >>> # Custom priority
        >>> chain = create_parser_chain(["unified_document", "fallback_text"])
    """
    return ParserChain(parser_names=priority, event_system=event_system, config=config)


__all__ = [
    "ParserChain",
    "ParsingError",
    "create_parser_chain",
    "DEFAULT_PARSER_PRIORITY",
]
