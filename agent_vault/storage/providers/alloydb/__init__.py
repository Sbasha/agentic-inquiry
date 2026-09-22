"""AlloyDB storage provider for agent_vault.

This package provides GCP AlloyDB-backed implementations that leverage
AlloyDB's built-in `embedding()` function for server-side vector generation
via Vertex AI, eliminating the local CPU embedding bottleneck.

Key difference from Cloud SQL:
- Embeddings are generated server-side using `embedding('text-embedding-005', content)`
- GENERATED ALWAYS AS columns auto-compute embeddings on INSERT/UPDATE
- No local sentence-transformers model needed
- Uses AlloyDB Auth Proxy (not Cloud SQL Proxy)

Available Components:
- AlloyDBConnectionManager: Connection manager with ADC and google_ml_integration
- AlloyDBSchemaGenerator: DDL with GENERATED ALWAYS AS embedding columns

Note: AlloyDB vector and graph functionality is now handled by the unified
PostgreSQL providers in agent_vault.storage.providers.postgresql.
"""

from agent_vault.storage.providers.alloydb.connection import (
    AlloyDBConnectionManager,
)
from agent_vault.storage.providers.alloydb.schemas import (
    AlloyDBSchemaGenerator,
)

__all__ = [
    "AlloyDBConnectionManager",
    "AlloyDBSchemaGenerator",
]
