"""Datasets, corpora and gold labels for the evaluation suites.

Every label comes from the dataset's own authors: SWE-bench Verified gold
patches, LOCOMO evidence dialog IDs, LongMemEval answer sessions, BEIR SciFact
qrels, and the AFP ERPNext rubrics' evidence spans (read in place from the AFP
checkout so its sealed rubrics are not copied into this repository).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CACHE = Path(
    os.environ.get(
        "INQUIRY_EVAL_CACHE", Path.home() / ".cache" / "agentic-inquiry-evals"
    )
)
AFP_ROOT = Path(
    os.environ.get(
        "AFP_BENCH_ROOT", Path.home() / "projects" / "afp" / "benchmarks" / "afp"
    )
)
SEED = 20260926

# URL and pinned sha256 per dataset; a mismatch refuses to run (RFC-0003).
SOURCES = {
    "swebench": (
        "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/main/data/test-00000-of-00001.parquet",
        "a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd",
    ),
    "locomo": (
        "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json",
        "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
    ),
    "longmemeval": (
        "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json",
        "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
    ),
    "scifact": (
        "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip",
        "536e14446a0ba56ed1398ab1055f39fe852686ecad24a6306c80c490fa8e0165",
    ),
}
# Bump when gold-label derivation changes so cached labels are rebuilt.
LABELS_VERSION = 2

# Per-repo caps for the SWE-bench Verified sample (150 tasks, all 12 repos).
SWEBENCH_CAPS = {
    "django/django": 42,
    "sympy/sympy": 20,
    "sphinx-doc/sphinx": 15,
    "matplotlib/matplotlib": 15,
    "scikit-learn/scikit-learn": 15,
    "astropy/astropy": 10,
    "pydata/xarray": 10,
    "pytest-dev/pytest": 10,
    "pylint-dev/pylint": 5,
    "psf/requests": 5,
    "mwaskom/seaborn": 2,
    "pallets/flask": 1,
}

ERPNEXT_REPO = "frappe/erpnext"
ERPNEXT_REVISION = "df8b7f9648c2ec4da12db8c4022edc8dd1018c6b"


@dataclass
class Case:
    """One query with its gold labels.

    Code suites fill ``gold_lines`` (path -> pre-image lines) and
    ``gold_functions`` (path, start, end); every suite fills ``gold_units``
    (file paths for code, turn/session/document IDs otherwise) with gains.
    """

    id: str
    suite: str
    corpus: str
    query: str
    gold_units: dict[str, float]
    gold_lines: dict[str, set[int]] = field(default_factory=dict)
    gold_functions: list[tuple[str, int, int]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    split_unit: str = ""
    fixed_split: str = ""

    @property
    def split(self) -> str:
        """Dev or test: fixed by the suite, else hashed from the split unit (the case by default)."""
        return self.fixed_split or split_of(self.split_unit or self.id)


@dataclass
class Suite:
    """A set of cases plus how to materialize the corpus each one searches.

    ``window`` is the retrieval unit for the baseline arms: that many lines per
    unit, or 0 for one unit per file. ``unit_pattern`` extracts unit IDs from
    rendered text when units are finer than files (LOCOMO turns).
    """

    name: str
    cases: list[Case]
    materialize: Callable[[str], Path]
    window: int
    unit_pattern: str | None = None
    code: bool = False
    data_sha256: dict[str, str] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def parse_patch(patch: str) -> dict[str, set[int]]:
    """Map each pre-existing file a unified diff touches to its gold pre-image lines.

    Deleted lines are gold. A run of pure insertions anchors on the pre-image
    line before it (line 1 at the top of a file). Files the patch creates have
    no pre-image and are omitted.
    """
    gold: dict[str, set[int]] = defaultdict(set)
    path: str | None = None
    old = 0
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("--- "):
            source = line[4:].split("\t")[0].strip()
            path = None if source == "/dev/null" else source.removeprefix("a/")
            in_hunk = False
            continue
        if line.startswith("+++ ") and not in_hunk:
            continue
        match = _HUNK.match(line)
        if match:
            old = int(match.group(1))
            in_hunk = True
            continue
        if not in_hunk or path is None:
            continue
        if line.startswith("-"):
            gold[path].add(old)
            old += 1
        elif line.startswith("+"):
            gold[path].add(max(old - 1, 1))
        elif line.startswith(" ") or line == "":
            old += 1
        elif line.startswith("diff "):
            in_hunk = False
    return {p: lines for p, lines in gold.items() if lines}


def insertion_pairs(patch: str) -> dict[str, list[tuple[int, int]]]:
    """Pre-image neighbour lines ``(before, after)`` around each run of insertions."""
    pairs: dict[str, list[tuple[int, int]]] = defaultdict(list)
    path: str | None = None
    old = 0
    in_hunk = False
    previous = ""
    for line in patch.splitlines():
        if line.startswith("--- "):
            source = line[4:].split("\t")[0].strip()
            path = None if source == "/dev/null" else source.removeprefix("a/")
            in_hunk = False
            continue
        if line.startswith("+++ ") and not in_hunk:
            continue
        match = _HUNK.match(line)
        if match:
            old = int(match.group(1))
            in_hunk = True
            previous = ""
            continue
        if not in_hunk or path is None:
            continue
        if line.startswith("+"):
            if not previous.startswith("+"):
                pairs[path].append((max(old - 1, 1), max(old, 1)))
        elif line.startswith("-") or line.startswith(" ") or line == "":
            old += 1
        previous = line
    return dict(pairs)


def enclosing_defs(
    source: str, lines: Iterable[int], pairs: Iterable[tuple[int, int]] = ()
) -> set[tuple[int, int]]:
    """Innermost function or class span (decorators included) around each line.

    Each ``(before, after)`` pair names the neighbours of an insertion; its
    gold definition is the innermost one containing both lines, so a method
    added between two methods is credited to the class, not to its neighbour.
    """
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            spans.append((start, node.end_lineno or node.lineno))
    found: set[tuple[int, int]] = set()
    targets = [(line, line) for line in lines] + list(pairs)
    for low, high in targets:
        containing = [s for s in spans if s[0] <= low and high <= s[1]]
        if containing:
            found.add(min(containing, key=lambda s: s[1] - s[0]))
    return found


def split_of(case_id: str) -> str:
    """Stable assignment: one third dev, two thirds test."""
    return (
        "dev"
        if int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 3 == 0
        else "test"
    )


_EVIDENCE = re.compile(r"D(\d+):(\d+)", re.IGNORECASE)


def evidence_ids(raw: Iterable[str]) -> list[str]:
    """Normalize LOCOMO evidence entries (some hold several IDs or bad case)."""
    ids: list[str] = []
    for entry in raw:
        for session, turn in _EVIDENCE.findall(entry):
            ident = f"D{session}:{turn}"
            if ident not in ids:
                ids.append(ident)
    return ids


def stratified_sample(
    rows: list[dict[str, Any]], key: str, id_field: str, caps: dict[str, int], seed: int
) -> list[dict[str, Any]]:
    """Take up to ``caps[group]`` rows per group, ordered by a seeded hash."""

    def rank(row: dict[str, Any]) -> str:
        return hashlib.sha256(f"{seed}:{row[id_field]}".encode()).hexdigest()

    picked: list[dict[str, Any]] = []
    for group, cap in caps.items():
        members = sorted((r for r in rows if r[key] == group), key=rank)
        picked.extend(members[:cap])
    return picked


# --------------------------------------------------------------------------
# Fetching and materialization
# --------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(name: str) -> Path:
    """Download a dataset file once into the cache and verify its pinned hash."""
    url, expected = SOURCES[name]
    target = CACHE / "data" / Path(url.split("?")[0]).name
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        with (
            urllib.request.urlopen(url, timeout=600) as response,
            partial.open("wb") as out,
        ):  # noqa: S310 - fixed https URLs
            shutil.copyfileobj(response, out)
        partial.rename(target)
    actual = _sha256(target)
    if actual != expected:
        raise RuntimeError(
            f"{name} dataset changed upstream: sha256 {actual} != pinned {expected}"
        )
    return target


def _git(args: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def ensure_clone(repo: str) -> Path:
    """Bare clone of a GitHub repository, fetched once."""
    target = CACHE / "repos" / (repo.replace("/", "__") + ".git")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        _git(
            [
                "clone",
                "--bare",
                "--quiet",
                f"https://github.com/{repo}.git",
                str(target),
            ]
        )
    return target


def snapshot(repo: str, commit: str) -> Path:
    """Read-only working tree of ``repo`` at ``commit``."""
    target = CACHE / "snapshots" / f"{repo.replace('/', '__')}@{commit[:12]}"
    if target.exists():
        return target
    clone = ensure_clone(repo)
    try:
        _git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=clone)
    except subprocess.CalledProcessError:
        _git(["fetch", "--quiet", "origin", commit], cwd=clone)
    partial = target.with_name(target.name + ".part")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=clone,
        check=True,
        capture_output=True,
    ).stdout
    tar_path = partial.with_suffix(".tar")
    tar_path.write_bytes(archive)
    with tarfile.open(tar_path) as tar:
        tar.extractall(partial, filter="data")
    tar_path.unlink()
    partial.rename(target)
    return target


def _write_corpus(target: Path, files: dict[str, str]) -> Path:
    if target.exists():
        return target
    partial = target.with_name(target.name + ".part")
    shutil.rmtree(partial, ignore_errors=True)
    for name, text in files.items():
        path = partial / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    partial.rename(target)
    return target


# --------------------------------------------------------------------------
# Suites
# --------------------------------------------------------------------------


def patch_gold(repo: str, base_commit: str, patch: str) -> dict[str, Any]:
    """Gold pre-image lines per file and the innermost definitions enclosing them."""
    gold = parse_patch(patch)
    pairs = insertion_pairs(patch)
    clone = ensure_clone(repo)
    functions: list[tuple[str, int, int]] = []
    for path, lines in gold.items():
        if not path.endswith(".py"):
            continue
        try:
            text = _git(["show", f"{base_commit}:{path}"], cwd=clone)
        except subprocess.CalledProcessError:
            try:
                _git(["fetch", "--quiet", "origin", base_commit], cwd=clone)
                text = _git(["show", f"{base_commit}:{path}"], cwd=clone)
            except subprocess.CalledProcessError:
                continue
        deleted = lines - {a for a, _ in pairs.get(path, [])}
        spans = enclosing_defs(text, deleted, pairs.get(path, []))
        functions += [(path, s, e) for s, e in sorted(spans)]
    return {"lines": {p: sorted(v) for p, v in gold.items()}, "functions": functions}


def load_swebench() -> Suite:
    import pandas as pd

    source = fetch("swebench")
    frame = pd.read_parquet(source)
    rows = frame.to_dict("records")
    sample = stratified_sample(
        rows, key="repo", id_field="instance_id", caps=SWEBENCH_CAPS, seed=SEED
    )
    labels_path = (
        CACHE / "cases" / f"swebench-{_sha256(source)[:12]}-v{LABELS_VERSION}.json"
    )
    labels: dict[str, Any] = (
        json.loads(labels_path.read_text()) if labels_path.exists() else {}
    )
    cases: list[Case] = []
    dropped = 0
    for row in sample:
        iid = row["instance_id"]
        if iid not in labels:
            labels[iid] = patch_gold(row["repo"], row["base_commit"], row["patch"])
        entry = labels[iid]
        if not entry["lines"]:
            dropped += 1
            continue
        cases.append(
            Case(
                id=iid,
                suite="swebench",
                corpus=f"{row['repo']}@{row['base_commit']}",
                query=row["problem_statement"],
                gold_units={p: 1.0 for p in entry["lines"]},
                gold_lines={p: set(v) for p, v in entry["lines"].items()},
                gold_functions=[tuple(f) for f in entry["functions"]],  # type: ignore[misc]
                meta={"repo": row["repo"], "difficulty": row.get("difficulty")},
            )
        )
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.write_text(json.dumps(labels))

    def materialize(corpus: str) -> Path:
        repo, commit = corpus.split("@")
        return snapshot(repo, commit)

    return Suite(
        "swebench",
        cases,
        materialize,
        window=50,
        code=True,
        data_sha256={"swebench": _sha256(source)},
        dropped={"no_preimage_gold": dropped},
    )


def load_erpnext() -> Suite:
    tasks = json.loads((AFP_ROOT / "manifests" / "retrieval-tasks.json").read_text())[
        "tasks"
    ]
    cases: list[Case] = []
    hashes: dict[str, str] = {}
    for task in tasks:
        rubric_path = AFP_ROOT / task["rubric_path"]
        hashes[task["id"]] = _sha256(rubric_path)
        rubric = json.loads(rubric_path.read_text())
        lines: dict[str, set[int]] = defaultdict(set)
        for fact in rubric["facts"]:
            for ev in fact.get("evidence", []):
                lines[ev["path"]].update(range(ev["start_line"], ev["end_line"] + 1))
        cases.append(
            Case(
                id=task["id"],
                suite="erpnext",
                corpus=f"{ERPNEXT_REPO}@{ERPNEXT_REVISION}",
                query=task["prompt"],
                gold_units={p: 1.0 for p in lines},
                gold_lines=dict(lines),
                fixed_split="test",
            )
        )

    def materialize(corpus: str) -> Path:
        repo, commit = corpus.split("@")
        return snapshot(repo, commit)

    return Suite(
        "erpnext", cases, materialize, window=50, code=True, data_sha256=hashes
    )


def _locomo_line(turn: dict[str, Any], date: str) -> str:
    text = " ".join(str(turn.get("text", "")).split())
    caption = turn.get("blip_caption")
    if caption:
        text += f" [shares an image: {caption}]"
    return f"[{turn['dia_id']}] ({date}) {turn['speaker']}: {text}"


def load_locomo() -> Suite:
    source = fetch("locomo")
    data = json.loads(source.read_text())
    cases: list[Case] = []
    corpora: dict[str, dict[str, str]] = {}
    dropped: dict[str, int] = defaultdict(int)
    for conv in data:
        sample = conv["sample_id"]
        conversation = conv["conversation"]
        files: dict[str, str] = {}
        present: set[str] = set()
        index = 1
        while f"session_{index}" in conversation:
            date = conversation.get(f"session_{index}_date_time", "")
            turns = conversation[f"session_{index}"]
            files[f"session_{index}.txt"] = (
                "\n".join(_locomo_line(t, date) for t in turns) + "\n"
            )
            present.update(t["dia_id"] for t in turns)
            index += 1
        corpora[sample] = files
        for number, qa in enumerate(conv["qa"]):
            if qa.get("category") == 5:
                dropped["adversarial_category_5"] += 1
                continue
            evidence = [e for e in evidence_ids(qa.get("evidence", [])) if e in present]
            if not evidence:
                dropped["no_evidence_in_corpus"] += 1
                continue
            cases.append(
                Case(
                    id=f"{sample}-q{number}",
                    suite="locomo",
                    corpus=sample,
                    query=str(qa["question"]),
                    gold_units={e: 1.0 for e in evidence},
                    meta={
                        "category": qa["category"],
                        "answer": str(qa.get("answer", "")),
                    },
                    split_unit=sample,
                )
            )

    # Ten conversations are too few for a hashed third: the three with the
    # lowest seeded hash are dev, the other seven test (RFC-0003).
    ranked = sorted(
        corpora, key=lambda s: hashlib.sha256(f"{SEED}:{s}".encode()).hexdigest()
    )
    dev = set(ranked[:3])
    for case in cases:
        case.fixed_split = "dev" if case.corpus in dev else "test"

    def materialize(corpus: str) -> Path:
        return _write_corpus(CACHE / "corpora" / "locomo" / corpus, corpora[corpus])

    return Suite(
        "locomo",
        cases,
        materialize,
        window=1,
        unit_pattern=r"\[(D\d+:\d+)\]",
        data_sha256={"locomo": _sha256(source)},
        dropped=dict(dropped),
    )


def load_longmemeval() -> Suite:
    """LongMemEval-S with the turns the dataset marks ``has_answer`` as evidence.

    Each session file holds one turn per line, prefixed ``[<session>#t<n>]``
    and its date, so evidence is scored on the answer turns an arm renders,
    not on touching the right session file.
    """
    source = fetch("longmemeval")
    data = json.loads(source.read_text())
    by_corpus: dict[str, dict[str, str]] = {}
    cases: list[Case] = []
    dropped = 0
    for item in data:
        qid = item["question_id"]
        if qid.endswith("_abs"):
            dropped += 1
            continue
        files: dict[str, str] = {}
        evidence: list[str] = []
        # Dataset session IDs mark the evidence sessions (every one starts with
        # "answer_"), so tools and answerers see an opaque ordinal instead.
        opaque = {
            raw: f"s{number:03d}"
            for number, raw in enumerate(item["haystack_session_ids"])
        }
        for raw_sid, date, session in zip(
            item["haystack_session_ids"],
            item["haystack_dates"],
            item["haystack_sessions"],
        ):
            sid = opaque[raw_sid]
            rows = []
            for number, turn in enumerate(session):
                marker = f"{sid}#t{number}"
                rows.append(
                    f"[{marker}] ({date}) {turn['role']}: {' '.join(str(turn['content']).split())}"
                )
                if turn.get("has_answer"):
                    evidence.append(marker)
            files[f"{sid}.txt"] = "\n".join(rows) + "\n"
        by_corpus[f"opaque-{qid}"] = files
        if not evidence:
            dropped += 1
            continue
        cases.append(
            Case(
                id=qid,
                suite="longmemeval",
                corpus=f"opaque-{qid}",
                query=item["question"],
                gold_units={marker: 1.0 for marker in evidence},
                meta={
                    "type": item["question_type"],
                    "answer": str(item["answer"]),
                    "gold_sessions": sorted(
                        opaque[s]
                        for s in set(item["answer_session_ids"])
                        if s in opaque
                    ),
                    "question_date": str(item.get("question_date", "")),
                },
            )
        )

    def materialize(corpus: str) -> Path:
        return _write_corpus(
            CACHE / "corpora" / "longmemeval-opaque" / corpus, by_corpus[corpus]
        )

    return Suite(
        "longmemeval",
        cases,
        materialize,
        window=1,
        unit_pattern=r"\[([^\]\s]+#t\d+)\]",
        data_sha256={"longmemeval": _sha256(source)},
        dropped={"abstention_or_no_evidence": dropped},
    )


def load_scifact() -> Suite:
    source = fetch("scifact")
    root = CACHE / "data" / "scifact"
    if not root.exists():
        with zipfile.ZipFile(source) as archive:
            archive.extractall(CACHE / "data")
    corpus_rows = [
        json.loads(line)
        for line in (root / "corpus.jsonl").read_text().splitlines()
        if line
    ]
    queries = {
        q["_id"]: q["text"]
        for q in map(json.loads, (root / "queries.jsonl").read_text().splitlines())
        if q
    }
    qrels: dict[str, dict[str, float]] = defaultdict(dict)
    for line in (root / "qrels" / "test.tsv").read_text().splitlines()[1:]:
        qid, doc, score = line.split("\t")
        if int(score) > 0:
            qrels[qid][f"{doc}.txt"] = float(score)
    files = {
        f"{row['_id']}.txt": f"{row.get('title', '')}\n{row['text']}\n"
        for row in corpus_rows
    }
    cases = [
        Case(
            id=f"scifact-{qid}",
            suite="scifact",
            corpus="scifact",
            query=queries[qid],
            gold_units=gold,
        )
        for qid, gold in sorted(qrels.items(), key=lambda kv: int(kv[0]))
    ]

    def materialize(corpus: str) -> Path:
        return _write_corpus(CACHE / "corpora" / "scifact" / "corpus", files)

    return Suite(
        "scifact",
        cases,
        materialize,
        window=0,
        data_sha256={"scifact": _sha256(source)},
    )


def _load_fresh() -> Suite:
    from evals.fresh import load_fresh

    return load_fresh()


LOADERS: dict[str, Callable[[], Suite]] = {
    "swebench": load_swebench,
    "fresh": _load_fresh,
    "erpnext": load_erpnext,
    "locomo": load_locomo,
    "longmemeval": load_longmemeval,
    "scifact": load_scifact,
}
