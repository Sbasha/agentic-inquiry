"""Dynamic entry point that loads the simple workflow at runtime."""

import importlib
from typing import Callable


def load_workflow(name: str) -> Callable[[], dict[str, float]]:
    module = importlib.import_module("simple")
    return getattr(module, name)


REGISTRY = {
    "simple_flow": load_workflow("simple_flow"),
    "summarize": load_workflow("summarize"),
}


def run_dynamic(name: str = "summarize") -> str:
    action = REGISTRY[name]
    result = action()
    if isinstance(result, dict):
        return f"dynamic:{result['baseline']:.1f}:{result['rms']:.1f}"
    return str(result)
