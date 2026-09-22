"""Search result deduplication for improved result diversity."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class SearchDeduplicator:
    """Removes duplicate files from search results to improve diversity.
    
    This class implements file-level deduplication with configurable thresholds:
    - Groups results by file_path
    - Keeps highest-scoring chunk(s) per file
    - Maintains overall relevance ordering
    - Calculates diversity metrics
    
    Example:
        >>> deduplicator = SearchDeduplicator(max_results_per_file=1)
        >>> results = [
        ...     {"file_path": "a.py", "relevance_score": 0.9, "id": "1"},
        ...     {"file_path": "b.py", "relevance_score": 0.8, "id": "2"},
        ...     {"file_path": "a.py", "relevance_score": 0.7, "id": "3"},
        ... ]
        >>> deduplicated = deduplicator.deduplicate_results(results)
        >>> len(deduplicated)  # Only 2 results (highest from each file)
        2
        >>> deduplicator.calculate_diversity_score(results)
        0.6666666666666666  # 2 unique files / 3 total results
    """
    
    def __init__(
        self,
        max_results_per_file: int = 2,
        min_diversity_ratio: float = 0.7,
    ):
        """Initialize SearchDeduplicator.
        
        Args:
            max_results_per_file: Maximum number of results to keep per file.
                                 1 = keep only highest-scoring chunk per file.
            min_diversity_ratio: Minimum acceptable diversity ratio (0.0-1.0).
                                If diversity falls below this, a warning is logged.
        """
        self.max_results_per_file = max_results_per_file
        self.min_diversity_ratio = min_diversity_ratio
    
    def deduplicate_results(
        self,
        results: List[Dict[str, Any]],
        preserve_order: bool = True,
    ) -> List[Dict[str, Any]]:
        """Deduplicate search results by file path.
        
        Strategy:
        1. Group results by file_path
        2. Keep top N results per file (by relevance_score or _distance)
        3. Maintain overall relevance ordering if preserve_order=True
        
        Args:
            results: List of search results from database
            preserve_order: Whether to maintain original relevance ordering
        
        Returns:
            Deduplicated results with at most max_results_per_file per file
        """
        if not results:
            return results
        
        # Group results by file_path
        results_by_file: Dict[str, List[Dict[str, Any]]] = {}
        for result in results:
            file_path = result.get("file_path", "")
            if not file_path:
                # If no file_path, treat as unique (shouldn't happen in practice)
                file_path = f"_unknown_{id(result)}"
            
            if file_path not in results_by_file:
                results_by_file[file_path] = []
            results_by_file[file_path].append(result)
        
        # For each file, keep only the top N results
        deduplicated = []
        for file_path, file_results in results_by_file.items():
            # Sort by relevance (higher is better) or distance (lower is better)
            if file_results and ("score" in file_results[0] or "relevance_score" in file_results[0]):
                # Sort by score or relevance_score (higher is better)
                sorted_results = sorted(
                    file_results,
                    key=lambda x: x.get("score", x.get("relevance_score", 0.0)),
                    reverse=True
                )
            elif file_results and "_distance" in file_results[0]:
                # Sort by _distance (lower is better for LanceDB)
                sorted_results = sorted(
                    file_results,
                    key=lambda x: x.get("_distance", float("inf"))
                )
            else:
                # No scoring field, keep original order
                sorted_results = file_results
            
            # Keep top N results for this file
            top_results = sorted_results[:self.max_results_per_file]
            deduplicated.extend(top_results)
        
        # Preserve original relevance ordering if requested
        if preserve_order:
            # Create a mapping of result IDs to their original positions
            original_positions = {}
            for i, result in enumerate(results):
                result_id = result.get("id") or id(result)  # Use canonical 'id' field
                original_positions[result_id] = i

            # Sort deduplicated results by original position
            deduplicated.sort(
                key=lambda x: original_positions.get(
                    x.get("id") or id(x),  # Use canonical 'id' field
                    float("inf")
                )
            )
        
        # Log diversity metrics
        diversity = self.calculate_diversity_score(results)
        dedup_diversity = self.calculate_diversity_score(deduplicated)
        
        logger.debug(
            "Deduplication: %d results -> %d results (diversity: %.2f -> %.2f)",
            len(results),
            len(deduplicated),
            diversity,
            dedup_diversity
        )
        
        # Warn if diversity is below threshold
        if dedup_diversity < self.min_diversity_ratio:
            logger.warning(
                "Search result diversity (%.2f) is below minimum threshold (%.2f). "
                "Consider adjusting search parameters or deduplication settings.",
                dedup_diversity,
                self.min_diversity_ratio
            )
        
        return deduplicated
    
    def calculate_diversity_score(self, results: List[Dict[str, Any]]) -> float:
        """Calculate diversity as ratio of unique files to total results.
        
        Args:
            results: List of search results
        
        Returns:
            Diversity score between 0.0 and 1.0, where:
            - 1.0 = all results from different files (maximum diversity)
            - 0.0 = all results from same file (no diversity)
        """
        if not results:
            return 1.0  # Empty results are considered maximally diverse
        
        # Count unique file paths
        unique_files = set()
        for result in results:
            file_path = result.get("file_path", "")
            if file_path:
                unique_files.add(file_path)
        
        # Calculate diversity ratio
        diversity = len(unique_files) / len(results)
        return diversity
