# Initialize logging before any other imports that might use logging
try:
    from agent_vault.utils.logging_setup import LoggingConfigurator
    LoggingConfigurator.setup()
except Exception:
    # If logging setup fails, continue without file logging
    # Error messages are already printed to stderr by LoggingConfigurator
    pass

from . import database, embeddings, exceptions, indexing, models, parsers, search

__all__ = ['database', 'embeddings', 'exceptions', 'indexing', 'models', 'parsers', 'search']
