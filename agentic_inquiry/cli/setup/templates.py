"""Configuration templates for setup wizard.

Templates define the default configuration structure for each backend type.
Placeholders use ${VAR_NAME} syntax for variable substitution during setup.
"""

from typing import Any

# LanceDB (Local/Development) template
LANCEDB_TEMPLATE: dict[str, Any] = {
    "storage": {
        "root": "${root}",
        "backends": {
            "default": {
                "type": "lancedb",
                "database_path": "${root}/lancedb",
            },
            "metadata_store": {
                "type": "sqlite",
                "database_path": "${root}/metadata.db",
            },
        },
        "vector_backend": "default",
        "graph_backend": "default",
        "events_backend": "metadata_store",
        "file_tracker_backend_v2": "metadata_store",
    },
    "embeddings": {
        "default_provider": "sentence_transformer",
        "default_dimensions": 384,
    },
    "mcp": {
        "enabled": True,
        "api": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8000,
        },
    },
}

def render_template(template: dict[str, Any], variables: dict[str, str]) -> dict[str, Any]:
    """Render a template by substituting variables.

    Args:
        template: Template dictionary with ${VAR_NAME} placeholders
        variables: Variable name to value mapping

    Returns:
        Rendered template with substituted values

    Example:
        >>> tpl = {"path": "${ROOT}/data"}
        >>> render_template(tpl, {"ROOT": "/tmp"})
        {"path": "/tmp/data"}
    """
    import copy
    import re

    def _substitute(value: Any) -> Any:
        if isinstance(value, str):
            # Replace ${VAR_NAME} patterns
            pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

            def replacer(match: re.Match) -> str:
                var_name = match.group(1)
                return variables.get(var_name, match.group(0))

            return pattern.sub(replacer, value)
        elif isinstance(value, dict):
            return {k: _substitute(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_substitute(v) for v in value]
        return value

    return _substitute(copy.deepcopy(template))
