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
    "services": {
        "auto_start_proxy": False,
    },
}

# PostgreSQL (Direct Connection) template
POSTGRES_TEMPLATE: dict[str, Any] = {
    "storage": {
        "root": "${root}",
        "backends": {
            "postgres_db": {
                "type": "postgresql",
                "connection_string": "${CONNECTION_STRING}",
                "pool_size": 10,
                "table_prefix": "${TABLE_PREFIX}",
            },
        },
        "vector_backend": "postgres_db",
        "graph_backend": "postgres_db",
        "events_backend": "postgres_db",
        "file_tracker_backend_v2": "postgres_db",
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
    "services": {
        "auto_start_proxy": False,
    },
}

# CloudSQL (GCP Managed) template
CLOUDSQL_TEMPLATE: dict[str, Any] = {
    "storage": {
        "root": "${root}",
        "backends": {
            "cloudsql": {
                "type": "cloudsql",
                "project": "${GCP_PROJECT}",
                "region": "${GCP_REGION}",
                "instance": "${GCP_INSTANCE}",
                "database": "${GCP_DATABASE}",
                "user": "${GCP_USER}",
                "pool_size": 10,
                "table_prefix": "${TABLE_PREFIX}",
            },
        },
        "vector_backend": "cloudsql",
        "graph_backend": "cloudsql",
        "events_backend": "cloudsql",
        "file_tracker_backend_v2": "cloudsql",
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
    "services": {
        "auto_start_proxy": True,
        "proxy": {
            "connection_name": "${GCP_PROJECT}:${GCP_REGION}:${GCP_INSTANCE}",
            "port": 5433,
        },
        "startup_timeout": 30,
    },
}


# AlloyDB (GCP Managed, Server-Side Embeddings) template
ALLOYDB_TEMPLATE: dict[str, Any] = {
    "storage": {
        "root": "${root}",
        "backends": {
            "alloydb": {
                "type": "alloydb",
                "project": "${GCP_PROJECT}",
                "region": "${GCP_REGION}",
                "cluster": "${ALLOYDB_CLUSTER}",
                "instance": "${ALLOYDB_INSTANCE}",
                "database": "${GCP_DATABASE}",
                "user": "${GCP_USER}",
                "pool_size": 10,
                "table_prefix": "${TABLE_PREFIX}",
            },
        },
        "vector_backend": "alloydb",
        "graph_backend": "alloydb",
        "events_backend": "alloydb",
        "file_tracker_backend_v2": "alloydb",
    },
    "embeddings": {
        "default_provider": "none",
        "default_dimensions": 768,
    },
    "mcp": {
        "enabled": True,
        "api": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8000,
        },
    },
    "services": {
        "auto_start_proxy": True,
        "proxy": {
            "connection_name": "projects/${GCP_PROJECT}/locations/${GCP_REGION}/clusters/${ALLOYDB_CLUSTER}/instances/${ALLOYDB_INSTANCE}",
            "port": 5432,
            "type": "alloydb",
        },
        "startup_timeout": 30,
    },
}


# AWS RDS (Managed PostgreSQL) template
RDS_TEMPLATE: dict[str, Any] = {
    "storage": {
        "root": "${root}",
        "backends": {
            "rds": {
                "type": "rds",
                "region": "${AWS_REGION}",
                "instance": "${RDS_INSTANCE}",
                "host": "${RDS_HOST}",
                "database": "${RDS_DATABASE}",
                "user": "${RDS_USER}",
                "pool_size": 10,
                "table_prefix": "${TABLE_PREFIX}",
            },
        },
        "vector_backend": "rds",
        "graph_backend": "rds",
        "events_backend": "rds",
        "file_tracker_backend_v2": "rds",
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
    "services": {
        "auto_start_proxy": False,
    },
}


# Azure Database for PostgreSQL template
#
# Defaults to **server-side** embedding via the ``azure_ai`` extension —
# that's the deployment shape that justifies running on Azure Postgres
# in the first place (the alternative is plain Postgres with a local
# embedder, in which case the ``postgresql`` template applies). The
# template's defaults align with ``docs/backends/azure.md``: model
# ``text-embedding-3-small`` at 1536 dim. Operators wanting a different
# Azure OpenAI deployment override ``EMBEDDING_MODEL`` /
# ``EMBEDDING_DIM`` at render time.
AZURE_TEMPLATE: dict[str, Any] = {
    "storage": {
        "root": "${root}",
        "backends": {
            "azure_db": {
                "type": "azure",
                "host": "${AZURE_HOST}",
                "database": "${AZURE_DATABASE}",
                "user": "${AZURE_USER}",
                "pool_size": 10,
                "table_prefix": "${TABLE_PREFIX}",
                "embedding_strategy": "${EMBEDDING_STRATEGY}",
                "embedding_model": "${EMBEDDING_MODEL}",
                "embedding_dim": "${EMBEDDING_DIM}",
            },
        },
        "vector_backend": "azure_db",
        "graph_backend": "azure_db",
        "events_backend": "azure_db",
        "file_tracker_backend_v2": "azure_db",
    },
    "embeddings": {
        # Server-side path: the azure_ai extension generates embeddings
        # in-database; the client-side embedder is the noop slot-filler
        # (see ``Config.validate_embedding_consistency`` for why
        # ``"none"`` is the sentinel that suppresses the dim check).
        "default_provider": "none",
        "default_dimensions": 1536,
    },
    "mcp": {
        "enabled": True,
        "api": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8000,
        },
    },
    "services": {
        "auto_start_proxy": False,
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
