"""Preview and remove disposable caches while preserving published evidence."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .library import Library, reject_symlinks


def _size(path: Path) -> int:
    def failed(error):
        raise error

    total = 0
    for directory, dirs, files in os.walk(path, followlinks=False, onerror=failed):
        base = Path(directory)
        total += sum((base / name).lstat().st_size for name in files)
        total += sum((base / name).lstat().st_size for name in dirs if (base / name).is_symlink())
    return total


def clean(db_path: Path, *, apply: bool = False, models: bool = False) -> dict:
    """Remove inactive generations and optionally models; defaults to a scope preview."""
    if type(apply) is not bool or type(models) is not bool:
        raise TypeError("apply and models must be explicitly true or false")
    if not (Path(db_path).expanduser() / "records.sqlite3").is_file():
        raise FileNotFoundError("Cache cleanup requires an existing library")
    lib = Library(db_path)
    with lib.writer() as conn:
        if apply:
            if conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal":
                raise ValueError("Cache cleanup cannot exclude active read snapshots in WAL mode")
            # Keep the writer lock while upgrading to a lock that excludes read snapshots.
            conn.commit()
            conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()
        if row is None or not re.fullmatch(r"initial|[a-f0-9]{32}", row[0]):
            raise ValueError("Library has an unrecognized active index generation")
        generation = row[0]
        candidates, retained = [], []
        directory = lib.path / "index"
        reject_symlinks(directory)
        if directory.exists():
            for path in sorted(directory.iterdir()):
                if path.name == generation:
                    reason = "active generation, including any orphan derived rows"
                elif path.is_symlink() or not path.is_dir():
                    reason = "unrecognized cache entry"
                elif not re.fullmatch(r"initial|[a-f0-9]{32}", path.name):
                    reason = "unrecognized generation name"
                else:
                    candidates.append(
                        {
                            "path": str(path.relative_to(lib.path)),
                            "kind": "index",
                            "bytes": _size(path),
                        }
                    )
                    continue
                retained.append({"path": str(path.relative_to(lib.path)), "reason": reason})
        model_path = lib.path / "models"
        reject_symlinks(model_path)
        if model_path.exists():
            if not model_path.is_dir():
                raise ValueError("Model cache must be a directory")
            if models:
                candidates.append({"path": "models", "kind": "models", "bytes": _size(model_path)})
            else:
                retained.append({"path": "models", "reason": "model cleanup was not selected"})
        removed, failed = [], []
        if apply:
            for item in candidates:
                path = lib.path / item["path"]
                try:
                    reject_symlinks(path)
                    shutil.rmtree(path)
                    removed.append(item["path"])
                except (OSError, ValueError) as error:
                    failed.append({"path": item["path"], "error": str(error)})
        return {
            "schema_version": 1,
            "status": "partial" if failed else "ok",
            "complete": not failed,
            "applied": apply,
            "active_generation": generation,
            "candidates": candidates,
            "estimated_bytes": sum(item["bytes"] for item in candidates),
            "removed": removed,
            "retained": retained,
            "failed": failed,
            "active_generation_orphan_rows_removed": 0,
            "orphan_cleanup": "Run index --rebuild for a collection, then cache clean to remove inactive generations",
            "durable_records_preserved": True,
            "authored_pages_preserved": True,
            "backups_preserved": True,
            "secure_erasure": False,
        }
