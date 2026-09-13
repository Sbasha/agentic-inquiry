"""Durable library identity, writer transactions and recoverable snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock

SCHEMA = 1
DDL = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collections(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL UNIQUE,
 root TEXT NOT NULL UNIQUE, settings TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES collections(id),
 path TEXT NOT NULL, active_version TEXT, state TEXT NOT NULL, error TEXT,
 UNIQUE(collection_id,path));
CREATE TABLE IF NOT EXISTS versions(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 source_hash TEXT NOT NULL, created REAL NOT NULL, state TEXT NOT NULL,
 extraction TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks(
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id), row_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_version ON chunks(version_id);
CREATE TABLE IF NOT EXISTS symbols(
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS relations(
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scans(
 collection_id TEXT PRIMARY KEY, report TEXT NOT NULL);
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    reject_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.chmod(temporary, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)


def reject_symlinks(path: Path) -> None:
    path = path.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        # macOS /tmp and /var are platform aliases, so callers resolve the parent first.
        raise ValueError(f"Symlink storage path is not allowed: {path}")


def validate_collection_settings(settings: dict) -> dict:
    if not isinstance(settings, dict):
        raise TypeError("Collection settings must be an object")
    if set(settings) - {"include", "exclude", "parser"}:
        raise ValueError("Collection settings allow include, exclude and parser")
    for key in ("include", "exclude"):
        if key in settings and (
            not isinstance(settings[key], list)
            or any(not isinstance(pattern, str) for pattern in settings[key])
        ):
            raise ValueError("Collection patterns must be lists of strings")
    parser = settings.get("parser", {})
    if not isinstance(parser, dict):
        raise TypeError("Collection parser settings must be an object")
    from .ingestion import _settings

    _settings(parser)
    return settings


class Library:
    def __init__(self, path: Path):
        raw = Path(path).expanduser().absolute()
        if raw.is_symlink():
            raise ValueError("Library root is a symlink")
        self.path = raw.resolve()
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("records.sqlite3", "write.lock", "knowledge", "index", "models"):
            reject_symlinks(self.path / name)
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA:
            raise ValueError("Library uses an unknown newer schema")
        if version == 0:
            with (
                FileLock(self.path / "write.lock", timeout=1, mode=0o600),
                self.connection() as conn,
            ):
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA:
                    raise ValueError("Library uses an unknown newer schema")
                if version == 0:
                    conn.executescript(DDL)
                    conn.execute(
                        "INSERT OR IGNORE INTO metadata VALUES('library_id',?)", (uuid.uuid4().hex,)
                    )
                    conn.execute("INSERT OR IGNORE INTO metadata VALUES('generation','initial')")
                    conn.execute(f"PRAGMA user_version={SCHEMA}")
                    conn.commit()
        (self.path / "knowledge").mkdir(exist_ok=True)

    @contextmanager
    def connection(self):
        reject_symlinks(self.path / "records.sqlite3")
        conn = sqlite3.connect(self.path / "records.sqlite3", timeout=1)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def writer(self):
        reject_symlinks(self.path / "write.lock")
        with FileLock(self.path / "write.lock", timeout=1, mode=0o600), self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def collections(self) -> list[dict]:
        with self.connection() as conn:
            return [
                dict(row) | {"settings": json.loads(row["settings"])}
                for row in conn.execute("SELECT * FROM collections ORDER BY name")
            ]

    def register(
        self,
        root: Path,
        name: str | None = None,
        project_id: str | None = None,
        settings: dict | None = None,
    ) -> dict:
        settings = validate_collection_settings({} if settings is None else settings)
        root = Path(root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Collection root must be a directory")
        with self.writer() as conn:
            row = conn.execute("SELECT * FROM collections WHERE root=?", (str(root),)).fetchone()
            if row:
                if row["state"] != "active":
                    raise ValueError("Collection is detached; explicitly relocate to reattach")
                return dict(row) | {"settings": json.loads(row["settings"])}
            cid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO collections(id,project_id,name,root,settings) VALUES(?,?,?,?,?)",
                (
                    cid,
                    project_id or uuid.uuid4().hex,
                    name or root.name,
                    str(root),
                    json.dumps(settings),
                ),
            )
            row = conn.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
            return dict(row) | {"settings": json.loads(row["settings"])}

    def collection(self, collection: str | None = None) -> dict:
        rows = [
            c
            for c in self.collections()
            if c["state"] == "active" and (collection is None or collection in (c["id"], c["name"]))
        ]
        if len(rows) != 1:
            raise ValueError("Select one registered active collection by name or ID")
        return rows[0]

    def relocate(self, collection: str, root: Path) -> dict:
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Collection root must be a directory")
        with self.writer() as conn:
            row = conn.execute(
                "SELECT * FROM collections WHERE id=? OR name=?", (collection, collection)
            ).fetchone()
            if not row:
                raise FileNotFoundError(collection)
            conn.execute(
                "UPDATE collections SET root=?,state='active' WHERE id=?", (str(root), row["id"])
            )
        return {"collection_id": row["id"], "root": str(root), "reconciliation_required": True}

    def detach(self, collection: str, apply: bool = False) -> dict:
        row = self.collection(collection)
        with self.writer() as conn:
            count = conn.execute(
                "SELECT count(*) FROM sources WHERE collection_id=?", (row["id"],)
            ).fetchone()[0]
            if apply:
                conn.execute("UPDATE collections SET state='detached' WHERE id=?", (row["id"],))
        return {
            "collection_id": row["id"],
            "sources": count,
            "applied": apply,
            "originals_preserved": True,
            "secure_erasure": False,
        }


def backup(path: Path, destination: Path) -> dict:
    lib = Library(path)
    destination = Path(destination).absolute()
    destination = destination.parent.resolve() / destination.name
    reject_symlinks(destination)
    if destination.exists() or destination.is_relative_to(lib.path):
        raise ValueError("Backup destination must be new and outside the library")
    stage = Path(tempfile.mkdtemp(prefix=".ai-backup-", dir=destination.parent))
    try:
        with lib.writer() as conn:
            # A second read connection avoids backing up an active write transaction.
            with lib.connection() as reader, sqlite3.connect(stage / "records.sqlite3") as target:
                reader.backup(target)
            for file in (lib.path / "knowledge").rglob("*"):
                reject_symlinks(file)
            shutil.copytree(lib.path / "knowledge", stage / "knowledge")
            for name in ("config.json",):
                if (lib.path / name).exists():
                    shutil.copy2(lib.path / name, stage / name)
            identity = dict(conn.execute("SELECT key,value FROM metadata"))
            files = {
                p.relative_to(stage).as_posix(): digest(p.read_bytes())
                for p in stage.rglob("*")
                if p.is_file()
            }
            atomic_write(
                stage / "manifest.json",
                json.dumps(
                    {
                        "schema_version": SCHEMA,
                        "identity": identity,
                        "created": time.time(),
                        "files": files,
                        "derived_index_included": False,
                    },
                    indent=2,
                ).encode(),
            )
            os.replace(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {"backup": str(destination), "files": len(files), "derived_index_included": False}


def restore(backup_path: Path, destination: Path) -> dict:
    source = Path(backup_path).resolve(strict=True)
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported backup schema")
    for name, expected in manifest["files"].items():
        file = source / name
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Invalid backup member")
        reject_symlinks(file)
        if digest(file.read_bytes()) != expected:
            raise ValueError(f"Backup checksum mismatch: {name}")
    with sqlite3.connect(f"file:{source / 'records.sqlite3'}?mode=ro", uri=True) as conn:
        if (
            conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA
            or conn.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise ValueError("Invalid backup database")
    target = Path(destination).absolute()
    target = target.parent.resolve() / target.name
    reject_symlinks(target)
    if source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("Restore and backup paths must be disjoint")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".ai-restore-", dir=target.parent))
    prior = None
    try:
        for name in manifest["files"]:
            file = stage / name
            file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, file)
        with sqlite3.connect(stage / "records.sqlite3") as conn:
            conn.execute("INSERT OR REPLACE INTO metadata VALUES('needs_rebuild','true')")
            conn.commit()
        (stage / "knowledge").mkdir(exist_ok=True)
        # Lock stays held until the replacement is fully installed. Callers never wait on it.
        lock = (
            FileLock(target / "write.lock", timeout=1)
            if target.exists()
            else FileLock(target.parent / f".{target.name}.restore.lock", timeout=1)
        )
        with lock:
            if target.exists():
                prior = target.with_name(target.name + ".prior-" + uuid.uuid4().hex)
                os.replace(target, prior)
            try:
                os.replace(stage, target)
            except BaseException:
                if prior:
                    os.replace(prior, target)
                raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {
        "restored": str(target),
        "prior_copy": str(prior) if prior else None,
        "rebuild_required": True,
    }
