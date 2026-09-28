"""C3 tasks mined from fixes merged after the agent model's training cutoff (RFC-0004).

``python -m evals mine-fresh`` writes ``evals/tasks/fresh-2026.jsonl`` once;
``load_fresh`` reads it as a code suite. A task is the linked issue's title and
body, the corpus is the repository at the merge commit's first parent, and the
gold is the pre-image of the non-test Python changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from evals.data import (
    SEED,
    Case,
    Suite,
    _git,
    ensure_clone,
    patch_gold,
    snapshot,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "evals" / "tasks" / "fresh-2026.jsonl"
MANIFEST_B = REPO_ROOT / "evals" / "tasks" / "fresh-2026b.jsonl"
C3B_TASKS = 100
MERGED_FROM, MERGED_TO = "2026-02-01", "2026-09-26"
CAPS = {
    "pytest-dev/pytest": 15,
    "sympy/sympy": 15,
    "matplotlib/matplotlib": 15,
    "scikit-learn/scikit-learn": 15,
    "astropy/astropy": 15,
    "pylint-dev/pylint": 15,
    "pydata/xarray": 10,
}
MIN_TEXT, MAX_TEXT = 100, 20_000
MAX_FILES = 5

_QUERY = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number
        mergedAt
        mergeCommit { oid }
        closingIssuesReferences(first: 5) {
          nodes { number createdAt title body repository { nameWithOwner } }
        }
      }
    }
  }
}
"""


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return (
        any(part in {"tests", "testing"} for part in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _pull_requests(repo: str) -> list[dict[str, Any]]:
    query = (
        f"repo:{repo} is:pr is:merged merged:{MERGED_FROM}..{MERGED_TO} linked:issue"
    )
    out: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        args = ["gh", "api", "graphql", "-f", f"query={_QUERY}", "-f", f"q={query}"]
        if after:
            args += ["-f", f"after={after}"]
        data = json.loads(
            subprocess.run(args, check=True, capture_output=True, text=True).stdout
        )
        page = data["data"]["search"]
        out += [node for node in page["nodes"] if node]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        after = page["pageInfo"]["endCursor"]


def _order(task_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{task_id}".encode()).hexdigest()


def candidate(repo: str, pr: dict[str, Any]) -> dict[str, Any] | None:
    """The task a pull request yields, or None when it fails a pre-registered rule."""
    issues = pr["closingIssuesReferences"]["nodes"]
    if len(issues) != 1 or not pr.get("mergeCommit"):
        return None
    issue = issues[0]
    if issue["repository"]["nameWithOwner"] != repo or issue["createdAt"] < MERGED_FROM:
        return None
    text = f"{issue['title']}\n{issue['body'] or ''}".strip()
    if not MIN_TEXT <= len(text) <= MAX_TEXT:
        return None
    clone = ensure_clone(repo)
    merge = pr["mergeCommit"]["oid"]
    try:
        _git(["cat-file", "-e", f"{merge}^{{commit}}"], cwd=clone)
    except subprocess.CalledProcessError:
        _git(["fetch", "--quiet", "origin", merge], cwd=clone)
    base = _git(["rev-parse", f"{merge}^1"], cwd=clone).strip()
    changed = [
        path
        for path in _git(["diff", "--name-only", base, merge], cwd=clone).split()
        if path.endswith(".py") and not is_test_path(path)
    ]
    if not 1 <= len(changed) <= MAX_FILES:
        return None
    patch = _git(["diff", base, merge, "--", *changed], cwd=clone)
    gold = patch_gold(repo, base, patch)
    if not gold["functions"]:
        return None
    task_id = f"{repo.replace('/', '__')}-{pr['number']}"
    return {
        "id": task_id,
        "repo": repo,
        "pr": pr["number"],
        "merged_at": pr["mergedAt"],
        "merge_commit": merge,
        "base_commit": base,
        "issue": issue["number"],
        "issue_created_at": issue["createdAt"],
        "problem_statement": text,
        "gold_lines": gold["lines"],
        "gold_functions": gold["functions"],
    }


def names_changed_file(task: dict[str, Any]) -> bool:
    """The issue text contains a changed file's name, module path or repository path."""
    text = task["problem_statement"]
    return any(
        os.path.basename(path) in text
        or path[:-3].replace("/", ".") in text
        or path in text
        for path in task["gold_lines"]
    )


def mine_b() -> Path:
    """RFC-0005 C3b: C3's rules, minus C3's tasks and issues that name a changed file."""
    if MANIFEST_B.exists():
        raise SystemExit(
            f"{MANIFEST_B.relative_to(REPO_ROOT)} exists; C3b tasks are mined once"
        )
    used = {
        json.loads(line)["id"]
        for line in MANIFEST.read_text().splitlines()
        if line.strip()
    }
    eligible = [
        task
        for repo in CAPS
        for pr in _pull_requests(repo)
        if (task := candidate(repo, pr))
        and task["id"] not in used
        and not names_changed_file(task)
    ]
    eligible.sort(key=lambda t: _order(t["id"]))
    tasks = eligible[:C3B_TASKS]
    print(f"{len(eligible)} eligible, {len(tasks)} taken")
    MANIFEST_B.write_text("".join(json.dumps(t, sort_keys=True) + "\n" for t in tasks))
    return MANIFEST_B


def mine() -> Path:
    """Apply the RFC-0004 rules and caps; refuses to overwrite an existing task list."""
    if MANIFEST.exists():
        raise SystemExit(
            f"{MANIFEST.relative_to(REPO_ROOT)} exists; C3 tasks are mined once"
        )
    tasks: list[dict[str, Any]] = []
    for repo, cap in CAPS.items():
        eligible = [t for pr in _pull_requests(repo) if (t := candidate(repo, pr))]
        eligible.sort(key=lambda t: _order(t["id"]))
        tasks += eligible[:cap]
        print(f"{repo}: {len(eligible)} eligible, {min(cap, len(eligible))} taken")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text("".join(json.dumps(t, sort_keys=True) + "\n" for t in tasks))
    return MANIFEST


def load_fresh(manifest: Path = MANIFEST, name: str = "fresh") -> Suite:
    tasks = [
        json.loads(line) for line in manifest.read_text().splitlines() if line.strip()
    ]
    cases = [
        Case(
            id=t["id"],
            suite=name,
            corpus=f"{t['repo']}@{t['base_commit']}",
            query=t["problem_statement"],
            gold_units={p: 1.0 for p in t["gold_lines"]},
            gold_lines={p: set(v) for p, v in t["gold_lines"].items()},
            gold_functions=[tuple(f) for f in t["gold_functions"]],  # type: ignore[misc]
            meta={"repo": t["repo"], "pr": t["pr"]},
            fixed_split="test",
        )
        for t in tasks
    ]

    def materialize(corpus: str) -> Path:
        repo, commit = corpus.split("@")
        return snapshot(repo, commit)

    return Suite(
        name,
        cases,
        materialize,
        window=50,
        code=True,
        data_sha256={name: hashlib.sha256(manifest.read_bytes()).hexdigest()},
    )
