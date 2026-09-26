"""Retrieval arms behind one contract: ``index(corpus) -> handle``, ``search(handle, queries)``.

Baselines (``bm25``, ``bm25-paths``, ``dense``, ``hybrid``) share fixed
retrieval units: 50-line windows for code, one line per LOCOMO turn, one file
per LongMemEval session or SciFact abstract. Competitors run from isolated
virtual environments (ADR-0006); ``inquiry`` runs the checked-out package in a
subprocess so each corpus gets a clean process and configuration.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from evals.data import CACHE, Suite
from evals.metrics import Hit

REPO_ROOT = Path(__file__).resolve().parent.parent
# The mcp extra is how Graphify is installed for agent use (graphify-mcp).
GRAPHIFY_SPEC = "graphifyy[mcp]==0.9.68"
DENSE_MODEL = "BAAI/bge-m3"
DENSE_MAX_TOKENS = 512
RRF_K = 60
FUSION_DEPTH = 100
MAX_FILE_BYTES = 1_000_000
INDEX_TIMEOUT_S = 1800
QUERY_TIMEOUT_S = 120
_SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__"}


class Arm(Protocol):
    name: str

    def config(self) -> dict[str, Any]: ...

    def index(self, corpus: str, root: Path, suite: Suite) -> Any: ...

    def search(self, handle: Any, queries: list[str], k: int) -> list[tuple[list[Hit], float]]: ...

    def indexed_paths(self, handle: Any) -> set[str]: ...


# --------------------------------------------------------------------------
# Shared baseline units
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Unit:
    path: str
    start: int
    end: int
    text: str

    def hit(self) -> Hit:
        return Hit(self.path, self.start, self.end, f"== {self.path}:{self.start}-{self.end} ==\n{self.text}", 1)

    def pointer(self) -> Hit:
        return Hit(self.path, self.start, self.end, f"{self.path}:{self.start}-{self.end}", pointer=True)


def corpus_files(root: Path) -> Iterator[tuple[str, str]]:
    """UTF-8 text files under ``root`` (sorted, no VCS dirs, under 1 MB)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "\x00" in text:
                continue
            yield path.relative_to(root).as_posix(), text


@lru_cache(maxsize=2)
def build_units(root: Path, window: int) -> tuple[Unit, ...]:
    units: list[Unit] = []
    for rel, text in corpus_files(root):
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if not lines:
            continue
        step = window if window > 0 else len(lines)
        for begin in range(0, len(lines), step):
            chunk = lines[begin : begin + step]
            if any(line.strip() for line in chunk):
                units.append(Unit(rel, begin + 1, begin + len(chunk), "\n".join(chunk)))
    return tuple(units)


# --------------------------------------------------------------------------
# BM25
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _stemmer():  # type: ignore[no-untyped-def]
    import Stemmer

    return Stemmer.Stemmer("english")


def _bm25_index(units: tuple[Unit, ...]):  # type: ignore[no-untyped-def]
    import bm25s

    retriever = bm25s.BM25()
    tokens = bm25s.tokenize([f"{u.path}\n{u.text}" for u in units], stopwords="en", stemmer=_stemmer(), show_progress=False)
    retriever.index(tokens, show_progress=False)
    return retriever


def _bm25_rank(retriever, query: str, n_units: int, depth: int) -> list[int]:  # type: ignore[no-untyped-def]
    import bm25s

    tokens = bm25s.tokenize([query], stopwords="en", stemmer=_stemmer(), show_progress=False)
    if not tokens.ids or not tokens.ids[0]:
        return []
    ids, scores = retriever.retrieve(tokens, k=min(depth, n_units), show_progress=False, n_threads=1)
    return [int(i) for i, s in zip(ids[0], scores[0]) if s > 0]


