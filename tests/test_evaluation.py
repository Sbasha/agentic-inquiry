"""Component checks of imported evidence, never comparative study results."""

import copy
import json
import sqlite3

import pytest

from agentic_inquiry.evaluation import dispatch


@pytest.fixture
def manifest():
    return {
        "schema_version": 1,
        "id": "component-accounting",
        "partition": "development",
        "corpus_revision": "component-input-v1",
        "required_capabilities": ["retrieval", "scope"],
        "repetitions": 1,
        "acceptance_threshold": 0.85,
        "conditions": {
            "model": "component-model",
            "effort": "none",
            "context_policy": "fixed-context-v1",
            "tool_policy": "no-execution",
            "environment": "component-only",
            "limits": {"turns": 10, "wall_seconds": 100, "execution_tokens": 10000},
        },
        "systems": [
            {
                "id": name,
                "revision": "v1",
                "configuration": {},
                "capabilities": ["retrieval", "scope"],
            }
            for name in ("baseline", "candidate")
        ],
        "rubric": {
            "owner": "independent-owner",
            "revision": "rubric-v1",
            "independent_of": ["baseline", "candidate"],
        },
        "evaluator": {"id": "reviewer", "revision": "v1", "kind": "human"},
        "tasks": [
            {
                "id": "task-a",
                "text": "Component rubric only.",
                "capability": "retrieval",
                "facts": [
                    {"id": "fact-a", "text": "An atomic fact.", "weight": 1, "source_backed": True}
                ],
                "retrieval_gold": ["source-a", "source-b"],
            },
            {
                "id": "task-b",
                "text": "Component scope rubric only.",
                "capability": "scope",
                "facts": [
                    {"id": "fact-b", "text": "An atomic fact.", "weight": 1, "source_backed": False}
                ],
            },
        ],
        "comparison": {
            "baseline": "baseline",
            "candidate": "candidate",
            "kind": "component",
            "minimum_paired_tasks": 2,
            "power_analysis": "Component definition, no statistical power claim.",
            "loss_margin": 0,
        },
    }


def frozen(tmp_path, manifest):
    study = str(tmp_path / "study")
    result = dispatch("freeze", {"study": study, "manifest": manifest})
    return study, result["manifest_digest"]


def execution(
    identifier,
    *,
    phase="answering",
    input_tokens=100,
    cached=50,
    semantics="includes_cached",
    output=10,
):
    return {
        "id": identifier,
        "phase": phase,
        "model": "component-model",
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output,
        "input_semantics": semantics,
        "measurement": "provider",
    }


def trial(
    digest,
    *,
    system="candidate",
    task="task-a",
    attempt=1,
    repetition=1,
    status="completed",
    executions=None,
):
    identifier = f"{system}-{task}-{repetition}-{attempt}"
    return {
        "id": identifier,
        "manifest_digest": digest,
        "system_id": system,
        "task_id": task,
        "repetition": repetition,
        "attempt": attempt,
        "status": status,
        "raw": {"answer": "Component evidence only."},
        "usage_complete": True,
        "executions": executions if executions is not None else [execution(identifier + "-call")],
        "turns": 1,
        "resources": {"wall_seconds": 1.5},
        "cold_start": False,
        "retrieved_ids": ["irrelevant", "source-a", "source-a"],
    }


def judge(record, *, score=1, critical=None, citations=True):
    return {
        "id": "judge-" + record["id"],
        "trial_id": record["id"],
        "evaluator_id": "reviewer",
        "evaluator_revision": "v1",
        "rubric_revision": "rubric-v1",
        "status": "judged",
        "raw": "Component judgment only.",
        "material_unsupported": False,
        "critical_failures": critical or [],
        "facts": {
            "fact-" + record["task_id"][-1]: {
                "score": score,
                "citations_valid": citations,
                "evidence": [{"source": "component-evidence"}],
            }
        },
    }


def append_trial(study, record, **judgment):
    dispatch("trial", {"study": study, "record": record})
    dispatch("judge", {"study": study, "record": judge(record, **judgment)})


