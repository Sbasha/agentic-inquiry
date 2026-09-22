"""Unified filter system for database queries.

This package provides a single source of truth for filter operations:

1. **Filter AST** (ast.py): Canonical filter representation
   - Filter class with operators (EQ, NE, GT, IN, AND, OR, etc.)
   - Convenience constructors (eq, ne, gt, is_in, and_, or_, etc.)

2. **Filter Builder** (builder.py): Fluent API for constructing filters
   - FilterBuilder class with method chaining
   - Safe escaping and validation

3. **Filter Translator** (translator.py): AST → SQL translation
   - LanceDBFilterTranslator for Filter AST to SQL
   - translate_filter() convenience function

4. **Dict Translator** (dict_translator.py): Dict → SQL translation
   - translate_dict_filters() for legacy dict-based filters
   - Supports nested OR/NOT operators

Usage:
    # Using Filter AST (recommended)
    from agent_vault.database.filters import eq, and_, translate_filter
    filter_ast = and_(eq("status", "active"), eq("type", "code"))
    sql = translate_filter(filter_ast)

    # Using dict filters (legacy)
    from agent_vault.database.filters import translate_dict_filters
    sql = translate_dict_filters({"status": "active", "type": "code"})

    # Using FilterBuilder
    from agent_vault.database.filters import FilterBuilder
    builder = FilterBuilder()
    builder.add_field_filter("status", "active")
    sql = builder.build()
"""

# Re-export Filter AST
from .ast import (
    Filter,
    FilterOperator,
    FilterValue,
    FilterValueList,
    and_,
    eq,
    gt,
    gte,
    ilike,
    is_in,
    is_not_null,
    is_null,
    like,
    lt,
    lte,
    ne,
    not_in,
    or_,
    validate_field_name,
    validate_filter_value,
    validate_filter_value_list,
)

# Re-export FilterBuilder
from .builder import FilterBuilder

# Re-export Dict Translator
from .dict_translator import translate_dict_filters

# Re-export AST Translator
from .translator import (
    FilterTranslationError,
    LanceDBFilterTranslator,
    translate_filter,
)

# Re-export backend-agnostic translator protocol + adapters
from .lancedb_adapter import LanceDBFilterAdapter
from .memory_adapter import MemoryFilterAdapter, Predicate
from .postgres_adapter import PostgresFilter, PostgresFilterAdapter
from .protocol import FilterInput, FilterTranslator, normalize_to_ast

__all__ = [
    # AST types
    "Filter",
    "FilterOperator",
    "FilterValue",
    "FilterValueList",
    # AST convenience constructors
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "is_in",
    "not_in",
    "is_null",
    "is_not_null",
    "like",
    "ilike",
    "and_",
    "or_",
    # Validation
    "validate_field_name",
    "validate_filter_value",
    "validate_filter_value_list",
    # Builder
    "FilterBuilder",
    # Translators (legacy AST/dict → SQL string)
    "LanceDBFilterTranslator",
    "FilterTranslationError",
    "translate_filter",
    "translate_dict_filters",
    # Backend-agnostic translator protocol + adapters
    "FilterInput",
    "FilterTranslator",
    "normalize_to_ast",
    "LanceDBFilterAdapter",
    "MemoryFilterAdapter",
    "Predicate",
    "PostgresFilter",
    "PostgresFilterAdapter",
]