class Bm25:
    def __init__(self, pointers: bool = False) -> None:
        self.pointers = pointers
        self.name = "bm25-paths" if pointers else "bm25"

    def config(self) -> dict[str, Any]:
        import bm25s

        return {"impl": f"bm25s=={bm25s.__version__}", "method": "lucene", "stopwords": "en",
                "stemmer": "snowball-english", "display": "pointer" if self.pointers else "text"}

    def index(self, corpus: str, root: Path, suite: Suite) -> Any:
        units = build_units(root, suite.window)
        return units, _bm25_index(units)

    def search(self, handle: Any, queries: list[str], k: int) -> list[tuple[list[Hit], float]]:
        units, retriever = handle
        out = []
        for query in queries:
            t0 = time.perf_counter()
            order = _bm25_rank(retriever, query, len(units), k)
            elapsed = (time.perf_counter() - t0) * 1000
            out.append(([units[i].pointer() if self.pointers else units[i].hit() for i in order], elapsed))
        return out

    def indexed_paths(self, handle: Any) -> set[str]:
        return {u.path for u in handle[0]}


# --------------------------------------------------------------------------
# Dense (BGE-m3) with a persistent embedding cache
# --------------------------------------------------------------------------


# BGE-m3 is served by Ollama (llama.cpp) by default: its memory stays bounded,
# while PyTorch on Metal compiles a graph per input shape and a long run of
# variable-length windows grew one process to 80 GB. EVALS_DENSE_BACKEND=torch
# selects sentence-transformers instead.
DENSE_BACKEND = os.environ.get("EVALS_DENSE_BACKEND", "ollama")
OLLAMA_MODEL = "bge-m3"
OLLAMA_URL = "http://localhost:11434/api/embed"


class _Embedder:
    def __init__(self) -> None:
        self._model: Any = None
        suffix = "" if DENSE_BACKEND == "torch" else f"-{DENSE_BACKEND}"
        path = CACHE / "embeddings" / f"{DENSE_MODEL.replace('/', '__')}-{DENSE_MAX_TOKENS}{suffix}.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vec BLOB)")

    def _load(self) -> Any:
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            device = "mps" if torch.backends.mps.is_available() else "cpu"
            try:
                model = SentenceTransformer(DENSE_MODEL, device=device)
            except (RuntimeError, NotImplementedError):
                model = SentenceTransformer(DENSE_MODEL, device="cpu")
            model.max_seq_length = DENSE_MAX_TOKENS
            self._model = model
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        keys = [hashlib.sha1(t.encode("utf-8", "surrogatepass")).hexdigest() for t in texts]
        found: dict[str, np.ndarray] = {}
        for start in range(0, len(keys), 900):
            batch = keys[start : start + 900]
            marks = ",".join("?" * len(batch))
            for key, blob in self._db.execute(f"SELECT key, vec FROM emb WHERE key IN ({marks})", batch):  # noqa: S608 - placeholders only
                found[key] = np.frombuffer(blob, dtype=np.float16).astype(np.float32)
        missing = sorted({k: t for k, t in zip(keys, texts) if k not in found}.items(), key=lambda kv: len(kv[1]))
        if missing and DENSE_BACKEND == "ollama":
            for start in range(0, len(missing), 64):
                chunk = missing[start : start + 64]
                vectors = _ollama_embed([t for _, t in chunk])
                rows = [(k, v.astype(np.float16).tobytes()) for (k, _), v in zip(chunk, vectors)]
                self._db.executemany("INSERT OR REPLACE INTO emb VALUES (?, ?)", rows)
                self._db.commit()
                for (k, _), v in zip(chunk, vectors):
                    found[k] = v.astype(np.float16).astype(np.float32)
        elif missing:
            model = self._load()
            for start in range(0, len(missing), 256):
                chunk = missing[start : start + 256]
                try:
                    vectors = model.encode([t for _, t in chunk], batch_size=32, normalize_embeddings=True,
                                           show_progress_bar=False, convert_to_numpy=True)
                except RuntimeError as exc:
                    # Unified memory runs out when other jobs hold the GPU; the
                    # same model on CPU gives the same vectors, only slower.
                    if "MPS" not in str(exc):
                        raise
                    model = self._model = model.to("cpu")
                    vectors = model.encode([t for _, t in chunk], batch_size=32, normalize_embeddings=True,
                                           show_progress_bar=False, convert_to_numpy=True)
                rows = [(k, v.astype(np.float16).tobytes()) for (k, _), v in zip(chunk, vectors)]
                self._db.executemany("INSERT OR REPLACE INTO emb VALUES (?, ?)", rows)
                self._db.commit()
                _release_gpu_cache()
                for (k, _), v in zip(chunk, vectors):
                    found[k] = v.astype(np.float16).astype(np.float32)
        return np.stack([found[k] for k in keys]) if keys else np.zeros((0, 1024), dtype=np.float32)