def close(study, *, complete=True):
    dispatch(
        "close",
        {
            "study": study,
            "record": {
                "id": "closed",
                "accounting_complete": complete,
                "attestation": "All component record costs are supplied; unlisted phases had zero work.",
            },
        },
    )


def single_system(manifest):
    manifest["systems"] = manifest["systems"][1:]
    manifest["rubric"]["independent_of"] = ["candidate"]
    manifest.pop("comparison")
    manifest["tasks"] = manifest["tasks"][:1]


def test_frozen_identity_replay_and_append_only_evidence(tmp_path, manifest):
    study, digest = frozen(tmp_path, manifest)
    assert dispatch("freeze", {"study": study, "manifest": manifest})["duplicate"]
    record = trial(digest)
    first = dispatch("trial", {"study": study, "record": record})
    assert dispatch("trial", {"study": study, "record": record}) == {**first, "duplicate": True}
    original = copy.deepcopy(record)
    record["raw"]["answer"] = "Different evidence"
    with pytest.raises(ValueError, match="replace"):
        dispatch("trial", {"study": study, "record": record})
    manifest["tasks"][0]["text"] = "Changed question"
    with pytest.raises(ValueError, match="frozen"):
        dispatch("freeze", {"study": study, "manifest": manifest})
    events = dispatch("inspect", {"study": study})["events"]
    assert events[1]["document"]["record"] == original
    before = dispatch("report", {"study": study})
    assert dispatch("report", {"study": study}) == before
    database = sqlite3.connect(tmp_path / "study" / "evaluation.sqlite3")
    with database, pytest.raises(sqlite3.IntegrityError, match="append-only"):
        database.execute("DELETE FROM events WHERE id = ?", (original["id"],))
    database.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("manifest_digest", "wrong"),
        ("task_id", "missing"),
        ("system_id", "missing"),
        ("repetition", 2),
    ],
)
def test_rejects_identity_drift(tmp_path, manifest, field, value):
    study, digest = frozen(tmp_path, manifest)
    record = trial(digest)
    record[field] = value
    with pytest.raises(ValueError):
        dispatch("trial", {"study": study, "record": record})
    assert len(dispatch("inspect", {"study": study})["events"]) == 1


def test_all_phases_retries_cached_semantics_and_amortization(tmp_path, manifest):
    single_system(manifest)
    study, digest = frozen(tmp_path, manifest)
    append_trial(study, trial(digest, status="failed"), score=0)
    append_trial(
        study,
        trial(digest, attempt=2, executions=[execution("retry-call", semantics="excludes_cached")]),
    )
    for phase, tokens in (("preparation", 40), ("knowledge_synthesis", 20), ("grading", 30)):
        dispatch(
            "cost",
            {
                "study": study,
                "record": {
                    "id": phase,
                    "system_id": "candidate",
                    "phase": phase,
                    "description": "Component cost",
                    "usage_complete": True,
                    "executions": [
                        execution(
                            phase + "-call", phase=phase, input_tokens=tokens, cached=0, output=0
                        )
                    ],
                },
            },
        )
    dispatch(
        "cost",
        {
            "study": study,
            "record": {
                "id": "embeddings",
                "system_id": "candidate",
                "phase": "embedding",
                "description": "Component embedding work",
                "usage_complete": True,
                "executions": [],
                "embeddings": [{"model": "local-embed", "units": 100, "unit": "passage_tokens"}],
            },
        },
    )
    assert (
        dispatch("report", {"study": study})["systems"]["candidate"][
            "answering_tokens_per_accepted_outcome"
        ]
        is None
    )
    close(study)
    result = dispatch("report", {"study": study, "amortized_uses": 2})["systems"]["candidate"]
    assert result["recorded_attempts"] == 2 and result["accepted_outcomes"] == 1
    assert result["answering"]["input_tokens"] == 250
    assert result["answering"]["cached_input_tokens"] == 100
    assert result["answering"]["uncached_input_tokens"] == 150
    assert result["answering_tokens_per_accepted_outcome"] == 270
    assert result["all_in_tokens_per_accepted_outcome"] == 360
    assert result["amortized"]["all_in_tokens_per_accepted_outcome"] == 330
    assert result["embedding_work"] == [
        {"model": "local-embed", "unit": "passage_tokens", "units": 100, "records": 1}
    ]
    assert result["attempt_statuses"] == {"failed": 1, "completed": 1}


