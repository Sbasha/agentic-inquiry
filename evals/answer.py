"""Level B: answer LOCOMO questions from each arm's budgeted context, then judge.

The answerer and primary judge run through the Claude Code CLI (``claude -p``)
on the user's subscription, or through Moonshot's ``kimi-k2.6`` (Graphify's
model) when ``MOONSHOT_API_KEY`` is set. A second judge from a different model
family runs locally through Ollama, so judge agreement costs nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import string
import subprocess
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.data import CACHE, LOADERS, SEED, Case
from evals.metrics import paired, render
from evals.run import REPO_ROOT, RESULTS, _git, applicable_arms, collect

BUDGET = 2000
ANSWERER = "claude-haiku-4-5-20251001"
JUDGE = "claude-sonnet-5"
SECOND_JUDGE = "qwen2.5:14b-instruct"
KIMI = "kimi-k2.6"
PARALLEL = 4

ANSWER_PROMPT = """You are answering a question about a long conversation between two people.
Use only the retrieved excerpts below. Each excerpt line starts with a dialog id and the date of its session.

Excerpts:
{context}

Question: {question}

Answer with a short phrase. Resolve relative times ("last week", "yesterday") against the session date.
If the excerpts do not contain the answer, reply exactly: Not mentioned."""

JUDGE_PROMPT = """Label a generated answer as CORRECT or WRONG against a gold answer.

The question asks about something one speaker should know about the other from their past conversations.
The gold answer is short. The generated answer may be longer or phrased differently; grade generously:
it is CORRECT when it refers to the same thing as the gold answer. For dates and times, it is CORRECT
when it names the same date or period, even in a different format or as a relative time that resolves
to it. It is WRONG when it names something different, contradicts the gold answer, or says the
information is not available.

Question: {question}
Gold answer: {gold}
Generated answer: {answer}

Reply with JSON only: {{"label": "CORRECT"}} or {{"label": "WRONG"}}"""


# --------------------------------------------------------------------------
# Scoring helpers
# --------------------------------------------------------------------------


def _normalize(text: str) -> list[str]:
    import Stemmer

    stemmer = Stemmer.Stemmer("english")
    text = text.lower().replace(",", "")
    text = "".join(ch for ch in text if ch not in set(string.punctuation))
    text = re.sub(r"\b(a|an|the|and)\b", " ", text)
    return [stemmer.stemWord(w) for w in text.split()]


def token_f1(prediction: str, gold: str) -> float:
    """LOCOMO's token F1: normalized, stemmed bag-of-words overlap."""
    pred, ref = _normalize(prediction), _normalize(gold)
    common = Counter(pred) & Counter(ref)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision, recall = overlap / len(pred), overlap / len(ref)
    return 2 * precision * recall / (precision + recall)


def cohen_kappa(a: list[int], b: list[int]) -> float:
    """Agreement between two binary raters beyond chance."""
    n = len(a)
    if n == 0:
        return 0.0
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def parse_label(text: str) -> int | None:
    match = re.search(r"\b(CORRECT|WRONG)\b", text.upper())
    return None if match is None else int(match.group(1) == "CORRECT")


def stratified(cases: list[Case], n: int, key: str) -> list[Case]:
    """Proportional allocation per stratum, seeded order within each."""
    groups: dict[Any, list[Case]] = defaultdict(list)
    for case in cases:
        groups[case.meta.get(key)].append(case)
    total = len(cases)
    picked: list[Case] = []
    for _, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        members.sort(key=lambda c: hashlib.sha256(f"{SEED}:{c.id}".encode()).hexdigest())
        picked += members[: max(1, round(n * len(members) / total))]
    return picked[:n]


# --------------------------------------------------------------------------
# Model routes (cached)
# --------------------------------------------------------------------------


def _cache_path(model: str, prompt: str) -> Path:
    key = hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()
    return CACHE / "llm" / key[:2] / f"{key}.json"


