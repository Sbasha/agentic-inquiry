"""Frozen study definitions and append-only local evidence, without model execution.

``dispatch(action, payload)`` accepts a ``study`` directory and one of:
``freeze`` (``manifest``), ``trial``, ``judge``, ``cost``, ``close`` (``record``),
``inspect``, or ``report`` (optional positive ``amortized_uses``).

Trials contain every execution belonging to an attempt. Retries have distinct
attempt numbers; workers have distinct execution IDs. A final close attests
whether all costs were supplied, and prevents further records. A new study is
required to change frozen inputs or append evidence after closure.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PHASES = ("answering", "preparation", "knowledge_synthesis", "grading")
STATUSES = ("completed", "failed", "blocked", "cancelled", "incomplete", "error", "unknown")
RESOURCE_SUMS = (
    "wall_seconds",
    "cpu_seconds",
    "model_download_bytes",
    "extraction_seconds",
    "indexing_seconds",
)
RESOURCE_PEAKS = ("peak_memory_bytes", "disk_bytes")
MAX_RECORD_BYTES = 16 * 1024 * 1024


def _json(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Records must contain finite JSON values") from exc
    if len(encoded.encode()) > MAX_RECORD_BYTES:
        raise ValueError("Record exceeds the 16 MiB limit")
    return encoded


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _number(value: Any, name: str, *, integer: bool = False, nullable: bool = False) -> Any:
    if value is None and nullable:
        return None
    valid = type(value) is int if integer else type(value) in (int, float)
    if not valid or not math.isfinite(value) or value < 0:
        raise ValueError(
            f"{name} must be a finite nonnegative {'integer' if integer else 'number'}"
        )
    return value


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _mapping(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _strings(value: Any, name: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{name} must be a {'nonempty ' if nonempty else ''}list")
    for item in value:
        _text(item, name)
    if len(value) != len(set(value)):
        raise ValueError(f"{name} must not contain duplicates")
    return value


def _manifest(value: dict) -> dict:
    value = json.loads(_json(_mapping(value, "manifest")))
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported manifest schema_version")
    _text(value.get("id"), "manifest.id")
    if value.get("partition") not in ("development", "public", "sealed"):
        raise ValueError("partition must be development, public, or sealed")
    _text(value.get("corpus_revision"), "corpus_revision")
    capabilities = _strings(
        value.get("required_capabilities"), "required_capabilities", nonempty=True
    )
    repetitions = _number(value.get("repetitions"), "repetitions", integer=True)
    if not repetitions:
        raise ValueError("repetitions must be positive")
    threshold = _number(value.get("acceptance_threshold"), "acceptance_threshold")
    if not 0.85 <= threshold <= 1:
        raise ValueError("acceptance_threshold must be between 0.85 and 1")
    conditions = _mapping(value.get("conditions"), "conditions")
    _text(conditions.get("model"), "conditions.model")
    if "execution_models" in conditions:
        _strings(conditions["execution_models"], "conditions.execution_models", nonempty=True)
    for key in ("model", "effort", "context_policy", "tool_policy", "environment"):
        if not conditions.get(key):
            raise ValueError(f"conditions.{key} must freeze its identity or policy")
    limits = _mapping(conditions.get("limits"), "conditions.limits")
    for key in ("turns", "wall_seconds", "execution_tokens"):
        if _number(limits.get(key), f"limits.{key}") <= 0:
            raise ValueError(f"limits.{key} must be positive")
    systems = value.get("systems")
    if not isinstance(systems, list) or not systems:
        raise ValueError("systems must be a nonempty list")
    system_ids = []
    for system in systems:
        _mapping(system, "system")
        system_ids.append(_text(system.get("id"), "system.id"))
        _text(system.get("revision"), "system.revision")
        _mapping(system.get("configuration"), "system.configuration")
        _strings(system.get("capabilities"), "system.capabilities", nonempty=True)
    if len(set(system_ids)) != len(system_ids):
        raise ValueError("Duplicate system identity")
    rubric = _mapping(value.get("rubric"), "rubric")
    _text(rubric.get("owner"), "rubric.owner")
    _text(rubric.get("revision"), "rubric.revision")
    if set(_strings(rubric.get("independent_of"), "rubric.independent_of")) != set(system_ids):
        raise ValueError("The rubric must declare independence from every evaluated system")
    evaluator = _mapping(value.get("evaluator"), "evaluator")
    _text(evaluator.get("id"), "evaluator.id")
    _text(evaluator.get("revision"), "evaluator.revision")
    if evaluator.get("kind") not in ("human", "model"):
        raise ValueError("evaluator.kind must be human or model")
    if evaluator["kind"] == "model":
        for key in ("model", "prompt_revision", "calibration_revision"):
            _text(evaluator.get(key), f"evaluator.{key}")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a nonempty list")
    task_ids = []
    for task in tasks:
        _mapping(task, "task")
        task_ids.append(_text(task.get("id"), "task.id"))
        _text(task.get("text"), "task.text")
        if task.get("capability") not in capabilities:
            raise ValueError("Each task must identify a declared required capability")
        facts = task.get("facts")
        if not isinstance(facts, list) or not facts:
            raise ValueError("Each task requires independent atomic facts")
        fact_ids = []
        for fact in facts:
            _mapping(fact, "fact")
            fact_ids.append(_text(fact.get("id"), "fact.id"))
            _text(fact.get("text"), "fact.text")
            if _number(fact.get("weight"), "fact.weight") <= 0:
                raise ValueError("fact.weight must be positive")
            _boolean(fact.get("source_backed"), "fact.source_backed")
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("Duplicate fact identity")
        if "retrieval_gold" in task:
            _strings(task["retrieval_gold"], "task.retrieval_gold")
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("Duplicate task identity")
    comparison = value.get("comparison")
    if comparison is not None:
        _mapping(comparison, "comparison")
        if (
            comparison.get("baseline") not in system_ids
            or comparison.get("candidate") not in system_ids
            or comparison["baseline"] == comparison["candidate"]
        ):
            raise ValueError("comparison requires distinct declared baseline and candidate")
        if comparison.get("kind") not in ("component", "product"):
            raise ValueError("comparison.kind must be component or product")
        if (
            _number(comparison.get("minimum_paired_tasks"), "minimum_paired_tasks", integer=True)
            < 2
        ):
            raise ValueError("minimum_paired_tasks must be at least two independent tasks")
        _text(comparison.get("power_analysis"), "comparison.power_analysis")
        margin = _number(comparison.get("loss_margin", 0), "loss_margin")
        if margin > 1:
            raise ValueError("loss_margin must not exceed one")
        if margin:
            _text(comparison.get("margin_decision"), "comparison.margin_decision")
    return value


def _execution(value: dict) -> dict:
    _mapping(value, "execution")
    _text(value.get("id"), "execution.id")
    _text(value.get("model"), "execution.model")
    if value.get("phase") not in PHASES:
        raise ValueError(f"execution.phase must be one of {PHASES}")
    if value.get("input_semantics") not in ("includes_cached", "excludes_cached"):
        raise ValueError("input_semantics must say whether input includes cached input")
    if value.get("measurement") not in ("provider", "tokenizer", "estimate"):
        raise ValueError("measurement must be provider, tokenizer, or estimate")
    for field in ("input_tokens", "cached_input_tokens", "output_tokens"):
        if field not in value:
            raise ValueError(f"Missing {field}; use null for unknown usage")
        _number(value[field], field, integer=True, nullable=True)
    reported, cached, output = (
        value["input_tokens"],
        value["cached_input_tokens"],
        value["output_tokens"],
    )
    if value["input_semantics"] == "includes_cached":
        if reported is not None and cached is not None and cached > reported:
            raise ValueError("Cached input cannot exceed inclusive input")
        total_input = reported
        uncached = reported - cached if reported is not None and cached is not None else None
    else:
        uncached = reported
        total_input = reported + cached if reported is not None and cached is not None else None
    return {
        **value,
        "reported_input_tokens": reported,
        "input_tokens": total_input,
        "uncached_input_tokens": uncached,
        "execution_tokens": total_input + output
        if total_input is not None and output is not None
        else None,
        "complete": all(v is not None for v in (reported, cached, output))
        and value["measurement"] != "estimate",
    }


def _usage(record: dict, *, trial: bool) -> None:
    _boolean(record.get("usage_complete"), "usage_complete")
    executions = record.get("executions")
    if not isinstance(executions, list):
        raise TypeError(
            "executions must include every worker/call, or [] for known zero generation"
        )
    for execution in executions:
        _execution(execution)
        if trial and execution["phase"] != "answering":
            raise ValueError("Trial executions are answering; record other phases with cost")
        if not trial and execution["phase"] == "answering":
            raise ValueError("Answering executions must belong to a trial")
    resources = _mapping(record.get("resources", {}), "resources")
    for field in RESOURCE_SUMS + RESOURCE_PEAKS:
        _number(resources.get(field), field, nullable=True)
    for embedding in record.get("embeddings", []):
        _mapping(embedding, "embedding")
        _text(embedding.get("model"), "embedding.model")
        _text(embedding.get("unit"), "embedding.unit")
        _number(embedding.get("units"), "embedding.units", nullable=True)


@contextmanager
def _database(study: Path, *, create: bool = False) -> Iterator[sqlite3.Connection]:
    study = study.expanduser().resolve()
    path = study / "evaluation.sqlite3"
    if create:
        study.mkdir(parents=True, exist_ok=True)
    elif not path.is_file():
        raise FileNotFoundError(f"No frozen study at {study}")
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in ((0, SCHEMA_VERSION) if create else (SCHEMA_VERSION,)):
            raise ValueError(f"Unsupported evaluation schema {version}")
        connection.execute("BEGIN IMMEDIATE" if create else "BEGIN")
        if create and version == 0:
            connection.execute(
                "CREATE TABLE events (sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
                "id TEXT NOT NULL UNIQUE, document TEXT NOT NULL, previous_digest TEXT, "
                "digest TEXT NOT NULL)"
            )
            for operation in ("UPDATE", "DELETE"):
                connection.execute(
                    f"CREATE TRIGGER prevent_{operation.lower()} BEFORE {operation} ON events "
                    "BEGIN SELECT RAISE(ABORT, 'Evaluation evidence is append-only'); END"
                )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _events(connection: sqlite3.Connection) -> list[dict]:
    events = []
    previous = None
    for sequence, kind, event_id, document, prior, digest in connection.execute(
        "SELECT sequence, kind, id, document, previous_digest, digest FROM events ORDER BY sequence"
    ):
        payload = json.loads(document)
        expected = _hash({"kind": kind, "id": event_id, "document": payload, "previous": previous})
        if prior != previous or digest != expected or sequence != len(events) + 1:
            raise ValueError("Evaluation evidence integrity check failed")
        events.append({"kind": kind, "id": event_id, "document": payload, "digest": digest})
        previous = digest
    if events and events[0]["kind"] != "manifest":
        raise ValueError("Study does not begin with its frozen manifest")
    return events


def _append(connection: sqlite3.Connection, kind: str, event_id: str, document: dict) -> dict:
    events = _events(connection)
    for event in events:
        if event["id"] == event_id:
            if event["kind"] == kind and event["document"].get("record") == document.get("record"):
                return {"id": event_id, "digest": event["digest"], "duplicate": True}
            raise ValueError("An event ID cannot replace previously recorded evidence")
    previous = events[-1]["digest"] if events else None
    digest = _hash({"kind": kind, "id": event_id, "document": document, "previous": previous})
    connection.execute(
        "INSERT INTO events (kind, id, document, previous_digest, digest) VALUES (?, ?, ?, ?, ?)",
        (kind, event_id, _json(document), previous, digest),
    )
    return {"id": event_id, "digest": digest, "duplicate": False}


def _records(events: list[dict], kind: str) -> list[dict]:
    return [event["document"]["record"] for event in events if event["kind"] == kind]


def _validate_record(kind: str, record: dict, manifest: dict, events: list[dict]) -> None:
    _mapping(record, "record")
    _text(record.get("id"), "record.id")
    if kind == "close":
        _boolean(record.get("accounting_complete"), "accounting_complete")
        _text(record.get("attestation"), "attestation")
        return
    if kind == "judge":
        trials = {trial["id"]: trial for trial in _records(events, "trial")}
        if record.get("trial_id") not in trials:
            raise ValueError("Judgment must identify a recorded trial")
        if any(j["trial_id"] == record["trial_id"] for j in _records(events, "judge")):
            raise ValueError("A trial already has an immutable judgment")
        if record.get("evaluator_id") != manifest["evaluator"]["id"]:
            raise ValueError("Judgment evaluator differs from the frozen identity")
        if record.get("evaluator_revision") != manifest["evaluator"]["revision"]:
            raise ValueError("Judgment evaluator revision differs from the frozen identity")
        if record.get("rubric_revision") != manifest["rubric"]["revision"]:
            raise ValueError("Judgment rubric revision differs from the frozen identity")
        if record.get("status") not in ("judged", "unjudgeable"):
            raise ValueError("Judgment status must be judged or unjudgeable")
        if "raw" not in record:
            raise ValueError("Preserve the raw judgment in raw")
        if record["status"] == "unjudgeable":
            _text(record.get("reason"), "unjudgeable reason")
            return
        _boolean(record.get("material_unsupported"), "material_unsupported")
        _strings(record.get("critical_failures"), "critical_failures")
        task_id = trials[record["trial_id"]]["task_id"]
        task = next(task for task in manifest["tasks"] if task["id"] == task_id)
        facts = _mapping(record.get("facts"), "judgment.facts")
        if set(facts) != {fact["id"] for fact in task["facts"]}:
            raise ValueError("Judgment must score every frozen atomic fact exactly once")
        for fact in facts.values():
            _mapping(fact, "fact judgment")
            if _number(fact.get("score"), "fact.score") > 1:
                raise ValueError("Fact scores must be between zero and one")
            _boolean(fact.get("citations_valid"), "citations_valid")
            if not isinstance(fact.get("evidence"), list):
                raise TypeError("Fact judgment must preserve evidence references as a list")
        return
    if record.get("system_id") not in {system["id"] for system in manifest["systems"]}:
        raise ValueError("Record system differs from the frozen identities")
    _usage(record, trial=kind == "trial")
    if kind == "cost":
        if record.get("phase") not in PHASES[1:] + ("embedding",):
            raise ValueError(
                "Cost phase must be preparation, knowledge_synthesis, grading, embedding"
            )
        if any(execution["phase"] != record["phase"] for execution in record["executions"]):
            raise ValueError("Execution phase must match its cost record")
        _text(record.get("description"), "cost.description")
        return
    if record.get("task_id") not in {task["id"] for task in manifest["tasks"]}:
        raise ValueError("Trial task differs from the frozen identities")
    if record.get("manifest_digest") != events[0]["digest"]:
        raise ValueError("Trial must identify the frozen manifest_digest returned by freeze")
    permitted_models = manifest["conditions"].get(
        "execution_models", [manifest["conditions"]["model"]]
    )
    if any(execution["model"] not in permitted_models for execution in record["executions"]):
        raise ValueError("Trial execution model differs from the frozen model identities")
    repetition = _number(record.get("repetition"), "repetition", integer=True)
    attempt = _number(record.get("attempt"), "attempt", integer=True)
    if not 1 <= repetition <= manifest["repetitions"] or attempt < 1:
        raise ValueError("Repetition must be in the frozen range and attempt positive")
    key = tuple(record[field] for field in ("system_id", "task_id", "repetition", "attempt"))
    for trial in _records(events, "trial"):
        if key == tuple(
            trial[field] for field in ("system_id", "task_id", "repetition", "attempt")
        ):
            raise ValueError("Duplicate task/system/repetition/attempt identity")
    if record.get("status") not in STATUSES:
        raise ValueError(f"Trial status must be one of {STATUSES}")
    if "raw" not in record:
        raise ValueError("Preserve raw trial evidence in raw")
    _number(record.get("turns"), "turns", integer=True, nullable=True)
    if "cold_start" in record:
        _boolean(record["cold_start"], "cold_start")
    if "retrieved_ids" in record:
        if not isinstance(record["retrieved_ids"], list):
            raise ValueError("retrieved_ids must be a list")
        for identifier in record["retrieved_ids"]:
            _text(identifier, "retrieved_id")


def _execution_ids(events: list[dict]) -> set[str]:
    ids = set()
    for event in events:
        record = event["document"]["record"]
        for execution in record.get("executions", []):
            if execution["id"] in ids:
                raise ValueError("Duplicate execution ID would double-count usage")
            ids.add(execution["id"])
    return ids


def _sum_nullable(values: list[Any]) -> Any:
    return sum(values) if all(value is not None for value in values) else None


def _accounting(records: list[dict]) -> dict:
    executions = [_execution(item) for record in records for item in record["executions"]]
    complete = all(record["usage_complete"] for record in records) and all(
        execution["complete"] for execution in executions
    )
    totals = {
        key: _sum_nullable([execution[key] for execution in executions])
        for key in (
            "input_tokens",
            "uncached_input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "execution_tokens",
        )
    }
    return {
        **totals,
        "complete": complete,
        "executions": len(executions),
        "unknown_or_estimated_executions": sum(
            not execution["complete"] for execution in executions
        ),
        "measurement_counts": dict(Counter(execution["measurement"] for execution in executions)),
    }


def _trial_result(trial: dict, judgment: dict | None, task: dict, manifest: dict) -> dict:
    coverage = None
    failures = []
    citations_valid = None
    if judgment and judgment["status"] == "judged":
        facts = judgment["facts"]
        coverage = sum(fact["weight"] * facts[fact["id"]]["score"] for fact in task["facts"]) / sum(
            fact["weight"] for fact in task["facts"]
        )
        citations_valid = all(
            facts[fact["id"]]["citations_valid"] and bool(facts[fact["id"]]["evidence"])
            for fact in task["facts"]
            if fact["source_backed"] and facts[fact["id"]]["score"] > 0
        )
        failures.extend(judgment["critical_failures"])
        if judgment["material_unsupported"]:
            failures.append("material_unsupported_assertion")
        if not citations_valid:
            failures.append("invalid_or_missing_citation")
        if coverage < manifest["acceptance_threshold"]:
            failures.append("insufficient_fact_coverage")
    else:
        failures.append("unjudgeable" if judgment else "missing_judgment")
    if trial["status"] != "completed":
        failures.append(trial["status"])
    usage = _accounting([trial])
    limits = manifest["conditions"]["limits"]
    observed = {
        "turns": trial.get("turns"),
        "wall_seconds": trial.get("resources", {}).get("wall_seconds"),
        "execution_tokens": usage["execution_tokens"] if usage["complete"] else None,
    }
    for key, value in observed.items():
        if value is None:
            failures.append(f"unknown_{key}")
        elif value > limits[key]:
            failures.append(f"exceeded_{key}")
    retrieved = trial.get("retrieved_ids")
    gold = task.get("retrieval_gold")
    retrieval = {"precision": None, "recall": None, "reciprocal_rank": None}
    if retrieved is not None and gold is not None:
        hits = set(retrieved) & set(gold)
        retrieval = {
            "precision": len(hits) / len(retrieved) if retrieved else 0.0,
            "recall": len(hits) / len(gold) if gold else None,
            "reciprocal_rank": next(
                (1 / rank for rank, item in enumerate(retrieved, 1) if item in gold), 0.0
            ),
        }
    return {
        "id": trial["id"],
        "task_id": task["id"],
        "system_id": trial["system_id"],
        "repetition": trial["repetition"],
        "attempt": trial["attempt"],
        "status": trial["status"],
        "weighted_fact_coverage": coverage,
        "citations_valid": citations_valid,
        "accepted": not failures,
        "failures": failures,
        "critical_failures": judgment.get("critical_failures", []) if judgment else [],
        "retrieval": retrieval,
        "usage": usage,
    }


def _resources(records: list[dict]) -> dict:
    result = {"unclassified_latency_records": sum("cold_start" not in record for record in records)}
    for field in RESOURCE_SUMS + RESOURCE_PEAKS:
        values = [record.get("resources", {}).get(field) for record in records]
        known = [value for value in values if value is not None]
        result[field] = {
            "value": (sum(known) if field in RESOURCE_SUMS else max(known, default=None))
            if len(known) == len(values)
            else None,
            "known_subtotal" if field in RESOURCE_SUMS else "known_peak": sum(known)
            if field in RESOURCE_SUMS
            else max(known, default=None),
            "measured_records": len(known),
            "unknown_records": len(values) - len(known),
        }
    for label, cold in (("cold_latency_seconds", True), ("warm_latency_seconds", False)):
        selected = [record for record in records if record.get("cold_start") is cold]
        times = [record.get("resources", {}).get("wall_seconds") for record in selected]
        known = sorted(value for value in times if value is not None)
        result[label] = {
            "observations": known,
            "count": len(known),
            "unknown_count": len(times) - len(known),
            "mean": sum(known) / len(known) if known else None,
        }
    return result


def _paired_interval(differences: list[float]) -> dict:
    """Conservative bounded paired-task interval, with tasks as sampling units."""
    if not differences:
        return {
            "tasks": 0,
            "mean_difference": None,
            "two_sided_95": None,
            "one_sided_95_lower": None,
        }
    n = len(differences)
    mean = sum(differences) / n
    # Task means are bounded [-1, 1]. Repetitions never inflate independent n.
    width = math.sqrt(2 * math.log(40) / n)
    lower = math.sqrt(2 * math.log(20) / n)
    return {
        "tasks": n,
        "mean_difference": mean,
        "two_sided_95": [max(-1.0, mean - width), min(1.0, mean + width)],
        "one_sided_95_lower": max(-1.0, mean - lower),
    }


def _comparison(manifest: dict, outcomes: list[dict], closed: bool) -> dict | None:
    definition = manifest.get("comparison")
    if not definition:
        return None
    by_key = {(o["system_id"], o["task_id"], o["repetition"]): o for o in outcomes}
    differences, accepted_differences, missing, groups = [], [], [], {}
    for task in manifest["tasks"]:
        task_differences, task_acceptance = [], []
        for repetition in range(1, manifest["repetitions"] + 1):
            pair = [
                by_key[(definition[side], task["id"], repetition)]
                for side in ("baseline", "candidate")
            ]
            if any(outcome["weighted_fact_coverage"] is None for outcome in pair):
                missing.append({"task_id": task["id"], "repetition": repetition})
                continue
            task_differences.append(
                pair[1]["weighted_fact_coverage"] - pair[0]["weighted_fact_coverage"]
            )
            task_acceptance.append(int(pair[1]["accepted"]) - int(pair[0]["accepted"]))
        if len(task_differences) == manifest["repetitions"]:
            difference = sum(task_differences) / len(task_differences)
            differences.append(difference)
            accepted_differences.append(sum(task_acceptance) / len(task_acceptance))
            groups.setdefault(task["capability"], []).append(difference)
    coverage = _paired_interval(differences)
    acceptance = _paired_interval(accepted_differences)
    group_reports = {
        group: _paired_interval(groups.get(group, []))
        for group in manifest["required_capabilities"]
    }
    limitations = []
    if not closed:
        limitations.append("study_not_closed")
    if manifest["partition"] != "sealed":
        limitations.append("not_a_sealed_study")
    if missing:
        limitations.append("missing_or_unjudged_pairs")
    if len(differences) < definition["minimum_paired_tasks"]:
        limitations.append("insufficient_independent_tasks")
    if any(outcome["critical_failures"] for outcome in outcomes):
        limitations.append("critical_capability_failure")
    if any(not outcome["attempt_sequence_complete"] for outcome in outcomes):
        limitations.append("missing_attempts")
    if any(
        failure.startswith("unknown_")
        for outcome in outcomes
        for failure in outcome["budget_failures"]
    ):
        limitations.append("unverified_execution_limits")
    for system in manifest["systems"]:
        if system["id"] in (definition["baseline"], definition["candidate"]) and not set(
            manifest["required_capabilities"]
        ).issubset(system["capabilities"]):
            limitations.append(f"omitted_capability:{system['id']}")
    margin = definition.get("loss_margin", 0)
    for name, result in {"coverage": coverage, "acceptance": acceptance, **group_reports}.items():
        mean, lower = result["mean_difference"], result["one_sided_95_lower"]
        if mean is None or mean < 0:
            limitations.append(f"missing_or_reduced_observed_{name}")
        if lower is None or lower < -margin:
            limitations.append(f"confidence_bound_permits_loss:{name}")
    return {
        "definition": definition,
        "method": "Paired task means; distribution-free Hoeffding bounds for differences in [-1, 1]",
        "assumption": "Tasks are independent draws from the declared population; repeats are averaged within tasks.",
        "weighted_fact_coverage": coverage,
        "acceptance": acceptance,
        "capability_groups": group_reports,
        "missing_pairs": missing,
        "decision": "inconclusive" if limitations else "non_inferior",
        "no_quality_loss": not limitations and margin == 0,
        "limitations": limitations,
    }


def _report(events: list[dict], amortized_uses: int | None) -> dict:
    manifest = events[0]["document"]["record"]
    trials, costs, judgments = (_records(events, kind) for kind in ("trial", "cost", "judge"))
    closure = _records(events, "close")
    complete_attestation = bool(closure and closure[0]["accounting_complete"])
    tasks = {task["id"]: task for task in manifest["tasks"]}
    by_trial = {judgment["trial_id"]: judgment for judgment in judgments}
    scored = [
        _trial_result(trial, by_trial.get(trial["id"]), tasks[trial["task_id"]], manifest)
        for trial in trials
    ]
    outcomes = []
    for system in manifest["systems"]:
        for task in manifest["tasks"]:
            for repetition in range(1, manifest["repetitions"] + 1):
                attempts = sorted(
                    (
                        trial
                        for trial in scored
                        if (trial["system_id"], trial["task_id"], trial["repetition"])
                        == (system["id"], task["id"], repetition)
                    ),
                    key=lambda trial: trial["attempt"],
                )
                # The final attempt is the delivered outcome, never the best-scoring retry.
                final = attempts[-1] if attempts else {}
                attempt_ids = {attempt["id"] for attempt in attempts}
                raw_attempts = [trial for trial in trials if trial["id"] in attempt_ids]
                total_usage = _accounting(raw_attempts)
                observed = {
                    "turns": _sum_nullable([trial.get("turns") for trial in raw_attempts]),
                    "wall_seconds": _sum_nullable(
                        [trial.get("resources", {}).get("wall_seconds") for trial in raw_attempts]
                    ),
                    "execution_tokens": total_usage["execution_tokens"]
                    if total_usage["complete"]
                    else None,
                }
                budget_failures = [
                    f"{'unknown' if value is None else 'exceeded'}_{key}"
                    for key, value in observed.items()
                    if value is None or value > manifest["conditions"]["limits"][key]
                ]
                sequence_complete = [trial["attempt"] for trial in attempts] == list(
                    range(1, len(attempts) + 1)
                )
                critical = sorted(
                    {failure for trial in attempts for failure in trial["critical_failures"]}
                )
                outcomes.append(
                    {
                        "system_id": system["id"],
                        "task_id": task["id"],
                        "repetition": repetition,
                        "attempts": len(attempts),
                        "trial_id": final.get("id"),
                        "status": final.get("status", "missing"),
                        "accepted": final.get("accepted", False)
                        and not budget_failures
                        and not critical
                        and sequence_complete,
                        "weighted_fact_coverage": final.get("weighted_fact_coverage"),
                        "critical_failures": critical,
                        "budget_failures": budget_failures,
                        "attempt_sequence_complete": sequence_complete,
                    }
                )
    system_reports = {}
    for system in manifest["systems"]:
        selected = [outcome for outcome in outcomes if outcome["system_id"] == system["id"]]
        selected_trials = [trial for trial in trials if trial["system_id"] == system["id"]]
        selected_costs = [cost for cost in costs if cost["system_id"] == system["id"]]
        accepted = sum(outcome["accepted"] for outcome in selected)
        missing = sum(outcome["status"] == "missing" for outcome in selected)
        attempt_gaps = sum(not outcome["attempt_sequence_complete"] for outcome in selected)
        answering = _accounting(selected_trials)
        all_in = _accounting(selected_trials + selected_costs)
        cohort_complete = complete_attestation and not missing and not attempt_gaps
        can_ratio = cohort_complete and answering["complete"] and accepted > 0
        all_ratio = can_ratio and all_in["complete"]
        phases = {
            phase: _accounting([cost for cost in selected_costs if cost["phase"] == phase])
            for phase in PHASES[1:]
        }
        embeddings = [
            embedding
            for record in selected_trials + selected_costs
            for embedding in record.get("embeddings", [])
        ]
        embedding_groups = {}
        for embedding in embeddings:
            key = (embedding["model"], embedding["unit"])
            embedding_groups.setdefault(key, []).append(embedding["units"])
        scores = [
            outcome["weighted_fact_coverage"]
            for outcome in selected
            if outcome["weighted_fact_coverage"] is not None
        ]
        system_reports[system["id"]] = {
            "planned_outcomes": len(selected),
            "recorded_attempts": len(selected_trials),
            "accepted_outcomes": accepted,
            "missing_outcomes": missing,
            "attempt_sequence_gaps": attempt_gaps,
            "outcome_statuses": dict(Counter(outcome["status"] for outcome in selected)),
            "attempt_statuses": dict(Counter(trial["status"] for trial in selected_trials)),
            "unjudged_attempts": sum(trial["id"] not in by_trial for trial in selected_trials),
            "acceptance_rate": accepted / len(selected),
            "mean_observed_fact_coverage": sum(scores) / len(scores) if scores else None,
            "scored_outcomes": len(scores),
            "answering": answering,
            "phases": phases,
            "cold_all_in": all_in,
            "answering_tokens_per_accepted_outcome": answering["execution_tokens"] / accepted
            if can_ratio
            else None,
            "all_in_tokens_per_accepted_outcome": all_in["execution_tokens"] / accepted
            if all_ratio
            else None,
            "amortized": {
                "uses": amortized_uses,
                "preparation_tokens_per_use": phases["preparation"]["execution_tokens"]
                / amortized_uses
                if all_ratio
                else None,
                "all_in_tokens_per_accepted_outcome": (
                    answering["execution_tokens"]
                    + phases["grading"]["execution_tokens"]
                    + (
                        phases["preparation"]["execution_tokens"]
                        + phases["knowledge_synthesis"]["execution_tokens"]
                    )
                    / amortized_uses
                )
                / accepted
                if all_ratio
                else None,
            }
            if amortized_uses
            else None,
            "ratio_limitations": [
                reason
                for reason, applies in (
                    ("zero_accepted_outcomes", not accepted),
                    ("accounting_not_attested_complete", not complete_attestation),
                    ("missing_outcomes", bool(missing)),
                    ("missing_attempts", bool(attempt_gaps)),
                    ("incomplete_or_estimated_usage", not all_in["complete"]),
                )
                if applies
            ],
            "resources": _resources(selected_trials + selected_costs),
            "resources_by_phase": {
                "answering": _resources(selected_trials),
                **{
                    phase: _resources([cost for cost in selected_costs if cost["phase"] == phase])
                    for phase in PHASES[1:] + ("embedding",)
                },
            },
            "embedding_work": [
                {"model": model, "unit": unit, "units": _sum_nullable(units), "records": len(units)}
                for (model, unit), units in embedding_groups.items()
            ],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": manifest["id"],
        "manifest_digest": events[0]["digest"],
        "evidence_digest": events[-1]["digest"],
        "evidence_events": len(events),
        "closed": bool(closure),
        "evidence_kind": "recorded_trials",
        "systems": system_reports,
        "trials": scored,
        "outcomes": outcomes,
        "comparison": _comparison(manifest, outcomes, bool(closure)),
        "limitations": [
            "Scores and citation validity are recorded evaluator judgments, not independent verification by this reporter.",
            "This interface records and replays supplied evidence; it does not execute models or certify study independence.",
        ],
    }


def dispatch(action: str, payload: dict) -> dict:
    """Validate, record, or replay a frozen local study. Never runs model calls."""
    _mapping(payload, "payload")
    study = Path(_text(payload.get("study"), "study"))
    if action not in ("freeze", "trial", "judge", "cost", "close", "inspect", "report"):
        raise ValueError("Unknown evaluation action")
    with _database(study, create=action == "freeze") as connection:
        events = _events(connection)
        if action == "freeze":
            manifest = _manifest(payload.get("manifest"))
            if events:
                if events[0]["document"]["record"] != manifest:
                    raise ValueError(
                        "Study manifest is frozen; changed conditions require a new study"
                    )
                return {
                    "schema_version": SCHEMA_VERSION,
                    "manifest_digest": events[0]["digest"],
                    "duplicate": True,
                }
            receipt = _append(
                connection,
                "manifest",
                "manifest",
                {"record": manifest, "recorded_at": datetime.now(UTC).isoformat()},
            )
            return {
                "schema_version": SCHEMA_VERSION,
                "manifest_digest": receipt["digest"],
                "duplicate": False,
            }
        if not events:
            raise ValueError("Study has no frozen manifest")
        _execution_ids(events)
        if action == "inspect":
            return {"schema_version": SCHEMA_VERSION, "events": events}
        if action == "report":
            uses = payload.get("amortized_uses")
            if uses is not None and _number(uses, "amortized_uses", integer=True) == 0:
                raise ValueError("amortized_uses must be positive")
            return _report(events, uses)
        record = json.loads(_json(_mapping(payload.get("record"), "record")))
        _text(record.get("id"), "record.id")
        for event in events:
            if event["id"] == record["id"]:
                if event["kind"] == action and event["document"]["record"] == record:
                    return {
                        "schema_version": SCHEMA_VERSION,
                        "id": event["id"],
                        "digest": event["digest"],
                        "duplicate": True,
                    }
                raise ValueError("An event ID cannot replace previously recorded evidence")
        if _records(events, "close"):
            raise ValueError("Study is closed; create a new study to add or revise evidence")
        _validate_record(action, record, events[0]["document"]["record"], events)
        seen_ids = _execution_ids(events)
        for execution in record.get("executions", []):
            if execution["id"] in seen_ids:
                raise ValueError("Duplicate execution ID would double-count usage")
            seen_ids.add(execution["id"])
        receipt = _append(
            connection,
            action,
            record["id"],
            {"record": record, "recorded_at": datetime.now(UTC).isoformat()},
        )
        return {"schema_version": SCHEMA_VERSION, **receipt}