def _ollama_embed(texts: list[str]) -> np.ndarray:
    """Normalized BGE-m3 vectors from a local Ollama, truncated at DENSE_MAX_TOKENS."""
    import urllib.request

    body = json.dumps({"model": OLLAMA_MODEL, "input": texts, "truncate": True,
                       "options": {"num_ctx": DENSE_MAX_TOKENS}}).encode()
    request = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310 - local Ollama
        vectors = np.asarray(json.loads(response.read())["embeddings"], dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


def _release_gpu_cache() -> None:
    """Return cached MPS blocks to the system; PyTorch keeps them otherwise and a
    long run grows to tens of gigabytes of unified memory."""
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except (ImportError, RuntimeError):
        pass


@lru_cache(maxsize=1)
def _embedder() -> _Embedder:
    return _Embedder()


def _dense_rank(matrix: np.ndarray, query: str, depth: int) -> list[int]:
    if matrix.shape[0] == 0:
        return []
    vector = _embedder().encode([query])[0]
    scores = matrix @ vector
    top = np.argsort(-scores, kind="stable")[:depth]
    return [int(i) for i in top]


class Dense:
    name = "dense"

    def config(self) -> dict[str, Any]:
        import sentence_transformers

        impl = (f"ollama {OLLAMA_MODEL}" if DENSE_BACKEND == "ollama"
                else f"sentence-transformers=={sentence_transformers.__version__}")
        return {"model": DENSE_MODEL, "max_tokens": DENSE_MAX_TOKENS, "impl": impl, "similarity": "cosine"}

    def index(self, corpus: str, root: Path, suite: Suite) -> Any:
        units = build_units(root, suite.window)
        return units, _embedder().encode([f"{u.path}\n{u.text}" for u in units])

    def search(self, handle: Any, queries: list[str], k: int) -> list[tuple[list[Hit], float]]:
        units, matrix = handle
        out = []
        for query in queries:
            t0 = time.perf_counter()
            order = _dense_rank(matrix, query, k)
            out.append(([units[i].hit() for i in order], (time.perf_counter() - t0) * 1000))
        return out

    def indexed_paths(self, handle: Any) -> set[str]:
        return {u.path for u in handle[0]}


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[int]:
    """Reciprocal rank fusion; ties break on first appearance."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda item: -scores[item])


class Hybrid:
    name = "hybrid"

    def config(self) -> dict[str, Any]:
        return {"fusion": "rrf", "k": RRF_K, "depth": FUSION_DEPTH, "bm25": Bm25().config(), "dense": Dense().config()}

    def index(self, corpus: str, root: Path, suite: Suite) -> Any:
        units, retriever = Bm25().index(corpus, root, suite)
        _, matrix = Dense().index(corpus, root, suite)
        return units, retriever, matrix

    def search(self, handle: Any, queries: list[str], k: int) -> list[tuple[list[Hit], float]]:
        units, retriever, matrix = handle
        out = []
        for query in queries:
            t0 = time.perf_counter()
            fused = rrf([_bm25_rank(retriever, query, len(units), FUSION_DEPTH), _dense_rank(matrix, query, FUSION_DEPTH)])
            out.append(([units[i].hit() for i in fused[:k]], (time.perf_counter() - t0) * 1000))
        return out

    def indexed_paths(self, handle: Any) -> set[str]:
        return {u.path for u in handle[0]}


# --------------------------------------------------------------------------
# Graphify (live, isolated)
# --------------------------------------------------------------------------

_NODE = re.compile(r"^NODE .*?\[src=(?P<src>[^\]]*?) loc=(?P<loc>[^\]]*?)(?: community=[^\]]*)?\]\s*$")


def parse_graphify(output: str) -> list[Hit]:
    """Every output line in Graphify's order; NODE lines point at ``src:loc``."""
    hits: list[Hit] = []
    for line in output.rstrip("\n").split("\n"):
        match = _NODE.match(line)
        if match and match.group("src"):
            digits = re.search(r"\d+", match.group("loc") or "")
            number = int(digits.group()) if digits else 0
            hits.append(Hit(match.group("src"), number, number, line, pointer=True))
        else:
            hits.append(Hit("", 0, 0, line))
    return hits


def _safe(corpus: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.@-]+", "__", corpus)


class Graphify:
    name = "graphify"
    version = GRAPHIFY_SPEC.split("==")[1]

    def __init__(self) -> None:
        self.venv = CACHE / "venvs" / f"graphifyy-mcp-{self.version}"

    def config(self) -> dict[str, Any]:
        return {"package": GRAPHIFY_SPEC, "build": "graphify update <tree> --no-cluster (AST only, no LLM)",
                "query": "graphify query <q> --budget 100000", "display": "verbatim output lines"}

    def _binary(self) -> Path:
        binary = self.venv / "bin" / "graphify"
        if not binary.exists():
            subprocess.run(["uv", "venv", "--quiet", "--python", "3.12", str(self.venv)], check=True)
            subprocess.run(["uv", "pip", "install", "--quiet", "--python", str(self.venv / "bin" / "python"), GRAPHIFY_SPEC], check=True)
        return binary

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
        env["PATH"] = f"{self.venv / 'bin'}:{env.get('PATH', '')}"
        return env

    def index(self, corpus: str, root: Path, suite: Suite) -> Any:
        target = CACHE / "index" / f"graphify-{self.version}" / _safe(corpus)
        graph = target / "graph.json"
        if graph.exists():
            return target
        binary = self._binary()
        tree = target / "tree"
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        subprocess.run(["cp", "-al", f"{root}/.", str(tree)], check=True)
        t0 = time.perf_counter()
        subprocess.run([str(binary), "update", ".", "--no-cluster"], cwd=tree, env=self._env(), check=True,
                       capture_output=True, timeout=INDEX_TIMEOUT_S)
        (target / "build.json").write_text(json.dumps({"seconds": round(time.perf_counter() - t0, 2)}))
        shutil.move(str(tree / "graphify-out" / "graph.json"), graph)
        shutil.rmtree(tree)
        return target

    def build_seconds(self, handle: Any) -> float | None:
        path = Path(handle) / "build.json"
        return float(json.loads(path.read_text())["seconds"]) if path.exists() else None

    def search(self, handle: Any, queries: list[str], k: int) -> list[tuple[list[Hit], float]]:
        binary = self._binary()
        out = []
        for query in queries:
            t0 = time.perf_counter()
            result = subprocess.run([str(binary), "query", query, "--budget", "100000", "--graph", "graph.json"],
                                    cwd=handle, env=self._env(), capture_output=True, text=True, timeout=QUERY_TIMEOUT_S)
            elapsed = (time.perf_counter() - t0) * 1000
            if result.returncode != 0:
                raise RuntimeError(f"graphify query failed: {result.stderr.strip()[:300]}")
            out.append((parse_graphify(result.stdout), elapsed))
        return out

    def indexed_paths(self, handle: Any) -> set[str]:
        data = json.loads((Path(handle) / "graph.json").read_text())
        return {n.get("source_file") for n in data.get("nodes", []) if n.get("source_file")}


# --------------------------------------------------------------------------
# Agentic Inquiry (checked-out package, subprocess per corpus)
# --------------------------------------------------------------------------


# Packages that shape queries and answers but not what an index contains.
_SEARCH_ONLY = ("agentic_inquiry/search/", "agentic_inquiry/mcp/", "agentic_inquiry/cli/",
                "agentic_inquiry/server/", "agentic_inquiry/integration/")


def _inquiry_code_hash(index_only: bool = False) -> str:
    """Content hash of the runtime package, its config and the worker.

    Hashes file bytes rather than git objects so the cache key is the same
    before and after a commit of identical content. ``index_only`` leaves out
    search-only packages, so a ranking change reuses existing indexes.
    """
    paths = ["agentic_inquiry", "config", "evals/inquiry_worker.py"]
    listed = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "--", *paths], cwd=REPO_ROOT,
                            capture_output=True, text=True, check=True).stdout.split()
    if index_only:
        listed = [name for name in listed if not name.startswith(_SEARCH_ONLY)]
    digest = hashlib.sha256()
    for name in sorted(listed):
        path = REPO_ROOT / name
        if path.is_file() and path.suffix not in {".pyc"}:
            digest.update(name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:16]


