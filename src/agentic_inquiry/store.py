"""Local source indexing and cited retrieval. Source files are never modified."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

MODEL = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOKENS = 480  # Reserve space within BGE's 512 tokens for special tokens/prefixes.
IDENTITY = {
    "schema": 1,
    "chunking": 1,
    "source_policy": 1,
    "model": MODEL,
    "dimensions": DIMENSIONS,
}
EXCLUDED_DIRS = {
    ".git",
    ".agentic-inquiry",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "vendor",
    "__pycache__",
    ".ssh",
    ".aws",
    ".azure",
    ".gcloud",
    ".claude",
    ".codex",
    ".pi",
    ".agents",
    ".pytest_cache",
    ".ruff_cache",
}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save(path: Path, data: dict) -> None:
    if path.is_symlink():
        raise ValueError(f"Index metadata is a symlink: {path.name}")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _config(db_path: Path) -> dict:
    path = Path(db_path) / "config.json"
    if path.is_symlink():
        raise ValueError("Index configuration is a symlink")
    config = json.loads(path.read_text(encoding="utf-8"))
    if any(config.get(key) != value for key, value in IDENTITY.items()):
        raise ValueError("Incompatible index identity; use a new index directory")
    return config


def _table(db_path: Path, generation: str | None = None):
    import lancedb

    from .library import Library

    if generation is None:
        with Library(db_path).connection() as conn:
            generation = conn.execute(
                "SELECT value FROM metadata WHERE key='generation'"
            ).fetchone()[0]
    db = lancedb.connect(str(Path(db_path) / "index" / generation))
    return db, db.open_table("chunks") if "chunks" in db.list_tables().tables else None


def _embedding_model(db_path: Path, *, download: bool):
    from fastembed import TextEmbedding

    return TextEmbedding(
        MODEL,
        cache_dir=str(db_path / "models"),
        local_files_only=not download,
        threads=2,
        providers=["CPUExecutionProvider"],
    )


RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"


def _reranker(db_path: Path, *, download: bool):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(
        RERANKER,
        cache_dir=str(Path(db_path) / "models"),
        local_files_only=not download,
        threads=2,
        providers=["CPUExecutionProvider"],
        cuda=False,
    )


def prepare_reranker(db_path: Path) -> dict:
    import sys

    lib = _library(db_path)
    print(f"Preparing local reranker {RERANKER} (approximately 80 MB; Apache-2.0)", file=sys.stderr)
    with lib.writer() as conn:
        model = _reranker(lib.path, download=True)
        identity = {
            "model": RERANKER,
            "tokenizer_sha256": _hash(_tokenizer(model).to_str().encode()),
            "query_document_token_limit": 512,
            "artifacts": {
                str(p.relative_to(lib.path / "models")): _hash(p.read_bytes())
                for p in (lib.path / "models").rglob("*")
                if p.is_file() and p.suffix in {".onnx", ".json"}
            },
        }
        conn.execute(
            "INSERT OR REPLACE INTO metadata VALUES('reranker_identity',?)", (json.dumps(identity),)
        )
    return identity


def _tokenizer(model):
    original = model.model.tokenizer
    tokenizer = type(original).from_str(original.to_str())
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def _eligible(relative: str) -> str | None:
    path = Path(relative)
    name = path.name.lower()
    if any(part.lower() in EXCLUDED_DIRS for part in path.parts):
        return "excluded directory"
    if (
        name.startswith(".env")
        or name in {".npmrc", ".pypirc", ".netrc"}
        or (
            path.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini"}
            and re.search(r"(^|[._-])(secrets?|credentials|auth)([._-]|$)", name)
        )
        or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".keystore"}
    ):
        return "private file policy"
    from .ingestion import SUPPORTED_SUFFIXES

    if path.suffix.lower() not in SUPPORTED_SUFFIXES and name not in {
        "dockerfile",
        "makefile",
        "license",
        "notice",
    }:
        return "unsupported file type"
    return None


def _inventory(root: Path, db_path: Path) -> tuple[list[str], list[dict]]:
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if probe.returncode == 0:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                ".",
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError("Git could not enumerate the complete source collection")
        paths = sorted({os.fsdecode(p) for p in result.stdout.split(b"\0") if p})
    else:
        if any((parent / ".git").exists() for parent in (root, *root.parents)):
            raise RuntimeError("Git source inventory failed; no deletion was attempted")
        paths = []

        def failed(error):
            raise RuntimeError("Source directory could not be completely enumerated") from error

        for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
            base = Path(directory)
            if len(base.relative_to(root).parts) > 64:
                raise ValueError("Source inventory exceeds the 64-directory depth limit")
            dirs[:] = [
                name
                for name in dirs
                if name.lower() not in EXCLUDED_DIRS
                and not (base / name).is_symlink()
                and not (base / name).resolve().is_relative_to(db_path)
            ]
            paths.extend(str((base / name).relative_to(root)) for name in files)
            if len(paths) > 100000:
                raise ValueError("Source inventory exceeds 100000 files; register a narrower root")
        paths.sort()
    if len(paths) > 100000:
        raise ValueError("Source inventory exceeds 100000 files; register a narrower root")
    selected, skipped = [], []
    for relative in paths:
        path = root / relative
        reason = _eligible(relative)
        try:
            path.lstat()
        except FileNotFoundError:
            skipped.append({"path": relative, "reason": "missing from working tree"})
            continue
        if path.is_symlink() or any(
            parent.is_symlink() for parent in path.parents if parent.is_relative_to(root)
        ):
            reason = "symlink source"
        if path.resolve().is_relative_to(db_path):
            reason = "index storage"
        if reason:
            skipped.append({"path": relative, "reason": reason})
        else:
            selected.append(relative)
    return selected, skipped


def _bytes(root: Path, relative: str) -> bytes:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Source path must be relative to the collection")
    current = root
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Symlink sources are excluded")
    if not current.resolve().is_relative_to(root):
        raise ValueError("Source escapes the collection")
    if not current.is_file():
        raise FileNotFoundError(relative)
    with current.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Source exceeds the 32 MiB file limit")
    return data


def _chunks(text: str, tokenizer) -> list[tuple[str, int, int]]:
    """Keep original slices and their exact lines, including split long lines."""
    if not text.strip():
        return []
    pieces, offset, line = [], 0, 1
    while offset < len(text):
        end = min(len(text), offset + 4000)
        while len(tokenizer.encode(text[offset:end]).ids) > MAX_TOKENS:
            end = offset + (end - offset) // 2
            if end == offset:
                raise ValueError("Tokenizer cannot encode a source character within its budget")
        if end < len(text):
            # Prefer a paragraph or line boundary without losing whitespace.
            candidate = text.rfind("\n\n", offset, end)
            if candidate <= offset:
                candidate = text.rfind("\n", offset, end)
            if candidate > offset:
                end = candidate + 1
        content = text[offset:end]
        end_line = line + content.count("\n") - int(content.endswith("\n"))
        if content.strip():
            pieces.append((content, line, max(line, end_line)))
        line += content.count("\n")
        offset = end
    return pieces


def _source_id(relative: str) -> str:
    return _hash(relative.encode("utf-8"))


def _freshness(root: Path, row: dict) -> str:
    try:
        if not root.is_dir():
            return "unavailable"
        return "current" if _hash(_bytes(root, row["path"])) == row["source_hash"] else "changed"
    except FileNotFoundError:
        return "missing"
    except (OSError, ValueError):
        return "unavailable"


def _result(row: dict, root: Path, *, state: str = "published") -> dict:
    result = {
        k: v
        for k, v in row.items()
        if k not in {"vector", "fts_text", "location_json"} and not k.startswith("_")
    }
    location = json.loads(row["location_json"])
    result["location"] = location
    result["freshness"] = _freshness(root, row)
    result["publication_state"] = state
    result["citation"] = {
        k: row[k]
        for k in ("id", "collection_id", "project_id", "source_id", "source_version", "source_hash")
    }
    result["citation"]["location"] = location
    for key in ("_relevance_score", "_score", "_distance"):
        if key in row:
            result.update(score=row[key], score_kind=key.removeprefix("_"))
            break
    return result


def _library(db_path: Path, *, rebuilding: bool = False):
    from .library import Library

    lib = Library(db_path)
    if (lib.path / "config.json").exists():
        _config(lib.path)
        with lib.connection() as conn:
            migrated = conn.execute(
                "SELECT value FROM metadata WHERE key='legacy_imported'"
            ).fetchone()
        if not migrated:
            _migrate(lib)
    with lib.connection() as conn:
        identity = conn.execute("SELECT value FROM metadata WHERE key='index_identity'").fetchone()
    if identity and json.loads(identity[0]) != IDENTITY and not rebuilding:
        raise ValueError("Incompatible index identity; run index --rebuild for atomic migration")
    return lib


def _migrate(lib) -> None:
    """Preserve legacy metadata and evidence before adopting publication records."""
    import shutil
    import time
    import uuid

    import lancedb

    config = _config(lib.path)
    with lib.writer() as conn:
        if conn.execute("SELECT value FROM metadata WHERE key='legacy_imported'").fetchone():
            return
        backup_dir = lib.path / "legacy-backup"
        backup_dir.mkdir(exist_ok=True)
        for name in ("config.json", "last-index.json"):
            if (lib.path / name).exists() and not (backup_dir / name).exists():
                shutil.copy2(lib.path / name, backup_dir / name)
        cid, pid = uuid.uuid4().hex, uuid.uuid4().hex
        conn.execute(
            "INSERT INTO collections(id,project_id,name,root,settings) VALUES(?,?,?,?,?)",
            (cid, pid, Path(config["root"]).name, config["root"], "{}"),
        )
        old = lancedb.connect(str(lib.path / "data"))
        if "chunks" in old.list_tables().tables:
            table = old.open_table("chunks")
            rows = table.search().limit(table.count_rows()).to_list()
            for row in rows:
                sid = _hash(f"{cid}:{row['path']}".encode())
                vid = _hash(f"{sid}:{row['source_hash']}:legacy".encode())
                conn.execute(
                    "INSERT OR IGNORE INTO sources VALUES(?,?,?,?,'published',NULL)",
                    (sid, cid, row["path"], vid),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO versions VALUES(?,?,?,?,'published','{}')",
                    (vid, sid, row["source_hash"], time.time()),
                )
                row.update(
                    collection_id=cid,
                    project_id=pid,
                    source_id=sid,
                    source_version=vid,
                    format="text",
                    language="text",
                    location_json=json.dumps(
                        {
                            "kind": "lines",
                            "line_start": row["line_start"],
                            "line_end": row["line_end"],
                        }
                    ),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO chunks VALUES(?,?,?)",
                    (row["id"], vid, json.dumps({k: v for k, v in row.items() if k != "vector"})),
                )
            if rows:
                db, _ = _table(lib.path, "initial")
                new = db.create_table("chunks", data=rows, mode="overwrite")
                from lancedb.index import FTS

                new.create_index("fts_text", config=FTS(), replace=True)
        conn.execute("INSERT INTO metadata VALUES('legacy_imported','true')")


def _policy(relative: str, settings: dict) -> str | None:
    import fnmatch

    if settings.get("include") and not any(
        fnmatch.fnmatch(relative, p) for p in settings["include"]
    ):
        return "collection include policy"
    if any(fnmatch.fnmatch(relative, p) for p in settings.get("exclude", [])):
        return "collection exclude policy"
    return _eligible(relative)


def index(
    root: Path | None,
    db_path: Path,
    *,
    collection: str | None = None,
    project: str | None = None,
    rebuild: bool = False,
) -> dict:
    import time
    import uuid

    from .library import atomic_write

    started = time.monotonic()
    if project is not None and (not isinstance(project, str) or not project.strip()):
        raise ValueError("Project scope must be a nonempty string")
    lib = _library(db_path, rebuilding=rebuild)
    if root is not None:
        root = Path(root).resolve(strict=True)
        existing = lib.collections()
        match = [c for c in existing if c["root"] == str(root) and c["state"] == "active"]
        if not match and existing:
            raise ValueError(
                "Index belongs to another source root; register another collection explicitly"
            )
        c = lib.collection(match[0]["id"]) if match else lib.register(root, project_id=project)
        if isinstance(c["settings"], str):
            c["settings"] = json.loads(c["settings"])
    else:
        if collection is None and project is not None:
            matches = [
                c
                for c in lib.collections()
                if c["state"] == "active" and c["project_id"] == project
            ]
            if len(matches) != 1:
                raise ValueError("Select one registered active collection in the project scope")
            collection = matches[0]["id"]
        c = lib.collection(collection)
        root = Path(c["root"])
    if project is not None and c["project_id"] != project:
        raise ValueError("Selected collection is outside the requested project scope")
    report = {
        "schema_version": 1,
        "collection_id": c["id"],
        "project_id": c["project_id"],
        "changed": [],
        "unchanged": [],
        "removed": [],
        "skipped": [],
        "failed": [],
        "unattempted": [],
        "reduced_coverage": [],
        "complete": False,
        "fts_ready": True,
    }
    with lib.writer() as conn:
        before = {
            r["path"]: dict(r)
            for r in conn.execute(
                "SELECT s.*,v.source_hash,v.extraction FROM sources s LEFT JOIN versions v ON v.id=s.active_version WHERE collection_id=?",
                (c["id"],),
            )
        }
        try:
            if not root.is_dir():
                raise OSError("Registered root unavailable; no deletion attempted")
            selected, report["skipped"] = _inventory(root, lib.path)
            if len(selected) > 100000:
                raise ValueError("Collection exceeds 100000-file inventory bound")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            report["failed"].append({"path": ".", "reason": str(error)})
            conn.execute("INSERT OR REPLACE INTO scans VALUES(?,?)", (c["id"], json.dumps(report)))
            return report
        admitted = []
        for relative in selected:
            reason = _policy(relative, c["settings"])
            if reason:
                report["skipped"].append({"path": relative, "reason": reason})
            else:
                admitted.append(relative)
        selected = admitted
        for skipped in report["skipped"]:
            if skipped["reason"] != "missing from working tree":
                conn.execute(
                    "UPDATE sources SET state='excluded' WHERE collection_id=? AND path=?",
                    (c["id"], skipped["path"]),
                )
        # A committed in-progress record makes interrupted work visible after restart.
        conn.execute("INSERT OR REPLACE INTO scans VALUES(?,?)", (c["id"], json.dumps(report)))
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        generation = conn.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()[0]
        if rebuild:
            from lancedb.index import FTS

            generation = uuid.uuid4().hex
        db, table = _table(lib.path, generation)
        model = tokenizer = None
        model_failure = None
        prepared = []
        from .ingestion import extract
        from .structure import chunk_segments

        try:
            for relative in selected:
                try:
                    data = _bytes(root, relative)
                    source_hash = _hash(data)
                    previous = before.get(relative, {})
                    parser_settings = c["settings"].get("parser", {})
                    settings_digest = _hash(json.dumps(parser_settings, sort_keys=True).encode())
                    if (
                        previous.get("source_hash") == source_hash
                        and previous.get("state") == "published"
                        and not rebuild
                        and json.loads(previous.get("extraction") or "{}").get("settings_digest")
                        == settings_digest
                    ):
                        report["unchanged"].append(relative)
                        prior_extraction = json.loads(previous.get("extraction") or "{}")
                        if not prior_extraction.get("coverage", {}).get("complete", False):
                            report["reduced_coverage"].append(
                                {"path": relative, "coverage": prior_extraction["coverage"]}
                            )
                        continue
                    extraction = extract(relative, data, c["settings"].get("parser", {}))
                    extraction["settings_digest"] = settings_digest
                    if not extraction["coverage"]["complete"]:
                        report["reduced_coverage"].append(
                            {"path": relative, "coverage": extraction["coverage"]}
                        )
                    if extraction["status"] not in {"ok", "empty", "partial"}:
                        raise ValueError(
                            f"Extraction {extraction['status']}: {extraction.get('diagnostic', 'no usable extraction')}"
                        )
                    segments = extraction["segments"]
                    if segments and model is None:
                        if model_failure:
                            report["unattempted"].append(
                                {"path": relative, "reason": model_failure}
                            )
                            continue
                        try:
                            model = _embedding_model(lib.path, download=True)
                            tokenizer = _tokenizer(model)
                        except Exception as error:
                            model_failure = (
                                f"Local embedding model unavailable: {type(error).__name__}"
                            )
                            raise RuntimeError(model_failure) from error
                    chunks = chunk_segments(segments, tokenizer, MAX_TOKENS) if segments else []
                    vectors = (
                        list(model.passage_embed([s["text"] for s in chunks])) if chunks else []
                    )
                    if len(vectors) != len(chunks):
                        raise ValueError("Embedding count does not match source chunks")
                    sid = previous.get("id") or _hash(f"{c['id']}:{relative}".encode())
                    vid = uuid.uuid4().hex
                    records = []
                    for number, (segment, embedding) in enumerate(zip(chunks, vectors)):
                        vector = [float(v) for v in embedding]
                        if len(vector) != DIMENSIONS or not all(math.isfinite(v) for v in vector):
                            raise ValueError("Embedding dimensions or values are invalid")
                        content = segment["text"]
                        records.append(
                            {
                                "id": _hash(f"{vid}:{number}".encode()),
                                "source_id": sid,
                                "source_version": vid,
                                "collection_id": c["id"],
                                "project_id": c["project_id"],
                                "path": relative,
                                "source_hash": source_hash,
                                "line_start": segment.get("line_start", 0),
                                "line_end": segment.get("line_end", 0),
                                "location_json": json.dumps(segment["location"]),
                                "format": extraction["format"],
                                "language": extraction.get("language") or "text",
                                "text": content,
                                "fts_text": content
                                + "\n"
                                + re.sub(r"(?<=[a-z])(?=[A-Z])|_", " ", content),
                                "vector": vector,
                            }
                        )
                    if _hash(_bytes(root, relative)) != source_hash:
                        raise ValueError("Source changed during indexing; retry refresh")
                    if records:
                        if table is None:
                            table = db.create_table("chunks", data=records)
                        else:
                            table.add(records)
                    prepared.append((relative, sid, vid, source_hash, extraction, records))
                except Exception as error:  # noqa: BLE001 - Preserve prior evidence and report per-source failure.
                    report["failed"].append(
                        {"path": relative, "reason": f"{type(error).__name__}: {error}"}
                    )
            if table is not None and table.count_rows():
                from lancedb.index import FTS

                try:
                    table.create_index("fts_text", config=FTS(), replace=True)
                except Exception as error:  # noqa: BLE001 - FTS errors must preserve published sources.
                    report["fts_ready"] = False
                    report["failed"].append({"path": ".", "reason": f"Full-text index: {error}"})
            if report["fts_ready"] and (not rebuild or not report["failed"]):
                for relative, sid, vid, source_hash, extraction, records in prepared:
                    conn.execute(
                        "INSERT INTO sources VALUES(?,?,?,NULL,'pending',NULL) ON CONFLICT(id) DO NOTHING",
                        (sid, c["id"], relative),
                    )
                    conn.execute(
                        "INSERT INTO versions VALUES(?,?,?,?,'published',?)",
                        (
                            vid,
                            sid,
                            source_hash,
                            time.time(),
                            json.dumps(
                                {
                                    k: v
                                    for k, v in extraction.items()
                                    if k not in {"segments", "symbols", "relations"}
                                }
                            ),
                        ),
                    )
                    for row in records:
                        conn.execute(
                            "INSERT INTO chunks VALUES(?,?,?)",
                            (
                                row["id"],
                                vid,
                                json.dumps({k: v for k, v in row.items() if k != "vector"}),
                            ),
                        )
                    for kind in ("symbols", "relations"):
                        for number, item in enumerate(extraction.get(kind, [])):
                            conn.execute(
                                f"INSERT INTO {kind} VALUES(?,?,?)",
                                (_hash(f"{vid}:{kind}:{number}".encode()), vid, json.dumps(item)),
                            )
                    conn.execute(
                        "UPDATE versions SET state='superseded' WHERE source_id=? AND id!=?",
                        (sid, vid),
                    )
                    conn.execute(
                        "UPDATE sources SET active_version=?,state='published',error=NULL WHERE id=?",
                        (vid, sid),
                    )
                    report["changed"].append(relative)
                if rebuild:
                    # Include other collections and historical published evidence in a rebuild.
                    known = {r["id"] for p in prepared for r in p[-1]}
                    extra = [
                        json.loads(r[0])
                        for r in conn.execute("SELECT row_json FROM chunks")
                        if json.loads(r[0])["id"] not in known
                    ]
                    if extra:
                        if model is None:
                            model = _embedding_model(lib.path, download=True)
                            tokenizer = _tokenizer(model)
                        for start in range(0, len(extra), 128):
                            batch = extra[start : start + 128]
                            for row, vector in zip(
                                batch, model.passage_embed([r["text"] for r in batch])
                            ):
                                row["vector"] = [float(v) for v in vector]
                            if table is None:
                                table = db.create_table("chunks", data=batch)
                            else:
                                table.add(batch)
                        table.create_index("fts_text", config=FTS(), replace=True)
                    conn.execute(
                        "UPDATE metadata SET value=? WHERE key='generation'", (generation,)
                    )
                    conn.execute("DELETE FROM metadata WHERE key='needs_rebuild'")
            if not report["failed"] and not report["unattempted"]:
                excluded = {
                    r["path"]
                    for r in report["skipped"]
                    if r["reason"] != "missing from working tree"
                }
                for relative in sorted(set(before) - set(selected) - excluded):
                    conn.execute(
                        "UPDATE sources SET state='deleted' WHERE collection_id=? AND path=?",
                        (c["id"], relative),
                    )
                    if before[relative]["state"] != "deleted":
                        report["removed"].append(relative)
            if report["fts_ready"] and (not rebuild or not report["failed"]):
                conn.execute(
                    "INSERT OR REPLACE INTO metadata VALUES('index_identity',?)",
                    (json.dumps(IDENTITY),),
                )
                if model is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO metadata VALUES('embedding_identity',?)",
                        (
                            json.dumps(
                                {
                                    **IDENTITY,
                                    "tokenizer_sha256": _hash(tokenizer.to_str().encode()),
                                    "query_convention": "FastEmbed query_embed",
                                    "passage_convention": "FastEmbed passage_embed",
                                    "max_chunk_tokens": MAX_TOKENS,
                                    "artifacts": {
                                        str(p.relative_to(lib.path / "models")): _hash(
                                            p.read_bytes()
                                        )
                                        for p in (lib.path / "models").rglob("*")
                                        if p.is_file() and p.suffix in {".onnx", ".json"}
                                    },
                                }
                            ),
                        ),
                    )
            report["complete"] = (
                not report["failed"]
                and not report["unattempted"]
                and not report["reduced_coverage"]
            )
            report["elapsed_seconds"] = time.monotonic() - started
            conn.execute("INSERT OR REPLACE INTO scans VALUES(?,?)", (c["id"], json.dumps(report)))
        finally:
            atomic_write(lib.path / "last-index.json", json.dumps(report, indent=2).encode())
    return report


def _eligible_rows(
    lib,
    conn,
    *,
    collection=None,
    project=None,
    language=None,
    path=None,
    kind=None,
    include_stale=False,
):
    import fnmatch

    rows = []
    coverage = {
        "eligible_sources": 0,
        "stale_sources": [],
        "excluded_sources": 0,
        "unavailable_collections": [],
        "retrieval_complete": True,
    }
    coverage["collections"] = []
    for selected in conn.execute("SELECT * FROM collections ORDER BY name"):
        if (
            selected["state"] != "active"
            or (collection and collection not in {selected["id"], selected["name"]})
            or (project and project != selected["project_id"])
        ):
            continue
        scan = conn.execute(
            "SELECT report FROM scans WHERE collection_id=?", (selected["id"],)
        ).fetchone()
        scan = json.loads(scan[0]) if scan else {"complete": False, "pending": "not indexed"}
        coverage["collections"].append(
            {
                "id": selected["id"],
                "name": selected["name"],
                "scan_complete": scan["complete"],
                "failed": scan.get("failed", []),
                "unattempted": scan.get("unattempted", []),
                "skipped": scan.get("skipped", []),
                "reduced_coverage": scan.get("reduced_coverage", []),
            }
        )
        if not scan["complete"]:
            coverage["retrieval_complete"] = False
        if not Path(selected["root"]).is_dir():
            coverage["unavailable_collections"].append(selected["id"])
            coverage["retrieval_complete"] = False
    query = "SELECT s.*,c.root,c.project_id,c.name,c.settings,v.source_hash,v.state AS version_state FROM sources s JOIN collections c ON c.id=s.collection_id JOIN versions v ON v.id=s.active_version WHERE c.state='active'"
    versions = {}
    for source in conn.execute(query):
        if (collection and collection not in {source["collection_id"], source["name"]}) or (
            project and project != source["project_id"]
        ):
            continue
        settings = json.loads(source["settings"])
        if source["state"] in {"excluded", "deleted"} or _policy(source["path"], settings):
            coverage["excluded_sources"] += 1
            continue
        fresh = _freshness(Path(source["root"]), dict(source))
        if fresh != "current":
            coverage["stale_sources"].append(
                {
                    "collection_id": source["collection_id"],
                    "path": source["path"],
                    "freshness": fresh,
                }
            )
            if not include_stale:
                continue
        coverage["eligible_sources"] += 1
        versions[source["active_version"]] = dict(source)
    for version, source in versions.items():
        for chunk in conn.execute("SELECT row_json FROM chunks WHERE version_id=?", (version,)):
            row = json.loads(chunk[0])
            if language and row["language"] != language:
                continue
            if kind and row["format"] != kind:
                continue
            if path and not fnmatch.fnmatch(row["path"], path):
                continue
            rows.append((row, source))
    return rows, coverage


def search_report(
    db_path: Path,
    query: str,
    limit: int = 8,
    mode: str = "hybrid",
    *,
    rerank: bool = False,
    **filters,
) -> dict:
    if mode not in {"hybrid", "lexical", "vector"} or not 1 <= limit <= 100:
        raise ValueError("Use hybrid, lexical or vector mode and a limit between 1 and 100")
    if not query.strip():
        raise ValueError("Query is empty")
    lib = _library(db_path)
    with lib.connection() as conn:
        conn.execute("BEGIN")
        if conn.execute("SELECT 1 FROM metadata WHERE key='needs_rebuild'").fetchone():
            raise RuntimeError("Restored library requires an index rebuild for search")
        pairs, coverage = _eligible_rows(lib, conn, **filters)
        sources = {row["id"]: source for row, source in pairs}
        report = {
            "schema_version": 1,
            "mode": mode,
            "results": [],
            "coverage": coverage,
            "complete": coverage["retrieval_complete"],
            "candidate_limit": min(400, limit * 8),
            "reranker": RERANKER if rerank else None,
        }
        if not pairs:
            report["empty_reason"] = "No current eligible evidence in the selected scope"
            return report
        generation = conn.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()[0]
        _, table = _table(lib.path, generation)
        if table is None:
            raise RuntimeError("Derived index unavailable; run index --rebuild")
        if mode == "lexical":
            builder = table.search(query, query_type="fts", fts_columns="fts_text")
        else:
            model = _embedding_model(lib.path, download=False)
            if len(_tokenizer(model).encode(query).ids) > MAX_TOKENS:
                raise ValueError("Query exceeds the embedding token budget")
            vector = [float(v) for v in next(iter(model.query_embed(query)))]
            if mode == "vector":
                builder = table.search(vector, query_type="vector")
            else:
                from lancedb.rerankers import RRFReranker

                builder = (
                    table.search(query_type="hybrid", fts_columns="fts_text")
                    .vector(vector)
                    .text(query)
                    .rerank(RRFReranker())
                )
        ids = list(sources)
        if len(ids) > 50000:
            raise ValueError("Scope exceeds 50000 eligible chunks; narrow collection/path filters")
        where = "id IN (" + ",".join("'" + i + "'" for i in ids) + ")"
        ranked = builder.where(where, prefilter=True).limit(report["candidate_limit"]).to_list()
        if rerank and ranked:
            reranker = _reranker(lib.path, download=False)
            pair_tokenizer = _tokenizer(reranker)
            oversized = [
                r["id"] for r in ranked if len(pair_tokenizer.encode(query, r["text"]).ids) > 512
            ]
            report["reranker_omitted"] = oversized
            if oversized:
                report["reranker_applied"] = False
                report["reranker_reason"] = (
                    "A query/document pair exceeds 512 tokens; fusion order retained without truncation"
                )
            else:
                scores = list(reranker.rerank(query, [r["text"] for r in ranked], batch_size=16))
                if len(scores) != len(ranked) or not all(math.isfinite(float(x)) for x in scores):
                    raise ValueError("Invalid local reranker response")
                ranked = [
                    r
                    for _, r in sorted(zip(scores, ranked), key=lambda pair: pair[0], reverse=True)
                ]
                report["reranker_applied"] = True
        ranked.sort(key=lambda r: query in re.findall(r"[A-Za-z_]\w*", r["text"]), reverse=True)
        selected = []
        seen = set()
        per_source = {}
        for row in ranked:
            source = sources[row["id"]]
            key = (row["source_id"], row["text"])
            if key in seen:
                continue
            seen.add(key)
            result = _result(row, Path(source["root"]))
            if result["freshness"] != "current" and not filters.get("include_stale"):
                coverage["retrieval_complete"] = False
                continue
            selected.append(result)
        # Round-robin source diversity while retaining an exact identifier match at the head.
        for row in selected:
            per_source.setdefault(row["source_id"], []).append(row)
        diverse = []
        while per_source and len(diverse) < limit:
            for sid in list(per_source):
                diverse.append(per_source[sid].pop(0))
                if not per_source[sid]:
                    del per_source[sid]
                if len(diverse) == limit:
                    break
        report["results"] = diverse
        report["complete"] = coverage["retrieval_complete"]
        report["candidate_bound_reached"] = len(ranked) == report["candidate_limit"]
        return report


def search(
    db_path: Path, query: str, limit: int = 8, mode: str = "hybrid", **filters
) -> list[dict]:
    return search_report(db_path, query, limit, mode, **filters)["results"]


def read(
    db_path: Path, chunk_id: str, *, project: str | None = None, collection: str | None = None
) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", chunk_id):
        raise ValueError("Invalid chunk ID")
    lib = _library(db_path)
    with lib.connection() as conn:
        conn.execute("BEGIN")
        item = conn.execute(
            "SELECT k.row_json,c.root,c.project_id,c.name,c.state AS collection_state,c.settings,s.state,s.active_version,v.state AS version_state FROM chunks k JOIN versions v ON v.id=k.version_id JOIN sources s ON s.id=v.source_id JOIN collections c ON c.id=s.collection_id WHERE k.id=?",
            (chunk_id,),
        ).fetchone()
        if not item:
            raise FileNotFoundError(chunk_id)
        row = json.loads(item["row_json"])
        if (
            project
            and project != item["project_id"]
            or collection
            and collection not in {row["collection_id"], item["name"]}
        ):
            raise ValueError("Citation outside selected scope")
        if (
            item["collection_state"] != "active"
            or item["state"] == "excluded"
            or _policy(row["path"], json.loads(item["settings"]))
        ):
            raise ValueError("Citation no longer eligible under collection policy")
        return _result(
            row,
            Path(item["root"]),
            state="deleted" if item["state"] == "deleted" else item["version_state"],
        )


def status(db_path: Path) -> dict:
    lib = _library(db_path)
    with lib.connection() as conn:
        sources = [
            dict(s)
            for s in conn.execute(
                "SELECT s.path,c.root,v.source_hash FROM sources s JOIN collections c ON c.id=s.collection_id JOIN versions v ON v.id=s.active_version WHERE s.state='published' AND c.state='active'"
            )
        ]
        stale = [
            {"path": s["path"], "freshness": f}
            for s in sources
            if (f := _freshness(Path(s["root"]), s)) != "current"
        ]
        scans = [json.loads(s[0]) for s in conn.execute("SELECT report FROM scans")]
        return {
            "schema_version": 1,
            "identity": IDENTITY,
            "library": str(lib.path),
            "collections": lib.collections(),
            "sources": len(sources),
            "chunks": conn.execute(
                "SELECT count(*) FROM chunks k JOIN sources s ON s.active_version=k.version_id WHERE s.state='published'"
            ).fetchone()[0],
            "stale_sources": stale,
            "scans": scans,
            "last_index": scans[-1] if scans else None,
            "needs_rebuild": bool(
                conn.execute("SELECT 1 FROM metadata WHERE key='needs_rebuild'").fetchone()
            ),
        }


def remove(
    db_path: Path, source: str, *, collection: str | None = None, preview: bool = False
) -> dict:
    lib = _library(db_path)
    c = lib.collection(collection)
    relative = Path(source)
    if relative.is_absolute():
        relative = relative.relative_to(c["root"])
    if ".." in relative.parts or not relative.parts:
        raise ValueError("Source must name a file inside the indexed collection")
    with lib.writer() as conn:
        found = conn.execute(
            "SELECT id FROM sources WHERE collection_id=? AND path=? AND state!='deleted'",
            (c["id"], relative.as_posix()),
        ).fetchone()
        if not found:
            raise FileNotFoundError(source)
        if not preview:
            conn.execute("UPDATE sources SET state='deleted' WHERE id=?", (found[0],))
    return {
        "removed": relative.as_posix(),
        "source_preserved": True,
        "preview": preview,
        "secure_erasure": False,
    }


def context(
    db_path: Path,
    query: str,
    *,
    budget: int = 2048,
    project: str | None = None,
    include_shared: bool = False,
    **filters,
) -> dict:
    if not 64 <= budget <= 100000:
        raise ValueError("Context budget must be between 64 and 100000")
    report = search_report(db_path, query, limit=32, project=project, **filters)
    from .knowledge import dispatch

    memories = (
        dispatch(
            db_path,
            "memory.recall",
            {"project": project, "query": query, "include_shared": include_shared},
        )
        if project
        else {"records": []}
    )
    # UTF-8 byte count is a conservative, explicitly labeled bound, including citations.
    entries = []
    omitted = []
    used = 0
    material = [{"type": "evidence", "data": r} for r in report["results"]]
    records = memories.get("memories", memories.get("records", []))
    material.extend({"type": "memory", "data": r} for r in records)
    for entry in material:
        cost = len(json.dumps(entry, ensure_ascii=False).encode())
        if used + cost <= budget:
            entries.append(entry)
            used += cost
        else:
            omitted.append(entry["data"].get("id"))
    return {
        "schema_version": 1,
        "entries": entries,
        "budget": budget,
        "used": used,
        "accounting": "UTF-8 bytes as conservative token upper bound; not provider usage",
        "omitted": omitted,
        "coverage": report["coverage"],
        "complete": report["complete"],
        "empty_reason": None
        if entries
        else "No supporting evidence fits the selected scope and budget",
    }
