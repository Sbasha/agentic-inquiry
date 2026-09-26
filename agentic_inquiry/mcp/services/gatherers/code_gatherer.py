# agentic_inquiry/mcp/services/gatherers/code_gatherer.py
"""Code context gatherer implementation."""

import logging
from typing import Any, Dict, List

from agentic_inquiry.search.service import SearchService
from agentic_inquiry.mcp.services.token_optimizer import TokenOptimizer
from agentic_inquiry.database.results import SearchResult
from .protocol import ContextGathererProtocol, GatherContext

logger = logging.getLogger(__name__)

# Code file extensions
CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".js",
        ".tsx",
        ".jsx",
        ".java",
        ".cpp",
        ".c",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".cs",
        ".scala",
        ".r",
        ".m",
        ".h",
        ".hpp",
    }
)


class CodeGatherer(ContextGathererProtocol):
    """Gathers context from source code files.

    Uses hybrid search to find relevant code chunks and converts them
    to standardized context items while respecting token budget.
    """

    def __init__(
        self, search_service: SearchService, token_optimizer: TokenOptimizer
    ) -> None:
        """Initialize code gatherer.

        Args:
            search_service: Search service for finding code
            token_optimizer: Token optimizer for creating snippets
        """
        self.search = search_service
        self.token_optimizer = token_optimizer

    @property
    def gatherer_type(self) -> str:
        """Return gatherer type."""
        return "code"

    async def gather(self, context: GatherContext) -> List[Dict[str, Any]]:
        """Gather relevant code chunks.

        Args:
            context: Gather context with query, budget, depth, etc.

        Returns:
            List of code context items
        """
        if not context.project_id:
            logger.warning("No project_id provided for code gathering")
            return []

        # Determine limit based on depth
        limit_map = {"focused": 10, "broad": 15, "comprehensive": 30}
        limit = limit_map.get(context.depth, 15)

        logger.info(
            "Searching for code: query=%s, limit=%s, project_id=%s, include_overview=%s",
            context.query,
            limit,
            context.project_id,
            context.include_overview,
        )

        try:
            # Use pre-computed query vector if provided, otherwise compute it
            query_vector = context.query_vector
            if query_vector is None:
                query_vector_array = await self.search.embedding_service.embed_async(
                    context.query
                )
                query_vector = query_vector_array.tolist()

            # Search for code - increase limit to allow for filtering
            search_limit = limit * 2
            results = await self.search.hybrid_search(
                query_vector=query_vector,
                query_fts=context.query,
                limit=search_limit,
                project_id=context.project_id,
                boost_overview=context.include_overview,
            )

            logger.info("Search returned %s results", len(results))

            # Filter for code files
            code_results = [
                r
                for r in results
                if isinstance(r, SearchResult)
                and any(
                    r.data.get("file_path", "").endswith(ext) for ext in CODE_EXTENSIONS
                )
            ]

            logger.info("Filtered to %s code results", len(code_results))

            # Convert to context items and fit into budget
            code_items: List[Dict[str, Any]] = []
            for result in code_results[:limit]:
                item = self._result_to_context_item(result.data, context.query)

                # Check if we can add this item
                item_text = f"{item['summary']} {item['snippet']}"
                if context.budget.can_add(item_text):
                    context.budget.add(item_text)
                    code_items.append(item)
                else:
                    logger.debug("Skipping code item %s - budget exceeded", item["id"])
                    break

            logger.info("Converted to %s code context items", len(code_items))
            return code_items

        except Exception as e:
            logger.error("Error gathering code context: %s", e, exc_info=True)
            return []

    def _result_to_context_item(
        self, result: Dict[str, Any], query: str
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

        # Extract metadata
        metadata: Dict[str, Any] = {}
        metadata["language"] = result.get(
            "language", result.get("metadata", {}).get("language", "unknown")
        )
        metadata["type"] = result.get("type", "")
        metadata["line_start"] = result.get(
            "line_start", result.get("metadata", {}).get("line_start", 0)
        )
        metadata["line_end"] = result.get(
            "line_end", result.get("metadata", {}).get("line_end", 0)
        )

        # Extract symbols if available
        symbols = result.get("symbols", result.get("metadata", {}).get("symbols", []))
        if symbols:
            metadata["symbols"] = symbols

        return {
            "id": result.get("id", ""),
            "type": "code",
            "name": result.get("name", result.get("title", "Unknown")),
            "summary": result.get("summary", "")[:200],
            "relevance_score": relevance_score,
            "location": result.get("file_path", result.get("location", "")),
            "snippet": snippet,
            "metadata": metadata,
            "why_relevant": why_relevant,
        }

    def _explain_relevance(self, result: Dict[str, Any], relevance_score: float) -> str:
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

        # Language
        language = result.get("language", "")
        if language:
            explanations.append(f"{language} code")

        return f"Match: {', '.join(explanations)} (score: {relevance_score:.2f})"
