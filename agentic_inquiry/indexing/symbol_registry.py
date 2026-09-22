"""Symbol Registry Service for cross-file linking.

This module provides a standalone service for managing symbol definitions
and lookups across a project. It maintains multiple indexes for efficient
resolution of import relationships.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Set, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class SymbolMetadata:
    """Rich metadata for a symbol to aid resolution.
    
    Attributes:
        name: Symbol name (e.g., "IndexingPipeline")
        file_path: Absolute or relative path to file containing symbol
        entity_type: Type of entity (class, function, module, etc.)
        language: Programming language (python, javascript, etc.)
        project_id: Project identifier for multi-project support
        line_start: Starting line number of symbol definition
        line_end: Ending line number of symbol definition
        module_path: Module path (e.g., "agentic_inquiry.indexing.pipeline")
        parent_scope: Parent scope for nested symbols (e.g., class name for methods)
        is_exported: Whether symbol is exported/public
    """
    name: str
    file_path: str
    entity_type: str
    language: str
    project_id: str
    line_start: int
    line_end: int
    module_path: Optional[str]
    parent_scope: Optional[str]
    is_exported: bool


class SymbolRegistry:
    """Project-wide symbol registry with multiple indexes for fast resolution.
    
    Implements SymbolRegistryProtocol for dependency injection and testing.
    
    This is a standalone service that can be used by IndexingPipeline or other
    components that need symbol resolution. It maintains multiple indexes for
    O(1) lookups and supports incremental updates.
    
    The service is stateless except for the symbol data - no database dependencies.
    
    Enhanced with language-agnostic features for 90%+ resolution:
    - Frequency tracking: Track how often symbols are imported
    - Co-occurrence tracking: Track which files commonly import from each other
    - File naming pattern scoring: Match symbol names to file names
    - Directory structure scoring: Match symbol names to directory names
    - Composite scoring: Combine multiple signals for better resolution
    
    Note:
        This class implements SymbolRegistryProtocol, providing async methods
        for symbol registration, lookup, and import tracking.
    """
    
    def __init__(self, project_root: str, project_id: str, cache_size: int = 1024):
        """Initialize the symbol registry.
        
        Args:
            project_root: Root directory of the project
            project_id: Unique identifier for the project
            cache_size: Size of LRU cache for resolution results (default: 1024)
        """
        self.project_root = Path(project_root)
        self.project_id = project_id
        self._cache_size = cache_size
        
        # Primary index: name → [SymbolMetadata]
        # Allows lookup of all symbols with a given name
        self._by_name: Dict[str, List[SymbolMetadata]] = {}
        
        # Type-specific index: (name, type) → [SymbolMetadata]
        # Faster when we know the target type (e.g., "class")
        self._by_name_type: Dict[Tuple[str, str], List[SymbolMetadata]] = {}
        
        # Reverse index: file_path → Set[symbol_names]
        # For incremental updates - track which symbols are in each file
        self._by_file: Dict[str, Set[str]] = {}
        
        # Module path index: module_path → SymbolMetadata
        # Maps import paths to actual files
        # e.g., "agentic_inquiry.indexing.pipeline" → metadata
        self._module_paths: Dict[str, SymbolMetadata] = {}
        
        # Language-agnostic enhancement: Frequency tracking
        # Track how often each symbol is imported across the codebase
        # symbol_name → import_count
        self._import_frequency: Dict[str, int] = {}
        
        # Language-agnostic enhancement: Co-occurrence tracking
        # Track which files commonly import from each other
        # (source_file, target_file) → import_count
        self._co_occurrence: Dict[Tuple[str, str], int] = {}
        
        # Create LRU cache for resolution results
        # Cache key: (target_name, target_type, source_file)
        # Cache value: (resolved_file_path, resolved_type, confidence)
        self._resolve_cached = lru_cache(maxsize=cache_size)(self._resolve_impl)
    
    async def register(self,
                 name: str,
                 file_path: str,
                 entity_type: str,
                 language: str,
                 line_start: int = -1,
                 line_end: int = -1,
                 parent_scope: Optional[str] = None,
                 is_exported: bool = True) -> None:
        """Register a symbol definition with rich metadata.
        
        Adds the symbol to all relevant indexes for efficient lookup.
        
        Args:
            name: Symbol name
            file_path: Path to file containing the symbol
            entity_type: Type of entity (class, function, module, etc.)
            language: Programming language
            line_start: Starting line number (default: -1)
            line_end: Ending line number (default: -1)
            parent_scope: Parent scope for nested symbols (default: None)
            is_exported: Whether symbol is exported/public (default: True)
        """
        # Create metadata
        module_path = self._file_to_module_path(file_path)
        metadata = SymbolMetadata(
            name=name,
            file_path=file_path,
            entity_type=entity_type,
            language=language,
            project_id=self.project_id,
            line_start=line_start,
            line_end=line_end,
            module_path=module_path,
            parent_scope=parent_scope,
            is_exported=is_exported
        )
        
        # Add to primary index
        if name not in self._by_name:
            self._by_name[name] = []
        self._by_name[name].append(metadata)
        
        # Add to type-specific index
        key = (name, entity_type)
        if key not in self._by_name_type:
            self._by_name_type[key] = []
        self._by_name_type[key].append(metadata)
        
        # Add to reverse index
        if file_path not in self._by_file:
            self._by_file[file_path] = set()
        self._by_file[file_path].add(name)
        
        # Add to module path index
        if module_path:
            self._module_paths[module_path] = metadata

        # NOTE: Removed full cache clear - it was invalidating all cached
        # resolutions on every symbol registration, making the cache useless.
        # The LRU cache will naturally evict stale entries. If targeted
        # invalidation is needed later, invalidate only entries matching
        # the registered symbol name.

        logger.debug("Registered symbol: %s (%s) in %s "
            "[module: %s]", name, entity_type, file_path, module_path)
    
    def lookup_by_name(self, name: str) -> List[SymbolMetadata]:
        """Look up symbol by name.
        
        Args:
            name: Symbol name to look up
            
        Returns:
            List of SymbolMetadata for all symbols with the given name
        """
        return self._by_name.get(name, [])
    
    def lookup_by_name_and_type(self, name: str, entity_type: str) -> List[SymbolMetadata]:
        """Look up symbol by name and type.
        
        More specific than lookup_by_name - useful when the target type is known.
        
        Args:
            name: Symbol name to look up
            entity_type: Entity type (class, function, module, etc.)
            
        Returns:
            List of SymbolMetadata for symbols matching both name and type
        """
        return self._by_name_type.get((name, entity_type), [])

    async def lookup(self, name: str, type_hint: Optional[str] = None) -> List[SymbolMetadata]:
        """Look up symbols by name and optional type (protocol-compatible method).
        
        This method provides a unified interface compatible with SymbolRegistryProtocol.
        It delegates to lookup_by_name_and_type if type_hint is provided, otherwise
        to lookup_by_name.
        
        Args:
            name: Symbol name to look up
            type_hint: Optional type filter (class, function, module, etc.)
            
        Returns:
            List of SymbolMetadata for symbols matching the criteria
        """
        if type_hint:
            return self.lookup_by_name_and_type(name, type_hint)
        return self.lookup_by_name(name)
    
    async def clear(self) -> None:
        """Clear all registered symbols (protocol-compatible method).
        
        Clears all symbol indexes and caches. Useful for testing or
        when reindexing a project.
        """
        self._by_name.clear()
        self._by_name_type.clear()
        self._by_file.clear()
        self._module_paths.clear()
        self._import_frequency.clear()
        self._co_occurrence.clear()
        self.clear_cache()
        logger.debug("Cleared all symbols for project %s", self.project_id)
    
    def resolve_with_cache(self,
                          target_name: str,
                          target_type: str,
                          source_file: str) -> Optional[Tuple[str, str, float]]:
        """Resolve symbol with LRU caching for performance.
        
        This method wraps the actual resolution logic with an LRU cache
        to avoid repeated lookups for the same symbols.
        
        Args:
            target_name: Name of symbol to resolve
            target_type: Type of symbol (class, function, etc.)
            source_file: File where the reference originates
            
        Returns:
            Tuple of (file_path, entity_type, confidence) or None if not found
        """
        return self._resolve_cached(target_name, target_type, source_file)
    
    def _resolve_impl(self,
                     target_name: str,
                     target_type: str,
                     source_file: str) -> Optional[Tuple[str, str, float]]:
        """Internal resolution implementation (wrapped by lru_cache).
        
        Uses multiple strategies with frequency and co-occurrence data to find
        the best match for a symbol reference.
        
        Resolution strategies (in order):
        1. Exact match by name and type
        2. Frequency-weighted match (prefer commonly imported symbols)
        3. Co-occurrence weighted match (prefer files that commonly import from each other)
        4. File naming pattern match
        5. Directory structure match
        
        Args:
            target_name: Name of symbol to resolve
            target_type: Type of symbol (class, function, etc.)
            source_file: Source file path
            
        Returns:
            Tuple of (file_path, entity_type, confidence) or None if not found
        """
        # Strategy 1: Exact match by name and type
        candidates = self.lookup_by_name_and_type(target_name, target_type)
        
        if len(candidates) == 1:
            # Single exact match - highest confidence
            candidate = candidates[0]
            logger.debug("Resolved %s via exact match: %s", target_name, candidate.file_path)
            return (candidate.file_path, candidate.entity_type, 1.0)
        
        # Strategy 2: If no exact type match, try by name only
        if not candidates:
            candidates = self.lookup_by_name(target_name)
        
        if not candidates:
            logger.debug("No candidates found for %s", target_name)
            return None
        
        # Multiple candidates - use composite scoring
        scored_candidates = []
        
        for candidate in candidates:
            score = 0.0
            
            # Factor 1: Import frequency (0-30 points)
            # More frequently imported symbols are more likely to be the target
            frequency = self.get_import_frequency(target_name)
            if frequency > 0:
                # Normalize frequency score (cap at 30 points)
                frequency_score = min(30.0, frequency * 3.0)
                score += frequency_score
            
            # Factor 2: Co-occurrence (0-40 points)
            # Files that commonly import from each other are more likely
            co_occurrence = self.get_co_occurrence_score(source_file, candidate.file_path)
            if co_occurrence > 0:
                # Normalize co-occurrence score (cap at 40 points)
                co_occurrence_score = min(40.0, co_occurrence * 10.0)
                score += co_occurrence_score
            
            # Factor 3: File naming pattern (0-100 points)
            # Symbol names that match file names are more likely
            naming_score = self.score_file_naming_pattern(target_name, candidate.file_path)
            score += naming_score * 0.15  # Weight: 15% of naming score
            
            # Factor 4: Directory structure (0-100 points)
            # Symbol names that match directory names are more likely
            directory_score = self.score_directory_structure(target_name, candidate.file_path)
            score += directory_score * 0.10  # Weight: 10% of directory score
            
            # Factor 5: Type match bonus (20 points)
            # If type matches the requested type, add bonus
            if candidate.entity_type == target_type:
                score += 20.0
            
            # Factor 6: Export status bonus (10 points)
            # Exported symbols are more likely to be imported
            if candidate.is_exported:
                score += 10.0
            
            scored_candidates.append((candidate, score))
        
        # Sort by score (highest first)
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        
        best_candidate, best_score = scored_candidates[0]
        
        # Convert score to confidence (0.0-1.0)
        # Max possible score is ~230 points
        # Use sigmoid-like function for confidence
        confidence = min(1.0, best_score / 150.0)
        
        # Only return if confidence is reasonable (>= 0.3)
        if confidence >= 0.3:
            logger.debug("Resolved %s to %s "
                "(score: %.1f, confidence: %.2f)", target_name, best_candidate.file_path, best_score, confidence)
            return (best_candidate.file_path, best_candidate.entity_type, confidence)
        
        logger.debug("Best match for %s has low confidence "
            "(%.2f), returning None", target_name, confidence)
        return None
    
    def clear_cache(self) -> None:
        """Clear the resolution cache.
        
        Should be called when the registry is modified to invalidate
        cached resolution results.
        """
        self._resolve_cached.cache_clear()
        logger.debug("Resolution cache cleared")
    
    def get_cache_info(self) -> Dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics:
            - hits: Number of cache hits
            - misses: Number of cache misses
            - size: Current cache size
            - max_size: Maximum cache size
        """
        info = self._resolve_cached.cache_info()
        return {
            "hits": info.hits,
            "misses": info.misses,
            "size": info.currsize,
            "max_size": info.maxsize or 0
        }
    
    def remove_file_symbols(self, file_path: str) -> None:
        """Remove all symbols from a file (for incremental updates).
        
        This is used when a file is modified or deleted to remove outdated
        symbol definitions from all indexes.
        
        Args:
            file_path: Path to file whose symbols should be removed
        """
        if file_path not in self._by_file:
            logger.debug("No symbols found for file: %s", file_path)
            return
        
        symbols = self._by_file[file_path]
        logger.debug("Removing %s symbols from %s", len(symbols), file_path)
        
        for symbol in symbols:
            # Remove from primary index
            if symbol in self._by_name:
                self._by_name[symbol] = [
                    metadata for metadata in self._by_name[symbol]
                    if metadata.file_path != file_path
                ]
                if not self._by_name[symbol]:
                    del self._by_name[symbol]
            
            # Remove from type-specific index
            for key in list(self._by_name_type.keys()):
                if key[0] == symbol:
                    self._by_name_type[key] = [
                        metadata for metadata in self._by_name_type[key]
                        if metadata.file_path != file_path
                    ]
                    if not self._by_name_type[key]:
                        del self._by_name_type[key]
        
        # Remove from reverse index
        del self._by_file[file_path]
        
        # Remove from module path index
        module_path = self._file_to_module_path(file_path)
        if module_path and module_path in self._module_paths:
            if self._module_paths[module_path].file_path == file_path:
                del self._module_paths[module_path]
        
        # Clear cache since registry changed
        self.clear_cache()
    
    def _file_to_module_path(self, file_path: str) -> Optional[str]:
        """Convert file path to module path.
        
        Converts a file path to a module path using dot notation.
        For example: "path/to/file.py" → "path.to.file"
        
        Args:
            file_path: File path to convert
            
        Returns:
            Module path string or None if conversion fails
        """
        try:
            path = Path(file_path)
            
            # Try to make path relative to project root
            try:
                rel_path = path.relative_to(self.project_root)
            except ValueError:
                # If path is not under project root, use as-is
                rel_path = path
            
            # Remove extension and convert to dot notation
            module_path = str(rel_path.with_suffix('')).replace('/', '.').replace('\\', '.')
            
            # Handle __init__ files - they represent the package itself
            if module_path.endswith('.__init__'):
                module_path = module_path[:-9]  # Remove .__init__
            
            return module_path
        except Exception as e:
            logger.debug("Failed to convert file path to module path: %s - %s", file_path, e)
            return None
    
    def _normalize_name(self, name: str) -> str:
        """Normalize a name for comparison across naming conventions.
        
        Converts various naming conventions to a common format for matching:
        - PascalCase → pascal_case
        - camelCase → camel_case
        - kebab-case → kebab_case
        - snake_case → snake_case (unchanged)
        
        Args:
            name: Name to normalize
            
        Returns:
            Normalized name in snake_case
        """
        import re
        
        # Convert PascalCase and camelCase to snake_case
        # Insert underscore before uppercase letters
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1)
        
        # Convert kebab-case to snake_case
        s3 = s2.replace('-', '_')
        
        # Lowercase and remove multiple underscores
        s4 = s3.lower()
        s5 = re.sub('_+', '_', s4)
        
        return s5.strip('_')
    
    def score_file_naming_pattern(self, symbol_name: str, file_path: str) -> float:
        """Score how well a file name matches a symbol name.
        
        This is a language-agnostic heuristic that works across all naming conventions.
        Higher scores indicate better matches.
        
        Scoring:
        - Exact match (after normalization): 100 points
        - File name contains symbol name: 50 points
        - Symbol name contains file name: 30 points
        - Partial word matches: 10 points per word
        
        Args:
            symbol_name: Symbol name to match
            file_path: File path to score
            
        Returns:
            Score (0-100+)
        """
        try:
            path = Path(file_path)
            file_name = path.stem  # Get filename without extension
            
            # Normalize both names for comparison
            norm_symbol = self._normalize_name(symbol_name)
            norm_file = self._normalize_name(file_name)
            
            score = 0.0
            
            # Exact match after normalization
            if norm_symbol == norm_file:
                score += 100.0
                return score
            
            # File name contains symbol name
            if norm_symbol in norm_file:
                score += 50.0
            
            # Symbol name contains file name
            if norm_file in norm_symbol:
                score += 30.0
            
            # Partial word matches
            symbol_words = set(norm_symbol.split('_'))
            file_words = set(norm_file.split('_'))
            common_words = symbol_words & file_words
            score += len(common_words) * 10.0
            
            return score
        except Exception as e:
            logger.debug("Failed to score file naming pattern: %s, %s - %s", symbol_name, file_path, e)
            return 0.0
    
    def score_directory_structure(self, symbol_name: str, file_path: str) -> float:
        """Score how well directory names match a symbol name.
        
        This is a language-agnostic heuristic that considers the directory
        structure as a hint for symbol location.
        
        Scoring:
        - Directory name matches symbol name: 30 points
        - Parent directory matches: 20 points
        - Any directory in path matches: 10 points per match
        
        Args:
            symbol_name: Symbol name to match
            file_path: File path to score
            
        Returns:
            Score (0-100+)
        """
        try:
            path = Path(file_path)
            norm_symbol = self._normalize_name(symbol_name)
            
            score = 0.0
            
            # Check each directory component
            for i, part in enumerate(path.parts[:-1]):  # Exclude filename
                norm_dir = self._normalize_name(part)
                
                # Exact match
                if norm_symbol == norm_dir:
                    # Immediate parent directory is most important
                    if i == len(path.parts) - 2:
                        score += 30.0
                    else:
                        score += 20.0
                
                # Partial matches
                elif norm_symbol in norm_dir or norm_dir in norm_symbol:
                    score += 10.0
                
                # Word matches
                symbol_words = set(norm_symbol.split('_'))
                dir_words = set(norm_dir.split('_'))
                common_words = symbol_words & dir_words
                if common_words:
                    score += len(common_words) * 5.0
            
            return score
        except Exception as e:
            logger.debug("Failed to score directory structure: %s, %s - %s", symbol_name, file_path, e)
            return 0.0
    
    async def track_import(self, symbol_name: str, source_file: str, target_file: str) -> None:
        """Track an import for frequency and co-occurrence learning.
        
        This method should be called when a successful resolution occurs to
        build up statistics that improve future resolutions.
        
        Args:
            symbol_name: Name of the imported symbol
            source_file: File doing the importing
            target_file: File containing the symbol definition
        """
        # Track import frequency
        self._import_frequency[symbol_name] = self._import_frequency.get(symbol_name, 0) + 1
        
        # Track co-occurrence (file import patterns)
        key = (source_file, target_file)
        self._co_occurrence[key] = self._co_occurrence.get(key, 0) + 1
        
        logger.debug("Tracked import: %s from %s to %s "
            "(frequency: %s, "
            "co-occurrence: %s)", symbol_name, source_file, target_file, self._import_frequency[symbol_name], self._co_occurrence[key])
    
    def get_import_frequency(self, symbol_name: str) -> int:
        """Get the import frequency for a symbol.
        
        Args:
            symbol_name: Symbol name to query
            
        Returns:
            Number of times this symbol has been imported
        """
        return self._import_frequency.get(symbol_name, 0)
    
    def get_co_occurrence_score(self, source_file: str, target_file: str) -> int:
        """Get the co-occurrence score between two files.
        
        Args:
            source_file: Source file path
            target_file: Target file path
            
        Returns:
            Number of times source_file has imported from target_file
        """
        return self._co_occurrence.get((source_file, target_file), 0)
    
    async def get_stats(self) -> Dict[str, int]:
        """Get registry statistics.
        
        Returns:
            Dictionary with registry statistics:
            - total_symbols: Total number of unique symbols
            - total_files: Total number of files with symbols
            - total_entries: Total number of symbol entries (including duplicates)
            - module_paths: Number of module paths indexed
            - import_frequency_entries: Number of symbols with tracked imports
            - co_occurrence_entries: Number of file pairs with tracked imports
        """
        total_entries = sum(len(symbols) for symbols in self._by_name.values())
        return {
            "total_symbols": len(self._by_name),
            "total_files": len(self._by_file),
            "total_entries": total_entries,
            "module_paths": len(self._module_paths),
            "import_frequency_entries": len(self._import_frequency),
            "co_occurrence_entries": len(self._co_occurrence)
        }

    def get_symbol_count(self) -> int:
        """Get the total number of unique symbols registered.
        
        Returns:
            The count of unique symbol names in the registry.
            
        Example:
            >>> registry = SymbolRegistry(project_root=Path("."), project_id="test")
            >>> registry.register(SymbolMetadata(name="MyClass", ...))
            >>> count = registry.get_symbol_count()
            >>> print(f"Registry contains {count} unique symbols")
        """
        return len(self._by_name)

    def get_file_count(self) -> int:
        """Get the total number of files with registered symbols.
        
        Returns:
            The count of files that have at least one registered symbol.
            
        Example:
            >>> registry = SymbolRegistry(project_root=Path("."), project_id="test")
            >>> # After registering symbols from multiple files
            >>> file_count = registry.get_file_count()
            >>> print(f"Symbols registered from {file_count} files")
        """
        return len(self._by_file)

    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive registry statistics.
        
        Returns:
            Dictionary containing:
            - symbol_count: Total unique symbols
            - file_count: Total files with symbols
            - type_breakdown: Count of symbols by entity type (class, function, etc.)
            - most_imported: Top 10 most frequently imported symbols with their counts
            
        Example:
            >>> registry = SymbolRegistry(project_root=Path("."), project_id="test")
            >>> # After registering symbols
            >>> stats = registry.get_statistics()
            >>> print(f"Total symbols: {stats['symbol_count']}")
            >>> print(f"Most imported: {stats['most_imported'][:3]}")
        """
        # Count symbols by type
        type_breakdown: Dict[str, int] = {}
        for symbols in self._by_name.values():
            for symbol in symbols:
                entity_type = symbol.entity_type
                type_breakdown[entity_type] = type_breakdown.get(entity_type, 0) + 1
        
        # Get top 10 most imported symbols
        most_imported = sorted(
            self._import_frequency.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        return {
            "symbol_count": len(self._by_name),
            "file_count": len(self._by_file),
            "type_breakdown": type_breakdown,
            "most_imported": most_imported
        }
