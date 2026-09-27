"""Version Manager - Git-linked memory versioning.

Tracks git commit SHA with memories, detects staleness when
referenced files change, and decays confidence accordingly.
"""

import logging
import subprocess

logger = logging.getLogger("ai.daemon.version")


class VersionManager:
    """Git-linked memory versioning and confidence decay."""

    def __init__(self, workspace: str, config: dict) -> None:
        self.workspace = workspace
        versioning = config.get("versioning", {})
        self.decay_per_commit = versioning.get("decay_per_commit", 0.05)
        self.decay_bulk_change = versioning.get("decay_bulk_change", 0.50)
        self.stale_threshold = versioning.get("stale_threshold", 0.3)
        self.bulk_change_files = versioning.get("bulk_change_files", 10)

        self._last_known_commit: str | None = None

    def get_current_commit(self) -> str | None:
        """Get the current HEAD commit SHA."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def get_current_branch(self) -> str | None:
        """Get the current branch name."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def get_changed_files_since(self, since_commit: str) -> list[str]:
        """Get files changed between a commit and HEAD."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since_commit, "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=10,
            )
            if result.returncode == 0:
                return [
                    f.strip() for f in result.stdout.strip().split("\n") if f.strip()
                ]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return []

    def get_commits_since(self, since_commit: str) -> list[dict]:
        """Get commits since a given commit SHA.

        Returns list of {sha, files_changed, is_bulk} dicts.
        """
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"{since_commit}..HEAD",
                    "--format=%H",
                    "--name-only",
                ],
                capture_output=True,
                text=True,
                cwd=self.workspace,
                timeout=10,
            )
            if result.returncode != 0:
                return []

            commits = []
            current_sha = None
            current_files = []

            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    if current_sha:
                        commits.append(
                            {
                                "sha": current_sha,
                                "files_changed": current_files,
                                "is_bulk": len(current_files) >= self.bulk_change_files,
                            }
                        )
                    current_sha = None
                    current_files = []
                elif len(line) == 40 and all(c in "0123456789abcdef" for c in line):
                    if current_sha:
                        commits.append(
                            {
                                "sha": current_sha,
                                "files_changed": current_files,
                                "is_bulk": len(current_files) >= self.bulk_change_files,
                            }
                        )
                    current_sha = line
                    current_files = []
                else:
                    current_files.append(line)

            # Last commit
            if current_sha:
                commits.append(
                    {
                        "sha": current_sha,
                        "files_changed": current_files,
                        "is_bulk": len(current_files) >= self.bulk_change_files,
                    }
                )

            return commits

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def calculate_decay(
        self,
        memory_file_paths: list[str],
        commits: list[dict],
    ) -> float:
        """Calculate confidence decay for a memory based on commits.

        Returns the total decay amount (to subtract from confidence).
        """
        total_decay = 0.0

        for commit in commits:
            changed = set(commit["files_changed"])
            referenced = set(memory_file_paths)

            if changed & referenced:
                if commit["is_bulk"]:
                    total_decay += self.decay_bulk_change
                else:
                    total_decay += self.decay_per_commit

        return min(total_decay, 1.0)

    def create_version_metadata(
        self,
        file_paths: list[str] | None = None,
        entity_names: list[str] | None = None,
    ) -> dict:
        """Create versioning metadata for a new memory."""
        return {
            "git_commit_sha": self.get_current_commit() or "unknown",
            "git_branch": self.get_current_branch() or "unknown",
            "file_paths": file_paths or [],
            "entity_names": entity_names or [],
            "confidence": 1.0,
        }

    def check_staleness(
        self,
        memories: list[dict],
        since_commit: str | None = None,
    ) -> list[dict]:
        """Check memories for staleness and return updated confidence.

        Uses each memory's own git_commit_sha as baseline when available,
        falling back to since_commit or _last_known_commit.
        """
        fallback_commit = since_commit or self._last_known_commit
        if not fallback_commit:
            return memories

        updated = []
        for memory in memories:
            file_paths = memory.get("file_paths", [])
            if not file_paths:
                updated.append(memory)
                continue

            # Use per-memory commit SHA if available, else fallback
            memory_commit = memory.get("git_commit_sha") or fallback_commit
            commits = self.get_commits_since(memory_commit)
            if not commits:
                updated.append(memory)
                continue

            decay = self.calculate_decay(file_paths, commits)
            if decay > 0:
                current_confidence = memory.get("confidence", 1.0)
                new_confidence = max(0.0, current_confidence - decay)
                memory = {**memory, "confidence": new_confidence}
                if new_confidence < self.stale_threshold:
                    memory["stale"] = True
                    logger.debug(
                        "Memory stale (confidence=%.2f): %s",
                        new_confidence,
                        memory.get("content", "")[:60],
                    )

            updated.append(memory)

        return updated

    def update_last_commit(self) -> None:
        """Update the last known commit to HEAD."""
        self._last_known_commit = self.get_current_commit()
