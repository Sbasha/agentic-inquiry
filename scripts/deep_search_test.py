"""Deep search test suite for agv search relevance improvement.

Runs 10 queries against a large-scale production index and scores results.
Categories: keyword (exact match), conceptual (semantic), structural (architecture).

Usage:
    uv run --env-file .env python scripts/deep_search_test.py [--env gcp-meta] [--limit 20]
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class QueryTest:
    """A test query with expected results."""
    id: int
    category: str  # keyword, conceptual, structural
    query: str
    expected_patterns: list[str]  # patterns that SHOULD appear in results
    expected_files: list[str]  # file path patterns that SHOULD appear
    weight: float = 1.0


@dataclass
class QueryResult:
    """Result of running a test query."""
    test: QueryTest
    results: list[dict]
    score: float = 0.0
    max_score: float = 0.0
    matched_patterns: list[str] = field(default_factory=list)
    matched_files: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    notes: str = ""


# ── Test suite ──────────────────────────────────────────────────────
TEST_QUERIES = [
    # KEYWORD queries (exact identifier match)
    QueryTest(
        id=1,
        category="keyword",
        query="UserAuthenticationAdapter",
        expected_patterns=["Authentication", "Adapter", "user"],
        expected_files=["authentication", "adapter", "Adapter"],
        weight=1.5,
    ),
    QueryTest(
        id=2,
        category="keyword",
        query="SessionServlet doPost",
        expected_patterns=["SessionServlet", "doPost", "servlet"],
        expected_files=["SessionServlet", "session"],
        weight=1.0,
    ),
    QueryTest(
        id=3,
        category="keyword",
        query="ExternalApiVerificationManager",
        expected_patterns=["External", "Verification", "Manager"],
        expected_files=["external", "verification"],
        weight=1.0,
    ),
    # CONCEPTUAL queries (semantic understanding)
    QueryTest(
        id=4,
        category="conceptual",
        query="how does user authentication work",
        expected_patterns=["authentication", "user", "login", "session", "token"],
        expected_files=["auth", "login", "manager"],
        weight=1.5,
    ),
    QueryTest(
        id=5,
        category="conceptual",
        query="payment processing and transaction management",
        expected_patterns=["payment", "transaction", "processing", "service"],
        expected_files=["payment", "transaction", "service"],
        weight=1.0,
    ),
    QueryTest(
        id=6,
        category="conceptual",
        query="access control and permission rules",
        expected_patterns=["access", "control", "permission", "role"],
        expected_files=["access", "permission", "security"],
        weight=1.0,
    ),
    # STRUCTURAL queries (architecture/flow)
    QueryTest(
        id=7,
        category="structural",
        query="workflow process invocation service",
        expected_patterns=["workflow", "process", "invocation", "service"],
        expected_files=["workflow", "process", "service"],
        weight=1.0,
    ),
    QueryTest(
        id=8,
        category="structural",
        query="Spring controller for web forms",
        expected_patterns=["Controller", "Form", "Spring"],
        expected_files=["controller", "Controller", "form"],
        weight=1.0,
    ),
    QueryTest(
        id=9,
        category="structural",
        query="data access layer for user entity",
        expected_patterns=["User", "DAO", "dao", "data", "access", "repository"],
        expected_files=["user", "User", "dao", "Dao"],
        weight=1.0,
    ),
    QueryTest(
        id=10,
        category="structural",
        query="lookup service manager architecture",
        expected_patterns=["Lookup", "Service", "Manager", "lookup", "architecture"],
        expected_files=["lookup", "Lookup", "LookupService"],
        weight=1.0,
    ),
]


def score_result(test: QueryTest, results: list[dict]) -> QueryResult:
    """Score search results against expected patterns."""
    qr = QueryResult(test=test, results=results)

    if not results:
        qr.notes = "NO RESULTS"
        return qr

    # Collect all text from results for pattern matching
    # Include file_path in text matching — finding the right file IS valuable
    all_text = ""
    all_files = ""
    for r in results[:20]:  # score top 20
        text = r.get("text", "") or r.get("content", "") or r.get("chunk_text", "")
        file_path = r.get("file_path", "")
        all_text += f" {text} {file_path}"
        all_files += f" {file_path}"

    # Score pattern matches (case-insensitive)
    for pattern in test.expected_patterns:
        if pattern.lower() in all_text.lower():
            qr.matched_patterns.append(pattern)

    # Score file path matches
    for fp in test.expected_files:
        if fp.lower() in all_files.lower():
            qr.matched_files.append(fp)

    # Calculate score
    # Pattern match: 60% weight
    pattern_score = len(qr.matched_patterns) / len(test.expected_patterns) if test.expected_patterns else 0
    # File path match: 40% weight
    file_score = len(qr.matched_files) / len(test.expected_files) if test.expected_files else 0

    # Bonus: top result relevance (is the #1 result actually relevant?)
    top_result = results[0]
    top_text = (top_result.get("text", "") or top_result.get("content", "") or "").lower()
    top_file = (top_result.get("file_path", "") or "").lower()
    top_bonus = 0.0
    # Check if any key pattern appears in the top result
    key_patterns = test.expected_patterns[:2]  # first 2 patterns are most important
    for p in key_patterns:
        if p.lower() in top_text or p.lower() in top_file:
            top_bonus = 0.1
            break

    raw_score = (pattern_score * 0.6 + file_score * 0.4 + top_bonus) * 10.0
    qr.score = min(10.0, raw_score)
    qr.max_score = 10.0

    # Note about result quality
    if qr.score >= 8.0:
        qr.notes = "EXCELLENT"
    elif qr.score >= 6.0:
        qr.notes = "GOOD"
    elif qr.score >= 4.0:
        qr.notes = "FAIR"
    elif qr.score >= 2.0:
        qr.notes = "POOR"
    else:
        qr.notes = "VERY POOR"

    return qr


async def run_search(query: str, limit: int = 20, env_name: str = "alloydb") -> list[dict]:
    """Run a agv hybrid search and return results."""
    from agent_vault.cli.env_resolver import load_config_for_environment
    from agent_vault.embeddings.factory import configure_embedder_for_backend
    from agent_vault.search.service import SearchService
    from agent_vault.storage.facade import StorageFacade

    # Load config via environment resolver
    config = load_config_for_environment(None)
    configure_embedder_for_backend(config, quiet=True)

    # Create storage and search
    storage = await StorageFacade.from_config(config, "default")

    try:
        search_service = SearchService(storage=storage, config=config)

        # For AlloyDB (server-side embeddings), pass query text as the vector
        backend_type = getattr(storage, "_backend_type", "lancedb")
        if backend_type == "alloydb":
            # AlloyDB vector_search accepts text strings for server-side embedding
            query_vector = query
        else:
            # For local embedding backends
            from agent_vault.embeddings.service import EmbeddingService
            embed_service = EmbeddingService()
            query_vector = await embed_service.embed_async(query)

        # Run hybrid search
        results = await search_service.hybrid_search(
            query_vector=query_vector,
            query_fts=query,
            limit=limit,
        )

        # Convert to flat dicts for scoring
        result_dicts = []
        for r in results:
            if hasattr(r, "data") and isinstance(r.data, dict):
                d = dict(r.data)
                d["relevance_score"] = getattr(r, "score", 0)
                d["source"] = getattr(r, "source", "")
                result_dicts.append(d)
            elif hasattr(r, "to_dict"):
                rd = r.to_dict()
                # Flatten nested data dict if present
                if "data" in rd and isinstance(rd["data"], dict):
                    d = dict(rd["data"])
                    d["relevance_score"] = rd.get("score", 0)
                    d["source"] = rd.get("source", "")
                    result_dicts.append(d)
                else:
                    result_dicts.append(rd)
            else:
                result_dicts.append(r)

        return result_dicts
    finally:
        await storage.close()


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Deep search test suite")
    parser.add_argument("--env", default="alloydb", help="agv environment name")
    parser.add_argument("--limit", type=int, default=20, help="Results per query")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args()

    print("=" * 70)
    print("agv DEEP SEARCH TEST SUITE")
    print(f"Environment: {args.env}  |  Limit: {args.limit}")
    print("=" * 70)

    all_results = []
    category_scores = {"keyword": [], "conceptual": [], "structural": []}

    for test in TEST_QUERIES:
        print(f"\n--- Query {test.id} [{test.category}] ---")
        print(f"  Q: {test.query}")

        start = time.time()
        try:
            results = await run_search(test.query, limit=args.limit, env_name=args.env)
        except Exception as e:
            print(f"  ERROR: {e}")
            results = []
        elapsed = (time.time() - start) * 1000

        qr = score_result(test, results)
        qr.elapsed_ms = elapsed

        all_results.append(qr)
        category_scores[test.category].append(qr.score * test.weight)

        print(f"  Results: {len(results)} | Score: {qr.score:.1f}/10 | {qr.notes}")
        print(f"  Patterns matched: {qr.matched_patterns}")
        print(f"  Files matched: {qr.matched_files}")
        print(f"  Time: {elapsed:.0f}ms")

        if results:
            top = results[0]
            fp = top.get("file_path", "?")
            score = top.get("relevance_score", 0)
            print(f"  Top result: {fp} (score={score:.3f})")

    # ── Summary ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_score = 0.0
    total_weight = 0.0
    for qr in all_results:
        total_score += qr.score * qr.test.weight
        total_weight += 10.0 * qr.test.weight

    overall = (total_score / total_weight) * 10.0 if total_weight > 0 else 0.0

    print(f"\n  OVERALL SCORE: {overall:.1f}/10")
    print()

    for cat in ["keyword", "conceptual", "structural"]:
        scores = category_scores[cat]
        if scores:
            cat_tests = [t for t in TEST_QUERIES if t.category == cat]
            cat_weight = sum(t.weight for t in cat_tests)
            cat_total = sum(scores) / (10.0 * cat_weight) * 10.0 if cat_weight > 0 else 0.0
            print(f"  {cat.upper():12s}: {cat_total:.1f}/10  ({len(scores)} queries)")

    print()
    for qr in all_results:
        emoji = "O" if qr.score >= 6.0 else "X" if qr.score < 4.0 else "~"
        print(f"  [{emoji}] Q{qr.test.id:2d} ({qr.test.category:11s}) {qr.score:4.1f}/10  {qr.test.query[:50]}")

    # Save JSON output
    if args.output:
        output_data = {
            "overall_score": overall,
            "category_scores": {
                cat: sum(category_scores[cat]) / (10.0 * sum(t.weight for t in TEST_QUERIES if t.category == cat)) * 10.0
                for cat in ["keyword", "conceptual", "structural"]
            },
            "queries": [
                {
                    "id": qr.test.id,
                    "category": qr.test.category,
                    "query": qr.test.query,
                    "score": qr.score,
                    "result_count": len(qr.results),
                    "matched_patterns": qr.matched_patterns,
                    "matched_files": qr.matched_files,
                    "elapsed_ms": qr.elapsed_ms,
                    "notes": qr.notes,
                    "top_results": [
                        {
                            "file_path": r.get("file_path", ""),
                            "relevance_score": r.get("relevance_score", 0),
                            "text_preview": (r.get("text", "") or r.get("content", ""))[:200],
                        }
                        for r in qr.results[:5]
                    ],
                }
                for qr in all_results
            ],
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\n  Results saved to: {args.output}")

    print()
    return overall


if __name__ == "__main__":
    score = asyncio.run(main())
    sys.exit(0 if score >= 7.0 else 1)
