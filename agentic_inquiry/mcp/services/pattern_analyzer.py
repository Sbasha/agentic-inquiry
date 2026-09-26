"""Pattern discovery service using embedding clustering.

This module provides pattern analysis capabilities by clustering similar code chunks
using K-means clustering on embeddings. It identifies representative examples from
each cluster and calculates diversity scores.
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import numpy as np

from agentic_inquiry.storage.facade import StorageFacade

if TYPE_CHECKING:
    from agentic_inquiry.embeddings.service import EmbeddingService

logger = logging.getLogger(__name__)


class PatternAnalyzer:
    """Discovers patterns via embedding clustering.

    Uses K-means clustering to identify similar code patterns and selects
    representative examples from each cluster. No LLM inference - pure vector math.
    """

    def __init__(self, search_service: Any, db_manager: StorageFacade, embedding_service: "EmbeddingService"):
        """Initialize pattern analyzer.

        Args:
            search_service: SearchService instance for querying
            db_manager: StorageFacade instance providing unified storage access
            embedding_service: EmbeddingService instance for generating query embeddings
        """
        # Architectural discovery clusters stored chunk vectors read from here
        self._storage = db_manager
        self.search = search_service
        self.embedding_service = embedding_service
    
    async def find_patterns(
        self,
        project_id: str,
        pattern_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Find patterns in the codebase."""
        logger.info(
            "Finding patterns for project_id=%s, pattern_type=%s, limit=%s",
            project_id, pattern_type, limit
        )

        if pattern_type == "architectural":
            return await self._find_architectural_patterns(project_id, limit)
        
        # Original query-based behavior for specific types
        pattern_queries = self._get_pattern_queries(pattern_type)
        all_patterns = []
        for query_info in pattern_queries:
            patterns = await self._find_patterns_by_query(project_id, query_info, limit)
            all_patterns.extend(patterns)
            
        all_patterns.sort(key=lambda x: x.get("count", 0), reverse=True)
        return all_patterns[:limit]

    async def _find_architectural_patterns(self, project_id: str, limit: int) -> List[Dict[str, Any]]:
        """Discover architectural patterns via global clustering."""
        try:
            # 1. Fetch all project vectors efficiently
            # Note: We only need vector, content, and file_path
            raw_records = await self._storage.query_raw(
                table_name="document_chunks",
                filters={"project_id": project_id},
                limit=1000 # Cap for performance
            )
            
            # Filter to only records that have vectors (crucial for clustering alignment)
            records = [r for r in raw_records if r.get("vector") is not None]
            
            if len(records) < 10:
                logger.info("Insufficient records for architectural clustering")
                return []
                
            X = np.array([r["vector"] for r in records])
            
            # 2. Perform clustering
            from sklearn.cluster import KMeans
            n_clusters = max(2, min(5, len(records) // 5))
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(X)
            
            # 3. Analyze clusters
            patterns: List[Dict[str, Any]] = []
            for i in range(n_clusters):
                cluster_indices = np.where(labels == i)[0]
                cluster_records = [records[idx] for idx in cluster_indices]
                
                # Get representatives
                centroid = kmeans.cluster_centers_[i]
                distances = [np.linalg.norm(X[idx] - centroid) for idx in cluster_indices]
                closest_indices = np.argsort(distances)[:3]
                representatives = [cluster_records[idx] for idx in closest_indices]
                
                name = self._infer_pattern_name(representatives, "architectural")
                
                examples = []
                for r in representatives:
                    examples.append({
                        "file_path": r.get("file_path", ""),
                        "snippet": r.get("content", "")[:200],
                        "line_start": r.get("line_start", 0)
                    })
                    
                patterns.append({
                    "name": name,
                    "type": "architectural",
                    "count": len(cluster_records),
                    "examples": examples,
                    "prevalence": len(cluster_records) / len(records)
                })

            patterns.sort(key=lambda x: x["count"], reverse=True)
            return patterns[:limit]
            
        except Exception as e:
            logger.error("Architectural pattern discovery failed: %s", e, exc_info=True)
            return []

    async def _find_patterns_by_query(self, project_id: str, query_info: Dict[str, str], limit: int) -> List[Dict[str, Any]]:
        """Existing logic for query-based clustering (refactored)."""
        query_text = query_info["query"]
        query_pattern_type = query_info["type"]
        
        try:
            query_vector = await self.embedding_service.embed_async(query_text)
            results = await self.search.hybrid_search(
                query_vector=query_vector.tolist(),
                query_fts=query_text,
                limit=50,
                project_id=project_id
            )
            
            if len(results) < 3:
                return []

            texts_to_embed = []
            valid_results = []
            for r in results:
                data = r.data if hasattr(r, 'data') else r
                content = data.get("content", "")
                if content and len(content) > 10:
                    valid_results.append(r)
                    texts_to_embed.append(content[:2000])

            if len(texts_to_embed) < 3:
                return []
            
            # Use batch embedding as suggested by specialist
            batch_embeddings = await self.embedding_service.embed_batch_async(texts_to_embed)
            X = np.array([emb.tolist() for emb in batch_embeddings])
            
            from sklearn.cluster import KMeans
            n_clusters = max(2, min(3, len(valid_results) // 3))
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(X)
            
            patterns = []
            for i in range(n_clusters):
                cluster_indices = np.where(labels == i)[0]
                cluster_results = [valid_results[idx] for idx in cluster_indices]
                centroid = kmeans.cluster_centers_[i]
                distances = [np.linalg.norm(X[idx] - centroid) for idx in cluster_indices]
                representatives = [cluster_results[idx] for idx in np.argsort(distances)[:3]]
                
                name = self._infer_pattern_name(representatives, query_pattern_type)
                examples = []
                for r in representatives:
                    data = r.data if hasattr(r, 'data') else r
                    examples.append({
                        "file_path": data.get("file_path", ""),
                        "snippet": data.get("content", "")[:200],
                        "line_start": data.get("line_start", 0)
                    })
                
                patterns.append({
                    "name": name, "type": query_pattern_type, "count": len(cluster_results),
                    "examples": examples, "prevalence": len(cluster_results) / len(valid_results)
                })
            return patterns
        except Exception as e:
            logger.debug("Query-based clustering failed for %s: %s", query_pattern_type, e)
            return []

    
    def _get_pattern_queries(self, pattern_type: Optional[str]) -> List[Dict[str, str]]:
        """Get search queries for different pattern types.
        
        Args:
            pattern_type: Type of patterns to find, or None for all
            
        Returns:
            List of query dictionaries with 'query' and 'type' keys
        """
        all_queries = {
            "architectural": [
                {"query": "MVC model view controller architecture", "type": "architectural"},
                {"query": "dependency injection container service", "type": "architectural"},
                {"query": "factory pattern create instance", "type": "architectural"},
                {"query": "repository pattern data access", "type": "architectural"},
                {"query": "service layer business logic", "type": "architectural"},
            ],
            "design": [
                {"query": "singleton pattern instance", "type": "design"},
                {"query": "observer pattern subscribe notify", "type": "design"},
                {"query": "strategy pattern algorithm", "type": "design"},
                {"query": "decorator pattern wrapper", "type": "design"},
                {"query": "adapter pattern interface", "type": "design"},
            ],
            "naming": [
                {"query": "naming convention variable function", "type": "naming"},
                {"query": "camelCase snake_case naming", "type": "naming"},
                {"query": "class name convention", "type": "naming"},
                {"query": "constant naming uppercase", "type": "naming"},
            ],
            "antipattern": [
                {"query": "god class too many responsibilities", "type": "antipattern"},
                {"query": "code duplication repeated logic", "type": "antipattern"},
                {"query": "magic number hardcoded value", "type": "antipattern"},
                {"query": "long method too many lines", "type": "antipattern"},
            ]
        }
        
        if pattern_type is None or pattern_type == "auto":
            # Return all queries
            result = []
            for queries in all_queries.values():
                result.extend(queries)
            return result
        elif pattern_type in all_queries:
            return all_queries[pattern_type]
        else:
            logger.warning("Unknown pattern type: %s, using all types", pattern_type)
            result = []
            for queries in all_queries.values():
                result.extend(queries)
            return result
    
    def _infer_pattern_name(
        self, examples: list, pattern_type: str
    ) -> str:
        """Infer specific pattern name from examples."""
        snippets = []
        for example in examples:
            data = example.data if hasattr(example, 'data') else example
            content = data.get("content", "") or data.get("text", "")
            snippets.append(content)
        
        combined = " ".join(snippets).lower()
        
        if pattern_type in ("architectural", "auto"):
            if any(x in combined for x in ("service", "manager", "registry")):
                return "Service/Manager Layer"
            if any(x in combined for x in ("model", "schema", "table", "entity")):
                return "Data Model Layer"
            if any(x in combined for x in ("adapter", "connector", "provider")):
                return "Adapter/Provider Pattern"
            if any(x in combined for x in ("test", "mock", "fixture")):
                return "Testing Infrastructure"
            if any(x in combined for x in ("parser", "chain", "grammar")):
                return "Parsing/Semantic Layer"
            if any(x in combined for x in ("api", "route", "mcp", "tool")):
                return "API/Interface Layer"
            if "factory" in combined or "create" in combined:
                return "Factory Pattern"
            if "inject" in combined or "dependency" in combined:
                return "Dependency Injection"
            if "repository" in combined or "data access" in combined:
                return "Repository Pattern"
            if "controller" in combined or "view" in combined:
                return "MVC Architecture"
            
            return "Architectural Pattern"
                
        if pattern_type == "design":
            if "singleton" in combined:
                return "Singleton Pattern"
            elif "observer" in combined or "subscribe" in combined:
                return "Observer Pattern"
            elif "strategy" in combined:
                return "Strategy Pattern"
            elif "decorator" in combined or "wrapper" in combined:
                return "Decorator Pattern"
            elif "adapter" in combined:
                return "Adapter Pattern"
            else:
                return "Design Pattern"
                
        elif pattern_type == "naming":
            if "camel" in combined or "CamelCase" in " ".join(snippets):
                return "CamelCase Convention"
            elif "_" in combined:
                return "Snake_case Convention"
            elif "UPPER" in " ".join(snippets) or combined.isupper():
                return "UPPERCASE Convention"
            else:
                return "Naming Convention"
                
        elif pattern_type == "antipattern":
            if "god" in combined or "too many" in combined:
                return "God Class Antipattern"
            elif "duplicate" in combined or "repeated" in combined:
                return "Code Duplication"
            elif "magic" in combined or "hardcoded" in combined:
                return "Magic Numbers"
            elif "long" in combined:
                return "Long Method"
            else:
                return "Code Smell"
        
        return f"{pattern_type.title()} Pattern"
