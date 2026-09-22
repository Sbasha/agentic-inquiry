"""Temporal analysis service for tracking codebase changes over time."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from agentic_inquiry.config import Config
from agentic_inquiry.database.filters import eq
from agentic_inquiry.storage.facade import StorageFacade

logger = logging.getLogger(__name__)


class TemporalAnalyzer:
    """Analyzes temporal patterns in codebase."""

    def __init__(self, db_manager: StorageFacade, config: Config):
        """Initialize temporal analyzer.

        Args:
            db_manager: StorageFacade instance providing unified storage access
            config: Configuration instance
        """
        # Use StorageFacade directly - it provides advanced_filter method
        # that works across all backends (LanceDB, PostgreSQL, etc.)
        self.db = db_manager
        logger.debug("TemporalAnalyzer initialized with StorageFacade")

        self.config = config

    async def get_recent_activity(
        self, project_id: str, time_range_days: int = 7
    ) -> Dict[str, Any]:
        """
        Get recent file modifications and activity patterns.

        Args:
            project_id: Project identifier
            time_range_days: Number of days to look back

        Returns:
            Recent activity information
        """
        cutoff_date = datetime.now() - timedelta(days=time_range_days)

        # Query chunks with modification timestamps
        recent_chunks = await self._get_recent_chunks(project_id, cutoff_date)

        # Group by file path
        file_activity = self._group_by_file(recent_chunks)

        # Sort by recency
        modified_files = sorted(
            file_activity.values(), key=lambda x: x["last_modified"], reverse=True
        )

        # Identify hot areas (directories with frequent changes)
        hot_areas = self._identify_hot_areas(modified_files)

        # Identify new files (created within time range)
        new_files = await self._identify_new_files(project_id, cutoff_date)

        # Identify stale areas (not modified in long time)
        stale_areas = await self._identify_stale_areas(project_id, cutoff_date)

        return {
            "recent_activity": {
                "time_range": f"last {time_range_days} days",
                "modified_files": modified_files[:50],  # Limit to top 50
                "hot_areas": hot_areas,
                "new_files": new_files,
                "stale_areas": stale_areas,
            }
        }

    async def _get_recent_chunks(
        self, project_id: str, cutoff_date: datetime
    ) -> List[Dict[str, Any]]:
        """Get chunks modified after cutoff date."""
        try:
            # Query chunks with modification timestamps
            # Note: This assumes chunks have last_modified metadata
            chunks = await self.db.advanced_filter(
                table_name="document_chunks",
                filters=eq("project_id", project_id),
                limit=self.config.mcp.query.batch_limit,
            )

            # Filter by date (if last_modified exists)
            recent_chunks = []
            for chunk in chunks:
                last_modified = chunk.get("last_modified")
                if last_modified:
                    try:
                        # Parse ISO format datetime
                        modified_dt = datetime.fromisoformat(
                            last_modified.replace("Z", "+00:00")
                        )
                        if modified_dt >= cutoff_date:
                            recent_chunks.append(chunk)
                    except (ValueError, AttributeError) as e:
                        # S5-002: Log invalid timestamps for debugging
                        logger.debug(
                            "Skipping chunk with invalid timestamp: %s",
                            e
                        )
                        continue

            return recent_chunks

        except Exception as e:
            logger.error("Error getting recent chunks: %s", e)
            return []

    def _group_by_file(self, chunks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Group chunks by file path."""
        file_activity = {}

        for chunk in chunks:
            file_path = chunk.get("file_path", "unknown")
            last_modified = chunk.get("last_modified")

            if file_path not in file_activity:
                file_activity[file_path] = {
                    "path": file_path,
                    "last_modified": last_modified,
                    "chunks_affected": 0,
                    "change_type": "modified",
                    "affected_entities": [],
                }

            file_activity[file_path]["chunks_affected"] += 1

            # Update last_modified if more recent
            if last_modified and (
                not file_activity[file_path]["last_modified"]
                or last_modified > file_activity[file_path]["last_modified"]
            ):
                file_activity[file_path]["last_modified"] = last_modified

            # Collect affected entities
            entity_name = chunk.get("entity_name")
            if entity_name and entity_name not in file_activity[file_path]["affected_entities"]:
                file_activity[file_path]["affected_entities"].append(entity_name)

        return file_activity

    def _identify_hot_areas(
        self, modified_files: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Identify directories with frequent changes."""
        # Group by directory
        dir_activity = {}

        for file_info in modified_files:
            file_path = Path(file_info["path"])
            directory = str(file_path.parent)

            if directory not in dir_activity:
                dir_activity[directory] = {
                    "directory": directory,
                    "change_frequency": 0,
                    "last_change": file_info["last_modified"],
                }

            dir_activity[directory]["change_frequency"] += 1

            # Update last_change if more recent
            if file_info["last_modified"] > dir_activity[directory]["last_change"]:
                dir_activity[directory]["last_change"] = file_info["last_modified"]

        # Sort by frequency
        hot_areas = sorted(
            dir_activity.values(), key=lambda x: x["change_frequency"], reverse=True
        )

        return hot_areas[:10]  # Top 10 hot areas

    async def _identify_new_files(
        self, project_id: str, cutoff_date: datetime
    ) -> List[Dict[str, Any]]:
        """Identify files created within time range."""
        try:
            # Query chunks with creation timestamps
            chunks = await self.db.advanced_filter(
                table_name="document_chunks",
                filters=eq("project_id", project_id),
                limit=self.config.mcp.query.batch_limit,
            )

            # Group by file and get earliest creation time
            new_files: dict[str, Any] = {}
            for chunk in chunks:
                file_path = chunk.get("file_path", "unknown")
                created_at = chunk.get("created_at") or chunk.get("indexed_at")

                if created_at:
                    try:
                        created_dt = datetime.fromisoformat(
                            created_at.replace("Z", "+00:00")
                        )

                        if created_dt >= cutoff_date:
                            if file_path not in new_files or created_dt < datetime.fromisoformat(
                                new_files[file_path]["created"].replace("Z", "+00:00")
                            ):
                                new_files[file_path] = {
                                    "path": file_path,
                                    "created": created_at,
                                    "indexed": True,
                                }
                    except (ValueError, AttributeError) as e:
                        # S5-002: Log parsing failures for debugging
                        logger.debug(
                            "Skipping file with invalid created_at timestamp: %s",
                            e
                        )
                        continue

            return list(new_files.values())

        except Exception as e:
            logger.error("Error identifying new files: %s", e)
            return []

    async def _identify_stale_areas(
        self, project_id: str, cutoff_date: datetime
    ) -> List[Dict[str, Any]]:
        """Identify areas not modified recently."""
        try:
            # Query all chunks
            all_chunks = await self.db.advanced_filter(
                table_name="document_chunks",
                filters=eq("project_id", project_id),
                limit=self.config.mcp.query.batch_limit,
            )

            # Group by directory and find oldest modification
            dir_staleness = {}
            for chunk in all_chunks:
                file_path = Path(chunk.get("file_path", "unknown"))
                directory = str(file_path.parent)
                last_modified = chunk.get("last_modified")

                if directory not in dir_staleness:
                    dir_staleness[directory] = {
                        "directory": directory,
                        "last_change": last_modified,
                        "days_stale": 0,
                    }

                # Track oldest modification in directory
                if last_modified:
                    if (
                        not dir_staleness[directory]["last_change"]
                        or last_modified < dir_staleness[directory]["last_change"]
                    ):
                        dir_staleness[directory]["last_change"] = last_modified

            # Calculate staleness
            now = datetime.now()
            stale_areas = []

            for area in dir_staleness.values():
                if area["last_change"]:
                    try:
                        last_change_str = str(area["last_change"])
                        last_change = datetime.fromisoformat(
                            last_change_str.replace("Z", "+00:00")
                        )
                        days_stale = (now - last_change).days

                        if days_stale > 30:  # Consider stale if > 30 days
                            area["days_stale"] = days_stale
                            stale_areas.append(area)
                    except (ValueError, AttributeError) as e:
                        # S5-002: Log staleness calculation failures
                        logger.debug(
                            "Skipping area with invalid last_change timestamp: %s",
                            e
                        )
                        continue

            # Sort by staleness
            stale_areas.sort(key=lambda x: x["days_stale"], reverse=True)  # type: ignore[arg-type,return-value]

            return stale_areas[:10]  # Top 10 stale areas

        except Exception as e:
            logger.error("Error identifying stale areas: %s", e)
            return []
