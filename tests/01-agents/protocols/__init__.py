"""
UAT protocol registry.

Maps test IDs to full protocol modules or falls back to generic smoke.
"""
from typing import Callable

from . import smoke
from . import test_01_core
from . import test_02_onboarding
from . import test_04_bug
from . import test_06_knowledge
from . import test_08_docs
from . import test_10_perf
from . import test_11_api_design
from . import test_12_code_graph
from . import test_13_document_graph
from . import test_14_semantic_graph

# Full protocol modules (key = test_id)
FULL_PROTOCOLS: dict[str, Callable] = {
    "01": test_01_core.run,
    "02": test_02_onboarding.run,
    "04": test_04_bug.run,
    "06": test_06_knowledge.run,
    "08": test_08_docs.run,
    "10": test_10_perf.run,
    "11": test_11_api_design.run,
    "12": test_12_code_graph.run,
    "13": test_13_document_graph.run,
    "14": test_14_semantic_graph.run,
}


def get_protocol(test_id: str, mode: str = "full") -> Callable:
    """Get the run function for a test ID.

    In 'full' mode, returns the full protocol if available, else smoke.
    In 'smoke' mode, always returns the smoke protocol.
    """
    if mode == "smoke":
        return smoke.run
    return FULL_PROTOCOLS.get(test_id, smoke.run)