class Inquiry:
    """The checked-out package, run on ``config/default.yaml`` or on the file named by
    ``EVALS_INQUIRY_CONFIG`` for ablations; that file's bytes are part of the cache key."""

    name = "inquiry"

    def __init__(self) -> None:
        override = os.environ.get("EVALS_INQUIRY_CONFIG")
        self.config_path = Path(override).resolve() if override else REPO_ROOT / "config" / "default.yaml"
        import yaml

        settings = yaml.safe_load(self.config_path.read_text()) or {}
        code = _inquiry_code_hash().encode()
        # The index depends on everything but search-time code and settings, so
        # ranking ablations (per-file cap, graph channel, rerank) reuse one index.
        index_part = json.dumps({k: v for k, v in settings.items() if k != "search"}, sort_keys=True, default=str)
        self.index_hash = hashlib.sha256(_inquiry_code_hash(index_only=True).encode() + index_part.encode()).hexdigest()[:16]
        self.code_hash = hashlib.sha256(code + self.config_path.read_bytes()).hexdigest()[:16]

    def config(self) -> dict[str, Any]:
        return {"entry": "IndexingPipeline.index_directory + SearchService.hybrid_search",
                "config": str(self.config_path.relative_to(REPO_ROOT)) if self.config_path.is_relative_to(REPO_ROOT)
                else str(self.config_path), "code_hash": self.code_hash, "index_hash": self.index_hash}

    def _worker(self, *args: str, timeout: int) -> None:
        env = dict(os.environ, INQUIRY_CONFIG=str(self.config_path))
        result = subprocess.run([sys.executable, "-m", "evals.inquiry_worker", *args], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=timeout, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"inquiry worker {args[0]} failed: {result.stderr.strip()[-600:]}")

    def index(self, corpus: str, root: Path, suite: Suite) -> Any:
        target = CACHE / "index" / f"inquiry-{self.index_hash}" / _safe(corpus)
        if not (target / "index.json").exists():
            shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True)
            self._worker("index", str(root), str(target), timeout=INDEX_TIMEOUT_S)
        failed = json.loads((target / "index.json").read_text())["result"].get("files_failed", 0)
        if failed:
            print(f"  ! inquiry could not index {failed} file(s) in {corpus}", file=sys.stderr)
        return target, root

    def search(self, handle: Any, queries: list[str], k: int) -> list[tuple[list[Hit], float]]:
        target, root = handle
        # Unique names: search-time ablations share one index directory.
        token = uuid.uuid4().hex
        request = target / f"queries-{token}.json"
        response = target / f"results-{token}.json"
        request.write_text(json.dumps({"queries": queries, "k": k}))
        self._worker("search", str(target), str(root), str(request), str(response),
                     timeout=QUERY_TIMEOUT_S * max(1, len(queries)))
        rows = json.loads(response.read_text())
        request.unlink(missing_ok=True)
        response.unlink(missing_ok=True)
        out = []
        for row in rows:
            hits = []
            for h in row["hits"]:
                start, end = h["start"], h["end"]
                header = f"== {h['path']}:{start}-{end} ==" if start > 0 else f"== {h['path']} =="
                hits.append(Hit(h["path"], start, end, f"{header}\n{h['text']}", 1))
            out.append((hits, row["latency_ms"]))
        return out

    def indexed_paths(self, handle: Any) -> set[str]:
        target, _ = handle
        return set(json.loads((target / "index.json").read_text())["files"])

    def build_seconds(self, handle: Any) -> float | None:
        target, _ = handle
        return float(json.loads((target / "index.json").read_text())["seconds"])


ARMS: dict[str, type] = {"bm25": Bm25, "dense": Dense, "hybrid": Hybrid, "graphify": Graphify, "inquiry": Inquiry}


def make_arm(name: str) -> Arm:
    if name == "bm25-paths":
        return Bm25(pointers=True)
    return ARMS[name]()  # type: ignore[no-any-return]
