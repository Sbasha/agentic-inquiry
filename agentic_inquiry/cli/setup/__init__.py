"""Local environment setup for the ai command.

The setup wizard creates a LanceDB environment configuration under the
workspace or the global ~/.agentic-inquiry directory. External database
providers are future work; see docs/storage-backends.md for the provider
contract they must satisfy.

Example:
    >>> from agentic_inquiry.cli.setup import LocalSetup
    >>> setup = LocalSetup(env_name="dev", is_dev=True)
    >>> setup.run()
"""

from agentic_inquiry.cli.setup.base import BaseSetup, run_async
from agentic_inquiry.cli.setup.local_setup import LocalSetup
from agentic_inquiry.cli.setup.templates import LANCEDB_TEMPLATE, render_template

__all__ = [
    "BaseSetup",
    "LocalSetup",
    "run_async",
    "LANCEDB_TEMPLATE",
    "render_template",
]