def test_missing_failed_unjudgeable_and_unknown_usage_are_never_dropped(tmp_path, manifest):
    study, digest = frozen(tmp_path, manifest)
    append_trial(study, trial(digest))
    failed = trial(
        digest, task="task-b", status="failed", executions=[execution("unknown", output=None)]
    )
    dispatch("trial", {"study": study, "record": failed})
    judgment = judge(failed)
    judgment.update(status="unjudgeable", reason="No recoverable output")
    dispatch("judge", {"study": study, "record": judgment})
    close(study)
    result = dispatch("report", {"study": study})
    candidate = result["systems"]["candidate"]
    assert candidate["planned_outcomes"] == 2 and candidate["accepted_outcomes"] == 1
    assert candidate["acceptance_rate"] == 0.5
    assert candidate["answering"]["execution_tokens"] is None
    assert candidate["all_in_tokens_per_accepted_outcome"] is None
    assert result["systems"]["baseline"]["missing_outcomes"] == 2
    assert len(result["outcomes"]) == 4
    assert len(result["comparison"]["missing_pairs"]) == 2


@pytest.mark.parametrize(
    "status", ["failed", "blocked", "cancelled", "incomplete", "error", "unknown"]
)
def test_failure_statuses_retain_cost_denominator(tmp_path, manifest, status):
    single_system(manifest)
    study, digest = frozen(tmp_path, manifest)
    append_trial(study, trial(digest, status=status))
    close(study)
    result = dispatch("report", {"study": study})["systems"]["candidate"]
    assert result["accepted_outcomes"] == 0 and result["recorded_attempts"] == 1
    assert result["answering"]["execution_tokens"] == 110
    assert result["answering_tokens_per_accepted_outcome"] is None
    assert "zero_accepted_outcomes" in result["ratio_limitations"]


def test_retry_does_not_reset_limits_or_erase_critical_failure(tmp_path, manifest):
    single_system(manifest)
    manifest["conditions"]["limits"]["execution_tokens"] = 200
    study, digest = frozen(tmp_path, manifest)
    append_trial(study, trial(digest, status="failed"), critical=["scope"])
    append_trial(study, trial(digest, attempt=2))
    close(study)
    result = dispatch("report", {"study": study})
    assert result["trials"][-1]["accepted"]
    assert not result["outcomes"][0]["accepted"]
    assert result["outcomes"][0]["budget_failures"] == ["exceeded_execution_tokens"]
    assert result["outcomes"][0]["critical_failures"] == ["scope"]


def test_final_attempt_not_best_attempt_and_sequence_gaps(tmp_path, manifest):
    single_system(manifest)
    study, digest = frozen(tmp_path, manifest)
    append_trial(study, trial(digest))
    append_trial(study, trial(digest, attempt=3), score=0.4)
    close(study)
    report = dispatch("report", {"study": study})
    assert report["outcomes"][0]["weighted_fact_coverage"] == 0.4
    assert not report["outcomes"][0]["accepted"]
    assert report["systems"]["candidate"]["attempt_sequence_gaps"] == 1


@pytest.mark.parametrize(
    "score,citations,expected", [(0.84, True, False), (0.85, True, True), (1, False, False)]
)
def test_atomic_coverage_citations_and_retrieval_metrics(
    tmp_path, manifest, score, citations, expected
):
    study, digest = frozen(tmp_path, manifest)
    append_trial(study, trial(digest), score=score, citations=citations)
    result = dispatch("report", {"study": study})["trials"][0]
    assert result["accepted"] is expected
    assert result["weighted_fact_coverage"] == score
    assert result["retrieval"] == {"precision": 1 / 3, "recall": 0.5, "reciprocal_rank": 0.5}


