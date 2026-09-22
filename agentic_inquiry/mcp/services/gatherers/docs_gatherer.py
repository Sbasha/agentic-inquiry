# agentic_inquiry/mcp/services/gatherers/docs_gatherer.py
"""Documentation context gatherer implementation."""
import logging
from typing import Any, Dict, List

from agentic_inquiry.search.service import SearchService
from agentic_inquiry.mcp.services.token_optimizer import TokenOptimizer
from agentic_inquiry.database.results import SearchResult
from .protocol import ContextGathererProtocol, GatherContext

logger = logging.getLogger(__name__)

# Documentation file extensions
DOC_EXTENSIONS = frozenset({
    '.md', '.txt', '.rst', '.adoc', '.asciidoc', '.org', '.tex',
    '.pdf', '.docx', '.html', '.htm'
})


class DocsGatherer(ContextGathererProtocol):
    """Gathers context from documentation files.

    Uses hybrid search to find relevant documentation chunks and converts them
    to standardized context items while respecting token budget.
    """

    def __init__(
        self,
        search_service: SearchService,
        token_optimizer: TokenOptimizer
    ) -> None:
        """Initialize docs gatherer.

        Args:
            search_service: Search service for finding documentation
            token_optimizer: Token optimizer for creating snippets
        """
        self.search = search_service
        self.token_optimizer = token_optimizer

    @property
    def gatherer_type(self) -> str:
        """Return gatherer type."""
        return "documentation"

    async def gather(self, context: GatherContext) -> List[Dict[str, Any]]:
        """Gather relevant documentation chunks.

        Args:
            context: Gather context with query, budget, depth, etc.

        Returns:
            List of documentation context items
        """
        if not context.project_id:
            logger.warning("No project_id provided for docs gathering")
            return []

        # Determine limit based on depth
        limit_map = {"focused": 8, "broad": 10, "comprehensive": 20}
        limit = limit_map.get(context.depth, 10)

        logger.info(
            "Searching for documentation: query=%s, limit=%s, project_id=%s, include_overview=%s",
            context.query, limit, context.project_id, context.include_overview
        )

        try:
            # Use pre-computed query vector if provided, otherwise compute it
            query_vector = context.query_vector
            if query_vector is None:
                query_vector_array = await self.search.embedding_service.embed_async(context.query)
                query_vector = query_vector_array.tolist()

            # Search for documentation - increase limit to allow for filtering
            search_limit = limit * 2
            results = await self.search.hybrid_search(
                query_vector=query_vector,
                query_fts=context.query,
                limit=search_limit,
                project_id=context.project_id,
                boost_overview=context.include_overview
            )

            logger.info("Search returned %s results", len(results))

            # Filter for documentation files
            doc_results = []
            for r in results:
                if not isinstance(r, SearchResult):
                    logger.warning("Skipping non-SearchResult item in docs gatherer: %s", r)
                    continue
                file_path = r.data.get("file_path", "")
                matches = any(file_path.endswith(ext) for ext in DOC_EXTENSIONS)
                logger.debug("Checking file_path=%s, matches_doc=%s", file_path, matches)
                if matches:
                    doc_results.append(r)

            logger.info("Filtered to %s documentation results", len(doc_results))

            # Convert to context items and fit into budget
            doc_items: List[Dict[str, Any]] = []
            for result in doc_results[:limit]:
                item = self._result_to_context_item(result.data, context.query)

                # Check if we can add this item
                item_text = f"{item['summary']} {item['snippet']}"
                if context.budget.can_add(item_text):
                    context.budget.add(item_text)
                    doc_items.append(item)
                else:
                    logger.debug("Skipping doc item %s - budget exceeded", item['id'])
                    break

            logger.info("Converted to %s documentation context items", len(doc_items))
            return doc_items

        except Exception as e:
            logger.error("Error gathering documentation context: %s", e, exc_info=True)
            return []

    def _result_to_context_item(
        self,
        result: Dict[str, Any],
        query: str
    ) -> Dict[str, Any]:
        """Convert search result to context item dictionary.

        Args:
            result: Search result dictionary
            query: Original query

        Returns:
            Context item dictionary
        """
        # Extract relevance score (distance is inverted - lower is better)
        distance = result.get("_distance", 1.0)
        relevance_score = max(0.0, 1.0 - distance)

        # Create snippet from content
        content = result.get("content", "")
        snippet = self.token_optimizer.create_snippet(content, max_tokens=125)

        # Generate why_relevant explanation
        why_relevant = self._explain_relevance(result, relevance_score)

        # Extract metadata for documentation
        metadata: Dict[str, Any] = {}
        metadata["section"] = result.get(
            "section",
            result.get("metadata", {}).get("section", "")
        )

        return {
            "id": result.get("id", ""),
            "type": "documentation",
            "name": result.get("name", result.get("title", "Unknown")),
            "summary": result.get("summary", "")[:200],
            "relevance_score": relevance_score,
            "location": result.get("file_path", result.get("location", "")),
            "snippet": snippet,
            "metadata": metadata,
            "why_relevant": why_relevant
        }

    def _explain_relevance(
        self,
        result: Dict[str, Any],
        relevance_score: float
    ) -> str:
        """Generate explanation of why item is relevant.

        Args:
            result: Search result
            relevance_score: Relevance score

        Returns:
            Explanation string
        """
        explanations = []

        # Relevance score
        if relevance_score > 0.8:
            explanations.append("highly relevant")
        elif relevance_score > 0.6:
            explanations.append("relevant")
        else:
            explanations.append("potentially relevant")

        # Entity type
        entity_type = result.get("type", "")
        if entity_type:
            explanations.append(f"contains {entity_type}")

        return f"Match: {', '.join(explanations)} (score: {relevance_score:.2f})"