def complete(model: str, prompt: str) -> dict[str, Any]:
    """One completion, cached by (model, prompt). Returns text and usage."""
    path = _cache_path(model, prompt)
    if path.exists():
        return json.loads(path.read_text())
    if model.startswith("claude-"):
        result = _claude(model, prompt)
    elif model == KIMI:
        result = _moonshot(model, prompt)
    else:
        result = _ollama(model, prompt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    return result


def _claude(model: str, prompt: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(
            ["claude", "-p", "--model", model, "--output-format", "json", "--setting-sources", "project",
             "--no-session-persistence", "--tools", "", "--system-prompt", "You are a precise assistant."],
            input=prompt, capture_output=True, text=True, cwd=cwd, timeout=300,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed: {proc.stderr.strip()[-300:] or proc.stdout[-300:]}")
    data = json.loads(proc.stdout)
    if data.get("is_error"):
        raise RuntimeError(f"claude -p error: {str(data.get('result'))[:300]}")
    usage = data.get("usage", {})
    return {"text": str(data.get("result", "")).strip(), "model": model,
            "input_tokens": usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0)}


def _moonshot(model: str, prompt: str) -> dict[str, Any]:
    body = json.dumps({"model": model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]}).encode()
    request = urllib.request.Request(
        "https://api.moonshot.ai/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['MOONSHOT_API_KEY']}"})
    with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 - fixed https URL
        data = json.loads(response.read())
    usage = data.get("usage", {})
    return {"text": data["choices"][0]["message"]["content"].strip(), "model": model,
            "input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)}


def _ollama(model: str, prompt: str) -> dict[str, Any]:
    body = json.dumps({"model": model, "stream": False, "format": "json", "options": {"temperature": 0, "seed": SEED},
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    request = urllib.request.Request("http://localhost:11434/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310 - local Ollama
        data = json.loads(response.read())
    return {"text": data["message"]["content"].strip(), "model": model,
            "input_tokens": data.get("prompt_eval_count", 0), "output_tokens": data.get("eval_count", 0)}


def _ollama_digest(model: str) -> str:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=10) as response:  # noqa: S310
            tags = json.loads(response.read())
        return next((m["digest"] for m in tags.get("models", []) if m["name"] == model), "missing")
    except OSError:
        return "unavailable"


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------


def run_answers(arm_names: list[str], split: str, n: int, jobs: int = 3) -> Path:
    suite = LOADERS["locomo"]()
    pool_cases = [c for c in suite.cases if c.split == split]
    cases = stratified(pool_cases, n, "category")
    arms = applicable_arms(suite, arm_names)
    answerer = KIMI if os.environ.get("MOONSHOT_API_KEY") else ANSWERER
    judge = KIMI if os.environ.get("MOONSHOT_API_KEY") else JUDGE
    started = datetime.now(timezone.utc)
    retrieved, _ = collect(suite, arms, cases, jobs)

    work: list[tuple[str, Case, str, int]] = []
    rows: list[dict[str, Any]] = []
    for arm in arms:
        for case in cases:
            got = retrieved[(arm.name, case.id)]
            if isinstance(got, str):
                rows.append({"arm": arm.name, "case": case.id, "error": got})
                continue
            rendered = render(got.hits, BUDGET, unit_pattern=suite.unit_pattern)
            work.append((arm.name, case, rendered.text, rendered.tokens))

    def answer_and_judge(item: tuple[str, Case, str, int]) -> dict[str, Any]:
        arm_name, case, context, tokens = item
        gold = case.meta["answer"]
        try:
            answer = complete(answerer, ANSWER_PROMPT.format(context=context, question=case.query))
            verdict = complete(judge, JUDGE_PROMPT.format(question=case.query, gold=gold, answer=answer["text"]))
            second = complete(SECOND_JUDGE, JUDGE_PROMPT.format(question=case.query, gold=gold, answer=answer["text"]))
        except Exception as exc:  # noqa: BLE001 - recorded per item
            return {"arm": arm_name, "case": case.id, "error": str(exc)[-300:]}
        return {
            "arm": arm_name, "case": case.id, "category": case.meta.get("category"), "context_tokens": tokens,
            "gold": gold, "answer": answer["text"], "answer_input_tokens": answer["input_tokens"],
            "judge": parse_label(verdict["text"]), "second_judge": parse_label(second["text"]),
            "f1": round(token_f1(answer["text"], gold), 4),
        }

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        for number, row in enumerate(pool.map(answer_and_judge, work), 1):
            rows.append(row)
            if number % 25 == 0:
                print(f"  answered {number}/{len(work)}", file=sys.stderr)

    report = _answer_report(rows, arms, cases, split, started, answerer, judge)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    target = RESULTS / "locomo" / f"answers-{split}-{stamp}-{_git('rev-parse', '--short=8', 'HEAD')}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    _print(report)
    print(f"results: {target.relative_to(REPO_ROOT)}", file=sys.stderr)
    return target


def _answer_report(rows: list[dict[str, Any]], arms: list[Any], cases: list[Case], split: str,
                   started: datetime, answerer: str, judge: str) -> dict[str, Any]:
    good = [r for r in rows if "error" not in r and r["judge"] is not None]
    both = [r for r in good if r["second_judge"] is not None]
    kappa = cohen_kappa([r["judge"] for r in both], [r["second_judge"] for r in both])
    summary: dict[str, Any] = {}
    by_arm: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in good:
        by_arm[row["arm"]][row["case"]] = row
    for arm in arms:
        items = list(by_arm[arm.name].values())
        count = max(1, len(items))
        summary[arm.name] = {
            "n": len(items),
            "errors": sum(1 for r in rows if r["arm"] == arm.name and ("error" in r or r.get("judge") is None)),
            "accuracy": round(sum(r["judge"] for r in items) / count, 4),
            "second_judge_accuracy": round(sum(r["second_judge"] or 0 for r in items) / count, 4),
            "f1": round(sum(r["f1"] for r in items) / count, 4),
            "median_context_tokens": sorted(r["context_tokens"] for r in items)[len(items) // 2] if items else 0,
        }
    corpus_of = {c.id: c.corpus for c in cases}
    comparisons = []
    reference = "inquiry" if "inquiry" in by_arm else (arms[0].name if arms else "")
    for arm in arms:
        if arm.name == reference:
            continue
        shared = sorted(set(by_arm[reference]) & set(by_arm[arm.name]))
        for metric in ("judge", "f1"):
            a = [float(by_arm[reference][c][metric]) for c in shared]
            b = [float(by_arm[arm.name][c][metric]) for c in shared]
            stats = paired(a, b, seed=SEED, clusters=[corpus_of[c] for c in shared])
            comparisons.append({"metric": "accuracy" if metric == "judge" else "f1", "a": reference, "b": arm.name,
                                "clustered": True, **stats})
    return {
        "schema": "InquiryEvalAnswers/v1",
        "suite": "locomo",
        "split": split,
        "budget_tokens": BUDGET,
        "provenance": {
            "sha": _git("rev-parse", "HEAD"),
            "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "started_utc": started.isoformat(timespec="seconds"),
            "answerer": answerer,
            "judge": judge,
            "second_judge": {"model": SECOND_JUDGE, "digest": _ollama_digest(SECOND_JUDGE)},
            "answer_prompt_sha256": hashlib.sha256(ANSWER_PROMPT.encode()).hexdigest(),
            "judge_prompt_sha256": hashlib.sha256(JUDGE_PROMPT.encode()).hexdigest(),
            "seed": SEED,
        },
        "judge_agreement": {"n": len(both), "cohen_kappa": round(kappa, 4)},
        "summary": summary,
        "comparisons": comparisons,
        "rows": rows,
    }


def _print(report: dict[str, Any]) -> None:
    print(f"\nlocomo answers / {report['split']}  kappa={report['judge_agreement']['cohen_kappa']:.3f}")
    print(f"{'arm':12}  {'accuracy':>9}  {'judge2':>7}  {'f1':>6}  {'ctx tok':>7}  err")
    for arm, s in report["summary"].items():
        print(f"{arm:12}  {s['accuracy']:9.4f}  {s['second_judge_accuracy']:7.4f}  {s['f1']:6.4f}  "
              f"{s['median_context_tokens']:7d}  {s['errors']}")
    for c in report["comparisons"]:
        print(f"  {c['metric']}: {c['a']} - {c['b']}: {c['mean_diff']:+.4f} [{c['ci_low']:+.4f}, {c['ci_high']:+.4f}]")