def test_duplicate_execution_ids_and_unknown_model_are_rejected(tmp_path, manifest):
    study, digest = frozen(tmp_path, manifest)
    append_trial(study, trial(digest))
    duplicate = trial(digest, task="task-b", executions=[execution("candidate-task-a-1-1-call")])
    with pytest.raises(ValueError, match="double-count"):
        dispatch("trial", {"study": study, "record": duplicate})
    duplicate["executions"][0]["id"] = "fresh-id"
    duplicate["executions"][0]["model"] = "unfrozen-model"
    with pytest.raises(ValueError, match="model identities"):
        dispatch("trial", {"study": study, "record": duplicate})


@pytest.mark.parametrize(
    "change",
    [
        {"input_tokens": -1},
        {"cached_input_tokens": 101},
        {"output_tokens": True},
        {"input_tokens": float("nan")},
    ],
)
def test_invalid_usage_is_rejected_without_partial_event(tmp_path, manifest, change):
    study, digest = frozen(tmp_path, manifest)
    record = trial(digest)
    record["executions"][0].update(change)
    with pytest.raises(ValueError):
        dispatch("trial", {"study": study, "record": record})
    assert len(dispatch("inspect", {"study": study})["events"]) == 1


def test_estimates_and_known_zero_are_distinct(tmp_path, manifest):
    study, digest = frozen(tmp_path, manifest)
    record = trial(digest)
    record["executions"][0]["measurement"] = "estimate"
    append_trial(study, record)
    append_trial(study, trial(digest, task="task-b", executions=[]))
    close(study)
    report = dispatch("report", {"study": study})
    assert not report["trials"][0]["accepted"]
    assert report["trials"][1]["accepted"]
    assert report["trials"][1]["usage"]["execution_tokens"] == 0
    assert report["systems"]["candidate"]["answering_tokens_per_accepted_outcome"] is None


def test_repeated_small_pilot_cannot_claim_zero_quality_loss(tmp_path, manifest):
    manifest["partition"] = "sealed"
    manifest["repetitions"] = 4
    study, digest = frozen(tmp_path, manifest)
    for system in ("baseline", "candidate"):
        for task in ("task-a", "task-b"):
            for repetition in range(1, 5):
                append_trial(study, trial(digest, system=system, task=task, repetition=repetition))
    close(study)
    comparison = dispatch("report", {"study": study})["comparison"]
    assert comparison["weighted_fact_coverage"]["tasks"] == 2
    assert comparison["weighted_fact_coverage"]["mean_difference"] == 0
    assert comparison["weighted_fact_coverage"]["one_sided_95_lower"] < 0
    assert comparison["decision"] == "inconclusive" and not comparison["no_quality_loss"]
    assert not comparison["missing_pairs"]


def test_closed_study_idempotency_and_tamper_detection(tmp_path, manifest):
    study, digest = frozen(tmp_path, manifest)
    record = trial(digest)
    append_trial(study, record)
    close(study)
    assert dispatch("trial", {"study": study, "record": record})["duplicate"]
    with pytest.raises(ValueError, match="closed"):
        dispatch("trial", {"study": study, "record": trial(digest, task="task-b")})
    database = sqlite3.connect(tmp_path / "study" / "evaluation.sqlite3")
    with database:
        database.execute("DROP TRIGGER prevent_update")
        document = json.loads(
            database.execute(
                "SELECT document FROM events WHERE id = ?", (record["id"],)
            ).fetchone()[0]
        )
        document["record"]["raw"] = "Tampered"
        database.execute(
            "UPDATE events SET document = ? WHERE id = ?", (json.dumps(document), record["id"])
        )
    database.close()
    with pytest.raises(ValueError, match="integrity"):
        dispatch("report", {"study": study})


def test_newer_schema_is_rejected_without_repair(tmp_path, manifest):
    study, _ = frozen(tmp_path, manifest)
    database = sqlite3.connect(tmp_path / "study" / "evaluation.sqlite3")
    with database:
        database.execute("PRAGMA user_version = 999")
    database.close()
    with pytest.raises(ValueError, match="Unsupported evaluation schema 999"):
        dispatch("report", {"study": study})
