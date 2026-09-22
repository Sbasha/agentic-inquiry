"""Index configuration strategy for PostgreSQL vector indexes.

This module provides configuration and parameter calculation for vector indexes
(HNSW and IVFFlat) based on expected dataset size and performance requirements.

Design decisions:
    - Dynamic ivfflat lists: Calculated using sqrt(n) formula
    - HNSW as default: Better recall without tuning
    - Explicit override: Allow manual lists parameter
    - Safety limits: Cap ivfflat lists at 10000 (PostgreSQL practical limit)

Example:
    >>> config = IndexConfig(
    ...     index_type=IndexType.HNSW,
    ...     hnsw_params=HNSWParams(m=16, ef_construction=64)
    ... )
    >>> # Or calculate ivfflat parameters dynamically
    >>> lists = IndexConfigStrategy.calculate_ivfflat_lists(100000)  # Returns 316
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ConfigurationError(Exception):
    """Raised when index configuration is invalid."""

    pass


class IndexType(Enum):
    """Vector index types supported by pgvector."""

    HNSW = "hnsw"
    IVFFLAT = "ivfflat"
    NONE = "none"


@dataclass
class HNSWParams:
    """Parameters for HNSW index.

    Attributes:
        m: Number of connections per layer (default: 16)
            Higher values = better recall, more memory, slower build
        ef_construction: Build-time search width (default: 64)
            Higher values = better recall, slower build
    """

    m: int = 16
    ef_construction: int = 64

    def to_sql_options(self) -> str:
        """Generate SQL WITH clause for HNSW index creation."""
        return f"WITH (m = {self.m}, ef_construction = {self.ef_construction})"


@dataclass
class IVFFlatParams:
    """Parameters for IVFFlat index.

    Attributes:
        lists: Number of IVF lists (default: 100)
            Optimal value: max(1, floor(sqrt(row_count)))
            Higher values = better recall, slower search
    """

    lists: int = 100

    def to_sql_options(self) -> str:
        """Generate SQL WITH clause for IVFFlat index creation."""
        return f"WITH (lists = {self.lists})"


@dataclass
class IndexConfig:
    """Complete index configuration including type and parameters.

    Attributes:
        index_type: Type of index to create (HNSW, IVFFLAT, or NONE)
        hnsw_params: HNSW parameters (if index_type is HNSW)
        ivfflat_params: IVFFlat parameters (if index_type is IVFFLAT)
        expected_rows: Expected number of rows for parameter calculation
    """

    index_type: IndexType = IndexType.HNSW
    hnsw_params: Optional[HNSWParams] = None
    ivfflat_params: Optional[IVFFlatParams] = None
    expected_rows: Optional[int] = None

    def __post_init__(self):
        """Initialize default parameters based on index type."""
        if self.index_type == IndexType.HNSW and self.hnsw_params is None:
            self.hnsw_params = HNSWParams()
        elif self.index_type == IndexType.IVFFLAT and self.ivfflat_params is None:
            self.ivfflat_params = IVFFlatParams()


class IndexConfigStrategy:
    """Calculates optimal index parameters based on configuration and table size.

    This class implements the index parameter calculation logic from FR-1.2,
    including the formula: lists = max(1, min(floor(sqrt(n)), 10000))
    """

    IVFFLAT_LISTS_MIN = 1
    IVFFLAT_LISTS_MAX = 10000

    @classmethod
    def calculate_ivfflat_lists(cls, row_count: int) -> int:
        """Calculate optimal lists parameter for IVFFlat index.

        Uses formula: max(1, min(floor(sqrt(n)), 10000))

        This formula provides a good balance between recall and performance:
        - 1,000 rows → 31 lists
        - 10,000 rows → 100 lists
        - 100,000 rows → 316 lists
        - 1,000,000 rows → 1,000 lists
        - 100,000,000 rows → 10,000 lists (capped)

        Args:
            row_count: Expected or actual number of rows in the table

        Returns:
            Calculated lists parameter (capped at 10000)

        Raises:
            ConfigurationError: If row_count is negative

        Example:
            >>> IndexConfigStrategy.calculate_ivfflat_lists(10000)
            100
            >>> IndexConfigStrategy.calculate_ivfflat_lists(100000000)
            10000
        """
        if row_count < 0:
            raise ConfigurationError(f"expected_rows cannot be negative: {row_count}")

        calculated = max(1, int(math.floor(math.sqrt(row_count))))
        return min(calculated, cls.IVFFLAT_LISTS_MAX)

    @classmethod
    def validate_ivfflat_lists(cls, lists: int) -> None:
        """Validate lists parameter is within PostgreSQL practical limits.

        Args:
            lists: The lists parameter to validate

        Raises:
            ConfigurationError: If lists is out of valid range [1, 10000]

        Example:
            >>> IndexConfigStrategy.validate_ivfflat_lists(100)  # OK
            >>> IndexConfigStrategy.validate_ivfflat_lists(20000)  # Raises
            Traceback (most recent call last):
                ...
            ConfigurationError: ivfflat lists must be in range [1, 10000], got: 20000
        """
        if not (cls.IVFFLAT_LISTS_MIN <= lists <= cls.IVFFLAT_LISTS_MAX):
            raise ConfigurationError(
                f"ivfflat lists must be in range [{cls.IVFFLAT_LISTS_MIN}, "
                f"{cls.IVFFLAT_LISTS_MAX}], got: {lists}"
            )

    @classmethod
    def resolve_ivfflat_lists(
        cls, config: IndexConfig, current_row_count: Optional[int] = None
    ) -> int:
        """Resolve lists parameter from config or calculate from row count.

        Resolution priority:
        1. Explicit override in config.ivfflat_params.lists
        2. Calculate from config.expected_rows
        3. Calculate from current_row_count
        4. Default to 100

        Args:
            config: Index configuration with optional explicit lists
            current_row_count: Current table row count (optional)

        Returns:
            Resolved lists parameter

        Raises:
            ConfigurationError: If explicit lists value is out of range

        Example:
            >>> config = IndexConfig(
            ...     index_type=IndexType.IVFFLAT,
            ...     ivfflat_params=IVFFlatParams(lists=50)
            ... )
            >>> IndexConfigStrategy.resolve_ivfflat_lists(config)
            50
            >>> config2 = IndexConfig(
            ...     index_type=IndexType.IVFFLAT,
            ...     expected_rows=10000
            ... )
            >>> IndexConfigStrategy.resolve_ivfflat_lists(config2)
            100
        """
        # 1. Explicit override takes precedence (AC-3)
        if config.ivfflat_params and config.ivfflat_params.lists:
            lists = config.ivfflat_params.lists
            cls.validate_ivfflat_lists(lists)
            return lists

        # 2. Use expected_rows from config
        if config.expected_rows is not None:
            return cls.calculate_ivfflat_lists(config.expected_rows)

        # 3. Fall back to current table row count
        if current_row_count is not None:
            return cls.calculate_ivfflat_lists(current_row_count)

        # 4. Default for empty/new tables
        return 100
