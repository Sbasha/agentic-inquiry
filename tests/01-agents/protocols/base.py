"""
Shared helpers for UAT protocol modules.

All protocol modules use these helpers for common operations:
session creation, indexing, waiting, tool calls, and result formatting.
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CODEBASE_PATH = str(PROJECT_ROOT)
TOOLS_PATH = str(PROJECT_ROOT / "agent_vault/mcp/tools")


def log(test_id: str, msg: str):
    """Log with timestamp and test ID prefix."""
    print(f"[{time.strftime('%H:%M:%S')}] TEST_{test_id}: {msg}", flush=True)


async def call_tool(tool_func, **kwargs) -> tuple[dict, float]:
    """Call an MCP tool function and return (result, elapsed_seconds)."""
    t0 = time.time()
    result = await tool_func(**kwargs)
    return result, time.time() - t0


async def create_test_session(
    services: dict,
    test_id: str,
    slug: str,
    run_id: str,
    description: str = "",
) -> tuple[str, str]:
    """Create a session with a unique project_id. Returns (session_id, project_id)."""
    from agent_vault.mcp.tools.session import create_session

    project_id = f"agv_test{test_id}_{slug}_{run_id}"
    desc = description or f"UAT {slug} test"
    r = await create_session(services, project_id=project_id, description=desc)
    session_id = r.get("session_id")
    if not session_id:
        raise RuntimeError(f"Session creation failed: {r.get('error', 'unknown')}")
    return session_id, project_id


async def index_and_wait(
    services: dict,
    session_id: str,
    project_id: str,
    test_id: str,
    source: str = CODEBASE_PATH,
    content_type: str = "directory",
    max_wait: int = 600,
    poll_interval: int = 10,
    wait_for_embeddings: bool = False,
) -> Dict[str, Any]:
    """Index content and wait for completion. Returns indexing result dict.

    Uses detect_index_state (chunk count check) as the primary signal.
    Note: with the shared MCPServer, get_project_info may not see per-test data
    due to project scoping, but detect_index_state and search both work correctly.
    """
    from agent_vault.mcp.tools.knowledge import add_knowledge
    from agent_vault.mcp.utils.index_state import detect_index_state, IndexState

    t0 = time.time()
    r, _ = await call_tool(
        add_knowledge,
        services=services,
        session_id=session_id,
        content_type=content_type,
        source=source,
    )
    status = r.get("status", "unknown")
    operation_id = r.get("operation_id")

    if status == "completed":
        log(test_id, f"Indexing completed synchronously in {time.time() - t0:.1f}s")
        return {"completed": True, "elapsed_s": time.time() - t0, **r}

    if status != "started":
        return {"completed": False, "error": r.get("error", f"Unexpected status: {status}")}

    log(test_id, f"Indexing started (op={operation_id}), polling...")

    from agent_vault.mcp.tools.info import get_events

    prev_chunks = 0
    stable_count = 0  # how many consecutive polls showed same chunk count
    STABLE_THRESHOLD = 2  # declare chunks done after N consecutive stable polls
    chunks_stable_at: Optional[float] = None

    wait_start = time.time()
    while time.time() - wait_start < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed = time.time() - wait_start

        # Check for completion events.
        # chunking_completed: chunks + entities + relationships stored (FTS/graph ready)
        # indexing_completed: everything including embeddings (vector search ready)
        target_event = "indexing_completed" if wait_for_embeddings else "chunking_completed"
        try:
            events_result = await get_events(
                services=services,
                session_id=session_id,
                event_types=[target_event, "indexing_completed", "indexing_failed"],
            )
            for evt in events_result.get("events", []):
                # get_events returns "details" not "data" (info.py line 148)
                evt_data = evt.get("details", evt.get("data", {}))
                if evt_data.get("operation_id") == operation_id:
                    evt_type = evt.get("event_type", "")
                    data = evt_data
                    if evt_type == "indexing_completed":
                        total_elapsed = time.time() - t0
                        log(test_id, f"Indexing completed (event, rels={data.get('relationships_created', '?')}) in {total_elapsed:.1f}s")
                        return {
                            "completed": True,
                            "elapsed_s": total_elapsed,
                            "files_processed": data.get("items_processed", 0),
                            "chunks_created": data.get("chunks_created", 0),
                            "relationships_created": data.get("relationships_created", 0),
                        }
                    elif evt_type == "indexing_failed":
                        return {"completed": False, "error": data.get("message", "Indexing failed")}
        except Exception:
            pass

        # Track chunk stability for progress reporting
        try:
            state = await detect_index_state(
                services["storage"],
                services.get("event_system"),
                project_id,
            )
            chunks = state.indexed_so_far

            if chunks > 0:
                if chunks == prev_chunks:
                    stable_count += 1
                else:
                    stable_count = 0
                    prev_chunks = chunks

                if stable_count >= STABLE_THRESHOLD and chunks_stable_at is None:
                    chunks_stable_at = time.time()
                    log(test_id, f"  Chunks stable at {chunks}, waiting for completion event...")

                if int(elapsed) % 15 == 0:
                    log(test_id, f"  chunks={chunks} (stable={stable_count}/{STABLE_THRESHOLD})")
            elif int(elapsed) % 30 == 0:
                log(test_id, f"  Indexing... state={state.status}, chunks={chunks}")
        except Exception as e:
            if int(elapsed) % 30 == 0:
                log(test_id, f"  Still indexing... {elapsed:.0f}s (poll error: {e})")

    # Timeout — if chunks exist, return partial success
    if prev_chunks > 0:
        log(test_id, f"Indexing timed out after {max_wait}s (chunks={prev_chunks} but no completion event)")
        return {"completed": True, "elapsed_s": time.time() - t0, "chunks_detected": prev_chunks, "timed_out": True}
    log(test_id, f"Indexing timed out after {max_wait}s")
    return {"completed": False, "error": f"Timed out after {max_wait}s"}


def note_adoption(
    journal: list,
    observation: str,
    signal: str = "neutral",
):
    """Record an adoption observation during test execution.

    Called by test protocols whenever something notable happens — good or bad.
    The agent forms its adoption opinion continuously, not after the fact.

    Args:
        journal: Running list of adoption observations
        observation: What happened and what it means for adoption
        signal: "positive" (better than grep), "negative" (worse than grep),
                "neutral" (expected behavior), "blocker" (would prevent adoption)
    """
    journal.append({"observation": observation, "signal": signal})


def check(
    results: dict,
    issues: list,
    name: str,
    passed: bool,
    detail: Optional[Dict[str, Any]] = None,
    severity: str = "MEDIUM",
    fail_msg: str = "",
):
    """Record a test check result."""
    results[name] = {"pass": passed, **(detail or {})}
    if not passed:
        issues.append({
            "severity": severity,
            "test": name,
            "msg": fail_msg or f"{name} failed",
        })


def _build_adoption_evidence(
    test_checks: dict,
    issues: list,
    results: dict,
    slug: str,
    elapsed: float,
) -> Dict[str, Any]:
    """Build structured evidence for agent-based adoption scoring.

    Adoption question: "Would an AI agent choose Agent-Vault over alternatives
    (grep, manual file reading, GitHub search) for this workflow?"

    Evidence captures:
    - What the tool provided (result counts, quality, speed)
    - What failed and why (blocking vs cosmetic)
    - Comparative value signals (cross-file discovery, semantic understanding)
    """
    total = len(test_checks)
    passed = sum(1 for v in test_checks.values() if v)
    failed_checks = [k for k, v in test_checks.items() if not v]

    # Extract quality signals from results
    quality_signals = []
    value_over_alternatives = []
    for name, detail in results.items():
        if not isinstance(detail, dict):
            continue
        # Result counts — more results = more value vs grep
        for key in ("total", "result_count", "total_results", "entity_count"):
            if key in detail and isinstance(detail[key], (int, float)) and detail[key] > 0:
                quality_signals.append(f"{name}: {key}={detail[key]}")
        # Timing — fast enough to be useful interactively?
        for key in ("elapsed_s", "time_s"):
            if key in detail and isinstance(detail[key], (int, float)):
                quality_signals.append(f"{name}: {key}={detail[key]:.1f}s")
        # Cross-file and semantic signals — things grep can't do
        if detail.get("cross_file"):
            value_over_alternatives.append(f"{name}: cross-file discovery")
        if detail.get("structural_found"):
            value_over_alternatives.append(f"{name}: structural relationship found")
        if detail.get("dependencies") and len(detail.get("dependencies", [])) > 0:
            value_over_alternatives.append(f"{name}: dependency chain traced")
        # Error messages
        if detail.get("error"):
            quality_signals.append(f"{name}: error={detail['error']}")

    return {
        "slug": slug,
        "workflow": slug.replace("_", " "),
        "pass_rate": f"{passed}/{total}",
        "failed_checks": failed_checks,
        "issues": [
            {"severity": i.get("severity"), "test": i.get("test"), "msg": i.get("msg")}
            for i in issues
        ],
        "elapsed_s": round(elapsed, 1),
        "quality_signals": quality_signals[:20],
        "value_over_alternatives": value_over_alternatives[:10],
        "adoption_question": (
            f"For a '{slug.replace('_', ' ')}' workflow, would an AI agent choose "
            f"Agent-Vault (which passed {passed}/{total} checks in {elapsed:.0f}s) "
            f"over grep/manual file reading? Score 1-10 where 10 = always choose agv, "
            f"1 = never choose agv, 5 = coin flip."
        ),
    }


def compute_adoption_score(evidence: Dict[str, Any]) -> int:
    """Heuristic adoption score (fallback when no LLM agent available).

    Answers: "Would an agent choose agv over grep/manual reading?"

    Scoring philosophy — start at 7 (neutral), adjust based on evidence:
      10: exceptional — every workflow faster and better than alternatives
      8-9: strong — clear value, agent would default to agv
      6-7: useful — works for complex queries, grep still wins for simple ones
      4-5: mixed — some value but agent would hedge with fallback tools
      1-3: weak — unreliable, agent would prefer grep most of the time
      0: broken

    Key insight: even 100% pass rate doesn't mean 10/10 adoption.
    A tool with 7s latency and perfect results is ~7-8, not 10.
    """
    parts = evidence.get("pass_rate", "0/0").split("/")
    passed = int(parts[0]) if parts[0].isdigit() else 0
    total = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1

    if total == 0:
        return 0

    ratio = passed / total

    # Start at 7 (functional but not exceptional)
    base = 7

    # Critical/setup failures drop significantly
    failed = evidence.get("failed_checks", [])
    issues = evidence.get("issues", [])
    critical_count = sum(1 for i in issues if i.get("severity") == "CRITICAL")
    setup_failures = [f for f in failed if f.startswith("setup")]

    if critical_count > 0:
        base = max(1, round(ratio * 4))
        return base
    if setup_failures:
        base = max(2, round(ratio * 5))
        return base

    # Pass rate adjustments
    if ratio == 1.0:
        base = 8  # All checks pass = solid baseline
    elif ratio >= 0.9:
        base = 7
    elif ratio >= 0.7:
        base = 6
    else:
        base = max(3, round(ratio * 7))

    # Journal-based adjustments — the agent's actual experience
    journal_summary = evidence.get("journal_summary", {})
    positives = journal_summary.get("positive", 0)
    negatives = journal_summary.get("negative", 0)
    blockers = journal_summary.get("blocker", 0)
    neutrals = journal_summary.get("neutral", 0)

    if blockers > 0:
        base = min(base, 4)

    # Positive signals: each 3 positives above negatives = +1
    net_positive = positives - negatives
    if net_positive >= 6:
        base = min(10, base + 2)
    elif net_positive >= 3:
        base = min(10, base + 1)
    elif net_positive < 0:
        base = max(base - 1, 2)

    # Latency penalty — honest about speed vs grep
    elapsed = evidence.get("elapsed_s", 0)
    if elapsed > 900:  # >15min total test time = heavy indexing workflow
        base = max(base - 1, 5)  # Indexing cost is a real adoption friction

    # Neutral signals indicate honest assessment (latency tradeoffs etc)
    # Don't penalize but don't boost either — neutrals are informational

    return max(1, min(10, base))


def summarize(
    test_id: str,
    slug: str,
    results: dict,
    issues: list,
    elapsed: float,
    project_id: str = "",
    adoption_journal: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Build a standard summary dict from test results."""
    test_checks = {
        k: v.get("pass", False) for k, v in results.items()
        if isinstance(v, dict) and "pass" in v
    }
    passed = sum(1 for v in test_checks.values() if v)
    total = len(test_checks)

    # Build evidence for adoption scoring (agent or heuristic)
    evidence = _build_adoption_evidence(test_checks, issues, results, slug, elapsed)

    # Include the running journal in evidence if provided
    if adoption_journal:
        evidence["journal"] = adoption_journal
        evidence["journal_summary"] = {
            "positive": sum(1 for j in adoption_journal if j.get("signal") == "positive"),
            "negative": sum(1 for j in adoption_journal if j.get("signal") == "negative"),
            "blocker": sum(1 for j in adoption_journal if j.get("signal") == "blocker"),
            "neutral": sum(1 for j in adoption_journal if j.get("signal") == "neutral"),
        }

    adoption = compute_adoption_score(evidence)

    return {
        "test_id": test_id,
        "slug": slug,
        "project_id": project_id,
        "status": "pass" if passed == total else "partial" if passed > 0 else "fail",
        "pass_rate": f"{passed}/{total}",
        "passed": passed,
        "total": total,
        "adoption_score": adoption,
        "adoption_method": "heuristic",  # "agent" when LLM scores it
        "adoption_evidence": evidence,
        "elapsed": round(elapsed, 1),
        "checks": test_checks,
        "results": results,
        "issues": issues,
    }


def write_results(output_dir: Path, summary: dict):
    """Write results JSON to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "results.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
